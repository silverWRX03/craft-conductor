"""`craft-conductor uninstall` (roadmap 38): the command on top of uninstall.py.

Everything runs in a temporary home, with the person's folders (HOME, USERPROFILE, APPDATA, ...)
pointed into it too (R17), and a runner that only records, or one that only deletes inside the
temporary folder. Nothing on this computer (registry, firewall, services, the real Craft Conductor)
is touched. "Running" servers and panels are small Python processes standing in for them.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from craft_conductor import cli, daemon, folders, uninstall
from craft_conductor.uninstall import Choices

TOML = '[server]\nloader = "vanilla"\nminecraft = "1.21.1"\n'
REPORT = "Craft Conductor uninstall report.txt"


class FakeRunner:
    """Records every call; deletes nothing. ``fail``: paths whose deletion raises."""

    def __init__(self, fail=()):
        self.calls: list[tuple] = []
        self.fail = {Path(p) for p in fail}

    def run(self, argv, *, elevated=False, detached=False):
        self.calls.append(("run", list(argv), elevated, detached))
        return 0

    def delete_tree(self, path):
        self.calls.append(("delete_tree", Path(path)))
        if Path(path) in self.fail:
            raise PermissionError(13, "The file is in use", str(path))

    def delete_file(self, path):
        self.calls.append(("delete_file", Path(path)))
        if Path(path) in self.fail:
            raise PermissionError(13, "The file is in use", str(path))

    def registry_delete(self, key):
        self.calls.append(("registry_delete", key))

    def deleted(self) -> list[Path]:
        return [c[1] for c in self.calls if c[0] in ("delete_tree", "delete_file")]

    def gone(self, path: Path) -> bool:
        """``path`` was deleted, itself or with a folder holding it."""
        return any(path == d or path.is_relative_to(d) for d in self.deleted())


class TmpRunner(FakeRunner):
    """Deletes for real, but only inside the test's temporary folder (anything else fails the test)."""

    def __init__(self, inside: Path):
        super().__init__()
        self.inside = inside.resolve()

    def _check(self, path):
        assert Path(path).resolve().is_relative_to(self.inside), path

    def delete_tree(self, path):
        super().delete_tree(path)
        self._check(path)
        shutil.rmtree(path)

    def delete_file(self, path):
        super().delete_file(path)
        self._check(path)
        Path(path).unlink()


def _server(root: Path, port: int | None = None) -> Path:
    (root / "server" / "world").mkdir(parents=True)
    (root / "server" / "world" / "level.dat").write_bytes(b"level")
    if port:
        (root / "server" / "server.properties").write_text(f"server-port={port}\n", encoding="utf-8")
    (root / "craft-conductor.toml").write_text(TOML, encoding="utf-8")
    return root


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A person's home folder (every folder variable pointed into it) with a Craft Conductor home:
    state with the lock key, two servers (alpha with backups), exports; a Downloads folder."""
    user = tmp_path / "user"
    cc = user / "craft-conductor"
    state = cc / ".craft-conductor"
    (state / "java" / "21").mkdir(parents=True)
    (state / "hub.json").write_text("{}", encoding="utf-8")
    (state / "backup.key").write_bytes(b"k" * 32)
    alpha = _server(cc / "servers" / "alpha")
    (alpha / "backups").mkdir()
    (alpha / "backups" / "alpha-1.tar.gz").write_bytes(b"backup")
    beta = _server(cc / "servers" / "beta")
    (cc / "exports").mkdir()
    (cc / "exports" / "alpha.craft-conductor.zip").write_bytes(b"zip")
    downloads = user / "Downloads"
    downloads.mkdir()
    for name, value in {"HOME": user, "USERPROFILE": user, "APPDATA": user / "AppData" / "Roaming",
                        "LOCALAPPDATA": user / "AppData" / "Local", "XDG_CONFIG_HOME": user / ".config",
                        "XDG_DATA_HOME": user / ".local" / "share", "CRAFT_CONDUCTOR_HOME": cc}.items():
        monkeypatch.setenv(name, str(value))
    monkeypatch.delenv("CRAFT_CONDUCTOR_CONTAINER", raising=False)
    monkeypatch.setattr(folders, "downloads_dir", lambda *a, **k: downloads)
    monkeypatch.setattr(uninstall, "_frozen", lambda: False)
    monkeypatch.setattr(uninstall, "_prefix", lambda: str(tmp_path / "venv"))
    monkeypatch.setattr(cli, "interactive", lambda: False)
    monkeypatch.setattr(cli, "_server_status", lambda root: None)  # (no Minecraft answering on any port)
    runner = FakeRunner()
    monkeypatch.setattr(cli, "uninstall_runner", lambda: runner)
    monkeypatch.chdir(tmp_path)
    return SimpleNamespace(tmp=tmp_path, user=user, home=cc, state=state, alpha=alpha, beta=beta,
                           exports=cc / "exports", downloads=downloads, runner=runner)


def _answers(monkeypatch, *answers):
    """The person at the terminal, answering in turn; the questions asked are kept."""
    asked, left = [], list(answers)
    monkeypatch.setattr(cli, "interactive", lambda: True)

    def answer(prompt=""):
        asked.append(prompt)
        return left.pop(0)
    monkeypatch.setattr("builtins.input", answer)
    return asked


FAKE_DAEMON = """\
import os, pathlib, sys, time
state, mode, got = pathlib.Path(sys.argv[1]), sys.argv[2], pathlib.Path(sys.argv[3])
(state / "daemon.pid").write_text(str(os.getpid()))
request = state / "stop-requested"
end = time.time() + 60
while time.time() < end:
    if mode == "obey" and request.exists():
        got.write_text(request.read_text(encoding="utf-8"), encoding="utf-8")
        request.unlink()
        (state / "daemon.pid").unlink()
        sys.exit(0)
    time.sleep(0.05)
