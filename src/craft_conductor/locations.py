"""Where Craft Conductor keeps servers, backups and exports, as the owner chose them, and moving
what's there when one of them changes.

The places are Craft Conductor's own setting (hub.json ``locations``), offered once after the
first sign-in and changeable in Craft Conductor settings → Folders. By default they're as they
always were: servers in ``<home>/servers``, each server's backups in its own folder, exports in
``<home>/exports``. A chosen backups folder holds one folder per server (``<folder>/<id>``), set
in each server's craft-conductor.toml (``[backups] dir``); a server whose own file names another
backups folder keeps it.

A place is refused when it's inside another one (or holds one), inside Craft Conductor's own
folders, a system folder, a network folder or a removable drive. A synced folder (OneDrive,
Dropbox, Google Drive) is fine for backups and exports, and only warned about for servers.

Moving never deletes anything before its copy is checked: on the same drive a folder is renamed;
otherwise each file is copied, the copy read back and its SHA-256 compared with the original,
and only then are the originals deleted, one checked file at a time (links are never followed;
a folder with a link in it isn't moved). A note in the state folder (``move.json``) says what's
under way: if Craft Conductor stops halfway, the next start puts everything back as it was.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import stat
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import folders, private

log = logging.getLogger(__name__)

KINDS = ("servers", "backups", "exports")
README = "README.txt"
JOURNAL = "move.json"
RESERVE = 256 << 20  # free space kept on the drive moved to (as when unpacking: safearchive.DISK_RESERVE)
DRIVE_REMOVABLE = 2
_WINDOWS_SYSTEM = ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData")
_POSIX_SYSTEM = ("/bin", "/boot", "/dev", "/etc", "/lib", "/lib32", "/lib64", "/libx32", "/proc", "/sbin", "/sys", "/usr",
                 "/System", "/Library", "/Applications", "/private/etc", "/opt/homebrew")
_POSIX_SYSTEM_ITSELF = ("/", "/home", "/Users", "/var", "/private", "/private/var", "/opt", "/srv", "/mnt", "/media", "/Volumes",
                        "/run", "/tmp")
_SYNCED_NAMES = ("onedrive", "dropbox", "google drive", "googledrive", "my drive", "icloud drive", "mobile documents",
                 "box", "pcloud drive", "mega")


class LocationError(ValueError):
    """A place that can't be used, or a move that can't go ahead, said in plain words."""


# ------------------------------------------------------------------ the setting
def defaults(home: Path) -> dict:
    return {"servers": home / "servers", "backups": None, "exports": home / "exports"}


def read(data: dict, home: Path) -> dict:
    """The places from hub.json's ``locations`` (the defaults where it says nothing), and whether
    the owner has chosen them (``chosen``)."""
    raw = data.get("locations") if isinstance(data.get("locations"), dict) else {}
    out: dict = dict(defaults(home))
    for kind in KINDS:
        value = raw.get(kind)
        if isinstance(value, str) and value and Path(value).is_absolute():
            out[kind] = Path(value)
    out["chosen"] = bool(raw.get("chosen"))
    return out


def servers_folder(home: Path) -> Path:
    """Where the servers are kept, read from hub.json without a Hub (cli: is this computer running servers?)."""
    from .config import STATE_DIR
    try:
        data = json.loads((home / STATE_DIR / "hub.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return read(data if isinstance(data, dict) else {}, home)["servers"]


def stored(places: dict, chosen: bool = True) -> dict:
    """``places`` as hub.json keeps them."""
    return {**{k: str(places[k]) if places.get(k) else None for k in KINDS}, "chosen": chosen}


def choosable() -> str | None:
    """Why the places can't be chosen here (None when they can): Docker keeps everything in its
    volume, so a folder outside it would be lost when the container is replaced."""
    if os.environ.get("CRAFT_CONDUCTOR_CONTAINER"):
        return ("Craft Conductor runs in a container here: everything is kept in its /data volume, so the folders "
                "can't be changed (one outside the volume would be lost when the container is replaced).")
    return None


# ------------------------------------------------------------------ what a place may be
def _norm(path: Path | str) -> str:
    return os.path.normcase(os.path.realpath(path)).rstrip("\\/") or os.sep


def inside(child: Path | str, parent: Path | str) -> bool:
    """``child`` is ``parent`` or inside it (both as the real folders they are)."""
    c, p = _norm(child), _norm(parent)
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


def _existing(path: Path) -> Path | None:
    """The deepest folder of ``path`` that's there (itself, or the parent it will be made in)."""
    for p in (path, *path.parents):
        if p.is_dir():
            return p
    return None


