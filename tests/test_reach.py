"""Reaching a server from outside (reach.py): the way friends join, the port picked for port
forwarding, the whitelist on by default when the server can be reached from the internet (and
the warning when it's turned off), and getting playit.gg's program checked before it runs."""

import json
import random
import re
from pathlib import Path

import pytest

from craft_conductor import config as configmod, reach, tunnel
from craft_conductor.config import ModSpec
from craft_conductor.properties import read_properties, write_properties
from test_web import wait_for

ROOT = Path(__file__).resolve().parents[1]


def login(c):
    assert c.post("/api/login", {"password": "PASSWORD"})[0] == 200


def props(d):
    return read_properties(d.m.server_dir / "server.properties")


def upnp_on(hub, on=True):
    hub._update_hub_file(lambda data: data.__setitem__("upnp", {"enabled": on, "mapped": []}))


# ------------------------------------------------------------------ the port
def test_the_port_picked_is_free_not_25565_and_nobody_elses():
    taken = {30001, 30002}
    picks = iter([25565, 30001, 30002, 30003, 30004])

    class Fixed(random.Random):
        def randint(self, a, b):
            return next(picks)
    free = lambda p: p != 30003  # (another program has 30003)  # noqa: E731
    assert reach.pick_port(taken, free, Fixed()) == 30004
    for _ in range(200):
        p = reach.pick_port({30010}, lambda p: True)
        assert reach.OPEN_RANGE[0] <= p <= reach.OPEN_RANGE[1] and p not in (25565, 30010)
    # nearly everything taken: the one left is found; nothing left: said plainly
    lo, hi = reach.OPEN_RANGE
    assert reach.pick_port(set(range(lo, hi)), lambda p: True, tries=5) == hi
    with pytest.raises(RuntimeError, match="no free port"):
        reach.pick_port(set(range(lo, hi + 1)), lambda p: True, tries=5)


def test_the_hub_never_picks_another_servers_or_its_own_ports(hub_env, monkeypatch):
    hub, _ = hub_env
    alpha = hub.get("alpha")
    write_properties(alpha.m.server_dir / "server.properties", {"server-port": "30500", "enable-rcon": "true", "rcon.port": "30501"})
    taken = hub.taken_ports()
    assert {30500, 30501, hub.share_settings()["port"]} <= taken and hub.ui.httpd.server_address[1] in taken
    queue = iter([30500, 30501, hub.ui.httpd.server_address[1], 30777])
    monkeypatch.setattr(reach.random.SystemRandom, "randint", lambda self, a, b: next(queue), raising=False)
    monkeypatch.setattr("craft_conductor.hub.port_free", lambda p: True)
    assert hub.pick_open_port() == 30777


# ------------------------------------------------------- the whitelist default
@pytest.mark.parametrize("way, closed", [("playit", True), ("forward", True), ("home", False), ("", False)])
def test_a_new_server_reachable_from_the_internet_has_its_whitelist_on(hub_env, way, closed):
    hub, c = hub_env
    login(c)
    body = {"loader": "vanilla", "motd": f"Way {way or 'none'}", "accept_eula": True}
    if way:
        body["reach"] = way
    status, r, _ = c.post("/api/hub/create", body)
    assert status == 200, r
    d = hub.get(r["id"])
    p = props(d)
    assert p["white-list"] == ("true" if closed else "false") and p["enforce-whitelist"] == p["white-list"]
    assert d.m.config.reach_way == way
    assert reach.read_state(d.m.config.state_dir)["guarded"] is True
    port = int(p["server-port"])
    if way == "forward":  # a port Craft Conductor picked for the router: not 25565, nobody else's
        assert reach.in_open_range(port) and port not in hub.taken_ports(exclude=r["id"])
    else:
        assert not reach.in_open_range(port)


def test_router_on_or_a_public_address_makes_new_servers_closed_too(hub_env):
    hub, c = hub_env
    login(c)
    upnp_on(hub)
    sid = c.post("/api/hub/create", {"loader": "vanilla", "motd": "Router", "accept_eula": True, "reach": "home"})[1]["id"]
    assert props(hub.get(sid))["white-list"] == "true"
    upnp_on(hub, False)
    hub._update_hub_file(lambda data: data.__setitem__("share", {"port": 8766, "address": "203.0.113.4"}))
    sid = c.post("/api/hub/create", {"loader": "vanilla", "motd": "Public", "accept_eula": True})[1]["id"]
    assert props(hub.get(sid))["white-list"] == "true"


