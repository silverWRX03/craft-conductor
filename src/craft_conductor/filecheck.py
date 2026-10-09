"""Will these mods start? The loaders' own check (modcheck.py) on the files a server, or its
players, would get, before anything is installed or any invite is sent.

What's checked is a list of "entries", the same as the players' download lists them
(clientpack.py): a name, the mod's key ("modrinth:<id>"), its file (``path`` when it's on this
computer, else its download address and hash) and its ``side``: "server", "client" or "both".
Files that aren't here are downloaded once into the shared store (modfiles.py), where installing
the server finds them later.

For each problem it can also look for a fix: other builds of the mod that complains, and of the
mod it needs, made for this Minecraft version, that make the problem go away without bringing
another one ("Use Iris 1.10.9").
"""

from __future__ import annotations

import copy
import logging
import threading
from pathlib import Path

from . import modcheck
from .config import ModSpec, Pin
from .http import HashMismatch, HttpError
from .mods.base import CHANNEL_RANK, ModError, Unavailable

log = logging.getLogger(__name__)

TRIES = 8         # builds tried for each mod when looking for a fix
FIXES = 2         # fixes offered for one problem at most


def store_for(m):
    """The manager's shared store of mod files, or (one server on its own) one of its own."""
    from .modfiles import Store
    return m.mod_files if getattr(m, "mod_files", None) is not None else Store(m.config.state_dir / "mod-files", m.http)


def infos_of(entry: dict, loader: str, store) -> list[modcheck.ModInfo] | None:
    """The mods inside one entry's file; None when it can't be read (not here, and can't be
    downloaded: a mod to download by hand, a site that didn't answer)."""
    path = entry.get("path")
    try:
        if path:
            return modcheck.read_file(Path(path), loader)
        if store is None:
            return None
        return modcheck.read_file(store.get(entry.get("url", ""), entry.get("sha1"), entry.get("sha512")), loader)
    except (OSError, ValueError, HttpError, HashMismatch) as e:
        log.info("couldn't look into %s to check it: %s", entry.get("name"), e)
        return None


class Files:
    """The entries being checked and what's in each one's file."""

    def __init__(self, entries: list[dict], loader: str, store, progress=None):
        self.loader = loader
        self.store = store
        self.entries = list(entries)
        self.infos: dict[int, list[modcheck.ModInfo] | None] = {}
        for n, e in enumerate(self.entries):
            if progress:
                progress(n, len(self.entries), e.get("name", ""))
            self.infos[id(e)] = infos_of(e, loader, store)

    def on(self, side: str) -> list[dict]:
        return [e for e in self.entries if e.get("side", "both") in ("both", side)]

    def problems(self, side: str, **where) -> list[modcheck.Problem]:
        mods, complete = [], True
        for e in self.on(side):
            found = self.infos.get(id(e))
            if found is None:
                complete = False
            else:
                mods += found
        return modcheck.check(mods, loader=self.loader, side=side, complete=complete, **where)

    def entry_of(self, problem: modcheck.Problem) -> dict | None:
        """The entry whose file has the mod that complains (itself, or bundled in it)."""
        for e in self.entries:
            if any(info.id == problem.mod_id for info in self.infos.get(id(e)) or ()):
                return e
        return None

    def giver_of(self, mod_id: str, side: str) -> dict | None:
        """The entry whose file has (or provides) ``mod_id``."""
        for e in self.on(side):
            for info in self.infos.get(id(e)) or ():
                if mod_id == info.id or mod_id in info.provides:
                    return e
        return None

    def swapped(self, old: dict, new: dict, infos) -> "Files":
        other = copy.copy(self)
        other.entries = [new if e is old else e for e in self.entries]
        other.infos = {**self.infos, id(new): infos}
        return other


def _plain(problem: modcheck.Problem, side: str, files: Files) -> dict:
    who, giver = files.entry_of(problem), files.giver_of(problem.needs, side)
    return {"side": side, "kind": problem.kind, "mod": problem.mod, "needs": problem.needs, "text": problem.text,
            "key": (who or {}).get("project"), "needs_key": (giver or {}).get("project"), "fixes": []}


def check(entries: list[dict], *, loader: str, minecraft: str, loader_version: str | None, java_major: int | None,
          store, providers: dict | None = None, mod_loaders: tuple[str, ...] = (), channel: str = "release",
          sides: tuple[str, ...] = ("server", "client"), fixes: bool = True, progress=None) -> dict:
    """Problems with ``entries`` on each side, each with the fixes found (when ``fixes`` and
    ``providers``): {"ok", "problems": [...], "unreadable": [names]}."""
    if loader not in modcheck.LOADERS:
        return {"ok": True, "problems": [], "unreadable": []}
    where = dict(minecraft=minecraft, loader_version=loader_version, java_major=java_major)
    files = Files(entries, loader, store, progress)
    out = []
    for side in sides:
        for p in files.problems(side, **where):
            item = _plain(p, side, files)
            if not any(x["side"] != side and x["text"] == item["text"] for x in out):  # (once, for both sides)
                out.append(item)
                if fixes and providers:
                    item["fixes"] = _fixes(p, side, files, providers, mod_loaders or (loader,), minecraft, channel, where)
    unreadable = [e.get("name", "") for e in files.entries if files.infos.get(id(e)) is None]
    return {"ok": not out, "problems": out, "unreadable": unreadable}


