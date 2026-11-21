"""Make a modpack from a server's mods: a Modrinth ``.mrpack`` or a CurseForge ``.zip``, chosen when
it's made (the Mods page's Make a modpack…).

A made pack holds no mod files and no config files (some mods keep passwords or tokens in theirs):
only the mod sites' own links, the way each format allows. A ``.mrpack`` lists each file's Modrinth
download (its hashes and size from Modrinth itself) with the sides it runs on; a CurseForge pack
lists project and file ids. A mod that can't go in the chosen format is named, with why, on the page
and in the pack (a ``.mrpack``'s summary, a CurseForge pack's ``modlist.html``), never left out
silently.
"""

from __future__ import annotations

import html
import io
import json
import logging
import re
import threading
import time
import zipfile

from .mods.modrinth import API as MODRINTH_API

log = logging.getLogger(__name__)

FORMATS = ("mrpack", "curseforge")
MOD_LOADERS = {"fabric": "fabric-loader", "quilt": "quilt-loader", "forge": "forge", "neoforge": "neoforge"}
MODRINTH_CDN = "https://cdn.modrinth.com/"
CACHE_SECONDS = 300   # the dialog's look, then its download: the mod sites are asked once

ONLY_CURSEFORGE = "only on CurseForge: a Modrinth pack can't link to it"
ONLY_MODRINTH = "only on Modrinth: a CurseForge pack can't link to it"
BY_HAND = "added by hand: not on a mod site"
DATAPACK = "a datapack for the world, not a mod"
GONE = "Modrinth no longer has this file"
CURSEFORGE_PAGE = "its author only lets people download it from CurseForge's page"

