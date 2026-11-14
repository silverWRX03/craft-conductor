"""Restart with players on (#205): when the owner says Yes, they're told in game and given a minute.
Stop pressed during that minute stops the server instead."""
import threading
from types import SimpleNamespace

from craft_conductor import daemon


class FakeProc:
    def __init__(self):
        self.running, self.said = True, []

    def say(self, message):
        self.said.append(message)


class Clock:
    """daemon.time, with each wait moving the clock on instead of sleeping."""
    def __init__(self, monkeypatch, during=None):
        self.now, self.waited, self.during = 0.0, 0.0, during
        monkeypatch.setattr(daemon, "time", SimpleNamespace(monotonic=lambda: self.now))
        real_wait = threading.Event.wait

        def wait(event, timeout=None):
            if self.during and self.waited >= 10:
                self.during()
            self.now += timeout or 0
            self.waited += timeout or 0
            return real_wait(event, 0)
        monkeypatch.setattr(threading.Event, "wait", wait)


def fake_daemon(players):
    d = SimpleNamespace(proc=FakeProc(), players=set(players), stop_requested=threading.Event(), steps=[],
                        restart_warning=None, job={"name": "restart"})
    d.stop_server = lambda: d.steps.append("stop") or "stopped"
    d.start_server = lambda: d.steps.append("start") or "started"
    d.call_off_restart = lambda: daemon.Daemon.call_off_restart(d)
    return d


def test_players_on_are_warned_a_minute_before_the_restart(monkeypatch):
    clock, d = Clock(monkeypatch), fake_daemon({"Steve"})
    assert daemon.Daemon.restart_server(d, warn=True) == "started"
    assert d.proc.said == ["Server restarting in 60 seconds", "Restarting now!"]
    assert clock.waited == daemon.RESTART_WARNING == 60
    assert d.steps == ["stop", "start"]
    assert d.restart_warning is None and "can_stop" not in d.job


def test_stop_during_the_warning_stops_instead(monkeypatch):
    d = fake_daemon({"Steve"})
    seen = []
    clock = Clock(monkeypatch, during=lambda: seen.append((d.job.get("can_stop"), d.call_off_restart())))
    assert daemon.Daemon.restart_server(d, warn=True) == "stopped"
    assert seen[0] == (True, True) and clock.waited < 60
    assert d.steps == ["stop"] and d.proc.said == ["Server restarting in 60 seconds"]
    assert d.call_off_restart() is False  # (nothing to call off now: Stop is an ordinary stop again)


def test_closing_craft_conductor_during_the_warning_doesnt_start_it_again(monkeypatch):
    d = fake_daemon({"Steve"})
    Clock(monkeypatch, during=d.stop_requested.set)
    assert "closing" in daemon.Daemon.restart_server(d, warn=True)
    assert d.steps == []


def test_nobody_on_or_no_warning_asked_for_restarts_straight_away(monkeypatch):
    for players, warn in (((), True), ({"Steve"}, False)):
        clock, d = Clock(monkeypatch), fake_daemon(players)
        daemon.Daemon.restart_server(d, warn=warn)
        assert d.proc.said == [] and clock.waited == 0
        assert d.steps == ["stop", "start"]
