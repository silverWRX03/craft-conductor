"""World tools: game rules with explanations, the world border, and pre-generating terrain with
the Chunky mod. All of it goes through the running server's own commands, so it works on every
loader and version that has them, and nothing is edited behind the server's back.
"""

from __future__ import annotations

import re

# (id, kind, what it does). Newer Minecraft spells rule names in snake_case (keep_inventory);
# both spellings are tried, and a rule this server doesn't know by either is left out.
RULES = [
    ("keepInventory", "bool", "Keep your items and experience when you die."),
    ("doDaylightCycle", "bool", "Day turns to night. Off: the time of day stays where it is."),
    ("doWeatherCycle", "bool", "The weather changes. Off: it stays as it is."),
    ("doMobSpawning", "bool", "Mobs appear by themselves."),
    ("mobGriefing", "bool", "Creepers blow up blocks, endermen pick them up, and so on."),
    ("doFireTick", "bool", "Fire spreads and burns out."),
    ("doInsomnia", "bool", "Phantoms come for players who haven't slept."),
    ("naturalRegeneration", "bool", "Health comes back by itself when you've eaten."),
    ("playersSleepingPercentage", "int", "How many players (in %) must sleep to skip the night."),
    ("announceAdvancements", "bool", "Say in chat when someone gets an advancement."),
    ("showDeathMessages", "bool", "Say in chat when someone dies."),
    ("spawnRadius", "int", "How far from the spawn point new players appear (blocks)."),
]


def snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
RULE_NAME = re.compile(r"[A-Za-z_]{2,60}")
VALUE = re.compile(r"true|false|-?\d{1,9}")
_CURRENT = re.compile(r"(?:Gamerule|Game rule)\s+(\S+)\s+is currently set to:?\s*(\S+)", re.I)
_BORDER = re.compile(r"world border is currently\s+([\d.,]+)\s+block", re.I)
_CHUNKY = re.compile(r"\[Chunky\].*?(?:Task running|Task finished|Processed)[^\n]*?(\d[\d,]*)\s+chunks?\s*\(([\d.]+)%\)", re.I)
_CHUNKY_DONE = re.compile(r"\[Chunky\].*?(Task finished|Task cancelled|Task stopped)", re.I)


def _answer(lines: list[str]):
    for line in lines:
        if m := _CURRENT.search(line):
            return m.group(2).rstrip(".")
        if re.search(r"Incorrect argument|Unknown or incomplete command|Unknown game ?rule", line, re.I):
            return False  # this name isn't known to this version
    return None


def read_rules(proc) -> list[dict]:
    """The rules this server knows, with their values. The first answer tells which spelling
    it uses; a server that doesn't answer at all is asked only once."""
    out: list[dict] = []
    style = None  # "camel" or "snake", once known
    for camel, kind, words in RULES:
        names = [camel, snake(camel)] if style is None else [camel if style == "camel" else snake(camel)]
        for name in names:
            got = proc.ask(f"gamerule {name}", _answer, timeout=2)
            if got is None:
                if not out and style is None:
                    return out  # not answering: don't make the page wait for every rule
                continue
            if got is not False:
                style = style or ("camel" if name == camel else "snake")
                out.append({"id": name, "kind": kind, "value": got, "words": words})
                break
    return out


def set_rule(proc, rule: str, value: str) -> str:
    if not RULE_NAME.fullmatch(rule) or not VALUE.fullmatch(value):
        raise ValueError("a game rule is a name and true, false or a number")
    proc.send(f"gamerule {rule} {value}")
    return f"{rule} set to {value}"


def border_size(proc) -> float | None:
    def parse(lines):
        for line in lines:
            if m := _BORDER.search(line):
                return float(m.group(1).replace(",", ""))
        return None
    return proc.ask("worldborder get", parse, timeout=3)


def set_border(proc, diameter: int, x: int = 0, z: int = 0) -> str:
    if not 16 <= diameter <= 59_999_968:
        raise ValueError("the world border must be between 16 and 59,999,968 blocks wide")
    if not (abs(x) <= 29_999_984 and abs(z) <= 29_999_984):
        raise ValueError("the centre is outside the world")
    proc.send(f"worldborder center {x} {z}")
    proc.send(f"worldborder set {diameter}")
    return f"world border: {diameter} blocks wide around {x}, {z}"


def chunky_progress(lines: list[str]) -> dict | None:
    """The latest pre-generation progress Chunky printed, if any."""
    for line in reversed(lines):
        if _CHUNKY_DONE.search(line):
            return {"running": False, "percent": 100.0 if "finished" in line.lower() else None, "line": line.strip()}
        if m := _CHUNKY.search(line):
            return {"running": True, "percent": float(m.group(2)), "chunks": int(m.group(1).replace(",", "")), "line": line.strip()}
    return None


CHUNKY_ACTIONS = {"pause": "chunky pause", "continue": "chunky continue", "cancel": "chunky cancel"}


def chunky_start(proc, radius: int, x: int = 0, z: int = 0) -> str:
    if not 100 <= radius <= 50_000:
        raise ValueError("pick a radius between 100 and 50,000 blocks")
    proc.send(f"chunky center {x} {z}")
    proc.send(f"chunky radius {radius}")
    proc.send("chunky start")
    proc.send("chunky confirm")  # (Chunky asks when a task for the world already exists)
    return f"pre-generating {radius} blocks around {x}, {z}"
