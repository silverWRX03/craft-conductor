"""Which mods of a plan stay off the server because only players run them.

The planner takes the mod sites' word for what a server needs. Two things it can't see there:

* CurseForge doesn't say whether a mod runs on servers. The same mod on Modrinth usually does,
  so a CurseForge mod is matched to Modrinth by its file's checksum (most authors upload the
  same file to both: an exact match), else by its slug and name, and one Modrinth says doesn't
  run on servers is left off the server (#94). One Modrinth doesn't know goes on the server; if
  it stops the server, the Dashboard offers to move it to players' mods (explain.py).
* A mod's own file can say it needs another mod on players' computers only (Forge's and
  NeoForge's ``side = "CLIENT"``, or a Fabric mod that only loads on players' computers) where
  its mod site just says "required". Such a dependency is left off the server and goes in the
  friends' download instead, with the mods only it needed (#93).

A modpack's mods are left as the pack lists them (the pack, and its server pack, decide), and a
dependency is kept whenever anything here can't be told: a file that couldn't be read, or a mod
on the server that needs it without its file saying where.
"""

from __future__ import annotations

import logging
import threading
import time

from . import modcheck
from .mods.base import Project, same_project
from .mods.modrinth import ModrinthProvider

log = logging.getLogger(__name__)

CACHE_SECONDS = 3600
_known: dict[str, tuple[float, Project | None]] = {}  # CurseForge file sha1 -> the same mod on Modrinth (or None)
_known_lock = threading.Lock()


def on_modrinth(modrinth: ModrinthProvider, files: list, projects: dict | None = None) -> dict[str, Project]:
    """The same mods on Modrinth, with what Modrinth says about their sides: CurseForge mod key ->
    Modrinth project. ``files`` are CurseForge ModFiles; ``projects`` (key -> CurseForge project)
    gives the slugs and names for the ones whose file Modrinth doesn't have. A failed lookup
    finds nothing (the mod is then taken to run on servers)."""
    projects = projects or {}
    out: dict[str, Project] = {}
    now = time.monotonic()
    todo = []
    with _known_lock:
        for f in files:
            hit = _known.get((f.sha1 or "").lower())
            if hit and now - hit[0] < CACHE_SECONDS:
                if hit[1] is not None:
                    out[f.key] = hit[1]
            else:
                todo.append(f)
    if not todo:
        return out
    found: dict[str, Project | None] = {}
    try:  # by checksum: one request for them all
        by_sha1 = modrinth.identify([f.sha1 for f in todo if f.sha1])
        ids = {str(v.get("project_id")) for v in by_sha1.values() if isinstance(v, dict) and v.get("project_id")}
        data = _projects(modrinth, sorted(ids))
        for f in todo:
            v = by_sha1.get(f.sha1 or "") if f.sha1 else None
            p = data.get(str(v.get("project_id"))) if isinstance(v, dict) else None
            if p:
                found[f.key] = _project(p)
    except Exception as e:  # (never a reason to fail a check: the mod goes on the server)
        log.info("couldn't ask Modrinth which CurseForge mods run on servers: %s", e)
        return out
    left = [f for f in todo if f.key not in found and projects.get(f.key) is not None and projects[f.key].slug]
    if left:
        try:  # by slug (Modrinth takes slugs where it takes ids), the name confirming it's the same mod
            data = _projects(modrinth, sorted({projects[f.key].slug for f in left}))
            by_slug = {str(p.get("slug", "")).lower(): p for p in data.values()}
            for f in left:
                p = by_slug.get(projects[f.key].slug.lower())
                if p and same_project(projects[f.key], _project(p)):
                    found[f.key] = _project(p)
        except Exception as e:
            log.info("couldn't look CurseForge mods up on Modrinth by name: %s", e)
    with _known_lock:
        if len(_known) > 5000:
            _known.clear()
        for f in todo:
            if f.sha1:
                _known[f.sha1.lower()] = (now, found.get(f.key))
    out.update({k: p for k, p in found.items() if p is not None})
    return out


def _projects(modrinth: ModrinthProvider, ids: list[str], batch: int = 100) -> dict[str, dict]:
    """Modrinth's projects for these ids or slugs, a hundred to a request (a modpack has hundreds)."""
    out: dict[str, dict] = {}
    for i in range(0, len(ids), batch):
        out.update(modrinth.projects(ids[i:i + batch]))
    return out


def _project(p: dict) -> Project:
    return Project(source="modrinth", id=str(p.get("id", "")), slug=str(p.get("slug", "")), name=str(p.get("title", "")),
                   server_side=str(p.get("server_side", "unknown")), client_side=str(p.get("client_side", "unknown")))


