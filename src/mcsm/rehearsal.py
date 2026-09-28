"""Update rehearsal: try an update on a copy of the server before doing it for real.

The server folder (world included, with saving paused while it's copied) is copied into
``.mcsm/rehearsal/``. The update is installed on the copy, which then runs for a few minutes on
a private port on this computer (nobody can join it). The report says whether it started and
how long that took, how well it kept up (TPS), and which mods complained in the log. The copy
is deleted afterwards; the real server isn't touched.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import socket
import threading
import time
from pathlib import Path

from . import config as configmod, perf
from .properties import read_properties, write_properties

log = logging.getLogger(__name__)

WATCH_DEFAULT = 3            # minutes the copy runs after it has started
WATCH_MAX = 15
SAMPLE_EVERY = 20            # seconds between TPS readings
MAX_LINES = 50_000           # server output kept for the report
FRESH = 7 * 24 * 3600        # a passing rehearsal lets an automatic update go ahead for a week
REPORT_NAME = "rehearsal.json"
SKIP = ("logs", "crash-reports", "backups", "debug")  # not copied (not needed to run)

_LEVEL = re.compile(r"[/\[ ](WARN|WARNING|ERROR|FATAL|SEVERE)\]|^\s*at\s|\b(Exception|Error):", re.I)
_LAG = re.compile(r"Can't keep up! .*?Running (\d+)ms or (\d+) ticks behind", re.I)
_WORD = re.compile(r"[a-z0-9]+")


class RehearsalError(Exception):
    pass


def folder_size(path: Path) -> int:
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in SKIP]
        for name in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                pass
    return total


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _tokens(mod) -> set[str]:
    """Words a log line about ``mod`` is likely to contain: its name, file name and id."""
    words = set()
    name = mod.name.lower()
    if len(name) >= 4:
        words.add(name)
    stem = re.split(r"[-_+ ]\d|[-_+](?:fabric|forge|neoforge|quilt|paper|purpur|mc)\b", Path(mod.filename).stem.lower())[0]
    if len(stem) >= 4:
        words.add(stem)
    mod_id = mod.key.partition(":")[2].lower()
    if len(mod_id) >= 4 and not mod_id.isupper():
        words.add(mod_id)
    return words


def complaints(lines: list[str], mods) -> dict:
    """Warnings and errors in ``lines``, by the mod they name (``other`` when none), and how often
    the server said it couldn't keep up."""
    names = [(m.name, _tokens(m)) for m in mods]
    by_mod: dict[str, dict] = {}
    other = {"warnings": 0, "errors": 0, "examples": []}
    lag = {"count": 0, "worst_ms": 0}
    for raw in lines:
        line = raw.rstrip()
        if m := _LAG.search(line):
            lag["count"] += 1
            lag["worst_ms"] = max(lag["worst_ms"], int(m.group(1)))
            continue
        hit = _LEVEL.search(line)
        if not hit:
            continue
        error = not re.search(r"WARN", hit.group(0), re.I)
        low = line.lower()
        who = next((n for n, words in names if any(w in low for w in words)), None)
        entry = other if who is None else by_mod.setdefault(who, {"name": who, "warnings": 0, "errors": 0, "examples": []})
        entry["errors" if error else "warnings"] += 1
        if len(entry["examples"]) < 3 and line.strip() not in entry["examples"]:
            entry["examples"].append(line.strip()[:300])
    ranked = sorted(by_mod.values(), key=lambda e: (-e["errors"], -e["warnings"], e["name"]))
    return {"mods": ranked, "other": other, "lag": lag}


def verdict(result: dict) -> tuple[str, str]:
    """(good|warn|bad, words) for a finished rehearsal."""
    if not result.get("started"):
        return "bad", "The update didn't start on the copy: " + (result.get("error") or "see the details")
    if result.get("crashed"):
        return "bad", "The copy started but then stopped by itself: " + (result.get("error") or "see the details")
    errors = sum(m["errors"] for m in result["complaints"]["mods"])
    tps = result.get("tps_avg")
    problems = []
    if errors:
        problems.append(f"{errors} error(s) from mods")
    if tps is not None and tps < 18:
        problems.append(f"it kept up at only {tps} TPS (20 is perfect)")
    if result["complaints"]["lag"]["count"] >= 3:
        problems.append(f"it fell behind {result['complaints']['lag']['count']} times")
    if problems:
        return "warn", "It worked, but " + "; ".join(problems) + ". Look at the details before updating."
    return "good", "It worked: the copy started and ran without problems."


def load_report(cfg) -> dict | None:
    try:
        return json.loads((cfg.state_dir / REPORT_NAME).read_text())
    except (OSError, ValueError):
        return None


def passed(cfg, fingerprint: str) -> bool:
    """A rehearsal of exactly this update worked recently."""
    r = load_report(cfg)
    return bool(r and r.get("fingerprint") == fingerprint and r.get("verdict") in ("good", "warn")
                and time.time() - r.get("finished", 0) < FRESH)


