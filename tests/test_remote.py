"""Remote access: strong passwords only, and phones paired by QR code with limited powers."""

import re

import pytest

from craft_conductor import qr, webauth
from craft_conductor.config import ConfigError

from test_hub import login
from test_web import Client

STRONG = "Correct-Horse-9"
AWAY = {"X-Forwarded-For": "203.0.113.9"}  # looks like a request from another device


def test_password_rules():
    assert webauth.strong_password(STRONG)
    for weak in ("short-A1!", "alllowercase-123", "ALLUPPERCASE-123", "NoSpecialChars12"):
        assert not webauth.strong_password(weak)


def test_apply_remote_access_preserves_sessions_and_server(hub_env):
    from test_web import wait_for
    hub, c = hub_env
    login(c)
    assert c.post("/api/auth/change", {"mode": "password", "secret": STRONG})[0] == 200
    assert c.post("/api/servers/alpha/server/start")[0] == 200
    wait_for(lambda: hub.get("alpha").state == "running", timeout=30)
    process = hub.get("alpha").proc
    port = hub.ui.httpd.server_address[1]
    assert c.post("/api/hub/network", {"enabled": True})[0] == 200
    assert hub.ui.host == "127.0.0.1"  # saving during setup doesn't interrupt it
    assert c.post("/api/hub/network/apply")[0] == 200
    assert c.get("/api/hub/remote")[1]["running_on_network"]
    assert hub.ui.httpd.server_address[1] == port
    assert hub.get("alpha").proc is process and process.running
    assert not hub.restart_requested and not hub.stop_requested.is_set()
    assert c.post("/api/hub/network", {"enabled": False})[0] == 200
    # A pending switch back to localhost must not allow a weak password yet.
    assert c.post("/api/auth/change", {"mode": "pin", "secret": "4321"})[0] == 400
    assert c.post("/api/hub/network/apply")[0] == 200
    assert not c.get("/api/hub/remote")[1]["running_on_network"]
    assert c.post("/api/auth/change", {"mode": "pin", "secret": "4321"})[0] == 200


def test_apply_remote_access_restores_listener_on_bind_failure(hub_env, monkeypatch):
    from craft_conductor import web
    hub, c = hub_env
    login(c)
    assert c.post("/api/auth/change", {"mode": "password", "secret": STRONG})[0] == 200
    assert c.post("/api/hub/network", {"enabled": True})[0] == 200
    original = web._Server
    def bind(address, handler):
        if address[0] == "0.0.0.0":
            raise OSError("test bind failure")
        return original(address, handler)
    monkeypatch.setattr(web, "_Server", bind)
    assert c.post("/api/hub/network/apply")[0] == 409
    assert c.get("/api/hub/remote")[1]["running_on_network"] is False
    monkeypatch.setattr(web, "_Server", original)
    assert c.post("/api/hub/network/apply")[0] == 200


def test_qr_code_svg():
    svg = qr.svg("http://192.168.1.20:8765/#pair=abc")
    assert svg.startswith("<svg") and "path" in svg
    with pytest.raises(ValueError):
        qr.QrCode("x" * 5000)


def as_other_device(c):
    other = Client(c.base)
    other.call = (lambda f: (lambda m, p, body=None, headers=None, raw=None: f(m, p, body, {**AWAY, **(headers or {})}, raw)))(other.call)
    return other


