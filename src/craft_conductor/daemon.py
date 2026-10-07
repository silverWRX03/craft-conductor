"""``craft-conductor run``: keep the server up and keep it updated.

The daemon owns the server process. It restarts it after crashes, checks for
updates on a schedule (or when ``craft-conductor update`` drops a request file), and applies
them with an in-game countdown. Anything slow (starting, updating, backups, Java
installs) runs as a *job*: one at a time, in the background, so the optional web
UI stays responsive while it happens.
"""

from __future__ import annotations

import logging
import os
import re
import signal
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable

from . import __version__, notice, rollback, selfupdate, setup as setupmod
from .http import HttpError, sha1_file
from .manager import Manager, ManualDownloadRequired
from .process import JOINED, LEFT, READY, ServerProcess, check_command

log = logging.getLogger(__name__)

CRASH_WINDOW = 600      # seconds
MAX_CRASHES = 3         # within CRASH_WINDOW before giving up
EMPTY_RETRY = 300       # seconds between "is anyone online?" checks when waiting for an empty server
SELF_CHECK_INTERVAL = 24 * 3600
MANUAL_WAIT = 12 * 3600  # how long setup waits for mods to be downloaded by hand
MANUAL_POLL = 10         # seconds between looks in the manual-downloads folder while it waits


# Which server the current thread is working for, so that with several servers in one
# process (the hub) each one's activity feed only shows its own messages.
_context = threading.local()


def current_server() -> str | None:
    return getattr(_context, "server", None)


def set_current_server(server_id: str | None) -> None:
    _context.server = server_id


def pid_path(manager: Manager) -> Path:
    return manager.config.state_dir / "daemon.pid"


def request_path(manager: Manager) -> Path:
    return manager.config.state_dir / "update-requested"


def self_update_request_path(manager: Manager) -> Path:
    return manager.config.state_dir / "self-update-requested"


def stop_request_path(manager: Manager) -> Path:
    return manager.config.state_dir / "stop-requested"


def pid_alive(pid: int) -> bool:
    if os.name == "nt":
        # os.kill(pid, 0) would send Ctrl+C on Windows, so ask the kernel instead.
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:  # alive, owned by someone else
        return True


def running_pid(manager: Manager) -> int | None:
    try:
        pid = int(pid_path(manager).read_text().strip())
    except (FileNotFoundError, ValueError):
        return None
    return pid if pid_alive(pid) else None


def request_stop(manager: Manager) -> None:
    """Ask a running daemon to stop the server cleanly and exit (works on every OS)."""
    path = stop_request_path(manager)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stop")


class LogBuffer:
    """A bounded, thread-safe list of entries with increasing sequence numbers."""

    def __init__(self, maxlen: int):
        self._items: deque[dict] = deque(maxlen=maxlen)
        self._seq = 0
        self._lock = threading.Lock()

    def append(self, **item: Any) -> None:
        with self._lock:
            self._seq += 1
            self._items.append({"seq": self._seq, "time": time.time(), **item})

    def since(self, seq: int, limit: int = 1000) -> tuple[list[dict], int]:
        with self._lock:
            items = [i for i in self._items if i["seq"] > seq]
            return items[-limit:], self._seq


class _EventHandler(logging.Handler):
    def __init__(self, buffer: LogBuffer, server_id: str | None = None):
        super().__init__(logging.INFO)
        self.buffer = buffer
        self.server_id = server_id

    def emit(self, record: logging.LogRecord) -> None:
        if self.server_id is not None and current_server() != self.server_id:
            return  # another server's message
        try:
            self.buffer.append(level=record.levelname.lower(), message=record.getMessage())
        except Exception:
            pass


def decision_to_dict(m: Manager, decision, changes) -> dict:
    from . import reminders
    plan = decision.plan
    try:
        lagging = reminders.lagging(m, decision)
    except Exception as e:  # never let this break the update check
        log.debug("couldn't work out which mods are behind: %s", e)
        lagging = None
    return {
        "checked_at": time.time(),
        "installed": m.lock.minecraft,
        "latest": decision.latest,
        "target": plan.minecraft if plan else None,
        "fingerprint": plan.fingerprint if plan else None,
        "loader_version": plan.loader_version if plan else None,
        "up_to_date": bool(plan and (changes is None or changes.empty)),
        "changes": changes.summary() if changes else [],
        "dropped": [{"name": b.name, "reason": b.reason} for b in plan.dropped] if plan else [],
        "manual": [{"name": x.name, "filename": x.filename, "url": x.manual_url, "sha1": x.sha1}
                   for x in m.missing_manual(plan)] if plan else [],
        "blocked": [{
            "minecraft": p.minecraft,
            "loader_missing": p.loader_version is None,
            "loader_reason": p.loader_reason,  # (only when it says more than "no build yet")
            "blockers": [{"name": b.name, "reason": b.reason, "waiting": b.waiting, "chain": b.chain or [b.name],
                          "checked": b.checked, "explain": b.explain(p.minecraft, p.loader),
                          "dependency": b.dependency_of is not None} for b in p.blockers],
        } for p in decision.blocked],
        "lagging": lagging,
    }


