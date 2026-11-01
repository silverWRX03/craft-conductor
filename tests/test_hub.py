"""Several servers in one craft-conductor (`craft-conductor start`): listed in the web UI, and never started by themselves."""

import json
from pathlib import Path

import pytest

from craft_conductor import cli, config as configmod, lock as lockmod, setup as setupmod, webauth
from craft_conductor.hub import Hub

from test_web import Client, wait_for


def login(c):
    assert c.post("/api/login", {"password": "PASSWORD"})[0] == 200


def reset_here(c) -> tuple:
    """The forgotten-password reset, from this computer: the code from the file, then the reset."""
    import re
    status, made, _ = c.post("/api/auth/reset-code", {})
    assert status == 200, made
    code = re.search(r"[A-Z0-9]{4}-[A-Z0-9]{4}", Path(made["file"]).read_text()).group(0)
    return c.post("/api/auth/reset-local", {"code": code})


def test_servers_are_listed_and_never_start_by_themselves(hub_env):
    hub, c = hub_env
    login(c)
    overview = c.get("/api/hub")[1]
    assert not overview["single"] and overview["auth"]["default"]
    servers = {s["id"]: s for s in overview["servers"]}
    assert servers["alpha"]["name"] == "Alpha" and servers["alpha"]["minecraft"] == "1.21.1"
    assert servers["main"]["setup_pending"]
    import time
    time.sleep(1.0)
    assert all(s["state"] == "stopped" for s in c.get("/api/hub")[1]["servers"])  # nothing auto-starts

    assert c.get("/api/status")[0] == 404  # with several servers, say which one
    assert c.get("/api/servers/alpha/status")[1]["id"] == "alpha"
    assert c.get("/api/servers/nope/status")[0] == 404

    assert c.post("/api/servers/alpha/server/start")[0] == 200
    wait_for(lambda: hub.get("alpha").state == "running", timeout=30)
    assert hub.get("main").state == "stopped"
    assert c.post("/api/servers/alpha/command", {"command": "say hi"})[0] == 200
    lines = c.get("/api/servers/alpha/console")[1]["lines"]
    assert any(line["text"] == "> say hi" for line in lines)
    # Each server's activity feed only shows its own messages.
    events = [e["message"] for e in c.get("/api/servers/alpha/events")[1]["events"]]
    assert any("starting server" in e for e in events)
    assert not any("starting server" in e["message"] for e in c.get("/api/servers/main/events")[1]["events"])

    assert c.post("/api/servers/alpha/server/stop")[0] == 200
    wait_for(lambda: hub.get("alpha").state == "stopped" and not hub.get("alpha").job, timeout=30)



def test_a_two_line_motd_is_listed_on_one_line(hub_env):
    """The name the page shows (and asks to be typed to delete a server with its files) is one line."""
    from craft_conductor.properties import write_properties
    hub, c = hub_env
    login(c)
    alpha = hub.get("alpha")
    write_properties(alpha.m.server_dir / "server.properties", {"motd": "Alpha\nSecond line"})
    assert (alpha.m.server_dir / "server.properties").read_text().count("motd=Alpha\\nSecond line") == 1
    names = {s["id"]: s["name"] for s in c.get("/api/hub")[1]["servers"]}
    assert names["alpha"] == "Alpha Second line"
    assert c.get("/api/servers/alpha/status")[1]["motd"] == "Alpha Second line"


