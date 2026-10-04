"""Repeatable real-world flows, once per loader (vanilla, Fabric, Quilt, Paper, Purpur, NeoForge,
Forge), through the real loader code and a real child process for every boot:

create the server → install it with a mod (a plugin on Paper/Purpur) → start → back up while it
runs → crash, and be restarted → scheduled backup → stop → damage the world and restore it →
an update whose new build crashes is rolled back → the server still starts → the fixed update
goes through and the world survives every step.

Only the download sites and Minecraft itself are pretend (see flowkit.py); the real thing runs in
packaging/e2e_test.py (the e2e workflow), which needs the internet."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

import flowkit
from craft_conductor import backup, daemon as daemonmod, snapshots
from craft_conductor.daemon import Daemon
from flowkit import LOADERS


@pytest.fixture
def flow_java(tmp_path, monkeypatch):
    java = flowkit.write_java(tmp_path / "flowbin")
    flowkit.patch_template(monkeypatch, java)
    return java


@pytest.fixture
def quick_daemon(monkeypatch):
    monkeypatch.setattr(daemonmod, "time", flowkit.no_sleep_time())


CRASHING_SERVER_JAR = flowkit.zipapp("import sys\nprint('[Server thread/ERROR]: broken build', flush=True)\nsys.exit(1)\n")


@pytest.mark.parametrize("loader", list(LOADERS))
def test_a_server_lives_through_its_whole_life(loader, tmp_path, http, modrinth, flow_java, quick_daemon):
    first, nxt, mod_loader = LOADERS[loader]
    m = flowkit.make_server(tmp_path / loader, http, modrinth, loader)
    notes: list[str] = []
    m.notifier.listeners.append(notes.append)
    sd = m.server_dir
    world = sd / "world"

    # Install, with a test boot.
    result = flowkit.update(m)
    assert result.ok, result.message
    assert m.lock.installed and m.lock.minecraft == first and m.lock.loader == loader
    if mod_loader:
        assert m.mods_dir.name == ("plugins" if loader in ("paper", "purpur") else "mods")
        assert (m.mods_dir / "AAAAAAAA-1.0.jar").exists()

    d = Daemon(m, autostart=False)
    d.stop_requested = flowkit.FastEvent()
    try:
        # Start.
        assert d.start_server() == "started"
        assert d.proc.running and d.proc.players_online() == 0
        assert (world / "level.dat").read_bytes() == flowkit.LEVEL_DAT

        # A backup while it runs: saving paused around it, then read back to check it.
        message = d.backup_now("manual")
        assert "(checked)" in message, message
        assert any("save-off" in line for line in d.proc.lines) and any("save-on" in line for line in d.proc.lines)
        manual = backup.list_backups(m.config.backups.dir)[-1]

        # The server process dies: it's restarted.
        dead = d.proc
        dead.proc.kill()
        dead.proc.wait(10)
        d._handle_crash()
        flowkit.wait_for(lambda: d.proc is not dead and d.proc.running and d.job is None, what="restart after a crash")
        assert any("crashed" in n and "restarting" in n for n in notes)

        # A scheduled backup comes due.
        m.config.schedule.backup = "* * * * *"
        d._sched_last = datetime.now() - timedelta(minutes=2)
        d._run_schedules()
        flowkit.wait_for(lambda: d.job is None and (d.last_job or {}).get("name") == "scheduled backup",
                         what="the scheduled backup")
        assert d.last_job["ok"] and "(checked)" in d.last_job["message"], d.last_job
        assert any(p.name.endswith("-scheduled.tar.gz") for p in backup.list_backups(m.config.backups.dir))
        m.config.schedule.backup = ""
        assert d.stop_server() == "stopped"
    finally:
        if d.proc and d.proc.running:
            d.proc.stop(10)

    # The world is damaged; restoring the backup brings it back.
    (world / "level.dat").write_bytes(b"corrupted")
    (world / "region" / "r.0.0.mca").unlink()
    snapshots.roll_back(manual, m)
    assert (world / "level.dat").read_bytes() == flowkit.LEVEL_DAT
    assert (world / "region" / "r.0.0.mca").exists()

    # The next Minecraft comes out, and the build for it doesn't start: rolled back.
    flowkit.publish(http, loader, nxt)
    m.mojang.set_releases([first, nxt])
    if mod_loader:
        flowkit.add_mod(modrinth, loader, "AAAAAAAA", nxt, "2.0", filename="crash-AAAAAAAA-2.0.jar")
    else:
        http.files[f"https://files.test/{nxt}/server.jar"] = CRASHING_SERVER_JAR
    result = flowkit.update(m)
    assert not result.ok and "rolled back" in result.message, result.message
    assert m.lock.minecraft == first and len(m.lock.failed_plans) == 1
    if mod_loader:
        assert (m.mods_dir / "AAAAAAAA-1.0.jar").exists()
        assert not (m.mods_dir / "crash-AAAAAAAA-2.0.jar").exists()
    assert (world / "level.dat").read_bytes() == flowkit.LEVEL_DAT
    assert not m.journal_path.exists()

    # ...and the rolled-back server is playable.
    proc = m.start_server()
    try:
        assert proc.running and proc.players_online() == 0
    finally:
        proc.stop(10)

    # A fixed build comes out: the update goes through, the world is kept.
    if mod_loader:
        flowkit.add_mod(modrinth, loader, "AAAAAAAA", nxt, "2.1")
        result = flowkit.update(m)
    else:
        http.files[f"https://files.test/{nxt}/server.jar"] = flowkit.SERVER_JAR
        result = flowkit.update(m, retry_failed=True)  # (the same plan failed before: retried by hand)
    assert result.ok, result.message
    assert m.lock.minecraft == nxt
    if mod_loader:
        assert (m.mods_dir / "AAAAAAAA-2.1.jar").exists() and not (m.mods_dir / "AAAAAAAA-1.0.jar").exists()
    assert (world / "level.dat").read_bytes() == flowkit.LEVEL_DAT
    proc = m.start_server()
    try:
        assert proc.running
    finally:
        proc.stop(10)


def test_a_server_that_keeps_crashing_is_given_up_on(tmp_path, http, modrinth, flow_java, quick_daemon):
    """Three crashes within ten minutes are restarted; the fourth isn't, and it says so."""
    m = flowkit.make_server(tmp_path / "s", http, modrinth, "fabric")
    assert flowkit.update(m).ok
    notes: list[str] = []
    m.notifier.listeners.append(notes.append)
    d = Daemon(m, autostart=False)
    d.stop_requested = flowkit.FastEvent()
    d.web_enabled = True  # (without the web page, giving up also stops Craft Conductor)
    d.start_server()
    try:
        for _ in range(daemonmod.MAX_CRASHES):
            dead = d.proc
            dead.proc.kill()
            dead.proc.wait(10)
            d._handle_crash()
            flowkit.wait_for(lambda: d.proc is not dead and d.proc.running and d.job is None, what="a restart")
        d.proc.proc.kill()
        d.proc.proc.wait(10)
        d._handle_crash()
        assert not d.want_running
        assert any("not restarting" in n for n in notes)
        assert d.job is None and not d.proc.running
    finally:
        if d.proc and d.proc.running:
            d.proc.stop(10)
