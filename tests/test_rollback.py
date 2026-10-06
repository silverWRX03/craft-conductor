"""An update that doesn't work puts the previous Craft Conductor back (rollback.py)."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from craft_conductor import rollback, selfupdate
from craft_conductor.selfupdate import Updater


# ------------------------------------------------------- keeping and restoring the previous version
def make_site(root: Path, version: str, body: str):
    pkg = root / "craft_conductor"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(f'__version__ = "{version}"\n')
    (pkg / "core.py").write_text(body)
    info = root / f"craft_conductor-{version}.dist-info"
    info.mkdir(exist_ok=True)
    (info / "METADATA").write_text(f"Version: {version}\n")
    return pkg, info


def test_the_installed_package_is_put_back(tmp_path):
    site = tmp_path / "site-packages"
    pkg, info = make_site(site, "0.24.0", "OLD")
    backup = rollback.backup_dir(tmp_path / "state")
    rollback.keep_previous(backup, False, Path(sys.executable), "0.24.0", package=pkg, dist_info=info)
    # the update: files changed and added, the old metadata replaced by the new
    (pkg / "core.py").write_text("NEW")
    (pkg / "extra.py").write_text("new file")
    import shutil
    shutil.rmtree(info)
    make_site(site, "0.25.0", "NEW")
    assert rollback.restore(backup) == "Craft Conductor 0.24.0 is back"
    assert (pkg / "core.py").read_text() == "OLD" and not (pkg / "extra.py").exists()
    assert (pkg / "__init__.py").read_text() == '__version__ = "0.24.0"\n'
    assert sorted(p.name for p in site.glob("*.dist-info")) == ["craft_conductor-0.24.0.dist-info"]


def test_the_executable_is_put_back(tmp_path):
    exe = tmp_path / "craft-conductor-linux-x64"
    exe.write_bytes(b"old program")
    backup = rollback.backup_dir(tmp_path / "state")
    rollback.keep_previous(backup, True, exe, "0.24.0")
    exe.write_bytes(b"new program")
    rollback.restore(backup)
    assert exe.read_bytes() == b"old program" and os.access(exe, os.X_OK)


def test_nothing_kept_means_nothing_is_put_back(tmp_path):
    with pytest.raises(rollback.RollbackError, match="no kept copy"):
        rollback.restore(rollback.backup_dir(tmp_path))


# ------------------------------------------------------------------ trying the new version first
def said(version, code=0, err=""):
    return lambda argv, **kw: subprocess.CompletedProcess(argv, code, f"Craft Conductor {version}\n", err)


def test_the_new_version_must_start_and_say_what_it_is():
    rollback.check_new_version("9.9.9", said("9.9.9"))
    rollback.check_new_version("0.25.0b1", said("0.25.0-beta.1"))  # (the same version, spelled differently)
    with pytest.raises(rollback.RollbackError, match="it said 0.24.0, not 9.9.9"):
        rollback.check_new_version("9.9.9", said("0.24.0"))
    with pytest.raises(rollback.RollbackError, match="ImportError"):
        rollback.check_new_version("9.9.9", said("", 1, "ImportError: no module named x"))

    def hangs(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 1)
    with pytest.raises(rollback.RollbackError, match="couldn't be started"):
        rollback.check_new_version("9.9.9", hangs)


# --------------------------------------------------------------------------- the update's outcome
def test_the_outcome_is_announced_once(tmp_path):
    state = tmp_path
    rollback.write_pending(state, "0.24.0", "9.9.9", ["craft-conductor", "start"])
    assert rollback.settle(state, "0.24.0") is None  # (not the new copy, nothing to say yet)
    done = rollback.settle(state, "9.9.9")
    assert done["ok"] is True and done["to"] == "9.9.9"
    assert rollback.pending(state)["confirmed"]["pid"] == os.getpid()
    assert rollback.settle(state, "9.9.9") is None
    assert rollback.public(rollback.result(state))["ok"] is True and "announced" not in rollback.public(rollback.result(state))
    # a copy that was put back hears of the failure once
    rollback.record_result(state, False, "0.24.0", "9.9.9", "it didn't work", reverted=True)
    failed = rollback.settle(state, "0.24.0")
    assert failed["ok"] is False and failed["reverted"] is True
    assert rollback.settle(state, "0.24.0") is None


# --------------------------------------------------------------------------------- the guard
class Clock:
    def __init__(self):
        self.t = 1000.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def guarded(tmp_path, monkeypatch, **pending):
    """A state folder with a kept executable, an update to 9.9.9 pending, and a guard clock."""
    state = tmp_path / "state"
    exe = tmp_path / "craft-conductor"
    exe.write_bytes(b"old program")
    rollback.keep_previous(rollback.backup_dir(state), True, exe, "0.24.0")
    exe.write_bytes(b"new program")
    rollback.write_pending(state, "0.24.0", "9.9.9", [str(exe), "start"], pid=pending.pop("pid", os.getpid()))
    data = rollback.pending(state)
    data.update(pending)
    rollback._write(state / rollback.PENDING, data)
    stopped, started = [], []
    monkeypatch.setattr(rollback, "_stop", lambda pid, **kw: stopped.append(pid))
    return state, exe, Clock(), stopped, started


def run_guard(state, clock, started, **kw):
    return rollback.guard(state, now=clock.now, sleep=clock.sleep, popen=lambda argv, **k: started.append((argv, k)), **kw)


def test_a_new_copy_that_never_comes_up_is_replaced_by_the_previous_one(tmp_path, monkeypatch):
    clock = Clock()
    state, exe, clock, stopped, started = guarded(tmp_path, monkeypatch, restart_at=Clock().t - 1)
    assert run_guard(state, clock, started, guard_seconds=180) == "reverted"
    assert exe.read_bytes() == b"old program"                       # the previous version is back...
    assert started[0][0] == [str(exe), "start"]                     # ...and started again, as before
    assert started[0][1]["env"][selfupdate.RESTARTED_ENV] == "1"    # (no new browser tab for that either)
    out = rollback.result(state)
    assert out["ok"] is False and out["reverted"] is True and "0.24.0 is back" in out["message"]
    assert rollback.pending(state) is None and stopped                 # the broken copy was stopped first


def test_a_new_copy_that_confirms_and_stays_up_is_kept(tmp_path, monkeypatch):
    state, exe, clock, stopped, started = guarded(tmp_path, monkeypatch, restart_at=1000.0 - 5)
    rollback.settle(state, "9.9.9")  # (the new copy says it's up; this test process stands in for it)
    data = rollback.pending(state)
    data["confirmed"]["at"] = clock.now()
    rollback._write(state / rollback.PENDING, data)
    assert run_guard(state, clock, started, stable_seconds=15) == "confirmed"
    assert exe.read_bytes() == b"new program" and started == []
    assert rollback.pending(state) is None and not rollback.backup_dir(state).exists()  # the kept copy is let go


def test_a_new_copy_that_dies_right_after_starting_is_replaced(tmp_path, monkeypatch):
    state, exe, clock, stopped, started = guarded(tmp_path, monkeypatch, restart_at=1000.0 - 5)
    rollback.settle(state, "9.9.9")
    data = rollback.pending(state)
    data["confirmed"] = {"at": clock.now(), "pid": 2 ** 22 + 12345}   # (a process that isn't running)
    rollback._write(state / rollback.PENDING, data)
    assert run_guard(state, clock, started) == "reverted"
    assert exe.read_bytes() == b"old program"


def test_nothing_is_undone_when_craft_conductor_was_closed_before_restarting(tmp_path, monkeypatch):
    state, exe, clock, stopped, started = guarded(tmp_path, monkeypatch, pid=2 ** 22 + 54321)  # (never restarted, gone)
    assert run_guard(state, clock, started) == "abandoned"
    assert exe.read_bytes() == b"new program" and started == []


def test_a_rollback_that_cannot_happen_is_said_plainly(tmp_path, monkeypatch):
    state, exe, clock, stopped, started = guarded(tmp_path, monkeypatch, restart_at=1000.0 - 500)
    rollback.forget(rollback.backup_dir(state))  # (the kept copy is gone)
    assert run_guard(state, clock, started) == "abandoned"
    out = rollback.result(state)
    assert out["ok"] is False and out["reverted"] is False and "couldn't be put back" in out["message"]
    assert started == []


def test_the_guard_starts_from_the_kept_version(tmp_path):
    state = tmp_path / "state"
    exe = tmp_path / "craft-conductor"
    exe.write_bytes(b"old program")
    rollback.keep_previous(rollback.backup_dir(state), True, exe, "0.24.0")
    calls = []
    rollback.spawn_guard(state, rollback.backup_dir(state), popen=lambda argv, **kw: calls.append((argv, kw)))
    argv, kw = calls[0]
    assert argv == [str(rollback.backup_dir(state) / "previous" / "craft-conductor")]      # the OLD program, not the new one
    assert kw["env"][rollback.GUARD_ENV] == str(state)


def test_the_kept_package_runs_the_guard_by_itself(tmp_path):
    """The previous version's own copy of the package can be run alone: that's what watches an update."""
    info = tmp_path / "craft_conductor-0.24.0.dist-info"   # (stands in for the installed metadata)
    info.mkdir()
    (info / "METADATA").write_text("Version: 0.24.0\n")
    state = tmp_path / "state"
    state.mkdir()
    rollback.keep_previous(rollback.backup_dir(state), False, Path(sys.executable), "0.24.0",
                           package=Path(rollback.__file__).resolve().parent, dist_info=info)
    env = {**os.environ, rollback.GUARD_ENV: str(state),
           "PYTHONPATH": str(rollback.backup_dir(state) / "previous")}
    done = subprocess.run([sys.executable, "-c", "import craft_conductor, sys; print(craft_conductor.__file__); "
                           "from craft_conductor import cli; sys.exit(cli.main([]))"],
                          capture_output=True, text=True, env=env, timeout=60)
    assert done.returncode == 0, done.stderr  # (no update pending: the guard has nothing to do and ends)
    assert str(rollback.backup_dir(state)) in done.stdout   # (it was the kept copy that ran)


# ---------------------------------------------- the updater: try it, then guard the restart, or put it back
@pytest.fixture
def exe_update(tmp_path, monkeypatch):
    """An update of an 'executable': the installer replaces it; the new version's check is decided by the test."""
    exe = tmp_path / "craft-conductor"
    exe.write_bytes(b"old program")
    state = tmp_path / "state"

    def install(release, **kw):
        kw["progress"]("downloading", 1, 2)
        selfupdate._keep_previous  # (the real installer keeps the previous version here)
        rollback.keep_previous(kw["backup"], True, exe, "0.24.0")
        exe.write_bytes(b"new program")
        return f"installed Craft Conductor {release.version}"
    monkeypatch.setattr(selfupdate, "install", install)
    monkeypatch.setattr(selfupdate, "_GUARDED_STATE", None)
    u = Updater()
    u.offer({"version": "9.9.9", "tag": "v9.9.9", "url": "", "notes": "", "current": "0.24.0", "can_install": True, "reason": ""})
    assert u.begin("9.9.9")
    return u, exe, state


