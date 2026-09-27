"""How fast the server keeps up: ticks per second (TPS, 20 is perfect) and milliseconds per
tick (MSPT, under 50 keeps up). Asked from the server's console with the command its loader
understands, only while someone is looking (the Dashboard), and at most every little while.
"""

from __future__ import annotations

import re
import time
from collections import deque


SPARK_URL = re.compile(r"https://spark\.lucko\.me/[A-Za-z0-9]+")
_TICK_QUERY = re.compile(r"Average time per tick:\s*([\d.]+)\s*ms", re.I)                     # vanilla 1.20.3+
_PAPER_TPS = re.compile(r"TPS from last 1m, 5m, 15m:\s*\*?([\d.]+)", re.I)                      # Paper /tps
_FORGE = re.compile(r"Overall\s*:?.*?Mean tick time:\s*([\d.]+)\s*ms", re.I)                    # Forge
_NEOFORGE = re.compile(r"Overall\s*:?\s*([\d.]+)\s*TPS\s*\(([\d.]+)\s*ms/tick\)", re.I)         # NeoForge
_COLOUR = re.compile(r"§.")


def command_for(loader: str, minecraft: str) -> str | None:
    """The console command that reports tick timing, or None for versions that have none."""
    if loader == "paper":
        return "tps"
    if loader == "forge":
        return "forge tps"
    if loader == "neoforge":
        return "neoforge tps"
    m = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?(?:$|[-_ ])", minecraft or "")
    if not m:
        return None  # snapshots and the like
    new_enough = tuple(int(x or 0) for x in m.groups()) >= (1, 20, 3)
    return "tick query" if new_enough else None  # vanilla, Fabric, Quilt


def parse(lines: list[str]) -> dict | None:
    """``{"tps", "mspt"}`` from the command's output (either may be None), or None."""
    for raw in lines:
        line = _COLOUR.sub("", raw)
        if m := _NEOFORGE.search(line):
            return {"tps": min(20.0, float(m.group(1))), "mspt": float(m.group(2))}
        if m := _TICK_QUERY.search(line) or _FORGE.search(line):
            mspt = float(m.group(1))
            return {"tps": round(min(20.0, 1000 / mspt), 1) if mspt > 0 else 20.0, "mspt": mspt}
        if m := _PAPER_TPS.search(line):
            return {"tps": min(20.0, float(m.group(1))), "mspt": None}
    return None


def verdict(tps: float | None) -> tuple[str, str]:
    """(ok|warn|bad, words) for a TPS value."""
    if tps is None:
        return "info", "not measured"
    if tps >= 19.5:
        return "ok", "running smoothly"
    if tps >= 17:
        return "warn", "a little behind: players may notice small hiccups"
    return "bad", "falling behind: players will feel lag"


class Meter:
    """Recent samples for one server (kept in memory, about an hour's worth)."""

    MIN_GAP = 20  # seconds between asks, however many pages are open

    def __init__(self):
        self.samples: deque[dict] = deque(maxlen=120)
        self.last_try = 0.0

    def sample(self, proc, loader: str, minecraft: str) -> dict | None:
        now = time.time()
        if now - self.last_try < self.MIN_GAP:
            return self.samples[-1] if self.samples else None
        self.last_try = now
        cmd = command_for(loader, minecraft)
        if not cmd or proc is None or not proc.running:
            return None
        got = proc.ask(cmd, parse, timeout=4)
        if got:
            got = {**got, "time": now}
            self.samples.append(got)
        return got