def test_a_new_server_with_the_whitelist_off_needs_the_warning_seen(hub_env):
    hub, c = hub_env
    login(c)
    body = {"loader": "vanilla", "motd": "Open", "accept_eula": True, "reach": "playit", "properties": {"white-list": False}}
    status, r, _ = c.post("/api/hub/create", body)
    assert status == 400 and reach.WHITELIST_OFF_WARNING in r["error"]
    assert not (hub.home / "servers" / "open").exists()  # (refused before any file is written)
    status, r, _ = c.post("/api/hub/create", {**body, "whitelist_off_ok": True})
    assert status == 200, r
    assert props(hub.get(r["id"]))["white-list"] == "false"


# --------------------------------------------- turning the whitelist off: asked
def test_turning_the_whitelist_off_on_a_reachable_server_asks_every_time(hub_env):
    hub, c = hub_env
    login(c)
    d = hub.get("alpha")
    assert c.post("/api/servers/alpha/players/action", {"action": "whitelist-on"})[0] == 200
    assert c.post("/api/servers/alpha/players/action", {"action": "whitelist-off"})[0] == 200  # (not reachable: no question)
    assert c.post("/api/servers/alpha/reach", {"way": "playit"})[0] == 200
    assert props(d)["white-list"] == "true"  # (reachable now, and made with the rule: turned on by itself)
    for _ in range(2):  # (every time, not once)
        status, r, _ = c.post("/api/servers/alpha/players/action", {"action": "whitelist-off"})
        assert status == 409 and r["confirm"] == "whitelist-off" and r["error"] == reach.WHITELIST_OFF_WARNING
        assert props(d)["white-list"] == "true"
    status, r, _ = c.post("/api/servers/alpha/players/action", {"action": "whitelist-off", "whitelist_off_ok": True})
    assert status == 200, r
    assert props(d)["white-list"] == "false" and reach.read_state(d.m.config.state_dir)["opted_out"] is True
    # Turned off knowingly: it isn't turned on again by itself (the next reason to be reachable either)
    upnp_on(hub)
    assert "alpha" not in hub.whitelist_when_reachable() and props(d)["white-list"] == "false"
    # The server's Settings: the same question
    assert c.post("/api/servers/alpha/players/action", {"action": "whitelist-on"})[0] == 200
    assert reach.read_state(d.m.config.state_dir)["opted_out"] is False
    status, r, _ = c.post("/api/servers/alpha/settings", {"properties": {"white-list": False}})
    assert status == 409 and r["confirm"] == "whitelist-off" and props(d)["white-list"] == "true"
    assert c.post("/api/servers/alpha/settings", {"properties": {"white-list": False}, "whitelist_off_ok": True})[0] == 200
    assert props(d)["white-list"] == "false"


def test_a_server_that_becomes_reachable_later_gets_its_whitelist_on_with_a_notice(hub_env):
    hub, c = hub_env
    login(c)
    d = hub.get("alpha")
    sent = []
    d.m.notifier.send = lambda text, *a, **k: sent.append(text)
    assert props(d)["white-list"] == "false"
    # a playit.gg address saved in its Settings
    assert c.post("/api/servers/alpha/settings", {"tunnel_address": "fox-lake.gl.joinmc.link"})[0] == 200
    assert props(d)["white-list"] == "true"
    assert sent and "whitelist of Alpha is now on" in sent[-1] and "playit.gg address" in sent[-1]