def test_remote_access_needs_a_strong_password_and_phones_are_limited(hub_env):
    hub, c = hub_env
    login(c)
    assert c.post("/api/hub/network", {"enabled": True})[0] == 400  # still the default password
    assert c.post("/api/auth/change", {"mode": "pin", "secret": "1234"})[0] == 200
    status, body, _ = c.post("/api/hub/network", {"enabled": True})
    assert status == 400 and "strong password" in body["error"]
    away = as_other_device(c)
    assert away.post("/api/login", {"password": "1234"})[0] == 403  # PINs don't work from elsewhere
    assert c.post("/api/auth/change", {"mode": "password", "secret": STRONG})[0] == 200
    assert c.post("/api/hub/network", {"enabled": True})[0] == 200
    assert c.post("/api/auth/change", {"mode": "pin", "secret": "4321"})[0] == 400  # not while it's on
    assert c.post("/api/auth/change", {"mode": "password", "secret": "weakpassword"})[0] == 400
    assert away.post("/api/login", {"password": STRONG})[0] == 200

    # Pairing a phone: a one-time code shown as a QR code.
    ui = c  # the owner's browser
    info = ui.get("/api/hub/remote")[1]
    assert info["strong"] and info["network_access"] and "12 characters" in info["rules"]
    webui = hub.ui
    webui.host = "0.0.0.0"  # as if craft-conductor had restarted with network access on
    host = info["addresses"][0]["host"] if info["addresses"] else None
    if host is None:  # no network here: pretend there's a home network address
        hub.save_share(hub.share_settings()["port"], "mc.example.com")
        host = "mc.example.com"
    r = ui.post("/api/hub/devices/pair", {"host": host})[1]
    assert r["qr"].startswith("<svg") and "#pair=" in r["url"]
    code = r["url"].split("#pair=")[1]
    phone = as_other_device(Client(c.base))
    assert phone.get("/api/hub")[0] == 401
    status, body, _ = phone.post("/api/pair", {"code": code, "name": "Sam's phone <b>"})
    assert status == 200 and body["name"] == "Sam's phone b"
    assert phone.post("/api/pair", {"code": code, "name": "again"})[0] == 400  # used up
    assert phone.get("/api/hub")[1]["device"] == "Sam's phone b"
    assert phone.get("/api/servers/alpha/status")[0] == 200
    assert phone.post("/api/servers/alpha/backups/create", {"name": "from phone"})[0] == 200
    for path, body in (("/api/servers/alpha/command", {"command": "op someone"}), ("/api/servers/alpha/settings", {}),
                       ("/api/servers/alpha/mods/add", {"id": "x"}), ("/api/hub/network", {"enabled": False}),
                       ("/api/hub/network/apply", {}),
                       ("/api/auth/change", {"mode": "password", "secret": STRONG + "x"})):
        assert phone.post(path, body)[0] == 403, path
    assert phone.get("/api/servers/alpha/settings")[0] == 403
    assert phone.get("/api/hub/remote")[0] == 403
    devices = ui.get("/api/hub/remote")[1]["devices"]
    assert [d["name"] for d in devices] == ["Sam's phone b"] and "hash" not in devices[0]

    # Removing it (or changing the password) signs it out.
    assert ui.post("/api/hub/devices/remove", {"id": devices[0]["id"]})[0] == 200
    assert phone.get("/api/hub")[0] == 401
    # (an iPhone's Home Screen app is paired by typing the code the computer shows)
    r = ui.post("/api/hub/devices/pair", {"host": host})[1]
    assert r["url"].endswith("#pair=" + r["code"]) and r["secure"] is False
    typed = r["code"].replace("-", " ").lower()
    assert phone.post("/api/pair", {"code": typed, "name": "phone"})[0] == 200
    assert c.post("/api/auth/change", {"mode": "password", "secret": STRONG + "2"})[0] == 200
    assert phone.get("/api/hub")[0] == 401
    with pytest.raises(ConfigError):
        webui.devices.pair("nope", "x", "1.2.3.4", 0)


def test_pairing_codes_can_be_typed(tmp_path):
    """Short, with letters that can't be mixed up; typed in any case, with or without the dashes,
    and O or I/L for 0 or 1 still work."""
    devices = webauth.Devices(tmp_path)
    code = devices.new_code(1000.0)
    assert re.fullmatch(r"[2-9A-HJKMNP-Z]{4}-[2-9A-HJKMNP-Z]{4}-[2-9A-HJKMNP-Z]{4}", code)
    assert webauth.pair_code(" abcd-efgh o1il ") == "ABCDEFGH0111"
    devices.pair(code.lower().replace("-", ""), "Phone", "10.0.0.5", 1001.0)
    with pytest.raises(ConfigError):  # (once)
        devices.pair(code, "Phone", "10.0.0.5", 1002.0)
    late = devices.new_code(1000.0)
    with pytest.raises(ConfigError):  # (five minutes)
        devices.pair(late, "Phone", "10.0.0.5", 1000.0 + webauth.PAIR_SECONDS + 1)
    assert len({devices.new_code(1000.0) for _ in range(50)}) == 50


