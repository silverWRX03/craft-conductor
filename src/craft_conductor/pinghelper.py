"""Craft Conductor Ping's side in Craft Conductor (roadmap 47): players' ping on the Dashboard.

The helper is a small mod or plugin that ships inside Craft Conductor (``helpers/``), built from
``helpers/ping/``. On a server that has ``[players] ping = true`` it is copied into the mods (or
plugins) folder every time the server starts, and taken out when the setting is off or the server
can't run it. Every 5 seconds the helper writes ``.craft-conductor/ping.json`` in the server folder,
and the Connected Players card reads it (:func:`read`).

The file is untrusted input: whatever is in the server folder (a mod, a person) could have written it.
So it is opened without following links, read up to 64 KB, and only whole numbers for players are kept.
The helper has no stop hook, so the last file stays after the server stops; it counts only while it is
fresh, and :func:`sync` deletes it before each start, so a fast restart never shows the last run's numbers.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import stat
from pathlib import Path

from . import folders
from .preview import _version_key

log = logging.getLogger(__name__)

#: where the helper writes, from the server's folder
PING_FILE = Path(".craft-conductor") / "ping.json"
MAX_BYTES = 65536          # the most read of it
FRESH_SECONDS = 30         # a reading older than this counts as no reading (Paper's 100-tick timer takes
                           # over 15 s below about 6.7 TPS)
MAX_MS = 60000             # a ping above this is nonsense
MAX_NAME = 32              # characters in a name (Minecraft's are 16; a Floodgate prefix adds one)
PREFIX = "craft_conductor_ping-"
NAME = "Craft Conductor Ping"   # (as Manage Mods names it)
#: where the shipped jars are (a seam for tests)
JARS_DIR = Path(__file__).parent / "helpers"

#: Which helper jar runs where: (loaders, lowest Minecraft inclusive, below this Minecraft or None,
#: the jar's platform: ``craft_conductor_ping-<platform>-<version>.jar``). Fabric has two jars, since
#: Minecraft 26 changed the names the mod uses; NeoForge has two, since from 1.20.5 it reads another
#: metadata file (neoforge.mods.toml for mods.toml); Forge 1.20.1 has its own, on Forge's own (SRG) names.
SUPPORT: list[tuple[tuple[str, ...], str, str | None, str]] = [
    (("paper", "purpur"), "1.17", None, "paper"),
    (("fabric", "quilt"), "1.20.2", "26", "fabric"),
    (("fabric", "quilt"), "26", None, "fabric26"),
    (("neoforge",), "1.20.2", "1.20.5", "neoforge"),
    (("neoforge",), "1.20.5", None, "neoforge1.20.5"),
    (("forge",), "1.20.1", "1.20.2", "forge"),
]

VANILLA_REASON = "Minecraft doesn't share each player's ping without a mod or plugin, and plain Minecraft runs neither."
TOO_OLD_REASON = "Craft Conductor's ping helper needs Minecraft {version} or newer on this server type."
NOT_YET_REASON = "Craft Conductor's ping helper doesn't run on {loader} yet."
OFF_REASON = "Ping is off for this server."
RESTART_REASON = "Ping shows after the next restart."
WAITING_REASON = "Waiting for the server to report ping…"


def _key(minecraft: str) -> tuple[int, ...] | None:
    """A release's place in the order of versions (26.1 after 1.21.11); None for a name that isn't a plain
    release: a snapshot (24w14a), a pre-release or release candidate (1.20.2-rc1). Fabric orders those below
    the release, so a jar picked by guessing could be one Fabric refuses to start with: they get no helper."""
    if not re.fullmatch(r"\d+(?:\.\d+)*", minecraft or ""):
        return None
    return _version_key(minecraft)


def _row(loader: str, minecraft: str):
    key = _key(minecraft)
    if key is None:
        return None
    for loaders, lowest, below, platform in SUPPORT:
        if loader in loaders and key >= _version_key(lowest) and (below is None or key < _version_key(below)):
            return loaders, lowest, below, platform
    return None


def helper_jar(loader: str, minecraft: str) -> Path | None:
    """The shipped jar for this server type and Minecraft version; None where it can't run."""
    row = _row(loader, minecraft)
    if row is None:
        return None
    found = sorted(JARS_DIR.glob(f"{PREFIX}{row[3]}-*.jar"))
    return found[-1] if found else None


def unsupported_reason(loader: str, minecraft: str) -> str | None:
    """None where the helper runs, else why not (shown on the Connected Players card)."""
    if _row(loader, minecraft) is not None:
        return None
    if loader == "vanilla":
        return VANILLA_REASON
    lowest = min((r[1] for r in SUPPORT if loader in r[0]), key=_version_key, default=None)
    key = _key(minecraft)
    if lowest is None or (key is not None and key > _version_key(lowest)):   # (none yet for this one)
        return NOT_YET_REASON.format(loader=loader or "this server type")
    return TOO_OLD_REASON.format(version=lowest)


def is_helper(filename: str) -> bool:
    """Whether a file in the mods folder is Craft Conductor's own helper (any version, on or off)."""
    return filename.startswith(PREFIX) and filename.endswith((".jar", ".jar.disabled"))


