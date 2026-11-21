"""Craft Conductor's side of players' ping (roadmap 47): the setting, putting the helper jar in and
taking it out at each start, and reading the file it writes (pinghelper.py)."""
import json
import os
import shutil
import time

import pytest

from craft_conductor import config as configmod, modcheck, pinghelper
from craft_conductor.config import ModSpec
from craft_conductor.pinghelper import helper_jar, is_helper, unsupported_reason
from test_manager import manager, update

VANILLA = "Minecraft doesn't share each player's ping without a mod or plugin, and plain Minecraft runs neither."


@pytest.fixture
def fake_jars(tmp_path, monkeypatch):
    """A helpers folder with a fake jar for each platform (the shipped ones are only read in test_support)."""
    folder = tmp_path / "helpers"
    folder.mkdir()
    for platform in ("paper", "fabric", "fabric26"):
        (folder / f"craft_conductor_ping-{platform}-1.0.0.jar").write_bytes(f"fake {platform}".encode())
    monkeypatch.setattr(pinghelper, "JARS_DIR", folder)
    return folder


def test_support():
    assert helper_jar("paper", "1.21.1").name == "craft_conductor_ping-paper-1.0.0.jar"
    assert helper_jar("purpur", "1.17").name == "craft_conductor_ping-paper-1.0.0.jar"
    assert helper_jar("fabric", "1.20.2").name == "craft_conductor_ping-fabric-1.0.0.jar"
    assert helper_jar("quilt", "1.21.11").name == "craft_conductor_ping-fabric-1.0.0.jar"
    # (26.x versions come after every 1.x one, and have a jar of their own)
    assert helper_jar("fabric", "26").name == "craft_conductor_ping-fabric26-1.0.0.jar"
    assert helper_jar("fabric", "26.1").name == "craft_conductor_ping-fabric26-1.0.0.jar"
    assert helper_jar("quilt", "26.2.1").name == "craft_conductor_ping-fabric26-1.0.0.jar"
    assert helper_jar("paper", "26.1").name == "craft_conductor_ping-paper-1.0.0.jar"
    for loader, version in (("fabric", "1.20.1"), ("fabric", "1.19.4"), ("paper", "1.16.5"),
                            ("vanilla", "1.21.1"), ("neoforge", "1.21.1"), ("forge", "1.20.1")):
        assert helper_jar(loader, version) is None
        assert unsupported_reason(loader, version)
    assert unsupported_reason("paper", "1.21.1") is None and unsupported_reason("fabric", "26.1") is None
    assert unsupported_reason("fabric", "1.20.1") == "Craft Conductor's ping helper needs Minecraft 1.20.2 or newer on this server type."
    assert unsupported_reason("quilt", "1.20.1") == "Craft Conductor's ping helper needs Minecraft 1.20.2 or newer on this server type."
    assert unsupported_reason("paper", "1.16.5") == "Craft Conductor's ping helper needs Minecraft 1.17 or newer on this server type."
    assert unsupported_reason("vanilla", "1.21.1") == VANILLA
    assert unsupported_reason("neoforge", "1.21.1") == "Craft Conductor's ping helper doesn't run on neoforge yet."
    assert unsupported_reason("forge", "1.20.1") == "Craft Conductor's ping helper doesn't run on forge yet."
    assert is_helper("craft_conductor_ping-fabric-1.0.0.jar") and is_helper("craft_conductor_ping-paper-2.1.jar.disabled")
    assert not is_helper("sodium.jar") and not is_helper("craft_conductor_ping-fabric-1.0.0.zip")


