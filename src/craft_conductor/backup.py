"""Snapshots of the server directory, used for manual restores and automatic rollback."""

from __future__ import annotations

import errno
import gzip
import logging
import os
import re
import shutil
import tarfile
import time
import zlib
from datetime import datetime
from pathlib import Path

from . import safearchive

log = logging.getLogger(__name__)

SUFFIX = ".tar.gz"
MAX_RESTORE_BYTES = 1 << 40        # unpacked; the disk's free space decides first
MAX_RESTORE_MEMBERS = 2_000_000    # (a big web map can be hundreds of thousands of small files)
STALE_PART = 3600                  # an unfinished backup untouched this long was cut off


class RestoreError(ValueError):
    """A backup that can't be restored. The server is left exactly as it was."""


def create(server_dir: Path, backups_dir: Path, label: str, exclude: list[str]) -> Path:
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

    def keep(info: tarfile.TarInfo):
        top = Path(info.name).parts[1] if len(Path(info.name).parts) > 1 else ""
        return None if top in excluded or info.name.endswith("session.lock") else info

    _remove_stale_parts(backups_dir)
    log.info("backing up %s -> %s", server_dir, dest)
    try:
        # Region files are already compressed, so a fast compression level is plenty.
        with tarfile.open(tmp, "w:gz", compresslevel=1) as tar:
            tar.add(server_dir, arcname="server", filter=keep)
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
    return dest


def _remove_stale_parts(backups_dir: Path) -> None:
    """Unfinished backups left by a Craft Conductor that was stopped mid-way (they're never listed
    or restored, but they fill the disk). One still being written is younger than STALE_PART."""
    cutoff = time.time() - STALE_PART
    for part in backups_dir.glob(f"*{SUFFIX}.part"):
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


def restore(archive: Path, server_dir: Path) -> None:
    """Replace ``server_dir`` with the archive's contents.

    The backup is unpacked next to the server first (``<dir>.restoring``); the server is only
    touched once that worked, and is kept as ``<dir>.replaced`` until the new one is in place.
    A backup that is damaged, unsafe or too big for the disk raises :class:`RestoreError` and
    leaves the server as it was.
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
    try:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(staging, filter=_restore_filter(staging, skipped))
        skipped.log()
        if not (staging / "server").is_dir() or (staging / "server").is_symlink():
            raise RestoreError("it isn't a Craft Conductor backup (there's no server folder in it)")
    except BaseException as e:
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
            shutil.rmtree(staging, ignore_errors=True)
            raise RestoreError(f"the server folder couldn't be moved aside ({e}): is a program still using a "
                               "file in it? The server was left as it was") from e
    try:
        (staging / "server").rename(server_dir)
    except OSError:
        if aside.exists() and not server_dir.exists():
            aside.rename(server_dir)  # put it back
        shutil.rmtree(staging, ignore_errors=True)
        raise
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(aside, ignore_errors=True)


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


def recover(server_dir: Path) -> bool:
    """Put the server folder back if Craft Conductor stopped in the middle of swapping a restored
    backup in (the computer turned off between the two renames): the old folder is still there,
    complete, as ``<dir>.replaced``."""
    aside = server_dir.with_name(server_dir.name + ".replaced")
    if aside.is_dir() and not server_dir.exists():
        aside.rename(server_dir)
        log.warning("put the server folder %s back: a restore was interrupted", server_dir)
        return True
    return False
