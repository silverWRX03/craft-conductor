"""Deciding what the server should be running.

For a candidate Minecraft version the planner checks the loader and resolves every
configured mod plus its required dependencies. A plan is *complete* when the loader
and every required mod are available. Optional mods that are not ready are dropped
from the plan and picked up again by a later update, except that moving an installed
server to a newer Minecraft waits for every mod (``updates.wait_for_all_mods``):
nothing is removed without the admin saying so.

Which Minecraft versions are candidates depends on the policy:

- ``CREATE`` (nothing installed yet): the version chosen for the new server is fixed, and so
  are the loader and its build. Mods are resolved around them; when they can't be, the plan
  says why, and other versions are only ever *suggested* (:meth:`Planner.alternatives`).
  "latest" means the newest release its loader runs at the time the server is made.
- ``UPGRADE`` (an installed server): newer versions are weighed against the mods, as
  ``updates.strategy`` says.

A required dependency is looked for on the site that names it first, then on the other mod
site (CurseForge and Modrinth), for the same Minecraft version and loader; a mod found on both
is installed once.
"""

from __future__ import annotations

import hashlib
import logging
from collections import deque
from dataclasses import dataclass, field

from .config import Config, ModSpec
from .loaders import Loader
from .lock import Lock
from .minecraft import Mojang
from .mods import ModError, ModFile, ModProvider, Unavailable
from .mods.base import CHANNEL_RANK, MOD_SOURCES, SOURCE_NAMES, ClientOnly, Project, not_checked, same_project

log = logging.getLogger(__name__)

# How far back to look for other versions to suggest when a new server's mods don't work on its own.
FIRST_INSTALL_LOOKBACK = 25
SUGGESTIONS = 3

CREATE = "create"    # a new server: its Minecraft version and loader are fixed
UPGRADE = "upgrade"  # an installed server: newer Minecraft versions are considered (updates.strategy)


@dataclass
class Blocker:
    key: str
    name: str
    reason: str
    required: bool
    dependency_of: str | None = None
    client_only: bool = False
    config: str | None = None    # "source:id" as listed in craft-conductor.toml, for mods listed there
    waiting: bool = False        # optional, but upgrades wait for every mod (wait_for_all_mods)
    #: the mod names from this one down to the one that has no build: ["A", "B", "C"] for A needs B needs C
    chain: list[str] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)    # the sites looked on for the one that has no build
    unchecked: list[str] = field(default_factory=list)  # sites that couldn't be asked, and why
    cause: str = ""  # why the last mod in the chain can't be used (``reason`` says it for this one)

    def explain(self, minecraft: str, loader: str) -> str:
        """In words, for people: what needs what, and where Craft Conductor looked."""
        chain = self.chain or [self.name]
        cause = self.cause or self.reason
        if len(chain) == 1:
            text = cause if cause.startswith(chain[0]) else f"{chain[0]}: {cause}"
        else:
            needs = "".join(f", which requires {name}" for name in chain[2:])
            text = (f"{chain[0]} requires {chain[1]}{needs}, but no compatible {chain[-1]} release was found "
                    f"for Minecraft {minecraft} using {LOADER_NAMES.get(loader, loader)}")
            if " has no " not in cause:
                text += f" ({cause})"
        if self.checked:
            text += f". Craft Conductor checked {' and '.join(self.checked)}"
        if self.unchecked:
            text += f" ({'; '.join(self.unchecked)})"
        return text + "."


@dataclass
class Changes:
    minecraft: tuple[str | None, str] | None = None
    loader: tuple[str | None, str] | None = None
    added: list[ModFile] = field(default_factory=list)
    updated: list[tuple[ModFile, ModFile]] = field(default_factory=list)
    removed: list[ModFile] = field(default_factory=list)

    @property
    def runtime(self) -> bool:
        return self.minecraft is not None or self.loader is not None

    @property
    def empty(self) -> bool:
        return not (self.runtime or self.added or self.updated or self.removed)

    def summary(self) -> list[str]:
        lines = []
        if self.minecraft:
            lines.append(f"Minecraft {self.minecraft[0] or '(none)'} -> {self.minecraft[1]}")
        if self.loader:
            lines.append(f"loader {self.loader[0] or '(none)'} -> {self.loader[1]}")
        lines += [f"+ {m.name} {m.version_number}" for m in self.added]
        lines += [f"~ {new.name} {old.version_number} -> {new.version_number}" for old, new in self.updated]
        lines += [f"- {m.name} {m.version_number}" for m in self.removed]
        return lines


