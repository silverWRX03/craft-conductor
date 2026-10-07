"""Mods a new server needs downloaded by hand, found while it's still being set up.

CurseForge lets a mod's author stop other apps from downloading its files. Following CurseForge's
terms for third-party apps, Craft Conductor doesn't fetch such a file or look for it elsewhere:
the person downloads it from the file's CurseForge page. The setup page asks, as soon as a
modpack or mods are chosen, which of the files the server will ask for are like that (the same
file the planner picks: newest for the Minecraft version, loader and release channel), shows a
link to each, and takes the downloaded files back through the hub's staging area. An upload is
kept only when CurseForge's SHA-1 says it's one of those files, and creating the server moves it
into the server's manual-downloads folder, where the manager finds it.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

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


def early(channel: str | None) -> str | None:
    """A mod's own channel when it's an early one (its file in a pack is a beta or an alpha)."""
    return channel if channel in ("beta", "alpha") else None


def needed(http: HttpClient, key: str, loader: str, minecraft: str, mods: list[tuple[str, str | None]],
           pack_version: str = "", pack_exclude: list[str] | tuple[str, ...] = ()) -> list[dict]:
    """The files that must be downloaded by hand: of the CurseForge modpack ``pack_version`` (its
    server mods, less ``pack_exclude``) and of ``mods`` (CurseForge project ids, with their own
    channel), for ``loader`` and ``minecraft``."""
    specs: dict[str, ModSpec] = {}
    if pack_version.startswith("curseforge:"):
        from . import curseforgepack
        info = curseforgepack.preview(http, key, pack_version)
        loader, minecraft = info["loader"], info["minecraft"]
        excluded = set(pack_exclude)
        for m in info["mods"]:
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
    with _lock:
        if len(_wanted) > 2000:
            _wanted.clear()
        _wanted.update({x["sha1"]: x for x in out if x["sha1"]})
    return out


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