def test_delete_servers(hub_env):
    hub, c = hub_env
    login(c)
    alpha = hub.get("alpha").m.config.root
    world = hub.get("alpha").m.server_dir / "world"
    world.mkdir(parents=True, exist_ok=True)
    (world / "level.dat").write_text("level")

    # A running server can't be deleted.
    assert c.post("/api/servers/alpha/server/start")[0] == 200
    wait_for(lambda: hub.get("alpha").state == "running", timeout=30)
    assert c.post("/api/hub/delete", {"id": "alpha", "delete_files": True})[0] == 400
    assert c.post("/api/servers/alpha/server/stop")[0] == 200
    wait_for(lambda: hub.get("alpha").state == "stopped" and not hub.get("alpha").job, timeout=30)

    # "Keep the files": off the list (and it stays off), but the world is untouched.
    status, body, _ = c.post("/api/hub/delete", {"id": "alpha", "delete_files": False})
    assert status == 200 and "still in" in body["message"]
    assert (world / "level.dat").read_text() == "level"
    hub.scan()
    assert "alpha" not in {s["id"] for s in c.get("/api/hub")[1]["servers"]}

    # "Delete everything" in the home folder removes only that server's files, not craft-conductor's own.
    (hub.home / "notes.txt").write_text("mine")
    status, body, _ = c.post("/api/hub/delete", {"id": "main", "delete_files": True})
    assert status == 200, body
    assert not (hub.home / "craft-conductor.toml").exists() and not (hub.home / "server").exists()
    assert (hub.home / "notes.txt").exists() and (hub.home / ".craft-conductor" / "web-auth.json").exists()
    assert alpha.exists()  # the kept one is still there

    # A server in craft-conductor's servers folder is erased completely.
    sid = c.post("/api/hub/create", {"loader": "vanilla", "motd": "Temp", "accept_eula": True})[1]["id"]
    d = hub.get(sid)
    wait_for(lambda: d.last_job and d.last_job["name"] == "set up server", timeout=30)
    root = d.m.config.root
    assert root.exists()
    assert c.post("/api/hub/delete", {"id": sid, "delete_files": True})[0] == 200
    assert not root.exists()
    assert c.get("/api/hub")[1]["servers"] == []


def test_create_a_server_from_the_web(hub_env):
    hub, c = hub_env
    login(c)
    opts = c.get("/api/hub/setup")[1]
    assert opts["versions"] == ["1.21.1"] and not opts["network_option"]
    from craft_conductor.mods.modrinth import API
    hub.http.json[f"{API}/search"] = {"hits": [{"project_id": "AAA", "slug": "goodmod", "title": "Good Mod"}]}
    assert c.get("/api/hub/mods/search?loader=fabric&q=good")[1]["results"][0]["slug"] == "goodmod"
    # With nothing typed, the setup page lists the 20 most downloaded mods for the loader.
    seen, orig = [], hub.http.get_json
    hub.http.get_json = lambda url, params=None, headers=None: seen.append(params) or orig(url, params, headers)
    assert c.get("/api/hub/mods/search?loader=fabric&top=1")[1]["results"]
    assert seen[-1]["index"] == "downloads" and seen[-1]["limit"] == 20 and seen[-1]["query"] == ""
    assert c.get("/api/hub/mods/search?loader=vanilla&top=1")[1]["results"] == []
    assert c.get("/api/hub/mods/search?loader=fabric")[1]["results"] == []
    hub.http.get_json = orig

    status, body, _ = c.post("/api/hub/create", {"loader": "fabric", "minecraft": "1.21.1", "mods": ["goodmod"],
                                                  "motd": "My World!", "accept_eula": True,
                                                  "properties": {"pvp": False, "view-distance": "12"}})
    assert status == 200, body
    sid = body["id"]
    assert sid == "my-world" and (hub.home / "servers" / "my-world" / "craft-conductor.toml").exists()
    d = hub.get(sid)
    wait_for(lambda: d.last_job and d.last_job["name"] == "set up server", timeout=30)
    assert d.last_job["ok"], d.last_job
    assert "press Start" in d.last_job["message"]
    assert d.state == "stopped" and not d.setup_pending  # installed and test-booted, but not left running
    from craft_conductor.properties import read_properties
    assert read_properties(d.m.server_dir / "server.properties")["pvp"] == "false"  # advanced setting
    lk = lockmod.load(d.m.config.root)
    assert lk.minecraft == "1.21.1" and {m.name for m in lk.mods} == {"Fabric API", "Good Mod"}
    # A second server with the same name gets its own folder, and each gets its own port.
    assert c.post("/api/hub/create", {"loader": "vanilla", "motd": "My World", "accept_eula": True})[1]["id"] == "my-world-2"
    ports = {s["id"]: s["port"] for s in c.get("/api/hub")[1]["servers"] if s["id"] != "main"}
    assert len(set(ports.values())) == 3 and ports["alpha"] == "25565"
    # The setup page checks ports as you type, and a port picked by hand that's taken is refused.
    info = c.get("/api/hub/port?port=25565")[1]
    assert info["used_by"] == "Alpha" and info["suggestion"] not in (25565, int(ports["my-world"]), int(ports["my-world-2"]))
    assert c.get("/api/hub/port?port=25590")[1]["used_by"] is None
    assert c.get("/api/hub/port?port=80")[0] == 400
    status, body, _ = c.post("/api/hub/create", {"loader": "vanilla", "motd": "Clash", "port": 25565, "accept_eula": True})
    assert status == 400 and "already used" in body["error"]
    # Two servers can't be given the same port...
    status, body, _ = c.post("/api/servers/my-world/settings", {"port": 25565})
    assert status == 400 and "alpha" in body["error"]
    # ...nor one Craft Conductor itself listens on (the control panel, friends' downloads): the server
    # couldn't start on it.
    for port in (hub.ui.httpd.server_address[1], hub.share_settings()["port"]):
        status, body, _ = c.post("/api/servers/my-world/settings", {"port": port})
        assert status == 400 and "Craft Conductor itself" in body["error"], body
        status, body, _ = c.post("/api/hub/create", {"loader": "vanilla", "motd": "Clash", "port": port, "accept_eula": True})
        assert status == 400 and "Craft Conductor itself" in body["error"], body
    assert c.post("/api/servers/my-world/settings", {"port": 25600})[0] == 200
    settings = c.get("/api/servers/my-world/settings")[1]
    assert settings["port"] == 25600 and settings["properties"]["view-distance"] == "12"
    assert c.post("/api/servers/my-world/settings", {"properties": {"spawn-protection": 0, "level-seed": "abc"}})[0] == 200
    props = read_properties(d.m.server_dir / "server.properties")
    assert props["spawn-protection"] == "0" and props["level-seed"] == "abc" and props["pvp"] == "false"
    assert c.post("/api/servers/my-world/settings", {"properties": {"rcon.password": "x"}})[0] == 400
    assert c.post("/api/servers/my-world/settings", {"properties": {"view-distance": 99}})[0] == 400
    # ...and one can't start while another running server is on its port.
    from craft_conductor.properties import write_properties
    write_properties(d.m.server_dir / "server.properties", {"server-port": "25565"})
    assert c.post("/api/servers/alpha/server/start")[0] == 200
    wait_for(lambda: hub.get("alpha").state == "running", timeout=30)
    assert c.post(f"/api/servers/{sid}/server/start")[0] == 200
    wait_for(lambda: d.last_job and d.last_job["name"] == "start", timeout=30)
    assert not d.last_job["ok"] and "already used by Alpha" in d.last_job["message"] and d.state == "stopped"


