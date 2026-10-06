"""Setting a server up from a Modrinth modpack (.mrpack).

A modpack fixes the Minecraft version and mod loader and lists its mods. craft-conductor reads
the pack's ``modrinth.index.json`` and:

* sets the server's loader and Minecraft version, and keeps it on that version
  (strategy "mods-only": the pack's mods are made to work together on it);
* adds every mod hosted on Modrinth as a normal craft-conductor mod (kept up to date);
* downloads other files the server needs (checked against their hashes);
* copies the pack's ``overrides/`` and ``server-overrides/`` (configs, scripts...)
  into the server folder.

Files marked client-only (``env.server == "unsupported"``) are skipped.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from . import config as configmod, safearchive
from .config import ModSpec
from .http import HttpClient, HttpError
from .mods.base import ModError
from .mods.modrinth import API as MODRINTH

log = logging.getLogger(__name__)

LOADER_KEYS = {"fabric-loader": "fabric", "quilt-loader": "quilt", "neoforge": "neoforge", "forge": "forge"}
MODRINTH_FILE = re.compile(r"^https://cdn\.modrinth\.com/data/([A-Za-z0-9]{8})/versions/([A-Za-z0-9]{8})/[^/]+$")
DOWNLOAD_HOSTS = ("https://cdn.modrinth.com/", "https://github.com/", "https://raw.githubusercontent.com/",
                  "https://gitlab.com/")
MAX_PACK = 512 << 20
MAX_UNPACKED_PACK = 2 << 30   # the pack's own files (configs, scripts, resource packs), unpacked
MAX_PACK_FILES = 50_000
MAX_INDEX = 16 << 20          # modrinth.index.json
OVERRIDES = ("overrides/", "server-overrides/")  # in this order: the server's own overrides win


class ModpackError(ModError):
    pass


def _safe_target(base: Path, relative: str) -> Path:
    """``base / relative`` if it stays inside ``base``; raises safearchive.UnsafeName."""
    target = base.joinpath(*safearchive.parts(relative))
    try:
        target.resolve().relative_to(base.resolve())
    except ValueError:
        raise safearchive.UnsafeName("it would be written through a link to outside the server folder") from None
    return target


def version_info(http: HttpClient, version_id: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9]{8}", version_id or ""):
        raise ModpackError("that isn't a Modrinth modpack version")
    v = http.get_json(f"{MODRINTH}/version/{version_id}")
    files = [f for f in v.get("files", []) if f.get("filename", "").endswith(".mrpack")]
    if not files:
        raise ModpackError(f"{v.get('name', 'that version')} has no .mrpack file")
    f = next((x for x in files if x.get("primary")), files[0])
    return {"id": v["id"], "project_id": v["project_id"], "name": v.get("name") or v.get("version_number", ""),
            "url": f["url"], "sha1": f.get("hashes", {}).get("sha1"), "sha512": f.get("hashes", {}).get("sha512"),
            "minecraft": v.get("game_versions", []), "loaders": v.get("loaders", [])}


def read_index(pack: Path) -> tuple[dict, zipfile.ZipFile]:
    safearchive.check_zip(pack, MAX_PACK_FILES, ModpackError)
    try:
        z = zipfile.ZipFile(pack)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError) as e:
        raise ModpackError("that file isn't a Modrinth modpack (.mrpack), or it's damaged") from e
    try:
        info = z.getinfo("modrinth.index.json")
        if info.file_size > MAX_INDEX:
            raise ModpackError("that modpack's list of files is too big")
        index = json.loads(z.read(info))
    except (KeyError, ValueError, zipfile.BadZipFile, EOFError) as e:
        z.close()
        if isinstance(e, ModpackError):
            raise
        raise ModpackError("that file isn't a Modrinth modpack (no modrinth.index.json)") from e
    files, deps = index.get("files", []) if isinstance(index, dict) else None, \
        index.get("dependencies", {}) if isinstance(index, dict) else None
    if not isinstance(files, list) or not all(isinstance(f, dict) for f in files) or not isinstance(deps, dict):
        z.close()
        raise ModpackError("that modpack's modrinth.index.json is damaged")
    if index.get("game") != "minecraft":
        z.close()
        raise ModpackError("that modpack isn't for Minecraft: Java Edition")
    return index, z


def _platform(index: dict) -> tuple[str, str]:
    """Minecraft and loader declared by a Modrinth pack index."""
    deps = index.get("dependencies", {})
    minecraft = str(deps.get("minecraft", ""))
    loaders = [LOADER_KEYS[k] for k in deps if k in LOADER_KEYS]
    return minecraft, loaders[0] if loaders else "vanilla"


def preview_file(pack: Path, http: HttpClient, name: str = "") -> dict:
    """Describe the server-side mods a .mrpack would add, without changing a server.

    Paths are the stable identifiers used by the setup UI when a person removes one pack
    mod. Project/version lookups only enrich the display; a failed metadata lookup does not
    make an otherwise valid pack impossible to inspect.
    """
    index, z = read_index(pack)
    with z:
        minecraft, loader = _platform(index)
        raw = []
        project_ids, version_ids = [], []
        client_only = 0
        for f in index.get("files", []):
            path = str(f.get("path", ""))
            if not path.startswith("mods/") or not path.endswith(".jar"):
                continue
            env = f.get("env") or {}
            included_on_server = env.get("server") != "unsupported"
            if not included_on_server:
                client_only += 1
            urls = [u for u in f.get("downloads", []) if isinstance(u, str)]
            match = next((MODRINTH_FILE.match(u) for u in urls if MODRINTH_FILE.match(u)), None)
            pid = match.group(1) if match else None
            vid = match.group(2) if match else None
            if pid:
                project_ids.append(pid)
            if vid:
                version_ids.append(vid)
            raw.append({
                "path": path,
                "name": Path(path).stem,
                "source": "modrinth" if pid else "modpack",
                "project_id": pid,
                "version_id": vid,
                "version": "",
                "channel": None,
                "minecraft": [minecraft] if minecraft else [],
                "loaders": [loader] if loader else [],
                "server_side": env.get("server", "required"),
                "client_side": env.get("client", "required"),
                "included_on_server": included_on_server,
            })

        projects = {}
        versions = {}
        try:
            from .mods.modrinth import ModrinthProvider
            projects = ModrinthProvider(http).projects(project_ids)
        except (HttpError, ModError):
            pass
        try:
            if version_ids:
                data = http.get_json(f"{MODRINTH}/versions", params={"ids": json.dumps(sorted(set(version_ids)))})
                versions = {v.get("id"): v for v in data if isinstance(v, dict) and v.get("id")}
        except HttpError:
            pass

        for m in raw:
            p = projects.get(m["project_id"]) or {}
            v = versions.get(m["version_id"]) or {}
            m["name"] = p.get("title") or m["name"]
            m["slug"] = p.get("slug") or ""
            m["version"] = v.get("version_number") or ""
            m["channel"] = v.get("version_type") or None
            m["minecraft"] = list(v.get("game_versions") or m["minecraft"])
            m["loaders"] = list(v.get("loaders") or m["loaders"])

    return {
        "name": name or str(index.get("name") or pack.name),
        "minecraft": minecraft,
        "loader": loader,
        "mods": raw,
        "count": sum(1 for m in raw if m["included_on_server"]),
        "client_only": client_only,
    }


def preview(http: HttpClient, version_id: str) -> dict:
    """Download a Modrinth pack version and return its mod-management preview."""
    info = version_info(http, version_id)
    with tempfile.TemporaryDirectory() as tmp:
        pack = http.download(info["url"], Path(tmp) / "pack.mrpack", sha1=info["sha1"], sha512=info["sha512"])
        if pack.stat().st_size > MAX_PACK:
            raise ModpackError("that modpack is too big")
        return preview_file(pack, http, name=info["name"])


def _override_members(z: zipfile.ZipFile, server_dir: Path, what: str) -> list[tuple[zipfile.ZipInfo, tuple[str, ...]]]:
    """The pack's own files to copy (overrides/, then server-overrides/), checked before anything
    is written: names that could land outside the server folder are left out (and logged), and
    a pack that unpacks to too much, or more than the disk has room for, is refused."""
    infos = z.infolist()
    if len(infos) > MAX_PACK_FILES:  # (the end record understated it)
        raise ModpackError(f"that modpack holds too many files ({len(infos):,}; at most {MAX_PACK_FILES:,})")
    skipped = safearchive.Skipped(what)
    out = []
    for prefix in OVERRIDES:
        for member in infos:
            if member.filename.startswith(prefix) and not member.is_dir():
                try:
                    out.append((member, safearchive.parts(member.filename[len(prefix):])))
                except safearchive.UnsafeName as e:
                    skipped.add(member.filename, str(e))
    skipped.log()
    total = sum(m.file_size for m, _ in out)
    if total > MAX_UNPACKED_PACK:
        log.warning("refused %s: its files unpack to %s (at most %s)", what, safearchive.size_words(total),
                    safearchive.size_words(MAX_UNPACKED_PACK))
        raise ModpackError(f"that modpack is too big: its files unpack to {safearchive.size_words(total)}")
    safearchive.ensure_space(server_dir, total, ModpackError, "that modpack")
    return out


def apply(root: Path, version_id: str, http: HttpClient, exclude: tuple[str, ...] | list[str] = ()) -> dict:
    """Install a modpack version into the server at ``root`` (whose craft-conductor.toml exists).

    ``exclude`` contains exact ``mods/*.jar`` paths the user removed in the setup UI.
    """
    info = version_info(http, version_id)
    with tempfile.TemporaryDirectory() as tmp:
        pack = http.download(info["url"], Path(tmp) / "pack.mrpack", sha1=info["sha1"], sha512=info["sha512"])
        if pack.stat().st_size > MAX_PACK:
            raise ModpackError("that modpack is too big")
        return apply_file(root, pack, http, name=info["name"], exclude=exclude)


def apply_file(root: Path, pack: Path, http: HttpClient, name: str = "", exclude: tuple[str, ...] | list[str] = ()) -> dict:
    index, z = read_index(pack)
    with z:
        deps = index.get("dependencies", {})
        minecraft = str(deps.get("minecraft", ""))
        if not re.fullmatch(r"\d+(\.\d+){1,3}(-[A-Za-z0-9.]+)?", minecraft):
            raise ModpackError("the modpack doesn't say which Minecraft version it's for")
        loaders = [LOADER_KEYS[k] for k in deps if k in LOADER_KEYS]
        loader = loaders[0] if loaders else "vanilla"
        what = f"the modpack {safearchive.printable(name or str(index.get('name') or pack.name))}"
        # Every check that can refuse the pack happens before the server's settings change.
        overrides = _override_members(z, configmod.load(root).server.dir, what)
        cfg_path = root / configmod.CONFIG_NAME
        configmod.set_value(cfg_path, "server", "loader", json.dumps(loader))
        configmod.set_value(cfg_path, "server", "minecraft", json.dumps(minecraft))
        configmod.set_value(cfg_path, "updates", "strategy", '"mods-only"')
        cfg = configmod.load(root)
        server_dir = cfg.server.dir
        server_dir.mkdir(parents=True, exist_ok=True)
        listed = {s.id for s in cfg.mods}

        added, local, skipped, removed = [], [], 0, 0
        excluded = set(exclude)
        unsafe = safearchive.Skipped(f"the downloads listed by {what}")
        for f in index.get("files", []):
            if (f.get("env") or {}).get("server") == "unsupported":
                skipped += 1
                continue
            path = str(f.get("path", ""))
            if path in excluded and path.startswith("mods/") and path.endswith(".jar"):
                removed += 1
                continue
            try:
                target = _safe_target(server_dir, path)
            except safearchive.UnsafeName as e:
                unsafe.add(path, str(e))
                continue
            urls = [u for u in f.get("downloads", []) if isinstance(u, str)]
            m = next((MODRINTH_FILE.match(u) for u in urls if MODRINTH_FILE.match(u)), None)
            if m and path.startswith("mods/") and path.endswith(".jar"):
                pid = m.group(1)
                if pid not in listed:
                    configmod.append_mod(cfg_path, ModSpec("modrinth", pid, required=True))
                    listed.add(pid)
                    added.append(pid)
                continue
            url = next((u for u in urls if u.startswith(DOWNLOAD_HOSTS)), None)
            hashes = f.get("hashes") or {}
            if not url or not (hashes.get("sha1") or hashes.get("sha512")):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            http.download(url, target, sha1=hashes.get("sha1"), sha512=hashes.get("sha512"))
            local.append(path)

        unsafe.log()
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
    title = name or index.get("name", "modpack")
    log.info("applied %s: Minecraft %s, %s, %d mods from Modrinth, %d other files, %d config files",
             title, minecraft, loader, len(added), len(local), copied)
    return {"name": title, "minecraft": minecraft, "loader": loader, "mods": len(added), "files": len(local),
            "overrides": copied, "client_only": skipped, "removed": removed}
