"""The web UI's API, served by a real daemon running the fake Minecraft server."""

import json

from craft_conductor import __version__
import threading
import time
import urllib.error
import urllib.request

import pytest

from craft_conductor.config import ModSpec
from craft_conductor.daemon import Daemon
from craft_conductor.players import offline_uuid

from test_manager import manager, update


class Client:
    def __init__(self, base):
        # (Windows tries localhost as ::1 first and waits 2 seconds a request before 127.0.0.1)
        self.base = base.replace("://localhost:", "://127.0.0.1:")
        self.cookie = None

    def call(self, method, path, body=None, headers=None, raw=None):
        h = {"X-CRAFT-CONDUCTOR": "1", **(headers or {})}
        if self.cookie:
            h["Cookie"] = self.cookie
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        if body is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                if "Set-Cookie" in r.headers:
                    self.cookie = r.headers["Set-Cookie"].split(";")[0]
                raw_body = r.read()
                ctype = r.headers.get("Content-Type", "")
                if "json" in ctype:
                    return r.status, json.loads(raw_body), r.headers
                return r.status, raw_body.decode() if ctype.startswith("text/") else raw_body, r.headers
        except urllib.error.HTTPError as e:
            raw_body = e.read() or b"{}"
            try:
                return e.code, json.loads(raw_body), e.headers
            except ValueError:
                return e.code, raw_body.decode(), e.headers

    def get(self, path):
        return self.call("GET", path)

    def post(self, path, body=None, **kw):
        return self.call("POST", path, body if body is not None else {}, **kw)