def test_password_reset_from_this_computer(hub_env):
    hub, c = hub_env
    login(c)
    assert c.post("/api/auth/change", {"mode": "pin", "secret": "2468"})[0] == 200
    other = Client(c.base)
    assert other.post("/api/login", {"password": "PASSWORD"})[0] == 401
    # Not over the network (or through a proxy)...
    assert other.call("POST", "/api/auth/reset-local", {}, headers={"X-Forwarded-For": "203.0.113.5"})[0] == 403
    # ...but at the server's own computer, back to PASSWORD without a sign-in, with the code
    # written to a file in Craft Conductor's folder.
    assert other.post("/api/auth/reset-local", {})[0] == 401
    status, made, _ = other.post("/api/auth/reset-code", {})
    assert status == 200
    import re as _re
    code = _re.search(r"[A-Z0-9]{4}-[A-Z0-9]{4}", Path(made["file"]).read_text()).group(0)
    assert other.post("/api/auth/reset-local", {"code": code.lower()})[0] == 200
    assert not Path(made["file"]).exists()  # (used up)
    assert other.post("/api/login", {"password": "PASSWORD"})[0] == 200
    assert c.get("/api/hub")[0] == 401  # everyone else was signed out


def test_password_carried_over_by_020_is_replaced(tmp_path):
    # craft-conductor 0.2.0 turned 0.1's generated password into web-auth.json (without a format number).
    state = tmp_path / ".craft-conductor"
    state.mkdir()
    import hashlib
    salt = b"0123456789abcdef"
    (state / "web-auth.json").write_text(json.dumps({
        "mode": "password", "salt": salt.hex(), "iterations": 1000, "default": False,
        "hash": hashlib.pbkdf2_hmac("sha256", b"randomOld", salt, 1000).hex()}))
    hub = Hub(tmp_path)
    auth = webauth.AuthStore(hub).get()
    assert auth.default and auth.check("PASSWORD") and not auth.check("randomOld")
    # Passwords chosen since are kept.
    webauth.AuthStore(hub).set("password", "mine!")
    assert webauth.AuthStore(Hub(tmp_path)).get().check("mine!")


