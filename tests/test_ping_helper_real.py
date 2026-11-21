"""Craft Conductor Ping on real Fabric, Quilt, NeoForge, Forge and Paper servers (roadmap 47).

Optional: skipped unless CRAFT_REAL_SERVERS=1 and CRAFT_MINEFLAYER is the path to the mineflayer
package (``.../node_modules/mineflayer``), with ``node`` on PATH. Each version downloads Minecraft,
Fabric (Quilt, NeoForge, Forge, Paper) and, where this computer has no fitting Java, Temurin into pytest's
temporary folders, so a run takes several minutes and needs the internet.

For each server type and Minecraft version: a server made through Craft Conductor's own setup and
Manager (``online-mode=false``, only in these throwaway servers, so the bot can join) with
``[players] ping = true`` in its craft-conductor.toml, started: ``start_server`` puts the right shipped
helper jar into the mods (or plugins) folder itself (pinghelper.sync); a mineflayer bot joins, and ``.craft-conductor/ping.json``
must list the bot with a whole number within 20 seconds, and the server's log must hold the helper's
start line and nothing else from it. The bot is a plain Minecraft client, so its joining also shows
that players need nothing installed (NeoForge and Forge turn away a client missing a mod they need).
On Forge the bot answers the server's keep-alives late, so its ping must come out above 0: the value is
the player's latency, which only those answers set (a local bot otherwise shows 0); and every Minecraft
field and method the helper uses must be in the server's Minecraft jar on the names Forge runs it on
(Forge's own SRG names up to 1.20.4, Mojang's from 1.20.6).
mineflayer speaks Minecraft up to 26.1: on a newer version the bot can't join, so the test checks
that the helper loads and writes the file, and that every Minecraft field and method the helper uses
is in that version's (unobfuscated) server jar (for NeoForge, the one it patched).
"""
from __future__ import annotations

import json
import os
import socket
import struct
import subprocess
import time
import zipfile
from pathlib import Path

import pytest

from craft_conductor import config as configmod, java as javamod, pinghelper
from craft_conductor import setup as setupmod
from craft_conductor.http import HttpClient
from craft_conductor.manager import Manager

MINEFLAYER = os.environ.get("CRAFT_MINEFLAYER", "")
pytestmark = pytest.mark.skipif(
    os.environ.get("CRAFT_REAL_SERVERS") != "1" or not MINEFLAYER,
    reason="real servers: set CRAFT_REAL_SERVERS=1 and CRAFT_MINEFLAYER=<path to the mineflayer package>")

BOT_NAME = "PingBot"
START = "Craft Conductor Ping: reporting players' ping to Craft Conductor"   # (the helper's one log line)

# Fabric: the oldest supported, two in between, the last 1.x, then every 26.x up to the newest
# Fabric supports. Quilt (which runs Fabric mods): one version for each jar.
SERVERS = [("fabric", v) for v in ("1.20.2", "1.20.4", "1.21.1", "1.21.11", "26.1", "26.2", "26.3")] \
    + [("quilt", "1.21.1"), ("quilt", "26.1")]

# NeoForge: the first version of each jar (1.20.2: mods.toml; 1.20.6, as 1.20.5 has only beta NeoForge
# builds, which Craft Conductor doesn't install: neoforge.mods.toml), 1.20.4 (NeoForge 20.4 reads the
# metadata differently), 1.21.1, the last 1.x, 26.1 (Minecraft without obfuscation) and the newest.
NEOFORGE = [("neoforge", v) for v in ("1.20.2", "1.20.4", "1.20.6", "1.21.1", "1.21.11", "26.1", "26.3")]

# Forge: for each Minecraft version the build Craft Conductor installs (Forge's recommended one, else its
# latest), and older builds a modpack may pin (a pack's server runs the pack's Forge). 1.20.1 (the forge
# jar): 47.1.0, the first recommended, and 47.0.0. 1.20.2 to 1.20.4 (forge1.20.2, SRG names): 1.20.2 and
# 48.0.0, the first, and 1.20.4 (Forge's only 1.20.3 build, 49.0.2, installs a server Craft Conductor
# can't start yet). 1.20.6 and newer (forge1.20.6, Mojang's names): 1.20.6 and 50.1.0 (on 50.0.x mineflayer
# can't read what the server sends, so it can't answer keep-alives), 1.21.1, the last 1.21.x, 26.1
# (Minecraft without obfuscation) and the newest.
FORGE = [("1.20.1", None), ("1.20.1", "47.1.0"), ("1.20.1", "47.0.0"),
         ("1.20.2", None), ("1.20.2", "48.0.0"), ("1.20.4", None),
         ("1.20.6", None), ("1.20.6", "50.1.0"), ("1.21.1", None), ("1.21.11", None), ("26.1", None), ("26.3", None)]