def wait_for(fn, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if fn():
            return True
        time.sleep(0.1)
    raise AssertionError("condition not met in time")


@pytest.fixture
def running(make_config, http, modrinth):
    yield from _running(make_config, http, modrinth, "hunter2hunter2")


@pytest.fixture
def running_default(make_config, http, modrinth):
    """No password in craft-conductor.toml: sign-in is chosen in the web UI."""
    yield from _running(make_config, http, modrinth, "")


def _running(make_config, http, modrinth, password):
    modrinth.project("AAA", "goodmod", "Good Mod")
    modrinth.version("AAA", "1.0", ["1.21.1"])
    modrinth.project("BBB", "othermod", "Other Mod")
    modrinth.version("BBB", "1.0", ["1.21.1"])
    cfg = make_config([ModSpec("modrinth", "goodmod")])
    cfg.web.port = 0
    cfg.web.password = password
    m = manager(cfg, http, ["1.21.1"])
    assert update(m).ok
    d = Daemon(m, tick=0.1)
    t = threading.Thread(target=d.run, kwargs={"web": True}, daemon=True)
    t.start()
    wait_for(lambda: getattr(d, "ui", None) is not None and d.state == "running")
    client = Client(d.ui.url.rstrip("/"))
    yield d, client, cfg
    d.stop_requested.set()
    t.join(20)


def login(c):
    status, body, _ = c.post("/api/login", {"password": "hunter2hunter2"})
    assert status == 200, body


def test_auth_and_csrf(running):
    d, c, cfg = running
    assert c.get("/api/status")[0] == 401
    assert c.post("/api/login", {"password": "nope"})[0] == 401
    status, _, _ = c.call("POST", "/api/login", {"password": "hunter2hunter2"}, headers={"X-CRAFT-CONDUCTOR": ""})
    assert status == 403  # no CSRF header
    login(c)
    assert c.get("/api/status")[0] == 200
    # State-changing calls need the header even with a valid session.
    assert c.call("POST", "/api/server/stop", {}, headers={"X-CRAFT-CONDUCTOR": "0"})[0] == 403
    c.post("/api/logout")
    assert c.get("/api/status")[0] == 401


def test_login_is_rate_limited(running):
    _, c, _ = running
    for _ in range(5):
        c.post("/api/login", {"password": "wrong"})
    assert c.post("/api/login", {"password": "hunter2hunter2"})[0] == 429


def test_static_page_and_headers(running):
    _, c, _ = running
    status, body, headers = c.get("/")
    assert status == 200 and "Craft Conductor" in body
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert headers["X-Frame-Options"] == "DENY"
    assert c.get("/app.js")[0] == 200
    status, png, headers = c.get("/screenshots/dashboard.png")  # (Help's and the manual's pictures)
    assert status == 200 and png.startswith(b"\x89PNG") and headers["Content-Type"] == "image/png"
    assert c.get("/screenshots/missing.png")[0] == 404 and c.get("/screenshots/../app.js")[0] == 404


def test_status_console_and_commands(running):
    d, c, _ = running
    login(c)
    _, s, _ = c.get("/api/status")
    assert s["state"] == "running" and s["minecraft"] == "1.21.1" and s["mods"] == 1
    assert c.post("/api/command", {"command": "/list"})[0] == 200
    wait_for(lambda: any("players online" in line["text"] for line in c.get("/api/console?since=0")[1]["lines"]))
    lines = c.get("/api/console?since=0")[1]["lines"]
    assert any(line["user"] and line["text"] == "> list" for line in lines)
    last = c.get("/api/console?since=0")[1]["last"]
    assert c.get(f"/api/console?since={last}")[1]["lines"] == []


def test_stop_start_and_jobs(running):
    d, c, _ = running
    login(c)
    assert c.post("/api/server/stop")[0] == 200
    wait_for(lambda: c.get("/api/status")[1]["state"] == "stopped" and not c.get("/api/status")[1]["job"])
    time.sleep(0.5)
    assert d.state == "stopped"  # a deliberate stop isn't treated as a crash
    assert c.post("/api/server/start")[0] == 200
    wait_for(lambda: c.get("/api/status")[1]["state"] == "running")
    wait_for(lambda: not c.get("/api/status")[1]["job"])


def test_update_check_and_mod_management(running, modrinth):
    d, c, cfg = running
    login(c)
    assert c.post("/api/updates/check")[0] == 200
    wait_for(lambda: c.get("/api/updates")[1]["check"] is not None)
    check = c.get("/api/updates")[1]["check"]
    assert check["up_to_date"] and check["installed"] == "1.21.1"

    status, body, _ = c.post("/api/mods/add", {"source": "modrinth", "id": "othermod", "required": False})
    assert status == 200, body
    assert c.post("/api/mods/add", {"source": "modrinth", "id": "othermod"})[0] == 409
    assert c.post("/api/mods/add", {"source": "modrinth", "id": "../../etc"})[0] == 400
    configured = c.get("/api/mods")[1]["configured"]
    assert {"source": "modrinth", "id": "othermod", "required": False} in [{k: m[k] for k in ("source", "id", "required")} for m in configured]

    wait_for(lambda: not c.get("/api/status")[1]["job"])
    assert c.post("/api/updates/apply", {})[0] == 200
    wait_for(lambda: len(d.m.lock.mods) == 2, timeout=30)
    wait_for(lambda: c.get("/api/status")[1]["state"] == "running" and not c.get("/api/status")[1]["job"])

    assert c.post("/api/mods/remove", {"source": "modrinth", "id": "othermod"})[0] == 200
    assert all(s["id"] != "othermod" for s in c.get("/api/mods")[1]["configured"])


def test_settings_validation(running):
    d, c, cfg = running
    login(c)
    before = cfg.path.read_text()
    assert c.post("/api/settings", {"strategy": "bogus"})[0] == 400
    assert cfg.path.read_text() == before  # rolled back
    assert c.post("/api/settings", {"strategy": "mods-only", "auto_upgrade": False,
                                    "warn_minutes": [5, 1], "check_interval": "2h"})[0] == 200
    s = c.get("/api/settings")[1]
    assert s["strategy"] == "mods-only" and s["auto_upgrade"] is False
    assert s["warn_minutes"] == [5, 1] and s["check_interval"] == "2h"
    assert d.m.config.updates.strategy == "mods-only"


def test_backups_and_restore_requires_stop(running):
    d, c, cfg = running
    login(c)
    assert c.post("/api/backups/create", {"label": "web test"})[0] == 200
    wait_for(lambda: any("web_test" in b["name"] for b in c.get("/api/backups")[1]["backups"]))
    name = c.get("/api/backups")[1]["backups"][0]["name"]
    assert c.post("/api/backups/restore", {"name": name})[0] == 409  # still running
    assert c.post("/api/backups/restore", {"name": "../craft-conductor.toml"})[0] == 404


def test_manual_upload_only_accepts_expected_files(running):
    d, c, cfg = running
    login(c)
    status, body, _ = c.call("POST", "/api/manual/upload?filename=evil.jar", raw=b"x",
                             headers={"Content-Type": "application/octet-stream"})
    assert status == 400
    d.last_check = {"manual": [{"filename": "blocked.jar", "name": "B", "url": "u"}], "target": None,
                    "checked_at": 0, "up_to_date": False, "latest": "1.21.1"}
    status, body, _ = c.call("POST", "/api/manual/upload?filename=blocked.jar", raw=b"jar bytes",
                             headers={"Content-Type": "application/octet-stream"})
    assert status == 200, body
    assert (cfg.manual_dir / "blocked.jar").read_bytes() == b"jar bytes"
    assert d.last_check["manual"] == []


def test_a_blocked_curseforge_file_is_checked_before_it_counts(running, http, monkeypatch):
    """Updates page → Manual downloads needed: the link is the file's CurseForge page, and only
    the exact file CurseForge lists is taken."""
    import hashlib
    from craft_conductor import config as configmod
    from craft_conductor.mods.curseforge import API
    d, c, cfg = running
    login(c)
    jar = b"the author's own jar"
    http.json[f"{API}/mods/123"] = {"data": {"id": 123, "slug": "blocked-mod", "name": "Blocked Mod"}}
    http.json[f"{API}/mods/123/files"] = {"data": [{
        "id": 5550001, "displayName": "Blocked Mod 1.0", "fileName": "blocked-1.0.jar", "releaseType": 1,
        "downloadUrl": None, "gameVersions": ["1.21.1", "Fabric"], "fileDate": "2025-01-01T00:00:00Z",
        "hashes": [{"value": hashlib.sha1(jar).hexdigest(), "algo": 1}], "dependencies": []}]}
    monkeypatch.setenv("CRAFT_CONDUCTOR_CURSEFORGE_API_KEY", "test-key")
    configmod.append_mod(cfg.path, ModSpec("curseforge", "123"))
    d.m.reload_config()
    d.check_only()
    assert d.last_check["manual"] == [{"name": "Blocked Mod", "filename": "blocked-1.0.jar",
                                       "url": "https://www.curseforge.com/minecraft/mc-mods/blocked-mod/files/5550001",
                                       "sha1": hashlib.sha1(jar).hexdigest()}]
    upload = "/api/manual/upload?filename=blocked-1.0.jar"
    status, body, _ = c.call("POST", upload, raw=b"something else", headers={"Content-Type": "application/octet-stream"})
    assert status == 400 and "checksum is different" in body["error"]
    status, body, _ = c.call("POST", "/api/manual/upload?filename=other.jar", raw=b"something else",
                             headers={"Content-Type": "application/octet-stream"})
    assert status == 400 and "isn't one of the mods waiting" in body["error"]
    assert not (cfg.manual_dir / "blocked-1.0.jar").exists()
    # Dropped on the panel under another name (the browser saved "blocked-1.0 (1).jar"): the checksum says which mod it is.
    status, body, _ = c.call("POST", "/api/manual/upload?filename=blocked-1.0%20(1).jar", raw=jar,
                             headers={"Content-Type": "application/octet-stream"})
    assert status == 200 and body["filename"] == "blocked-1.0.jar" and body["left"] == 0
    assert (cfg.manual_dir / "blocked-1.0.jar").read_bytes() == jar and d.last_check["manual"] == []


def test_web_players_page(running):
    d, c, cfg = running
    login(c)
    d._on_line("[12:00:00] [Server thread/INFO]: Steve joined the game")
    d._on_line("[12:00:01] [Server thread/INFO]: <Steve> Alex joined the game")  # chat can't fake a join
    status, body, _ = c.get("/api/players")
    assert status == 200 and body["online"] == ["Steve"] and body["running"]

    status, body, _ = c.post("/api/players/action", {"action": "op", "name": "Steve"})
    assert status == 200 and body["message"] == "sent: op Steve"
    lines = c.get("/api/console?since=0")[1]["lines"]
    assert any(line["user"] and line["text"] == "> op Steve" for line in lines)
    assert c.post("/api/players/action", {"action": "op", "name": "a b"})[0] == 400

    # Stopped: edits the files instead (the test config runs with online-mode on, so seed usercache).
    assert c.post("/api/server/stop")[0] == 200
    wait_for(lambda: c.get("/api/status")[1]["state"] == "stopped" and not c.get("/api/status")[1]["job"])
    (cfg.server.dir / "usercache.json").write_text(json.dumps([{"name": "Alex", "uuid": offline_uuid("Alex")}]))
    status, body, _ = c.post("/api/players/action", {"action": "ban", "name": "Alex", "reason": "griefing"})
    assert status == 200, body
    bans = c.get("/api/players")[1]["bans"]
    assert bans[0]["name"] == "Alex" and bans[0]["reason"] == "griefing"
    assert c.post("/api/players/action", {"action": "kick", "name": "Alex"})[0] == 400


def test_dashboard_connected_players(running):
    """The Connected Players card: a light call to poll, roles from ops.json, no ping source."""
    d, c, cfg = running
    login(c)
    (cfg.server.dir / "server.properties").write_text("max-players=30\nwhite-list=true\n")
    (cfg.server.dir / "ops.json").write_text(json.dumps([
        {"uuid": offline_uuid("Steve"), "name": "Steve", "level": 4}, {"uuid": offline_uuid("Alex"), "name": "Alex", "level": 2}]))
    (cfg.server.dir / "whitelist.json").write_text(json.dumps([{"uuid": offline_uuid("Sam"), "name": "Sam"}]))
    for name in ("Steve", "Alex", "Kit"):
        d._on_line(f"[12:00:00] [Server thread/INFO]: {name} joined the game")
    before = c.get("/api/console?since=0")[1]["last"]
    status, body, _ = c.get("/api/players/online")
    assert status == 200 and body["max"] == 30 and body["whitelist_enabled"] and body["running"]
    assert [(p["name"], p["op"], p["op_level"], p["ping_ms"]) for p in body["players"]] == [
        ("Alex", True, 2, None), ("Kit", False, None, None), ("Steve", True, 4, None)]
    assert body["ping"]["available"] is False and "ping" in body["ping"]["reason"]
    assert "whitelist" not in body                                   # (the names only when the panel is open)
    assert c.get("/api/players/online?whitelist=1")[1]["whitelist"] == ["Sam"]
    for _ in range(3):
        c.get("/api/players/online")
    assert c.get(f"/api/console?since={before}")[1]["lines"] == []   # polling the card sends the server nothing
    d._on_line("[12:00:09] [Server thread/INFO]: Kit left the game")
    assert [p["name"] for p in c.get("/api/players/online")[1]["players"]] == ["Alex", "Steve"]
    assert Client(c.base).get("/api/players/online")[0] == 401        # (signed-in only)


def test_dashboard_broadcast(running):
    d, c, cfg = running
    login(c)
    status, body, _ = c.post("/api/broadcast", {"message": "  Restart in 5 minutes  "})
    assert status == 200 and body["ok"]
    assert any(line["user"] and line["text"] == "> say Restart in 5 minutes" for line in c.get("/api/console?since=0")[1]["lines"])
    sent = len(c.get("/api/console?since=0")[1]["lines"])
    for message in ("", "   ", None, 7, "x" * 257, "one\ntwo", "one\r\ntwo", "bell\x07", "nul\x00", "esc\x1b[0m"):
        status, body, _ = c.post("/api/broadcast", {"message": message})
        assert status == 400 and body["error"], repr(message)
    assert c.post("/api/broadcast", {})[0] == 400
    # (nothing refused reached the server's console)
    assert not any(line["text"].startswith("> say") and "two" in line["text"] for line in c.get("/api/console?since=0")[1]["lines"])
    assert len([x for x in c.get("/api/console?since=0")[1]["lines"] if x["user"]]) == 1 and sent
    assert c.post("/api/server/stop")[0] == 200
    wait_for(lambda: c.get("/api/status")[1]["state"] == "stopped" and not c.get("/api/status")[1]["job"])
    status, body, _ = c.post("/api/broadcast", {"message": "anyone?"})
    assert status == 409 and "isn't running" in body["error"]
    assert Client(c.base).post("/api/broadcast", {"message": "hi"})[0] == 401


def test_dashboard_whitelist_through_the_players_calls(running):
    """The Dashboard's Whitelist panel uses the Players page's calls: on/off, add, remove."""
    d, c, cfg = running
    login(c)
    assert c.post("/api/server/stop")[0] == 200
    wait_for(lambda: c.get("/api/status")[1]["state"] == "stopped" and not c.get("/api/status")[1]["job"])
    (cfg.server.dir / "usercache.json").write_text(json.dumps([{"name": "Sam", "uuid": offline_uuid("Sam")}]))
    assert c.post("/api/players/action", {"action": "whitelist-on"})[0] == 200
    assert c.post("/api/players/action", {"action": "whitelist-add", "name": "Sam"})[0] == 200
    body = c.get("/api/players/online?whitelist=1")[1]
    assert body["whitelist_enabled"] and body["whitelist"] == ["Sam"] and not body["running"]
    for bad in ("two words", "Sam\nop Evil", "x" * 17, ""):
        assert c.post("/api/players/action", {"action": "whitelist-add", "name": bad})[0] == 400, bad
    assert c.post("/api/players/action", {"action": "whitelist-remove", "name": "Sam"})[0] == 200
    assert c.post("/api/players/action", {"action": "whitelist-off"})[0] == 200
    body = c.get("/api/players/online?whitelist=1")[1]
    assert not body["whitelist_enabled"] and body["whitelist"] == []


def test_default_password_and_changing_it(running_default):
    d, c, cfg = running_default
    assert c.get("/api/auth")[1] == {"mode": "password", "default": True, "managed": False, "strong": False, "temporary": False, "local": True, "strong_required": False, "passkeys": False,
                                  "version": __version__, "matches": False, "last_update": None}
    assert c.post("/api/login", {"password": "passw0rd"})[0] == 401
    assert c.post("/api/login", {"password": " password "})[0] == 200  # the default ignores case
    assert c.post("/api/login", {"password": "PASSWORD"})[0] == 200
    assert c.get("/api/status")[1]["auth"]["default"] is True  # the UI asks to change it

    other = Client(c.base)
    assert other.post("/api/login", {"password": "PASSWORD"})[0] == 200
    assert c.post("/api/auth/change", {"mode": "password", "secret": "PASSWORD"})[0] == 400
    assert c.post("/api/auth/change", {"mode": "pin", "secret": "12ab"})[0] == 400
    status, body, _ = c.post("/api/auth/change", {"mode": "pin", "secret": "4821"})
    assert status == 200 and body["mode"] == "pin" and not body["default"]
    assert c.get("/api/status")[0] == 200       # this browser stays signed in
    assert other.get("/api/status")[0] == 401   # everyone else is signed out
    assert other.post("/api/login", {"password": "PASSWORD"})[0] == 401
    assert other.post("/api/login", {"password": "4821"})[0] == 200
    stored = (cfg.state_dir / "web-auth.json").read_text()
    # Only a salted hash: the PIN isn't stored as a value anywhere (a hex salt can contain "4821" by chance).
    import json as _json
    values = [str(v) for v in _json.loads(stored).values()] if stored.lstrip().startswith("{") else [stored]
    assert "4821" not in values and "PASSWORD" not in stored

    # There's no "no password" option: even this computer signs in.
    assert c.post("/api/auth/change", {"mode": "none"})[0] == 400
    assert Client(c.base).get("/api/status")[0] == 401

    # `craft-conductor web-password --reset` while running goes back to PASSWORD.
    from craft_conductor import webauth
    webauth.AuthStore(cfg).reset()
    fresh = Client(c.base)
    assert fresh.get("/api/status")[0] == 401
    assert fresh.post("/api/login", {"password": "PASSWORD"})[0] == 200


def test_foreign_host_names_are_refused(running_default):
    d, c, cfg = running_default
    port = c.base.rsplit(":", 1)[1]
    assert c.call("GET", "/api/auth", headers={"Host": f"evil.example:{port}"})[0] == 421
    assert c.call("GET", "/", headers={"Host": "evil.example"})[0] == 421
    for ok in (f"localhost:{port}", f"127.0.0.1:{port}", f"[::1]:{port}", "192.168.1.20", "mypc.local"):
        assert c.call("GET", "/api/auth", headers={"Host": ok})[0] == 200, ok
    cfg.web.allowed_hosts.append("mc.example.com")
    assert c.call("GET", "/api/auth", headers={"Host": "mc.example.com"})[0] == 200


def test_dashboard_usage_and_skins(running):
    d, c, cfg = running
    login(c)
    first = c.get("/api/status")[1]["resources"]
    assert first["memory_bytes"] > 0 and first["cpus"] >= 1 and first["memory_max_bytes"] == 4 * 1024 ** 3
    time.sleep(0.6)
    assert c.get("/api/status")[1]["resources"]["cpu_percent"] is not None

    from craft_conductor.skins import SkinError
    skins = d.ui.api.skins

    def fake_png(name):
        if name != "Notch":
            raise SkinError("no skin")
        return b"\x89PNG\r\n\x1a\nfake"
    skins.png = fake_png
    assert c.get("/api/players/skin?name=Nobody")[0] == 404  # the page draws a lettered tile
    status, body, headers = c.call("GET", "/api/players/skin?name=Notch")
    assert status == 200 and headers["Content-Type"] == "image/png" and body.startswith(b"\x89PNG")
    assert Client(c.base).get("/api/players/skin?name=Notch")[0] == 401  # signed-in only