def is_network(path: Path) -> bool:
    return folders.is_network(path) or (sys.platform == "darwin" and _under_volumes(path))


def is_removable(path: Path) -> bool:
    if os.name == "nt":
        return _drive_type(path) == DRIVE_REMOVABLE
    if sys.platform == "darwin":
        return _under_volumes(path)
    real = _norm(path)
    return real.startswith(("/media/", "/run/media/")) or real in ("/media", "/run/media")


def _drive_type(path: Path) -> int:
    drive = os.path.splitdrive(os.path.realpath(path))[0]
    if not drive or drive.startswith("\\\\"):
        return 0
    import ctypes
    return ctypes.windll.kernel32.GetDriveTypeW(drive + "\\")


def _under_volumes(path: Path) -> bool:
    """macOS: other drives, USB sticks and network shares appear under /Volumes (the startup
    drive's own entry there leads back to /)."""
    real = os.path.realpath(path)
    return real.startswith("/Volumes/")


def is_system(path: Path) -> bool:
    real = _norm(path)
    if os.name == "nt":
        drive, rest = os.path.splitdrive(real)
        if not rest.strip("\\/"):
            return True  # (the top of a drive)
        users = os.path.normcase(os.path.dirname(os.path.expanduser("~")))
        if real == users:
            return True  # (C:\Users, where everyone's home folder is)
        for var in _WINDOWS_SYSTEM:
            if os.environ.get(var) and inside(real, os.environ[var]):
                return True
        return False
    if real in _POSIX_SYSTEM_ITSELF:
        return True
    return any(real == p or real.startswith(p + "/") for p in _POSIX_SYSTEM)


def is_synced(path: Path) -> str | None:
    """The app syncing ``path`` (OneDrive, Dropbox, Google Drive...), if it's in a synced folder."""
    real = _norm(path)
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        if os.environ.get(var) and inside(real, os.environ[var]):
            return "OneDrive"
    if "/library/cloudstorage/" in real.replace("\\", "/").lower():
        return "a cloud storage app"
    for part in Path(real).parts:
        low = part.lower()
        for name in _SYNCED_NAMES:
            if low == name or low.startswith(name + " -") or low.startswith(name + " ("):
                return {"onedrive": "OneDrive", "dropbox": "Dropbox", "google drive": "Google Drive", "googledrive": "Google Drive",
                        "my drive": "Google Drive", "icloud drive": "iCloud", "mobile documents": "iCloud"}.get(name, part)
    return None


def own_folders(state_dir: Path) -> tuple[list[Path], list[Path]]:
    """Craft Conductor's own folders: nothing goes in them, and no place holds them (its settings
    folder; its program files when it's installed with pip, or a build's _internal folder). And the
    folder the downloaded program file is in (Downloads, often): never a place itself, nor one that
    holds it, but a folder inside it can be."""
    inside_too, itself = [state_dir], []
    if getattr(sys, "frozen", False):
        itself.append(Path(sys.executable).parent)
        if (Path(sys.executable).parent / "_internal").is_dir():
            inside_too.append(Path(sys.executable).parent / "_internal")
    else:
        inside_too.append(Path(__file__).resolve().parent)
    return inside_too, itself


