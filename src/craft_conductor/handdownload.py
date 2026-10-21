"""Mods a new server needs downloaded by hand, found while it's still being set up.

CurseForge lets a mod's author stop other apps from downloading its files. Following CurseForge's
terms for third-party apps, Craft Conductor doesn't fetch such a file or look for it elsewhere:
the person downloads it from the file's CurseForge page. The setup page asks, as soon as a
modpack or mods are chosen, which of the files the server will ask for are like that (the same
file the planner picks: newest for the Minecraft version, loader and release channel), shows a
link to each, and takes the downloaded files back through the hub's staging area. An upload is
kept only when CurseForge's SHA-1 says it's one of those files, and creating the server moves it
into the server's manual-downloads folder, where the manager finds it.

The files are also found where the browser saved them (``look``): the computer's Downloads
folder, and folders the owner chose. Only the file names the page is waiting for are looked at
(and a browser's renames of them, like ``name (1).jar``), never any other file there; each is
copied, never moved, and kept only when the copy's SHA-1 is CurseForge's.
"""

from __future__ import annotations

import bisect
import logging
import os
import re
import shutil
import stat
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from .config import ModSpec
from .http import HttpClient, HttpError, sha1_file
from .loaders import LOADERS
from .mods.base import ModError, Unavailable, safe_file_name
from .mods.curseforge import CurseForgeProvider
from .planner import lowest

log = logging.getLogger(__name__)

MAX_MODS = 300           # mods looked up in one go (a pack's blocked ones are usually a handful)
SERVER_CHANNEL = "release"  # a new server's mod channel (setup doesn't change it)
CACHE_SECONDS = 3600     # the page asks again each time a mod is added: each mod's answer is kept a while
_wanted: dict[str, dict] = {}  # SHA-1 -> a file the setup page was told to download (what an upload may be)
_resolved: dict[tuple, tuple[float, dict | None]] = {}  # (mod, Minecraft, loader, channel) -> its file to download by hand, if any
_lock = threading.Lock()

MAX_FILE = 512 << 20     # the biggest file looked at in a folder (the same as an upload)
MAX_FOLDERS = 20         # folders remembered to look in
LIST_AGAIN = 60          # seconds: a folder's names are read again when it changed, or after this long
SETTLED = 2_000_000_000  # ns: a folder changed more recently than this is read again next time (its clock may not tick between two changes)
_PARTIAL = (".crdownload", ".part", ".download", ".partial")  # a browser still saving the file beside it
_hashed: dict[tuple[str, int, int], str] = {}  # (path, size, modified) -> its SHA-1: a file is read once
_listed: dict[str, tuple[int, float, "_Names"]] = {}  # folder -> (its modified time, when, its names)
_look_lock = threading.Lock()  # one look at a time (two pages open don't read the same files twice)


def early(channel: str | None) -> str | None:
    """A mod's own channel when it's an early one (its file in a pack is a beta or an alpha)."""
    return channel if channel in ("beta", "alpha") else None