@pytest.mark.parametrize("how", ["router", "public-address", "port-test", "start"])
def test_each_way_of_becoming_reachable_turns_the_whitelist_on(hub_env, how, monkeypatch):
    hub, c = hub_env
    login(c)
    d = hub.get("alpha")
    if how == "router":  # (Router (UPnP) forwards a server set to Open a port on my router)
        configmod.set_value(d.m.config.path, "reach", "way", json.dumps("forward"))
        d.m.reload_config()
        upnp_on(hub)
        monkeypatch.setattr(hub, "upnp_sync", lambda enabled=None: {"enabled": True, "ports": []})
        assert c.post("/api/hub/upnp", {"enabled": True, "accept": True})[0] == 200
    elif how == "public-address":
        assert c.post("/api/hub/share", {"port": hub.share_settings()["port"], "address": "203.0.113.4"})[0] == 200
    elif how == "port-test":
        from craft_conductor import doctor
        monkeypatch.setattr(doctor, "internet_check", lambda http, port, running: doctor.Check("internet", "t", doctor.OK, "reached"))
        assert c.post("/api/servers/alpha/doctor/internet")[0] == 200
        assert reach.read_state(d.m.config.state_dir)["port_test"]["ok"] is True
    else:  # (switched on by hand in hub.json, say: checked again before the server starts)
        configmod.set_value(d.m.config.path, "reach", "way", json.dumps("forward"))
        d.m.reload_config()
        upnp_on(hub)
        hub.before_start(d)
    assert props(d)["white-list"] == "true"


@pytest.mark.parametrize("way", ["home", ""])
def test_router_upnp_doesnt_make_a_home_only_server_reachable(hub_env, way):
    """Router (UPnP) forwards only servers set to Open a port on my router (#201)."""
    hub, c = hub_env
    d = hub.get("alpha")
    if way:
        configmod.set_value(d.m.config.path, "reach", "way", json.dumps(way))
        d.m.reload_config()
    upnp_on(hub)
    assert hub.why_reachable(d) == []
    hub.before_start(d)
    assert props(d)["white-list"] == "false"


def test_servers_from_before_this_are_left_as_they_are(hub_env):
    hub, c = hub_env
    login(c)
    d = hub.get("alpha")
    (d.m.config.state_dir / reach.STATE).unlink()  # (made by an earlier Craft Conductor: no rule)
    assert c.post("/api/servers/alpha/settings", {"tunnel_address": "fox-lake.gl.joinmc.link"})[0] == 200
    assert props(d)["white-list"] == "false"
    # but turning it off while reachable still asks
    assert c.post("/api/servers/alpha/players/action", {"action": "whitelist-on"})[0] == 200
    assert c.post("/api/servers/alpha/players/action", {"action": "whitelist-off"})[0] == 409


def test_the_permission_table_is_unchanged_for_invited_people():
    from craft_conductor import access
    assert access.SERVER_ROUTES[("GET", "/api/reach")] == access.OWNER
    assert access.SERVER_ROUTES[("POST", "/api/reach")] == access.OWNER
    assert access.body_needs("/api/players/action", {"action": "whitelist-off", "whitelist_off_ok": True}) == ["players.moderate"]
    assert access.body_needs("/api/settings", {"whitelist_off_ok": True}, {}) == []
    assert access.body_needs("/api/settings", {"tunnel_address": "x.gl.joinmc.link"}, {}) == [access.OWNER]


# ------------------------------------------------------------ port forwarding
def test_choosing_port_forwarding_picks_the_ports_for_java_and_bedrock(hub_env):
    hub, c = hub_env
    login(c)
    d = hub.get("alpha")
    for mod in ("geyser", "floodgate"):
        configmod.append_mod(d.m.config.path, ModSpec("modrinth", mod, required=False))
    d.m.reload_config()
    cfg = d.m.server_dir / "config" / "Geyser-Fabric" / "config.yml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("bedrock:\n  # where Bedrock players come in\n  address: 0.0.0.0\n  port: 19132\nremote:\n  port: 25565\n")
    status, r, _ = c.post("/api/servers/alpha/reach", {"way": "forward"})
    assert status == 200, r
    tcp, udp = int(props(d)["server-port"]), reach.geyser_port(d.m.server_dir)
    assert reach.in_open_range(tcp) and reach.in_open_range(udp) and tcp != udp
    assert f"TCP port {tcp}" in r["message"] and f"UDP port {udp}" in r["message"]
    assert "remote:\n  port: 25565" in cfg.read_text()  # (only Bedrock's port changed)
    assert r["way"] == "forward" and r["port"] == tcp and r["bedrock"]["port"] == udp
    assert "griefed" in r["router_risks"] and "internet address becomes public" in r["router_risks"]
    # Router (UPnP) and the firewall use them
    assert (tcp, "TCP") in {(p, pr) for p, pr, _ in hub.upnp_wanted()} and (udp, "UDP") in {(p, pr) for p, pr, _ in hub.upnp_wanted()}
    api = hub.ui.api_for("alpha")
    wanted = api._firewall_ports(None)
    assert {"port": udp, "protocol": "UDP"}.items() <= next(w for w in wanted if w.get("protocol") == "UDP").items()
    assert wanted[0]["port"] == tcp
    # Chosen again: the ports stay (they're already fine)
    assert c.post("/api/servers/alpha/reach", {"way": "forward"})[1]["port"] == tcp
    assert c.post("/api/servers/alpha/reach", {"way": "nope"})[0] == 400


