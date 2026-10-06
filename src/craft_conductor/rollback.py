"""Putting the previous Craft Conductor back when an update didn't work.

Before an update replaces anything, the version that's running is kept aside (``update-backup/previous``
in the state folder): the executable, or the installed Python package with its metadata. Then

1. **Before restarting**, the freshly installed version is asked for its version in a new process
   (``check_new_version``). A copy that can't even do that is never started: the previous version is
   put back at once, and the running Craft Conductor carries on.
2. **After restarting**, a small guard process (started from the *previous* version, so it works even when
   the new one is broken) waits for the new copy to confirm that it's up (``confirm``). If that doesn't
   happen in ``GUARD_SECONDS`` of the restart, or the new copy dies in its first seconds, the guard stops
   it, puts the previous version back, starts that, and leaves the outcome in ``update-result.json`` so the
   restored copy can tell the person (and their phones) what happened.

All of it is in the state folder, nothing is sent anywhere, and every file touched is Craft
Conductor's own program files. Whatever can't be put back is said plainly, never hidden.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path

log = logging.getLogger(__name__)

PENDING = "self-update.json"        # an update whose new copy hasn't proven itself yet
RESULT = "update-result.json"       # how the last update ended (read by the page and the phones)
BACKUP = "update-backup"
GUARD_ENV = "CRAFT_CONDUCTOR_UPDATE_GUARD"   # set to the state folder: this process is the guard
GUARD_SECONDS = 180      # how long the new copy has, after the restart, to say it's up
STABLE_SECONDS = 15      # and how long it must then stay up before the previous version is let go
PREFLIGHT_SECONDS = 90


class RollbackError(Exception):
    pass


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text("utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1), "utf-8")
    os.replace(tmp, path)


def backup_dir(state_dir: Path) -> Path:
    return Path(state_dir) / BACKUP


# ------------------------------------------------------------------ keeping the previous version
def keep_previous(backup: Path, frozen: bool, exe: Path, version: str,
                  package: Path | None = None, dist_info: Path | None = None) -> None:
    """Copy what's running aside, before anything is replaced."""
    shutil.rmtree(backup, ignore_errors=True)
    prev = backup / "previous"
    prev.mkdir(parents=True)
    plan: dict = {"kind": "binary" if frozen else "wheel", "version": version}
    if frozen:
        shutil.copy2(exe, prev / exe.name)
        plan["exe"] = str(exe)
    else:
        package = package or Path(__file__).resolve().parent
        dist_info = dist_info or Path(str(metadata.distribution("craft-conductor")._path))  # (the .dist-info next to the package)
        shutil.copytree(package, prev / package.name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(dist_info, prev / dist_info.name)
        plan.update(package=str(package), dist_info=dist_info.name, site=str(package.parent))
    _write(backup / "plan.json", plan)


def restore(backup: Path) -> str:
    """Put the kept version back over the new one. Returns what was done; raises RollbackError when it
    couldn't (the message says what to do by hand)."""
    plan = _read(Path(backup) / "plan.json")
    prev = Path(backup) / "previous"
    if not plan or not prev.is_dir():
        raise RollbackError("there's no kept copy of the previous version to put back")
    try:
        # (only ever Craft Conductor's own files: a plan that names anything else is refused)
        if plan["kind"] == "binary":
            exe = Path(plan["exe"])
            if not exe.name.lower().startswith("craft-conductor") or not (prev / exe.name).is_file():
                raise RollbackError("the kept plan doesn't name a Craft Conductor program")
            tmp = exe.with_name(exe.name + ".reverting")
            shutil.copy2(prev / exe.name, tmp)
            tmp.chmod(0o755)
            if os.name == "nt":  # (a running program can be renamed out of the way, not overwritten)
                failed = exe.with_name(exe.stem + ".failed" + exe.suffix)
                failed.unlink(missing_ok=True)
                if exe.exists():
                    exe.rename(failed)
            os.replace(tmp, exe)
        else:
            package, site = Path(plan["package"]), Path(plan["site"])
            if package.name != "craft_conductor" or package.parent != site or not (prev / package.name / "__init__.py").is_file() \
                    or not re.fullmatch(r"craft_conductor-[0-9A-Za-z.+!]+\.dist-info", str(plan["dist_info"])):
                raise RollbackError("the kept plan doesn't name the Craft Conductor package")
            shutil.rmtree(package, ignore_errors=True)
            shutil.copytree(prev / package.name, package)
            for stale in site.glob("craft_conductor-*.dist-info"):
                shutil.rmtree(stale, ignore_errors=True)
            shutil.copytree(prev / plan["dist_info"], site / plan["dist_info"])
    except (OSError, KeyError) as e:
        raise RollbackError(f"couldn't put Craft Conductor {plan.get('version', '')} back ({e}); "
                            f"the copy is in {prev}") from e
    return f"Craft Conductor {plan.get('version', '')} is back"


def forget(backup: Path) -> None:
    shutil.rmtree(backup, ignore_errors=True)


# ------------------------------------------------------------------ before restarting
def check_new_version(expected: str, runner=subprocess.run, timeout: int = PREFLIGHT_SECONDS) -> None:
    """Run what was just installed, in its own process, and require it to say it's ``expected``."""
    from . import selfupdate
    if selfupdate.frozen():
        argv = [sys.executable, "--version"]
    else:
        argv = [sys.executable, "-m", "craft_conductor", "--version"]
    try:
        proc = runner(argv, capture_output=True, text=True, timeout=timeout, env=selfupdate.restart_env())
    except (OSError, subprocess.SubprocessError) as e:
        raise RollbackError(f"the new version couldn't be started ({e})") from e
    said = (proc.stdout or "").strip().splitlines()
    version = said[-1].split()[-1] if said else ""
    if proc.returncode != 0 or not selfupdate.same_version(version, expected):
        detail = "\n".join(((proc.stderr or "") + (proc.stdout or "")).strip().splitlines()[-6:])
        raise RollbackError(f"the new version doesn't start properly (it said {version or 'nothing'}, "
                            f"not {expected})" + (f":\n{detail}" if detail else ""))


# ------------------------------------------------------------------ the pending update
def write_pending(state_dir: Path, old: str, new: str, argv: list[str], pid: int | None = None) -> None:
    _write(Path(state_dir) / PENDING, {"from": old, "to": new, "argv": argv, "pid": pid or os.getpid(),
                                       "started": time.time(), "restart_at": None, "confirmed": None})


def pending(state_dir: Path) -> dict | None:
    return _read(Path(state_dir) / PENDING)


def mark_restarting(state_dir: Path) -> None:
    """The running copy is about to be replaced: the new one has ``GUARD_SECONDS`` from now."""
    data = pending(state_dir)
    if data is not None:
        data["restart_at"] = time.time()
        _write(Path(state_dir) / PENDING, data)


def result(state_dir: Path) -> dict | None:
    return _read(Path(state_dir) / RESULT)


def record_result(state_dir: Path, ok: bool, old: str, new: str, message: str, reverted: bool = False) -> dict:
    data = {"ok": ok, "from": old, "to": new, "message": message, "reverted": reverted, "at": time.time(),
            "announced": False}
    _write(Path(state_dir) / RESULT, data)
    return data


def mark_announced(state_dir: Path) -> None:
    data = result(state_dir)
    if data and not data.get("announced"):
        data["announced"] = True
        _write(Path(state_dir) / RESULT, data)


def confirm(state_dir: Path, version: str) -> dict | None:
    """Called by a freshly started copy once it's up: if it's the version a pending update was
    installing, say so (the guard then lets the previous version go). Returns the recorded result."""
    from . import selfupdate
    data = pending(state_dir)
    if not data or data.get("confirmed") or not selfupdate.same_version(data.get("to", ""), version):
        return None  # (not the version being installed, or it already said so)
    data["confirmed"] = {"at": time.time(), "pid": os.getpid()}
    _write(Path(state_dir) / PENDING, data)
    return record_result(state_dir, True, data.get("from", ""), version, f"Craft Conductor was updated to {version}")


def settle(state_dir: Path, version: str) -> dict | None:
    """What a copy that has just started has to tell people: it's the one a pending update was installing
    (confirmed here, so the guard lets the previous version go), or it's the previous version that was put
    back. Returns that outcome once (None when there's nothing new to say)."""
    confirm(state_dir, version)
    data = result(state_dir)
    if data and not data.get("announced"):
        mark_announced(state_dir)
        return data
    return None


def public(data: dict | None) -> dict | None:
    """The part of an outcome the page and phones may see."""
    if not data:
        return None
    return {k: data.get(k) for k in ("ok", "from", "to", "message", "reverted", "at")}


# ------------------------------------------------------------------ the guard
def spawn_guard(state_dir: Path, backup: Path, popen=subprocess.Popen) -> None:
    """Start the guard, from the kept previous version: it works whatever state the new one is in."""
    from . import selfupdate
    plan = _read(Path(backup) / "plan.json")
    if not plan:
        return
    env = selfupdate.restart_env()
    env[GUARD_ENV] = str(state_dir)
    prev = Path(backup) / "previous"
    if plan["kind"] == "binary":
        argv = [str(prev / Path(plan["exe"]).name)]
    else:
        argv = [sys.executable, "-m", "craft_conductor"]
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(prev), env.get("PYTHONPATH", "")]))
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "env": env}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    popen(argv, **kwargs)


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    from .daemon import pid_alive
    return pid_alive(pid)