def test_help_images_and_app_manifest_are_served(hub_env):
    hub, c = hub_env
    for path, ctype in (("/help-network.svg", "image/svg+xml"), ("/help-router.svg", "image/svg+xml"),
                        ("/manifest.webmanifest", "application/manifest+json")):
        status, _, headers = c.get(path)
        assert status == 200 and headers["Content-Type"] == ctype, path


def test_headless_first_sign_in_from_another_device(hub_env, monkeypatch):
    """No screen: a random one-time password (shown on the console) that can only be replaced."""
    hub, c = hub_env
    store = hub.ui.store
    store.path.unlink(missing_ok=True)
    store._auth = None
    first = store.first_run_password()
    assert first and first.startswith("Craft-Conductor-") and store.get().temporary
    assert (store.path.parent / "first-password.txt").read_text().count(first) == 1
    hub.web.host = "0.0.0.0"
    away = as_other_device(Client(c.base))
    assert away.post("/api/login", {"password": "PASSWORD"})[0] == 401
    assert away.post("/api/login", {"password": first})[0] == 200
    assert away.get("/api/hub")[0] == 200
    assert away.get("/api/servers/alpha/status")[0] == 403  # only choosing a password until then
    assert away.post("/api/auth/change", {"mode": "pin", "secret": "1234"})[0] == 400
    assert away.post("/api/auth/change", {"mode": "password", "secret": STRONG})[0] == 200
    assert away.get("/api/servers/alpha/status")[0] == 200
    assert not (store.path.parent / "first-password.txt").exists()
    # A strong CRAFT_CONDUCTOR_INITIAL_PASSWORD (e.g. for Docker) is used as the real password instead.
    store.path.unlink()
    store._auth = None
    monkeypatch.setenv("CRAFT_CONDUCTOR_INITIAL_PASSWORD", "Another-Strong-7")
    assert store.first_run_password() is None and store.get().remote_ready


def test_a_refused_request_is_answered_not_reset(hub_env):
    """A request refused before its body is read still gets its answer: on Windows, closing a
    connection with the body unread reset it, and the page saw "connection reset" instead."""
    hub, c = hub_env
    proxied = Client(c.base)
    body = {"padding": "x" * 20_000}
    for _ in range(50):
        status, r, _ = proxied.call("POST", "/api/auth/reset-local", body, headers={"Via": "1.1 nginx"})
        assert status == 403 and "own computer" in r["error"]
    for _ in range(10):  # (and one answered without needing its body at all)
        login(c)
        assert c.post("/api/logout", body)[0] == 200


@pytest.mark.parametrize("header", [{"Via": "1.1 nginx"}, {"Tailscale-User-Login": "someone@example.com"},
                                    {"X-Forwarded-Host": "mc.example.com"}, {"Host": "mc.example.com"}])
def test_a_proxy_on_this_computer_isnt_local(hub_env, header):
    """Through a reverse proxy or tunnel, visitors aren't at the server's computer: no PIN
    sign-in for them, and no password reset."""
    hub, c = hub_env
    hub.web.allowed_hosts = ["mc.example.com"]
    login(c)
    assert c.post("/api/auth/change", {"mode": "pin", "secret": "1234"})[0] == 200
    proxied = Client(c.base)
    assert proxied.call("GET", "/api/auth", headers=header)[1]["local"] is False
    assert proxied.call("POST", "/api/login", {"password": "1234"}, headers=header)[0] == 403
    assert proxied.call("POST", "/api/auth/reset-local", {}, headers=header)[0] == 403
    assert c.get("/api/auth")[1]["local"] is True  # a browser on this computer still is


def test_idle_and_excess_connections_are_dropped(hub_env, monkeypatch):
    import socket
    import time
    from craft_conductor import web
    hub, c = hub_env
    host, port = c.base.split("//")[1].split(":")
    server = hub.ui.httpd
    monkeypatch.setattr(server, "_slots", __import__("threading").BoundedSemaphore(2))
    idle = [socket.create_connection((host, int(port))) for _ in range(2)]  # say nothing
    time.sleep(0.3)
    extra = socket.create_connection((host, int(port)))
    extra.settimeout(3)
    assert extra.recv(1) == b""  # closed straight away: no free slot
    for s in idle + [extra]:
        s.close()
    assert web.RequestHandler.timeout == web.REQUEST_TIMEOUT > 0