def test_a_new_port_needs_the_server_stopped(hub_env):
    hub, c = hub_env
    login(c)
    d = hub.get("alpha")
    assert c.post("/api/servers/alpha/server/start")[0] == 200
    wait_for(lambda: d.state == "running", timeout=30)
    try:
        status, r, _ = c.post("/api/servers/alpha/reach", {"way": "forward"})
        assert status == 409 and "stop the server" in r["error"]
        assert props(d)["server-port"] == "25565"
    finally:
        c.post("/api/servers/alpha/server/stop")
        wait_for(lambda: d.state == "stopped" and not d.job, timeout=30)


def test_geysers_port_is_read_and_written_in_its_bedrock_section_only(tmp_path):
    assert reach.geyser_port(tmp_path) == 19132 and reach.set_geyser_port(tmp_path, 31000) is False
    cfg = tmp_path / "plugins" / "Geyser-Spigot" / "config.yml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("remote:\n  port: 25565\nbedrock:\n  address: 0.0.0.0\n\n  # The port\n  port: 19132\n  clone-remote-port: false\n")
    assert reach.geyser_port(tmp_path) == 19132
    assert reach.set_geyser_port(tmp_path, 31000) is True
    text = cfg.read_text()
    assert reach.geyser_port(tmp_path) == 31000 and "remote:\n  port: 25565" in text
    with pytest.raises(ValueError):
        reach.set_geyser_port(tmp_path, 70000)
    # Windows line endings are kept; a port in the next section isn't Bedrock's.
    cfg.write_bytes(b"bedrock:\r\n  address: 0.0.0.0\r\n  port: 19132\r\nremote:\r\n  port: 25565\r\n")
    assert reach.set_geyser_port(tmp_path, 31001) and cfg.read_bytes() == \
        b"bedrock:\r\n  address: 0.0.0.0\r\n  port: 31001\r\nremote:\r\n  port: 25565\r\n"
    cfg.write_text("bedrock:\n  address: 0.0.0.0\nremote:\n  port: 25565\n")
    assert reach.geyser_port(tmp_path) == 19132 and reach.set_geyser_port(tmp_path, 31000) is False
    # An odd file is read quickly (a pattern over the whole file could take very long: CodeQL).
    import time
    cfg.write_text("bedrock:\n" + "\t\t\n" * 100_000 + "x")
    start = time.monotonic()
    assert reach.geyser_port(tmp_path) == 19132 and time.monotonic() - start < 2


def test_the_firewall_rule_for_bedrock_is_udp():
    from craft_conductor import firewall
    text = firewall.script([{"port": 31000, "label": "Alpha (Bedrock)", "protocol": "UDP"}, {"port": 30500, "label": "Alpha"}])
    assert "-Protocol UDP -LocalPort 31000" in text and "(UDP 31000)" in text
    assert "-Protocol TCP -LocalPort 30500" in text


# ---------------------------------------------------- friends' download port
def test_links_work_for_a_week_at_most(tmp_path):
    from craft_conductor import clientpack
    from craft_conductor.config import ConfigError
    assert configmod.LINK_DAYS == (1, 3, 7) and configmod.DEFAULT_LINK_DAYS == 3
    for old in (30, 0):  # (offered before: read as a week)
        c = configmod._client({"enabled": True, "link_days": old})
        assert c.link_days == 7
    with pytest.raises(ConfigError):
        clientpack.checked_link_days(30)
    assert clientpack.link_expiry(3, now=1000) == 1000 + 3 * 86400