def needed(http: HttpClient, key: str, loader: str, minecraft: str, mods: list[tuple[str, str | None]],
           pack_version: str = "", pack_exclude: list[str] | tuple[str, ...] = ()) -> list[dict]:
    """The files that must be downloaded by hand: of the CurseForge modpack ``pack_version`` (its
    server mods, less ``pack_exclude``) and of ``mods`` (CurseForge project ids, with their own
    channel), for ``loader`` and ``minecraft``."""
    specs: dict[str, ModSpec] = {}
    pack_ids: set[str] = set()
    if pack_version.startswith("curseforge:"):
        from . import curseforgepack
        info = curseforgepack.preview(http, key, pack_version)
        loader, minecraft = info["loader"], info["minecraft"]
        excluded = set(pack_exclude)
        for m in info["mods"]:
            pack_ids.add(m["project_id"])
            if m["manual"] and m["included_on_server"] and m["path"] not in excluded:
                specs[m["project_id"]] = ModSpec("curseforge", m["project_id"], channel=early(m.get("channel")))
    for pid, channel in mods:
        specs.setdefault(pid, ModSpec("curseforge", pid, channel=early(channel)))
    if not specs or loader not in LOADERS or not LOADERS[loader].mod_loaders or not minecraft:
        return []
    provider = CurseForgeProvider(http, key)
    out = []
    for spec in list(specs.values())[:MAX_MODS]:
        found = _hand_file(provider, spec, minecraft, loader)
        if found:
            out.append(found)
    picked = {pid for pid, _ in mods} - pack_ids  # (a pack's mods are as the pack says)
    out = [x for x in out if x["project_id"] not in _players_only(http, provider, [x for x in out if x["project_id"] in picked])]
    with _lock:
        if len(_wanted) > 2000:
            _wanted.clear()
        _wanted.update({x["sha1"]: x for x in out if x["sha1"]})
    return out


def _players_only(http: HttpClient, provider: CurseForgeProvider, files: list[dict]) -> set[str]:
    """Of these mods picked by themselves, the ones Modrinth says only run on players' computers:
    they'll be left off the server (sides.py), so they aren't asked for by hand (#146)."""
    if not files:
        return set()
    from . import sides
    from .mods.base import ModFile, Project
    from .mods.modrinth import ModrinthProvider
    items, projects = [], {}
    now = time.monotonic()
    for x in files:
        k = f"curseforge:{x['project_id']}"
        items.append(ModFile(key=k, source="curseforge", project_id=x["project_id"], name=x["name"], version_id="",
                             version_number=x["version"], filename=x["filename"], url="", sha1=x["sha1"] or None))
        with sides._known_lock:
            hit = sides._known.get(x["sha1"]) if x["sha1"] else None
        if hit and now - hit[0] < sides.CACHE_SECONDS:
            continue  # (Modrinth's answer for this file is known: no need for its slug)
        try:
            projects[k] = provider.project(x["project_id"])  # (its slug: found on Modrinth by it, when not by its file)
        except (ModError, HttpError):
            projects[k] = Project("curseforge", x["project_id"], "", x["name"])
    found = sides.on_modrinth(ModrinthProvider(http), items, projects)
    return {k.split(":", 1)[1] for k, p in found.items() if p.server_side == "unsupported"}


def _hand_file(provider: CurseForgeProvider, spec: ModSpec, minecraft: str, loader: str) -> dict | None:
    """The file of ``spec`` the server will ask for, when it must be downloaded by hand."""
    channel = lowest(SERVER_CHANNEL, spec.channel)
    key, now = (spec.id, minecraft, loader, channel), time.monotonic()
    with _lock:
        hit = _resolved.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    try:
        f = provider.resolve(spec, minecraft, LOADERS[loader].mod_loaders, channel)
    except (ModError, Unavailable, HttpError) as e:  # (setup says so when it makes the server)
        log.debug("couldn't look up CurseForge mod %s: %s", spec.id, e)
        return None  # (not kept: asked again next time)
    found = None
    if f.manual and f.manual_url and safe_file_name(f.filename):
        found = {"project_id": f.project_id, "name": f.name, "version": f.version_number,
                 "filename": f.filename, "url": f.manual_url, "sha1": (f.sha1 or "").lower()}
    with _lock:
        if len(_resolved) > 2000:
            _resolved.clear()
        _resolved[key] = (now, found)
    return found


def match(path: Path) -> dict | None:
    """The file the setup page asked for that ``path`` is (by CurseForge's SHA-1), if any."""
    digest = sha1_file(path)
    with _lock:
        return _wanted.get(digest)


def wanted_named(filenames: list[str]) -> list[dict]:
    """The files the setup page was told to download that have these names (what it still misses)."""
    with _lock:
        by_name = {x["filename"]: x for x in _wanted.values()}
    return [by_name[f] for f in dict.fromkeys(filenames) if f in by_name]