def test_sync_puts_it_in_and_takes_it_out(make_config, http, modrinth, fake_jars):
    cfg = make_config()
    m = manager(cfg, http, ["1.21.1"])
    assert update(m).ok
    mods = m.mods_dir
    ping = m.server_dir / pinghelper.PING_FILE
    helper = mods / "craft_conductor_ping-fabric-1.0.0.jar"

    pinghelper.sync(m)                                       # (off by default: nothing is added)
    assert not helper.exists()

    m.config.player_ping = True
    (mods / "craft_conductor_ping-fabric-0.9.0.jar").write_bytes(b"older")      # an older version of it
    (mods / "craft_conductor_ping-paper-1.0.0.jar.disabled").write_bytes(b"x")  # (only one helper may be there)
    (mods / "craft_conductor_ping-fabric26-1.0.0.jar").write_bytes(b"other platform")
    (mods / "mine.jar").write_bytes(b"hand-made")
    ping.parent.mkdir()
    ping.write_text(json.dumps({"version": 1, "time": int(time.time() * 1000), "players": {"Old": 5}}))
    pinghelper.sync(m)
    assert helper.read_bytes() == b"fake fabric"
    assert sorted(p.name for p in mods.iterdir() if is_helper(p.name)) == [helper.name]
    assert not ping.exists()                                 # (the last run's numbers never show)
    assert m.unmanaged_jars() == ["mine.jar"] and m.disabled_jars() == []

    before = helper.stat().st_mtime_ns
    pinghelper.sync(m)                                       # (the same file: not copied again)
    assert helper.stat().st_mtime_ns == before

    (fake_jars / "craft_conductor_ping-fabric-1.0.0.jar").write_bytes(b"fake fabric, newer")
    pinghelper.sync(m)                                       # (a newer Craft Conductor: replaced)
    assert helper.read_bytes() == b"fake fabric, newer"

    # An update rebuilds the mods folder: the helper is still there, and never "added by hand".
    modrinth.project("AAA", "goodmod")
    modrinth.version("AAA", "1.0", ["1.21.1"])
    configmod.append_mod(cfg.path, ModSpec("modrinth", "goodmod"))
    m.reload_config()
    m.config.player_ping = True                              # (reading the file again: this test sets it in memory)
    assert update(m).ok                                      # (it boots the new server to check it: that start syncs too)
    assert helper.exists() and m.unmanaged_jars() == ["mine.jar"]

    # ... nor read by the load check as one of the owner's mods.
    read = []
    real = modcheck.read_file
    modcheck.read_file = lambda path, loader: read.append(path.name) or []
    try:
        modcheck.check_folder(mods, loader="fabric", minecraft="1.21.1", loader_version="1")
    finally:
        modcheck.read_file = real
    assert "mine.jar" in read and not any(is_helper(n) for n in read)

    m.config.player_ping = False                             # switched off: it is taken out
    pinghelper.sync(m)
    assert not any(is_helper(p.name) for p in mods.iterdir())

    m.config.player_ping = True                              # a server switched to vanilla loses it too
    pinghelper.sync(m)
    assert helper.exists()
    m.lock.loader = "vanilla"
    pinghelper.sync(m)
    assert not helper.exists()
    m.lock.loader, m.lock.minecraft = "fabric", "1.20.1"     # ... and one on Minecraft 1.20.1
    pinghelper.sync(m)
    assert not helper.exists()


def test_sync_never_stops_a_start(make_config, http, fake_jars, monkeypatch):
    m = manager(make_config(), http, ["1.21.1"])
    assert update(m).ok
    m.config.player_ping = True

    def refuse(*a, **kw):
        raise OSError("read-only folder")
    monkeypatch.setattr(shutil, "copyfile", refuse)
    pinghelper.sync(m)                                       # (logs a warning, raises nothing)
    proc = m.start_server()
    try:
        assert proc.running
    finally:
        proc.stop(10)
    assert not (m.mods_dir / "craft_conductor_ping-fabric-1.0.0.jar").exists()


def test_start_server_puts_it_in(make_config, http, fake_jars):
    m = manager(make_config(), http, ["1.21.1"])
    assert update(m).ok
    m.config.player_ping = True
    proc = m.start_server()
    try:
        assert (m.mods_dir / "craft_conductor_ping-fabric-1.0.0.jar").read_bytes() == b"fake fabric"
    finally:
        proc.stop(10)


def write_ping(folder, body):
    path = folder / ".craft-conductor" / "ping.json"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(body if isinstance(body, bytes) else json.dumps(body).encode())
    return path


