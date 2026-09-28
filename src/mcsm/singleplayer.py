"""Modded single-player games: set one up (a loader, a Minecraft version, mods), put it into the
launcher of your choice, and keep it up to date. mcsm isn't a launcher: the game is installed the
way a friend's is (join.py / launchers.py: the Minecraft Launcher, Prism, the Modrinth App or
CurseForge), only without a server to join. The worlds live in that installation and are kept when
the mods are updated.

Each game is ``<hub state>/singleplayer/<id>.json``: the recipe (name, loader, Minecraft version or
"latest", mods, memory) and what was last installed.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from pathlib import Path

from .clientpack import FORMAT, _entry, allowed_url
from .config import ModSpec
from .mods.base import ModError, Unavailable
from .mods.modrinth import ModrinthProvider

LOADERS = ("fabric", "quilt", "neoforge", "forge")
MAX_GAMES = 30
MAX_MODS = 300
TRY_VERSIONS = 8      # with "latest": newest Minecraft releases tried, until every mod has a build
ID = re.compile(r"[0-9a-f]{12}")
SLUG = re.compile(r"[A-Za-z0-9_.-]{1,100}")


class SingleplayerError(ValueError):
    pass


def folder(hub) -> Path:
    return hub.state_dir / "singleplayer"


def _path(hub, game_id: str) -> Path:
    if not ID.fullmatch(game_id or ""):
        raise SingleplayerError("no such game")
    return folder(hub) / f"{game_id}.json"


def games(hub) -> list[dict]:
    out = []
    d = folder(hub)
    for p in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            out.append(json.loads(p.read_text()))
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda g: g.get("created", 0))


def load(hub, game_id: str) -> dict:
    try:
        return json.loads(_path(hub, game_id).read_text())
    except (OSError, ValueError):
        raise SingleplayerError("no such game") from None


def save(hub, game: dict) -> dict:
    d = folder(hub)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{game['id']}.tmp"
    tmp.write_text(json.dumps(game, indent=1))
    os.replace(tmp, d / f"{game['id']}.json")
    return game


def check_recipe(name, loader, minecraft, mods, memory_gb) -> dict:
    """The parts of a game someone chose, checked."""
    name = str(name or "").strip()
    if not name or len(name) > 60 or not re.fullmatch(r"[^\\/:*?\"<>|]+", name):
        raise SingleplayerError("give the game a name (up to 60 letters, no \\ / : * ? \" < > |)")
    if loader not in LOADERS:
        raise SingleplayerError("pick Fabric, Quilt, NeoForge or Forge")
    minecraft = str(minecraft or "latest")
    if minecraft != "latest" and not re.fullmatch(r"\d+(\.\d+){1,3}", minecraft):
        raise SingleplayerError("pick a Minecraft version")
    if not isinstance(mods, list) or len(mods) > MAX_MODS:
        raise SingleplayerError(f"pick up to {MAX_MODS} mods")
    clean = []
    for item in mods:
        slug = str(item).removeprefix("modrinth:")
        if not SLUG.fullmatch(slug):
            raise SingleplayerError(f"{item!r} isn't a Modrinth mod")
        if slug not in clean:
            clean.append(slug)
    try:
        memory_gb = int(memory_gb or 4)
    except (TypeError, ValueError):
        raise SingleplayerError("memory is a number of GB") from None
    if not 2 <= memory_gb <= 32:
        raise SingleplayerError("give the game 2 to 32 GB of memory")
    return {"name": name, "loader": loader, "minecraft": minecraft, "mods": clean, "memory_gb": memory_gb}


def create(hub, **recipe) -> dict:
    if len(games(hub)) >= MAX_GAMES:
        raise SingleplayerError(f"mcsm keeps up to {MAX_GAMES} single-player games; delete one first")
    game = {"id": secrets.token_hex(6), "created": time.time(), "installed": None, **check_recipe(**recipe)}
    if any(g["name"].lower() == game["name"].lower() for g in games(hub)):
        raise SingleplayerError("there's already a game with that name")
    return save(hub, game)


def delete(hub, game_id: str) -> None:
    """Forget the game (its installation, with its worlds, stays in the launcher)."""
    _path(hub, game_id).unlink(missing_ok=True)


# ------------------------------------------------------------------ resolving
def resolve(hub, game: dict, channel: str = "release") -> dict:
    """The pack for this game now: the Minecraft version (the newest one every mod supports, for
    "latest"), the loader's newest build for it, and a build of every mod and what it needs."""
    from .loaders import get_loader
    from .minecraft import Mojang
    http = hub.http
    mojang = Mojang(http)
    loader = get_loader(game["loader"], http, mojang)
    modrinth = ModrinthProvider(http)
    if game["minecraft"] == "latest":
        candidates = list(reversed(mojang.releases()))[:TRY_VERSIONS]  # (newest first)
    else:
        candidates = [game["minecraft"]]
    why = ""
    for mc in candidates:
        loader_version = loader.latest_version(mc)
        if not loader_version:
            why = f"{game['loader']} has no build for Minecraft {mc} yet"
            continue
        mods, manual, missing = _mods(modrinth, game["mods"], mc, loader.mod_loaders, channel)
        if missing and game["minecraft"] == "latest":
            why = f"waiting for {', '.join(missing[:3])}{' and more' if len(missing) > 3 else ''} on Minecraft {mc}"
            continue  # an older Minecraft may have them all
        try:
            java = mojang.info(mc).java_major
        except Exception:
            java = None
        return {"format": FORMAT, "name": game["name"], "minecraft": mc, "loader": game["loader"],
                "loader_version": loader_version, "java_major": java, "address": "", "singleplayer": True,
                "memory_gb": game["memory_gb"], "mods": mods, "manual": manual,
                "skipped": [{"name": n, "reason": f"no build for Minecraft {mc}"} for n in missing],
                "icon": None, "updated": int(time.time())}
    raise SingleplayerError(f"nothing can be installed yet: {why}" if why else "nothing can be installed yet")


