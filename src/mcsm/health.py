"""Warnings about the computer the servers run on: little disk space left where the servers and
backups live, the CPU busy for minutes on end, memory running out, or more memory given to the
running servers than the computer has.

The hub looks every minute (Hub.run). A warning shows on the page while it lasts (``/api/hub``'s
"health") and is sent once, to the phones with notifications on and the log, when it starts; it's
sent again only after it has cleared, and not more often than every few hours.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import sys
import time
from collections import deque
from pathlib import Path

log = logging.getLogger(__name__)

DISK_BAD_GB, DISK_WARN_GB = 3, 10
CPU_BUSY = 0.9          # the whole computer, averaged over CPU_MINUTES
CPU_MINUTES = 5
MEMORY_LOW_GB = 0.5
RENOTIFY = 6 * 3600


# ------------------------------------------------------------ measuring
def _cpu_times() -> tuple[float, float] | None:
    """(busy, total) CPU time so far, for the whole computer; None where it can't be read."""
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/stat") as f:
                fields = [float(x) for x in f.readline().split()[1:]]
            idle = fields[3] + (fields[4] if len(fields) > 4 else 0)  # idle + iowait
            return sum(fields) - idle, sum(fields)
        if sys.platform == "win32":
            import ctypes
            idle, kernel, user = (ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong())
            if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
                return None
            total = kernel.value + user.value  # (kernel time includes idle time)
            return total - idle.value, total
    except (OSError, ValueError, IndexError, AttributeError):
        return None
    return None


def memory_available_gb() -> float | None:
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/meminfo") as f:
                m = re.search(r"^MemAvailable:\s+(\d+) kB", f.read(), re.M)
            return int(m.group(1)) / 1024 ** 2 if m else None
        if sys.platform == "win32":
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.ullAvailPhys / 1024 ** 3
    except (OSError, ValueError, AttributeError):
        return None
    return None  # (macOS: the memory the servers are given is checked instead)


def disk_free(paths: list[Path]) -> list[tuple[Path, float]]:
    """Free space (GB) on each drive holding one of ``paths`` (once per drive)."""
    seen, out = set(), []
    for p in paths:
        p = Path(p)
        while not p.exists() and p.parent != p:
            p = p.parent
        try:
            dev = os.stat(p).st_dev
            if dev in seen:
                continue
            seen.add(dev)
            out.append((p, shutil.disk_usage(p).free / 1024 ** 3))
        except OSError:
            continue
    return out


# -------------------------------------------------------------- watching
class Health:
    def __init__(self, hub):
        self.hub = hub
        self.cpu = deque(maxlen=CPU_MINUTES)   # the whole computer's busy share, a sample a minute
        self._last_times = None
        self.warnings: list[dict] = []
        self._sent: dict[str, float] = {}      # warning id -> when it was last sent

    def _cpu_sample(self) -> float | None:
        if not sys.platform.startswith("linux") and sys.platform != "win32":
            try:  # macOS: the load average, per core
                return min(1.0, os.getloadavg()[0] / (os.cpu_count() or 1))
            except (OSError, AttributeError):
                return None
        now = _cpu_times()
        last, self._last_times = self._last_times, now
        if not now or not last or now[1] <= last[1]:
            return None
        return max(0.0, min(1.0, (now[0] - last[0]) / (now[1] - last[1])))

    def check(self) -> list[dict]:
        """Look now; returns the current warnings (and sends the new ones)."""
        found = []
        daemons = list(self.hub.daemons.values())
        places = [d.m.config.root for d in daemons] + [d.m.config.backups.dir for d in daemons]
        for where, free in disk_free(places or [self.hub.home]):
            if free < DISK_WARN_GB:
                bad = free < DISK_BAD_GB
                found.append({"id": f"disk:{where}", "level": "bad" if bad else "warn",
                              "title": f"Only {free:.1f} GB of disk space left",
                              "detail": f"On the drive with {where}. " + ("Backups, updates and the world itself may fail to save. "
                                        if bad else "Backups and updates need room. ") +
                                        "Delete old backups or exports, or move backups to another drive (Settings → Backup copies)."})
        busy = self._cpu_sample()
        if busy is not None:
            self.cpu.append(busy)
        if len(self.cpu) == self.cpu.maxlen and sum(self.cpu) / len(self.cpu) >= CPU_BUSY:
            found.append({"id": "cpu", "level": "warn", "title": f"The computer's CPU has been {round(100 * sum(self.cpu) / len(self.cpu))}% busy for {CPU_MINUTES} minutes",
                          "detail": "Servers may lag. See each server's Performance (Dashboard) and Find what's causing lag, "
                                    "limit a server's CPU cores or lower its priority (Settings), or stop a server."})
        free_mem = memory_available_gb()
        if free_mem is not None and free_mem < MEMORY_LOW_GB and any(d.proc and d.proc.running for d in daemons):
            found.append({"id": "memory", "level": "bad", "title": f"The computer is almost out of memory ({free_mem:.1f} GB free)",
                          "detail": "Servers may slow right down or crash. Give servers less memory (Settings), or stop one."})
        plan = self.hub.memory_plan() if hasattr(self.hub, "memory_plan") else None
        if plan and plan.get("total_gb") and plan["running_gb"] > plan["total_gb"] - 1.5 and len(plan["running"]) > 1:
            found.append({"id": "servers-memory", "level": "warn",
                          "title": f"The running servers are given {plan['running_gb']} GB of memory; this computer has {plan['total_gb']} GB",
                          "detail": "Too many servers for this computer at once: give them less memory (Settings), or stop one."})
        self._send(found)
        self.warnings = found
        return found

    def _send(self, found: list[dict]) -> None:
        now = time.time()
        before = {w["id"] for w in self.warnings}
        for w in found:
            if w["id"] in before or now - self._sent.get(w["id"], 0) < RENOTIFY:
                continue  # (still the same problem, or told recently)
            self._sent[w["id"]] = now
            log.warning("%s. %s", w["title"], w["detail"])
            push = getattr(self.hub, "push", None)
            if push is not None:
                try:
                    push.notify("Craft Conductor", w["title"], url="/#servers", tag=re.sub(r"[^A-Za-z0-9_-]", "_", w["id"])[:32],
                                kind="computer")
                except Exception:
                    log.debug("couldn't send the warning to phones", exc_info=True)
