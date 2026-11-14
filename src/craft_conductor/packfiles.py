"""A modpack's own files (its configs, scripts, resource packs...) for friends' Minecraft (#288).

A server made from a modpack gets the pack's mods and its overrides folder: the configs and scripts
the mods read. Players need the same ones: All the Mods 11's KubeGroovy scripts register items, and a
friend's game without them was refused by the server ("registries with unknown keys"). The pack's
own Prism instance, which has them, joined fine.

The friends' download (clientpack.py) names the modpack file the server is on, with its checksum, and
the friend's Craft Conductor downloads that file straight from CurseForge or Modrinth (as for mods:
nothing is handed out from the server), checks it, and unpacks its overrides into the game folder
the way launchers import a pack: CurseForge's overrides folder; Modrinth's overrides/ then
client-overrides/. The friend's own settings files (options.txt...) are only put there when missing.
What was unpacked is remembered, so the next version of the pack replaces it and what it no longer
has is removed.
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable

from . import safearchive

log = logging.getLogger(__name__)

KINDS = ("curseforge", "modrinth")
#: the friend's own settings: put there from the pack only when there's none yet, never replaced or removed
KEEP_THEIRS = frozenset({"options.txt", "optionsof.txt", "optionsshaders.txt", "servers.dat"})
CACHE_SECONDS = 3600
_SHA1 = re.compile(r"[0-9a-f]{40}")
_known: dict[tuple[str, str], tuple[float, dict | None]] = {}
_lock = threading.Lock()


# ----------------------------------------------------------------- the server's side
def describe(m) -> dict | None:
    """The modpack file the server ``m`` is on, for the friends' download: {kind, name, url, sha1,
    size}; None when it wasn't made from a pack, or the file can't be downloaded by other apps."""
    rec = m.config.modpack
    if rec is None or rec.source not in KINDS or m.loader.mods_folder != "mods":
        return None
    key, now = (rec.source, rec.version), time.monotonic()
    with _lock:
        hit = _known.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    try:
        found = _curseforge(m, rec) if rec.source == "curseforge" else _modrinth(m, rec)
    except Exception as e:  # (friends still get the mods; asked again next time)
        log.warning("couldn't look up the modpack's file for friends (%s): they get its mods only for now", e)
        return None
    with _lock:
        if len(_known) > 200:
            _known.clear()
        _known[key] = (now, found)
    return found


def _curseforge(m, rec) -> dict | None:
    from .curseforgepack import _Api, _sha1
    provider = m.providers.get("curseforge")
    key = getattr(provider, "api_key", "") if provider is not None else ""
    if not key or not rec.version.isdigit():
        return None
    f = _Api(m.http, key).files([int(rec.version)]).get(int(rec.version)) or {}
    return _entry("curseforge", rec.name, f.get("downloadUrl"), _sha1(f), f.get("fileLength"))


def _modrinth(m, rec) -> dict | None:
    from .mods.modrinth import API
    if not re.fullmatch(r"[A-Za-z0-9]{1,64}", rec.version):
        return None
    files = (m.http.get_json(f"{API}/version/{rec.version}") or {}).get("files") or []
    f = next((x for x in files if isinstance(x, dict) and x.get("primary")), files[0] if files else {})
    f = f if isinstance(f, dict) else {}
    return _entry("modrinth", rec.name, f.get("url"), (f.get("hashes") or {}).get("sha1"), f.get("size"))


def _entry(kind: str, name, url, sha1, size) -> dict | None:
    from .clientpack import allowed_url
    if not isinstance(url, str) or not allowed_url(url) or not isinstance(sha1, str) or not _SHA1.fullmatch(sha1.lower()):
        return None  # (an author who keeps the pack to CurseForge's own app: friends get its mods only)
    return {"kind": kind, "name": str(name or "the modpack")[:100], "url": url, "sha1": sha1.lower(),
            "size": size if isinstance(size, int) and size >= 0 else 0}


# ----------------------------------------------------------------- the friend's side
def checked(info: object) -> dict | None:
    """``pack_files`` from a server, checked before it's acted on; raises ValueError."""
    from .clientpack import allowed_url
    if info is None:
        return None
    if not isinstance(info, dict) or info.get("kind") not in KINDS or not allowed_url(str(info.get("url", ""))) \
            or not _SHA1.fullmatch(str(info.get("sha1", ""))):
        raise ValueError("the modpack's file isn't one Craft Conductor downloads")
    name = " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", str(info.get("name") or "")).split())[:100] or "the modpack"
    size = info.get("size")
    return {"kind": info["kind"], "name": name, "url": info["url"], "sha1": info["sha1"],
            "size": size if isinstance(size, int) and size >= 0 else 0}


