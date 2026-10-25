"""Snapshots of the server directory, used for manual restores and automatic rollback."""

from __future__ import annotations

import errno
import gzip
import io
import json
import logging
import os
import re
import shutil
import tarfile
import time
import zlib
from datetime import datetime
from pathlib import Path
from typing import Iterable

from . import lockbox, parts, private, safearchive
from .properties import read_properties, write_properties

log = logging.getLogger(__name__)

SUFFIX = ".tar.gz"
MAX_RESTORE_BYTES = 1 << 40        # unpacked; the disk's free space decides first
MAX_RESTORE_MEMBERS = 2_000_000    # (a big web map can be hundreds of thousands of small files)
STALE_PART = 3600                  # an unfinished backup untouched this long was cut off
ABOUT = "craft-conductor/backup.json"   # in a backup, beside server/: what it holds
LOCKED = "craft-conductor/locked.bin"   # ...and its locked part (lockbox.py)
KEPT = "craft-conductor/kept.json"      # restoring: the server's own files moved into the new folder


class RestoreError(ValueError):
    """A backup that can't be restored. The server is left exactly as it was."""


def create(server_dir: Path, backups_dir: Path, label: str, exclude: list[str],
           holds: Iterable[str] | None = None) -> Path:
    """A backup of ``server_dir``. ``holds``: the parts it holds (parts.CHOICES, and "logs" and
    "secrets", which go in locked to this computer and account: lockbox.py); None for every part
    but the logs (the backups made before an update or a new world, which a roll back relies on).
    ``exclude``: folders (by name) left out besides. What it holds is written first in it
    (``craft-conductor/backup.json``), so restoring it keeps the server's own copy of the rest."""
    holds = set(parts.COMPLETE if holds is None else holds)
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", label)
    dest = backups_dir / f"{stamp}-{safe}{SUFFIX}"
    n = 2
    while dest.exists():  # two backups in the same second: keep both
        dest = backups_dir / f"{stamp}.{n}-{safe}{SUFFIX}"  # sorts after the first one
        n += 1
    tmp = dest.with_name(dest.name + ".part")
    excluded = set(exclude)
    props = server_dir / "server.properties"
    props_text = props.read_bytes().decode("latin-1") if props.is_file() else None  # (latin-1: every byte as it is)
    level = (read_properties(props).get("level-name") or "world") if props_text is not None else "world"
    props_secret = props_text is not None and bool(parts.properties_without_secrets(props_text)[1])
    ip_bans = _has_entries(server_dir / "banned-ips.json")

    def rel(info: tarfile.TarInfo) -> str:
        return info.name.split("/", 1)[1] if "/" in info.name else ""

    def plain(info: tarfile.TarInfo):  # what goes in as it is
        r = rel(info)
        if not r:
            return info
        if r.split("/", 1)[0] in excluded or info.name.endswith("session.lock") or r == "server.properties":
            return None
        part = parts.part_of(r, level)
        return info if part is None or (part in holds and part in parts.CHOICES) else None

    def locked(info: tarfile.TarInfo):  # what goes in locked
        r = rel(info)
        if not r:
            return info
        if r.split("/", 1)[0] in excluded:
            return None
        if r == "server.properties":
            return info if "secrets" in holds and props_secret else None
        part = parts.part_of(r, level)
        if part == "secrets":
            return info if "secrets" in holds and ip_bans else None
        return info if part == "logs" and "logs" in holds else None

    _remove_stale_parts(backups_dir)
    log.info("backing up %s -> %s", server_dir, dest)
    inner = backups_dir / f"{dest.name}.locked.part"   # (never listed as backups; tidied if left behind)
    sealed = backups_dir / f"{dest.name}.sealed.part"
    try:
        sensitive = bool(holds & set(parts.LOCKED)) and _gather(server_dir, inner, locked)
        if sensitive:  # (a backup with a locked part is this account's only, too)
            os.close(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600))
            private.protect(tmp)
            lockbox.lock_file(inner, sealed)
        about_it = {"format": 1, "holds": sorted(holds & set(parts.CHOICES)), "level": level,
                    "locked": sorted(holds & set(parts.LOCKED)) if sensitive else [], "excluded": sorted(excluded)}
        # Region files are already compressed, so a fast compression level is plenty.
        with tarfile.open(tmp, "w:gz", compresslevel=1) as tar:
            _add_bytes(tar, ABOUT, json.dumps(about_it, indent=1).encode(), time.time())  # (first: read quickly)
            tar.add(server_dir, arcname="server", filter=plain)
            if props_text is not None:  # (its passwords only ever in the locked part)
                _add_bytes(tar, "server/server.properties",
                           parts.properties_without_secrets(props_text)[0].encode("latin-1"), props.stat().st_mtime)
            if sensitive:
                tar.add(sealed, arcname=LOCKED, recursive=False)
        tmp.rename(dest)
    except BaseException as e:
        # A cut-off backup is never listed (only finished ones get the .tar.gz name); remove it
        # too, so a full disk gets its space back.
        tmp.unlink(missing_ok=True)
        if isinstance(e, OSError) and e.errno == errno.ENOSPC:
            free = safearchive.free_bytes(backups_dir)
            log.error("couldn't make the backup %s: the disk is full (%s free). The unfinished file was removed; "
                      "free some space, or keep fewer backups", dest.name,
                      safearchive.size_words(free) if free is not None else "nothing")
        elif isinstance(e, Exception):
            log.error("couldn't make the backup %s: %s", dest.name, e)
        raise
    finally:
        inner.unlink(missing_ok=True)
        sealed.unlink(missing_ok=True)
    return dest