KEEPALIVE_DELAY_MS = 400   # (how late the bot answers Forge's keep-alives)

BOT = r"""
// node bot.js <mineflayer> <port> <version> <name> [delay]: joins 127.0.0.1 in offline mode and stays;
// with a delay (ms), it answers the server's keep-alives that late (so its ping isn't 0).
const [mineflayerPath, port, version, username, delay] = process.argv.slice(2);
const mineflayer = require(mineflayerPath);
const minecraftData = require(require.resolve('minecraft-data', { paths: [mineflayerPath] }));
if (!minecraftData(version)) { console.log('unsupported', version); process.exit(3); }
const bot = mineflayer.createBot({ host: '127.0.0.1', port: +port, username, auth: 'offline', version,
                                   keepAlive: !delay });
if (delay) {
  bot._client.on('keep_alive', (packet) => setTimeout(() => {
    bot._client.write('keep_alive', { keepAliveId: packet.keepAliveId });
  }, +delay));
}
bot.once('spawn', () => console.log('spawned'));
bot.on('kicked', (reason) => console.log('kicked', JSON.stringify(reason).slice(0, 300)));
bot.on('error', (e) => console.log('error', e.message));
bot.on('end', (reason) => { console.log('end', reason); process.exit(1); });
"""


def _class_file(data: bytes) -> dict:
    """What a class file says: its super class, its own (kind, name, descriptor) members, and the
    (kind, class, name, descriptor) of the fields and methods it uses."""
    u2 = lambda at: struct.unpack_from(">H", data, at)[0]  # noqa: E731
    count, pos, pool, i = u2(8), 10, {}, 1
    while i < count:
        tag = data[pos]
        if tag == 1:
            n = u2(pos + 1)
            pool[i] = data[pos + 3:pos + 3 + n].decode("utf-8", "replace")
            pos += 3 + n
        elif tag in (7, 8, 16, 19, 20):
            pool[i], pos = (tag, u2(pos + 1)), pos + 3
        elif tag in (9, 10, 11, 12, 17, 18):
            pool[i], pos = (tag, u2(pos + 1), u2(pos + 3)), pos + 5
        elif tag in (3, 4):
            pos += 5
        elif tag in (5, 6):
            pos, i = pos + 9, i + 1  # (takes two entries)
        elif tag == 15:
            pos += 4
        else:
            raise ValueError(f"constant pool tag {tag}")
        i += 1
    cls = lambda k: pool[pool[k][1]]  # noqa: E731
    uses = set()
    for entry in pool.values():
        if isinstance(entry, tuple) and entry[0] in (9, 10, 11):
            nat = pool[entry[2]]
            uses.add(("field" if entry[0] == 9 else "method", cls(entry[1]), pool[nat[1]], pool[nat[2]]))
    super_index = u2(pos + 4)
    pos += 8 + 2 * u2(pos + 6)
    members = set()
    for kind in ("field", "method"):
        n, pos = u2(pos), pos + 2
        for _ in range(n):
            members.add((kind, pool[u2(pos + 2)], pool[u2(pos + 4)]))
            attrs, pos = u2(pos + 6), pos + 8
            for _ in range(attrs):
                pos += 6 + struct.unpack_from(">I", data, pos + 2)[0]
    return {"super": cls(super_index) if super_index else None, "members": members, "uses": uses}