"""


@pytest.fixture
def running(tmp_path):
    """Start a stand-in for `craft-conductor run` looking after a server: it writes its pid where the
    real one does and, with "obey", stops (and notes what it was asked) when asked; with "ignore" it
    doesn't. Returns the file the request is copied to."""
    procs = []
    script = tmp_path / "fake_daemon.py"
    script.write_text(FAKE_DAEMON, encoding="utf-8")

    def start(root: Path, mode: str = "obey") -> Path:
        state = root / ".craft-conductor"
        state.mkdir(parents=True, exist_ok=True)
        got = tmp_path / f"got-{root.name}.txt"
        p = subprocess.Popen([sys.executable, str(script), str(state), mode, str(got)], cwd=tmp_path)
        procs.append(p)
        threading.Thread(target=p.wait, daemon=True).start()  # (reaped as soon as it exits: no zombie)
        end = time.monotonic() + 20
        while not (state / "daemon.pid").exists() and time.monotonic() < end:
            time.sleep(0.05)
        return got
    yield start
    for p in procs:
        p.kill()


# ------------------------------------------------------------------ the plan, and doing it
def test_without_yes_it_prints_the_plan_and_changes_nothing(home, capsys):
    assert cli.main(["uninstall"]) == 0
    out = capsys.readouterr().out
    assert str(home.home) in out
    assert "Settings and state" in out and str(home.state) in out
    assert "Servers and worlds" in out and "--delete-servers" in out  # (kept, and how to delete them)
    assert "Nothing was changed" in out and "--yes" in out
    assert home.runner.calls == []
    assert home.state.is_dir() and not (home.downloads / REPORT).exists()


def test_the_plan_warns_about_the_lock_key_unless_its_kept(home, capsys):
    assert cli.main(["uninstall"]) == 0
    out = capsys.readouterr().out
    assert "won't open anywhere" in out and "--keep-lockbox-key" in out
    assert cli.main(["uninstall", "--keep-lockbox-key"]) == 0
    assert "won't open anywhere" not in capsys.readouterr().out


def test_yes_removes_the_state_and_keeps_what_isnt_ticked(home, monkeypatch, capsys):
    runner = TmpRunner(home.tmp)
    monkeypatch.setattr(cli, "uninstall_runner", lambda: runner)
    assert cli.main(["uninstall", "--yes"]) == 0
    out = capsys.readouterr().out
    assert not home.state.exists()
    for kept in (home.alpha / "server" / "world" / "level.dat", home.alpha / "backups" / "alpha-1.tar.gz",
                 home.beta / "craft-conductor.toml", home.exports / "alpha.craft-conductor.zip"):
        assert kept.exists(), kept
    assert "Craft Conductor uninstall report" in out and "Removed:" in out
    saved = home.downloads / REPORT
    assert saved.is_file()  # (things are left for the person: the program, phones, browsers...)
    assert "Left for you to do" in saved.read_text(encoding="utf-8") and str(saved) in out