def _has_entries(path: Path) -> bool:
    """Whether a player list (banned-ips.json) lists anyone."""
    try:
        return bool(json.loads(path.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError):
        return path.is_file()  # (unreadable: treated as holding something)


def _gather(server_dir: Path, dest: Path, keep) -> bool:
    """The files ``keep`` passes, in a .tar.gz at ``dest`` (this account's only); False if there
    are none."""
    os.close(os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600))
    private.protect(dest)
    found = False

    def note(info):
        nonlocal found
        info = keep(info)
        if info is not None and info.isfile():
            found = True
        return info
    with tarfile.open(dest, "w:gz", compresslevel=1) as tar:
        tar.add(server_dir, arcname="server", filter=note)
    return found


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes, mtime: float) -> None:
    info = tarfile.TarInfo(name)
    info.size, info.mtime, info.mode = len(data), int(mtime), 0o600
    tar.addfile(info, io.BytesIO(data))


_about: dict[str, tuple[tuple, dict | None]] = {}  # path -> (its size and date, what it holds)


def about(archive: Path) -> dict | None:
    """What a backup holds (its first file, ``craft-conductor/backup.json``), or None for one
    made before Craft Conductor wrote that: it holds everything, nothing locked."""
    try:
        st = archive.stat()
    except OSError:
        return None
    cached = _about.get(str(archive))
    if cached and cached[0] == (st.st_size, st.st_mtime_ns):
        return cached[1]
    found = _read_about(archive)
    _about[str(archive)] = ((st.st_size, st.st_mtime_ns), found)
    return found


def _read_about(archive: Path) -> dict | None:
    try:
        with tarfile.open(archive, "r:gz") as tar:
            first = tar.next()
            if first is not None and first.name == ABOUT and first.isfile() and first.size < 1 << 16:
                data = json.loads(tar.extractfile(first).read())
                return data if isinstance(data, dict) else None
    except (tarfile.TarError, OSError, EOFError, zlib.error, ValueError):
        return None
    return None


def _remove_stale_parts(backups_dir: Path) -> None:
    """Unfinished backups left by a Craft Conductor that was stopped mid-way (they're never listed
    or restored, but they fill the disk). One still being written is younger than STALE_PART."""
    cutoff = time.time() - STALE_PART
    for part in backups_dir.glob("*.part"):
        try:
            if part.stat().st_mtime < cutoff:
                part.unlink()
                log.info("removed the unfinished backup %s", part.name)
        except OSError:
            pass


