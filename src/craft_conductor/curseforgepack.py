"""Setting a server up from a CurseForge modpack.

A CurseForge modpack is a zip with a ``manifest.json`` (the Minecraft version, the mod loader and
the CurseForge project and file of every mod) and an overrides folder (configs, scripts...).
Unlike a Modrinth pack, it doesn't say which mods only run on players' computers, and those can
crash a server. When the pack's author publishes an official server pack, its ``mods`` folder
shows which mods the server runs: the pack's other mods are for players, and go in the friends'
download instead (see clientpack.py). Without a server pack, every mod goes on the server and the
person can leave some out on the setup page.

Following CurseForge's terms for third-party apps (see the README): everything comes through the
official API with an API key, files are downloaded from CurseForge's own servers and checked
against CurseForge's checksum, and a file whose author doesn't allow other apps to download it
isn't looked for elsewhere: the person downloads it from CurseForge's page (the manual downloads
panel).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import tempfile
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath

from . import config as configmod, safearchive
from .config import ModSpec
from .http import HttpClient
from .modpack import MAX_INDEX, MAX_PACK, MAX_PACK_FILES, ModpackError, _override_members
from .mods import curseforge as cf
from .mods.base import safe_file_name

log = logging.getLogger(__name__)

MODPACKS_CLASS_ID = 4471
CF_ID = re.compile(r"curseforge:(\d{1,10})")  # a pack's file (setup) or a mod (friends), as Craft Conductor names them
_MINECRAFT = re.compile(r"\d+(\.\d+){1,3}(-[A-Za-z0-9.]+)?")
_FOLDER = re.compile(r"[A-Za-z0-9_. -]{1,64}")
BATCH = 500             # files or mods asked about in one request
CACHE_SECONDS = 3600    # a pack's preview (two downloads) is reused when the server is created
_previews: dict[int, tuple[float, dict]] = {}
_lock = threading.Lock()


def file_id(version: str) -> int:
    m = CF_ID.fullmatch(version or "")
    if not m:
        raise ModpackError("that isn't a CurseForge modpack file")
    return int(m.group(1))


class _Api:
    def __init__(self, http: HttpClient, key: str):
        if not key:
            raise ModpackError("CurseForge modpacks need a CurseForge API key (add one in the mod browser)")
        self.http, self.headers = http, {"x-api-key": key}

    def get(self, path: str, params: dict | None = None):
        return self.http.get_json(f"{cf.API}{path}", params=params, headers=self.headers)["data"]

    def post(self, path: str, body: dict):
        return (self.http.post_json(f"{cf.API}{path}", body, headers=self.headers) or {}).get("data") or []

    def files(self, ids: list[int]) -> dict[int, dict]:
        out = {}
        for i in range(0, len(ids), BATCH):
            for f in self.post("/mods/files", {"fileIds": ids[i:i + BATCH]}):
                if isinstance(f, dict) and isinstance(f.get("id"), int):
                    out[f["id"]] = f
        return out

    def mods(self, ids: list[int]) -> dict[int, dict]:
        out = {}
        for i in range(0, len(ids), BATCH):
            for m in self.post("/mods", {"modIds": ids[i:i + BATCH]}):
                if isinstance(m, dict) and isinstance(m.get("id"), int):
                    out[m["id"]] = m
        return out


def names(http: HttpClient, key: str, items: list[str]) -> dict[str, str]:
    """``curseforge:<id>`` -> the mod's name, as far as CurseForge answers (empty without a key)."""
    ids = sorted({int(x.split(":", 1)[1]) for x in items if CF_ID.fullmatch(x)})
    if not ids or not key:
        return {}
    try:
        return {f"curseforge:{i}": str(m.get("name") or "") for i, m in _Api(http, key).mods(ids).items()}
    except Exception as e:  # (only names: the page shows the ids instead)
        log.debug("couldn't look up CurseForge mod names: %s", e)
        return {}


def _sha1(f: dict) -> str | None:
    return next((h.get("value") for h in f.get("hashes") or [] if h.get("algo") == 1), None)