def test_read(tmp_path):
    now = 1_800_000_000.0

    def doc(**kw):
        return {"version": 1, "time": int(now * 1000) - 2000, "players": {"Alex": 42, ".Steve": 80}, **kw}

    write_ping(tmp_path, doc())
    assert pinghelper.read(tmp_path, now) == {"Alex": 42, ".Steve": 80}

    write_ping(tmp_path, doc(players={"Alex": 42, "Fast": "fast", "Neg": -1, "Flag": True, "Big": 70000,
                                      "Float": 1.5, "x" * 40: 10, "Zero": 0, "Max": 60000, "Nul": None}))
    assert pinghelper.read(tmp_path, now) == {"Alex": 42, "Zero": 0, "Max": 60000}

    for bad in (doc(time=int(now * 1000) - 16000),            # 16 s old
                doc(time=int(now * 1000) + 3_600_000),        # from the future
                doc(time="soon"), doc(time=True), doc(version=2), doc(version=True),
                doc(time=10 ** 400), doc(time=-10 ** 400), doc(time=10 ** 15), doc(time=0), doc(time=-5),  # (impossible times)
                {"version": 1, "time": int(now * 1000)},      # (no players)
                doc(players=["Alex"]), [1, 2], "text", 5):
        write_ping(tmp_path, bad)
        assert pinghelper.read(tmp_path, now) is None, bad
    write_ping(tmp_path, b"{not json")
    assert pinghelper.read(tmp_path, now) is None
    write_ping(tmp_path, b"\xff\xfe\x00")
    assert pinghelper.read(tmp_path, now) is None
    write_ping(tmp_path, (json.dumps(doc()) + " " * 70000).encode())   # (over 64 KB)
    assert pinghelper.read(tmp_path, now) is None
    write_ping(tmp_path, b"x" * (10 * 1024 * 1024))                    # 10 MB
    assert pinghelper.read(tmp_path, now) is None
    (tmp_path / ".craft-conductor" / "ping.json").unlink()
    assert pinghelper.read(tmp_path, now) is None                      # (no file)
    assert pinghelper.read(tmp_path / "nowhere", now) is None


def _good_file(folder, now):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "ping.json").write_text(json.dumps({"version": 1, "time": int(now * 1000), "players": {"Alex": 42}}))
    return folder / "ping.json"


def test_read_never_follows_a_link_to_the_file(tmp_path):
    now = 1_800_000_000.0
    outside = _good_file(tmp_path / "outside", now)
    server = tmp_path / "server"
    (server / ".craft-conductor").mkdir(parents=True)
    assert pinghelper.read(server, now) is None
    try:
        os.symlink(outside, server / ".craft-conductor" / "ping.json")
    except (OSError, NotImplementedError):
        pytest.skip("this system doesn't allow links here")
    assert pinghelper.read(server, now) is None


def test_read_never_follows_a_linked_folder(tmp_path):
    now = 1_800_000_000.0
    _good_file(tmp_path / "elsewhere", now)
    server = tmp_path / "server"
    server.mkdir()
    link = server / ".craft-conductor"
    try:
        os.symlink(tmp_path / "elsewhere", link, target_is_directory=True)
    except (OSError, NotImplementedError):
        if os.name != "nt":
            pytest.skip("this system doesn't allow links here")
        import subprocess      # (Windows: a junction needs no rights)
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(tmp_path / "elsewhere")], capture_output=True)
        if made.returncode != 0:
            pytest.skip("this system doesn't allow links here")
    assert (link / "ping.json").is_file()              # (the file is there through the link ...)
    assert pinghelper.read(server, now) is None        # (... and still isn't read)


