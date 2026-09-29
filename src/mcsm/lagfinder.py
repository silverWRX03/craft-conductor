"""Lag finder: when the server can't keep up, find out why and say it in plain words.

Two looks, both with what Minecraft already has (no mod needed):

* **Where the time goes:** Minecraft's own profiler (``/debug start``, then ``/debug stop`` after
  30 seconds) writes how much of each tick went to mobs and other entities, to machines (block
  entities: hoppers, furnaces, modded machines), to loading and making land, and so on, with the
  kinds of entity and machine that cost most.
* **Where in the world:** the saved world's files list every entity and machine by chunk, so the
  busiest places can be named by their coordinates ("around x 1200, z -400: 412 cows").

The report is kept in ``.mcsm/lag.json``. The daemon runs it by itself when the server keeps
falling behind while people play (``[server] find_lag``), at most once an hour.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import zipfile
from collections import Counter
from pathlib import Path

log = logging.getLogger(__name__)

PROFILE_SECONDS = 30
REPORT_NAME = "lag.json"
LAGGY_TPS = 17.0          # below this, players notice
WATCH_EVERY = 120         # seconds between readings while people play (the daemon's watch)
WATCH_SAMPLES = 3         # this many readings in a row below LAGGY_TPS start a look
AUTO_GAP = 3600           # at most one automatic look an hour
ENTITY_FILES = 400        # entity files read at most (newest first)
REGION_FILES = 8          # region files read for machines (the most recently changed)

# "[02] |   |   entities(201/1) - 45.80%/37.55%"
_LINE = re.compile(r"^\[(\d+)\]\s((?:\|\s{3})*)(.+?)\((\d+)/(\d+)\)\s+-\s+([\d.]+)%/([\d.]+)%\s*$")
_STOPPED = re.compile(r"Stopped (?:debug )?profiling after ([\d.]+) second.*?([\d.]+) tick", re.I)
_TICKS_PER_SECOND = re.compile(r"\(([\d.]+) ticks? per second\)", re.I)
_LAG_LINE = re.compile(r"Can't keep up!.*?Running (\d+)ms", re.I)

KINDS = {  # profiler section -> (kind, words)
    "entities": ("entities", "Mobs, animals, items on the ground and other entities"),
    "blockEntities": ("machines", "Machines: hoppers, furnaces, chests with hoppers, modded machines (block entities)"),
    "chunkSource": ("chunks", "Loading, making and saving land (chunks)"),
    "chunks": ("chunks", "Loading, making and saving land (chunks)"),
    "chunkLoad": ("chunks", "Loading, making and saving land (chunks)"),
    "randomTick": ("random", "Crops growing, leaves decaying and other random ticks"),
    "raid": ("raids", "Raids"),
    "connection": ("players", "Talking to the players' games (the network)"),
    "save": ("save", "Saving the world"),
    "autoSave": ("save", "Saving the world"),
}
TIPS = {
    "entities": "Too many animals in one pen, a mob farm, or lots of items lying around. Spread animals out or cull "
                "them, collect or clear dropped items, and keep mob farms small or switched off when nobody's near.",
    "machines": "Lots of hoppers or machines in one place. Hoppers are the usual cause: fewer of them, or put a "
                "composter or other block on top of hoppers that don't need to pull items.",
    "chunks": "Players exploring new land makes the server generate it as they go. Pre-generate the world "
              "(Settings → World tools → Pre-generate terrain) or lower the view distance.",
    "random": "Very large farms (crops, leaves). Usually harmless; a lower random tick speed game rule helps.",
    "raids": "A raid is on: it ends by itself.",
    "players": "Lots of players or a slow connection. Lower the view distance, or check the computer's upload speed.",
    "save": "Saving takes long: a slow or nearly full disk. Check my setup shows the free space.",
}


# ----------------------------------------------------------------- profile
def parse_profile(text: str) -> list[dict]:
    """Every section of a profiler dump: name, depth, its parents' names, % of the whole tick."""
    nodes, stack = [], []
    for raw in text.splitlines():
        m = _LINE.match(raw.rstrip())
        if not m:
            continue
        depth = int(m.group(1))
        name = m.group(3).strip()
        del stack[depth:]
        nodes.append({"name": name, "depth": depth, "parents": list(stack), "share": float(m.group(7))})
        stack.append(name)
    return nodes