class Daemon:
    def __init__(self, manager: Manager, tick: float = 2.0, autostart: bool = True,
                 server_id: str | None = None, hub_managed: bool = False):
        self.m = manager
        self.tick = tick
        #: start the server when craft-conductor starts (``craft-conductor run``); the hub waits for a click instead
        self.autostart = autostart
        self.server_id = server_id
        #: one of several servers run by the hub, which handles the terminal and self-updates
        self.hub_managed = hub_managed
        self.proc: ServerProcess | None = None
        self.stop_requested = threading.Event()
        self.exit_code = 0
        self.crashes: deque[float] = deque()
        self.next_check = 0.0
        self.announced: set[str] = set()

        self.want_running = autostart   # False after a deliberate stop (no crash restarts)
        self.web_enabled = False
        self.ui = None
        self.open_browser = False
        self.console = LogBuffer(3000)
        self.events = LogBuffer(500)
        self.players: set[str] = set()
        from .activity import Activity
        self.activity = Activity(getattr(getattr(manager, "config", None), "state_dir", None))  # who played when (Players page)
        self._sched_last = None  # the last time schedules were looked at
        self._backup_owed = False  # a scheduled backup that came due while another job ran
        self.meter = None        # recent TPS samples (perf.Meter), made when first asked for
        self.crashed_at = None   # when the server last stopped unexpectedly
        self.problem: dict | None = None  # what went wrong last (explain.py), until it starts fine
        self.tunnel_status = None  # the last playit.gg tunnel check (tunnel.check)
        self.started_at: float | None = None
        self.last_check: dict | None = None
        self.waiting_for_manual = False       # setup is paused for mods downloaded by hand
        self._manual_arrived = threading.Event()  # a mod downloaded by hand came in (or stop was pressed)
        self._manual_stop = False
        self.rehearsal = None      # the last update rehearsal (rehearsal.Rehearsal), if any
        self.lag = None            # the last lag finder look (lagfinder.LagFinder), if any
        self._slow = 0             # readings in a row below lagfinder.LAGGY_TPS
        self._next_lag_watch = 0.0
        self._last_lag_look = -1e9
        self.ops = threading.Lock()     # one job at a time
        self.job: dict | None = None
        self.last_job: dict | None = None
        self.updater = selfupdate.Updater()      # a newer craft-conductor release, if any, and how its update stands
        self.next_self_check = time.monotonic() + 30
        self.restart_requested = False           # re-exec craft-conductor after exiting (self-update)
        manager.on_line = self._on_line
        manager.on_process = self._on_process

    # ------------------------------------------------------------ state
    @property
    def state(self) -> str:
        if self.proc and self.proc.running:
            return "running" if self.proc.ready.is_set() else "starting"
        return "stopped"

    def _on_process(self, proc: ServerProcess) -> None:
        self.proc = proc
        self.players.clear()
        self.activity.all_left()  # (anyone still counted from before was gone by now)
        self.started_at = None

    def _on_line(self, line: str) -> None:
        self.console.append(text=line)
        if m := JOINED.search(line):
            self.players.add(m.group(1))
            self.activity.joined(m.group(1))
        elif m := LEFT.search(line):
            self.players.discard(m.group(1))
            self.activity.left(m.group(1))
        elif READY.search(line):
            self.started_at = time.time()

    def send_command(self, command: str) -> None:
        if not self.proc or not self.proc.running:
            raise RuntimeError("the server is not running")
        check_command(command)  # (before it's shown in the console as if it ran)
        self.console.append(text=f"> {command}", source="user")
        self.proc.send(command)

    # ------------------------------------------------------------- jobs
    def submit(self, name: str, fn: Callable[..., Any], *args: Any) -> bool:
        """Run ``fn`` in the background unless another job is running."""
        if not self.ops.acquire(blocking=False):
            return False
        self.job = {"name": name, "started": time.time()}

        def runner():
            set_current_server(self.server_id)
            ok, message = True, ""
            try:
                message = fn(*args) or "done"
            except Exception as e:
                ok, message = False, e.friendly if isinstance(e, HttpError) else str(e)
                report = self.failure_report(name, e)
                log.error("%s failed: %s", name, message)
                if report:
                    message += f"\nThe details are in {report}"
                    log.error("the details are in %s", report)
            finally:
                self.last_job = {"name": name, "ok": ok, "message": message, "finished": time.time()}
                self.job = None
                self.ops.release()
        threading.Thread(target=runner, daemon=True, name=f"job:{name}").start()
        return True

    def start_server(self) -> str:
        if self.proc and self.proc.running:
            self.want_running = True
            return "already running"
        hub = getattr(self, "hub", None)
        if hub is not None:
            hub.check_port(self)
            hub.check_memory(self)
        # An update, restore or world swap cut off half-way (the computer turned off) is put
        # right before the server runs on half-changed files.
        self.m.recover()
        self.want_running = True
        if not self.m.lock.installed:
            log.info("no server installed yet; installing")
            self.check_for_updates(force=True)
            if not self.m.lock.installed:
                raise RuntimeError("no server could be installed yet; see the Updates page")
            if self.proc and self.proc.running:  # the install left it running
                return "installed and started"
        elif not self.autostart and self.m.config.updates.auto_upgrade:
            # Started by hand after sitting stopped: bring it up to date on the way up.
            try:
                self.check_for_updates(allow_stopped=True)
            except Exception as e:
                log.warning("update before starting failed (%s); starting the current version", e)
                self.m.recover()  # (if its backup couldn't be put back, don't start half-updated files)
            if self.proc and self.proc.running:
                return "updated and started"
        try:
            self.m.start_server()
        except Exception:
            self._explain(getattr(self.m, "last_start_lines", None) or [], "start")
            raise
        if self.problem and self.problem.get("kind") == "start":  # (a crash's explanation stays until dismissed)
            self.problem = None
        self.m.notifier.send(f"Server is up (Minecraft {self.m.lock.minecraft})")
        return "started"

    def _explain(self, lines: list[str], kind: str) -> None:
        """Keep what went wrong, in plain words with fix buttons, for the Dashboard."""
        from .explain import explain
        try:
            self.problem = explain(lines, self.m.server_dir, self.m.lock.mods, since=time.time() - 900, kind=kind)
        except Exception:
            log.exception("couldn't work out what went wrong")

    def stop_server(self) -> str:
        self.want_running = False
        if not self.proc or not self.proc.running:
            return "already stopped"
        self.proc.stop(self.m.config.server.stop_timeout)
        self.activity.all_left()
        log.info("server stopped")
        return "stopped"

    def restart_server(self) -> str:
        self.stop_server()
        return self.start_server()

    def backup_now(self, label: str = "manual") -> str:
        """A backup of the server folder, taken safely while it runs (saving paused), then pruned
        and copied to the backup copy folder if one is set."""
        from . import backup
        cfg = self.m.config
        running = self.proc is not None and self.proc.running
        if running:
            self.proc.send("save-off")
            self.proc.send("save-all flush")
            time.sleep(5)
        try:
            path = backup.create(self.m.server_dir, cfg.backups.dir, label, cfg.backups.exclude)
            from . import snapshots
            snapshots.record(path, self.m)
        finally:
            if running and self.proc.running:
                self.proc.send("save-on")
        backup.prune(cfg.backups.dir, cfg.backups.keep)
        # Read it back (it's still in the computer's cache, so this is quick): a backup that
        # can't be restored is worse than none, and it's better to know now.
        from . import areas
        from .properties import read_properties
        level = read_properties(self.m.server_dir / "server.properties").get("level-name") or "world"
        checked = areas.check(cfg.backups.dir, path.name, level)
        if not checked["ok"]:
            log.error("the new backup %s doesn't look right: %s", path.name, checked["detail"])
            self.m.notifier.send(f"The backup {path.name} doesn't look right: {checked['detail']}")
        copied = backup.copy_out(path, cfg.backups.copy_to, cfg.root.name, cfg.backups.copy_keep)
        return f"created {path.name}" + (" (checked)" if checked["ok"] else " (but it doesn't look right: " + checked["detail"] + ")") + \
            (f" (copied to {copied.parent})" if copied else "")

    # --------------------------------------------------- playit.gg tunnel
    TUNNEL_FRESH = 60  # seconds a check is reused for (however many pages ask)

    def tunnel_check(self, force: bool = False) -> dict | None:
        from . import tunnel
        from .properties import read_properties
        address = self.m.config.tunnel_address
        if not address:
            self.tunnel_status = None
            return None
        old = self.tunnel_status
        if old and not force and time.time() - old["checked"] < self.TUNNEL_FRESH and old.get("address") == address:
            return old
        motd = read_properties(self.m.server_dir / "server.properties").get("motd", "")
        new = {**tunnel.check(address, motd, self.state == "running"), "address": address}
        if old and old.get("address") == address and old["status"] != new["status"]:
            if new["status"] in ("down", "wrong") and old["status"] == "ok":
                log.warning("playit.gg tunnel stopped working: %s", new["words"])
                self.m.notifier.send(f"playit.gg tunnel stopped working ({address}). {new['words']}")
            elif new["status"] == "ok" and old["status"] in ("down", "wrong"):
                log.info("playit.gg tunnel works again")
                self.m.notifier.send(f"playit.gg tunnel works again ({address}).")
        self.tunnel_status = new
        return new

    # -------------------------------------------------------- schedules
    def _run_schedules(self) -> None:
        """Scheduled restarts and backups (craft-conductor.toml [schedule], set on the Settings page)."""
        import datetime as dt
        from . import schedule
        now = dt.datetime.now()
        last, self._sched_last = self._sched_last, now
        sch = self.m.config.schedule
        try:
            restart = schedule.due(sch.restart, last, now)
            backup_due = schedule.due(sch.backup, last, now)
        except schedule.CronError as e:  # (checked when saved; a hand-edited file could still be wrong)
            log.warning("schedule: %s", e)
            return
        if backup_due or self._backup_owed:
            # Busy (an update or a rehearsal): made as soon as that's done, not skipped.
            self._backup_owed = not self.submit("scheduled backup", self.backup_now, "scheduled")
        elif restart:
            if not (self.want_running and self.proc is not None and self.proc.running):
                return  # nothing to restart
            if sch.restart_when_empty and self.players:
                log.info("scheduled restart skipped: %d player(s) online", len(self.players))
                return

            def scheduled_restart():
                self.m.countdown(self.proc, "Scheduled restart")
                return self.restart_server()
            self.submit("scheduled restart", scheduled_restart)

    # -------------------------------------------------------- lifecycle
    def run(self, web: bool = False) -> int:
        set_current_server(self.server_id)
        state = self.m.config.state_dir
        state.mkdir(parents=True, exist_ok=True)
        if (pid := running_pid(self.m)) and pid != os.getpid():
            log.error("Craft Conductor is already running (pid %s)", pid)
            return 1
        pid_path(self.m).write_text(str(os.getpid()))
        stop_request_path(self.m).unlink(missing_ok=True)
        handler = _EventHandler(self.events, self.server_id)
        craft_conductor_log = logging.getLogger("craft_conductor")
        craft_conductor_log.addHandler(handler)
        if craft_conductor_log.getEffectiveLevel() > logging.INFO:
            craft_conductor_log.setLevel(logging.INFO)  # the activity feed needs INFO records
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, lambda *_: self.stop_requested.set())
        ui = None
        try:
            if web:
                from .hub import Hub
                from .web import WebUI
                ui = WebUI(Hub.single(self))
                ui.start()
                self.ui = ui
                self.web_enabled = True
                if self.open_browser:
                    import webbrowser
                    threading.Timer(1.0, webbrowser.open, args=(ui.url,)).start()
            if not self.hub_managed:
                self._settle_update()
            return self._loop()
        finally:
            if ui:
                ui.stop()
            if self.proc and self.proc.running:
                log.info("stopping server")
                self.proc.stop(self.m.config.server.stop_timeout)
            self.activity.all_left()
            logging.getLogger("craft_conductor").removeHandler(handler)
            pid_path(self.m).unlink(missing_ok=True)

    def _boot(self) -> str:
        try:
            return self.start_server()
        except Exception:
            self.want_running = False
            if not self.web_enabled:
                # Without the web UI there's nobody to fix things interactively.
                self.exit_code = 1
                self.stop_requested.set()
            raise

    def _notice_accepted(self) -> bool:
        """Accepted for this server, or (a server in the control panel's list) in the control panel,
        which keeps it in its own folder: without that, a server made in the control panel never got
        past this point, so it never checked for updates, ran its schedules or restarted after a crash."""
        hub = getattr(self, "hub", None)
        return notice.accepted(self.m.config.root) or (self.hub_managed and hub is not None and notice.accepted(hub.root))

    def _loop(self) -> int:
        if not self.hub_managed:
            self._forward_console()
        if not self._notice_accepted():
            log.info("waiting for the first-run notice to be accepted in the web UI")
            while not self._notice_accepted():
                if self.stop_requested.wait(1) or stop_request_path(self.m).exists():
                    stop_request_path(self.m).unlink(missing_ok=True)
                    return self.exit_code
            log.info("notice accepted")
        if self.setup_pending:
            log.info("waiting for the server to be set up in the web UI")
        elif self.autostart:
            self.submit("start", self._boot)
        # Let the first start finish before the first scheduled update check.
        self.next_check = time.monotonic() + 60
        import datetime as _dt
        self._sched_last = _dt.datetime.now()  # schedules count from now, not from a missed past

        while not self.stop_requested.is_set():
            if stop_request_path(self.m).exists():
                stop_request_path(self.m).unlink(missing_ok=True)
                log.info("stop requested")
                self.stop_requested.set()
                break
            idle = not self.ops.locked()
            if (idle and self.want_running and self.proc is not None and not self.proc.running
                    and not self.proc.stopping):
                self._handle_crash()
            req = request_path(self.m)
            requested = req.exists()
            if self.setup_pending:  # nothing to check or restart until the server exists
                self.stop_requested.wait(self.tick)
                continue
            if idle and (requested or time.monotonic() >= self.next_check):
                target = (req.read_text().strip() or None) if requested else None
                req.unlink(missing_ok=True)
                self.submit("update check", self.check_for_updates, requested, target)
            if idle:
                self._run_schedules()
                self._watch_lag()
            sreq = self_update_request_path(self.m)
            if self.hub_managed:  # the hub checks for and installs craft-conductor updates
                self.stop_requested.wait(self.tick)
                continue
            if idle and sreq.exists():
                sreq.unlink(missing_ok=True)
                self.check_self_update()
                info = self.updater.release
                if info and info.get("can_install") and self.updater.begin(info["version"]):
                    self.submit(f"update Craft Conductor to {info['version']}", self.apply_self_update)
            if self.m.config.self_update_check and time.monotonic() >= self.next_self_check:
                self.next_self_check = time.monotonic() + SELF_CHECK_INTERVAL
                threading.Thread(target=self.check_self_update, daemon=True, name="self-update-check").start()
            self.stop_requested.wait(self.tick)
        return self.exit_code

    def failure_report(self, what: str, error: BaseException | str, console: list[str] | None = None) -> Path | None:
        """Write what went wrong (the error, recent activity, the server's last output) to a file
        people can read or send to someone helping them; returns its path."""
        import traceback
        folder = self.m.config.state_dir / "logs"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            path = folder / f"{stamp}-{re.sub(r'[^a-z0-9]+', '-', what.lower()).strip('-') or 'failure'}.txt"
            events, _ = self.events.since(0, 200)
            lines = self.proc.tail(200) if console is None and self.proc else (console or [])
            parts = [f"Craft Conductor {__version__}: {what} failed at {time.strftime('%Y-%m-%d %H:%M:%S')}",
                     f"Server folder: {self.m.server_dir}", "", "Error:", str(error)]
            if isinstance(error, BaseException):
                parts += ["", "Where it happened:", "".join(traceback.format_exception(error)).rstrip()]
            parts += ["", "Recent Craft Conductor activity:"] + [f"  {time.strftime('%H:%M:%S', time.localtime(e['time']))} "
                                                     f"{e.get('level', '')}: {e.get('message', '')}" for e in events]
            if lines:
                parts += ["", "The server's last output:"] + [f"  {x}" for x in lines]
            server_log = self.m.server_dir / "logs" / "latest.log"
            crashes = self.m.server_dir / "crash-reports"
            parts += ["", f"Minecraft's own log: {server_log}" + ("" if server_log.exists() else " (not written yet)")]
            if crashes.is_dir():
                parts.append(f"Minecraft's crash reports: {crashes}")
            path.write_text("\n".join(parts) + "\n", encoding="utf-8")
            for old in sorted(folder.glob("*.txt"))[:-20]:  # keep the last 20
                old.unlink(missing_ok=True)
            return path
        except OSError as e:
            log.warning("couldn't write a failure report: %s", e)
            return None

    def _handle_crash(self) -> None:
        self.crashed_at = time.time()
        self.activity.all_left(self.crashed_at)
        now = time.monotonic()
        self.crashes.append(now)
        while self.crashes and now - self.crashes[0] > CRASH_WINDOW:
            self.crashes.popleft()
        self._explain(self.proc.tail(400), "crash")
        tail = "\n".join(self.proc.tail(15))
        from .diagnose import diagnose
        blame = diagnose(self.proc.tail(400), self.m.server_dir, self.m.lock.mods).summary
        if blame:  # say which mod it was, where people look
            log.error("%s", blame)
            tail = f"{blame}\n{tail}"
        report = self.failure_report("server crash", f"the server stopped unexpectedly (exit {self.proc.returncode})"
                                     + (f"\n{blame}" if blame else ""))
        where = f"The details are in {report} (and Minecraft's own log, {self.m.server_dir / 'logs' / 'latest.log'})"
        log.error("%s", where)
        tail = f"{tail}\n{where}"
        self.proc.stopping = True  # handled; don't count this exit twice
        if not self.m.config.restart_on_crash or len(self.crashes) > MAX_CRASHES:
            self.m.notifier.send(f"Server stopped unexpectedly (exit {self.proc.returncode}); not restarting.\n{tail}")
            self.want_running = False
            if not self.web_enabled:
                self.exit_code = 1
                self.stop_requested.set()
            return
        self.m.notifier.send(f"Server crashed (exit {self.proc.returncode}); restarting.\n{tail}")
        delay = min(60, 5 * len(self.crashes))

        def restart():
            self.stop_requested.wait(delay)
            if self.stop_requested.is_set() or not self.want_running:
                return "cancelled"
            try:
                return self.start_server()
            except Exception:
                if self.proc:
                    self.proc.stopping = False  # let crash handling try again
                raise
        self.submit("restart after crash", restart)

    def _forward_console(self) -> None:
        """Pass lines typed into this terminal through to the server console."""
        if not sys.stdin or not sys.stdin.isatty():
            return

        def pump():
            for line in sys.stdin:
                if self.proc and self.proc.running and line.strip():
                    self.proc.send(line.rstrip("\n"))
        threading.Thread(target=pump, daemon=True, name="console").start()

    # ---------------------------------------------------------- updates
    def check_only(self, target: str | None = None) -> str:
        decision, changes = self.m.check(target, retry_failed=True)
        self.last_check = decision_to_dict(self.m, decision, changes)
        from . import reminders
        reminders.remind(self.m, self.last_check.get("lagging"))
        if self.last_check["up_to_date"]:
            lag = self.last_check.get("lagging")
            if lag:
                return (f"up to date on Minecraft {self.m.lock.minecraft}; {lag['version']} waits for "
                        f"{len(lag['mods'])} mod(s) to support it")
            return f"up to date (Minecraft {self.m.lock.minecraft})"
        if decision.plan:
            return f"update available: Minecraft {decision.plan.minecraft}"
        return "no installable combination found"

    def check_for_updates(self, force: bool = False, target: str | None = None,
                          allow_stopped: bool = False) -> str:
        cfg = self.m.config.updates
        self.next_check = time.monotonic() + cfg.check_interval
        try:
            decision, changes = self.m.check(target, retry_failed=force)
        except Exception as e:
            log.warning("update check failed: %s", e)
            return f"update check failed: {e}"
        self.last_check = decision_to_dict(self.m, decision, changes)
        from . import reminders
        reminders.remind(self.m, self.last_check.get("lagging"))
        for plan in decision.blocked:
            if plan.minecraft == decision.latest and plan.fingerprint not in self.announced:
                self.announced.add(plan.fingerprint)
                if any(b.key == "craft-conductor:failed" for b in plan.blockers):
                    continue  # already reported when it failed
                waiting = ", ".join(b.name for b in plan.blockers) or f"{plan.loader} loader"
                self.m.notifier.send(f"Minecraft {plan.minecraft} is out; waiting on: {waiting}")
        if not decision.plan or not changes or changes.empty:
            return "up to date" if decision.plan else "no installable combination found"
        summary = "\n".join(changes.summary())
        running = bool(self.proc and self.proc.running)
        if not (force or allow_stopped or self.autostart or running):
            # A server you start by hand isn't booted just to update it; it updates when you start it.
            return "update available (applies the next time the server starts)"
        if not (cfg.auto_upgrade or force):
            if decision.plan.fingerprint not in self.announced:
                self.announced.add(decision.plan.fingerprint)
                self.m.notifier.send(f"Update available (run `craft-conductor update` to apply):\n{summary}")
            return "update available (automatic upgrades are off)"
        missing = self.m.missing_manual(decision.plan)
        if missing:
            key = "manual:" + decision.plan.fingerprint
            if key not in self.announced:
                self.announced.add(key)
                self.m.notifier.send(str(ManualDownloadRequired(missing, self.m.config.manual_dir)))
            return f"waiting for {len(missing)} manual download(s)"
        if cfg.wait_for_empty and self.proc and self.proc.running and not force:
            online = self.proc.players_online()
            if online:
                log.info("update ready but %s player(s) online; waiting", online)
                self.next_check = time.monotonic() + EMPTY_RETRY
                return f"waiting for {online} player(s) to leave"
        if self.rehearsal is not None and self.rehearsal.state == "running" and not force:
            return "waiting for the update rehearsal to finish"
        if cfg.rehearse and not force and changes.minecraft:
            why = self._rehearsal_gate(decision.plan)
            if why:
                return why
        was_running = bool(self.proc and self.proc.running)
        result = self.m.apply(decision.plan, server=self.proc, restart=was_running or self.want_running)
        if result.ok:
            log.info(result.message)  # failures are already logged by the rollback
        if result.process:
            self.proc = result.process
        elif self.proc and not self.proc.running and self.want_running:
            # Neither the new nor the old version came back up; let crash handling retry.
            self.proc.stopping = False
        try:
            self.last_check = decision_to_dict(self.m, *self.m.check())
        except Exception:
            pass
        if not result.ok:
            raise RuntimeError(result.message)
        return result.message

    def make_manager(self):
        hub = getattr(self, "hub", None)
        if hub is not None:
            return hub.make_manager
        return lambda cfg: Manager(cfg, http=self.m.http, echo=False)

    def find_lag(self, automatic: bool = False):
        """Look for what's making the server lag (see lagfinder.py), in the background."""
        from . import lagfinder
        self.lag = f = lagfinder.LagFinder(self, automatic=automatic)

        def run():
            set_current_server(self.server_id)
            result = f.run() or {}
            if automatic and f.state == "done":
                tps = result.get("tps")
                self.m.notifier.send(f"The server kept falling behind with players on{f' ({tps} TPS)' if tps else ''}. "
                                     f"{result.get('summary', '')} The details are on the Dashboard, under Performance.")
        threading.Thread(target=run, daemon=True, name="lag-finder").start()
        return f

    def _watch_lag(self) -> None:
        """While people play, read the speed every couple of minutes; when it keeps falling
        behind, find out why by itself (at most once an hour)."""
        from . import lagfinder, perf
        now = time.monotonic()
        if (now < self._next_lag_watch or not self.m.config.server.find_lag or not self.players
                or not (self.proc and self.proc.running and self.proc.ready.is_set())):
            return
        self._next_lag_watch = now + lagfinder.WATCH_EVERY
        loader = self.m.lock.loader or self.m.config.server.loader
        minecraft = self.m.lock.minecraft or ""
        if not perf.command_for(loader, minecraft):
            return
        if self.meter is None:
            self.meter = perf.Meter()

        def sample():
            got = self.meter.sample(self.proc, loader, minecraft) or {}
            tps = got.get("tps")
            self._slow = self._slow + 1 if tps is not None and tps < lagfinder.LAGGY_TPS else 0
            busy = (self.lag is not None and self.lag.state == "running") or \
                (self.rehearsal is not None and self.rehearsal.state == "running")
            if self._slow >= lagfinder.WATCH_SAMPLES and not busy and time.monotonic() - self._last_lag_look >= lagfinder.AUTO_GAP:
                self._slow = 0
                self._last_lag_look = time.monotonic()
                log.info("the server keeps falling behind (%s TPS) with players on: looking for why", tps)
                self.find_lag(automatic=True)
        threading.Thread(target=sample, daemon=True, name="lag-watch").start()

    def start_rehearsal(self, target: str | None = None, minutes: int | None = None, fingerprint: str | None = None):
        """Try the update on a copy of the server, in the background (it isn't one of the server's
        jobs: crash restarts and backups carry on meanwhile). When it's done the update check runs
        again, so an automatic update waiting for it goes ahead (or is held back) straight away."""
        from . import rehearsal
        r = rehearsal.Rehearsal(self, self.make_manager(), target=target, minutes=minutes or rehearsal.WATCH_DEFAULT)
        r.for_fingerprint = fingerprint
        self.rehearsal = r

        def run():
            set_current_server(self.server_id)
            r.run()
            self.next_check = 0.0
        threading.Thread(target=run, daemon=True, name=f"rehearsal:{r.id}").start()
        return r

    def _rehearsal_gate(self, plan) -> str | None:
        """Before a new Minecraft goes in by itself: None once it has worked on a copy of the
        server; otherwise why it waits. A rehearsal is started if there's no recent one; one that
        didn't work is reported once and holds the update back until someone looks (Updates page:
        rehearse again, or update anyway)."""
        from . import rehearsal
        if rehearsal.passed(self.m.config, plan.fingerprint):
            return None
        key = "rehearsal:" + plan.fingerprint
        held = f"held back: the update to Minecraft {plan.minecraft} didn't work on a copy of the server"
        if key in self.announced:
            return held
        r = self.rehearsal
        if r is not None and r.for_fingerprint == plan.fingerprint and r.state != "running":
            self.announced.add(key)
            result = r.result or {}
            self.m.notifier.send(f"The update to Minecraft {plan.minecraft} was held back: it was tried on a copy of the "
                                 f"server first, and {result.get('summary') or result.get('error') or 'it did not work'} "
                                 "See the server's Updates page.")
            return held
        log.info("trying the update to Minecraft %s on a copy of the server first", plan.minecraft)
        self.start_rehearsal(plan.minecraft, fingerprint=plan.fingerprint)
        return f"trying the update to Minecraft {plan.minecraft} on a copy of the server first"

    def remove_and_upgrade(self, version: str, mods: list[str]) -> str:
        """The admin's answer to a reminder: drop the mods that haven't caught up, then update."""
        from . import config as configmod
        for item in mods:
            source, _, mod_id = item.partition(":")
            if configmod.remove_mod(self.m.config.path, source, mod_id):
                log.info("removed %s from craft-conductor.toml so the server can move to Minecraft %s", mod_id, version)
        self.m.reload_config()
        return self.check_for_updates(force=True, target=version)

    # ------------------------------------------------------------ setup
    def wait_for_manual_downloads(self, limit: float = MANUAL_WAIT) -> None:
        """Setup pauses while the person downloads the mods whose authors don't let other apps
        download them (the page's manual downloads panel), and carries on once they're all in:
        dropped on the panel, or copied into the manual-downloads folder."""
        waiting = self.last_check["manual"]
        log.info("waiting for %d mod(s) to be downloaded by hand: %s", len(waiting), ", ".join(m["name"] for m in waiting))
        self._manual_stop = False
        self.waiting_for_manual = True
        deadline = time.monotonic() + limit
        try:
            while True:
                self.refresh_manual()
                left = self.last_check.get("manual") or []
                if not left:
                    break
                if self._manual_stop:
                    raise RuntimeError("setup stopped: it was waiting for mods to be downloaded by hand")
                if time.monotonic() > deadline:
                    raise RuntimeError("setup stopped after waiting too long for these mods to be downloaded by hand: "
                                       + ", ".join(m["name"] for m in left))
                self._manual_arrived.wait(MANUAL_POLL)  # (also looks now and then: files copied in by hand)
                self._manual_arrived.clear()
        finally:
            self.waiting_for_manual = False
        log.info("every mod downloaded by hand is in; carrying on")

    def refresh_manual(self) -> None:
        """Drop the mods that are now in the manual-downloads folder (and match CurseForge's
        checksum) from the ones waiting."""
        c = self.last_check
        if not c or not c.get("manual"):
            return
        folder = self.m.config.manual_dir
        def have(x: dict) -> bool:
            path = folder / x["filename"]
            return path.is_file() and (not x.get("sha1") or sha1_file(path) == str(x["sha1"]).lower())
        c["manual"] = [x for x in c["manual"] if not have(x)]

    def manual_arrived(self, stop: bool = False) -> None:
        """A mod downloaded by hand came in (``stop``: the person stopped the wait)."""
        if stop:
            self._manual_stop = True
        self._manual_arrived.set()

    @property
    def setup_pending(self) -> bool:
        return setupmod.is_pending(self.m.config.root)

    def run_setup(self, spec: "setupmod.SetupSpec") -> str:
        """First-time setup from the web UI: write the config, then install and boot the server."""
        if self.m.lock.installed:
            raise RuntimeError("this server is already set up")
        setupmod.configure(self.m.config.root, spec)
        if spec.modpack_version.startswith("curseforge:"):
            from . import curseforgepack
            log.info("downloading the modpack from CurseForge")
            curseforgepack.apply(self.m.config.root, spec.modpack_version, self.m.http,
                                 self.m.config.curseforge_api_key, exclude=spec.modpack_exclude)
        elif spec.modpack_version:
            from . import modpack
            log.info("downloading the modpack")
            modpack.apply(self.m.config.root, spec.modpack_version, self.m.http, exclude=spec.modpack_exclude)
        self.m.reload_config()
        setupmod.whitelist_as_chosen(self.m.server_dir, spec)  # a modpack's server.properties may turn it on
        if spec.world_source is not None:
            from . import world
            log.info("bringing in your world")
            world.install(spec.world_source, world.level_dir(self.m.server_dir))
        log.info("setting up a %s server (Minecraft %s, %d mod(s))", self.m.config.server.loader,
                 self.m.config.server.minecraft, len(self.m.config.mods))
        self.check_only()
        if not self.last_check or not self.last_check.get("target"):
            raise RuntimeError(self._setup_conflict(spec))
        if self.last_check.get("manual"):
            self.wait_for_manual_downloads()
        if self.autostart:
            self.start_server()
        else:
            # Install (with a test boot) but leave starting it to the person.
            self.check_for_updates(force=True)
            if not self.m.lock.installed:
                raise RuntimeError("the server couldn't be installed; see the activity log")
        setupmod.clear_pending(self.m.config.root)
        self.next_check = time.monotonic() + self.m.config.updates.check_interval
        if self.autostart:
            return f"your server is ready: Minecraft {self.m.lock.minecraft}"
        return f"your server is ready (Minecraft {self.m.lock.minecraft}); press Start to play"

    def _setup_conflict(self, spec: "setupmod.SetupSpec") -> str:
        """Why a new server can't be made with the choices on the setup page. Its Minecraft version
        and server type stay as chosen: other versions that would work are only suggested."""
        from .planner import LOADER_NAMES
        blocked = (self.last_check or {}).get("blocked", [])[:1]
        if not blocked:
            return "no Minecraft version works with these choices"
        b = blocked[0]
        minecraft, loader = b["minecraft"], LOADER_NAMES.get(spec.loader, spec.loader)
        # The mods you picked, each with the chain down to what's missing (which then needn't be said again).
        reasons = [x["explain"] for x in (b["blockers"] if all(x["dependency"] for x in b["blockers"])
                                          else [x for x in b["blockers"] if not x["dependency"]])]
        if b.get("loader_missing"):
            reasons.insert(0, (b.get("loader_reason") or f"{loader} has no build for Minecraft {minecraft} yet") + ".")
        text = f"Minecraft {minecraft} with {loader} doesn't work with these choices. " + " ".join(reasons)
        text += " Your Minecraft version has not been changed."
        try:
            others = self.m.planner().alternatives(minecraft)
        except Exception as e:  # (only a suggestion)
            log.debug("couldn't look for other Minecraft versions: %s", e)
            others = []
        if others:
            names = " and ".join([", ".join(others[:-1]), others[-1]] if len(others) > 1 else others)
            text += (f" These choices appear to work on Minecraft {names}: to use one, pick it under "
                     "Minecraft version and create the server again, or remove the mods that can't be used.")
        return text

    # ------------------------------------------------------- self-update
    @property
    def self_update(self) -> dict | None:
        """The newer craft-conductor release that was found, if any."""
        return self.updater.release

    @self_update.setter
    def self_update(self, info: dict | None) -> None:
        self.updater.offer(info)

    def check_self_update(self) -> str:
        if self.updater.in_progress:  # (what's being installed isn't offered again)
            return f"Craft Conductor {self.updater.release['version']} is being installed"
        try:
            release = selfupdate.check(self.m.http, channel=self.m.config.self_update_channel)
        except Exception as e:
            log.debug("craft-conductor update check failed: %s", e)
            return f"couldn't check for Craft Conductor updates: {e}"
        if release is None:
            self.updater.offer(None)
            return f"Craft Conductor {selfupdate.__version__} is the latest version"
        can, why = selfupdate.install_method(release)
        first = self.updater.offer({**release.to_dict(), "current": selfupdate.__version__, "can_install": can, "reason": why})
        if first:
            self.m.notifier.send(f"Craft Conductor {release.version} is available (you have {selfupdate.__version__}). "
                                 f"Update from the web UI or with `craft-conductor self-update`.")
        return f"Craft Conductor {release.version} is available"

    def _settle_update(self) -> None:
        """Up and running: if this is the copy an update was installing, say so (the guard then lets the
        previous version go); tell whoever listens how the last update ended."""
        try:
            outcome = rollback.settle(self.m.config.state_dir, selfupdate.__version__)
        except Exception:
            log.exception("couldn't settle the last update")
            return
        if outcome:
            self.m.notifier.send(outcome.get("message") or "Craft Conductor was updated.")

    def apply_self_update(self) -> str:
        """Install the accepted update (see Updater.begin), stop the server cleanly, and restart craft-conductor on the new version."""
        u = self.updater
        if not u.in_progress:
            raise RuntimeError("no craft-conductor update is accepted")
        old, new = selfupdate.__version__, (u.release or {}).get("version", "")
        try:
            message = u.run_install(self.m.http, self.m.config.state_dir)
        except Exception as e:
            note = f"The update to Craft Conductor {new} didn't work: {e}"
            rollback.record_result(self.m.config.state_dir, False, old, new, note, bool(u.failure and u.failure.get("reverted")))
            rollback.mark_announced(self.m.config.state_dir)
            self.m.notifier.send(note[:1000])
            raise
        if self.proc and self.proc.running:
            if self.players:
                self.proc.say("Server restarting in 1 minute: updating the server manager")
                self.stop_requested.wait(60)
            self.proc.say("Restarting now!")
        self.m.notifier.send(f"{message}; restarting Craft Conductor")
        self.restart_requested = True
        self.stop_requested.set()  # run() stops the server; cli re-executes craft-conductor
        return message