def _stop(pid: int | None, wait: float = 10.0, sleep=time.sleep) -> None:
    """End the new copy that never came up (it may be hung rather than gone)."""
    if not pid or pid == os.getpid() or not _alive(pid):
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        return
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(int(wait * 4)):
            if not _alive(pid):
                return
            sleep(0.25)
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def guard(state_dir: Path, now=time.time, sleep=time.sleep, popen=subprocess.Popen, poll: float = 2.0,
          guard_seconds: float = GUARD_SECONDS, stable_seconds: float = STABLE_SECONDS) -> str:
    """Watch the update through its restart; returns "confirmed", "reverted" or "abandoned".

    Waits for the running copy to restart (it records the moment); then the new copy has
    ``guard_seconds`` to confirm it's up and ``stable_seconds`` to stay up. Otherwise it's replaced by the
    previous version, which is started again with the same command line."""
    state_dir = Path(state_dir)
    backup = backup_dir(state_dir)
    while True:
        data = pending(state_dir)
        if data is None:
            return "abandoned"  # (cleared by someone else: nothing to guard)
        restart_at, confirmed = data.get("restart_at"), data.get("confirmed")
        if confirmed:
            if not _alive(confirmed.get("pid")):
                return _revert(state_dir, backup, data, "the new version stopped right after starting", now, sleep, popen)
            if now() - confirmed["at"] >= stable_seconds:
                (state_dir / PENDING).unlink(missing_ok=True)
                forget(backup)
                return "confirmed"
        elif restart_at is None:
            if not _alive(data.get("pid")):
                return "abandoned"  # (Craft Conductor was closed before restarting: the new files wait for the next start)
        elif now() - restart_at > guard_seconds:
            return _revert(state_dir, backup, data, "the new version didn't start in time", now, sleep, popen)
        sleep(poll)