def list_backups(backups_dir: Path) -> list[Path]:
    if not backups_dir.exists():
        return []
    # Oldest first: by the time in the name, then (for two in the same second) by when it was made.
    return sorted(backups_dir.glob(f"*{SUFFIX}"), key=lambda p: (p.name[:15], p.stat().st_mtime_ns, p.name))


def prune(backups_dir: Path, keep: int) -> list[Path]:
    backups = list_backups(backups_dir)
    removed = backups[:-keep] if keep > 0 else []
    for path in removed:
        path.unlink()
        path.with_name(path.name + ".json").unlink(missing_ok=True)  # (its snapshot note: snapshots.py)
    return removed


def copy_out(archive: Path, folder: Path | None, name: str, keep: int = 10) -> Path | None:
    """Copy a backup to another place too (a USB drive, a OneDrive/Dropbox/Google Drive folder),
    in a folder named after the server, keeping the newest ``keep`` there. A copy that can't
    be made (the drive is unplugged) is logged, never an error: the backup itself is made."""
    if folder is None:
        return None
    safe = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip() or "server"
    dest_dir = folder / safe
    try:
        if not folder.exists():
            raise OSError(f"{folder} isn't there (is the drive plugged in?)")
        dest_dir.mkdir(exist_ok=True)
        tmp = dest_dir / (archive.name + ".part")
        shutil.copyfile(archive, tmp)
        dest = dest_dir / archive.name
        tmp.replace(dest)
        prune(dest_dir, keep)
        log.info("copied the backup to %s", dest)
        return dest
    except OSError as e:
        log.warning("couldn't copy the backup to %s: %s", dest_dir, e)
        return None


def _restore_filter(staging: Path, skipped: safearchive.Skipped):
    """The tarfile filter for restoring: Python's "data" filter (no absolute paths, nothing
    outside the folder, no devices, no setuid bits), and also every link must point inside the
    restored ``server`` folder (the data filter only checks the staging folder around it, and a
    link to ``..`` would point outside the server once it's moved into place). Totals are counted
    as members are read, so a backup that unpacks to too much is stopped before it fills the disk."""
    server = os.path.realpath(staging / "server")
    seen = {"bytes": 0, "members": 0}

    def inside(path: str) -> bool:
        return os.path.commonpath([server, path]) == server

    def check(member: tarfile.TarInfo, dest: str) -> tarfile.TarInfo | None:
        seen["members"] += 1
        seen["bytes"] += max(member.size, 0)
        if seen["members"] > MAX_RESTORE_MEMBERS:
            raise RestoreError(f"it's too big: it holds more than {MAX_RESTORE_MEMBERS:,} files")
        if seen["bytes"] > MAX_RESTORE_BYTES:
            raise RestoreError(f"it's too big: it unpacks to more than {safearchive.size_words(MAX_RESTORE_BYTES)}")
        member = tarfile.data_filter(member, dest)  # (anything climbing out of the folder refuses the backup)
        name = os.path.normpath(member.name.replace("\\", "/")).replace("\\", "/")  # ("server/../x" is "x")
        if name in (ABOUT, LOCKED):
            return member if member.isfile() else None
        if name.split("/", 1)[0] != "server":
            skipped.add(member.name, "it isn't part of the server folder")
            return None
        if name == "server" and not member.isdir():
            raise RestoreError("its server folder isn't a folder")
        if member.issym() or member.islnk():
            where = os.path.dirname(os.path.join(dest, member.name)) if member.issym() else dest
            target = os.path.realpath(os.path.join(where, member.linkname))
            if not inside(target):
                raise tarfile.LinkOutsideDestinationError(member, target)
        return member
    return check