def test_a_new_version_that_wont_start_is_never_restarted_into(exe_update, monkeypatch):
    u, exe, state = exe_update

    def broken(expected, *a, **k):
        raise rollback.RollbackError("the new version doesn't start properly (it said nothing, not 9.9.9)")
    monkeypatch.setattr(rollback, "check_new_version", broken)
    guards = []
    monkeypatch.setattr(rollback, "spawn_guard", lambda *a, **k: guards.append(a))
    with pytest.raises(selfupdate.SelfUpdateError, match="doesn't start properly"):
        u.run_install(object(), state)
    assert exe.read_bytes() == b"old program"                 # put back, while this copy was still running
    snap = u.snapshot()
    assert snap["phase"] == "failed" and snap["failure"]["reverted"] is True and "put back" in snap["error"]
    assert guards == [] and rollback.pending(state) is None and snap["version"] == "9.9.9"  # still available for another try


def test_a_good_new_version_is_guarded_through_its_restart(exe_update, monkeypatch):
    u, exe, state = exe_update
    monkeypatch.setattr(rollback, "check_new_version", lambda *a, **k: None)
    guards = []
    monkeypatch.setattr(rollback, "spawn_guard", lambda *a, **k: guards.append(a))
    assert u.run_install(object(), state) == "installed Craft Conductor 9.9.9"
    assert u.snapshot()["phase"] == "restarting" and len(guards) == 1
    pending = rollback.pending(state)
    assert pending["from"] == "0.24.0" and pending["to"] == "9.9.9" and pending["restart_at"] is None
    monkeypatch.setattr(sys, "argv", ["craft-conductor", "start"])
    monkeypatch.setattr(selfupdate, "WINDOWS", False)
    monkeypatch.setattr(os, "execve", lambda *a: None)
    selfupdate.restart()
    assert rollback.pending(state)["restart_at"] is not None   # (the new copy's time starts when this one ends)


