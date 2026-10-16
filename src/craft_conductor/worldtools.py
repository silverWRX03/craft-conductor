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


# Minecraft 1.21.11 (snapshot 25w44a) moved game rules into a registry and renamed some of them for good;
# the others only changed spelling. The new name of each rule that was renamed.
RENAMED = {"doDaylightCycle": "advance_time", "doWeatherCycle": "advance_weather", "doMobSpawning": "spawn_mobs",
           "doInsomnia": "spawn_phantoms", "naturalRegeneration": "natural_health_regeneration",
           "announceAdvancements": "show_advancement_messages", "spawnRadius": "respawn_radius"}
# Rules that 1.21.11 and 26.x no longer have (doFireTick: there is a number, fire_spread_radius_around_player,
# but no on/off switch): not asked about there, so the server has nothing to log as an error.
GONE = {"doFireTick"}


def registry_names(minecraft: str | None) -> bool | None:
    """Whether this Minecraft version names its game rules the new way (1.21.11, and 26.1 on); None when
    that isn't known from the version (a snapshot, or no version)."""
    m = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?$", minecraft or "")
    if not m:
        return None
    version = tuple(int(x or 0) for x in m.groups())
    return version >= (1, 21, 11)


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


def read_rules(proc, minecraft: str | None = None) -> list[dict]:
    """The rules this server knows, with their values. Each command a server refuses is logged by the
    server as an error, so as few as possible are sent: the version says which names it uses; without
    it the first answer tells which spelling it uses; and what a server answered is remembered (on
    ``proc``, for as long as it runs), so later visits send only commands that work. A server that
    doesn't answer at all is asked only once."""
    new = registry_names(minecraft)
    known: dict = getattr(proc, "rule_names", None)
    if known is None:
        known = {}
        try:
            proc.rule_names = known
        except AttributeError:
            pass
    out: list[dict] = []
    style = {True: "snake", False: "camel", None: None}[new]  # "camel", "snake", or not known yet
    for camel, kind, words in RULES:
        if new and camel in GONE:
            continue
        if camel in known:
            names = [known[camel]] if known[camel] else []
        elif style == "camel":
            names = [camel]
        elif style == "snake":
            names = [snake(camel), RENAMED.get(camel)]
        else:
            names = [camel, snake(camel), RENAMED.get(camel)]
        refused = 0
        candidates = list(dict.fromkeys(n for n in names if n))
        for name in candidates:
            got = proc.ask(f"gamerule {name}", _answer, timeout=2)
            if got is None:
                if not out and style is None:
                    return out  # not answering: don't make the page wait for every rule
                continue
            if got is not False:
                if style is None:
                    style = "camel" if name == camel else "snake"
                known[camel] = name
                out.append({"id": name, "kind": kind, "value": got, "words": words})
                break
            refused += 1
        else:
            if candidates and refused == len(candidates):
                known[camel] = None  # (this version has no such rule: not asked about again)
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