def test_roster_reasons(hub_env, fake_jars):
    from test_hub import login
    from test_web import wait_for
    hub, c = hub_env
    login(c)
    alpha = hub.get("alpha")
    server = alpha.m.server_dir
    toml = alpha.m.config.path

    off = c.get("/api/servers/alpha/players/online")[1]["ping"]
    assert off == {"available": False, "reason": "Ping is off for this server.", "can_turn_on": True, "on": False}

    toml.write_text(toml.read_text() + "\n[players]\nping = true\n")
    alpha.m.reload_config()
    assert alpha.m.config.player_ping is True
    on = c.get("/api/servers/alpha/players/online")[1]["ping"]
    assert on["on"] and not on["available"] and on["reason"] == "Ping shows after the next restart."
    assert not on["can_turn_on"]                              # (it is on already)

    assert c.post("/api/servers/alpha/server/start")[0] == 200
    wait_for(lambda: alpha.state == "running", timeout=30)
    assert (alpha.m.mods_dir / "craft_conductor_ping-fabric-1.0.0.jar").exists()   # (put in at the start)
    alpha._on_line("[12:00:00] [Server thread/INFO]: Alex joined the game")
    alpha._on_line("[12:00:01] [Server thread/INFO]: .Steve joined the game")
    waiting = c.get("/api/servers/alpha/players/online")[1]
    assert waiting["ping"]["reason"] == "Waiting for the server to report ping…" and not waiting["ping"]["available"]

    write_ping(server, {"version": 1, "time": int(time.time() * 1000), "players": {"Alex": 42, ".Steve": 250}})
    body = c.get("/api/servers/alpha/players/online")[1]
    assert body["ping"]["available"] and body["ping"]["on"]
    shown = {p["name"]: (p["ping_ms"], p["ping_state"]) for p in body["players"]}
    assert shown == {"Alex": (42, "good"), ".Steve": (250, "poor")}    # (a Floodgate name keeps its ping)

    write_ping(server, {"version": 1, "time": int(time.time() * 1000) - 60000, "players": {"Alex": 42}})
    stale = c.get("/api/servers/alpha/players/online")[1]
    assert not stale["ping"]["available"] and stale["ping"]["reason"].startswith("Waiting")
    assert all(p["ping_ms"] is None for p in stale["players"])

    assert c.post("/api/servers/alpha/server/stop")[0] == 200
    wait_for(lambda: alpha.state == "stopped" and not alpha.job, timeout=30)

    alpha.m.lock.loader = "vanilla"                            # (switched to vanilla: it says why)
    gone = c.get("/api/servers/alpha/players/online")[1]["ping"]
    assert gone["reason"] == VANILLA and not gone["can_turn_on"] and gone["on"] and not gone["available"]


def test_turning_ping_on_needs_mods_manage(hub_env):
    from test_access import owner_ready
    from test_remote import invite
    hub, c = hub_env
    owner_ready(hub, c)
    alpha = hub.get("alpha")
    base = "/api/servers/alpha"
    assert c.get(base + "/settings")[1]["player_ping"] is False
    person, _ = invite(hub, c, "Sam", {"alpha": ["status.view", "settings.safe"]})
    assert person.post(base + "/settings", {"player_ping": True})[0] == 403
    assert alpha.m.config.player_ping is False
    assert "\nping = true" not in alpha.m.config.path.read_text()
    # (the page sends the whole form: ping unchanged needs nothing)
    assert person.post(base + "/settings", {"player_ping": False, "check_interval": "12h"})[0] == 200
    assert c.post(base + "/settings", {"player_ping": True})[0] == 200
    assert alpha.m.config.player_ping is True
    assert "\nping = true" in alpha.m.config.path.read_text()
    assert c.get(base + "/settings")[1]["player_ping"] is True
    allowed, _ = invite(hub, c, "Mia", {"alpha": ["status.view", "mods.manage"]})
    assert allowed.post(base + "/settings", {"memory": "12G"})[0] == 403      # (mods.manage is for ping only)
    assert allowed.post(base + "/settings", {"player_ping": False})[0] == 200
    assert alpha.m.config.player_ping is False
    assert c.post(base + "/settings", {"player_ping": "yes"})[0] == 400


def test_manage_mods_lists_the_helper_on_its_own(hub_env):
    from test_hub import login
    hub, c = hub_env
    login(c)
    alpha = hub.get("alpha")
    assert c.get("/api/servers/alpha/mods")[1]["helper"] is None
    alpha.m.mods_dir.mkdir(parents=True, exist_ok=True)
    (alpha.m.mods_dir / "craft_conductor_ping-fabric-1.0.0.jar").write_bytes(b"fake")
    body = c.get("/api/servers/alpha/mods")[1]
    assert body["helper"] == {"name": "Craft Conductor Ping", "filename": "craft_conductor_ping-fabric-1.0.0.jar"}
    assert "craft_conductor_ping-fabric-1.0.0.jar" not in body["unmanaged"]
