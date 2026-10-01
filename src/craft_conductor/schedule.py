"""Schedules: restart the server and make backups at set times.

People pick from simple choices in the web UI ("every night at 4:00", "every 6 hours"); what's
stored is a standard 5-field cron expression (minute hour day-of-month month day-of-week), so
power users can write their own in the Settings page or craft-conductor.toml. Times are this computer's
local time.
"""

from __future__ import annotations

import datetime as dt
import re

FIELDS = (("minute", 0, 59), ("hour", 0, 23), ("day of the month", 1, 31), ("month", 1, 12), ("day of the week", 0, 7))
NAMES = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
         "nov": 11, "dec": 12, "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
DAYS = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")


class CronError(ValueError):
    pass


def _values(part: str, lo: int, hi: int, name: str) -> set[int]:
    out: set[int] = set()
    for item in part.split(","):
        m = re.fullmatch(r"(\*|[a-z0-9]+(?:-[a-z0-9]+)?)(?:/(\d+))?", item.strip().lower())
        if not m:
            raise CronError(f"can't read {item!r} in the {name}")
        base, step = m.group(1), int(m.group(2) or 1)
        if step < 1:
            raise CronError(f"the step in the {name} must be 1 or more")
        if base == "*":
            a, b = lo, hi
        else:
            ends = [NAMES.get(x, x) for x in base.split("-")]
            try:
                a, b = int(ends[0]), int(ends[-1])
            except ValueError:
                raise CronError(f"can't read {item!r} in the {name}") from None
            if m.group(2) and len(ends) == 1:
                b = hi  # "5/15": from 5, every 15
        if not (lo <= a <= hi and lo <= b <= hi and a <= b):
            raise CronError(f"the {name} must be between {lo} and {hi} (got {item!r})")
        out.update(range(a, b + 1, step))
    return out


class Cron:
    """A parsed cron expression; ``matches(time)`` is True in the minutes it names."""

    def __init__(self, text: str):
        parts = text.split()
        if len(parts) != 5:
            raise CronError("a schedule has 5 parts: minute hour day-of-month month day-of-week (e.g. 0 4 * * *)")
        self.text = " ".join(parts)
        self.sets = [_values(p, lo, hi, name) for p, (name, lo, hi) in zip(parts, FIELDS)]
        if 7 in self.sets[4]:  # 7 is Sunday too
            self.sets[4] = (self.sets[4] - {7}) | {0}
        self.any_dom, self.any_dow = parts[2] == "*", parts[4] == "*"

    def matches(self, t: dt.datetime) -> bool:
        minute, hour, dom, month, dow = self.sets
        if t.minute not in minute or t.hour not in hour or t.month not in month:
            return False
        weekday = (t.weekday() + 1) % 7  # Monday=0 -> Sunday=0
        day_ok, week_ok = t.day in dom, weekday in dow
        if self.any_dom or self.any_dow:  # classic cron: if both are restricted, either one matches
            return day_ok and week_ok
        return day_ok or week_ok

    def next_after(self, t: dt.datetime, limit_days: int = 400) -> dt.datetime | None:
        t = t.replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
        end = t + dt.timedelta(days=limit_days)
        while t < end:
            if t.month not in self.sets[3]:
                t = (t.replace(day=1, hour=0, minute=0) + dt.timedelta(days=32)).replace(day=1)
                continue
            if self.matches(t):
                return t
            if t.hour not in self.sets[1]:
                t = t.replace(minute=0) + dt.timedelta(hours=1)
                continue
            t += dt.timedelta(minutes=1)
        return None


def parse(text: str) -> Cron | None:
    """``""`` (off) or a cron expression; raises CronError with a plain explanation."""
    text = (text or "").strip()
    return Cron(text) if text else None


def describe(text: str) -> str:
    """The schedule in words, for the ones the web UI offers; the expression itself otherwise."""
    text = " ".join((text or "").split())
    if not text:
        return "off"
    m = re.fullmatch(r"(\d+) (\d+) \* \* \*", text)
    if m:
        return f"every day at {int(m.group(2))}:{int(m.group(1)):02d}"
    m = re.fullmatch(r"(\d+) (\d+) \* \* (\d)", text)
    if m and int(m.group(3)) <= 7:
        return f"every {DAYS[int(m.group(3)) % 7]} at {int(m.group(2))}:{int(m.group(1)):02d}"
    m = re.fullmatch(r"(\d+) \*/(\d+) \* \* \*", text)
    if m:
        n = int(m.group(2))
        return "every hour" if n == 1 else f"every {n} hours"
    if re.fullmatch(r"(\d+) \* \* \* \*", text):
        return "every hour"
    return text


def due(expr: str, last: dt.datetime | None, now: dt.datetime) -> bool:
    """Whether a schedule names a minute after ``last`` and up to ``now`` (so a minute isn't
    missed when the loop wakes a little late, and isn't run twice)."""
    cron = parse(expr)
    if cron is None:
        return False
    now = now.replace(second=0, microsecond=0)
    if last is None:
        return cron.matches(now)
    last = last.replace(second=0, microsecond=0)
    if now <= last:
        return False
    if (now - last) > dt.timedelta(minutes=10):  # asleep for a while: only the current minute
        return cron.matches(now)
    t = last + dt.timedelta(minutes=1)
    while t <= now:
        if cron.matches(t):
            return True
        t += dt.timedelta(minutes=1)
    return False