def restore(archive: Path, server_dir: Path) -> dict:
    """Replace ``server_dir`` with the archive's contents.

    The backup is unpacked next to the server first (``<dir>.restoring``); the server is only
    touched once that worked, and is kept as ``<dir>.replaced`` until the new one is in place.
    A backup that is damaged, unsafe or too big for the disk raises :class:`RestoreError` and
    leaves the server as it was.

    What the backup left out (a part not chosen, its locked part when it was locked on another
    computer or account) is the server's own copy, moved into the new folder before the swap
    (``kept.json`` says what, so an interruption puts it back: ``recover``). Returns what
    happened to the locked part: {"locked": [...], "opened": [...], "why": ..., "kept": [...]}.
    """
    staging = server_dir.with_name(server_dir.name + ".restoring")
    aside = server_dir.with_name(server_dir.name + ".replaced")
    recover(server_dir)
    if staging.exists():
        shutil.rmtree(staging)
    try:
        size = archive.stat().st_size
    except OSError as e:
        raise RestoreError(f"the backup {archive.name} can't be read: {e}") from e
    # A backup unpacks to at least its own size (worlds are already compressed).
    safearchive.ensure_space(staging, size, RestoreError, f"restoring {archive.name}")
    skipped = safearchive.Skipped(f"the backup {safearchive.printable(archive.name)}")
    staging.mkdir(parents=True)
    result = {"locked": [], "opened": [], "why": None, "kept": []}
    try:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(staging, filter=_restore_filter(staging, skipped))
        skipped.log()
        if not (staging / "server").is_dir() or (staging / "server").is_symlink():
            raise RestoreError("it isn't a Craft Conductor backup (there's no server folder in it)")
        info = _about_file(staging / ABOUT)
        if info is not None:
            result = _complete(staging, server_dir, info, skipped)
        props = staging / "server" / "server.properties"
        if props.is_file() and parts.properties_without_secrets(props.read_bytes().decode("latin-1"))[1]:
            private.protect(props)  # (unpacked with the folder's permissions: its passwords are this account's only)
    except BaseException as e:
        _put_back_kept(staging, server_dir)
        shutil.rmtree(staging, ignore_errors=True)
        reason = _why(e)
        if reason is None:
            raise
        log.error("couldn't restore %s: %s. The server was left as it was", archive.name, reason)
        raise RestoreError(f"the backup {archive.name} can't be restored: {reason}. "
                           "The server was left as it was") from e
    if aside.exists():  # (left over from a restore that finished, but was stopped before tidying up)
        shutil.rmtree(aside)
    if server_dir.exists():
        try:
            server_dir.rename(aside)
        except OSError as e:
            _put_back_kept(staging, server_dir)
            shutil.rmtree(staging, ignore_errors=True)
            raise RestoreError(f"the server folder couldn't be moved aside ({e}): is a program still using a "
                               "file in it? The server was left as it was") from e
    try:
        (staging / "server").rename(server_dir)
    except OSError:
        if aside.exists() and not server_dir.exists():
            aside.rename(server_dir)  # put it back
        _put_back_kept(staging, server_dir)
        shutil.rmtree(staging, ignore_errors=True)
        raise
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(aside, ignore_errors=True)
    return result