class Rehearsal:
    """One rehearsal of the update to ``target`` (None: the update the Updates page offers)."""

    def __init__(self, daemon, make_manager, target: str | None = None, minutes: int = WATCH_DEFAULT):
        if not 1 <= minutes <= WATCH_MAX:
            raise RehearsalError(f"watch the copy for 1 to {WATCH_MAX} minutes")
        self.id = secrets.token_hex(6)
        self.d = daemon
        self.make_manager = make_manager
        self.target = target
        self.minutes = minutes
        self.root = daemon.m.config.state_dir / "rehearsal" / self.id
        self.state = "running"
        self.step = "Getting ready…"
        self.progress: float | None = None
        self.log: list[str] = []
        self.result: dict | None = None
        self.cancel = threading.Event()
        self.started = time.time()
        self.proc = None
        self.for_fingerprint: str | None = None  # the update an automatic rehearsal is for

    def say(self, text: str) -> None:
        self.log.append(text)
        log.info("rehearsal: %s", text)

    def to_dict(self) -> dict:
        return {"id": self.id, "state": self.state, "step": self.step, "progress": self.progress,
                "log": self.log[-50:], "result": self.result, "minutes": self.minutes,
                "elapsed": int(time.time() - self.started)}

    def close(self) -> None:
        """Stop now (mcsm is quitting): the copy's server doesn't outlive mcsm."""
        self.cancel.set()
        proc = self.proc
        if proc is not None and proc.running:
            proc.stop(30)

    def _check_cancel(self) -> None:
        if self.cancel.is_set():
            raise InterruptedError

    # ------------------------------------------------------------ steps
    def _copy(self) -> None:
        m = self.d.m
        cfg = m.config
        size = folder_size(m.server_dir)
        free = shutil.disk_usage(cfg.state_dir if cfg.state_dir.exists() else cfg.root).free
        if free < size * 1.2 + 1_000_000_000:
            raise RehearsalError(f"not enough free disk space for a copy of the server ({size / 1e9:.1f} GB "
                                 f"needed, {free / 1e9:.1f} GB free)")
        self.step = "Copying the server and its world…"
        self.say(f"Copying the server ({size / 1e9:.2f} GB)…")
        proc = self.d.proc if self.d.proc and self.d.proc.running else None
        if proc:  # save everything, and keep the world files still while they're copied
            proc.send("save-off")
            proc.send("save-all flush")
            time.sleep(5)
        try:
            shutil.copytree(m.server_dir, self.root / "server", symlinks=True,
                            ignore=lambda d, names: [n for n in names if n in SKIP] if Path(d) == m.server_dir else [])
        finally:
            if proc and proc.running:
                proc.send("save-on")
        for name in (configmod.CONFIG_NAME, "mcsm.lock.json"):
            if (cfg.root / name).is_file():
                shutil.copy2(cfg.root / name, self.root / name)
        path = self.root / configmod.CONFIG_NAME
        configmod.set_value(path, "server", "dir", '"server"')
        configmod.set_value(path, "backups", "dir", '"backups"')
        configmod.set_value(path, "backups", "keep", "1")
        # Java that's already downloaded is used again rather than fetched a second time.
        java = cfg.state_dir / "java"
        if java.is_dir():
            target = self.root / configmod.STATE_DIR / "java"
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.symlink(java, target, target_is_directory=True)
            except OSError:
                shutil.copytree(java, target, symlinks=True)
        # Private: only this computer can reach it, and no remote console.
        write_properties(self.root / "server" / "server.properties", {
            "server-ip": "127.0.0.1", "server-port": str(_free_port()), "enable-rcon": "false",
            "enable-query": "false", "motd": "mcsm update rehearsal"})

    def _manager(self):
        from .setup import total_ram_gb
        from .doctor import server_memory_gb
        m = self.make_manager(configmod.load(self.root))
        m.notifier.discord_webhook = ""  # nobody needs to hear about the copy
        m.config.backups.copy_to = None
        m.echo = False
        # Two servers at once: leave the real one its memory.
        if self.d.proc and self.d.proc.running:
            mine = server_memory_gb(m.config.server.memory)
            total = total_ram_gb() or 0
            spare = int(total - mine - 2) if total else mine
            if total and spare < mine:
                smaller = max(2, spare)
                m.config.server.memory = f"{smaller}G"
                self.memory_note = (f"The copy ran with {smaller} GB of memory (the server has {mine:g} GB) because the "
                                    "real server was running too; it may have been slower than the real update will be.")
        return m

    def _watch(self, proc, loader: str, minecraft: str) -> dict:
        cmd = perf.command_for(loader, minecraft)
        samples: list[dict] = []
        end = time.monotonic() + self.minutes * 60
        next_sample = time.monotonic() + 10  # (the first seconds are always busy)
        total = self.minutes * 60
        while time.monotonic() < end:
            self._check_cancel()
            if not proc.running:
                return {"samples": samples, "crashed": True}
            left = end - time.monotonic()
            self.progress = round(1 - left / total, 3)
            self.step = f"Watching the copy run ({int(left // 60)}:{int(left % 60):02d} left)…"
            if cmd and time.monotonic() >= next_sample:
                got = proc.ask(cmd, perf.parse, timeout=4)
                if got:
                    samples.append(got)
                next_sample = time.monotonic() + SAMPLE_EVERY
            time.sleep(1)
        return {"samples": samples, "crashed": False}

    def run(self) -> dict | None:
        """Run it (in this thread): the result is also kept in ``.mcsm/rehearsal.json``."""
        from .diagnose import diagnose
        self.memory_note = ""
        m = self.d.m
        result: dict = {"started": False, "crashed": False, "error": "", "from": m.lock.minecraft}
        try:
            self._copy()
            self._check_cancel()
            self.step = "Working out the update…"
            rm = self._manager()
            decision, changes = rm.check(self.target, retry_failed=True)
            if decision.plan is None or changes is None or changes.empty:
                raise RehearsalError("there's no update to rehearse" if decision.plan else "no update can be installed yet")
            plan = decision.plan
            result.update({"to": plan.minecraft, "fingerprint": plan.fingerprint, "changes": changes.summary(),
                           "target": self.target})
            self.say(f"Installing the update on the copy: {', '.join(changes.summary()[:3])}")
            self.step = "Installing the update on the copy…"
            self._check_cancel()
            began = time.time()
            lines: list[str] = []  # everything the copy says, from its first line

            def keep(line: str) -> None:
                if len(lines) < MAX_LINES:
                    lines.append(line)
            rm.on_line = keep
            rm.on_process = lambda p: setattr(self, "proc", p)  # (known from its launch, to stop it if need be)
            applied = rm.apply(plan, restart=True, make_backup=False)
            if not applied.ok or applied.process is None:
                if applied.process is not None and applied.process.running:
                    applied.process.stop(30)
                diag = rm.last_diagnosis.to_dict() if rm.last_diagnosis else None
                result["error"] = ((diag or {}).get("summary") or applied.message.splitlines()[0])[:400]
                result["diagnosis"] = diag
                self.say("✗ The update didn't start on the copy.")
            else:
                proc = applied.process
                result["started"] = True
                result["start_seconds"] = round(time.time() - began, 1)
                self.say(f"✓ It started ({result['start_seconds']} s including the install). Watching it for "
                         f"{self.minutes} minute(s)…")
                watched = self._watch(proc, rm.config.server.loader, plan.minecraft)
                if watched["crashed"]:
                    result["crashed"] = True
                    diag = diagnose(proc.tail(400), rm.server_dir, rm.lock.mods, since=began)
                    result["diagnosis"] = diag.to_dict()
                    result["error"] = diag.summary or "the server stopped (see the last lines)"
                    result["last_lines"] = proc.tail(15)
                    self.say("✗ The copy stopped by itself.")
                tps = [s["tps"] for s in watched["samples"] if s.get("tps") is not None]
                mspt = [s["mspt"] for s in watched["samples"] if s.get("mspt") is not None]
                result["tps_avg"] = round(sum(tps) / len(tps), 1) if tps else None
                result["tps_min"] = round(min(tps), 1) if tps else None
                result["mspt_avg"] = round(sum(mspt) / len(mspt), 1) if mspt else None
                result["mspt_max"] = round(max(mspt), 1) if mspt else None
                if proc.running:
                    self.step = "Stopping the copy…"
                    proc.stop(rm.config.server.stop_timeout)
            result["complaints"] = complaints(lines, rm.lock.mods if result["started"] else plan.mods)
            result["note"] = self.memory_note
            result["verdict"], result["summary"] = verdict(result)
            result["finished"] = time.time()
            result["minutes"] = self.minutes
            self.result = result
            m.config.state_dir.mkdir(parents=True, exist_ok=True)
            (m.config.state_dir / REPORT_NAME).write_text(json.dumps(result, indent=1))
            self.say(result["summary"])
            self.state = "done"
        except InterruptedError:
            self.say("Stopped.")
            self.state = "cancelled"
        except Exception as e:
            if not isinstance(e, (RehearsalError, OSError)):
                log.exception("the update rehearsal failed")
            self.say(f"The rehearsal couldn't be done: {e}")
            self.result = {**result, "error": str(e), "verdict": "error"}
            self.state = "failed"
        finally:
            if self.proc is not None and self.proc.running:
                self.proc.stop(30)
            self.step, self.progress = "", None
            link = self.root / configmod.STATE_DIR / "java"
            if link.is_symlink():  # (never delete the real Java through the link)
                link.unlink()
            shutil.rmtree(self.root, ignore_errors=True)
            try:
                self.root.parent.rmdir()
            except OSError:
                pass
        return self.result