def test_start_when_the_control_panels_port_is_taken(tmp_path, monkeypatch, capsys):
    """Another program on the control panel's port (or Windows keeping it for itself) gets a message
    that says so and what to do, not "stopped unexpectedly" with a socket error."""
    import socket
    home = tmp_path / "home" / "craft-conductor"
    monkeypatch.setenv("CRAFT_CONDUCTOR_HOME", str(home))
    with socket.socket() as other:
        other.bind(("127.0.0.1", 0))
        other.listen(1)
        port = other.getsockname()[1]
        assert cli.main(["-C", str(tmp_path), "start", "--no-browser", "--web-port", str(port)]) == 1
    err = capsys.readouterr().err
    assert f"port {port}" in err and "another program" in err and "--web-port" in err
    assert "stopped unexpectedly" not in err and "WinError" not in err


def test_two_craft_conductors_cant_share_a_port():
    """On Windows two listeners that both ask for SO_REUSEADDR may share a port: two Craft Conductors
    on one computer then shared the friends' download port, and invites reached the wrong one. The
    second must get "port in use" instead (as it does elsewhere)."""
    from http.server import BaseHTTPRequestHandler
    from craft_conductor.web import _Server
    first = _Server(("127.0.0.1", 0), BaseHTTPRequestHandler)
    try:
        with pytest.raises(OSError):
            _Server(("127.0.0.1", first.server_address[1]), BaseHTTPRequestHandler).server_close()
    finally:
        first.server_close()


def test_a_taken_usual_port_moves_the_control_panel(tmp_path, monkeypatch, capsys, caplog):
    """The usual port taken (and not chosen by hand): the control panel uses the next free port
    this time, says so, and a second start of Craft Conductor opens that address."""
    import socket
    import subprocess
    import sys
    import threading
    from craft_conductor.hub import hub_panel_path, hub_pid_path, running_panel
    from test_web import wait_for
    home = tmp_path / "home" / "craft-conductor"
    monkeypatch.setenv("CRAFT_CONDUCTOR_HOME", str(home))
    with socket.socket() as other:
        other.bind(("127.0.0.1", 0))
        other.listen(1)
        taken = other.getsockname()[1]
        hub = Hub(home, tick=0.1)
        assert not hub.web_port_chosen
        hub.web.port = taken  # (as if it were the usual port)
        t = threading.Thread(target=hub.run, daemon=True)
        t.start()
        try:
            wait_for(lambda: hub.ui is not None and hub.ui.httpd is not None and running_panel(home))
            port = hub.ui.httpd.server_address[1]
            assert taken < port <= taken + 30 and port != hub.share_settings()["port"]
            assert running_panel(home) == f"http://localhost:{port}/"
            assert f"port {taken} is taken" in caplog.text and f"on port {port} this time" in caplog.text
        finally:
            hub.stop_requested.set()
            t.join(30)
    assert not hub_panel_path(home).exists()
    # Opening Craft Conductor again while it runs (another process) opens the address it's really on.
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        hub_pid_path(home).write_text(str(sleeper.pid))
        hub_panel_path(home).write_text("http://localhost:8790/", encoding="utf-8")
        assert cli.main(["-C", str(tmp_path), "start", "--no-browser"]) == 0
        assert f"already running (pid {sleeper.pid}): http://localhost:8790/" in capsys.readouterr().out
    finally:
        sleeper.kill()
        sleeper.wait(10)


