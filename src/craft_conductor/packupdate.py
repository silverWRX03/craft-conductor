"""Moving a server made from a modpack to another version of the pack (#95).

A server made from a modpack remembers it: ``[modpack]`` in craft-conductor.toml (its site, project
and version) and, in ``.craft-conductor/modpack.json``, what the pack put where: the file each of
its mods is held at, its mods for players, the mods left out when it was set up, and a checksum of
each file it copied in (configs, scripts...). Updating the pack:

* holds the pack's mods at the new version's files: mods the pack no longer has are taken off,
  new ones added, the rest moved to their new file. A pack mod you removed stays removed, one you
  held at another build (Change version) stays there, and mods you added yourself are left alone;
* does the same with its mods for players (a CurseForge pack's, in the friends' download);
* copies its new files in, except the ones you changed since the pack put them there (they're
  kept, and the result says which). A mod file the pack had in its own files and no longer has
  goes, unless you changed it;
* moves the server to the pack's Minecraft version when the new version has another one, and
  its loader to the new version's build.

The server is then updated as usual: a backup first, the new files, a test start. If that fails,
the server is put back from the backup and craft-conductor.toml as it was: nothing is half done.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from . import config as configmod, safearchive
from .config import ModSpec, Pin
from .http import HttpClient, sha1_file
from .modpack import ModpackError

log = logging.getLogger(__name__)

STATE = "modpack.json"
NEWER = 10   # versions offered at most


def state_path(root: Path) -> Path:
    return root / configmod.STATE_DIR / STATE


def load_state(root: Path) -> dict:
    try:
        data = json.loads(state_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    for key in ("mods", "friends", "files"):
        data[key] = data.get(key) if isinstance(data.get(key), dict) else {}
    data["removed"] = [str(k) for k in data.get("removed") or [] if isinstance(k, str)]
    return data


def record(root: Path, source: str, project: str, version: str, name: str, mods: dict[str, str],
           removed: list[str], friends: dict[str, str], files: dict[str, str]) -> None:
    """Remember the pack a server was made from (or moved to): ``[modpack]`` and modpack.json.
    ``mods`` and ``friends``: mod key -> the file the pack holds it at; ``files``: path -> sha1."""
    path = root / configmod.CONFIG_NAME
    for key, value in (("source", source), ("project", project), ("version", version), ("name", name[:200])):
        configmod.set_value(path, "modpack", key, configmod.toml_string(value))
    state = state_path(root)
    state.parent.mkdir(parents=True, exist_ok=True)
    tmp = state.with_name(STATE + ".tmp")
    tmp.write_text(json.dumps({"mods": mods, "removed": sorted(set(removed)), "friends": friends, "files": files},
                              indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(state)


def copy_member(z: zipfile.ZipFile, member: zipfile.ZipInfo, server_dir: Path, parts: tuple[str, ...]) -> str:
    """Copy one of a pack's own files into the server folder (never through a link); its sha1."""
    digest = hashlib.sha1()
    with safearchive.open_new(server_dir, parts) as out, z.open(member) as src:
        while chunk := src.read(1 << 20):
            digest.update(chunk)
            out.write(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------- a version of the pack
@dataclass
class Mod:
    key: str
    version: str        # the file the pack holds it at (Modrinth version id, CurseForge file id)
    name: str
    path: str = ""      # mods/<file>.jar, as the pack names it
    required: bool = True
    channel: str | None = None


@dataclass
class Pack:
    """One version of a modpack: what it puts on the server and gives players."""
    source: str
    project: str
    version: str
    name: str
    minecraft: str
    loader: str
    server: dict[str, Mod] = field(default_factory=dict)
    friends: dict[str, Mod] = field(default_factory=dict)
    loader_version: str = ""   # the loader's build it was made with ("" when it doesn't say)


def _key(m) -> str:
    key = getattr(m.providers.get("curseforge"), "api_key", "") or m.config.curseforge_api_key
    if not key:
        raise ModpackError("CurseForge modpacks need a CurseForge API key (Craft Conductor settings → CurseForge)")
    return key


def _curseforge(m, version: str) -> Pack:
    from . import curseforgepack
    info = curseforgepack.preview(m.http, _key(m), f"curseforge:{version}")
    pack = Pack("curseforge", str(info.get("project", "")), version, info["name"], info["minecraft"], info["loader"],
                loader_version=info.get("loader_version") or "")
    for x in info["mods"]:
        early = x.get("channel") if x.get("channel") in ("beta", "alpha") else None
        mod = Mod(f"curseforge:{x['project_id']}", x["version_id"], x["name"], x["path"], x["required"], early)
        (pack.server if x["included_on_server"] else pack.friends)[mod.key] = mod
    return pack


def _modrinth(m, version: str) -> Pack:
    from . import modpack
    info = modpack.version_info(m.http, version)
    data = modpack.preview(m.http, version)
    pack = Pack("modrinth", info["project_id"], version, info["name"], data["minecraft"], data["loader"],
                loader_version=data.get("loader_version") or "")
    for x in data["mods"]:
        if x["project_id"] and x["included_on_server"]:
            pack.server[f"modrinth:{x['project_id']}"] = Mod(f"modrinth:{x['project_id']}", x["version_id"], x["name"], x["path"])
    return pack


def open_version(m, version: str) -> Pack:
    rec = m.config.modpack
    if rec is None:
        raise ModpackError("this server wasn't made from a modpack (or was made before Craft Conductor remembered which)")
    if not re.fullmatch(r"[A-Za-z0-9]{8}" if rec.source == "modrinth" else r"\d{1,10}", version or ""):
        raise ModpackError("that isn't a version of this modpack")
    pack = _modrinth(m, version) if rec.source == "modrinth" else _curseforge(m, version)
    if pack.project != rec.project:
        raise ModpackError(f"{pack.name} isn't a version of {rec.name or 'this modpack'}")
    return pack


# --------------------------------------------------------------- newer versions
CHANNELS = {1: "release", 2: "beta", 3: "alpha"}
RANK = {"release": 0, "beta": 1, "alpha": 2}


def versions(m) -> dict:
    """The pack's version this server is on, and the newer ones (newest first, as stable as the one
    it's on or more): {"pack": {...}, "current": {...}, "newer": [{id, name, date, minecraft, channel}]}."""
    rec = m.config.modpack
    if rec is None:
        return {"pack": None, "current": None, "newer": []}
    if rec.source == "modrinth":
        from .mods.modrinth import API
        listed = [{"id": v.get("id", ""), "name": v.get("name") or v.get("version_number", ""), "date": v.get("date_published", ""),
                   "minecraft": list(v.get("game_versions") or []), "channel": v.get("version_type", "release")}
                  for v in m.http.get_json(f"{API}/project/{rec.project}/version", cache=False)]
    else:
        from . import curseforgepack
        api = curseforgepack._Api(m.http, _key(m))
        raw = [f for f in api.get(f"/mods/{rec.project}/files", {"pageSize": 50}) if not f.get("isServerPack")]
        if not any(str(f.get("id")) == rec.version for f in raw):
            raw += list(api.files([int(rec.version)]).values())
        listed = [{"id": str(f.get("id", "")), "name": f.get("displayName") or f.get("fileName", ""), "date": f.get("fileDate", ""),
                   "minecraft": [v for v in f.get("gameVersions", []) if re.fullmatch(r"\d+(\.\d+)+", str(v))],
                   "channel": CHANNELS.get(f.get("releaseType"), "alpha")} for f in raw]
    current = next((v for v in listed if v["id"] == rec.version), None)
    if current is None:
        return {"pack": rec.name, "current": {"id": rec.version, "name": rec.name}, "newer": []}
    allowed = max(RANK.get(current["channel"], 0), 0)
    newer = sorted((v for v in listed if v["date"] > current["date"] and RANK.get(v["channel"], 2) <= allowed),
                   key=lambda v: v["date"], reverse=True)
    return {"pack": rec.name, "current": current, "newer": newer[:NEWER]}


# --------------------------------------------------------------- what changes
@dataclass
class Plan:
    """What updating the pack to ``new`` changes in the server's settings."""
    new: Pack
    add: list[Mod] = field(default_factory=list)
    remove: list[str] = field(default_factory=list)       # keys of pack mods it no longer has
    move: list[Mod] = field(default_factory=list)         # pack mods held at another file now
    kept_removed: list[Mod] = field(default_factory=list)  # pack mods you removed: they stay removed
    kept_held: list[Mod] = field(default_factory=list)     # pack mods you held at another build: they stay there
    friends_add: list[Mod] = field(default_factory=list)
    friends_remove: list[str] = field(default_factory=list)
    friends_move: list[Mod] = field(default_factory=list)
    minecraft: str | None = None                          # the new Minecraft, when it changes
    loader_version: str | None = None                     # the loader's new build, when it changes

    def to_dict(self, names: dict[str, str]) -> dict:
        n = lambda k: names.get(k) or k  # noqa: E731
        return {"name": self.new.name, "version": self.new.version, "minecraft": self.minecraft,
                "loader": self.new.loader, "loader_version": self.loader_version,
                "added": [x.name for x in self.add], "removed": [n(k) for k in self.remove], "updated": len(self.move),
                "kept_removed": [x.name for x in self.kept_removed], "kept_held": [x.name for x in self.kept_held],
                "friends_added": [x.name for x in self.friends_add], "friends_removed": [n(k) for k in self.friends_remove],
                "friends_updated": len(self.friends_move)}


def plan(m, new: Pack) -> Plan:
    cfg, lk = m.config, m.lock
    if new.loader != cfg.server.loader:
        raise ModpackError(f"{new.name} runs on {new.loader}, not {cfg.server.loader} like this server: make a new server from it")
    state = load_state(cfg.root)
    old, old_friends = state["mods"], state["friends"]
    listed = {f"{s.source}:{s.id}": s for s in cfg.mods}
    gone = set(state["removed"]) | {k for k in old if k not in listed}  # removed when it was set up, or since
    p = Plan(new, minecraft=new.minecraft if new.minecraft != (lk.minecraft or cfg.server.minecraft) else None)
    if new.loader_version and new.loader_version != (lk.loader_version if lk.installed else cfg.server.loader_version):
        p.loader_version = new.loader_version
    for key, mod in new.server.items():
        if key in gone:
            p.kept_removed.append(mod)
        elif key not in old:
            if key not in listed:
                p.add.append(mod)  # (one you added yourself is left as you added it)
        elif old[key] != mod.version:
            unchanged = cfg.pins.get(key) is not None and cfg.pins[key].version == old[key]
            (p.move if unchanged else p.kept_held).append(mod)  # (held at another build, or Newest: as you chose)
    p.remove = [k for k in old if k not in new.server and k in listed and listed[k].pack]
    mine = set(cfg.client.mods)
    for key, mod in new.friends.items():
        entry = f"curseforge:{key.split(':', 1)[1]}"
        if key not in old_friends:
            if entry not in mine:
                p.friends_add.append(mod)
        elif entry in mine and cfg.pins.get(key) is not None and cfg.pins[key].version == old_friends[key] != mod.version:
            p.friends_move.append(mod)
    p.friends_remove = [k for k in old_friends if k not in new.friends and f"curseforge:{k.split(':', 1)[1]}" in mine]
    return p


def preview(m, version: str) -> dict:
    """What updating the pack to ``version`` would change, for the page to ask first."""
    p = plan(m, open_version(m, version))
    names = {x.key: x.name for x in m.lock.mods}
    return p.to_dict(names)


# --------------------------------------------------------------- doing it
class Change:
    """The settings changed for a pack update, ready to be undone; ``write`` puts the pack's files in."""

    def __init__(self, m, p: Plan):
        self.m, self.p = m, p
        self.path = m.config.path
        self.before = configmod.read_text(self.path)
        self.files: dict[str, str] | None = None   # the new version's own files (path -> sha1), once written
        self.kept: list[str] = []      # files you changed: left as they are
        self.written = 0
        self.archive: Path | None = None

    def settings(self) -> None:
        cfg, p, path = self.m.config, self.p, self.path
        new = p.new
        for mod in p.add:
            source, pid = mod.key.split(":", 1)
            configmod.append_mod(path, ModSpec(source, pid, required=mod.required, channel=mod.channel, pack=True))
            configmod.set_pin(path, mod.key, Pin(mod.version, new.minecraft))
        for mod in p.move:
            configmod.set_pin(path, mod.key, Pin(mod.version, new.minecraft))
        for key in p.remove:
            source, pid = key.split(":", 1)
            configmod.remove_mod(path, source, pid)
            configmod.set_pin(path, key, None)
        mods = list(cfg.client.mods)
        for key in p.friends_remove:
            entry = f"curseforge:{key.split(':', 1)[1]}"
            mods = [x for x in mods if x != entry]
            configmod.set_pin(path, key, None)
        for mod in p.friends_add + p.friends_move:
            entry = f"curseforge:{mod.key.split(':', 1)[1]}"
            if entry not in mods:
                mods.append(entry)
            configmod.set_pin(path, mod.key, Pin(mod.version, new.minecraft))
        if mods != cfg.client.mods:
            configmod.set_value(path, "client", "mods", json.dumps(mods))
        if p.minecraft:
            configmod.set_value(path, "server", "minecraft", json.dumps(p.minecraft))
        configmod.hold_loader(path, new.loader_version)  # (held at the new version's build)
        configmod.set_value(path, "modpack", "version", json.dumps(new.version))
        configmod.set_value(path, "modpack", "name", configmod.toml_string(new.name[:200]))
        self.m.reload_config()

    def undo(self) -> None:
        configmod.write_text(self.path, self.before)
        self.m.reload_config()

    def fetch(self, folder: Path) -> None:
        """Download the new version (into ``folder``) before the server is stopped for the update."""
        self.archive = _download_pack(self.m, self.p.new, folder)

    def write(self) -> None:
        """The pack's own files (configs, scripts, mods that aren't on a mod site), into the server folder:
        called once the update's backup is made (Manager.apply's ``prepare``), so a failed update puts
        them back too."""
        server_dir = self.m.server_dir
        old = load_state(self.m.config.root)["files"]
        self.files = {}
        for rel, sha1, put in _files(self.m, self.p.new, self.archive):
            self.files[rel] = sha1
            target = server_dir.joinpath(*PurePosixPath(rel).parts)
            if target.is_file():
                here = sha1_file(target)
                if here == sha1:
                    continue
                if rel in old and here != old[rel]:
                    self.kept.append(rel)  # (you changed it since the pack put it there)
                    continue
            put()
            self.written += 1
        from .modpack import _safe_target
        for rel, sha1 in old.items():  # a mod file the pack doesn't have any more (unless you changed it)
            if rel in self.files or not rel.startswith("mods/") or not rel.endswith(".jar"):
                continue
            try:
                target = _safe_target(server_dir, rel)  # (never outside the server folder, whatever the file says)
            except safearchive.UnsafeName:
                continue
            if target.is_file() and not safearchive.is_link(target) and sha1_file(target) == sha1:
                target.unlink()

    def done(self) -> None:
        new, p = self.p.new, self.p
        state = load_state(self.m.config.root)
        removed = sorted(set(state["removed"]) | {x.key for x in p.kept_removed})
        record(self.m.config.root, new.source, new.project, new.version, new.name,
               {x.key: x.version for x in new.server.values() if x.key not in removed}, removed,
               {x.key: x.version for x in new.friends.values()},
               state["files"] if self.files is None else self.files)


def _download_pack(m, new: Pack, folder: Path) -> Path:
    if new.source == "curseforge":
        from . import curseforgepack
        api = curseforgepack._Api(m.http, _key(m))
        mod, f = curseforgepack._pack(api, int(new.version))
        return curseforgepack._download(api, mod, f, folder / "pack.zip", "modpack file")
    from . import modpack
    info = modpack.version_info(m.http, new.version)
    archive = m.http.download(info["url"], folder / "pack.mrpack", sha1=info["sha1"], sha512=info["sha512"])
    if archive.stat().st_size > modpack.MAX_PACK:
        raise ModpackError("that modpack is too big")
    return archive


def _files(m, new: Pack, archive: Path):
    """The new version's own files: (path in the server folder, sha1, write it)."""
    if new.source == "curseforge":
        from . import curseforgepack
        manifest, z = curseforgepack.read_manifest(archive)
        prefixes = (str(manifest.get("overrides") or "overrides") + "/",)
        downloads = []
    else:
        from . import modpack
        index, z = modpack.read_index(archive)
        prefixes = modpack.OVERRIDES
        downloads = modpack.other_files(index, m.server_dir)
    from .modpack import _override_members
    with z:
        what = f"the modpack {safearchive.printable(new.name)}"
        chosen = {"/".join(parts): (member, parts) for member, parts in _override_members(z, m.server_dir, what, prefixes)}
        for rel, (member, parts) in chosen.items():  # (server-overrides/ over overrides/, as when it was set up)
            yield rel, _member_sha1(z, member), lambda member=member, parts=parts: copy_member(z, member, m.server_dir, parts)
    for rel, url, hashes in downloads:
        sha1 = hashes.get("sha1")
        if not sha1:
            continue
        yield rel, sha1, lambda rel=rel, url=url, hashes=hashes: _download_to(m.http, url, hashes, m.server_dir, rel)


def _member_sha1(z: zipfile.ZipFile, member: zipfile.ZipInfo) -> str:
    digest = hashlib.sha1()
    with z.open(member) as src:
        while chunk := src.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _download_to(http: HttpClient, url: str, hashes: dict, server_dir: Path, rel: str) -> None:
    from .modpack import _safe_target
    target = _safe_target(server_dir, rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    http.download(url, target, sha1=hashes.get("sha1"), sha512=hashes.get("sha512"))


def run(d, version: str) -> str:
    """The update, as a job of the server's (daemon.py): settings, then the usual update with the
    pack's files put in after its backup. Everything goes back as it was when it fails."""
    m = d.m
    p = plan(m, open_version(m, version))
    with tempfile.TemporaryDirectory() as tmp:
        change = Change(m, p)
        change.fetch(Path(tmp))
        message = _update(d, change)
    details = []
    if p.add or p.remove or p.move:
        details.append(f"{len(p.add)} mod(s) added, {len(p.remove)} removed, {len(p.move)} moved to the pack's new file")
    if change.kept:
        details.append(f"kept your changes to {', '.join(change.kept[:5])}" + (" and more" if len(change.kept) > 5 else ""))
    if p.kept_removed:
        details.append(f"left out as before: {', '.join(x.name for x in p.kept_removed[:5])}")
    log.info("%s%s", message, f" ({'; '.join(details)})" if details else "")
    return message + (f" ({'; '.join(details)})" if details else "")


def _update(d, change: Change) -> str:
    from . import backup
    m, p = d.m, change.p
    change.settings()
    try:
        decision, changes = m.check(p.minecraft, retry_failed=True)
        if decision.plan is None:
            blocked = decision.blocked[0] if decision.blocked else None
            why = "; ".join(b.explain(blocked.minecraft, blocked.loader) for b in blocked.blockers[:3]) if blocked and blocked.blockers \
                else (blocked.loader_problem if blocked else "nothing could be installed")
            raise ModpackError(f"{p.new.name} can't be installed: {why}")
        missing = m.missing_manual(decision.plan)
        if missing:
            raise ModpackError(f"{p.new.name} has {len(missing)} mod(s) to download by hand first: "
                               + ", ".join(x.name for x in missing[:5]) + ". Download them (Mods page), then update the pack again.")
        if changes is None or changes.empty:  # (only its own files changed: backed up first all the same)
            cfg = m.config
            archive = backup.create(m.server_dir, cfg.backups.dir, f"before-pack-{p.new.version}", cfg.backups.exclude)
            try:
                change.write()
            except Exception:
                backup.restore(archive, m.server_dir)
                raise
            running = bool(d.proc and d.proc.running)
            message = f"Updated the pack to {p.new.name}: its files" + (" (used from the server's next start)" if running else "")
        else:
            was_running = bool(d.proc and d.proc.running)
            result = m.apply(decision.plan, server=d.proc, restart=was_running or d.want_running, prepare=change.write)
            if result.process:
                d.proc = result.process
            if not result.ok:
                raise ModpackError(result.message)
            message = f"Updated the pack to {p.new.name}"
    except Exception:
        change.undo()
        raise
    change.done()
    try:
        from .daemon import decision_to_dict
        d.last_check = decision_to_dict(m, *m.check())
    except Exception:
        pass
    return message