def test_delete_everything_leaves_nothing_of_the_home(home, monkeypatch, capsys):
    """Every box ticked, and the home in its usual place (~/craft-conductor): the emptied folder goes too."""
    monkeypatch.delenv("CRAFT_CONDUCTOR_HOME")
    runner = TmpRunner(home.tmp)
    monkeypatch.setattr(cli, "uninstall_runner", lambda: runner)
    assert cli.main(["uninstall", "--yes", "--delete-servers", "--delete-backups", "--delete-exports",
                     "--delete-games"]) == 0
    assert not home.home.exists()
    assert home.user.is_dir() and (home.downloads / REPORT).is_file()
    assert f"deleted the empty folder {home.home}" in capsys.readouterr().out


def test_a_home_elsewhere_isnt_removed_even_when_empty(home, monkeypatch):
    """CRAFT_CONDUCTOR_HOME may be a folder the person made for something else too: it's left."""
    other = home.tmp / "someone"  # (so ~/craft-conductor isn't this home)
    other.mkdir()
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(other))
    runner = TmpRunner(home.tmp)
    monkeypatch.setattr(cli, "uninstall_runner", lambda: runner)
    assert cli.main(["uninstall", "--yes", "--delete-servers", "--delete-backups", "--delete-exports"]) == 0
    assert home.home.is_dir() and not any(home.home.iterdir())


@pytest.mark.parametrize("flags, choices", [
    ([], Choices()),
    (["--delete-servers"], Choices(servers=True)),
    (["--delete-backups"], Choices(backups=True)),
    (["--delete-exports"], Choices(exports=True)),
    (["--delete-games"], Choices(games=True)),
    (["--keep-lockbox-key"], Choices(keep_lockbox_key=True)),
    (["--delete-servers", "--delete-backups", "--delete-exports", "--delete-games", "--keep-lockbox-key"],
     Choices(True, True, True, True, True)),
])
def test_the_flags_are_the_choices_and_one_real_runner_plans_and_runs(home, monkeypatch, flags, choices):
    seen = {}
    real_plan, real_run = uninstall.plan, uninstall.run

    def plan(h, c, **kw):
        seen.update(home=Path(h), choices=c, plan_runner=kw.get("runner"))
        return real_plan(h, c, **kw)

    def run(parts, **kw):
        seen.update(run_runner=kw.get("runner"), stop=kw.get("stop_servers"))
        return real_run(parts, **kw)
    monkeypatch.setattr(uninstall, "plan", plan)
    monkeypatch.setattr(uninstall, "run", run)
    assert cli.main(["uninstall", "--yes", *flags]) == 0
    assert seen["choices"] == choices and seen["home"] == home.home
    assert seen["plan_runner"] is home.runner and seen["run_runner"] is home.runner  # (R14: probed, not guessed)
    assert callable(seen["stop"])


def test_the_exit_code_says_when_something_failed(home, monkeypatch, capsys):
    runner = FakeRunner(fail=[home.state])
    monkeypatch.setattr(cli, "uninstall_runner", lambda: runner)
    assert cli.main(["uninstall", "--yes"]) == 1
    out = capsys.readouterr().out
    assert "Couldn't be removed" in out and str(home.state) in out


def test_the_report_is_saved_only_when_something_is_left_to_do(home, monkeypatch, capsys):
    monkeypatch.setattr(uninstall, "run", lambda parts, **kw: uninstall.Report(removed=["Settings and state: deleted x"]))
    assert cli.main(["uninstall", "--yes"]) == 0
    assert "Settings and state: deleted x" in capsys.readouterr().out
    assert not (home.downloads / REPORT).exists()