def test_start_opens_the_server_list(tmp_path, monkeypatch, fake_template, capsys):
    home = tmp_path / "home" / "craft-conductor"
    monkeypatch.setenv("CRAFT_CONDUCTOR_HOME", str(home))
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    ran = []
    monkeypatch.setattr(Hub, "run", lambda self: ran.append(self) or 0)

    empty = tmp_path / "elsewhere"
    empty.mkdir()
    assert cli.main(["-C", str(empty), "start", "--no-browser"]) == 0
    assert ran and not (home / "craft-conductor.toml").exists()  # no placeholder server any more
    out = capsys.readouterr().out
    assert "Create your first server" in out
    if cli.has_display():
        assert "Password:       PASSWORD" in out
    else:  # no screen: other devices sign in, with a one-time password until you choose one
        assert "Password:       Craft-Conductor-" in out and "one-time" in out
        assert (home / ".craft-conductor" / "first-password.txt").is_file()

    # A server folder elsewhere is listed too; a home-folder server that never installed goes to setup.
    other = tmp_path / "other-server"
    setupmod.configure(other, setupmod.SetupSpec.from_dict({"loader": "fabric", "accept_eula": True}))
    setupmod.configure(home, setupmod.SetupSpec.from_dict({"loader": "fabric", "accept_eula": True}))
    assert cli.main(["-C", str(other), "start", "--no-browser"]) == 0
    assert set(ran[-1].discover()) == {"main", "other-server"}
    assert setupmod.is_pending(home)


def test_throwaway_servers_dont_get_the_same_port(tmp_path):
    """A map preview and a mod test picked at once both got 25590 before either Java bound it (#163)."""
    from craft_conductor.hub import Hub
    hub = Hub(tmp_path / "home")
    first = hub.free_port(25590, hold=True)
    second = hub.free_port(25590, hold=True)
    assert first != second and hub.free_port(25590) not in (first, second)
    hub.release_port(first)
    assert hub.free_port(25590) == first


def test_a_typo_in_server_properties_doesnt_break_the_page(hub_env):
    """``max-players=twenty`` typed into a stopped server's server.properties: Minecraft uses its
    default, but the server list and the status every page asks for answered "invalid literal for
    int()" (400), and the whole control panel said it was reconnecting."""
    from craft_conductor.properties import write_properties
    hub, c = hub_env
    login(c)
    write_properties(hub.get("alpha").m.server_dir / "server.properties", {"max-players": "twenty", "server-port": "25565x"})
    status, body, _ = c.call("GET", "/api/hub")
    assert status == 200, body
    assert next(s for s in body["servers"] if s["id"] == "alpha")["max_players"] == 20  # (Minecraft's default, as it uses)
    for path in ("/api/servers/alpha/status", "/api/servers/alpha/settings", "/api/servers/alpha/reach", "/api/servers/alpha/doctor"):
        assert c.call("GET", path)[0] == 200, path



def test_a_server_whose_settings_are_the_wrong_kind_is_listed_with_its_problem(hub_env):
    """``warn_minutes = 5`` (not a list) typed into a server's craft-conductor.toml: the hub's scan
    raised a TypeError, and Craft Conductor stopped (every server's page with it)."""
    hub, c = hub_env
    login(c)
    root = hub.servers_dir / "broken"
    root.mkdir()
    import re
    text, n = re.subn(r"warn_minutes = \[[^\]]*\]", "warn_minutes = 5", configmod.render_template("vanilla", "1.21.1"))
    assert n == 1
    (root / "craft-conductor.toml").write_text(text, encoding="utf-8")
    hub.scan()  # (raised)
    servers = {s["id"]: s for s in c.get("/api/hub")[1]["servers"]}
    assert "warn_minutes" in servers["broken"]["problem"] and servers["alpha"]["state"]


