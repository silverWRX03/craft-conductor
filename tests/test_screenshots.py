"""The pictures in the user manual, the Help page, the wiki and the README: every page of the control
panel, with example servers made up here (like the rest of the tests, never anyone's real server).

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> \\
    CRAFT_UI_SCREENSHOTS=src/craft_conductor/webui/screenshots pytest tests/test_screenshots.py

It needs Pillow (pip install pillow) to keep the pictures small: they ship with Craft Conductor.
CRAFT_UI_CHANNEL picks the browser (msedge on Windows unless set). The map preview needs a real
world to draw: set CRAFT_UI_WORLD to a world folder to retake it, otherwise the one there is kept.
Run it twice when the Help page changes: Help shows the pictures taken the time before.
"""

import base64
import json
import os
import random
import shutil
import struct
import subprocess
import textwrap
import threading
import time
import uuid
import zlib
from pathlib import Path

import pytest

from conftest import FakeLoader, FakeMojang
from test_friends import pack
from test_preview import chunk, write_world
from test_web import Client, wait_for

pytestmark = pytest.mark.skipif(not (os.environ.get("CRAFT_UI_NODE") and os.environ.get("CRAFT_UI_SCREENSHOTS")),
                                reason="documentation screenshots, taken on request")

ROOT = Path(__file__).resolve().parent.parent
RELEASES = ["1.21.1", "1.21.4"]
# (slug, title, its version for 1.21.1, that file, its build for 1.21.4: "release", "beta" or None)
MODS = [
    ("fabric-api", "Fabric API", "0.107.0+1.21.1", "fabric-api-0.107.0+1.21.1.jar", "release"),
    ("lithium", "Lithium", "mc1.21.1-0.14.3", "lithium-fabric-mc1.21.1-0.14.3.jar", "release"),
    ("ferrite-core", "FerriteCore", "7.0.2", "ferritecore-7.0.2-fabric.jar", "release"),
    ("krypton", "Krypton", "0.2.8", "krypton-0.2.8.jar", "beta"),
    ("terralith", "Terralith", "2.5.5", "Terralith_1.21.1_v2.5.5.jar", None),
    ("chunky", "Chunky", "1.4.23", "Chunky-Fabric-1.4.23.jar", "release"),
    ("spark", "spark", "1.10.109", "spark-1.10.109-fabric.jar", "release"),
    ("simple-voice-chat", "Simple Voice Chat", "fabric-1.21.1-2.5.24", "voicechat-fabric-1.21.1-2.5.24.jar", "release"),
    ("bluemap", "BlueMap", "5.4", "bluemap-5.4-fabric.jar", "release"),
    ("xaeros-minimap", "Xaero's Minimap", "24.6.1", "Xaeros_Minimap_24.6.1_Fabric_1.21.jar", "release"),
]
PLAYERS = ["Alex", "Sam_Builds", "KaiCrafts", "Mia", "JordanMC", "Riley", "Noor", "Griefer42", "LenaPlays", "Bruno_77"]
ONLINE = ["Alex", "KaiCrafts", "Mia", "Sam_Builds", "JordanMC", "Riley", "Noor", "LenaPlays", "Bruno_77"]

