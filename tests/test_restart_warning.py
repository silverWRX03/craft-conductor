"""Restart with players on (#205): when the owner says Yes, they're told in game and given a minute."""
import threading
from types import SimpleNamespace

from craft_conductor import daemon


class FakeProc:
    def __init__(self):
        self.running, self.said = True, []

    def say(self, message):
        self.said.append(message)


class FakeEvent(threading.Event):
    def __init__(self):
        super().__init__()
        self.waited = []

    def wait(self, timeout=None):
        self.waited.append(timeout)
        return False


def fake_daemon(players):
    d = SimpleNamespace(proc=FakeProc(), players=set(players), stop_requested=FakeEvent(), steps=[])
    d.stop_server = lambda: d.steps.append("stop")
    d.start_server = lambda: d.steps.append("start") or "started"
    return d


def test_players_on_are_warned_a_minute_before_the_restart():
    d = fake_daemon({"Steve"})
    assert daemon.Daemon.restart_server(d, warn=True) == "started"
    assert d.proc.said == ["Server restarting in 60 seconds", "Restarting now!"]
    assert d.stop_requested.waited == [daemon.RESTART_WARNING] == [60]
    assert d.steps == ["stop", "start"]


def test_nobody_on_or_no_warning_asked_for_restarts_straight_away():
    for players, warn in (((), True), ({"Steve"}, False)):
        d = fake_daemon(players)
        daemon.Daemon.restart_server(d, warn=warn)
        assert d.proc.said == [] and d.stop_requested.waited == []
        assert d.steps == ["stop", "start"]