def _fixes(problem: modcheck.Problem, side: str, files: Files, providers: dict, mod_loaders: tuple[str, ...],
           minecraft: str, channel: str, where: dict) -> list[dict]:
    """Other builds, of the mod that complains and of the one it needs, that make this problem go
    away and bring none of their own."""
    before = {(p.kind, p.mod_id, p.needs) for p in files.problems(side, **where)}
    target = (problem.kind, problem.mod_id, problem.needs)
    out = []
    for entry in (files.entry_of(problem), files.giver_of(problem.needs, side)):
        if entry is None or len(out) >= FIXES:
            continue
        source, _, project_id = str(entry.get("project", "")).partition(":")
        provider = providers.get(source)
        if provider is None or not project_id:
            continue
        # (builds as stable as the server takes, or as this mod's own build already is)
        allowed = max(CHANNEL_RANK.get(channel, 0), CHANNEL_RANK.get(entry.get("channel") or "release", 0))
        try:
            project = provider.project(project_id)
            builds = [b for b in provider.versions(project, mod_loaders)
                      if minecraft in b["minecraft"] and b["id"] != entry.get("version_id")
                      and CHANNEL_RANK.get(b["channel"], 9) <= allowed]
        except (ModError, HttpError) as e:
            log.info("couldn't list the builds of %s: %s", entry.get("name"), e)
            continue
        held = copy.copy(provider)
        for build in builds[:TRIES]:
            held.pins = {project.key: Pin(build["id"], minecraft)}
            try:
                f = held.resolve(ModSpec(source, project.id), minecraft, mod_loaders, "alpha",
                                 **({"side": "client" if side == "client" else "server"} if source == "modrinth" else {}))
            except (Unavailable, ModError, HttpError):
                continue
            new = {**entry, "url": f.url, "sha1": f.sha1, "sha512": f.sha512, "filename": f.filename,
                   "version": f.version_number, "version_id": f.version_id, "path": None}
            if f.manual or not f.url:
                continue
            infos = infos_of(new, files.loader, files.store)
            if infos is None:
                continue
            after = {(p.kind, p.mod_id, p.needs) for p in files.swapped(entry, new, infos).problems(side, **where)}
            if target not in after and after <= before:
                out.append({"key": entry.get("project"), "name": entry.get("name"), "version_id": f.version_id,
                            "version": f.version_number, "channel": f.channel, "text": f"Use {entry.get('name')} {f.version_number}"})
                break
    return out


def for_server(m, fixes: bool = True, progress=None, client_mods: list[str] | None = None) -> dict:
    """The check of what this server's next update installs (its held versions included), on
    the server and on players' computers: what Manage Mods and Manage Friends Mods show."""
    from .clientpack import _entry, players_mods
    lk, cfg = m.lock, m.config
    loader = m.loader.name
    minecraft = lk.minecraft or cfg.server.minecraft
    if loader not in modcheck.LOADERS or not minecraft:
        return {"ok": True, "problems": [], "unreadable": []}
    if minecraft == "latest":  # (a server not made yet: the newest its loader runs, as setting it up picks)
        from .planner import newest_release
        minecraft = newest_release(m.mojang, m.loader)
    plan = m.planner().plan_for(minecraft)
    loader_version = plan.loader_version or lk.loader_version
    java_major = lk.java_major
    if java_major is None:
        try:
            java_major = m.mojang.info(minecraft).java_major
        except Exception:
            java_major = None
    players = players_mods(m, plan.mods, minecraft, loader_version, java_major, client_mods)
    entries = list(players["mods"])
    there = {e.get("project") for e in entries}
    for x in plan.mods:
        if not x.datapack and x.key not in there:
            local = m._local_copy(x)
            entries.append(_entry(x, "server", str(local) if local else None))
    for name in m.unmanaged_jars():  # (your own files in the server's mods folder)
        entries.append({"name": name, "filename": name, "project": f"local:{name}", "side": "server",
                        "path": str(m.mods_dir / name)})
    result = check(entries, loader=loader, minecraft=minecraft, loader_version=loader_version, java_major=java_major,
                   store=store_for(m), providers=m.providers, mod_loaders=m.loader.mod_loaders,
                   channel=cfg.updates.mod_channel, fixes=fixes, progress=progress)
    result["minecraft"] = minecraft
    return result


# ------------------------------------------------------------------ the setup page
PACKS_DIR = "setup-packs"   # in the hub's state folder: modpacks unpacked once for the setup page's check
PACK_DAYS = 2