# A stand-in for Minecraft that looks like it in the console: it starts, takes connections on its
# port (on this computer only), lets players in, answers the commands Craft Conductor sends, and
# fails to start the way Fabric does when a mod is missing.
DOCS_SERVER = textwrap.dedent('''\
    import pathlib, socket, sys, threading, time
    here = pathlib.Path(".")
    def say(text, thread="Server thread", level="INFO"):
        print(f"[{time.strftime('%H:%M:%S')}] [{thread}/{level}]: {text}", flush=True)
    jars = sorted(p.name for p in (here / "mods").glob("*.jar")) if (here / "mods").is_dir() else []
    minecraft = next((p.name[8:-4] for p in here.glob("runtime-*.txt")), "1.21.1")
    port = "25565"
    for line in (here / "server.properties").read_text().splitlines() if (here / "server.properties").exists() else []:
        if line.startswith("server-port="):
            port = line.split("=", 1)[1]
    say(f"Loading Minecraft {minecraft} with Fabric Loader 0.16.9", "main")
    say(f"Loading {len(jars) + 3} mods:", "main")
    for jar in jars:
        say(f"  - {jar[:-4]}", "main")
    if any(j.startswith("betterend") for j in jars):
        say("Incompatible mods found!", "main", "ERROR")
        print(" - Mod 'Better End' (betterend) 21.0.11 requires version 21.0.0 or later of mod 'BCLib' (bclib), "
              "which is missing!", flush=True)
        sys.exit(1)
    say("Environment: Environment[sessionHost=https://sessionserver.mojang.com]", "main")
    say(f"Starting minecraft server version {minecraft}")
    say("Loading properties")
    say("Default game type: SURVIVAL")
    say("Generating keypair")
    say(f"Starting Minecraft server on *:{port}")
    say("Using epoll channel type")
    say('Preparing level "world"')
    say("Preparing start region for dimension minecraft:overworld")
    say("Preparing spawn area: 100%", "Worker-Main-2")
    def listen():
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", int(port)))
            s.listen()
        except OSError:
            return
        while True:
            s.accept()[0].close()
    threading.Thread(target=listen, daemon=True).start()
    say('Done (6.482s)! For help, type "help"')
    online = []
    players = here / "players.txt"
    if players.exists():
        chat = {"Alex": "anyone up for the nether fortress?", "Mia": "omw, bringing fire res",
                "KaiCrafts": "the new bridge is done :)"}
        for name in players.read_text().split():
            online.append(name)
            say(f"{name} joined the game")
            if name in chat:
                say(f"<{name}> {chat[name]}")
    rules = {"keepInventory": "true", "doDaylightCycle": "true", "doWeatherCycle": "true", "doMobSpawning": "true",
             "mobGriefing": "false", "doFireTick": "true", "doInsomnia": "false", "naturalRegeneration": "true",
             "playersSleepingPercentage": "50", "announceAdvancements": "true", "showDeathMessages": "true",
             "spawnRadius": "10"}
    for line in sys.stdin:
        cmd = line.strip()
        words = cmd.split()
        if cmd == "list":
            say(f"There are {len(online)} of a max of 20 players online: {', '.join(online)}")
        elif cmd == "tick query":
            say("The game is running normally")
            say("Target tick rate: 20.0 per second.")
            say("Average time per tick: 21.7ms (Target: 50.0ms)")
            say("Percentiles: P50: 20.9ms P95: 27.3ms P99: 31.8ms, sample: 100")
        elif words[:1] == ["gamerule"] and len(words) == 2 and words[1] in rules:
            say(f"Gamerule {words[1]} is currently set to: {rules[words[1]]}")
        elif words[:1] == ["gamerule"] and len(words) == 3 and words[1] in rules:
            rules[words[1]] = words[2]
            say(f"Gamerule {words[1]} is now set to: {words[2]}")
        elif words[:1] == ["gamerule"]:
            say("Incorrect argument for command")
        elif cmd == "worldborder get":
            say("The world border is currently 8000 blocks wide")
        elif cmd == "save-off":
            say("Automatic saving is now disabled")
        elif cmd.startswith("save-all"):
            say("Saving the game (this may take a moment!)")
            say("Saved the game")
        elif cmd == "save-on":
            say("Automatic saving is now enabled")
        elif cmd.startswith("say "):
            say(f"[Server] {cmd[4:]}")
        elif cmd == "stop":
            say("Stopping the server")
            say("Saving players")
            say("Saving worlds")
            sys.exit(0)
''')


class DocsLoader(FakeLoader):
    def latest_version(self, minecraft):
        return "0.16.9" if minecraft in RELEASES else None

    def install(self, minecraft, version, dest, java):
        runtime = super().install(minecraft, version, dest, java)
        (dest / "fake_server.py").write_text(DOCS_SERVER)
        return runtime


