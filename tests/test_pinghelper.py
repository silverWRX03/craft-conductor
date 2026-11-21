"""Craft Conductor's side of players' ping (roadmap 47): the setting, putting the helper jar in and
taking it out at each start, and reading the file it writes (pinghelper.py)."""
import json
import os
import re
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
    for platform in ("paper", "fabric", "fabric26", "neoforge", "neoforge1.20.5", "forge"):
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
    # NeoForge from 1.20.2: up to 1.20.4 it reads META-INF/mods.toml, from 1.20.5 neoforge.mods.toml
    assert helper_jar("neoforge", "1.20.2").name == "craft_conductor_ping-neoforge-1.0.0.jar"
    assert helper_jar("neoforge", "1.20.4").name == "craft_conductor_ping-neoforge-1.0.0.jar"
    assert helper_jar("neoforge", "1.20.5").name == "craft_conductor_ping-neoforge1.20.5-1.0.0.jar"
    assert helper_jar("neoforge", "1.21.1").name == "craft_conductor_ping-neoforge1.20.5-1.0.0.jar"
    assert helper_jar("neoforge", "26.1").name == "craft_conductor_ping-neoforge1.20.5-1.0.0.jar"
    # Forge 1.20.1 (Forge 47), which runs on its own (SRG) names
    assert helper_jar("forge", "1.20.1").name == "craft_conductor_ping-forge-1.0.0.jar"
    for loader, version in (("fabric", "1.20.2-rc1"), ("fabric", "1.20.2-pre1"), ("fabric", "26-rc1"),
                            ("paper", "1.17-pre1"), ("fabric", "24w14a"), ("fabric", "latest"),
                            ("fabric", "1.20.1"), ("fabric", "1.19.4"), ("paper", "1.16.5"),
                            ("vanilla", "1.21.1"), ("neoforge", "1.20.1"), ("neoforge", "1.20.5-rc1"),
                            ("forge", "1.19.2"), ("forge", "1.20"), ("forge", "1.20.1-rc1"), ("forge", "1.20.2"),
                            ("forge", "1.21.1")):
        assert helper_jar(loader, version) is None
        assert unsupported_reason(loader, version)
    assert unsupported_reason("paper", "1.21.1") is None and unsupported_reason("fabric", "26.1") is None
    assert unsupported_reason("fabric", "1.20.1") == "Craft Conductor's ping helper needs Minecraft 1.20.2 or newer on this server type."
    assert unsupported_reason("quilt", "1.20.1") == "Craft Conductor's ping helper needs Minecraft 1.20.2 or newer on this server type."
    assert unsupported_reason("paper", "1.16.5") == "Craft Conductor's ping helper needs Minecraft 1.17 or newer on this server type."
    assert unsupported_reason("vanilla", "1.21.1") == VANILLA
    assert unsupported_reason("neoforge", "1.21.1") is None and unsupported_reason("neoforge", "1.20.2") is None
    assert unsupported_reason("neoforge", "1.20.1") == "Craft Conductor's ping helper needs Minecraft 1.20.2 or newer on this server type."
    assert unsupported_reason("forge", "1.20.1") is None
    assert unsupported_reason("forge", "1.19.2") == "Craft Conductor's ping helper needs Minecraft 1.20.1 or newer on this server type."
    # (newer Forge has no jar yet: not "too old")
    assert unsupported_reason("forge", "1.21.1") == "Craft Conductor's ping helper doesn't run on forge yet."
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