def test_page_files_are_cached_by_the_browser(hub_env):
    hub, c = hub_env
    status, _, headers = c.get("/app.js")
    etag = headers["ETag"]
    assert status == 200 and etag and headers["Cache-Control"] == "no-cache"
    status, body, _ = c.call("GET", "/app.js", headers={"If-None-Match": etag})
    assert status == 304 and not body  # unchanged: nothing sent again


def test_the_user_manual_is_in_the_app(hub_env):
    hub, c = hub_env
    status, body, headers = c.get("/manual.md")
    assert status == 200 and headers["Content-Type"].startswith("text/markdown")
    for section in ("## Creating a server", "## Friends: playing with friends", "## For friends: joining a server", "## Troubleshooting"):
        assert section in body
    import re
    assert all(url.startswith("https://") for url in re.findall(r"\]\(([^)]+)\)", body))  # links work from the page


def pair_phone(hub, owner, role):
    """A paired phone with the given role, as seen from another device."""
    hub.ui.host = "0.0.0.0"  # as if Craft Conductor had restarted with network access on
    hub.save_share(hub.share_settings()["port"], "mc.example.com")
    r = owner.post("/api/hub/devices/pair", {"host": "mc.example.com", "role": role})[1]
    phone = as_other_device(Client(owner.base))
    assert phone.post("/api/pair", {"code": r["url"].split("#pair=")[1], "name": f"a {role}"})[0] == 200
    assert phone.get("/api/hub")[1]["role"] == role
    return phone


def test_kick_whitelist_and_broadcast_follow_the_phone_roles(hub_env):
    """The Dashboard's Kick, Whitelist and Broadcast: a helper's phone may use them (and the Dashboard
    keeps working there), a viewer's may only look. The server refuses a viewer, not just the page."""
    from test_web import wait_for
    hub, c = hub_env
    login(c)
    assert c.post("/api/auth/change", {"mode": "password", "secret": STRONG})[0] == 200
    assert c.post("/api/hub/network", {"enabled": True})[0] == 200
    helper, viewer = pair_phone(hub, c, "helper"), pair_phone(hub, c, "viewer")
    assert c.post("/api/servers/alpha/server/start")[0] == 200
    wait_for(lambda: hub.get("alpha").state == "running", timeout=30)
    hub.get("alpha")._on_line("[12:00:00] [Server thread/INFO]: Steve joined the game")

    base = "/api/servers/alpha"
    writes = [("/players/action", {"action": "kick", "name": "Steve"}), ("/players/action", {"action": "whitelist-on"}),
              ("/players/action", {"action": "whitelist-add", "name": "Sam"}), ("/players/action", {"action": "whitelist-remove", "name": "Sam"}),
              ("/players/action", {"action": "whitelist-off"}), ("/broadcast", {"message": "hello everyone"})]
    for path, body in writes:
        status, r, _ = viewer.post(base + path, body)
        assert status == 403 and "can't do that" in r["error"], (path, body)
    # (and with a bad message too: the role is checked before anything else is looked at)
    assert viewer.post(base + "/broadcast", {"message": "a\nb"})[0] == 403
    for path, body in writes:
        assert helper.post(base + path, body)[0] == 200, (path, body)
    assert helper.post(base + "/broadcast", {"message": "a\nb"})[0] == 400     # (the same rules as the console's)
    lines = c.get(base + "/console?since=0")[1]["lines"]
    assert any(x["text"] == "> say hello everyone" for x in lines) and not any("say a" in x["text"] for x in lines)

    # What the Dashboard reads works for both, phones included.
    for phone in (helper, viewer):
        for path in ("/status", "/players/online?whitelist=1", "/console?since=0", "/events?since=0", "/players"):
            assert phone.get(base + path)[0] == 200, path
    # The console is still the owner's: a phone can't type commands, so the page doesn't offer "Message" there.
    assert helper.post(base + "/command", {"command": "say hi"})[0] == 403