def _revert(state_dir: Path, backup: Path, data: dict, why: str, now, sleep, popen) -> str:
    from . import selfupdate
    old, new = data.get("from", ""), data.get("to", "")
    log.error("update to %s didn't work (%s); putting %s back", new, why, old)
    for candidate in (_hub_pid(state_dir), (data.get("confirmed") or {}).get("pid"), data.get("pid")):
        _stop(candidate, sleep=sleep)
    (state_dir / PENDING).unlink(missing_ok=True)
    try:
        restore(backup)
    except RollbackError as e:
        record_result(state_dir, False, old, new, f"The update to {new} didn't work ({why}), and Craft Conductor {old} "
                      f"couldn't be put back: {e}", reverted=False)
        return "abandoned"
    record_result(state_dir, False, old, new, f"The update to {new} didn't work ({why}); Craft Conductor {old} is back",
                  reverted=True)
    env = selfupdate.restart_env()
    env[selfupdate.RESTARTED_ENV] = "1"
    kwargs: dict = {"env": env, "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True
    popen(list(data.get("argv") or []), **kwargs)
    return "reverted"


def _hub_pid(state_dir: Path) -> int | None:
    try:
        return int((Path(state_dir) / "hub.pid").read_text().strip())
    except (OSError, ValueError):
        return None


def run_guard_from_env() -> int | None:
    """``cli.main`` calls this first: when the guard variable is set, this process is the guard."""
    state = os.environ.pop(GUARD_ENV, "")
    if not state:
        return None
    guard(Path(state))
    return 0