class _Files:
    """What's inside each mod's file, read when first asked (the installed copy, else the shared store)."""

    def __init__(self, m):
        from .filecheck import store_for
        self.m = m
        self.loader = m.loader.name
        self.store = store_for(m)
        self._infos: dict[str, list | None] = {}
        self.installed = {x.key: x for x in m.lock.mods}

    def of(self, mod) -> list | None:
        if mod.key not in self._infos:
            from .filecheck import infos_of
            path = self.m.mod_path(mod)
            here = self.installed.get(mod.key)
            entry = {"name": mod.name, "url": mod.url, "sha1": mod.sha1, "sha512": mod.sha512,
                     "path": str(path) if here and here.version_id == mod.version_id and path.is_file() else None}
            self._infos[mod.key] = None if mod.manual or mod.datapack else infos_of(entry, self.loader, self.store)
        return self._infos[mod.key]

    def own(self) -> list:
        """The mods in the files you put in the mods folder yourself."""
        out = []
        for name in self.m.unmanaged_jars():
            try:
                out += modcheck.read_file(self.m.mods_dir / name, self.loader)
            except OSError:
                pass
        return out


def _wants(infos: list, ids: set[str]) -> str | None:
    """How these mods' files ask for one of ``ids``: "client" (only on players' computers), "both",
    or None when they don't name it."""
    found = None
    for info in infos:
        for dep in info.depends:
            if dep.kind == "requires" and dep.id in ids:
                side = "client" if info.side == "client" else dep.side
                if side != "client":
                    return "both"
                found = "client"
    return found


def trim(m, plan) -> None:
    """Leave off the server the mods of ``plan`` that only players run (changes ``plan``: its
    mods, ``players`` and ``dropped``)."""
    from .planner import Blocker
    if plan is None or not plan.mods or m.loader.mods_folder != "mods":
        return
    away: dict[str, str] = {}        # mod key -> why it's left off the server
    for_players: set[str] = set()    # of those, the ones players need (the friends' download gets them)
    by_key = {x.key: x for x in plan.mods}
    curseforge = [x for x in plan.mods if x.source == "curseforge" and x.key not in plan.pack_keys and not x.datapack]
    if curseforge:
        modrinth = m.providers.get("modrinth") or ModrinthProvider(m.http)
        for key, p in on_modrinth(modrinth, curseforge, plan.projects).items():
            if p.server_side == "unsupported":
                away[key] = f"{by_key[key].name} only runs on players' computers (Modrinth says so)"
                if by_key[key].dependency_of is not None:
                    for_players.add(key)  # (a mod on the server needs it: on players' computers, where it runs)
    files = _Files(m) if m.loader.name in modcheck.LOADERS else None
    own: list | None = None
    changed = True
    while changed:
        changed = False
        for x in plan.mods:
            if x.key in away or x.dependency_of is None or x.key in plan.pack_keys:
                continue
            needers = [k for k, needs in plan.needs.items() if x.key in needs and k != x.key]
            left = [k for k in needers if k not in away]
            if needers and not left:  # only mods that are off the server needed it
                away[x.key] = f"{x.name} is only needed by {', '.join(by_key[k].name for k in needers)}, which only players run"
                if any(k in for_players for k in needers):
                    for_players.add(x.key)
                changed = True
                continue
            if not left or files is None:
                continue
            mine = files.of(x)
            ids = {i for info in mine or () for i in (info.id, *info.provides)}
            if not ids:
                continue  # (its file couldn't be read: it stays)
            if any(_wants(files.of(by_key[k]) or [], ids) != "client" for k in left):
                continue  # a mod on the server needs it there (or its file doesn't say where)
            # Nothing else on the server may need it there by its file alone (its site not saying so).
            others = [y for y in plan.mods if y.key not in away and y.key != x.key and y.key not in left]
            if own is None:
                own = files.own()
            if any(_wants(files.of(y) or [], ids) == "both" for y in others) or _wants(own, ids) == "both":
                continue
            away[x.key] = f"{', '.join(by_key[k].name for k in left)} only need{'s' if len(left) == 1 else ''} {x.name} on players' computers"
            for_players.add(x.key)
            changed = True
    if not away:
        return
    log.info("left off the server, as only players run them: %s", "; ".join(away.values()))
    plan.players = [x for x in plan.mods if x.key in for_players]
    plan.mods = [x for x in plan.mods if x.key not in away]
    plan.dropped += [Blocker(k, by_key[k].name, why, False, by_key[k].dependency_of, client_only=True,
                             config=by_key[k].listed_as or (k if by_key[k].dependency_of is None else None))
                     for k, why in away.items()]
