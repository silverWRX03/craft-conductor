"""Chaos tests for updates, backups and restores: Craft Conductor killed at the worst moments,
the disk filling up, damaged backups and world files. After each one, the next start must
leave a server that starts and is the version the files say (never half-updated)."""

from __future__ import annotations

import errno
import os
import pickle
import subprocess
import sys
import tarfile
import textwrap
import time
from pathlib import Path

import pytest

import flowkit
from craft_conductor import backup, config as configmod, daemon as daemonmod, snapshots
from craft_conductor.daemon import Daemon
from craft_conductor.manager import INTERRUPTED, Manager, UpgradeError
from craft_conductor.mods import providers_for

REPO = Path(__file__).resolve().parents[2]
OLD, NEW = "1.21.1", "1.21.2"


@pytest.fixture
def flow_java(tmp_path, monkeypatch):
    java = flowkit.write_java(tmp_path / "flowbin")
    flowkit.patch_template(monkeypatch, java)
    return java


@pytest.fixture
def quick_daemon(monkeypatch):
    monkeypatch.setattr(daemonmod, "time", flowkit.no_sleep_time())


@pytest.fixture
def installed(tmp_path, http, modrinth, flow_java):
    """A Fabric server on 1.21.1 with one mod, a world, and a config file of the owner's."""
    m = flowkit.make_server(tmp_path / "srv", http, modrinth, "fabric")
    assert flowkit.update(m).ok
    proc = m.start_server()  # (makes the world)
    proc.stop(10)
    (m.server_dir / "config").mkdir(exist_ok=True)
    (m.server_dir / "config" / "mine.toml").write_text("mine = true\n")
    return m