def for_setup(hub, spec, progress=None) -> dict:
    """The check of a server that isn't made yet, from the setup page's choices (setup.SetupSpec):
    its settings are written into a folder of their own, exactly as Create my server will, and
    checked like a server's next update. The files downloaded for it are kept (modfiles.py), so
    creating the server doesn't download them again."""
    import shutil
    import tempfile
    from . import config as configmod, setup as setupmod
    from .manager import Manager
    if spec.loader not in modcheck.LOADERS:
        return {"ok": True, "problems": [], "unreadable": []}
    pack_specs, pack_jars, pack_client = _pack_part(hub, spec)
    hub.state_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=hub.state_dir, prefix="setup-check-") as tmp:
        root = Path(tmp)
        setupmod.configure(root, spec)
        path = root / configmod.CONFIG_NAME
        for x in pack_specs:
            configmod.append_mod(path, x)
        if pack_client:
            import json
            configmod.set_value(path, "client", "mods", json.dumps(list(dict.fromkeys(spec.client_mods + pack_client))))
        cfg = configmod.load(root)
        folder = cfg.server.dir / "mods"
        folder.mkdir(parents=True, exist_ok=True)
        for jar in pack_jars:  # (a pack's own files that aren't on a mod site)
            shutil.copy2(jar, folder / jar.name)
        m = Manager(cfg, http=hub.http, echo=False)
        cf = m.providers.get("curseforge")
        if cf is not None and not getattr(cf, "api_key", ""):
            cf.api_key = hub.curseforge_key() or ""
        m.mod_files = hub.mod_files
        return for_server(m, progress=progress, client_mods=cfg.client.mods)


def setup_fingerprint(spec) -> str:
    """What the setup page's check is about, so Create my server knows whether it was checked."""
    import hashlib
    import json
    data = [spec.loader, spec.minecraft, sorted(spec.mods), sorted(spec.optional_mods), sorted(spec.mod_channels.items()),
            sorted(spec.datapacks), sorted(spec.client_mods), spec.modpack_version, sorted(spec.modpack_exclude),
            sorted((k, v.version) for k, v in spec.pins.items())]
    return hashlib.sha256(json.dumps(data).encode()).hexdigest()


def _pack_part(hub, spec) -> tuple[list, list[Path], list[str]]:
    """A modpack's own part of the setup: its mods (as setting it up lists them), its files that
    aren't on a mod site, and its mods for players. Unpacked once per pack (and mods left out)."""
    import hashlib
    import json
    import shutil
    import time
    from . import config as configmod, setup as setupmod
    if not spec.modpack_version:
        return [], [], []
    base = hub.state_dir / PACKS_DIR
    for old in base.glob("*") if base.is_dir() else ():  # (packs checked days ago)
        try:
            if time.time() - old.stat().st_mtime > PACK_DAYS * 86400:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass
    key = hashlib.sha256(json.dumps([spec.loader, spec.modpack_version, sorted(spec.modpack_exclude)]).encode()).hexdigest()[:20]
    folder = base / key
    done = folder / "pack.json"
    with _packs_lock:  # (two checks of the same pack unpack it once)
        if not done.is_file():
            _unpack(hub, spec, folder)
    data = json.loads(done.read_text())
    specs = [ModSpec(x["source"], str(x["id"]), required=bool(x["required"]), channel=x.get("channel")) for x in data["mods"]]
    return specs, [folder / "jars" / n for n in data["jars"] if (folder / "jars" / n).is_file()], list(data["client"])


_packs_lock = threading.Lock()


def _unpack(hub, spec, folder: Path) -> None:
    """Set a bare server up with the pack in ``folder`` and keep what the check needs of it."""
    import json
    import shutil
    from . import config as configmod, setup as setupmod
    done = folder / "pack.json"
    shutil.rmtree(folder, ignore_errors=True)
    root = folder / "root"
    bare = setupmod.SetupSpec(loader=spec.loader, minecraft=spec.minecraft, accept_eula=True, motd="pack check")
    setupmod.configure(root, bare)
    before = len(configmod.load(root).mods)
    if spec.modpack_version.startswith("curseforge:"):
        from . import curseforgepack
        curseforgepack.apply(root, spec.modpack_version, hub.http, hub.curseforge_key(), exclude=spec.modpack_exclude)
    else:
        from . import modpack
        modpack.apply(root, spec.modpack_version, hub.http, exclude=spec.modpack_exclude)
    cfg = configmod.load(root)
    mods_dir = cfg.server.dir / "mods"
    jars = sorted(p.name for p in mods_dir.glob("*.jar")) if mods_dir.is_dir() else []
    keep = folder / "jars"
    keep.mkdir(parents=True, exist_ok=True)
    for name in jars:
        shutil.move(str(mods_dir / name), keep / name)
    shutil.rmtree(root, ignore_errors=True)  # (its configs and other files aren't checked)
    done.write_text(json.dumps({"mods": [{"source": x.source, "id": x.id, "required": x.required, "channel": x.channel}
                                         for x in cfg.mods[before:]],
                                "jars": jars, "client": list(cfg.client.mods)}))