def test_the_router_takes_the_download_port_back_when_no_link_works(hub_env, monkeypatch):
    hub, c = hub_env
    login(c)
    upnp_on(hub)
    synced = []
    monkeypatch.setattr(hub, "upnp_sync", lambda enabled=None: synced.append(bool(hub.share)))
    assert c.post("/api/servers/alpha/client", {"enabled": True})[0] == 200
    wait_for(lambda: hub.share is not None and synced, timeout=15)  # (opened: asked for at once)
    assert c.post("/api/servers/alpha/client/stop-link")[0] == 200
    wait_for(lambda: hub.share is None, timeout=15)
    wait_for(lambda: synced[-1] is False, timeout=15)  # (closed: taken back at once, not at the next renewal)


# --------------------------------------------------- getting playit.gg's program
SHA = "a" * 64


def release(**asset):
    good = {"name": "playit-windows-x86_64-signed.msi", "size": 6070272, "digest": f"sha256:{SHA}",
            "browser_download_url": tunnel.RELEASE_DOWNLOADS + "v1.0.10/playit-windows-x86_64-signed.msi"}
    return {"tag_name": "v1.0.10", "assets": [{"name": "playit-linux-amd64", "digest": "sha256:" + "b" * 64}, {**good, **asset}]}


def test_only_the_signed_installer_from_playits_release_is_chosen():
    a = tunnel.installer_asset(release(), "AMD64")
    assert a == {"version": "1.0.10", "name": "playit-windows-x86_64-signed.msi", "sha256": SHA, "size": 6070272,
                 "url": "https://github.com/playit-cloud/playit-agent/releases/download/v1.0.10/playit-windows-x86_64-signed.msi"}
    with pytest.raises(tunnel.AgentError, match="isn't where it should be"):
        tunnel.installer_asset(release(browser_download_url="https://example.com/playit-windows-x86_64-signed.msi"), "AMD64")
    with pytest.raises(tunnel.AgentError, match="no checksum"):
        tunnel.installer_asset(release(digest=""), "AMD64")
    with pytest.raises(tunnel.AgentError, match="unexpected size"):
        tunnel.installer_asset(release(size=1 << 40), "AMD64")
    with pytest.raises(tunnel.AgentError, match="has no"):
        tunnel.installer_asset(release(name="something-else.msi"), "AMD64")
    with pytest.raises(tunnel.AgentError, match="didn't look right"):
        tunnel.installer_asset({**release(), "tag_name": "../../evil"}, "AMD64")


SIGNED = 'CN=Developed Methods LLC, O=Developed Methods LLC, L=Eugene, S=Oregon, C=US, SERIALNUMBER=E4952832020-4'


@pytest.mark.parametrize("answer, ok", [
    ({"status": "Valid", "subject": SIGNED}, True),
    ({"status": "NotSigned", "subject": ""}, False),
    ({"status": "HashMismatch", "subject": SIGNED}, False),                                   # changed after signing
    ({"status": "Valid", "subject": "CN=Developed Methods LLC, O=Someone Else, C=US"}, False),  # the name, but not the company
    ({"status": "Valid", "subject": 'CN=x, O="Developed Methods LLC, Fake", C=US'}, False),
])
def test_the_installer_runs_only_with_playits_valid_signature(tmp_path, answer, ok):
    seen = []

    def run(args):
        seen.append(args)
        return json.dumps(answer)
    path = tmp_path / "it's here.msi"  # (a quote in the path stays text in PowerShell)
    if ok:
        tunnel.check_signature(path, run=run)
    else:
        with pytest.raises(tunnel.AgentError):
            tunnel.check_signature(path, run=run)
    args = seen[0]
    assert re.search(r"[\\/]System32[\\/]WindowsPowerShell[\\/]v1\.0[\\/]powershell\.exe$", args[0], re.I)  # (by its full path)
    assert args[1:4] == ["-NoProfile", "-NonInteractive", "-EncodedCommand"]
    import base64
    script = base64.b64decode(args[4]).decode("utf-16-le")
    assert "-LiteralPath 'C:" in script or "-LiteralPath '" in script
    assert "it''s here.msi" in script  # (doubled: never ends the string)


