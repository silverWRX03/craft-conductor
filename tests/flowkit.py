"""A pretend Minecraft world for repeatable end-to-end tests of every loader.

The real loader classes (vanilla, Fabric, Quilt, Paper, Purpur, NeoForge, Forge) run unchanged
against canned answers from their download sites. The "jars" they download are Python zipapps:
the stand-in ``java`` runs them (expanding ``@argfiles`` like real Java, which Forge and NeoForge
start with). The installers write what the real ones do (libraries/, run.sh, the args files),
and the server makes a world, answers ``list`` and the save commands, and refuses to start with
a mod named ``crash*`` in mods/ or plugins/, like a broken mod.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import os
import stat
import sys
import textwrap
import threading
import time
import zipfile
from pathlib import Path

from craft_conductor import config as configmod, nbt, setup as setupmod
from craft_conductor.config import ModSpec
from craft_conductor.loaders import fabric, forge, paper, purpur
from craft_conductor.manager import Manager
from craft_conductor.mods import providers_for

from conftest import FakeMojang

# loader -> (first Minecraft version, the next one, the Modrinth loader its mods/plugins use)
LOADERS = {
    "vanilla": ("1.21.1", "1.21.2", None),
    "fabric": ("1.21.1", "1.21.2", "fabric"),
    "quilt": ("1.21.1", "1.21.2", "quilt"),
    "paper": ("1.21.1", "1.21.2", "paper"),
    "purpur": ("1.21.1", "1.21.2", "paper"),
    "neoforge": ("1.21.1", "1.21.2", "neoforge"),
    "forge": ("1.20.1", "1.20.2", "forge"),
}

LEVEL_DAT = gzip.compress(nbt.dumps({"Data": {"LevelName": "Flow World", "Version": {"Name": "1.21.1"}}}))

FLOW_JAVA = textwrap.dedent("""\
    import runpy, sys
    args = sys.argv[1:]
    if args[:1] == ["-version"]:
        print('openjdk version "21.0.4" 2024-07-16', file=sys.stderr)
        sys.exit(0)
    expanded = []
    for a in args:  # like real Java: @file is replaced by the arguments in it
        expanded += open(a[1:], encoding="utf-8").read().split() if a.startswith("@") else [a]
    args = expanded
    while args and args[0].startswith("-"):  # JVM flags, and -jar
        args.pop(0)
    sys.argv = args
    runpy.run_path(args[0], run_name="__main__")
    """)

SERVER = textwrap.dedent("""\
    import base64, pathlib, sys
    here = pathlib.Path(".")
    for folder in ("mods", "plugins"):
        d = here / folder
        bad = sorted(p.name for p in d.iterdir() if p.name.startswith("crash")) if d.is_dir() else []
        if bad:
            print("[Server thread/ERROR]: mod failed to load", flush=True)
            print(f"\\tat com.example.Mod.init(Mod.java:1) [{bad[0]}:?]", flush=True)
            sys.exit(1)
    level = "world"
    props = here / "server.properties"
    if props.exists():
        for line in props.read_text().splitlines():
            if line.startswith("level-name="):
                level = line.split("=", 1)[1].strip() or "world"
    world = here / level
    if not (world / "level.dat").exists():
        (world / "region").mkdir(parents=True, exist_ok=True)
        (world / "level.dat").write_bytes(base64.b64decode(LEVEL_DAT))
        (world / "region" / "r.0.0.mca").write_bytes(b"\\0" * 8192)
    print('[12:00:00] [Server thread/INFO]: Done (0.1s)! For help, type "help"', flush=True)
    for line in sys.stdin:
        cmd = line.strip()
        if cmd == "list":
            print("[12:00:01] [Server thread/INFO]: There are 0 of a max of 20 players online:", flush=True)
        elif cmd.startswith(("save-", "say ")):
            print(f"[12:00:01] [Server thread/INFO]: {cmd}", flush=True)
        elif cmd == "stop":
            print("[12:00:02] [Server thread/INFO]: Stopping the server", flush=True)
            sys.exit(0)
    """).replace("LEVEL_DAT", repr(base64.b64encode(LEVEL_DAT).decode()))

FORGE_INSTALLER = textwrap.dedent("""\
    import base64, pathlib, sys
    assert "--installServer" in sys.argv, sys.argv
    lib = pathlib.Path("libraries") / LIBRARY
    lib.mkdir(parents=True, exist_ok=True)
    (lib / "server.jar").write_bytes(base64.b64decode(SERVER_JAR))
    for name in ("unix_args.txt", "win_args.txt"):
        (lib / name).write_text(f"-Dfml.flow=1 -jar {(lib / 'server.jar').as_posix()}\\n")
    pathlib.Path("run.sh").write_text("#!/bin/sh\\njava @user_jvm_args.txt @" + (lib / "unix_args.txt").as_posix() + "\\n")
    pathlib.Path("run.bat").write_text("@echo off\\n")
    pathlib.Path("user_jvm_args.txt").write_text("# -Xmx4G\\n")
    print("The server installed successfully")
    """)

QUILT_INSTALLER = textwrap.dedent("""\
    import base64, pathlib, sys
    assert sys.argv[1:3] == ["install", "server"], sys.argv
    dest = pathlib.Path(next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--install-dir=")))
    (dest / "libraries").mkdir(parents=True, exist_ok=True)
    (dest / "quilt-server-launch.jar").write_bytes(base64.b64decode(SERVER_JAR))
    (dest / "server.jar").write_bytes(b"vanilla")
    """)


def zipapp(source: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("__main__.py", source)
    return buf.getvalue()


SERVER_JAR = zipapp(SERVER)


def _installer(template: str, **values: str) -> bytes:
    source = template.replace("SERVER_JAR", repr(base64.b64encode(SERVER_JAR).decode()))
    for key, value in values.items():
        source = source.replace(key, repr(value))
    return zipapp(source)


def write_java(bindir: Path) -> Path:
    bindir.mkdir(parents=True, exist_ok=True)
    (bindir / "flowjava.py").write_text(FLOW_JAVA)
    if os.name == "nt":
        path = bindir / "java.bat"
        path.write_text(f'@"{sys.executable}" "{bindir / "flowjava.py"}" %*\r\n')
    else:
        path = bindir / "java"
        path.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{bindir / "flowjava.py"}" "$@"\n')
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def patch_template(monkeypatch, java: Path) -> None:
    """New servers' craft-conductor.toml use the stand-in java, no countdown and short timeouts."""
    real = configmod.render_template

    def render(loader, minecraft):
        text = real(loader, minecraft).replace('default = "java"', f"default = {json.dumps(str(java))}")
        return text.replace("warn_minutes = [10, 5, 1]", "warn_minutes = []") \
                   .replace('startup_timeout = "10m"', 'startup_timeout = "30s"')
    monkeypatch.setattr(configmod, "render_template", render)


def publish(http, loader: str, minecraft: str) -> None:
    """What ``loader``'s download site says, and serves, for ``minecraft``."""
    if loader == "vanilla":
        http.files[f"https://files.test/{minecraft}/server.jar"] = SERVER_JAR
    elif loader == "fabric":
        http.json[f"{fabric.FABRIC_META}/versions/loader/{minecraft}"] = [{"loader": {"version": "0.16.0", "stable": True}}]
        http.json[f"{fabric.FABRIC_META}/versions/installer"] = [{"version": "1.0.1", "stable": True}]
        http.files[f"{fabric.FABRIC_META}/versions/loader/{minecraft}/0.16.0/1.0.1/server/jar"] = SERVER_JAR
    elif loader == "quilt":
        http.json[f"{fabric.QUILT_META}/versions/loader/{minecraft}"] = [{"loader": {"version": "0.26.0"}}]
        http.json[f"{fabric.QUILT_META}/versions/installer"] = [{"version": "0.9.2"}]
        http.files[f"{fabric.QUILT_MAVEN}/0.9.2/quilt-installer-0.9.2.jar"] = _installer(QUILT_INSTALLER)
    elif loader == "paper":
        url = f"https://fill-data.papermc.io/v1/objects/{minecraft}/paper-{minecraft}-100.jar"
        http.files[url] = SERVER_JAR
        http.json[f"{paper.FILL}/versions/{minecraft}/builds"] = [{
            "id": 100, "channel": "STABLE", "downloads": {"server:default": {
                "name": f"paper-{minecraft}-100.jar", "url": url,
                "checksums": {"sha256": hashlib.sha256(SERVER_JAR).hexdigest()}}}}]
    elif loader == "purpur":
        http.json[f"{purpur.API}/{minecraft}"] = {"builds": {"all": ["2300"]}}
        http.json[f"{purpur.API}/{minecraft}/2300"] = {"result": "SUCCESS",
                                                       "md5": hashlib.md5(SERVER_JAR, usedforsecurity=False).hexdigest()}
        http.files[f"{purpur.API}/{minecraft}/2300/download"] = SERVER_JAR
    elif loader == "neoforge":
        version = forge.neoforge_prefix(minecraft) + "77"
        listed = http.json.get(forge.NEOFORGE_VERSIONS, {"versions": []})["versions"]
        http.json[forge.NEOFORGE_VERSIONS] = {"versions": sorted(set(listed) | {version})}
        http.files[f"{forge.NEOFORGE_MAVEN}/{version}/neoforge-{version}-installer.jar"] = _installer(
            FORGE_INSTALLER, LIBRARY=f"net/neoforged/neoforge/{version}")
    elif loader == "forge":
        promos = http.json.get(forge.FORGE_PROMOS, {"promos": {}})["promos"]
        version = "47.3.0" if minecraft == "1.20.1" else "48.1.0"
        http.json[forge.FORGE_PROMOS] = {"promos": {**promos, f"{minecraft}-recommended": version}}
        http.files[f"{forge.FORGE_MAVEN}/{minecraft}-{version}/forge-{minecraft}-{version}-installer.jar"] = _installer(
            FORGE_INSTALLER, LIBRARY=f"net/minecraftforge/forge/{minecraft}-{version}")
    else:
        raise ValueError(loader)


def add_mod(modrinth, loader: str, pid: str, minecraft: str, number: str = "1.0", filename: str | None = None) -> None:
    """A Modrinth mod (a plugin, for Paper and Purpur) built for ``loader`` and ``minecraft``."""
    mod_loader = LOADERS[loader][2]
    if pid not in modrinth.versions:
        modrinth.project(pid, pid.lower(), f"Mod {pid}")
    modrinth.version(pid, number, [minecraft], loaders=(mod_loader,), filename=filename)


def make_server(root: Path, http, modrinth, loader: str, mods: tuple[str, ...] = ("AAAAAAAA",)) -> Manager:
    """A new server made the way the setup page does, with the real loader for ``loader``."""
    first, _next, mod_loader = LOADERS[loader]
    publish(http, loader, first)
    setupmod.configure(root, setupmod.SetupSpec.from_dict({"loader": loader, "minecraft": first,
                                                           "motd": f"Flow {loader}", "accept_eula": True}))
    cfg_path = root / configmod.CONFIG_NAME
    if mod_loader:
        for pid in mods:
            add_mod(modrinth, loader, pid, first)
            configmod.append_mod(cfg_path, ModSpec("modrinth", pid))
    # Follow new Minecraft versions (the setup page pins the chosen one).
    configmod.set_value(cfg_path, "server", "minecraft", '"latest"')
    configmod.set_value(cfg_path, "updates", "strategy", '"latest-compatible"')
    cfg = configmod.load(root)
    mojang = FakeMojang(http, [first])
    return Manager(cfg, http=http, mojang=mojang, providers=providers_for(cfg, http), echo=False, sleep=lambda s: None)


def update(m: Manager, retry_failed: bool = False):
    decision, changes = m.check(retry_failed=retry_failed)
    assert decision.plan is not None, decision
    return m.apply(decision.plan)


def wait_for(condition, timeout: float = 30.0, what: str = "condition") -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


class FastEvent(threading.Event):
    """A stop event whose waits are short: crash restarts happen at once instead of after 5 s."""

    def wait(self, timeout=None):
        return super().wait(min(timeout, 0.05) if timeout is not None else 0.05)


def no_sleep_time():
    """The ``time`` module without sleeping (the daemon waits 5 s for saves before a backup)."""
    import types
    return types.SimpleNamespace(**{**{k: getattr(time, k) for k in dir(time) if not k.startswith("_")},
                                    "sleep": lambda s: None})