def check_place(kind: str, text: str, places: dict, state_dir: Path) -> tuple[Path, list[str]]:
    """A place typed or picked for ``kind``: the real folder it is (it may not be there yet: then
    its parent must be), and warnings to show. Refused with LocationError, saying why."""
    text = str(text or "").strip()
    if not text or len(text) > 1000 or "\0" in text:
        raise LocationError("type the full path of a folder")
    path = Path(os.path.expanduser(text))
    if not path.is_absolute():
        raise LocationError(f"{text} isn't a full path (it starts with a drive like D:\\ or with /)")
    if is_network(path):
        raise LocationError(f"{text} is on the network: Craft Conductor keeps its files on this computer's own drives")
    path = Path(os.path.realpath(path))
    if is_network(path):  # (a link that leads to the network)
        raise LocationError(f"{text} leads to the network: Craft Conductor keeps its files on this computer's own drives")
    base = _existing(path)
    if base is None:
        raise LocationError(f"there's no drive or folder for {text}")
    if path.exists() and not path.is_dir():
        raise LocationError(f"{path} is a file, not a folder")
    if is_system(path):
        raise LocationError(f"{path} is one of the computer's own folders: pick a folder of yours, or make one")
    if is_removable(path):
        raise LocationError(f"{path} is on a removable drive (a USB stick or a memory card): the files would go "
                            "missing whenever it's unplugged")
    if not os.access(base, os.W_OK | os.X_OK):
        raise LocationError(f"Craft Conductor isn't allowed to write in {base}")
    inside_too, itself = own_folders(state_dir)
    for own in inside_too:
        if inside(path, own) or inside(own, path):
            raise LocationError(f"{path} {'is inside' if inside(path, own) else 'holds'} Craft Conductor's own folder "
                                f"({own}): pick another folder")
    for own in itself:
        if inside(own, path):
            raise LocationError(f"{path} holds Craft Conductor's program ({own}): pick another folder, or a new folder inside it")
    for other in KINDS:
        where = places.get(other)
        if other == kind or not where:
            continue
        if inside(path, where) or inside(where, path):
            raise LocationError(f"{path} {'is inside' if inside(path, where) else 'holds'} the {other} folder ({where}): "
                                "each one needs a folder of its own")
    warnings = []
    synced = is_synced(path)
    if synced and kind == "servers":
        warnings.append(f"{path} is synced by {synced}: a running world would upload all day, and {synced} can lock "
                        "files while it syncs them, which can stop a server from saving. Backups and exports are fine "
                        "there; servers are better kept in a folder that isn't synced.")
    return path, warnings


# ------------------------------------------------------------------ what's in each folder
READMES = {
    "servers": """Craft Conductor's servers
=========================

One folder per server, named after it (its id):

  <server>/craft-conductor.toml   the server's settings in Craft Conductor
  <server>/server/                Minecraft itself: the world, mods or plugins, server.properties
  <server>/backups/               its backups, unless Craft Conductor keeps backups in a folder of their own
  <server>/manual-downloads/      mods downloaded by hand from CurseForge
  <server>/.craft-conductor/      what Craft Conductor remembers about it (logs, reports)

To keep servers somewhere else, use Craft Conductor settings -> Folders: it moves them for you.
Moving or renaming these folders by hand makes Craft Conductor lose track of them.
""",
    "backups": """Craft Conductor's backups
=========================

One folder per server, named after it (its id), with that server's backups:

  <server>/<date>-<label>.tar.gz   a backup (the Backups page lists them, and restores them)
  <server>/*.json                  notes about each backup (what changed, whether it was checked)

To keep backups somewhere else, use Craft Conductor settings -> Folders: it moves them for you.
""",
    "exports": """Craft Conductor's exports
=========================

Servers packed to move to another computer (a server's Settings -> Export server...):

  <server>/<name>.craft-conductor.zip   an export: on the other computer, Servers -> Import a server...

Copy an export to carry it (don't move it). To keep exports somewhere else, use
Craft Conductor settings -> Folders: it moves them for you.
""",
}