# ------------------------------------------------------- found where the browser saved them
class _Names(dict):
    """A folder's names (lower case -> as written), and the lower-case ones sorted, so the names
    that start like a file are found without going through them all (a big Downloads folder)."""

    def __init__(self, names):
        super().__init__({n.lower(): n for n in names})
        self.order = sorted(self)

    def starting(self, prefix: str) -> list[str]:
        i = bisect.bisect_left(self.order, prefix)
        out = []
        while i < len(self.order) and self.order[i].startswith(prefix) and len(out) < 200:
            out.append(self.order[i])
            i += 1
        return out


def _names(folder: Path) -> _Names:
    """The names in a folder, read again only when it changed (or now and then, for drives that
    don't say when a folder changes)."""
    try:
        changed = folder.stat().st_mtime_ns
    except OSError:
        return _Names([])
    now = time.monotonic()
    with _lock:
        hit = _listed.get(str(folder))
    if hit and hit[0] == changed and now - hit[1] < LIST_AGAIN:
        return hit[2]
    try:
        with os.scandir(folder) as entries:
            names = _Names(e.name for e in entries)
    except OSError:
        return _Names([])
    with _lock:
        if len(_listed) > 50:
            _listed.clear()
        if time.time_ns() - changed > SETTLED:
            _listed[str(folder)] = (changed, now, names)
        else:
            _listed.pop(str(folder), None)
    return names


def _candidates(names: _Names, filename: str) -> list[tuple[str, bool]]:
    """The files in a folder that may be ``filename``: that name, and the names browsers give a
    second copy (``name (1).jar``, Firefox's ``name(1).jar``; and, quietly, ``name-1.jar`` and
    ``name 2.jar``). ``True`` when a different file there under that name is worth saying so."""
    stem, dot, ext = filename.rpartition(".")
    stem, ext = (stem, dot + ext) if dot else (filename, "")
    loud = re.compile(re.escape(stem.lower()) + r" ?\(\d{1,4}\)" + re.escape(ext.lower()))
    quiet = re.compile(re.escape(stem.lower()) + r"[ -]\d{1,4}" + re.escape(ext.lower()))
    out = [(names[filename.lower()], True)] if filename.lower() in names else []
    for low in names.starting(stem.lower()):
        if loud.fullmatch(low):
            out.append((names[low], True))
        elif quiet.fullmatch(low):
            out.append((names[low], False))
    return out[:40]


def _open_file(path: Path) -> tuple[int, os.stat_result] | None:
    """A plain file opened for reading (not a link, not empty or too big, not still being saved),
    and what it was when it was opened; None otherwise."""
    from . import folders
    try:
        st = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode) or folders.link_stat(st) or folders.in_the_cloud(st) or not 0 < st.st_size <= MAX_FILE:
        return None  # (a link; a file only in OneDrive; an empty file: Firefox's while it downloads)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    try:
        opened = os.fstat(fd)
    except OSError:
        opened = None
    if opened is None or (opened.st_ino, opened.st_dev, opened.st_size) != (st.st_ino, st.st_dev, st.st_size):
        os.close(fd)  # (it was swapped for another file, or a link, in between)
        return None
    return fd, opened


def _digest(path: Path) -> str | None:
    """The SHA-1 of a plain file in a folder (worked out once for each size and modified time)."""
    got = _open_file(path)
    if got is None:
        return None
    fd, st = got
    key = (str(path), st.st_size, st.st_mtime_ns)
    with _lock:
        if key in _hashed:
            os.close(fd)
            return _hashed[key]
    import hashlib
    h = hashlib.sha1()
    try:
        with open(fd, "rb") as f:
            while chunk := f.read(1 << 16):
                h.update(chunk)
    except OSError:
        return None  # (not kept: read again next time)
    with _lock:
        if len(_hashed) > 2000:
            _hashed.clear()
        _hashed[key] = h.hexdigest()
    return _hashed[key]