def docs_manager(cfg, http):
    from craft_conductor.manager import Manager
    from craft_conductor.minecraft import MANIFEST_URL
    from craft_conductor.mods import providers_for
    mojang = FakeMojang(http, RELEASES)
    for v in http.json[MANIFEST_URL]["versions"]:  # (out a few weeks: mods are still catching up)
        days = {"1.21.4": 12, "1.21.1": 200}.get(v["id"], 1)
        v["releaseTime"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - days * 86400))
        if v["type"] == "snapshot":
            v["id"] = "25w02a"
    return Manager(cfg, http=http, mojang=mojang, loader=DocsLoader(http, mojang), providers=providers_for(cfg, http),
                   echo=False, sleep=lambda s: None)


def managed_java(store: Path, fake_java: Path) -> None:
    """A Java 21 in the shared Java folder, running the stand-in server.
    (Named as on Windows elsewhere too: the pictures show Windows paths.)"""
    from craft_conductor.java import META
    folder = store / "21" / "jdk-21.0.4+7"
    name = fake_java.name if os.name == "nt" else "java.exe"
    (folder / "jdk-21.0.4+7-jre" / "bin").mkdir(parents=True)
    shutil.copy2(fake_java, folder / "jdk-21.0.4+7-jre" / "bin" / name)
    (folder / META).write_text(json.dumps({"major": 21, "release": "jdk-21.0.4+7", "semver": "21.0.4+7",
                                           "java": f"jdk-21.0.4+7-jre/bin/{name}", "installed_at": time.time() - 9 * 86400,
                                           "bytes": 141_300_000}))


def installed_javas(programs: Path, monkeypatch) -> None:
    """Java the owner installed themselves (as if in C:\\Program Files): a JDK 17 and an old 32-bit Java 8."""
    from craft_conductor import java as javamod
    kinds = {"jdk-17.0.12.7-hotspot": javamod.JavaInfo(17, "x64", "17.0.12+7", "Microsoft"),
             "jre1.8.0_421": javamod.JavaInfo(8, "x32", "1.8.0_421-b09", "Oracle Corporation")}
    for vendor, name in (("Microsoft", "jdk-17.0.12.7-hotspot"), ("Java", "jre1.8.0_421")):
        (programs / vendor / name / "bin").mkdir(parents=True)
        (programs / vendor / name / "bin" / "java.exe").write_text("")
        (programs / vendor / name / "bin" / "java.exe").chmod(0o755)
    real = javamod.run_version
    # (and not the java of the computer taking the pictures)
    monkeypatch.setattr(javamod, "run_version", lambda b: None if b == "java" else kinds.get(Path(b).parent.parent.name) or real(b))
    monkeypatch.setattr(javamod, "install_folders", lambda: [str(programs / "*" / "*" / "bin" / "java.exe")])
    monkeypatch.setattr(javamod, "host_platform", lambda: ("windows", "x64"))


def make_server(http, fake_java, root: Path, mods: list[str], **spec):
    """A server set up and installed the way New server does it."""
    from craft_conductor import config as configmod, setup as setupmod
    setupmod.configure(root, setupmod.SetupSpec.from_dict({"loader": "fabric", "minecraft": RELEASES[0], "mods": mods,  # (a server stays on the Minecraft chosen for it)
                                                           "accept_eula": True, **spec}))
    m = docs_manager(configmod.load(root), http)
    decision, _ = m.check()
    assert decision.plan is not None and m.apply(decision.plan).ok
    return m


def shrink(path: Path) -> None:
    """256 colours: a third of the size, and screens of flat colours look the same."""
    from PIL import Image
    with Image.open(path) as image:
        small = image.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    small.save(path, "PNG", optimize=True)