def write_readme(kind: str, folder: Path) -> None:
    """A short README.txt saying what's in the folder (written once; one already there stays)."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / README
        if not path.exists():
            path.write_text(READMES[kind].replace("\n", os.linesep) if os.name == "nt" else READMES[kind], encoding="utf-8")
    except OSError as e:
        log.info("couldn't write %s in %s: %s", README, folder, e)


# ------------------------------------------------------------------ moving
@dataclass
class Item:
    """One folder (or file) to move: ``src`` to ``dst``; ``size`` bytes."""
    src: Path
    dst: Path
    size: int = 0
    how: str = ""          # "rename" (the same drive) or "copy"
    done: bool = False


@dataclass
class Plan:
    kind: str
    old: Path | None
    new: Path | None
    items: list[Item] = field(default_factory=list)

    @property
    def size(self) -> int:
        return sum(i.size for i in self.items)


def _links_in(path: Path) -> Path | None:
    """The first link (a symlink, or a Windows junction) in a folder, if any."""
    st = os.lstat(path)
    if folders.link_stat(st):
        return path
    if not stat.S_ISDIR(st.st_mode):
        return None
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        for name in dirnames + filenames:
            p = Path(dirpath) / name
            try:
                if folders.link_stat(os.lstat(p)):
                    return p
            except OSError:
                return p
    return None


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for dirpath, _, filenames in os.walk(path, followlinks=False):
        for name in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                pass
    return total


def _same_drive(src: Path, dst: Path) -> bool:
    base = _existing(dst)
    try:
        return base is not None and os.stat(src).st_dev == os.stat(base).st_dev
    except OSError:
        return False


def prepare(plan: Plan) -> None:
    """Check a move can go ahead, before anything is touched: no links in what moves, each
    destination new or empty, and enough free space where it's copied to."""
    if plan.new is not None and plan.new.exists():
        if not plan.new.is_dir() or any(p.name != README for p in plan.new.iterdir()):
            raise LocationError(f"{plan.new} has files in it already: the new folder must be new or empty")
    for item in plan.items:
        link = _links_in(item.src)
        if link is not None:
            raise LocationError(f"{link} is a link to somewhere else: Craft Conductor doesn't move folders with links in them. "
                                "Remove the link, then try again")
        if item.dst.exists() and (not item.dst.is_dir() or any(item.dst.iterdir())):
            raise LocationError(f"{item.dst} is already there: the new folder must be new or empty")
        item.size = _size(item.src)
        item.how = "rename" if _same_drive(item.src, item.dst) else "copy"
    copied = sum(i.size for i in plan.items if i.how == "copy")
    if copied:
        base = _existing(plan.new or plan.items[0].dst)
        free = shutil.disk_usage(base).free if base else 0
        if copied + RESERVE > free:
            from .safearchive import size_words
            raise LocationError(f"there isn't enough free space on the drive of {plan.new or plan.items[0].dst}: moving needs "
                                f"{size_words(copied)} (and {size_words(RESERVE)} to spare), and it has {size_words(free)} free")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _copy_checked(src: Path, dst: Path, done: Callable[[int], None]) -> None:
    """Copy one file, then read the copy back: its SHA-256 must be the original's. A file that was
    this account's only (a secret in it) is so before anything goes in the copy."""
    h = hashlib.sha256()
    with open(src, "rb") as fin, open(dst, "xb") as fout:
        private.keep_access(src, dst)
        while chunk := fin.read(1 << 20):
            h.update(chunk)
            fout.write(chunk)
            done(len(chunk))
    shutil.copystat(src, dst, follow_symlinks=False)
    if _sha256(dst) != h.hexdigest():
        raise LocationError(f"the copy of {src} isn't the same as the original (the drive may be failing); nothing was moved")


def copy_tree(src: Path, dst: Path, done: Callable[[int], None]) -> list[Path]:
    """Copy a folder (or a file) file by file, each copy checked: the files copied (relative)."""
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        _copy_checked(src, dst, done)
        return [Path("")]
    copied = []
    dst.mkdir(parents=True, exist_ok=True)
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        rel = Path(dirpath).relative_to(src)
        for name in dirnames:
            (dst / rel / name).mkdir(exist_ok=True)
        for name in filenames:
            _copy_checked(Path(dirpath) / name, dst / rel / name, done)
            copied.append(rel / name)
    return copied


def remove_copied(src: Path, files: list[Path]) -> list[Path]:
    """Delete the originals that were copied and checked (never following a link), then the
    folders left empty: what couldn't be deleted (a file in use)."""
    left = []
    if files == [Path("")]:
        try:
            if not folders.link_stat(os.lstat(src)):
                src.unlink()
        except OSError:
            left.append(src)
        return left
    for rel in files:
        p = src / rel
        try:
            st = os.lstat(p)
            if stat.S_ISREG(st.st_mode) and not folders.link_stat(st):
                if not st.st_mode & stat.S_IWRITE:
                    os.chmod(p, stat.S_IWRITE)  # (Windows marks some files read-only)
                p.unlink()
        except OSError:
            left.append(p)
    for dirpath, _, _ in sorted(os.walk(src, topdown=False, followlinks=False), key=lambda x: -len(x[0])):
        try:
            if not folders.link_stat(os.lstat(dirpath)):
                os.rmdir(dirpath)  # (only when empty)
        except OSError:
            pass
    return left


def _remove_tree_made(path: Path) -> None:
    """Remove a folder this move made (its copies): files and folders, never following a link."""
    if not path.exists() and not os.path.islink(path):
        return
    st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode) or folders.link_stat(st):
        path.unlink()
        return
    for dirpath, dirnames, filenames in os.walk(path, topdown=False, followlinks=False):
        for name in filenames:
            p = Path(dirpath) / name
            try:
                os.chmod(p, stat.S_IWRITE)
            except OSError:
                pass
            p.unlink()
        for name in dirnames:
            p = Path(dirpath) / name
            try:
                os.rmdir(p)  # (a folder emptied above, or a link to a folder: the link goes, not what it leads to)
            except NotADirectoryError:
                p.unlink()
    os.rmdir(path)