def test_broadcast_is_an_everyday_control_for_phones():
    from craft_conductor.web import device_allowed
    assert device_allowed("POST", "/api/broadcast", "helper") and not device_allowed("POST", "/api/broadcast", "viewer")
    for path in ("/api/players/action", "/api/broadcast"):
        assert not device_allowed("POST", path, "viewer")
    assert not device_allowed("POST", "/api/command", "helper")
    assert device_allowed("GET", "/api/players/online", "viewer") and device_allowed("GET", "/api/players/online", "helper")


def test_the_manual_covers_every_page():
    """A new page in the app needs a section in the user manual (kept with every change)."""
    import re
    from pathlib import Path
    webui = Path(__file__).resolve().parents[1] / "src" / "craft_conductor" / "webui"
    app, manual = (webui / "app.js").read_text(encoding="utf-8"), (webui / "manual.md").read_text(encoding="utf-8")
    pages = re.findall(r'\["\w+", "([^"]+)"\]', re.search(r"const SERVER_VIEWS = \[(.*?)\];", app, re.S).group(1))
    headings = set(re.findall(r"^##+ (.+)$", manual, re.M))
    missing = [p for p in pages + ["Your servers", "Craft Conductor settings", "Remote access and phones"]
               if not any(h.lower().startswith(p.lower()) for h in headings)]
    assert not missing, f"the user manual (src/craft_conductor/webui/manual.md) has no section for: {missing}"


def test_the_changelog_has_the_version_being_built():
    """Every version gets its changelog entry (see CLAUDE.md)."""
    from pathlib import Path
    from craft_conductor import __version__
    changelog = (Path(__file__).resolve().parents[1] / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {__version__} " in changelog, f"CHANGELOG.md has no section for {__version__}"


def test_paired_devices_have_a_role(tmp_path):
    """The owner picks what a paired device may do when making the code: a helper gets the
    everyday controls, a viewer only looks. Phones paired before roles existed are helpers."""
    import time as _time
    from craft_conductor import webauth
    from craft_conductor.web import device_allowed
    devices = webauth.Devices(tmp_path)
    now = _time.time()
    token, viewer = devices.pair(devices.new_code(now, "viewer"), "Sam's laptop", "10.0.0.5", now)
    assert viewer["role"] == "viewer" and devices.find(token, now)["role"] == "viewer"
    _, helper = devices.pair(devices.new_code(now), "Phone", "10.0.0.6", now)
    assert helper["role"] == "helper"
    with pytest.raises(webauth.ConfigError):
        devices.new_code(now, "owner")  # not a role a code can give
    assert not device_allowed("POST", "/api/server/stop", "viewer") and device_allowed("POST", "/api/logout", "viewer")
    assert device_allowed("GET", "/api/status", "viewer") and not device_allowed("GET", "/api/settings", "viewer")
    assert device_allowed("POST", "/api/server/stop", "helper") and not device_allowed("POST", "/api/settings", "helper")
    old = devices._read()
    old[0].pop("role")  # paired with an older craft-conductor
    devices._write(old)
    assert devices.list()[0]["role"] == "helper"


def test_a_phone_pairs_at_tailscale_when_serve_was_already_on(hub_env, monkeypatch):
    """Tailscale Serve was on from before, so Use Tailscale for the phone app was never pressed: the
    pairing link opened at the ts.net address answered "This address isn't allowed"."""
    from craft_conductor import tailscale
    hub, c = hub_env
    login(c)
    assert c.post("/api/auth/change", {"mode": "password", "secret": STRONG})[0] == 200
    name = "laptop.tail1234.ts.net"
    monkeypatch.setattr(tailscale, "status", lambda port: {"installed": True, "running": True, "name": name, "serving": True})
    at_tailscale = as_other_device(Client(c.base))
    at_tailscale.call = (lambda f: (lambda m, p, body=None, headers=None, raw=None: f(m, p, body, {**(headers or {}), "Host": name}, raw)))(at_tailscale.call)
    assert at_tailscale.get("/")[0] == 421  # (not offered yet: still refused)
    r = c.post("/api/hub/devices/pair", {"host": name})[1]
    assert r["secure"] and r["url"].startswith(f"https://{name}/#pair=")
    assert at_tailscale.get("/")[0] == 200
    assert at_tailscale.post("/api/pair", {"code": r["code"], "name": "phone"})[0] == 200
    assert name in hub.web.allowed_hosts and name in hub._hub_file()["web"]["allowed_hosts"]  # (after a restart too)