def test_an_install_that_fails_part_way_puts_the_previous_version_back(exe_update, monkeypatch):
    u, exe, state = exe_update

    def failing(release, **kw):
        rollback.keep_previous(kw["backup"], True, exe, "0.24.0")
        exe.write_bytes(b"half a program")
        raise selfupdate.SelfUpdateError("pip could not install Craft Conductor 9.9.9")
    monkeypatch.setattr(selfupdate, "install", failing)
    with pytest.raises(selfupdate.SelfUpdateError):
        u.run_install(object(), state)
    assert exe.read_bytes() == b"old program" and u.snapshot()["failure"]["reverted"] is True


def test_a_download_that_fails_has_nothing_to_put_back(exe_update, monkeypatch):
    u, exe, state = exe_update
    # (a stale kept copy from an earlier try must not be mistaken for this one's)
    rollback.keep_previous(rollback.backup_dir(state), True, exe, "0.1.0")

    def failing(release, **kw):
        raise selfupdate.VerificationError("the download doesn't match its checksum")
    monkeypatch.setattr(selfupdate, "install", failing)
    exe.write_bytes(b"the program that's running")
    with pytest.raises(selfupdate.VerificationError):
        u.run_install(object(), state)
    assert exe.read_bytes() == b"the program that's running" and u.snapshot()["failure"]["reverted"] is False


