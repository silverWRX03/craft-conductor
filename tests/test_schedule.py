"""Schedules (restarts and backups at set times) and backup copies to another folder."""

import datetime as dt

import pytest

from craft_conductor import backup, schedule
from craft_conductor.config import ConfigError, parse

from test_hub import login

T = dt.datetime(2026, 9, 28, 4, 0)  # a Monday, 4:00


def test_cron_matches_and_next():
    daily = schedule.Cron("0 4 * * *")
    assert daily.matches(T) and not daily.matches(T.replace(minute=1))
    assert daily.next_after(T) == T + dt.timedelta(days=1)
    every6 = schedule.Cron("0 */6 * * *")
    assert [h for h in range(24) if every6.matches(T.replace(hour=h))] == [0, 6, 12, 18]
    weekdays = schedule.Cron("30 5 * * mon-fri")
    assert weekdays.matches(dt.datetime(2026, 9, 28, 5, 30)) and not weekdays.matches(dt.datetime(2026, 9, 27, 5, 30))
    sunday = schedule.Cron("0 4 * * 7")
    assert sunday.matches(dt.datetime(2026, 9, 27, 4, 0))  # 7 is Sunday too
    assert schedule.describe("0 4 * * *") == "every day at 4:00"
    assert schedule.describe("15 22 * * 5") == "every Friday at 22:15"
    assert schedule.describe("0 */6 * * *") == "every 6 hours"
    assert schedule.describe("") == "off"
    for bad in ("0 4 * *", "61 4 * * *", "0 25 * * *", "x 4 * * *", "0 4 * * 8"):
        with pytest.raises(schedule.CronError):
            schedule.Cron(bad)


def test_due_neither_misses_nor_repeats_a_minute():
    expr = "0 4 * * *"
    assert schedule.due(expr, T - dt.timedelta(seconds=30), T)          # woke up on time
    assert schedule.due(expr, T - dt.timedelta(minutes=2), T + dt.timedelta(minutes=1))  # woke a bit late
    assert not schedule.due(expr, T, T + dt.timedelta(seconds=40))      # same minute again
    assert not schedule.due(expr, T - dt.timedelta(hours=5), T + dt.timedelta(hours=1))  # asleep: not hours later
    assert not schedule.due("", T - dt.timedelta(minutes=1), T)


def test_config_checks_schedules_and_the_copy_folder(tmp_path):
    base = {"server": {"loader": "fabric"}}
    c = parse(tmp_path, {**base, "schedule": {"restart": "0 4 * * *", "backup": "0 */6 * * *"}})
    assert c.schedule.restart == "0 4 * * *" and c.schedule.backup == "0 */6 * * *" and not c.schedule.restart_when_empty
    with pytest.raises(ConfigError, match="schedule.restart"):
        parse(tmp_path, {**base, "schedule": {"restart": "every night"}})
    with pytest.raises(ConfigError, match="full path"):
        parse(tmp_path, {**base, "backups": {"copy_to": "relative/folder"}})
    assert parse(tmp_path, {**base, "backups": {"copy_to": str(tmp_path / "usb")}}).backups.copy_to == tmp_path / "usb"


def test_backup_copies(tmp_path):
    archive = tmp_path / "20260928-040000-scheduled.tar.gz"
    archive.write_bytes(b"backup")
    assert backup.copy_out(archive, tmp_path / "unplugged", "Survival") is None  # the drive isn't there: logged, no error
    usb = tmp_path / "usb"
    usb.mkdir()
    for i in range(4):
        a = tmp_path / f"2026092{i}-040000-scheduled.tar.gz"
        a.write_bytes(b"x")
        backup.copy_out(a, usb, "Survival", keep=2)
    assert sorted(p.name for p in (usb / "Survival").iterdir()) == ["20260922-040000-scheduled.tar.gz", "20260923-040000-scheduled.tar.gz"]


def _scheduled_daemon(tmp_path, monkeypatch, restart="", backup="", when_empty=False):
    """A daemon (its loop not running) with these schedules, a stand-in for the running server, and
    a clock to move: what it would start is listed in ``jobs``."""
    from types import SimpleNamespace
    from craft_conductor.config import ScheduleConfig
    from craft_conductor.daemon import Daemon
    clock = [T]
    monkeypatch.setattr(schedule.dt, "datetime", type("FakeNow", (dt.datetime,), {"now": classmethod(lambda cls: clock[0])}))
    m = SimpleNamespace(config=SimpleNamespace(state_dir=tmp_path, schedule=ScheduleConfig(restart, backup, when_empty)))
    d = Daemon(m, autostart=False)
    d.proc = SimpleNamespace(running=True, stopping=False)
    d.want_running = True
    jobs = []
    monkeypatch.setattr(d, "submit", lambda name, fn, *a: jobs.append(name) or True)
    return d, clock, jobs