@dataclass
class Plan:
    minecraft: str
    loader: str
    loader_version: str | None
    mods: list[ModFile] = field(default_factory=list)
    blockers: list[Blocker] = field(default_factory=list)   # required mods that are not ready
    dropped: list[Blocker] = field(default_factory=list)    # optional / client-only mods left out
    loader_reason: str | None = None  # why the loader has no build, when it isn't "not yet"

    @property
    def complete(self) -> bool:
        return self.loader_version is not None and not self.blockers

    @property
    def loader_problem(self) -> str:
        """What to tell people when ``loader_version`` is None."""
        return self.loader_reason or f"{self.loader} has no build for Minecraft {self.minecraft} yet"

    @property
    def fingerprint(self) -> str:
        parts = [self.minecraft, self.loader, self.loader_version or ""]
        parts += sorted(f"{m.key}@{m.version_id}" for m in self.mods)
        return hashlib.sha1("\n".join(parts).encode()).hexdigest()[:16]

    def changes(self, lock: Lock) -> Changes:
        c = Changes()
        if lock.minecraft != self.minecraft or not lock.installed:
            c.minecraft = (lock.minecraft, self.minecraft)
        if lock.loader_version != self.loader_version or lock.loader != self.loader:
            c.loader = (lock.loader_version, self.loader_version)
        old = {m.key: m for m in lock.mods}
        new = {m.key: m for m in self.mods}
        for key, m in new.items():
            if key not in old:
                c.added.append(m)
            elif old[key].version_id != m.version_id:
                c.updated.append((old[key], m))
        c.removed = [m for key, m in old.items() if key not in new]
        return c


@dataclass
class Decision:
    plan: Plan | None
    #: newer versions that were considered and why they were not chosen
    blocked: list[Plan] = field(default_factory=list)
    latest: str | None = None
    policy: str = UPGRADE


DATAPACK_LOADERS = ("datapack",)  # Modrinth's builds of a mod as a datapack (ModSpec.datapack)
LOADER_NAMES = {"fabric": "Fabric", "neoforge": "NeoForge", "forge": "Forge", "quilt": "Quilt", "paper": "Paper",
                "purpur": "Purpur", "vanilla": "Vanilla"}


def newest_release(mojang: Mojang, loader: Loader) -> str:
    """What "latest" means for a new server: the newest release its loader has a build for
    (a loader can take days to support a new Minecraft). It depends on the loader chosen, never
    on the mods. When the loader's own site can't say (an outage), the newest release: the plan
    then says what's wrong instead of moving to an older Minecraft."""
    latest = mojang.latest_release()
    for version in mojang.newer_than(None)[:FIRST_INSTALL_LOOKBACK]:
        try:
            if loader.latest_version(version):
                return version
            if loader.missing_reason(version):
                return latest
        except Exception as e:  # (the plan finds out again, and says why)
            log.debug("couldn't ask %s about Minecraft %s: %s", loader.name, version, e)
            return latest
    return latest


def lowest(server: str, mod: str | None) -> str:
    """The more permissive of the server's and a mod's own release channel."""
    return max((server, mod or server), key=lambda c: CHANNEL_RANK.get(c, 0))