def _is_type(name: str) -> bool:
    return bool(re.fullmatch(r"#?[a-z0-9_.-]+:[a-z0-9_./-]+", name))


def summarize_profile(nodes: list[dict]) -> dict:
    """{kind: {"share", "words", "types": [(type, share)]}} from :func:`parse_profile`."""
    out: dict[str, dict] = {}
    for n in nodes:
        kind = KINDS.get(n["name"])
        if not kind or any(p in KINDS for p in n["parents"]):
            continue  # (a section inside another one is already counted)
        entry = out.setdefault(kind[0], {"share": 0.0, "words": kind[1], "types": Counter()})
        entry["share"] += n["share"]
    for n in nodes:  # the kinds of entity and machine that cost most
        if not _is_type(n["name"]):
            continue
        section = next((KINDS[p][0] for p in reversed(n["parents"]) if p in KINDS), None)
        if section in ("entities", "machines"):
            entry = out.setdefault(section, {"share": 0.0, "words": KINDS["entities" if section == "entities" else "blockEntities"][1],
                                             "types": Counter()})
            key = n["name"].lstrip("#")
            entry["types"][key] = max(entry["types"][key], n["share"])
    for entry in out.values():
        entry["share"] = round(min(100.0, entry["share"]), 1)
        entry["types"] = [(t, round(s, 1)) for t, s in entry["types"].most_common(5) if s >= 0.5]
    return out