def test_a_download_that_fails_a_check_is_never_kept_or_opened(tmp_path, monkeypatch):
    from craft_conductor.http import HashMismatch

    class FakeHttp:
        def __init__(self, body):
            self.body = body
            self.asked = []

        def get_json(self, url, headers=None, cache=True):
            self.asked.append(url)
            return release(digest="sha256:" + __import__("hashlib").sha256(b"the real installer").hexdigest(), size=100)

        def download(self, url, dest, sha256=None, max_bytes=None, progress=None):
            assert url.startswith(tunnel.RELEASE_DOWNLOADS) and max_bytes == 100
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(self.body)
            if __import__("hashlib").sha256(self.body).hexdigest() != sha256:
                dest.unlink()
                raise HashMismatch("sha256 mismatch")
            return dest

    good = FakeHttp(b"the real installer")
    path, version = tunnel.download_installer(good, tmp_path, check=lambda p: None)
    assert good.asked == [tunnel.RELEASE_API] and version == "1.0.10" and path.read_bytes() == b"the real installer"
    with pytest.raises(HashMismatch):
        tunnel.download_installer(FakeHttp(b"something else"), tmp_path / "bad", check=lambda p: None)
    assert not list((tmp_path / "bad").glob("*.msi"))

    def unsigned(p):
        raise tunnel.AgentError("the installer's signature isn't valid")
    with pytest.raises(tunnel.AgentError):
        tunnel.download_installer(good, tmp_path / "unsigned", check=unsigned)
    assert not list((tmp_path / "unsigned").glob("*.msi"))

    opened, checked = [], []
    tunnel.open_installer(path, check=checked.append, popen=lambda args, **kw: opened.append((args, kw)))
    assert checked == [path]  # (checked again right before it's opened)
    args, kw = opened[0]
    assert re.search(r"[\\/]System32[\\/]msiexec\.exe$", args[0], re.I) and args[1:] == ["/i", str(path)]
    assert "shell" not in kw and "CRAFT_CONDUCTOR_CURSEFORGE_API_KEY" not in kw["env"]
    with pytest.raises(tunnel.AgentError):
        tunnel.open_installer(path, check=unsigned, popen=lambda *a, **k: pytest.fail("opened"))


def test_nothing_is_downloaded_until_the_button_is_pressed(hub_env, monkeypatch):
    hub, c = hub_env
    login(c)
    calls = []
    monkeypatch.setattr(tunnel, "download_installer", lambda *a, **k: calls.append(a) or (Path("x.msi"), "1.0.10"))
    monkeypatch.setattr(tunnel, "open_installer", lambda p: calls.append(("open", p)))
    st = c.get("/api/hub/playit")[1]
    assert st["install"]["state"] == "idle" and st["signer"] == "Developed Methods LLC"
    c.get("/api/servers/alpha/reach")
    c.post("/api/servers/alpha/reach", {"way": "playit"})
    assert calls == []
    monkeypatch.setattr(tunnel, "platform", lambda: "windows")
    assert c.post("/api/hub/playit/install", {})[0] == 200
    wait_for(lambda: hub.playit_status()["install"]["state"] == "opened")
    assert calls[-1] == ("open", Path("x.msi"))


def test_the_installer_is_only_opened_from_this_computer():
    from craft_conductor import web
    assert "/api/hub/playit/install" in web.LOCAL_ONLY


