"""Saved mod lists: keep the server's mods (and the friends' extra mods) under a name, switch to
another list, and go back. Restoring always saves the current list first ("Before …"), so a
switch can be undone. Lists are kept in the server's .craft-conductor folder; power users can download one
as JSON and load it on another server.
"""

from __future__ import annotations

import json
import re
import time
import tomllib
from pathlib import Path

from . import config as configmod
from .config import ModSpec

FILE = "mod-sets.json"
KEEP = 30
NAME = re.compile(r"[^\x00-\x1f]{1,60}")
MOD_ID = re.compile(r"[A-Za-z0-9_.-]{1,100}")


class ModSetError(ValueError):
    pass


def _path(cfg) -> Path:
    return cfg.state_dir / FILE


def load(cfg) -> list[dict]:
    try:
        data = json.loads(_path(cfg).read_text())
        return [x for x in data if isinstance(x, dict) and isinstance(x.get("name"), str) and isinstance(x.get("mods"), list)]
    except (OSError, ValueError):
        return []


def _write(cfg, sets: list[dict]) -> None:
    path = _path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(sets[:KEEP], indent=2))
    tmp.replace(path)


def current(cfg, name: str, minecraft: str | None = None) -> dict:
    return {"name": name, "saved": time.time(), "minecraft": minecraft,
            "mods": [{"source": m.source, "id": m.id, "required": m.required, "channel": m.channel} for m in cfg.mods],
            "client_mods": list(cfg.client.mods)}


def check(entry: dict) -> dict:
    """A mod list from a file or a request, checked field by field."""
    name = str(entry.get("name", "")).strip()
    if not NAME.fullmatch(name):
        raise ModSetError("give the list a name (up to 60 characters)")
    mods = []
    for m in entry.get("mods", []):
        if not isinstance(m, dict) or m.get("source", "modrinth") not in configmod.MOD_SOURCES or not MOD_ID.fullmatch(str(m.get("id", ""))):
            raise ModSetError("the list has a mod that isn't written right")
        channel = m.get("channel") if m.get("channel") in configmod.CHANNELS else None
        mods.append({"source": m.get("source", "modrinth"), "id": str(m["id"]), "required": bool(m.get("required", True)), "channel": channel})
    client = [str(x) for x in entry.get("client_mods", []) if MOD_ID.fullmatch(str(x))]
    return {"name": name, "saved": float(entry.get("saved") or time.time()), "minecraft": entry.get("minecraft"),
            "mods": mods, "client_mods": client}


def save(cfg, name: str, minecraft: str | None = None) -> dict:
    entry = check(current(cfg, name, minecraft))
    sets = [x for x in load(cfg) if x["name"] != entry["name"]]
    _write(cfg, [entry, *sets])
    return entry


def add(cfg, entry: dict) -> dict:
    """A list loaded from a file (power users)."""
    entry = check(entry)
    _write(cfg, [entry, *[x for x in load(cfg) if x["name"] != entry["name"]]])
    return entry


def delete(cfg, name: str) -> bool:
    sets = load(cfg)
    kept = [x for x in sets if x["name"] != name]
    _write(cfg, kept)
    return len(kept) != len(sets)


def restore(cfg, name: str, minecraft: str | None = None) -> str:
    """Make ``name`` the server's mod list (installed with the next update). The list it had is
    saved first as "Before <name>"."""
    entry = next((x for x in load(cfg) if x["name"] == name), None)
    if entry is None:
        raise ModSetError(f"there's no saved list called {name!r}")
    entry = check(entry)
    save(cfg, f"Before {name}"[:60], minecraft)
    path = cfg.path
    original = path.read_text()
    try:
        configmod.set_mods(path, [ModSpec(m["source"], m["id"], required=m["required"], channel=m["channel"]) for m in entry["mods"]])
        configmod.set_value(path, "client", "mods", json.dumps(entry["client_mods"]))
        configmod.parse(cfg.root, tomllib.loads(path.read_text()))  # still a valid config
    except Exception:
        path.write_text(original)
        raise
    return f"switched to {name!r}: {len(entry['mods'])} mod(s), installed with the next update"