def read_profile(server_dir: Path, since: float) -> str:
    """The text of the newest profiler dump written after ``since`` (a .txt, or inside a .zip)."""
    folder = server_dir / "debug"
    if not folder.is_dir():
        return ""
    files = sorted((p for p in folder.iterdir() if p.is_file() and p.stat().st_mtime >= since - 1
                    and p.suffix in (".txt", ".zip")), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        try:
            if path.suffix == ".txt":
                text = path.read_text(errors="replace")
            else:
                with zipfile.ZipFile(path) as z:
                    names = [n for n in z.namelist() if n.endswith(".txt") and "profil" in n.lower()]
                    text = "\n".join(z.read(n).decode("utf-8", "replace") for n in names[:3])
        except (OSError, zipfile.BadZipFile):
            continue
        if _LINE.search(text) or any(_LINE.match(line) for line in text.splitlines()[:200]):
            return text
    return ""


# ------------------------------------------------------------ the world
def _dimensions(world: Path) -> list[tuple[str, Path]]:
    """(name, folder) for the overworld and, if there, the Nether and the End (any layout)."""
    from .areas import dimension_folder
    out = [("the Overworld", dimension_folder(world))]
    for name, dim in (("the Nether", "nether"), ("the End", "end")):
        folder = dimension_folder(world, dim)
        if folder.is_dir():
            out.append((name, folder))
    return out


def _chunks(folder: Path, limit: int, newer_than: float = 0.0):
    from .preview import region_chunks
    if not folder.is_dir():
        return
    files = [p for p in folder.glob("r.*.mca") if p.stat().st_mtime >= newer_than]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files[:limit]:
        yield from region_chunks(path)


def hotspots(world: Path, top: int = 3) -> dict:
    """The busiest places in the saved world: {"entities": [...], "machines": [...]}, each place
    {"dimension", "x", "z", "count", "types": [(type, count)]}, busiest first."""
    ents: list[dict] = []
    machines: list[dict] = []
    recent = time.time() - 2 * 3600
    for dim, folder in _dimensions(world):
        for cx, cz, root in _chunks(folder / "entities", ENTITY_FILES):
            kinds = Counter(str(e.get("id", "?")) for e in root.get("Entities", []) if isinstance(e, dict))
            if sum(kinds.values()) >= 20:
                ents.append({"dimension": dim, "x": cx * 16 + 8, "z": cz * 16 + 8, "count": sum(kinds.values()),
                             "types": kinds.most_common(3)})
        for cx, cz, root in _chunks(folder / "region", REGION_FILES, newer_than=recent):
            kinds = Counter(str(e.get("id", "?")) for e in root.get("block_entities", root.get("Level", {}).get("TileEntities", []))
                            if isinstance(e, dict))
            if sum(kinds.values()) >= 20:
                machines.append({"dimension": dim, "x": cx * 16 + 8, "z": cz * 16 + 8, "count": sum(kinds.values()),
                                 "types": kinds.most_common(3)})
    return {"entities": _merge(ents)[:top], "machines": _merge(machines)[:top]}


def _merge(places: list[dict]) -> list[dict]:
    """Next-door chunks are one place (a farm often spans a few)."""
    places.sort(key=lambda p: -p["count"])
    merged: list[dict] = []
    for p in places:
        near = next((m for m in merged if m["dimension"] == p["dimension"]
                     and abs(m["x"] - p["x"]) <= 32 and abs(m["z"] - p["z"]) <= 32), None)
        if near:
            near["count"] += p["count"]
            kinds = Counter(dict(near["types"])) + Counter(dict(p["types"]))
            near["types"] = kinds.most_common(3)
        else:
            merged.append({**p, "types": list(p["types"])})
    merged.sort(key=lambda p: -p["count"])
    return merged


# ------------------------------------------------------------ the report
def _name(kind: str) -> str:
    """"minecraft:cow" -> "cow"; a mod's own kinds keep the mod's name."""
    ns, _, name = kind.partition(":")
    words = name.replace("_", " ")
    return words if ns == "minecraft" else f"{words} ({ns})"


def _place(p: dict) -> str:
    what = ", ".join(f"{n} {_name(k)}" for k, n in p["types"])
    return f"around x {p['x']}, z {p['z']} in {p['dimension']}: {p['count']} in all ({what})"


def report(profile: dict, places: dict, tps: float | None, lag_lines: int, mods=()) -> dict:
    """Findings, biggest first, each {"kind", "share", "title", "detail", "places", "tip", "mods"}."""
    names = {}
    for m in mods:  # a namespace -> the installed mod's name
        for token in {m.key.partition(":")[2].lower(), Path(m.filename).stem.split("-")[0].lower()}:
            if token:
                names[token] = m.name
    findings = []
    for kind, entry in sorted(profile.items(), key=lambda kv: -kv[1]["share"]):
        if entry["share"] < 10 and not (kind in ("entities", "machines") and places.get(kind)):
            continue
        types = entry["types"]
        mods_named = sorted({names.get(t.split(":")[0], t.split(":")[0]) for t, _ in types if not t.startswith("minecraft:")})
        detail = ""
        if types:
            detail = "Costing most: " + ", ".join(f"{_name(t)} ({s}% of the tick)" for t, s in types) + "."
        findings.append({"kind": kind, "share": entry["share"], "title": f"{entry['words']}: {entry['share']}% of each tick",
                         "detail": detail, "places": [_place(p) for p in places.get(kind, [])],
                         "tip": TIPS.get(kind, ""), "mods": mods_named})
    for kind in ("entities", "machines"):  # the world alone, when there was no profile
        if places.get(kind) and not any(f["kind"] == kind for f in findings):
            words = KINDS["entities" if kind == "entities" else "blockEntities"][1]
            findings.append({"kind": kind, "share": None, "title": f"{words}: lots of them in a few places",
                             "detail": "", "places": [_place(p) for p in places[kind]], "tip": TIPS[kind], "mods": []})
    if findings:
        first = findings[0]
        words = first["title"].split(":")[0]
        cost = f" ({first['share']}% of each tick)" if first["share"] is not None else ""
        where = f" The busiest place is {first['places'][0]}." if first["places"] else ""
        summary = f"The biggest cost: {words[0].lower()}{words[1:]}{cost}.{where}"
    elif tps is not None and tps >= 19.5:
        summary = "It kept up fine while it was being looked at: the lag may come and go (a farm, a big explosion, someone exploring)."
    else:
        summary = ("Nothing in particular stood out: the computer may be too slow or busy with other programs, "
                   "or the server may need more memory (Check my setup).")
    return {"summary": summary, "findings": findings, "tps": tps, "lag_lines": lag_lines}


def load_report(cfg) -> dict | None:
    try:
        return json.loads((cfg.state_dir / REPORT_NAME).read_text())
    except (OSError, ValueError):
        return None


class LagFinder:
    """One look (30 seconds of profiling, then the world's files), run in its own thread."""

    def __init__(self, daemon, automatic: bool = False, seconds: int = PROFILE_SECONDS):
        self.d = daemon
        self.automatic = automatic
        self.seconds = seconds
        self.state = "running"
        self.step = "Getting ready…"
        self.progress: float | None = None
        self.result: dict | None = None
        self.cancel = threading.Event()
        self.started = time.time()

    def start(self) -> "LagFinder":
        threading.Thread(target=self.run, daemon=True, name="lag-finder").start()
        return self

    def to_dict(self) -> dict:
        return {"state": self.state, "step": self.step, "progress": self.progress, "result": self.result,
                "automatic": self.automatic, "elapsed": int(time.time() - self.started)}

    def run(self) -> dict | None:
        from .properties import read_properties
        m, proc = self.d.m, self.d.proc
        try:
            if proc is None or not proc.running:
                raise RuntimeError("the server isn't running")
            sd = m.server_dir
            mark = proc.line_count
            began = time.time()
            self.step = "Watching where the time goes…"
            proc.send("debug start")
            profiled = False
            try:
                end = time.monotonic() + self.seconds
                while time.monotonic() < end:
                    if self.cancel.wait(1) or not proc.running:
                        raise InterruptedError
                    self.progress = round(1 - (end - time.monotonic()) / self.seconds, 2) * 0.8
            finally:
                if proc.running:
                    proc.send("debug stop")
                    profiled = True
            self.step = "Looking through the world…"
            self.progress = 0.85
            proc.send("save-all")
            time.sleep(3)
            text = ""
            for _ in range(10):  # (the dump is written a moment after /debug stop)
                text = read_profile(sd, began)
                if text or not profiled:
                    break
                time.sleep(1)
            new = min(proc.line_count - mark, len(proc.lines))
            lines = list(proc.lines)[len(proc.lines) - new:] if new else []
            tps = None
            for line in lines:
                if (s := _TICKS_PER_SECOND.search(line)) and _STOPPED.search(line):
                    tps = round(min(20.0, float(s.group(1))), 1)
            lag_lines = sum(1 for line in lines if _LAG_LINE.search(line))
            level = read_properties(sd / "server.properties").get("level-name") or "world"
            places = hotspots(sd / level)
            result = report(summarize_profile(parse_profile(text)), places, tps, lag_lines, m.lock.mods)
            result.update({"profiled": bool(text), "finished": time.time(), "automatic": self.automatic,
                           "seconds": self.seconds})
            if not text:
                result["note"] = ("Minecraft's profiler gave nothing this time (some server types switch it off), "
                                  "so this comes from the world's files only.")
            self._clean(sd, began)
            m.config.state_dir.mkdir(parents=True, exist_ok=True)
            (m.config.state_dir / REPORT_NAME).write_text(json.dumps(result, indent=1))
            self.result = result
            self.state = "done"
        except InterruptedError:
            self.state = "cancelled"
        except Exception as e:
            if not isinstance(e, (RuntimeError, OSError)):
                log.exception("the lag finder failed")
            self.result = {"error": str(e)}
            self.state = "failed"
        finally:
            self.step, self.progress = "", None
        return self.result

    @staticmethod
    def _clean(server_dir: Path, since: float) -> None:
        """The profiler's own dump files are only needed for the report."""
        folder = server_dir / "debug"
        if folder.is_dir():
            for p in folder.iterdir():
                try:
                    if p.is_file() and p.stat().st_mtime >= since - 1 and p.name.startswith("profile-results"):
                        p.unlink()
                except OSError:
                    pass