def _page(mod: dict, file_id: int | None = None) -> str:
    """The project's page on CurseForge (a file's, with ``file_id``): only ever curseforge.com."""
    slug = str(mod.get("slug") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", slug):
        return f"https://www.curseforge.com/projects/{int(mod.get('id') or 0)}"
    return f"{cf.WEBSITE}/{slug}" + (f"/files/{int(file_id)}" if file_id else "")


def _download(api: _Api, mod: dict, f: dict, dest: Path, what: str) -> Path:
    url = f.get("downloadUrl")
    if not url:
        raise ModpackError(f"the author of {mod.get('name', 'this modpack')} doesn't allow other apps to download "
                           f"its {what}. Download it from CurseForge instead: {_page(mod, f.get('id'))}")
    return api.http.download(url, dest, sha1=_sha1(f), max_bytes=MAX_PACK)


def _pack(api: _Api, fid: int) -> tuple[dict, dict]:
    """The modpack (CurseForge project) and the file chosen."""
    f = api.files([fid]).get(fid)
    if not f:
        raise ModpackError("CurseForge has no file with that id")
    mod = api.get(f"/mods/{int(f.get('modId', 0))}")
    if mod.get("classId") != MODPACKS_CLASS_ID:
        raise ModpackError(f"{mod.get('name', 'that project')} isn't a modpack")
    return mod, f


def read_manifest(pack: Path) -> tuple[dict, zipfile.ZipFile]:
    safearchive.check_zip(pack, MAX_PACK_FILES, ModpackError)
    try:
        z = zipfile.ZipFile(pack)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError) as e:
        raise ModpackError("that file isn't a CurseForge modpack, or it's damaged") from e
    try:
        info = z.getinfo("manifest.json")
        if info.file_size > MAX_INDEX:
            raise ModpackError("that modpack's list of files is too big")
        manifest = json.loads(z.read(info).decode("utf-8-sig"))
    except (KeyError, ValueError, zipfile.BadZipFile, EOFError, ModpackError) as e:
        z.close()
        if isinstance(e, ModpackError):
            raise
        raise ModpackError("that file isn't a CurseForge modpack (no manifest.json)") from e
    mc = manifest.get("minecraft") if isinstance(manifest, dict) else None
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(mc, dict) or not isinstance(files, list) or not all(
            isinstance(x, dict) and isinstance(x.get("projectID"), int) and isinstance(x.get("fileID"), int) for x in files):
        z.close()
        raise ModpackError("that modpack's manifest.json is damaged")
    overrides = str(manifest.get("overrides") or "overrides")
    if not _FOLDER.fullmatch(overrides) or overrides.strip(". ") != overrides:
        z.close()
        raise ModpackError("that modpack's manifest.json names an odd overrides folder")
    return manifest, z


def _platform(manifest: dict) -> tuple[str, str]:
    mc = manifest["minecraft"]
    minecraft = str(mc.get("version", ""))
    if not _MINECRAFT.fullmatch(minecraft):
        raise ModpackError("the modpack doesn't say which Minecraft version it's for")
    loaders = [x for x in mc.get("modLoaders") or [] if isinstance(x, dict)]
    loaders.sort(key=lambda x: not x.get("primary"))
    for x in loaders:
        name = str(x.get("id", "")).split("-", 1)[0].lower()
        if name in cf.LOADER_TYPES:
            return minecraft, name
    raise ModpackError("the modpack's mod loader isn't one Craft Conductor runs (Fabric, Quilt, Forge or NeoForge)")


def _server_jars(api: _Api, mod: dict, f: dict, tmp: Path) -> set[str] | None:
    """The mod files in the pack's official server pack, or None when there isn't a usable one."""
    spid = f.get("serverPackFileId")
    if not isinstance(spid, int) or not spid:
        return None
    try:
        sf = api.get(f"/mods/{int(mod['id'])}/files/{spid}")
        if not sf.get("downloadUrl"):
            return None  # (the author doesn't allow it: the pack's own list is used instead)
        path = _download(api, mod, sf, tmp / "server-pack.zip", "server pack")
        safearchive.check_zip(path, MAX_PACK_FILES, ModpackError)
        with zipfile.ZipFile(path) as z:
            return {PurePosixPath(n).name for n in z.namelist()
                    if n.endswith(".jar") and "mods" in PurePosixPath(n).parts[:-1]}
    except Exception as e:  # (only a better guess at what's client-only: never a reason to fail)
        log.info("couldn't read %s's server pack (%s); every mod goes on the server", mod.get("name"), e)
        return None


