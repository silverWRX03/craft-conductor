"""Remote access: strong passwords only, and phones paired by QR code with limited powers."""

import pytest

from mcsm import qr, webauth
from mcsm.config import ConfigError

from test_hub import login
from test_web import Client

STRONG = "Correct-Horse-9"
AWAY = {"X-Forwarded-For": "203.0.113.9"}  # looks like a request from another device


def test_password_rules():
    assert webauth.strong_password(STRONG)
    for weak in ("short-A1!", "alllowercase-123", "ALLUPPERCASE-123", "NoSpecialChars12"):
        assert not webauth.strong_password(weak)


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
    webui.host = "0.0.0.0"  # as if mcsm had restarted with network access on
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
                       ("/api/auth/change", {"mode": "password", "secret": STRONG + "x"})):
        assert phone.post(path, body)[0] == 403, path
    assert phone.get("/api/servers/alpha/settings")[0] == 403
    assert phone.get("/api/hub/remote")[0] == 403
    devices = ui.get("/api/hub/remote")[1]["devices"]
    assert [d["name"] for d in devices] == ["Sam's phone b"] and "hash" not in devices[0]

    # Removing it (or changing the password) signs it out.
    assert ui.post("/api/hub/devices/remove", {"id": devices[0]["id"]})[0] == 200
    assert phone.get("/api/hub")[0] == 401
    code = ui.post("/api/hub/devices/pair", {"host": host})[1]["url"].split("#pair=")[1]
    assert phone.post("/api/pair", {"code": code, "name": "phone"})[0] == 200
    assert c.post("/api/auth/change", {"mode": "password", "secret": STRONG + "2"})[0] == 200
    assert phone.get("/api/hub")[0] == 401
    with pytest.raises(ConfigError):
        webui.devices.pair("nope", "x", "1.2.3.4", 0)


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
    assert first and first.startswith("Mcsm-") and store.get().temporary
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
    # A strong MCSM_INITIAL_PASSWORD (e.g. for Docker) is used as the real password instead.
    store.path.unlink()
    store._auth = None
    monkeypatch.setenv("MCSM_INITIAL_PASSWORD", "Another-Strong-7")
    assert store.first_run_password() is None and store.get().remote_ready


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
    from mcsm import web
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


def test_the_manual_covers_every_page():
    """A new page in the app needs a section in the user manual (kept with every change)."""
    import re
    from pathlib import Path
    webui = Path(__file__).resolve().parents[1] / "src" / "mcsm" / "webui"
    app, manual = (webui / "app.js").read_text(encoding="utf-8"), (webui / "manual.md").read_text(encoding="utf-8")
    pages = re.findall(r'\["\w+", "([^"]+)"\]', re.search(r"const SERVER_VIEWS = \[(.*?)\];", app, re.S).group(1))
    headings = set(re.findall(r"^##+ (.+)$", manual, re.M))
    missing = [p for p in pages + ["Your servers", "mcsm settings", "Remote access and phones"]
               if not any(h.lower().startswith(p.lower()) for h in headings)]
    assert not missing, f"the user manual (src/mcsm/webui/manual.md) has no section for: {missing}"


def test_the_changelog_has_the_version_being_built():
    """Every version gets its changelog entry (see CLAUDE.md)."""
    from pathlib import Path
    from mcsm import __version__
    changelog = (Path(__file__).resolve().parents[1] / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {__version__} " in changelog, f"CHANGELOG.md has no section for {__version__}"


def test_paired_devices_have_a_role(tmp_path):
    """The owner picks what a paired device may do when making the code: a helper gets the
    everyday controls, a viewer only looks. Phones paired before roles existed are helpers."""
    import time as _time
    from mcsm import webauth
    from mcsm.web import device_allowed
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
    old[0].pop("role")  # paired with an older mcsm
    devices._write(old)
    assert devices.list()[0]["role"] == "helper"