def test_a_server_trying_an_update_on_a_copy_isnt_deleted_or_moved(hub_env, tmp_path):
    """The rehearsal's copy runs from inside the server's folder, but isn't one of its jobs: Delete went
    ahead (on Windows, stopped halfway by the copy's open files; its Java left running), and so did
    moving the servers to another folder."""
    from types import SimpleNamespace
    hub, c = hub_env
    login(c)
    d = hub.get("alpha")
    d.rehearsal = SimpleNamespace(state="running")
    status, body, _ = c.post("/api/hub/delete", {"id": "alpha", "delete_files": True})
    assert status == 400 and "copy" in body["error"], body
    assert hub.get("alpha") is d and (d.m.config.root / "craft-conductor.toml").exists()
    plan = c.post("/api/hub/locations", {"servers": str(tmp_path / "Elsewhere")})[1]
    assert any("copy of itself" in b for b in plan["busy"]), plan
    d.rehearsal = SimpleNamespace(state="done")
    assert c.post("/api/hub/delete", {"id": "alpha"})[0] == 200  # (once it's over)


def test_a_damaged_hub_json_doesnt_stop_craft_conductor(hub_env):
    """hub.json with parts of the wrong kind (damaged, or edited by hand): "extra": 5 made the scan raise,
    which stopped Craft Conductor; a share port that isn't one made every page answer "internal error"."""
    from craft_conductor import hub as hubmod
    hub, c = hub_env
    login(c)
    path = hub.state_dir / hubmod.HUB_FILE
    data = json.loads(path.read_text())
    path.write_text(json.dumps({**data, "extra": 5, "hidden": None, "share": {"port": None, "address": 7},
                                "upnp": {"enabled": True, "mapped": 5}, "discord": {"token": "x", "bot": True, "whitelist": 5}}))
    hub.scan()
    assert c.get("/api/hub")[0] == 200 and c.get("/api/hub/discord")[0] == 200
    assert hub.share_settings()["address"] == "" and hub.upnp_settings()["mapped"] == []


def test_one_step_going_wrong_doesnt_stop_craft_conductor(hub_env, monkeypatch):
    """An unexpected error in one step of the hub's own loop (the scan, the router, the friends'
    downloads) left the loop, and Craft Conductor stopped: every server's page with it. It's logged now,
    and the loop goes on."""
    from craft_conductor import hub as hubmod
    from test_web import wait_for
    hub, c = hub_env
    login(c)
    tries = []

    def broken():
        tries.append(1)
        raise RuntimeError("a bug")
    monkeypatch.setattr(hubmod, "SCAN_EVERY", 0.05)
    monkeypatch.setattr(hub, "scan", broken)
    wait_for(lambda: len(tries) >= 3, timeout=10)
    assert c.get("/api/hub")[0] == 200 and not hub.stop_requested.is_set()


def test_one_step_going_wrong_doesnt_leave_a_server_without_its_manager(hub_env, monkeypatch):
    """The same for each server's own loop: its thread ended, and the hub made a new manager that
    didn't know about the Minecraft still running (Stop no longer reached it)."""
    import time
    from test_web import wait_for
    hub, c = hub_env
    d = hub.get("alpha")
    tries = []

    def broken(*a, **k):
        tries.append(1)
        raise RuntimeError("a bug")
    monkeypatch.setattr(d, "_run_schedules", broken)
    wait_for(lambda: len(tries) >= 3, timeout=10)
    time.sleep(0.3)
    assert hub._threads["alpha"].is_alive() and hub.get("alpha") is d


def test_damaged_sign_in_files_dont_lock_the_owner_out(hub_env):
    """web-auth.json holding "null" (damaged): every page, and signing in, answered "internal error". It's
    treated like one that can't be read: the default password (from this computer), and the prompt to
    choose one. users.json whose list of people isn't one broke the People page."""
    from craft_conductor import webauth
    from test_web import Client
    hub, c = hub_env
    (hub.state_dir / webauth.FILE).write_text("null")
    fresh = Client(c.base)
    assert fresh.get("/api/auth")[0] == 200
    assert fresh.post("/api/login", {"password": webauth.DEFAULT_PASSWORD})[0] == 200
    (hub.state_dir / "users.json").write_text(json.dumps({"format": 1, "users": 5}))
    assert fresh.get("/api/hub/users")[0] == 200


def test_a_damaged_list_of_paired_phones_is_read_as_none(hub_env):
    """devices.json whose list isn't one raised on every paired phone's request."""
    from craft_conductor import webauth
    hub, c = hub_env
    (hub.state_dir / webauth.DEVICES_FILE).write_text(json.dumps({"devices": 5}))
    assert hub.ui.devices.find("x" * 40, 0) is None