def test_without_a_downloads_folder_the_report_is_only_printed(home, monkeypatch, capsys):
    monkeypatch.setattr(folders, "downloads_dir", lambda *a, **k: None)
    assert cli.main(["uninstall", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "Left for you to do" in out and "couldn't be saved" in out


def test_it_isnt_held_back_by_the_first_run_notice(home, monkeypatch, capsys):
    from craft_conductor import notice
    monkeypatch.setattr(notice, "accepted", lambda root=None: False)
    assert cli.main(["uninstall"]) == 0
    assert "Settings and state" in capsys.readouterr().out


# ------------------------------------------------------------------ asking
def test_interactively_it_asks_before_doing_anything(home, monkeypatch, capsys):
    asked = _answers(monkeypatch, "n")
    assert cli.main(["uninstall"]) == 1
    assert len(asked) == 1 and home.runner.calls == []
    assert "Nothing was changed" in capsys.readouterr().out
    _answers(monkeypatch, "y")
    assert cli.main(["uninstall"]) == 0 and home.state in home.runner.deleted()


def test_deleting_servers_interactively_needs_a_second_confirmation_naming_servers_and_worlds(home, monkeypatch, capsys):
    asked = _answers(monkeypatch, "y", "yes")
    assert cli.main(["uninstall", "--delete-servers"]) == 1
    assert "2 servers" in asked[1] and "2 worlds" in asked[1]
    assert home.runner.calls == [] and "Nothing was changed" in capsys.readouterr().out
    _answers(monkeypatch, "y", "2")
    assert cli.main(["uninstall", "--delete-servers"]) == 0
    assert home.runner.gone(home.alpha / "server" / "world") and home.runner.gone(home.beta)


def test_with_yes_the_flags_are_the_confirmation(home, monkeypatch):
    asked = _answers(monkeypatch)  # (any question would fail: nothing left to answer)
    assert cli.main(["uninstall", "--yes", "--delete-servers"]) == 0
    assert asked == [] and home.runner.gone(home.alpha / "server" / "world")


# ------------------------------------------------------------------ another Craft Conductor running
def test_a_control_panel_running_on_the_same_home_is_refused_with_how_to_stop_it(home, tmp_path, capsys):
    panel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], cwd=tmp_path)
    try:
        (home.state / "hub.pid").write_text(str(panel.pid))
        assert cli.main(["uninstall", "--yes", "--delete-servers"]) == 1
    finally:
        panel.kill()
        panel.wait()
    out = capsys.readouterr().out
    assert str(panel.pid) in out and "craft-conductor stop" in out and "Quit" in out
    assert home.runner.calls == [] and home.state.is_dir()


def test_a_stale_panel_record_doesnt_block_it(home):
    (home.state / "hub.pid").write_text("999999999")
    assert cli.main(["uninstall", "--yes"]) == 0


# ------------------------------------------------------------------ stopping servers
def test_running_servers_are_stopped_cleanly_with_the_warning_first(home, running, capsys):
    got = running(home.alpha)
    assert cli.main(["uninstall", "--yes", "--delete-servers"]) == 0
    words = got.read_text(encoding="utf-8")
    assert words.startswith("stop") and cli.UNINSTALL_WARNING in words  # (the daemon warns players with it)
    out = capsys.readouterr().out
    assert "still running" not in out
    assert home.runner.gone(home.alpha / "server" / "world")


def test_a_server_with_players_is_asked_about_first(home, monkeypatch, running, capsys):
    got = running(home.alpha)
    monkeypatch.setattr(cli, "_server_status", lambda root: {"online": 3} if root == home.alpha else None)
    asked = _answers(monkeypatch, "y", "n")
    assert cli.main(["uninstall"]) == 1
    assert "3 players" in asked[1] and "alpha" in asked[1]
    assert home.runner.calls == [] and not got.exists()  # (not asked to stop: nothing changed)
    assert "Nothing was changed" in capsys.readouterr().out


def test_with_yes_a_server_with_players_is_stopped_with_the_warning(home, monkeypatch, running, capsys):
    got = running(home.alpha)
    monkeypatch.setattr(cli, "_server_status", lambda root: {"online": 3} if root == home.alpha and not got.exists() else None)
    asked = _answers(monkeypatch)
    assert cli.main(["uninstall", "--yes"]) == 0
    assert asked == [] and cli.UNINSTALL_WARNING in got.read_text(encoding="utf-8")
    assert "3 players" in capsys.readouterr().out  # (the plan says who's on)