def _mods(modrinth, slugs, mc, loaders, channel) -> tuple[list[dict], list[dict], list[str]]:
    """Builds of ``slugs`` and their required dependencies for players' computers."""
    mods, manual, missing = [], [], []
    included: set[str] = set()
    todo = [ModSpec("modrinth", s) for s in slugs]
    while todo:
        spec = todo.pop(0)
        try:
            f = modrinth.resolve(spec, mc, loaders, channel, side="client")
        except (Unavailable, ModError) as e:
            if spec.dependency_of is None:
                missing.append(spec.id)
            elif not isinstance(e, Unavailable):
                missing.append(f"{spec.id} (needed by {spec.dependency_of})")
            continue
        if f.key in included:
            continue
        included.add(f.key)
        entry = _entry(f, "client")
        if spec.dependency_of:
            entry["needed_by"] = spec.dependency_of
        (mods if allowed_url(f.url) else manual).append(entry)
        todo += [ModSpec("modrinth", dep, dependency_of=f.name) for dep in f.dependencies if f"modrinth:{dep}" not in included]
    return mods, manual, missing


def summary(pack: dict) -> dict:
    """What's installed, as kept with the game."""
    return {"minecraft": pack["minecraft"], "loader_version": pack["loader_version"],
            "mods": {m["project"]: {"name": m["name"], "file": m["filename"]} for m in pack["mods"]}, "at": time.time()}


def changes(installed: dict | None, pack: dict) -> list[str]:
    """What installing ``pack`` would change, in plain words."""
    if not installed:
        return [f"Minecraft {pack['minecraft']} with {pack['loader']} {pack['loader_version']} and {len(pack['mods'])} mod(s)"]
    out = []
    if installed["minecraft"] != pack["minecraft"]:
        out.append(f"Minecraft {installed['minecraft']} → {pack['minecraft']}")
    elif installed["loader_version"] != pack["loader_version"]:
        out.append(f"{pack['loader']} {installed['loader_version']} → {pack['loader_version']}")
    new = {m["project"]: m for m in pack["mods"]}
    old = installed.get("mods", {})
    for key in sorted(set(new) - set(old), key=lambda k: new[k]["name"].lower()):
        out.append(f"+ {new[key]['name']}")
    for key in sorted(set(old) - set(new), key=lambda k: old[k]["name"].lower()):
        out.append(f"− {old[key]['name']}")
    for key in sorted(set(new) & set(old), key=lambda k: new[k]["name"].lower()):
        if new[key]["filename"] != old[key]["file"]:
            out.append(f"~ {new[key]['name']}: {old[key]['file']} → {new[key]['filename']}")
    return out