class Mover:
    """Moves a plan's items, keeping ``move.json`` up to date so a stop halfway can be undone.
    ``switch()`` (done once everything is in its new place) makes the new place the one used."""

    def __init__(self, plan: Plan, state_dir: Path, extra: dict | None = None):
        self.plan, self.journal = plan, state_dir / JOURNAL
        self.extra = extra or {}       # what else to put back if it stops (e.g. craft-conductor.toml values)
        self.total = sum(i.size for i in plan.items if i.how == "copy") or 1
        self.copied = 0
        self.files: dict[int, list[Path]] = {}
        self.left: list[Path] = []

    def _note(self, phase: str) -> None:
        data = {"kind": self.plan.kind, "old": str(self.plan.old) if self.plan.old else None,
                "new": str(self.plan.new) if self.plan.new else None, "phase": phase, "extra": self.extra,
                "items": [{"src": str(i.src), "dst": str(i.dst), "how": i.how, "done": i.done} for i in self.plan.items],
                "at": time.time()}
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.journal.with_name(JOURNAL + ".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, self.journal)

    def progress(self) -> float:
        return min(1.0, self.copied / self.total)

    def run(self, switch: Callable[[], None]) -> list[Path]:
        """Move everything, call ``switch``, then delete the originals that were copied. On any
        error before ``switch`` is done, everything is put back and the error raised again.
        The originals that couldn't be deleted (in use) are given back."""
        self._note("moving")
        try:
            for n, item in enumerate(self.plan.items):
                item.dst.parent.mkdir(parents=True, exist_ok=True)
                if item.how == "rename":
                    try:
                        os.rename(item.src, item.dst)
                    except OSError:
                        item.how = "copy"  # (a file in use, an antivirus: copy it instead)
                        self.total += item.size
                if item.how == "copy":
                    self._note("moving")  # (it says "copy" before the copy starts)
                    self.files[n] = copy_tree(item.src, item.dst, self._count)
                item.done = True
                self._note("moving")
            switch()
            self._note("switched")
        except BaseException:
            self.undo()
            raise
        for n, item in enumerate(self.plan.items):
            if item.how == "copy":
                self.left += remove_copied(item.src, self.files.get(n, []))
        self.journal.unlink(missing_ok=True)
        return self.left

    def _count(self, n: int) -> None:
        self.copied += n

    def undo(self) -> None:
        undo_items([(i.src, i.dst, i.how, i.done) for i in self.plan.items])
        self.journal.unlink(missing_ok=True)


def undo_items(items: list[tuple[Path, Path, str, bool]]) -> None:
    """Put back what a move did: renamed folders are renamed back, copies are removed (the
    originals are all still there: nothing is deleted before the new place is the one used)."""
    for src, dst, how, done in reversed(items):
        try:
            if how == "rename" and done and dst.exists() and not src.exists():
                os.rename(dst, src)
            elif how == "copy" and (dst.exists() or os.path.islink(dst)) and src.exists():
                _remove_tree_made(dst)
        except OSError as e:
            log.warning("couldn't put back %s (from %s): %s", src, dst, e)


def recover(state_dir: Path, put_back: Callable[[dict], None]) -> str | None:
    """At start: a move that stopped halfway is undone (``put_back`` restores what ``extra`` says),
    or, when it had already switched, its leftovers are named. What happened, for the log and the page."""
    path = state_dir / JOURNAL
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        path.unlink(missing_ok=True)
        return "a damaged note about moving files was removed"
    kind, old = str(data.get("kind") or "files"), data.get("old") or "where they were"
    items = [(Path(x["src"]), Path(x["dst"]), str(x.get("how") or ""), bool(x.get("done")))
             for x in data.get("items", []) if isinstance(x, dict) and x.get("src") and x.get("dst")]
    if data.get("phase") == "switched":
        path.unlink(missing_ok=True)
        left = [str(s) for s, _, how, _ in items if how == "copy" and Path(s).exists()]
        return (f"moving the {kind} to {data.get('new')} had finished, but Craft Conductor stopped before the old copies were "
                f"deleted: they're still in {', '.join(left)}" if left else None)
    undo_items(items)
    try:
        put_back(data.get("extra") or {})
    finally:
        path.unlink(missing_ok=True)
    return f"moving the {kind} was stopped halfway: everything was put back in {old}"