def in_folder(mods_dir: Path) -> dict | None:
    """The helper's file in the mods (or plugins) folder, for Manage Mods: ``{"name", "filename"}``, or None."""
    try:
        found = sorted(p.name for p in mods_dir.iterdir() if is_helper(p.name) and p.is_file())
    except OSError:
        return None
    found.sort(key=lambda n: n.endswith(".disabled"))   # (a file that is on first)
    return {"name": NAME, "filename": found[0]} if found else None


def _target(m, lock=None) -> tuple[str, str]:
    """The server type and Minecraft version the server runs (what is installed, else what is set)."""
    lock = lock or m.lock
    return lock.loader or m.config.server.loader, lock.minecraft or ""


def _same(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_size == b.stat().st_size and a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def sync(m, lock=None) -> None:
    """Before a start: delete the last run's ping file; with ``[players] ping`` on and a helper for this
    server, put its jar in the mods folder (and take out every other helper file: Fabric refuses to start
    with two, or the wrong one); otherwise take every helper file out. Never raises: a server that can't
    be given the helper still starts."""
    try:
        _sync(m, lock)
    except Exception as e:  # (never a reason not to start)
        log.warning("couldn't set up Craft Conductor's ping helper: %s", e)


def _sync(m, lock) -> None:
    try:
        (m.server_dir / PING_FILE).unlink(missing_ok=True)   # (a link is removed, not followed)
    except OSError as e:
        log.warning("couldn't remove the last ping file: %s", e)
    loader, minecraft = _target(m, lock)
    jar = helper_jar(loader, minecraft) if m.config.player_ping else None
    mods_dir = m.mods_dir
    if jar is not None:
        mods_dir.mkdir(parents=True, exist_ok=True)
        dest = mods_dir / jar.name
        if not _same(jar, dest):
            part = mods_dir / (jar.name + ".part")
            try:
                part.unlink(missing_ok=True)               # (a link planted at this name is removed, not written through)
                shutil.copyfile(jar, part)
                os.replace(part, dest)
                log.info("put the ping helper %s into %s", jar.name, mods_dir.name)
            except OSError as e:
                # Whatever helper is there may be the wrong one (Fabric refuses to start with it): take every one out.
                log.warning("couldn't put the ping helper %s into %s: %s", jar.name, mods_dir.name, e)
                jar = None
            finally:
                try:
                    part.unlink(missing_ok=True)
                except OSError:
                    pass
    if not mods_dir.is_dir():
        return
    for path in mods_dir.iterdir():
        if is_helper(path.name) and (jar is None or path.name != jar.name):
            try:
                if path.is_file() or path.is_symlink():
                    path.unlink()
                    log.info("took the ping helper file %s out of %s", path.name, mods_dir.name)
            except OSError as e:
                log.warning("couldn't remove %s: %s", path.name, e)


def read(server_dir: Path, now: float) -> dict[str, int] | None:
    """Each online player's ping (milliseconds) from the helper's file; None when there is no usable,
    fresh reading (no file, a link, over 64 KB, not valid, from an unknown version, older than 30 s)."""
    folder, path = server_dir / PING_FILE.parent, server_dir / PING_FILE
    try:
        for p in (folder, path):
            if folders.link_stat(os.lstat(p)):      # (a link, or on Windows a junction)
                return None
        before = os.lstat(path)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
            return None
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_NONBLOCK", 0))   # (a pipe swapped in can't hold a request thread)
    except OSError:
        return None
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_ino, opened.st_dev) != (before.st_ino, before.st_dev):
            return None                              # (swapped for something else in between)
        with os.fdopen(fd, "rb", closefd=False) as f:
            raw = f.read(MAX_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(fd)
    if len(raw) > MAX_BYTES:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or data.get("version") != 1 or isinstance(data.get("version"), bool):
        return None
    written, players = data.get("time"), data.get("players")
    if isinstance(written, bool) or not isinstance(written, int) or not isinstance(players, dict):
        return None
    if not 0 < written < 10 ** 15:                   # (a count too big for a float below would raise)
        return None
    if abs(now - written / 1000) > FRESH_SECONDS:    # (too old; or from the future: a clock that is wrong)
        return None
    return {name: ms for name, ms in players.items()
            if isinstance(name, str) and 0 < len(name) <= MAX_NAME
            and isinstance(ms, int) and not isinstance(ms, bool) and 0 <= ms <= MAX_MS}


def card(m, running: bool, now: float) -> tuple[dict[str, int] | None, dict]:
    """What the Connected Players card needs: the pings (None without a reading) and ``{"reason",
    "can_turn_on", "on"}``. Reads the file only while the server runs and the setting is on."""
    loader, minecraft = _target(m)
    jar = helper_jar(loader, minecraft)
    on = bool(m.config.player_ping)
    why = unsupported_reason(loader, minecraft)
    info = {"reason": "", "can_turn_on": why is None and not on, "on": on}
    if why is not None:
        info["reason"] = why
    elif not on:
        info["reason"] = OFF_REASON
    else:
        pings = read(m.server_dir, now) if running else None
        if pings is not None:
            return pings, info
        in_place = jar is not None and (m.mods_dir / jar.name).is_file()
        info["reason"] = WAITING_REASON if in_place else RESTART_REASON
    return None, info