def grass_icon() -> bytes:
    """A 64x64 server icon: the side of a grass block."""
    green, dirt = [(89, 145, 53), (106, 170, 64), (76, 128, 44)], [(134, 96, 67), (121, 85, 58), (150, 108, 80)]
    pattern = ["01002010", "10200102", "0a01b0a0", "abcaacb1", "baacbaab", "acbaabca", "caabcaab", "abcaabac"]
    pixel = lambda ch: green[int(ch)] if ch.isdigit() else dirt["abc".index(ch)]  # noqa: E731
    rows = [b"\0" + b"".join(bytes(pixel(ch)) * 8 for ch in line) for line in pattern for _ in range(8)]

    def part(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    return (b"\x89PNG\r\n\x1a\n" + part(b"IHDR", struct.pack(">IIBBBBB", 64, 64, 8, 2, 0, 0, 0))
            + part(b"IDAT", zlib.compress(b"".join(rows))) + part(b"IEND", b""))


def grow_world(server: Path, name: str, mb: int) -> None:
    """More of the world explored (bytes that don't compress, so backups have a real size)."""
    (server / "world" / "region" / name).write_bytes(random.Random(name).randbytes(mb << 20))


def players_files(server: Path) -> None:
    """Who has played here, the operators, the whitelist and a ban, as Minecraft keeps them."""
    ids = {name: str(uuid.uuid5(uuid.NAMESPACE_DNS, name)) for name in PLAYERS}
    later = time.strftime("%Y-%m-%d %H:%M:%S +0000", time.gmtime(time.time() + 30 * 86400))
    (server / "usercache.json").write_text(json.dumps([{"name": n, "uuid": u, "expiresOn": later} for n, u in ids.items()]))
    (server / "ops.json").write_text(json.dumps([{"name": "Alex", "uuid": ids["Alex"], "level": 4, "bypassesPlayerLimit": False},
                                                 {"name": "Riley", "uuid": ids["Riley"], "level": 2, "bypassesPlayerLimit": False}]))
    (server / "whitelist.json").write_text(json.dumps([{"name": n, "uuid": ids[n]} for n in PLAYERS if n != "Griefer42"]))
    (server / "banned-players.json").write_text(json.dumps([{
        "name": "Griefer42", "uuid": ids["Griefer42"], "created": "2026-09-21 20:14:03 +0000", "source": "Alex",
        "expires": "forever", "reason": "Burned down the village"}]))


def play_history(activity) -> None:
    """A month of evenings and weekend afternoons, the same every time the pictures are taken."""
    rng = random.Random(7)
    now = time.time()
    regulars = [n for n in PLAYERS if n != "Griefer42"]
    for day in range(30, 0, -1):
        midnight = now - now % 86400 - day * 86400
        weekend = time.gmtime(midnight).tm_wday >= 5
        for name in regulars:
            if rng.random() < (0.75 if weekend else 0.45):
                hour = rng.choice([14, 15, 16]) if weekend and rng.random() < .5 else rng.choice([18, 19, 20])
                start = midnight + hour * 3600 + rng.randrange(3600)
                activity.joined(name, start)
                activity.left(name, start + rng.randrange(40, 200) * 60)


def test_documentation_screenshots(tmp_path, http, modrinth, fake_java, monkeypatch):
    pytest.importorskip("PIL", reason="pip install pillow (it keeps the pictures small)")
    from craft_conductor import areas, backup, cli, health, join, joinui, perf, setup as setupmod, singleplayer, snapshots, stats
    from craft_conductor import config as configmod
    from craft_conductor.clientpack import make_link
    from craft_conductor.hub import Hub
    from craft_conductor.mods.modrinth import API
    from craft_conductor.properties import write_properties

    # This computer, as the pictures show it: not the one taking them.
    monkeypatch.setattr(cli, "lan_ip", lambda: "192.168.1.50")
    monkeypatch.setattr(setupmod, "total_ram_gb", lambda: 32.0)
    monkeypatch.setattr(health, "memory_available_gb", lambda: 18.5)
    disk = shutil._ntuple_diskusage(1000 * 1024 ** 3, 412 * 1024 ** 3, 588 * 1024 ** 3)
    monkeypatch.setattr(shutil, "disk_usage", lambda path: disk)
    monkeypatch.setattr(stats, "sample", lambda pid: (int(3.1 * 1024 ** 3), time.monotonic() * 0.28 * (os.cpu_count() or 1)))
    if os.environ.get("CRAFT_UI_WORLD"):  # the map preview draws a real world instead of making one
        from craft_conductor import preview
        monkeypatch.setattr(preview.MapSession, "generate", lambda session, center, radius, report=None:
                            shutil.copytree(os.environ["CRAFT_UI_WORLD"], session.world, dirs_exist_ok=True))

    for slug, title, number, filename, newer in MODS:
        modrinth.project(slug.upper(), slug, title,
                         client_side="required" if slug in ("xaeros-minimap", "simple-voice-chat") else "optional")
        modrinth.version(slug.upper(), number, ["1.21.1"], filename=filename)
        if newer:
            nxt = lambda s: s.replace("1.21.1", "1.21.4") if "1.21.1" in s else s.replace(".jar", "+1.21.4.jar")  # noqa: E731
            modrinth.version(slug.upper(), nxt(number + ".jar")[:-4] + ("-beta.1" if newer == "beta" else ""), ["1.21.4"],
                             filename=nxt(filename), version_type=newer)
    lithium = {**http.json[f"{API}/project/LITHIUM"], "description": "No-compromises game logic optimization mod.",
               "body": "Lithium makes the game's own logic faster: mob AI, block ticking, collisions, chunk loading and "
                       "more, while keeping how the game plays exactly the same.\n\n## What it helps\n\n"
                       "- Mobs and their pathfinding\n- Hoppers, redstone and other block updates\n- Entity collisions and "
                       "physics\n\nIt runs on servers and in single-player, and goes well with FerriteCore and Krypton.",
               "downloads": 42_800_000, "followers": 1_070_000, "categories": ["optimization"],
               "license": {"name": "LGPL-3.0-only"}, "updated": "2026-09-12T10:00:00Z", "loaders": ["fabric", "neoforge"],
               "game_versions": ["1.21.1", "1.21.4"], "source_url": "https://github.com/CaffeineMC/lithium"}
    http.json[f"{API}/project/LITHIUM"] = http.json[f"{API}/project/lithium"] = lithium
    # The mod browser's search: what Modrinth answers.
    hits = [{"project_id": slug.upper(), "slug": slug, "title": title, "description": desc, "project_type": "mod",
             "downloads": downloads, "follows": downloads // 40, "server_side": "required", "client_side": side,
             "categories": cats, "versions": ["1.21.1", "1.21.4"], "author": author}
            for slug, title, desc, downloads, side, cats, author in [
                ("lithium", "Lithium", "No-compromises game logic optimization mod. Well suited for clients and servers of all kinds.",
                 42_800_000, "optional", ["optimization"], "jellysquid3"),
                ("ferrite-core", "FerriteCore", "Memory usage optimizations", 38_100_000, "optional", ["optimization"], "malte0811"),
                ("krypton", "Krypton", "A mod to optimize the Minecraft networking stack", 12_400_000, "unsupported",
                 ["optimization"], "astei"),
                ("terralith", "Terralith", "Explore almost 100 new biomes consisting of both realism and light fantasy, using just Vanilla blocks.",
                 21_900_000, "optional", ["worldgen", "adventure"], "Stardust Labs"),
                ("chunky", "Chunky", "Pre-generates chunks, quickly and efficiently", 9_800_000, "unsupported", ["utility"], "pop4959"),
                ("simple-voice-chat", "Simple Voice Chat", "A working voice chat in Minecraft!", 31_200_000, "required",
                 ["social", "utility"], "henkelmax"),
                ("spark", "spark", "spark is a performance profiler for Minecraft clients, servers, and proxies.", 17_500_000,
                 "optional", ["utility"], "lucko"),
                ("bluemap", "BlueMap", "A Minecraft mapping tool that creates 3D models of your Minecraft worlds and displays them in a web viewer.",
                 2_100_000, "unsupported", ["utility"], "Blue")]]
    http.json[f"{API}/search"] = lambda params: (lambda found: {"total_hits": len(found), "hits": found, "offset": 0, "limit": 20})(
        [h for h in hits if "worldgen" in h["categories"] or "worldgen" not in params.get("facets", "")])

    home = tmp_path / "home"
    servers = home / "servers"
    now = time.time()
    from craft_conductor import java as javamod
    store = home / ".craft-conductor" / "java"
    monkeypatch.setattr(javamod, "default_store", lambda: store)
    managed_java(store, fake_java)
    installed_javas(tmp_path / "Program Files", monkeypatch)
    # The main server: friends play on it every evening. Its backups go back a week.
    survival = servers / "survival"
    m = make_server(http, fake_java, survival, [s for s, *_ in MODS if s not in ("simple-voice-chat", "bluemap", "xaeros-minimap")],
                    motd="Survival with friends", memory_gb=6)
    write_world(m.server_dir / "world", {(x, z): chunk(x, z, block="minecraft:grass_block" if (x + z) % 5 else "minecraft:water")
                                         for x in range(-4, 4) for z in range(-4, 4)}, spawn=(8, 8))
    (m.server_dir / "server-icon.png").write_bytes(grass_icon())
    made = []
    day = lambda days_ago, hour: now - now % 86400 - days_ago * 86400 + hour * 3600 + 17 * 60  # noqa: E731

    def back_up(label, when):
        """A backup as if it had been made then."""
        path = backup.create(m.server_dir, m.config.backups.dir, label, m.config.backups.exclude)
        snapshots.record(path, m)
        made.append((path, when))
    grow_world(m.server_dir, "r.2.2.mca", 9)
    back_up("scheduled", day(6, 4))
    grow_world(m.server_dir, "r.2.3.mca", 4)
    configmod.append_mod(survival / configmod.CONFIG_NAME, configmod.ModSpec("modrinth", "simple-voice-chat"))
    m.reload_config()
    decision, _ = m.check()
    assert decision.plan is not None and m.apply(decision.plan).ok  # (a backup first, then Simple Voice Chat)
    made.append((next(p for p in backup.list_backups(m.config.backups.dir) if "before-mod-updates" in p.name), day(3, 19)))
    grow_world(m.server_dir, "r.3.2.mca", 3)
    back_up("scheduled", day(1, 4))
    grow_world(m.server_dir, "r.3.3.mca", 2)
    back_up("before-the-castle", now - 2 * 3600)
    for path, when in made:  # (named and dated as if made then, and checked as Craft Conductor does)
        dated = path.with_name(time.strftime("%Y%m%d-%H%M%S", time.localtime(when)) + "-" + path.name.split("-", 2)[2])
        path.rename(dated)
        if (note := path.with_name(path.name + ".json")).exists():
            note.rename(dated.with_name(dated.name + ".json"))
        os.utime(dated, (when, when))
        areas.check(m.config.backups.dir, dated.name)
    players_files(m.server_dir)
    write_properties(m.server_dir / "server.properties", {"white-list": "true", "enforce-whitelist": "true"})
    (m.server_dir / "players.txt").write_text(" ".join(ONLINE))
    configmod.set_value(m.config.path, "client", "enabled", "true")
    configmod.set_value(m.config.path, "client", "mods", json.dumps(["xaeros-minimap"]))
    make_link(m.config.path, 7)
    # A creative world for building, stopped.
    make_server(http, fake_java, servers / "creative", ["fabric-api", "lithium"], motd="Creative builds",
                gamemode="creative", port=25566, memory_gb=4)
    # A modded server whose new mod needs another one: it won't start, and the Dashboard says why.
    adventure = make_server(http, fake_java, servers / "adventure", ["fabric-api"], motd="Modded adventure", port=25567,
                            memory_gb=8)
    (adventure.server_dir / "mods" / "betterend-21.0.11.jar").write_bytes(b"example")

    hub = Hub(home, make_manager=lambda cfg: docs_manager(cfg, http), http=http, tick=0.1)
    hub.web.port = 0
    hub.save_share(8766, "203.0.113.25")  # (a documentation address, not a real one)
    t = threading.Thread(target=hub.run, daemon=True)
    t.start()
    try:
        wait_for(lambda: hub.ui is not None and hub.ui.httpd is not None and {"survival", "creative", "adventure"} <= set(hub.daemons))
        main = hub.get("survival")
        play_history(main.activity)
        main.meter = perf.Meter()
        rng = random.Random(3)
        for i in range(60, 0, -1):
            mspt = round(rng.uniform(52, 61) if rng.random() < .15 else rng.uniform(15, 31), 1)
            main.meter.samples.append({"tps": round(min(20.0, 1000 / mspt), 1), "mspt": mspt, "time": now - i * 60})
        main.start_server()
        wait_for(lambda: set(ONLINE) <= main.players)
        broken = hub.get("adventure")  # (Start, as the button does it)
        assert broken.submit("start", broken.start_server)
        wait_for(lambda: broken.last_job and broken.last_job["name"] == "start", timeout=30)
        broken.want_running = False
        assert broken.problem and broken.problem["cause"] == "missing", broken.problem
        singleplayer.create(hub, name="Cozy modded survival", loader="fabric", minecraft="latest",
                            mods=["lithium", "xaeros-minimap"], memory_gb=4)

        # A friend's side: the invite page as GitHub Pages has it (.github/workflows/pages.yml), and
        # their Craft Conductor's page for setting up Minecraft.
        site = tmp_path / "_site"
        shutil.copytree(ROOT / "site", site)
        shutil.copy2(ROOT / "src" / "craft_conductor" / "webui" / "icon.png", site / "icon.png")
        invite = join.Invite("203.0.113.25", 8766, "A" * 24, "F" * 43)
        mods = [{"name": title, "filename": filename, "url": f"https://cdn.modrinth.com/data/{slug.upper()}/{filename}",
                 "sha1": "0" * 40, "side": "both"} for slug, title, _, filename, _ in MODS
                if slug in ("fabric-api", "simple-voice-chat", "xaeros-minimap")]
        http.json[invite.url + "/pack.json"] = pack(name="Survival with friends", address="203.0.113.25", mods=mods,
                                                    loader_version="0.16.9", whitelist=True,
                                                    icon="data:image/png;base64," + base64.b64encode(grass_icon()).decode())
        mc = tmp_path / "friend" / ".minecraft"
        mc.mkdir(parents=True)
        (mc / "launcher_profiles.json").write_text("{}")
        friend = joinui.JoinUI(invite, mc_dir=mc, http=http, prism_dir=tmp_path / "friend" / "prism", out_dir=tmp_path / "friend")
        friend.open_browser = lambda url: None
        friend_url = friend.start()
        try:
            env = {**os.environ, "CRAFT_UI_HOME": str(home), "CRAFT_UI_FRIEND": friend_url,
                   "CRAFT_UI_PROGRAMS": str(tmp_path / "Program Files"),
                   "CRAFT_UI_INVITE": invite.page_link("Survival with friends").split("#", 1)[1],
                   "CRAFT_UI_SITE": str(site / "join" / "index.html")}
            result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_screenshots.cjs")),
                                     Client(hub.ui.url.rstrip("/")).base], capture_output=True, text=True, timeout=600, env=env)
            assert result.returncode == 0, result.stdout + result.stderr
            for line in result.stdout.splitlines():
                if line.startswith("took "):
                    shrink(Path(os.environ["CRAFT_UI_SCREENSHOTS"]) / f"{line[5:]}.png")
        finally:
            friend.stop()
    finally:
        hub.stop_requested.set()
        t.join(30)
