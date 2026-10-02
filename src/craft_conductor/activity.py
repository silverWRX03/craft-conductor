"""Player activity: who played when, when the server is busy, and the quietest time for a restart.

Every visit (a player joining, until they leave or the server stops) is one line in
``<state>/activity.jsonl``: ``{"name", "start", "end"}`` (Unix times). Lines older than
``KEEP_DAYS`` are dropped once a day. Players still online count up to now.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

FILE = "activity.jsonl"
KEEP_DAYS = 90
MIN_DAYS = 3          # of history before a restart time is suggested
QUIET_HOUR = 4        # among equally quiet hours, the one nearest 4 in the morning
CACHE_SECONDS = 60
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class Activity:
    def __init__(self, state_dir: Path | None):
        self.path = Path(state_dir) / FILE if state_dir is not None else None  # (None: kept in memory only)
        self.lock = threading.Lock()
        self.online: dict[str, float] = {}   # name -> when they joined
        self._pruned = 0.0
        self._cache: tuple | None = None     # (key, summary)

    # ------------------------------------------------------------- recording
    def joined(self, name: str, now: float | None = None) -> None:
        with self.lock:
            self.online.setdefault(name, now or time.time())

    def left(self, name: str, now: float | None = None) -> None:
        with self.lock:
            start = self.online.pop(name, None)
            if start is not None:
                self._write([(name, start, now or time.time())])

    def all_left(self, now: float | None = None) -> None:
        """The server stopped (or crashed at ``now``): everyone's visit ends."""
        with self.lock:
            now = now or time.time()
            items = [(n, min(s, now), now) for n, s in self.online.items()]
            self.online.clear()
            if items:
                self._write(items)

    def _write(self, items: list[tuple[str, float, float]]) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                for name, start, end in items:
                    if end - start >= 1:
                        f.write(json.dumps({"name": name, "start": round(start), "end": round(end)}) + "\n")
            if time.time() - self._pruned > 86400:
                self._prune()
        except OSError as e:
            log.warning("couldn't note player activity: %s", e)

    def _prune(self) -> None:
        self._pruned = time.time()
        cutoff = time.time() - KEEP_DAYS * 86400
        rows = self._read()
        keep = [r for r in rows if r["end"] >= cutoff]
        if len(keep) == len(rows):
            return
        tmp = self.path.with_name(FILE + ".tmp")
        tmp.write_text("".join(json.dumps(r) + "\n" for r in keep), encoding="utf-8")
        os.replace(tmp, self.path)

    def _read(self) -> list[dict]:
        rows = []
        try:
            text = self.path.read_text(encoding="utf-8") if self.path else ""
        except OSError:
            return rows
        for line in text.splitlines():
            try:
                r = json.loads(line)
                rows.append({"name": str(r["name"])[:16], "start": float(r["start"]), "end": float(r["end"])})
            except (ValueError, KeyError, TypeError):
                continue  # (a line cut short by a power cut)
        return rows

    # ---------------------------------------------------------------- reading
    def visits(self, since: float, now: float | None = None) -> list[dict]:
        """Visits that overlap [since, now], oldest first; ones still going end ``now``."""
        now = now or time.time()
        with self.lock:
            rows = [r for r in self._read() if r["end"] >= since]
            rows += [{"name": n, "start": s, "end": now, "online": True} for n, s in self.online.items()]
        return sorted(rows, key=lambda r: r["start"])

    def summary(self, days: int = 30, now: float | None = None) -> dict:
        """Who played and for how long, how busy each hour of the week is, and the quietest hour."""
        now = now or time.time()
        days = max(1, min(KEEP_DAYS, int(days)))
        try:
            stat = self.path.stat() if self.path else None
        except OSError:
            stat = None
        key = (days, stat.st_mtime_ns if stat else 0, stat.st_size if stat else 0,
               tuple(sorted(self.online.items())), int(now // CACHE_SECONDS))
        if self._cache and self._cache[0] == key:
            return self._cache[1]
        result = summarise(self.visits(now - days * 86400, now), days, now)
        self._cache = (key, result)
        return result


def _hours(start: float, end: float):
    """(weekday, hour, seconds) pieces of [start, end] in local time."""
    t = start
    while t < end:
        d = dt.datetime.fromtimestamp(t)
        top = (d.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)).timestamp()
        piece = min(end, top) - t
        if piece <= 0:  # (a clock change)
            top = t + 3600 - (t % 3600)
            piece = min(end, top) - t
        yield d.weekday(), d.hour, piece
        t += piece


def summarise(visits: list[dict], days: int, now: float) -> dict:
    since = now - days * 86400
    players: dict[str, dict] = {}
    busy = [[0.0] * 24 for _ in range(7)]
    for v in visits:
        start, end = max(v["start"], since), min(v["end"], now)
        if end < start:
            continue
        # A just-joined player can have exactly the same start/end timestamp on clocks with
        # coarse resolution (notably Windows). They must still appear as online immediately.
        p = players.setdefault(v["name"], {"name": v["name"], "seconds": 0.0, "visits": 0, "last_seen": 0.0, "online": False})
        p["visits"] += 1
        p["last_seen"] = max(p["last_seen"], end)
        p["online"] = p["online"] or bool(v.get("online"))
        if end == start:
            continue
        p["seconds"] += end - start
        for wd, hr, secs in _hours(start, end):
            busy[wd][hr] += secs
    first = max(since, min((v["start"] for v in visits), default=now))
    history_days = (now - first) / 86400
    # How many times each hour of the week happened since the first visit: the average's divisor.
    seen = [[0] * 24 for _ in range(7)]
    for wd, hr, secs in _hours(first, now):
        seen[wd][hr] += 1 if secs >= 1800 else 0
    week = [[round(busy[wd][hr] / 3600 / seen[wd][hr], 2) if seen[wd][hr] else 0.0 for hr in range(24)] for wd in range(7)]
    by_hour = []
    for hr in range(24):
        n = sum(seen[wd][hr] for wd in range(7))
        by_hour.append(round(sum(busy[wd][hr] for wd in range(7)) / 3600 / n, 3) if n else 0.0)
    quiet = busiest = None
    if visits and history_days >= MIN_DAYS:
        hour = min(range(24), key=lambda h: (by_hour[h], min(abs(h - QUIET_HOUR), 24 - abs(h - QUIET_HOUR))))
        quiet = {"hour": hour, "average": by_hour[hour], "cron": f"0 {hour} * * *"}
        wd, hr = max(((wd, hr) for wd in range(7) for hr in range(24)), key=lambda x: week[x[0]][x[1]])
        if week[wd][hr] > 0:
            busiest = {"weekday": wd, "day": DAYS[wd], "hour": hr, "average": week[wd][hr]}
    return {
        "days": days,
        "history_days": round(history_days, 1),
        "enough": history_days >= MIN_DAYS,
        "players": sorted(({**p, "seconds": round(p["seconds"])} for p in players.values()), key=lambda p: -p["seconds"]),
        "week": week,               # average players online, [Monday..Sunday][hour 0..23], local time
        "by_hour": by_hour,         # the same for each hour of the day, all days together
        "quiet": quiet,             # the quietest hour: a good time for the nightly restart
        "busiest": busiest,
        "recent": [{"name": v["name"], "start": v["start"], "end": v["end"], "online": bool(v.get("online"))}
                   for v in visits[-30:][::-1]],
    }