class Planner:
    def __init__(self, config: Config, lock: Lock, mojang: Mojang, loader: Loader,
                 providers: dict[str, ModProvider], unmanaged: list[str] | None = None):
        self.config = config
        self.lock = lock
        self.mojang = mojang
        self.loader = loader
        self.providers = providers
        self.unmanaged = unmanaged or []
        self._same: dict[tuple[str, str], Project | None] = {}  # (project key, site) -> the same mod there

    @property
    def policy(self) -> str:
        return UPGRADE if self.lock.minecraft else CREATE

    def _counterpart(self, project: Project, source: str) -> Project | None:
        """The same mod on another site (looked up once per check). Raises ModError when that
        site can't be asked."""
        key = (project.key, source)
        if key not in self._same:
            self._same[key] = self.providers[source].find_same(project)
        return self._same[key]

    def _elsewhere(self, project: Project, spec: ModSpec, minecraft: str, channel: str,
                   blocker: Blocker) -> tuple[Project, ModFile] | None:
        """A required dependency with no build on the site that names it: the same mod on the
        other mod site, for the same Minecraft and loader. ``blocker`` notes where it looked.
        Raises :class:`ClientOnly` when the other site says only players need it."""
        loaders = self.loader.mod_loaders
        for source in MOD_SOURCES:
            provider = self.providers.get(source)
            if source == spec.source or provider is None or not provider.handles(loaders):
                continue
            name = SOURCE_NAMES.get(source, source)
            try:
                other = self._counterpart(project, source)
            except ModError as e:
                blocker.unchecked.append(not_checked(provider, e))
                continue
            blocker.checked.append(name)
            if other is None:
                continue
            try:
                mod = provider.resolve(ModSpec(source, other.id, required=spec.required, dependency_of=spec.dependency_of,
                                               channel=spec.channel), minecraft, loaders, channel)
            except ClientOnly:
                raise  # (only players need it)
            except (Unavailable, ModError):
                continue
            log.info("%s has no build for Minecraft %s on %s; using the one on %s", project.name, minecraft,
                     SOURCE_NAMES.get(spec.source, spec.source), name)
            return other, mod
        return None

    def plan_for(self, minecraft: str) -> Plan:
        plan = Plan(minecraft=minecraft, loader=self.loader.name,
                    loader_version=self.loader.latest_version(minecraft))
        if plan.loader_version is None:
            plan.loader_reason = self.loader.missing_reason(minecraft)
            if (self.lock.installed and minecraft == self.lock.minecraft and self.lock.loader == self.loader.name
                    and self.lock.loader_version):
                # The build this server runs exists, whatever the loader's list says just now (its
                # site can have an incomplete list for hours), so keep it and carry on with the mods.
                log.warning("%s lists no build for Minecraft %s just now; keeping the installed %s%s",
                            self.loader.name, minecraft, self.lock.loader_version,
                            f" ({plan.loader_reason})" if plan.loader_reason else "")
                plan.loader_version, plan.loader_reason = self.lock.loader_version, None
        if self.lock.installed and minecraft != self.lock.minecraft:
            for name in self.unmanaged:
                plan.blockers.append(Blocker(f"local:{name}", name,
                    "this local file has no verified build for the new Minecraft; identify it on the Mods page, "
                    "or disable it before changing Minecraft versions", True))
        channel = self.config.updates.mod_channel
        resolved: dict[str, ModFile] = {}
        failed: dict[str, Blocker] = {}
        client_only: set[str] = set()
        listed: dict[str, str] = {}  # project key -> "source:id" in craft-conductor.toml
        # A dependency's key on the site that names it -> the key it's known by here, when that's
        # another site's (found there, or the same mod already in the plan from there).
        alias: dict[str, str] = {}
        projects: dict[str, Project] = {}  # key -> project, to spot the same mod coming from another site
        queue = deque(self.config.mods)

        def known(project: Project) -> str | None:
            """The key of the same mod already in the plan from another site, if it is."""
            for k, other in projects.items():
                if other.source != project.source and (k in resolved or k in failed or k in client_only) \
                        and same_project(project, other):
                    return k
            return None

        while queue:
            spec: ModSpec = queue.popleft()
            provider = self.providers[spec.source]
            config_id = f"{spec.source}:{spec.id}" if spec.dependency_of is None else None
            try:
                project = provider.project(spec.id)
            except ModError as e:
                failed[spec.label] = Blocker(spec.label, spec.id, str(e), spec.required, spec.dependency_of,
                                             config=config_id, checked=[SOURCE_NAMES.get(spec.source, spec.source)])
                continue
            key = project.key
            if config_id:
                listed.setdefault(key, config_id)
            elif key not in projects and (same := known(project)):
                alias[key] = key = same  # one copy, whichever site it came from first
            if key in resolved or key in failed or key in client_only:
                # Something required depends on it, so it is required too.
                if spec.required:
                    if key in resolved:
                        if not resolved[key].required:
                            for dep in resolved[key].dependencies:
                                queue.append(ModSpec(resolved[key].source, dep, required=True, dependency_of=key,
                                                     channel=spec.channel))
                        resolved[key].required = True
                    elif key in failed:
                        failed[key].required = True
                continue
            projects[key] = project
            try:
                mod = provider.resolve(spec, minecraft, DATAPACK_LOADERS if spec.datapack else self.loader.mod_loaders,
                                       lowest(channel, spec.channel))
                if spec.datapack:  # (into the world's datapacks folder; a datapack needs no mods)
                    mod.datapack, mod.dependencies = True, []
            except ClientOnly as e:
                client_only.add(key)
                if spec.dependency_of is None:
                    plan.dropped.append(Blocker(key, project.name, str(e), False, client_only=True, config=config_id))
                continue
            except Unavailable as e:
                blocker = Blocker(key, project.name, str(e), spec.required, spec.dependency_of, config=config_id,
                                  chain=[project.name], checked=[SOURCE_NAMES.get(spec.source, spec.source)])
                # No build on the site that names it (the one it was picked from, or where a mod that
                # needs it says): the same mod on the other site. A datapack comes from Modrinth only.
                try:
                    found = None if spec.datapack else \
                        self._elsewhere(project, spec, minecraft, lowest(channel, spec.channel), blocker)
                except ClientOnly:
                    client_only.add(key)
                    continue
                if found is None:
                    failed[key] = blocker
                    continue
                other, mod = found
                alias[key] = mod.key
                if config_id:
                    mod.listed_as = config_id
                if mod.key in resolved:  # (already here, by another way)
                    if spec.required and not resolved[mod.key].required:
                        for dep in resolved[mod.key].dependencies:
                            queue.append(ModSpec(mod.source, dep, required=True, dependency_of=mod.key, channel=spec.channel))
                        resolved[mod.key].required = True
                    continue
                projects[mod.key] = other
            resolved[mod.key] = mod
            for dep in mod.dependencies:
                queue.append(ModSpec(mod.source, dep, required=spec.required, dependency_of=mod.key, channel=spec.channel))

        # A mod whose dependency is unavailable is unavailable too.
        changed = True
        while changed:
            changed = False
            for key, mod in list(resolved.items()):
                needs = (alias.get(k, k) for k in (f"{mod.source}:{d}" for d in mod.dependencies))
                missing = [failed[k] for k in needs if k in failed]
                if missing:
                    del resolved[key]
                    failed[key] = Blocker(key, mod.name, f"needs {missing[0].name}: {missing[0].reason}",
                                          mod.required, mod.dependency_of, config=listed.get(key),
                                          chain=[mod.name, *(missing[0].chain or [missing[0].name])],
                                          checked=missing[0].checked, unchecked=missing[0].unchecked,
                                          cause=missing[0].cause or missing[0].reason)
                    changed = True

        plan.mods = sorted(resolved.values(), key=lambda m: m.name.lower())
        for b in failed.values():
            (plan.blockers if b.required else plan.dropped).append(b)
        if self.config.updates.wait_for_all_mods and self.lock.installed and minecraft != self.lock.minecraft:
            for b in [b for b in plan.dropped if not b.client_only]:
                plan.dropped.remove(b)
                b.waiting = True
                plan.blockers.append(b)
        return plan

    def current_version(self) -> str:
        if self.lock.minecraft:
            return self.lock.minecraft
        wanted = self.config.server.minecraft
        return newest_release(self.mojang, self.loader) if wanted == "latest" else wanted

    def _candidates(self) -> list[str]:
        if self.policy == CREATE:
            # A new server is made on the version chosen for it ("latest": the newest release
            # today), never on another one picked to suit the mods: see alternatives().
            return [self.current_version()]
        strategy = self.config.updates.strategy
        current = self.lock.minecraft
        if strategy == "mods-only" or current not in self.mojang.releases():
            return [current]  # a beta stays a beta until you choose otherwise
        newer = self.mojang.newer_than(current)
        if strategy == "latest":
            return newer[:1] + [current]
        return newer + [current]

    def decide(self, target: str | None = None, retry_failed: bool = False) -> Decision:
        """Pick the plan to apply. ``target`` forces a specific Minecraft version.

        Combinations that failed before are skipped by automatic upgrades, but tried again
        when someone asks (``retry_failed``) or when nothing is installed yet.
        """
        latest = self.mojang.latest_release()
        policy = self.policy
        if target:
            plan = self.plan_for(target)
            return Decision(plan=plan if plan.complete else None, blocked=[] if plan.complete else [plan],
                            latest=latest, policy=policy)
        blocked = []
        skip_failed = self.lock.installed and not retry_failed
        for version in self._candidates():
            plan = self.plan_for(version)
            if skip_failed and plan.complete and plan.fingerprint in self.lock.failed_plans:
                log.info("not retrying Minecraft %s automatically: the same update failed before", version)
                plan.blockers.append(Blocker("craft-conductor:failed", "an earlier attempt",
                                             f"it failed ({self.lock.failed_plans[plan.fingerprint]}); "
                                             "update manually to try again", True))
            if plan.complete:
                return Decision(plan=plan, blocked=blocked, latest=latest, policy=policy)
            blocked.append(plan)
        return Decision(plan=None, blocked=blocked, latest=latest, policy=policy)

    def alternatives(self, chosen: str, limit: int = SUGGESTIONS) -> list[str]:
        """Other releases these mods and this loader would work on, newest first: only to
        offer when a new server's mods don't work on the version chosen for it. Nothing here
        changes that version; the person picks one of these, or doesn't."""
        out = []
        for version in self.mojang.newer_than(None)[:FIRST_INSTALL_LOOKBACK]:
            if version != chosen and self.plan_for(version).complete:
                out.append(version)
                if len(out) >= limit:
                    break
        return out