def look(folders: list[Path], files: list[dict]) -> tuple[dict[str, Path], dict[str, Path]]:
    """Of ``files`` (each with its ``filename`` and CurseForge's ``sha1``), the ones in ``folders``:
    ``{filename: path}`` of those whose SHA-1 is CurseForge's, and of those that are there under the
    name but are another file (another version, or a download that went wrong). Nothing else in
    the folders is read; a file without a checksum isn't taken (drop it on the page instead)."""
    found: dict[str, Path] = {}
    wrong: dict[str, Path] = {}
    with _look_lock:
        for folder in folders:
            names = _names(folder)
            if not names:
                continue
            for x in files:
                filename, sha1 = x["filename"], str(x.get("sha1") or "").lower()
                if filename in found or not sha1:
                    continue
                for name, loud in _candidates(names, filename):
                    if any(name.lower() + p in names for p in _PARTIAL):
                        continue  # (the browser is still saving it)
                    digest = _digest(folder / name)
                    if digest == sha1:
                        found[filename] = folder / name
                        wrong.pop(filename, None)
                        break
                    if digest and loud:
                        wrong.setdefault(filename, folder / name)
    return found, wrong


class Changed(Exception):
    """The file changed while it was copied: its copy isn't CurseForge's file."""


def take(source: Path, dest: Path, sha1: str) -> Path:
    """Copy ``source`` to ``dest`` (the original stays where it is). The copy is kept only when its
    own SHA-1, read back from where it now is, is ``sha1``."""
    got = _open_file(source)
    if got is None:
        raise Changed(f"{source.name} isn't there any more")
    fd, _ = got
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        out_fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".found-")
    except OSError:
        os.close(fd)
        raise
    try:
        with open(fd, "rb") as src, open(out_fd, "wb") as out:
            copied = 0
            while chunk := src.read(1 << 16):
                copied += len(chunk)
                if copied > MAX_FILE:
                    raise Changed(f"{source.name} grew while it was copied")
                out.write(chunk)
        if sha1_file(Path(tmp)) != sha1.lower():
            raise Changed(f"{source.name} changed while it was copied")
        os.replace(tmp, dest)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return dest


def where_to_look(remembered: list[str], extra: Path | None = None, downloads: Path | None | bool = True) -> list[tuple[str, Path]]:
    """Where to look for files downloaded by hand: the Downloads folder (``downloads``, found here
    when it's left out), the folders the owner said to always look in, and ``extra`` (one chosen
    just this time). Each as (what the page calls it, the real folder); one that isn't there now
    (a drive unplugged) is left out."""
    from . import folders
    out: list[tuple[str, Path]] = []
    if downloads is True:
        downloads = folders.downloads_dir()
    if downloads:
        out.append(("Downloads", Path(os.path.realpath(downloads))))
    for text in [*remembered[:MAX_FOLDERS], *([str(extra)] if extra else [])]:
        try:
            real = folders.check(text)
        except folders.FolderError:
            continue
        if all(real != p for _, p in out):
            out.append((str(real), real))
    return out


def copy_found(found: dict[str, Path], files: list[dict], into: Callable[[dict], Path]) -> tuple[list[dict], list[dict]]:
    """Copy each file found (``look``) to ``into(file)``: what was taken, and what changed meanwhile."""
    by_name = {x["filename"]: x for x in files}
    taken, failed = [], []
    for filename, path in found.items():
        x = by_name[filename]
        if not safe_file_name(filename):
            continue  # (CurseForge's names are checked when they're read; never a path)
        try:
            take(path, into(x), x["sha1"])
        except (Changed, OSError) as e:
            log.info("couldn't take %s from %s: %s", filename, path.parent, e)
            failed.append(x)
            continue
        log.info("found %s, downloaded by hand, in %s", filename, path.parent)
        taken.append(x)
    return taken, failed
