"""Snapshots of the server directory, used for manual restores and automatic rollback."""

from __future__ import annotations

import logging
import re
import shutil
import tarfile
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

SUFFIX = ".tar.gz"


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

    log.info("backing up %s -> %s", server_dir, dest)
    # Region files are already compressed, so a fast compression level is plenty.
    with tarfile.open(tmp, "w:gz", compresslevel=1) as tar:
        tar.add(server_dir, arcname="server", filter=keep)
    tmp.rename(dest)
    return dest


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


def restore(archive: Path, server_dir: Path) -> None:
    """Replace ``server_dir`` with the archive's contents.

    The current directory is kept as ``<dir>.replaced`` until the restore succeeds.
    """
    staging = server_dir.with_name(server_dir.name + ".restoring")
    aside = server_dir.with_name(server_dir.name + ".replaced")
    for p in (staging, aside):
        if p.exists():
            shutil.rmtree(p)
    staging.mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(staging, filter="data")
    restored = staging / "server"
    if not restored.is_dir():
        shutil.rmtree(staging)
        raise ValueError(f"{archive} is not an craft-conductor backup")
    if server_dir.exists():
        server_dir.rename(aside)
    restored.rename(server_dir)
    shutil.rmtree(staging)
    if aside.exists():
        shutil.rmtree(aside)