def _missing_in(server_jar: Path, helper_jar: Path) -> list[tuple]:
    """The Minecraft fields and methods the helper uses that the server jar hasn't (looked up the
    way Java links them: in the class named, then its super classes)."""
    with zipfile.ZipFile(helper_jar) as z:
        uses = set().union(*(_class_file(z.read(n))["uses"] for n in z.namelist() if n.endswith(".class")))
    missing = []
    with zipfile.ZipFile(server_jar) as z:
        names = set(z.namelist())
        for kind, owner, name, desc in sorted(u for u in uses if u[1].startswith("net/minecraft/")):
            found, at = False, owner
            while at and f"{at}.class" in names and not found:
                info = _class_file(z.read(f"{at}.class"))
                found, at = (kind, name, desc) in info["members"], info["super"]
            if not found:
                missing.append((kind, owner, name, desc))
    return missing


def _only_the_start_line(server_dir: Path) -> str:
    """The helper logged its start line and nothing else (nothing every 5 seconds): read from the
    server's whole log (logs/latest.log), as the console keeps only its last lines."""
    text = (server_dir / "logs" / "latest.log").read_text(encoding="utf-8", errors="replace")
    ours = [line.rstrip() for line in text.splitlines() if "Craft Conductor Ping:" in line]
    assert len(ours) == 1 and ours[0].endswith(START), ours
    return ours[0]


def _minecraft_jar(server_dir: Path, loader: str, minecraft: str) -> Path | None:
    """The jar holding the Minecraft classes the server runs (for NeoForge, the one it patched; for
    Forge, the first one holding them: up to 1.20.4 the one on Forge's own names, from 1.20.6 the one on
    Mojang's)."""
    if loader not in ("neoforge", "forge"):
        return server_dir / "versions" / minecraft / f"server-{minecraft}.jar"
    for jar in sorted((server_dir / "libraries").rglob("*.jar")):
        with zipfile.ZipFile(jar) as z:
            if "net/minecraft/server/level/ServerPlayer.class" in z.namelist():
                return jar
    return None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


_REAL_INSTALL_FOLDERS = javamod.install_folders  # (taken at import, before conftest's fixtures replace it)


@pytest.fixture(scope="module")
def shared_java(tmp_path_factory):
    """One Java folder for the whole run, so each Java version downloads once."""
    return tmp_path_factory.mktemp("java-store")


@pytest.fixture
def real_java(java_store, shared_java, monkeypatch):
    """This computer's Java where one fits, else Temurin downloaded into the run's Java folder
    (conftest gives each test its own empty Java folder and hides this computer's Java)."""
    monkeypatch.setattr(javamod, "default_store", lambda: shared_java)
    monkeypatch.setattr(javamod, "install_folders", _REAL_INSTALL_FOLDERS)


def _wait_for(check, timeout: float):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = check()
        if found:
            return found
        time.sleep(0.5)
    return None