def _files(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def _next_version(m: Manager, http, modrinth, crashing: bool = False):
    flowkit.publish(http, "fabric", NEW)
    m.mojang.set_releases([OLD, NEW])
    flowkit.add_mod(modrinth, "fabric", "AAAAAAAA", NEW, "2.0", filename="crash-AAAAAAAA-2.0.jar" if crashing else None)
    decision, changes = m.check()
    assert decision.plan is not None and decision.plan.minecraft == NEW
    return decision.plan


def _fresh_manager(m: Manager, http) -> Manager:
    """What the next start of Craft Conductor sees: only what's on disk."""
    cfg = configmod.load(m.config.root)
    return Manager(cfg, http=http, mojang=m.mojang, providers=providers_for(cfg, http), echo=False, sleep=lambda s: None)


def _playable(m: Manager) -> Daemon:
    d = Daemon(m, autostart=False)
    d.stop_requested = flowkit.FastEvent()
    d.start_server()
    assert d.proc.running and d.proc.players_online() == 0
    return d


def _no_leftovers(m: Manager) -> None:
    sd = m.server_dir
    assert not m.journal_path.exists()
    assert not sd.with_name(sd.name + ".restoring").exists() and not sd.with_name(sd.name + ".replaced").exists()
    assert not m.staging_dir.exists()
    assert not list(m.config.backups.dir.glob("*.part"))


# ------------------------------------------------------------- killed mid-way
WORKER = textwrap.dedent("""\
    import pickle, shutil, sys, time
    from pathlib import Path
    state = pickle.loads(Path(sys.argv[1]).read_bytes())
    marker, point = Path(sys.argv[2]), sys.argv[3]
    from conftest import FakeHttp
    from craft_conductor import config as configmod, lock as lockmod
    from craft_conductor.manager import Manager
    from craft_conductor.minecraft import Mojang
    from craft_conductor.mods import providers_for

    http = FakeHttp()
    http.json.update(state["json"])
    http.files.update(state["files"])
    cfg = configmod.load(Path(state["root"]))
    m = Manager(cfg, http=http, mojang=Mojang(http), providers=providers_for(cfg, http), echo=False,
                sleep=lambda s: None)

    def lights_out():
        marker.write_text(point)
        time.sleep(120)  # the test kills this process here

    if point == "swap":  # some new mods copied in, the old ones already gone
        real_copy2 = shutil.copy2
        def copy2(src, dst, *a, **k):
            out = real_copy2(src, dst, *a, **k)
            if Path(dst).parent == m.mods_dir:
                lights_out()
            return out
        shutil.copy2 = copy2
    elif point == "boot":  # every new file in place, not yet started or recorded
        m.start_server = lambda lock=None: lights_out()
    elif point == "rollback":  # the new build crashed; the server folder is moved aside, the backup not in yet
        real_rename = Path.rename
        def rename(self, target):
            out = real_rename(self, target)
            if self == m.server_dir:
                lights_out()
            return out
        Path.rename = rename
    elif point == "commit":  # the new lock file is saved; nothing after it ran
        real_save = lockmod.save
        def save(root, lock, touch=True):
            real_save(root, lock, touch)
            lights_out()
        lockmod.save = save
    m.apply(state["plan"])
    sys.exit("the update finished without reaching the kill point")
    """)


def _kill_during(m: Manager, http, plan, point: str, tmp_path: Path) -> None:
    state = tmp_path / "state.pickle"
    state.write_bytes(pickle.dumps({"root": str(m.config.root), "plan": plan, "files": dict(http.files),
                                    "json": {k: v for k, v in http.json.items() if not callable(v)}}))
    marker = tmp_path / "reached"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(REPO / "src"), str(REPO / "tests")])}
    proc = subprocess.Popen([sys.executable, "-c", WORKER, str(state), str(marker), point], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.monotonic() + 60
        while not marker.exists():
            if proc.poll() is not None:
                raise AssertionError(f"the worker ended before {point!r}:\n{proc.stdout.read()}")
            if time.monotonic() > deadline:
                raise AssertionError(f"the worker never reached {point!r}")
            time.sleep(0.02)
    finally:
        proc.kill()  # (SIGKILL: no clean-up code runs, as when the power goes)
        proc.wait(10)


@pytest.mark.parametrize("point", ["swap", "boot", "rollback"])
def test_killed_in_the_middle_of_an_update_the_next_start_puts_the_old_server_back(
        point, installed, http, modrinth, tmp_path, quick_daemon):
    m = installed
    before = _files(m.server_dir)
    plan = _next_version(m, http, modrinth, crashing=point == "rollback")

    _kill_during(m, http, plan, point, tmp_path)

    m2 = _fresh_manager(m, http)
    assert m2.journal_path.exists(), "the update must have left its note"
    d = _playable(m2)  # (the start puts things right first)
    try:
        assert m2.lock.minecraft == OLD
        assert m2.lock.failed_plans.get(plan.fingerprint) == INTERRUPTED, "not retried by itself"
        after = _files(m2.server_dir)
        assert after == before, "the server's files must be exactly as before the update"
        _no_leftovers(m2)
        assert d.check_only() in ("up to date",) or m2.check()[1].empty  # (stays on the old version)
    finally:
        d.proc.stop(10)


def test_killed_after_the_update_was_recorded_the_new_version_is_kept(installed, http, modrinth, tmp_path, quick_daemon):
    m = installed
    plan = _next_version(m, http, modrinth)

    _kill_during(m, http, plan, "commit", tmp_path)

    m2 = _fresh_manager(m, http)
    assert m2.journal_path.exists()
    d = _playable(m2)
    try:
        assert m2.lock.minecraft == NEW
        assert (m2.mods_dir / "AAAAAAAA-2.0.jar").exists() and not (m2.mods_dir / "AAAAAAAA-1.0.jar").exists()
        assert (m2.server_dir / "config" / "mine.toml").read_text() == "mine = true\n"
        _no_leftovers(m2)
    finally:
        d.proc.stop(10)


def test_an_interrupted_world_swap_is_put_back_before_the_server_starts(installed, quick_daemon):
    m = installed
    world = m.server_dir / "world"
    (world / "playerdata").mkdir()
    (world / "playerdata" / "steve.dat").write_bytes(b"years of building")  # (only the old world has it)
    os.replace(world, world.with_name(".world.replaced"))  # (cut off right after moving the old world aside)

    d = _playable(m)
    try:
        assert (world / "playerdata" / "steve.dat").read_bytes() == b"years of building", \
            "Minecraft must not have made a new world"
    finally:
        d.proc.stop(10)


# ------------------------------------------------------------- the disk fills
def _fill_disk_on_write(monkeypatch, when=lambda: True):
    real = tarfile.copyfileobj

    def copy(src, dst, length=None, exception=OSError, bufsize=None):
        if when():
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(src, dst, length, exception, bufsize)
    monkeypatch.setattr(tarfile, "copyfileobj", copy)


def test_disk_full_during_the_backup_before_an_update_keeps_the_old_server_running(
        installed, http, modrinth, monkeypatch, quick_daemon):
    m = installed
    before = _files(m.server_dir)
    d = _playable(m)
    _next_version(m, http, modrinth)  # (after starting: starting by hand would update it on the way up)
    try:
        _fill_disk_on_write(monkeypatch)
        with pytest.raises(RuntimeError, match="disk is full.*Nothing was changed"):
            d.check_for_updates(force=True)
        assert d.proc.running and d.proc.players_online() == 0, "the old version must be started again"
        assert m.lock.minecraft == OLD
        _no_leftovers(m)
    finally:
        d.proc.stop(10)
    assert _files(m.server_dir) == before


def test_disk_full_while_rolling_back_is_finished_by_the_next_start(installed, http, modrinth, monkeypatch, quick_daemon):
    m = installed
    before = _files(m.server_dir)
    plan = _next_version(m, http, modrinth, crashing=True)
    full = {"on": False}
    real_create = backup.create

    def create(*a, **k):  # (the backup before the update is made; then the disk fills)
        out = real_create(*a, **k)
        full["on"] = True
        return out
    monkeypatch.setattr(backup, "create", create)
    _fill_disk_on_write(monkeypatch, when=lambda: full["on"])

    result = m.apply(plan)

    assert not result.ok and "Putting the backup" in result.message and "wasn't started" in result.message
    assert m.journal_path.exists(), "the note stays, so the next start finishes the job"
    assert not m.server_dir.with_name("server.restoring").exists(), "the half-unpacked copy is removed"

    full["on"] = False  # (space was freed)
    m2 = _fresh_manager(m, http)
    d = _playable(m2)
    try:
        assert m2.lock.minecraft == OLD
        assert "mod failed to load" in m2.lock.failed_plans[plan.fingerprint] or \
            "did not finish starting" in m2.lock.failed_plans[plan.fingerprint]
        assert _files(m2.server_dir) == before
        _no_leftovers(m2)
    finally:
        d.proc.stop(10)


def test_disk_full_during_a_scheduled_backup_keeps_the_world_saving(installed, monkeypatch, quick_daemon):
    m = installed
    d = _playable(m)
    try:
        _fill_disk_on_write(monkeypatch)
        with pytest.raises(OSError):
            d.backup_now("scheduled")
        flowkit.wait_for(lambda: any("save-on" in line for line in d.proc.lines), what="save-on")
        assert d.proc.running
        assert not list(m.config.backups.dir.glob("*.part")) and not any(
            p.name.endswith("-scheduled.tar.gz") for p in backup.list_backups(m.config.backups.dir))
    finally:
        d.proc.stop(10)


# ----------------------------------------------------------------- damage
def test_a_damaged_backup_at_rollback_time_is_reported_and_a_good_one_still_restores(
        installed, http, modrinth, monkeypatch, quick_daemon):
    m = installed
    good = backup.create(m.server_dir, m.config.backups.dir, "manual", [])
    snapshots.record(good, m)
    plan = _next_version(m, http, modrinth, crashing=True)
    real_create = backup.create

    def create(*a, **k):  # (the backup before the update is damaged on the disk)
        out = real_create(*a, **k)
        data = out.read_bytes()
        out.write_bytes(data[: len(data) // 3])
        return out
    monkeypatch.setattr(backup, "create", create)

    result = m.apply(plan)
    assert not result.ok and "damaged or cut short" in result.message, result.message

    m2 = _fresh_manager(m, http)
    with pytest.raises(UpgradeError, match="putting the backup .* back failed"):
        Daemon(m2, autostart=False).start_server()  # never runs on half-updated files

    snapshots.roll_back(good, m2)  # (the owner picks an earlier backup on the Backups page)
    d = _playable(m2)
    try:
        assert m2.lock.minecraft == OLD and (m2.mods_dir / "AAAAAAAA-1.0.jar").exists()
        assert not (m2.mods_dir / "crash-AAAAAAAA-2.0.jar").exists()
        assert not m2.journal_path.exists()
    finally:
        d.proc.stop(10)


def test_damaged_world_files_are_caught_by_the_backup_check_and_a_good_backup_brings_them_back(
        installed, quick_daemon):
    m = installed
    notes: list[str] = []
    m.notifier.listeners.append(notes.append)
    d = _playable(m)
    try:
        good = d.backup_now("manual")
        assert "(checked)" in good
        world = m.server_dir / "world"
        (world / "level.dat").write_bytes(b"\x1f\x8b garbage")  # (a crash while Minecraft was saving)
        bad = d.backup_now("manual")
        assert "doesn't look right" in bad and "level.dat" in bad
        assert any("doesn't look right" in n for n in notes), "the owner is told"
    finally:
        d.stop_server()
    first = backup.list_backups(m.config.backups.dir)[0]
    snapshots.roll_back(first, m)
    assert (m.server_dir / "world" / "level.dat").read_bytes() == flowkit.LEVEL_DAT
    d = _playable(m)
    d.proc.stop(10)