def _about_file(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _complete(staging: Path, server_dir: Path, info: dict, skipped) -> dict:
    """Make the unpacked backup a whole server: open its locked part if it was locked here, and
    keep the server's own copy of what it left out."""
    new = staging / "server"
    level = str(info.get("level") or "world")
    holds, locked = set(info.get("holds") or []), set(info.get("locked") or [])
    excluded = set(info.get("excluded") or [])
    opened, why = set(), None
    if locked and (staging / LOCKED).is_file():
        inner = staging / "craft-conductor" / "locked.tar.gz"
        try:
            lockbox.unlock_file(staging / LOCKED, inner)
            with tarfile.open(inner, "r:gz") as tar:
                tar.extractall(staging, filter=_restore_filter(staging, skipped))
            opened = locked
        except lockbox.LockedElsewhere:
            why = "they were locked on another computer or account"
        except (ValueError, OSError, tarfile.TarError, EOFError, zlib.error) as e:
            why = f"that part of the backup is damaged ({e})"
        finally:
            inner.unlink(missing_ok=True)
    kept = []
    current_props = server_dir / "server.properties"
    mine = (read_properties(current_props).get("level-name") or "world") if current_props.is_file() else level
    if "world" not in holds and mine != level and (new / "server.properties").is_file():
        write_properties(new / "server.properties", {"level-name": mine})  # (the world kept is the one it uses)
    if server_dir.is_dir():
        for rel, part in parts.split(server_dir, mine):
            if ((part in parts.CHOICES and part not in holds) or rel.split("/", 1)[0] in excluded
                    or (part in parts.LOCKED and part not in opened)) and not (new / rel).exists():
                kept.append(rel)
    if "secrets" not in opened and current_props.is_file() and (new / "server.properties").is_file():
        _, mine = parts.properties_without_secrets(current_props.read_bytes().decode("latin-1"))
        if mine:  # (the server's own passwords, into the backup's settings)
            restored = (new / "server.properties").read_bytes().decode("latin-1")
            text, theirs = parts.properties_without_secrets(restored)
            private.write_bytes(new / "server.properties",
                                parts.properties_with_secrets(text, {**mine, **theirs}).encode("latin-1"))
    (staging / KEPT).parent.mkdir(parents=True, exist_ok=True)
    (staging / KEPT).write_text(json.dumps(kept), encoding="utf-8")  # (first: an interruption puts them back)
    for rel in kept:
        (new / rel).parent.mkdir(parents=True, exist_ok=True)
        os.replace(server_dir / rel, new / rel)
    if locked - opened:
        log.warning("restoring: the backup's %s couldn't be opened (%s); the server's own were kept",
                    " and ".join(sorted(locked - opened)), why)
    return {"locked": sorted(locked), "opened": sorted(opened), "why": why, "kept": kept}


def _put_back_kept(staging: Path, server_dir: Path) -> None:
    """Move what a restore took from the server folder (``kept.json``) back into it."""
    try:
        kept = json.loads((staging / KEPT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for rel in kept if isinstance(kept, list) else []:
        moved, home = staging / "server" / str(rel), server_dir / str(rel)
        try:
            if moved.exists() and not home.exists() and server_dir.is_dir():
                home.parent.mkdir(parents=True, exist_ok=True)
                os.replace(moved, home)
        except OSError as e:
            log.error("couldn't put %s back into %s: it's in %s (%s)", rel, server_dir, moved, e)
    (staging / KEPT).unlink(missing_ok=True)


def _why(e: BaseException) -> str | None:
    """A restore failure in plain words (None for one that isn't about the backup or the disk)."""
    if isinstance(e, RestoreError):
        return str(e)
    if isinstance(e, tarfile.FilterError):
        return f"it holds a file or link that would end up outside the server folder ({e})"
    if isinstance(e, OSError) and e.errno == errno.ENOSPC:
        return "the disk filled up while unpacking it"
    if isinstance(e, (tarfile.TarError, EOFError, zlib.error, gzip.BadGzipFile)):
        return f"it's damaged or cut short ({e})"
    if isinstance(e, OSError):
        return f"it couldn't be unpacked ({e})"
    return None


PUT_BACK = "the server folder was put back (a restore had been interrupted)"
CUT_OFF = "a roll back was stopped before it changed anything (the server is as it was)"


def recover(server_dir: Path) -> str | None:
    """Put the server folder back if Craft Conductor stopped in the middle of swapping a restored
    backup in (the computer turned off between the two renames): the old folder is still there,
    complete, as ``<dir>.replaced``. A restore stopped while unpacking (``<dir>.restoring`` with
    nothing of the server's in it) changed nothing: its half-unpacked copy is removed, and said.
    Returns what was done (PUT_BACK or CUT_OFF), or None."""
    aside = server_dir.with_name(server_dir.name + ".replaced")
    done = None
    if aside.is_dir() and not server_dir.exists():
        aside.rename(server_dir)
        log.warning("put the server folder %s back: a restore was interrupted", server_dir)
        done = PUT_BACK
    staging = server_dir.with_name(server_dir.name + ".restoring")
    if (staging / KEPT).is_file():
        if server_dir.is_dir():
            _put_back_kept(staging, server_dir)
            done = PUT_BACK
    elif staging.is_dir() and server_dir.is_dir():  # (only the backup's files: nothing of the server's to lose)
        shutil.rmtree(staging, ignore_errors=True)
        log.warning("a restore into %s was stopped while unpacking; the server is as it was, and the "
                    "half-unpacked copy was removed", server_dir)
        done = done or CUT_OFF
    return done