def _download(http, info: dict, folder: Path) -> Path:
    from .modpack import MAX_PACK
    return http.download(info["url"], folder / "pack.zip", sha1=info["sha1"], max_bytes=MAX_PACK)


def _members(path: Path, kind: str, base: Path) -> tuple[zipfile.ZipFile, list[tuple[zipfile.ZipInfo, tuple[str, ...]]]]:
    """The pack's own files for players (each checked: none can land outside ``base``)."""
    from .modpack import MAX_PACK_FILES, ModpackError, _override_members
    if kind == "curseforge":
        from .curseforgepack import read_manifest
        manifest, z = read_manifest(path)
        prefixes: tuple[str, ...] = (str(manifest.get("overrides") or "overrides") + "/",)
    else:
        safearchive.check_zip(path, MAX_PACK_FILES, ModpackError)
        try:
            z = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError) as e:
            raise ModpackError("the modpack's file is damaged") from e
        prefixes = ("overrides/", "client-overrides/")  # (the second for players: it wins)
    try:
        return z, _override_members(z, base, "the modpack's files", prefixes)
    except BaseException:
        z.close()
        raise


def sync(http, info: dict | None, game_dir: Path, state: dict, say: Callable[[str], None] = print) -> int:
    """Put the pack's own files in ``game_dir`` (``info``: checked()). ``state`` is the game folder's
    record (join.MANIFEST): its ``pack_files`` says what was put there before, and is updated. Returns
    how many files were written (0: up to date)."""
    before = state.get("pack_files") if isinstance(state.get("pack_files"), dict) else {}
    placed_before = {p for p in before.get("files") or [] if isinstance(p, str)}
    if info is None:  # (the server isn't on a pack any more)
        _remove(game_dir, placed_before)
        state.pop("pack_files", None)
        return 0
    if before.get("sha1") == info["sha1"] and all(_inside(game_dir, p) and _inside(game_dir, p).is_file() for p in placed_before):
        return 0
    say(f"  downloading {info['name']}'s settings and scripts")
    placed: set[str] = set()
    with tempfile.TemporaryDirectory() as tmp:
        z, members = _members(_download(http, info, Path(tmp)), info["kind"], game_dir)
        with z:
            from .packupdate import copy_member
            for member, parts in members:
                rel = "/".join(parts)
                if len(parts) == 1 and parts[0].lower() in KEEP_THEIRS:
                    if not (game_dir / rel).exists():  # (their own: only when there's none yet, and not looked after)
                        _copy(z, member, game_dir, parts, copy_member)
                    continue
                if _copy(z, member, game_dir, parts, copy_member):
                    placed.add(rel)
    _remove(game_dir, placed_before - placed)
    state["pack_files"] = {"sha1": info["sha1"], "files": sorted(placed)}
    return len(placed)


def _copy(z, member, base: Path, parts: tuple[str, ...], copy_member) -> bool:
    try:
        copy_member(z, member, base, parts)
        return True
    except safearchive.UnsafeName as e:
        log.warning("left out the modpack's %s: %s", safearchive.printable("/".join(parts)), e)
        return False


def _inside(base: Path, rel: str) -> Path | None:
    try:
        return base.joinpath(*safearchive.parts(rel))
    except safearchive.UnsafeName:
        return None


def _remove(game_dir: Path, rels: set[str]) -> None:
    """The pack's files put there before that it doesn't have any more (never through a link)."""
    for rel in rels:
        path = _inside(game_dir, rel)
        if path is None or path.name.lower() in KEEP_THEIRS:
            continue
        if any(safearchive.is_link(p) for p in (path, *path.parents) if p != game_dir and game_dir in p.parents):
            continue
        try:
            if path.is_file():
                path.unlink()
        except OSError as e:
            log.info("couldn't remove the modpack's old %s: %s", rel, e)


def add_to_zip(http, info: dict | None, out: zipfile.ZipFile, say: Callable[[str], None] = print) -> int:
    """Put the pack's own files in a modpack zip made for a launcher to import (its overrides/ folder).
    Names already in ``out`` stay as they are (the server's address in servers.dat, the mods)."""
    if info is None:
        return 0
    say(f"  downloading {info['name']}'s settings and scripts")
    taken, added = set(out.namelist()), 0
    with tempfile.TemporaryDirectory() as tmp:
        z, members = _members(_download(http, info, Path(tmp)), info["kind"], Path(tmp))
        with z:
            for member, parts in members:
                name = "overrides/" + "/".join(parts)
                if name in taken or parts == ("servers.dat",):
                    continue
                with z.open(member) as src, out.open(name, "w") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
                taken.add(name)
                added += 1
    return added