_cache: dict[tuple, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def _loader(m) -> str:
    """The server type as installed (as the config says before it is)."""
    return m.lock.loader or m.config.server.loader


def _check(m, fmt: str) -> None:
    if fmt not in FORMATS:
        raise ValueError("choose Modrinth (.mrpack) or CurseForge (.zip)")
    if _loader(m) not in MOD_LOADERS:
        raise ValueError("a modpack is made from a server that runs mods (Fabric, Quilt, Forge or NeoForge)")
    if not m.lock.installed or not m.lock.minecraft:
        raise ValueError("the server isn't installed yet")


def _server_name(m) -> str:
    from .properties import read_properties, server_name
    return server_name(read_properties(m.server_dir / "server.properties"), m.config.root.name)


def _file_name(name: str, fmt: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" ._") or "modpack"
    return f"{safe[:60]}-{time.strftime('%Y-%m-%d')}" + (".mrpack" if fmt == "mrpack" else ".zip")


def _mods(m) -> dict:
    """What goes in, whatever the format: each mod with where it runs ("server", "client", "both"),
    and what's left out of any pack (datapacks, files added by hand)."""
    from .clientpack import players_mods
    lk = m.lock
    on_server = [x for x in lk.mods if not x.datapack]
    players = players_mods(m, on_server, lk.minecraft, lk.loader_version, lk.java_major)
    for_players = {e.get("project"): e for e in players["mods"]}
    mods, left_out = [], []
    for x in on_server:
        mods.append({"name": x.name, "source": x.source, "project_id": x.project_id, "version_id": x.version_id,
                     "filename": x.filename, "required": x.required,
                     "side": "both" if x.key in for_players else "server"})
    keys = {x.key for x in on_server}
    for e in players["mods"]:
        if e.get("project") in keys:
            continue
        if e.get("local") or str(e.get("project", "")).startswith("local:"):
            left_out.append({"name": e.get("filename") or e.get("name", ""), "why": BY_HAND})
            continue
        mods.append({"name": e.get("name", ""), "source": e.get("source", ""),
                     "project_id": str(e.get("project", "")).partition(":")[2], "version_id": e.get("version_id", ""),
                     "filename": e.get("filename", ""), "required": True, "side": "client"})
    names = {x.filename for x in lk.mods}
    for x in players["manual"]:  # (players' mods whose authors allow only CurseForge's page: no ids kept)
        if x.get("filename") not in names:
            left_out.append({"name": x.get("name", ""), "why": CURSEFORGE_PAGE})
    left_out += [{"name": x.name, "why": DATAPACK} for x in lk.mods if x.datapack]
    left_out += [{"name": name, "why": BY_HAND} for name in m.unmanaged_jars()]
    return {"mods": mods, "left_out": left_out}


def _modrinth_files(m, version_ids: list[str]) -> dict[str, list[dict]]:
    """Modrinth's own files of these builds (hashes and sizes), in one request."""
    if not version_ids:
        return {}
    data = m.http.get_json(f"{MODRINTH_API}/versions", params={"ids": json.dumps(sorted(set(version_ids)))})
    return {str(v.get("id")): v.get("files") or [] for v in data if isinstance(v, dict)}


def _env(mod: dict) -> dict:
    server = "unsupported" if mod["side"] == "client" else "required" if mod["required"] else "optional"
    client = "unsupported" if mod["side"] == "server" else "required"
    return {"client": client, "server": server}


def _plan(m, fmt: str) -> dict:
    found = _mods(m)
    left_out = list(found["left_out"])
    entries = []
    if fmt == "mrpack":
        modrinth = [x for x in found["mods"] if x["source"] == "modrinth"]
        files = _modrinth_files(m, [x["version_id"] for x in modrinth])
        for x in found["mods"]:
            if x["source"] != "modrinth":
                left_out.append({"name": x["name"], "why": ONLY_CURSEFORGE})
                continue
            listed = files.get(x["version_id"]) or []
            f = next((f for f in listed if f.get("filename") == x["filename"]), None) or next(
                (f for f in listed if f.get("primary")), None)
            hashes = (f or {}).get("hashes") or {}
            url = str((f or {}).get("url") or "")
            if not (url.startswith(MODRINTH_CDN) and hashes.get("sha1") and hashes.get("sha512")
                    and isinstance(f.get("size"), int)):
                left_out.append({"name": x["name"], "why": GONE})
                continue
            name = str(f.get("filename") or x["filename"])
            if "/" in name or "\\" in name or name.startswith("."):
                left_out.append({"name": x["name"], "why": GONE})
                continue
            entries.append({"name": x["name"], "side": x["side"], "file": {
                "path": f"mods/{name}", "hashes": {"sha1": hashes["sha1"], "sha512": hashes["sha512"]},
                "env": _env(x), "downloads": [url], "fileSize": f["size"]}})
    else:
        for x in found["mods"]:
            if x["source"] != "curseforge":
                left_out.append({"name": x["name"], "why": ONLY_MODRINTH})
                continue
            try:
                ids = {"projectID": int(x["project_id"]), "fileID": int(x["version_id"])}
            except (TypeError, ValueError):
                left_out.append({"name": x["name"], "why": GONE})
                continue
            entries.append({"name": x["name"], "side": x["side"], "file": {**ids, "required": True}})
    return {"entries": entries, "left_out": left_out}


def _planned(m, fmt: str) -> dict:
    lk = m.lock
    key = (str(m.config.root), fmt, lk.minecraft, lk.loader_version, tuple((x.key, x.version_id) for x in lk.mods),
           tuple(m.config.client.mods), tuple(m.unmanaged_jars()))
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    plan = _plan(m, fmt)
    with _cache_lock:
        for k in [k for k, (when, _) in _cache.items() if now - when >= CACHE_SECONDS]:
            del _cache[k]
        _cache[key] = (now, plan)
    return plan


def contents(m, fmt: str) -> dict:
    """What a pack in this format would hold: {"name", "filename", "included": [{"name", "side"}],
    "left_out": [{"name", "why"}]}."""
    _check(m, fmt)
    plan = _planned(m, fmt)
    name = _server_name(m)
    return {"name": name, "filename": _file_name(name, fmt),
            "included": [{"name": e["name"], "side": e["side"]} for e in plan["entries"]],
            "left_out": list(plan["left_out"])}


def build(m, fmt: str) -> tuple[str, bytes]:
    """The pack's file name and its bytes."""
    _check(m, fmt)
    plan = _planned(m, fmt)
    lk = m.lock
    name = _server_name(m)
    version = time.strftime("%Y-%m-%d")
    missing = ", ".join(x["name"] for x in plan["left_out"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if fmt == "mrpack":
            summary = f"The mods of {name}, made by Craft Conductor."
            if missing:
                summary += f" Not included: {missing}."
            index = {"formatVersion": 1, "game": "minecraft", "versionId": version, "name": name, "summary": summary,
                     "files": [e["file"] for e in plan["entries"]],
                     "dependencies": {"minecraft": lk.minecraft, MOD_LOADERS[_loader(m)]: lk.loader_version or ""}}
            z.writestr("modrinth.index.json", json.dumps(index, indent=1))
        else:
            manifest = {"minecraft": {"version": lk.minecraft,
                                      "modLoaders": [{"id": f"{_loader(m)}-{lk.loader_version or ''}", "primary": True}]},
                        "manifestType": "minecraftModpack", "manifestVersion": 1, "name": name, "version": version,
                        "author": "Craft Conductor", "files": [e["file"] for e in plan["entries"]], "overrides": "overrides"}
            z.writestr("manifest.json", json.dumps(manifest, indent=1))
            rows = "".join(f"<li>{html.escape(e['name'])}</li>" for e in plan["entries"])
            gone = "".join(f"<li>{html.escape(x['name'])}: {html.escape(x['why'])}</li>" for x in plan["left_out"])
            z.writestr("modlist.html", f"<ul>{rows}</ul>" + (f"<h2>Not included</h2><ul>{gone}</ul>" if gone else ""))
    return _file_name(name, fmt), buf.getvalue()