def test_a_plan_that_names_other_files_is_refused(tmp_path):
    """Only Craft Conductor's own program files are ever replaced: a changed plan can't point elsewhere."""
    backup = rollback.backup_dir(tmp_path / "state")
    exe = tmp_path / "craft-conductor"
    exe.write_bytes(b"old")
    rollback.keep_previous(backup, True, exe, "0.24.0")
    plan = rollback._read(backup / "plan.json")
    other = tmp_path / "important-file"
    other.write_bytes(b"mine")
    rollback._write(backup / "plan.json", {**plan, "exe": str(other)})
    with pytest.raises(rollback.RollbackError):
        rollback.restore(backup)
    assert other.read_bytes() == b"mine"
    site = tmp_path / "site"
    pkg, info = make_site(site, "0.24.0", "OLD")
    rollback.keep_previous(backup, False, Path(sys.executable), "0.24.0", package=pkg, dist_info=info)
    plan = rollback._read(backup / "plan.json")
    victim = tmp_path / "documents"
    victim.mkdir()
    (victim / "thesis.txt").write_text("irreplaceable")
    rollback._write(backup / "plan.json", {**plan, "package": str(victim), "site": str(tmp_path)})
    with pytest.raises(rollback.RollbackError):
        rollback.restore(backup)
    assert (victim / "thesis.txt").read_text() == "irreplaceable"