def test_sync_swaps_the_neoforge_jar_across_1_20_5(make_config, http, fake_jars):
    """NeoForge reads mods.toml up to 1.20.4 and neoforge.mods.toml from 1.20.5: a server moved across
    gets the other jar, and never both."""
    m = manager(make_config(), http, ["1.21.1"])
    assert update(m).ok
    m.config.player_ping = True
    helpers = lambda: sorted(p.name for p in m.mods_dir.iterdir() if is_helper(p.name))  # noqa: E731
    m.lock.loader, m.lock.minecraft = "neoforge", "1.20.4"
    pinghelper.sync(m)
    assert helpers() == ["craft_conductor_ping-neoforge-1.0.0.jar"]
    m.lock.minecraft = "1.20.6"
    pinghelper.sync(m)
    assert helpers() == ["craft_conductor_ping-neoforge1.20.5-1.0.0.jar"]
    assert (m.mods_dir / "craft_conductor_ping-neoforge1.20.5-1.0.0.jar").read_bytes() == b"fake neoforge1.20.5"
    m.lock.minecraft = "1.20.2"
    pinghelper.sync(m)
    assert helpers() == ["craft_conductor_ping-neoforge-1.0.0.jar"]
    m.lock.minecraft = "1.20.1"                              # (below NeoForge's floor: none)
    pinghelper.sync(m)
    assert helpers() == []


def test_sync_swaps_between_forge_and_neoforge(make_config, http, fake_jars):
    """A server switched from Forge to NeoForge (or to a Minecraft the Forge jar doesn't run on) gets the
    right jar, never two: Forge's jar on NeoForge (or the other way) would stop the start."""
    m = manager(make_config(), http, ["1.21.1"])
    assert update(m).ok
    m.config.player_ping = True
    helpers = lambda: sorted(p.name for p in m.mods_dir.iterdir() if is_helper(p.name))  # noqa: E731
    m.lock.loader, m.lock.minecraft = "forge", "1.20.1"
    pinghelper.sync(m)
    assert helpers() == ["craft_conductor_ping-forge-1.0.0.jar"]
    assert (m.mods_dir / "craft_conductor_ping-forge-1.0.0.jar").read_bytes() == b"fake forge"
    m.lock.loader, m.lock.minecraft = "neoforge", "1.20.2"
    pinghelper.sync(m)
    assert helpers() == ["craft_conductor_ping-neoforge-1.0.0.jar"]
    m.lock.loader, m.lock.minecraft = "forge", "1.20.1"
    pinghelper.sync(m)
    assert helpers() == ["craft_conductor_ping-forge-1.0.0.jar"]
    for minecraft in ("1.20.2", "1.19.2"):                   # (no Forge jar for these: none)
        m.lock.minecraft = minecraft
        pinghelper.sync(m)
        assert helpers() == []
        m.lock.minecraft = "1.20.1"
        pinghelper.sync(m)
        assert helpers() == ["craft_conductor_ping-forge-1.0.0.jar"]


def test_sync_never_stops_a_start(make_config, http, fake_jars, monkeypatch):
    m = manager(make_config(), http, ["1.21.1"])
    assert update(m).ok
    m.config.player_ping = True
    # a helper for another platform is already there (it would stop Fabric from starting)
    m.mods_dir.mkdir(parents=True, exist_ok=True)
    wrong = m.mods_dir / "craft_conductor_ping-fabric26-1.0.0.jar"
    wrong.write_bytes(b"fake fabric26")

    def refuse(*a, **kw):
        raise OSError("read-only folder")
    monkeypatch.setattr(shutil, "copyfile", refuse)
    pinghelper.sync(m)                                       # (logs a warning, raises nothing)
    assert [p.name for p in m.mods_dir.iterdir() if is_helper(p.name)] == []   # (a failed copy leaves no helper)
    proc = m.start_server()
    try:
        assert proc.running
    finally:
        proc.stop(10)
    assert not (m.mods_dir / "craft_conductor_ping-fabric-1.0.0.jar").exists()


