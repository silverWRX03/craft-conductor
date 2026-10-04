"""Snapshots: a backup plus a note of what the server was, so backups can say what changed and a
roll back puts the whole server back (its craft-conductor settings and mod list too, not only its files).

Next to each backup ``<name>.tar.gz`` is ``<name>.tar.gz.json``: Minecraft and loader versions, the
mods, the server's settings (server.properties), a fingerprint of each mod config file, the world's
size, and the text of ``craft-conductor.toml`` and ``craft-conductor.lock.json`` at the time. Backups made before craft-conductor
0.15 have no note: they restore as before (the files only).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path

from . import backup, lock as lockmod
from .config import CONFIG_NAME
from .properties import read_properties

log = logging.getLogger(__name__)

NOTE = ".json"
CONFIG_FILES = 3000                 # config files fingerprinted at most
SECRET = re.compile(r"password|secret|token", re.I)  # settings never shown in a list of changes


def note_path(archive: Path) -> Path:
    return archive.with_name(archive.name + NOTE)


def _folder_size(path: Path) -> int:
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for name in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                pass
    return total


def describe(m) -> dict:
    """What the server is now (the same fields as a snapshot's note)."""
    sd, root = m.server_dir, m.config.root
    props = read_properties(sd / "server.properties")
    configs: dict[str, str] = {}
    folder = sd / "config"
    if folder.is_dir():
        for path in sorted(folder.rglob("*"))[:CONFIG_FILES]:
            if path.is_file() and path.stat().st_size <= 2_000_000:
                try:
                    configs[path.relative_to(sd).as_posix()] = hashlib.sha1(path.read_bytes()).hexdigest()
                except OSError:
                    pass
    lk = m.lock
    level = props.get("level-name") or "world"

    def text(name: str) -> str | None:
        try:
            return (root / name).read_text()
        except OSError:
            return None
    return {
        "time": time.time(), "minecraft": lk.minecraft, "loader": lk.loader, "loader_version": lk.loader_version,
        "mods": {x.key: {"name": x.name, "version": x.version_number} for x in lk.mods},
        "properties": props, "configs": configs, "world_bytes": _folder_size(sd / level) if (sd / level).is_dir() else 0,
        "toml": text(CONFIG_NAME), "lock": text(lockmod.LOCK_NAME),
    }


def record(archive: Path, m) -> None:
    """Write the note next to a backup just made (never fails the backup)."""
    try:
        path = note_path(archive)
        path.write_text(json.dumps(describe(m)))
        try:
            path.chmod(0o600)  # (it holds craft-conductor.toml, which can hold the Discord webhook)
        except OSError:
            pass
    except Exception:
        log.exception("couldn't note what's in the backup %s", archive.name)


def load(archive: Path) -> dict | None:
    try:
        return json.loads(note_path(archive).read_text())
    except (OSError, ValueError):
        return None


def _mb(n: int) -> str:
    return f"{abs(n) / 1e6:.0f} MB" if abs(n) >= 1e6 else f"{abs(n) / 1e3:.0f} KB"


def changes(before: dict, after: dict) -> list[str]:
    """What changed from ``before`` to ``after``, in plain words, most important first."""
    out: list[str] = []
    if before.get("minecraft") != after.get("minecraft"):
        out.append(f"Minecraft {before.get('minecraft') or '(not installed)'} → {after.get('minecraft') or '(not installed)'}")
    if before.get("loader_version") != after.get("loader_version") and before.get("minecraft") == after.get("minecraft"):
        out.append(f"{after.get('loader') or 'loader'} {before.get('loader_version')} → {after.get('loader_version')}")
    bm, am = before.get("mods", {}), after.get("mods", {})
    for key in sorted(set(am) - set(bm), key=lambda k: am[k]["name"].lower()):
        out.append(f"+ {am[key]['name']} {am[key]['version']}")
    for key in sorted(set(bm) - set(am), key=lambda k: bm[k]["name"].lower()):
        out.append(f"− {bm[key]['name']} {bm[key]['version']}")
    for key in sorted(set(am) & set(bm), key=lambda k: am[k]["name"].lower()):
        if am[key]["version"] != bm[key]["version"]:
            out.append(f"~ {am[key]['name']} {bm[key]['version']} → {am[key]['version']}")
    bp, ap = before.get("properties", {}), after.get("properties", {})
    for key in sorted(k for k in set(bp) | set(ap) if not SECRET.search(k)):
        if bp.get(key) != ap.get(key):
            out.append(f"Setting {key}: {bp.get(key, '(none)') or '(empty)'} → {ap.get(key, '(none)') or '(empty)'}")
    bc, ac = before.get("configs", {}), after.get("configs", {})
    changed = sorted(p for p in set(bc) | set(ac) if bc.get(p) != ac.get(p))
    if changed:
        shown = ", ".join(changed[:3])
        out.append(f"Mod config files changed: {shown}" + (f" and {len(changed) - 3} more" if len(changed) > 3 else ""))
    if (before.get("toml") or "") != (after.get("toml") or "") and before.get("toml") is not None:
        out.append("craft-conductor's settings for the server changed")
    grew = (after.get("world_bytes") or 0) - (before.get("world_bytes") or 0)
    if abs(grew) >= 5_000_000:
        out.append(f"The world {'grew' if grew > 0 else 'shrank'} by {_mb(grew)}")
    return out


_listed: dict[Path, tuple[tuple, dict]] = {}  # (the Backups page asks every few seconds)


def listing(backups_dir: Path) -> dict[str, dict]:
    """For each backup: whether it's a full snapshot, and what changed since the one before it.
    Worked out again only when a backup or a note changes."""
    archives = backup.list_backups(backups_dir)
    stamp = tuple((a.name, *_mtime(note_path(a))) for a in archives)
    cached = _listed.get(backups_dir)
    if cached and cached[0] == stamp:
        return cached[1]
    out = _listing(archives)
    if len(_listed) > 50:
        _listed.clear()
    _listed[backups_dir] = (stamp, out)
    return out


def _mtime(path: Path) -> tuple[int, int]:
    try:
        st = path.stat()
        return st.st_mtime_ns, st.st_size
    except OSError:
        return 0, 0


def _listing(archives: list[Path]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    previous = None
    for archive in archives:  # oldest first
        note = load(archive)
        out[archive.name] = {"snapshot": note is not None, "minecraft": (note or {}).get("minecraft"),
                             "mods": len((note or {}).get("mods", {})),
                             "changes": changes(previous, note) if note and previous else None}
        previous = note or previous
    return out


def roll_back(archive: Path, m) -> str:
    """Put the whole server back as it was in ``archive``: its files, and (for a snapshot) its
    craft-conductor settings and mod list. The server must be stopped."""
    note = load(archive)
    backup.restore(archive, m.server_dir)
    forget = getattr(m, "forget_interrupted_update", lambda: None)  # (this backup was chosen: an interrupted
    if note is None:                                                 # update mustn't put another one back)
        forget()
        return f"restored {archive.name} (an older backup: only the files; run an update check to re-sync the mods)"
    root = m.config.root
    for name, text in ((CONFIG_NAME, note.get("toml")), (lockmod.LOCK_NAME, note.get("lock"))):
        if text is not None:
            tmp = root / (name + ".rollback")
            tmp.write_text(text)
            os.replace(tmp, root / name)
    m.lock = lockmod.load(root)
    forget()
    m.reload_config()
    return f"rolled back to {archive.name}: Minecraft {note.get('minecraft')}, {len(note.get('mods', {}))} mod(s)"