def test_a_server_that_wont_stop_is_kept_and_the_exit_code_says_so(home, monkeypatch, running, capsys):
    running(home.alpha, "ignore")
    monkeypatch.setattr(cli, "UNINSTALL_STOP_UNANSWERED", 0.5)
    assert cli.main(["uninstall", "--yes", "--delete-servers", "--delete-backups"]) == 1
    assert not home.runner.gone(home.alpha / "server") and not home.runner.gone(home.alpha / "backups")
    assert home.runner.gone(home.beta) and home.runner.gone(home.state)
    out = capsys.readouterr().out
    assert f"the server in {home.alpha} is still running" in out
    assert not (home.alpha / ".craft-conductor" / "stop-requested").exists()  # (the unanswered request isn't left behind)


def test_a_server_answering_with_nothing_looking_after_it_is_kept(home, monkeypatch, capsys):
    """Its port answers like a Minecraft server but no `craft-conductor run` looks after it (left over after
    Craft Conductor was killed): it can't be stopped from here, so it isn't deleted."""
    monkeypatch.setattr(cli, "_server_status", lambda root: {"online": 0} if root == home.beta else None)
    assert cli.main(["uninstall", "--yes", "--delete-servers"]) == 1
    assert not home.runner.gone(home.beta / "server") and home.runner.gone(home.alpha / "server" / "world")
    assert f"the server in {home.beta} is still running" in capsys.readouterr().out


def test_the_stop_callback_returns_the_server_folders_the_plan_uses(home, running):
    """run() matches what's still running against the inventory's server folders exactly (R13)."""
    running(home.alpha, "ignore")
    stopped = cli._stop_for_uninstall(list(uninstall.servers_of(home.home).values()), check_ports=False, unanswered=0.5)
    assert stopped == [home.alpha]
    assert {Path(p) for p in stopped} <= set(uninstall.servers_of(home.home).values())


# ------------------------------------------------------------------ a server run the classic way (R11)
def test_a_server_run_with_craft_conductor_run_is_its_own_home(home, tmp_path, monkeypatch, capsys):
    """`craft-conductor run` in a folder keeps its state in that folder (config.state_dir): that's what goes."""
    classic = _server(tmp_path / "classic")
    (classic / ".craft-conductor").mkdir()
    (classic / ".craft-conductor" / "daemon.log").write_text("log", encoding="utf-8")
    runner = TmpRunner(home.tmp)
    monkeypatch.setattr(cli, "uninstall_runner", lambda: runner)
    assert cli.main(["-C", str(classic), "uninstall", "--yes"]) == 0
    assert not (classic / ".craft-conductor").exists()
    assert (classic / "server" / "world" / "level.dat").exists() and (classic / "craft-conductor.toml").exists()
    assert home.state.is_dir()  # (the control panel's home isn't this one)
    assert str(classic) in capsys.readouterr().out


def test_a_server_of_the_home_run_from_its_own_folder_uninstalls_the_home(home, monkeypatch):
    monkeypatch.chdir(home.alpha)
    assert cli.main(["uninstall", "--yes"]) == 0
    assert home.state in home.runner.deleted()


# ------------------------------------------------------------------ the daemon's side of the warning
def test_a_stop_request_with_a_warning_tells_the_players_and_gives_them_a_minute(tmp_path, monkeypatch):
    said, waited = [], []
    m = SimpleNamespace(config=SimpleNamespace(state_dir=tmp_path))
    d = daemon.Daemon(m, autostart=False)
    d.proc = SimpleNamespace(running=True, say=said.append)
    monkeypatch.setattr(d.stop_requested, "wait", lambda seconds=None: waited.append(seconds))
    d.players = {"Steve"}
    daemon.request_stop_in(tmp_path, "Craft Conductor is being removed")
    d._take_stop_request()
    assert said == ["Server stopping in 1 minute: Craft Conductor is being removed", "Stopping now!"]
    assert waited == [daemon.STOP_WARNING] and not daemon.stop_request_path(m).exists()
    said.clear(), waited.clear()
    d.players = set()  # (nobody on: nobody to warn, no wait)
    daemon.request_stop_in(tmp_path, "Craft Conductor is being removed")
    d._take_stop_request()
    assert said == [] and waited == []
    daemon.request_stop(m)  # (the plain request, as `craft-conductor stop` makes it: no warning)
    d.players = {"Steve"}
    d._take_stop_request()
    assert said == [] and waited == []