def preview(http: HttpClient, key: str, version: str) -> dict:
    """What a CurseForge modpack file would add to a new server, without changing one. Cached for
    an hour, so creating the server doesn't download and look everything up again."""
    fid = file_id(version)
    with _lock:
        hit = _previews.get(fid)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
    api = _Api(http, key)
    mod, f = _pack(api, fid)
    with tempfile.TemporaryDirectory() as tmp:
        pack = _download(api, mod, f, Path(tmp) / "pack.zip", "modpack file")
        manifest, z = read_manifest(pack)
        z.close()
        minecraft, loader = _platform(manifest)
        entries = manifest["files"]
        files = api.files([x["fileID"] for x in entries])
        projects = api.mods(sorted({x["projectID"] for x in entries}))
        on_server = _server_jars(api, mod, f, Path(tmp))
    mods, other = [], 0
    for x in entries:
        p, mf = projects.get(x["projectID"]) or {}, files.get(x["fileID"]) or {}
        if p.get("classId", cf.MODS_CLASS_ID) != cf.MODS_CLASS_ID:
            other += 1  # (resource packs and shaders: players' things)
            continue
        name = str(mf.get("fileName") or f"{x['projectID']}-{x['fileID']}.jar")
        if not safe_file_name(name):
            continue
        mods.append({"path": f"mods/{name}", "name": p.get("name") or name, "slug": p.get("slug") or "",
                     "source": "curseforge", "project_id": str(x["projectID"]), "version_id": str(x["fileID"]),
                     "version": mf.get("displayName") or "", "channel": cf.RELEASE_TYPES.get(mf.get("releaseType")),
                     "minecraft": [minecraft], "loaders": [loader], "required": x.get("required", True) is not False,
                     "manual": not mf.get("downloadUrl") or p.get("allowModDistribution") is False, "url": _page(p)})
    if on_server is not None:
        found = sum(1 for m in mods if PurePosixPath(m["path"]).name in on_server)
        if found < max(1, len(mods) // 2):  # (a server pack of other versions says nothing about these)
            log.info("%s's server pack doesn't match the pack's mods; every mod goes on the server", mod.get("name"))
            on_server = None
    for m in mods:
        m["included_on_server"] = on_server is None or PurePosixPath(m["path"]).name in on_server
        m["for_friends"] = not m["included_on_server"]
    out = {"source": "curseforge", "name": f"{mod.get('name', 'Modpack')} {f.get('displayName') or ''}".strip(),
           "minecraft": minecraft, "loader": loader, "mods": mods, "server_pack": on_server is not None,
           "count": sum(1 for m in mods if m["included_on_server"]),
           "client_only": sum(1 for m in mods if not m["included_on_server"]), "other": other,
           "overrides": str(manifest.get("overrides") or "overrides")}
    with _lock:
        if len(_previews) >= 8:
            _previews.clear()
        _previews[fid] = (time.monotonic(), out)
    return out


def apply(root: Path, version: str, http: HttpClient, key: str, exclude: tuple[str, ...] | list[str] = ()) -> dict:
    """Install a CurseForge modpack file into the server at ``root`` (whose craft-conductor.toml
    exists): its loader and Minecraft, its server mods as CurseForge mods Craft Conductor keeps
    up to date, and its overrides. Its mods for players are the setup page's to add to the friends'
    download (they come back in ``friends``). ``exclude``: ``mods/*.jar`` paths removed on the
    setup page."""
    info = preview(http, key, version)
    api = _Api(http, key)
    mod, f = _pack(api, file_id(version))
    with tempfile.TemporaryDirectory() as tmp:
        pack = _download(api, mod, f, Path(tmp) / "pack.zip", "modpack file")
        manifest, z = read_manifest(pack)
        with z:
            minecraft, loader = _platform(manifest)
            what = f"the modpack {safearchive.printable(info['name'])}"
            prefix = str(manifest.get("overrides") or "overrides") + "/"
            # Every check that can refuse the pack happens before the server's settings change.
            overrides = _override_members(z, configmod.load(root).server.dir, what, (prefix,))
            cfg_path = root / configmod.CONFIG_NAME
            configmod.set_value(cfg_path, "server", "loader", json.dumps(loader))
            configmod.set_value(cfg_path, "server", "minecraft", json.dumps(minecraft))
            configmod.set_value(cfg_path, "updates", "strategy", '"mods-only"')
            cfg = configmod.load(root)
            server_dir = cfg.server.dir
            server_dir.mkdir(parents=True, exist_ok=True)
            listed = {(s.source, s.id) for s in cfg.mods}
            excluded = set(exclude)
            added, friends, removed = [], [], 0
            for m in info["mods"]:
                if not m["included_on_server"]:
                    friends.append(f"curseforge:{m['project_id']}")
                elif m["path"] in excluded:
                    removed += 1
                elif ("curseforge", m["project_id"]) not in listed:
                    configmod.append_mod(cfg_path, ModSpec("curseforge", m["project_id"], required=m["required"]))
                    listed.add(("curseforge", m["project_id"]))
                    added.append(m["project_id"])
            copied = 0
            blocked = safearchive.Skipped(what)
            for member, parts in overrides:
                try:
                    with safearchive.open_new(server_dir, parts) as out, z.open(member) as src:
                        shutil.copyfileobj(src, out, 1 << 20)
                except safearchive.UnsafeName as e:
                    blocked.add(member.filename, str(e))
                    continue
                copied += 1
            blocked.log()
    log.info("applied %s: Minecraft %s, %s, %d mods from CurseForge, %d for players, %d config files",
             info["name"], minecraft, loader, len(added), len(friends), copied)
    return {"name": info["name"], "minecraft": minecraft, "loader": loader, "mods": len(added), "files": 0,
            "overrides": copied, "client_only": len(friends), "removed": removed, "friends": friends}