def _read_ping(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@pytest.mark.parametrize("loader, minecraft", SERVERS)
def test_fabric_ping_on_real_servers(loader, minecraft, tmp_path, real_java):
    _ping_on_a_real_server(loader, minecraft, tmp_path)


@pytest.mark.parametrize("loader, minecraft", NEOFORGE)
def test_neoforge_ping_on_real_servers(loader, minecraft, tmp_path, real_java):
    _ping_on_a_real_server(loader, minecraft, tmp_path)


@pytest.mark.parametrize("minecraft, forge", FORGE)
def test_forge_ping_on_real_servers(minecraft, forge, tmp_path, real_java):
    _ping_on_a_real_server("forge", minecraft, tmp_path, loader_version=forge, keepalive_delay=KEEPALIVE_DELAY_MS)


def test_paper_ping_on_a_real_server(tmp_path, real_java):
    """The Paper plugin, since it shares the file writing (common/PingFile) with the Fabric mod."""
    _ping_on_a_real_server("paper", "1.21.1", tmp_path)


def _ping_on_a_real_server(loader: str, minecraft: str, tmp_path: Path, loader_version: str | None = None,
                           keepalive_delay: int = 0) -> None:
    root = tmp_path / "server"
    port = _free_port()
    spec = setupmod.SetupSpec(loader=loader, minecraft=minecraft, accept_eula=True, port=port, memory_gb=2,
                              properties={"online-mode": "false"})  # (the bot has no Microsoft account)
    setupmod.configure(root, spec)
    with open(root / "craft-conductor.toml", "a", encoding="utf-8") as f:
        f.write("\n[players]\nping = true\n")       # (Craft Conductor puts the helper in at the start)
    if loader_version:
        configmod.hold_loader(root / "craft-conductor.toml", loader_version)   # (as a modpack pins its build)
    cfg = configmod.load(root)
    assert cfg.player_ping
    m = Manager(cfg, http=HttpClient(), echo=False)
    decision, changes = m.check(minecraft)
    assert decision.plan is not None, decision
    result = m.apply(decision.plan, verify=False, make_backup=False)
    assert result.ok, result.message
    assert m.lock.minecraft == minecraft
    if loader_version:
        assert m.lock.loader_version == loader_version

    jar = pinghelper.helper_jar(loader, minecraft)      # (the shipped jar for this server)
    assert jar is not None, (loader, minecraft)
    assert not (m.mods_dir / jar.name).exists()

    ping = m.server_dir / ".craft-conductor" / "ping.json"
    proc = m.start_server()
    bot = None
    try:
        assert (m.mods_dir / jar.name).read_bytes() == jar.read_bytes()   # (put in by start_server)
        assert [p.name for p in m.mods_dir.iterdir() if pinghelper.is_helper(p.name)] == [jar.name]
        log = "\n".join(proc.tail(500))
        assert START in log, log[-3000:]
        (tmp_path / "bot.js").write_text(BOT, encoding="utf-8")
        bot = subprocess.Popen(["node", str(tmp_path / "bot.js"), MINEFLAYER, str(port), minecraft, BOT_NAME]
                               + ([str(keepalive_delay)] if keepalive_delay else []),
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            bot_unsupported = bot.wait(timeout=5) == 3
        except subprocess.TimeoutExpired:
            bot_unsupported = False
        if bot_unsupported:
            # (mineflayer can't speak this Minecraft: the helper still has to load and write the file)
            seen = _wait_for(lambda: (_read_ping(ping) or {}).get("version") == 1 and _read_ping(ping), 20)
            assert seen and seen["players"] == {} and isinstance(seen["time"], int), seen
            server_jar = _minecraft_jar(m.server_dir, loader, minecraft)
            assert server_jar is not None and server_jar.is_file(), server_jar
            assert _missing_in(server_jar, jar) == []
            _only_the_start_line(m.server_dir)
            print(f"\n{loader} {minecraft}: helper loaded and wrote {seen}; mineflayer can't join this version, "
                  f"and every Minecraft member the helper uses is in {server_jar.name}")
            return
        seen = _wait_for(lambda: isinstance((_read_ping(ping) or {}).get("players", {}).get(BOT_NAME), int)
                         and _read_ping(ping), 20)
        tail = "\n".join(proc.tail(40))
        assert seen, f"no ping for {BOT_NAME} in {ping}: {_read_ping(ping)}\nserver:\n{tail}"
        assert seen["version"] == 1 and isinstance(seen["time"], int)
        assert 0 <= seen["players"][BOT_NAME] <= 60000
        warnings = [line for line in proc.tail(500) if "Craft Conductor Ping: can't write" in line]
        assert warnings == []
        _wait_for(lambda: (_read_ping(ping) or {}).get("time", 0) > seen["time"], 12)   # (another write)
        if keepalive_delay:
            # (the server sends a keep-alive every 15 s; each late answer moves the latency a quarter of the way)
            late = _wait_for(lambda: (_read_ping(ping) or {}).get("players", {}).get(BOT_NAME, 0) > 0
                             and _read_ping(ping), 45)
            assert late, f"{BOT_NAME}'s ping stayed 0 although it answers keep-alives {keepalive_delay} ms late"
            assert 0 < late["players"][BOT_NAME] <= keepalive_delay + 100, late
            seen = late
        if loader == "forge":                            # (the helper's names are the server's)
            server_jar = _minecraft_jar(m.server_dir, loader, minecraft)
            assert server_jar is not None and server_jar.is_file(), server_jar
            assert _missing_in(server_jar, jar) == []
            print(f"\n  every Minecraft member the helper uses is in {server_jar.name}")
        print(f"\n{loader} {minecraft} {m.lock.loader_version}: {seen}\n  {_only_the_start_line(m.server_dir)}")
    finally:
        if bot is not None and bot.poll() is None:
            bot.kill()
        if bot is not None:
            bot.wait(timeout=10)
        proc.stop(m.config.server.stop_timeout)
