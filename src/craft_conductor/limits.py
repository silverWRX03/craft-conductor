"""Limits per server: how many CPU cores it may use, and a lower priority so the rest of the
computer comes first; and a check that the servers running together fit in its memory.

Cores are set with the operating system's CPU affinity: on Linux in the new process before Java
starts (so every thread Java makes inherits it), on Windows on the process (which covers all its
threads). macOS has no way to pin a process to cores, so only the priority applies there.
Priority is ``nice`` 10 on Linux and macOS, "below normal" on Windows.
"""

from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger(__name__)

PRIORITIES = ("normal", "low")
LOW_NICE = 10
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
HEADROOM_GB = 1.5  # left for the computer itself when adding up what the servers are given


def cpu_count() -> int:
    try:
        return len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        return os.cpu_count() or 1


def can_pin_cores() -> bool:
    return hasattr(os, "sched_setaffinity") or sys.platform == "win32"


def chosen_cores(cores: int) -> list[int]:
    """The cores a server limited to ``cores`` runs on: the last ones this program may use (the
    first ones are busiest with everything else)."""
    try:
        allowed = sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        allowed = list(range(os.cpu_count() or 1))
    return allowed[-cores:] if 0 < cores < len(allowed) else allowed


def popen_options(cores: int, priority: str) -> dict:
    """Extra arguments for subprocess.Popen that start the server with these limits."""
    if cores <= 0 and priority != "low":
        return {}
    if sys.platform == "win32":
        return {"creationflags": BELOW_NORMAL_PRIORITY_CLASS} if priority == "low" else {}
    pin = hasattr(os, "sched_setaffinity") and cores > 0
    cpus = set(chosen_cores(cores)) if pin else None

    def limit():  # (runs in the new process, before Java: keep it to plain system calls)
        if cpus:
            os.sched_setaffinity(0, cpus)
        if priority == "low":
            os.nice(LOW_NICE)
    return {"preexec_fn": limit}


def after_start(pid: int, cores: int) -> None:
    """Windows: pin the started process to its cores (the whole process, every thread)."""
    if sys.platform != "win32" or cores <= 0:
        return
    import ctypes
    mask = 0
    for c in chosen_cores(cores):
        mask |= 1 << c
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x0200 | 0x0400, False, pid)  # PROCESS_SET_INFORMATION | QUERY_INFORMATION
    if not handle:
        log.warning("couldn't limit the server to %d core(s)", cores)
        return
    try:
        if not kernel32.SetProcessAffinityMask(handle, ctypes.c_size_t(mask)):
            log.warning("couldn't limit the server to %d core(s)", cores)
    finally:
        kernel32.CloseHandle(handle)


def check(cores: int, priority: str) -> tuple[int, str]:
    """Validated settings (ValueError says what's wrong)."""
    try:
        cores = int(cores)
    except (TypeError, ValueError):
        raise ValueError("cpu_cores must be a whole number (0 = all of them)") from None
    if cores < 0 or cores > max(cpu_count(), 256):
        raise ValueError(f"cpu_cores must be between 0 (all) and {cpu_count()}")
    if priority not in PRIORITIES:
        raise ValueError(f"priority must be one of {', '.join(PRIORITIES)}")
    return cores, priority


def memory_fits(given_gb: list[float], adding_gb: float, total_gb: float | None) -> dict:
    """Whether a server given ``adding_gb`` fits next to the running ones (``given_gb``), leaving
    HEADROOM_GB for the computer itself."""
    running = round(sum(given_gb), 1)
    if not total_gb:
        return {"fits": True, "running_gb": running, "total_gb": None, "after_gb": round(running + adding_gb, 1)}
    after = round(running + adding_gb, 1)
    return {"fits": after <= total_gb - HEADROOM_GB, "running_gb": running, "total_gb": round(total_gb, 1),
            "after_gb": after, "free_gb": round(max(0.0, total_gb - HEADROOM_GB - running), 1)}