def test_a_restart_and_a_backup_due_together_both_happen(tmp_path, monkeypatch):
    """Backups every hour and a restart every night at 4:00: at 4:00 the backup is made, then the
    server restarts (it used to skip the restart, every night)."""
    d, clock, jobs = _scheduled_daemon(tmp_path, monkeypatch, restart="0 4 * * *", backup="0 * * * *")
    d._sched_last = T - dt.timedelta(minutes=1)
    d._run_schedules()
    assert jobs == ["scheduled backup"]
    clock[0] = T + dt.timedelta(minutes=1)  # (the backup's job is done)
    d._run_schedules()
    assert jobs == ["scheduled backup", "scheduled restart"]
    clock[0] = T + dt.timedelta(minutes=2)
    d._run_schedules()
    assert jobs == ["scheduled backup", "scheduled restart"]  # once


def test_a_time_that_comes_during_a_long_job_isnt_skipped(tmp_path, monkeypatch):
    """A backup due at 4:00 while an update runs from 3:58 to 4:20 is made at 4:20 (it used to be
    skipped: 20 minutes without a look counted as the computer having been asleep)."""
    d, clock, jobs = _scheduled_daemon(tmp_path, monkeypatch, backup="0 4 * * *")
    d._sched_last = T - dt.timedelta(minutes=2)
    for minute in range(0, 20):  # (the loop looks every couple of seconds, busy or not)
        clock[0] = T + dt.timedelta(minutes=minute)
        d._run_schedules(idle=False)
    assert jobs == []
    clock[0] = T + dt.timedelta(minutes=20)
    d._run_schedules()
    assert jobs == ["scheduled backup"]
    # Asleep for hours (no look at all): a time that passed meanwhile isn't made up.
    d._sched_last = T + dt.timedelta(minutes=21)
    clock[0] = T + dt.timedelta(days=1, hours=3)
    d._run_schedules()
    assert jobs == ["scheduled backup"]


def test_an_owed_restart_isnt_done_twice_or_for_nothing(tmp_path, monkeypatch):
    """A restart that came due during a long job isn't done once the server was restarted since (the
    update itself did), nor while players are on with "skip while players are online", nor for a
    server that was stopped meanwhile."""
    d, clock, jobs = _scheduled_daemon(tmp_path, monkeypatch, restart="0 4 * * *")
    d._sched_last = T - dt.timedelta(minutes=1)
    d._run_schedules(idle=False)  # 4:00, while an update runs
    d.started_at = (T + dt.timedelta(minutes=5)).timestamp()  # (the update started the new version at 4:05)
    clock[0] = T + dt.timedelta(minutes=6)
    d._run_schedules()
    assert jobs == []
    clock[0] = T + dt.timedelta(days=1)
    d._run_schedules(idle=False)  # the next night, busy again
    d.players = {"Steve"}
    d.m.config.schedule.restart_when_empty = True
    clock[0] = T + dt.timedelta(days=1, minutes=3)
    d._run_schedules()
    assert jobs == []
    d.players = set()
    clock[0] = T + dt.timedelta(days=2)
    d._run_schedules(idle=False)
    d.want_running = False  # (stopped by hand meanwhile)
    clock[0] = T + dt.timedelta(days=2, minutes=1)
    d._run_schedules()
    assert jobs == []


def test_settings_and_the_daemon(hub_env, monkeypatch):
    hub, c = hub_env
    login(c)
    usb = hub.home / "usb"
    usb.mkdir()
    ok = c.post("/api/servers/alpha/settings", {"schedule_restart": "0 4 * * *", "schedule_backup": "0 */6 * * *",
                                                "restart_when_empty": True, "backup_copy_to": str(usb)})
    assert ok[0] == 200, ok
    s = c.get("/api/servers/alpha/settings")[1]
    assert s["schedule_restart_words"] == "every day at 4:00" and s["schedule_restart_next"] and s["backup_copy_ok"]
    assert c.post("/api/servers/alpha/settings", {"schedule_backup": "sometimes"})[0] == 400  # not a schedule

    d = hub.get("alpha")
    jobs = []
    monkeypatch.setattr(d, "submit", lambda name, fn, *a: jobs.append(name) or True)
    d._sched_last = T.replace(hour=5, minute=59)
    monkeypatch.setattr(schedule.dt, "datetime", type("FakeNow", (dt.datetime,), {"now": classmethod(lambda cls: T.replace(hour=6))}))
    d._run_schedules()
    assert jobs == ["scheduled backup"]
    # Due while another job runs (an update, a rehearsal): it's made afterwards, not skipped.
    busy = [True]
    monkeypatch.setattr(d, "submit", lambda name, fn, *a: (jobs.append(name), not busy[0])[1])
    d._sched_last = T.replace(hour=5, minute=59)
    d._run_schedules()
    assert d._backup_owed
    busy[0] = False
    d._run_schedules()  # (nothing new is due by now)
    assert not d._backup_owed and jobs == ["scheduled backup"] * 3