# ------------------------------------------------------------- the words
def test_the_page_says_the_same_as_reach_py():
    js = (ROOT / "src" / "craft_conductor" / "webui" / "app.js").read_text(encoding="utf-8")
    block = js[js.index("const REACH_TEXT = {"):js.index("};", js.index("const REACH_TEXT = {"))]
    texts = {k: "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', v)) for k, v in re.findall(r"(\w+): ((?:\"[^\n]*\"(?: \+)?\s*)+)", block)}
    assert texts == {"router": reach.ROUTER_RISKS, "playit": reach.PLAYIT_DOWNSIDES, "whitelist": reach.WHITELIST_OFF_WARNING}


def test_a_link_made_before_links_ended_within_a_week_stops_when_the_new_version_starts(hub_env):
    import time
    from craft_conductor import clientpack
    hub, c = hub_env
    d = hub.get("alpha")
    path = d.m.config.path
    configmod.set_value(path, "client", "enabled", "true")
    configmod.set_value(path, "client", "token", '"' + clientpack.new_token() + '"')
    sent = []
    for old_expiry in ("0", str(int(time.time()) + 30 * 86400)):  # ("until I make new ones", and 30 days)
        configmod.set_value(path, "client", "expires", old_expiry)
        d.m.reload_config()
        d.m.notifier.send = lambda text, *a, **k: sent.append(text)
        hub._end_long_link("alpha", d.m)
        assert not d.m.config.client.link_works(time.time())
        assert "stopped" in sent[-1] and "a week at most" in sent[-1]
    # a link within the week keeps working
    clientpack.make_link(path, 7)
    d.m.reload_config()
    hub._end_long_link("alpha", d.m)
    assert d.m.config.client.link_works(time.time())


def test_the_owners_own_name_goes_on_the_whitelist(hub_env, http):
    hub, c = hub_env
    login(c)
    http.json["https://api.mojang.com/users/profiles/minecraft/Owner_1"] = {"id": "0" * 32, "name": "Owner_1"}
    assert c.post("/api/hub/create", {"loader": "vanilla", "motd": "Bad name", "accept_eula": True,
                                      "reach": "playit", "owner_name": "not a name!"})[0] == 400
    status, r, _ = c.post("/api/hub/create", {"loader": "vanilla", "motd": "Mine", "accept_eula": True,
                                              "reach": "playit", "owner_name": "Owner_1"})
    assert status == 200, r
    d = hub.get(r["id"])
    wait_for(lambda: d.last_job and d.last_job["name"] == "set up server", timeout=30)
    names = [e["name"] for e in json.loads((d.m.server_dir / "whitelist.json").read_text())]
    assert names == ["Owner_1"] and props(d)["white-list"] == "true"


def test_the_before_you_update_note_goes_first_in_the_release_notes():
    import importlib.util
    spec = importlib.util.spec_from_file_location("release_note", ROOT / "packaging" / "release_note.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    text = ("## 1.2.0 (2026-11-01)\n\n**Before you update:** old links stop.\n\n**Added**\n- x\n"
            "- **Before you update:** and this.\n\n## 1.1.0 (2026-10-01)\n\n**Before you update:** not this one.\n")
    assert mod.note("1.2.0", text) == "> **Before you update:** old links stop.\n>\n> **Before you update:** and this."
    assert mod.note("1.1.0", text) == "> **Before you update:** not this one."
    assert mod.note("9.9.9", text) == ""
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    body = workflow[workflow.index("body: |"):]
    assert body.index("steps.before.outputs.text") < body.index("Craft Conductor is in beta")


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows' process list")
def test_playits_tray_icon_alone_isnt_the_agent(monkeypatch):
    import subprocess as sp

    def listing(text):
        return lambda *a, **k: sp.CompletedProcess(a, 0, stdout=text, stderr="")
    monkeypatch.setattr(tunnel.subprocess, "run", listing('"playitd-tray.exe","24100","Console","2","9,300 K"\n'))
    assert tunnel.agent_running() is False
    monkeypatch.setattr(tunnel.subprocess, "run", listing('"playitd-tray.exe","1","Console","2","1 K"\n"playitd.exe","2","Services","0","5 K"\n'))
    assert tunnel.agent_running() is True


def test_banning_this_computers_address_is_refused(hub_env, tmp_path):
    """Through playit.gg every player comes from this computer's address: banning it shuts out everyone."""
    from craft_conductor.players import Players, PlayerError
    hub, c = hub_env
    login(c)
    for ip in ("127.0.0.1", "::1"):
        with pytest.raises(PlayerError, match="this computer's own address"):
            Players(tmp_path).act("ban-ip", ip)
    Players(tmp_path).act("ban-ip", "203.0.113.7")  # (anyone else's still can be)
    assert c.post("/api/servers/alpha/reach", {"way": "playit"})[0] == 200
    status, r, _ = c.post("/api/servers/alpha/players/action", {"action": "ban-ip", "name": "Griefer"})
    assert status == 400 and "Ban the name instead" in r["error"]