def test_sync_does_not_write_through_a_link_planted_at_the_part_name(make_config, http, fake_jars, tmp_path):
    m = manager(make_config(), http, ["1.21.1"])
    assert update(m).ok
    m.config.player_ping = True
    target = tmp_path / "precious.txt"
    target.write_bytes(b"keep me")
    part = m.mods_dir / "craft_conductor_ping-fabric-1.0.0.jar.part"
    try:
        os.link(target, part)                                # (a hard link works on Windows too; copying onto it would write the target)
    except (OSError, NotImplementedError):
        pytest.skip("can't make a link here")
    pinghelper.sync(m)
    assert target.read_bytes() == b"keep me"
    assert (m.mods_dir / "craft_conductor_ping-fabric-1.0.0.jar").read_bytes() == b"fake fabric"
    assert not part.exists() and not part.is_symlink()


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
    assert pinghelper.FRESH_SECONDS == 30                    # (Paper's 100-tick timer is slow below ~6.7 TPS)

    def doc(**kw):
        return {"version": 1, "time": int(now * 1000) - 2000, "players": {"Alex": 42, ".Steve": 80}, **kw}

    write_ping(tmp_path, doc())
    assert pinghelper.read(tmp_path, now) == {"Alex": 42, ".Steve": 80}

    write_ping(tmp_path, doc(players={"Alex": 42, "Fast": "fast", "Neg": -1, "Flag": True, "Big": 70000,
                                      "Float": 1.5, "x" * 40: 10, "Zero": 0, "Max": 60000, "Nul": None}))
    assert pinghelper.read(tmp_path, now) == {"Alex": 42, "Zero": 0, "Max": 60000}

    for bad in (doc(time=int(now * 1000) - 31000),            # 31 s old
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


def test_support_matches_the_ranges_the_jars_declare():
    """SUPPORT (which jar goes where) and each shipped jar's own Minecraft range must say the same, or a
    server could be handed a jar that Fabric (or NeoForge) refuses to start with."""
    import zipfile
    for loaders, lowest, below, platform in pinghelper.SUPPORT:
        jar = sorted(pinghelper.JARS_DIR.glob(f"{pinghelper.PREFIX}{platform}-*.jar"))[-1]
        with zipfile.ZipFile(jar) as z:
            if platform == "paper":
                yml = z.read("plugin.yml").decode("utf-8").splitlines()
                assert f'api-version: "{lowest}"' in yml and below is None
            elif platform.startswith(("neoforge", "forge")):
                import tomllib
                toml = "META-INF/mods.toml" if "META-INF/mods.toml" in z.namelist() else "META-INF/neoforge.mods.toml"
                deps = tomllib.loads(z.read(toml).decode("utf-8"))["dependencies"]["craft_conductor_ping"]
                [declared] = [d["versionRange"] for d in deps if d["modId"] == "minecraft"]
                assert declared == f"[{lowest},{below or ''})"
            else:
                declared = json.loads(z.read("fabric.mod.json"))["depends"]["minecraft"]
                assert declared == f">={lowest}" + (f" <{below}" if below else "")


def test_pre_releases_get_no_helper():
    """Fabric puts 1.20.2-rc1 below >=1.20.2 and refuses the mod, so only plain releases get a jar."""
    for v in ("1.20.2-rc1", "1.20.2-pre1", "26-rc1", "26.1-pre2", "1.21.1-beta"):
        assert helper_jar("fabric", v) is None and helper_jar("quilt", v) is None, v
        assert unsupported_reason("fabric", v)
    assert helper_jar("paper", "1.21.4-rc1") is None
    assert helper_jar("fabric", "1.20.2").name == "craft_conductor_ping-fabric-1.0.0.jar"


def test_the_page_words_match_the_reasons():
    """webui/app.js turns the card's reasons back into their translatable text (PING_REASONS); its patterns
    and templates must match what pinghelper says."""
    from pathlib import Path
    js = (Path(pinghelper.__file__).parent / "webui" / "app.js").read_text(encoding="utf-8")
    block = js[js.index("const PING_REASONS = ["):]
    block = block[:block.index("];")]
    found = re.findall(r'\[/(.+?)/, "(.+?)", "(\{\w+\})"\]', block)
    assert len(found) == 2, found
    wanted = {pinghelper.TOO_OLD_REASON: ("1.17", "version"), pinghelper.NOT_YET_REASON: ("neoforge", "loader")}
    for pattern, template, slot in found:
        assert template in wanted, template
        value, name = wanted[template]
        assert slot == "{" + name + "}"
        shown = template.format(**{name: value})            # (what the server fills in)
        match = re.fullmatch(pattern.replace("\S", r"\S"), shown)
        assert match and match.group(1) == value, (pattern, shown)
