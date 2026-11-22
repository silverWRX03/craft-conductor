"""The uninstall inventory, plan and safety rules (roadmap 38).

Everything here runs in a temporary home with a fake runner that only records what it was asked
to do: nothing on this computer (registry, firewall, services, the real Craft Conductor) is touched.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

from craft_conductor import uninstall
from craft_conductor.uninstall import Choices


TOML = '[server]\nloader = "vanilla"\nminecraft = "1.21.1"\n'


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


def _server(root: Path, extra: str = "") -> Path:
    (root / "server" / "world").mkdir(parents=True)
    (root / "server" / "world" / "level.dat").write_bytes(b"level")
    (root / "craft-conductor.toml").write_text(TOML + extra, encoding="utf-8")
    return root


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A person's home folder with a Craft Conductor home in it: state, two servers (one with
    backups in its own folder), exports."""
    user = tmp_path / "user"
    home = user / "craft-conductor"
    state = home / ".craft-conductor"
    (state / "java" / "21").mkdir(parents=True)
    (state / "tools").mkdir()
    (state / "tools" / "cloudflared.exe").write_bytes(b"cf")
    (state / "hub.json").write_text("{}", encoding="utf-8")
    (state / "backup.key").write_bytes(b"k" * 32)
    alpha = _server(home / "servers" / "alpha")
    (alpha / "backups").mkdir()
    (alpha / "backups" / "alpha-1.tar.gz").write_bytes(b"backup")
    beta = _server(home / "servers" / "beta")
    (home / "exports").mkdir()
    (home / "exports" / "alpha.zip").write_bytes(b"zip")
    env = {"HOME": str(user), "USERPROFILE": str(user)}
    # (the program part: a pip install, unless a test says otherwise)
    monkeypatch.setattr(uninstall, "_frozen", lambda: False)
    monkeypatch.setattr(uninstall, "_prefix", lambda: str(tmp_path / "venv"))
    return {"user": user, "home": home, "state": state, "alpha": alpha, "beta": beta, "env": env}


def _parts(world, **choices) -> dict[str, uninstall.Part]:
    plan = uninstall.plan(world["home"], Choices(**choices), env=world["env"])
    return {p.key: p for p in plan}


# ------------------------------------------------------------------ the plan
def test_nothing_ticked_removes_the_state_and_keeps_servers_backups_and_exports(world):
    parts = _parts(world)
    assert not parts["state"].kept and parts["state"].present
    assert parts["state"].paths == [world["state"]]
    assert not parts["lockbox"].kept  # (off means the key is deleted)
    for key in ("servers", "backups", "exports"):
        assert parts[key].present and parts[key].kept, key
    assert "Java" in parts["state"].action and "cloudflared" in parts["state"].action


def test_the_plan_is_in_the_fixed_order(world):
    keys = [p.key for p in uninstall.plan(world["home"], Choices(), env=world["env"])]
    known = [k for k in uninstall.ORDER if k in keys]
    assert keys == known
    assert keys.index("exports") < keys.index("backups") < keys.index("servers") < keys.index("state") < keys.index("program")


@pytest.mark.parametrize("ticked", ["servers", "backups", "exports"])
def test_ticking_one_flips_only_it(world, ticked):
    parts = _parts(world, **{ticked: True})
    for key in ("servers", "backups", "exports"):
        assert parts[key].kept is (key != ticked), key
    assert not parts["state"].kept


def test_kept_backups_inside_a_server_survive_deleting_the_servers(world):
    parts = _parts(world, servers=True)
    paths = parts["servers"].paths
    alpha = world["alpha"]
    assert alpha / "backups" not in paths
    assert not any(p in (alpha, alpha.parent) for p in paths)  # (not the folders that hold the backups)
    assert alpha / "server" in paths and alpha / "craft-conductor.toml" in paths
    assert world["beta"] in paths


def test_servers_and_backups_both_ticked_delete_the_whole_servers_folder(world):
    parts = _parts(world, servers=True, backups=True)
    assert parts["servers"].paths == [world["home"] / "servers"]
    assert parts["backups"].paths == [world["alpha"] / "backups"]


def test_a_servers_folder_with_something_else_in_it_is_not_deleted_whole(world):
    (world["home"] / "servers" / "notes.txt").write_text("mine", encoding="utf-8")
    parts = _parts(world, servers=True, backups=True)
    assert sorted(parts["servers"].paths) == sorted([world["alpha"], world["beta"]])


def test_places_from_hub_json_and_a_backup_copy_folder(world, tmp_path):
    elsewhere = tmp_path / "games" / "servers"
    gamma = _server(elsewhere / "gamma")
    extra = _server(tmp_path / "loose" / "delta")
    chosen_backups = tmp_path / "backups-folder"
    (chosen_backups / "gamma").mkdir(parents=True)
    usb = tmp_path / "usb"
    (usb / "gamma").mkdir(parents=True)
    from craft_conductor import backup
    (usb / "gamma" / backup.COPY_OWNER).write_text(backup.copy_owner(gamma), encoding="utf-8")
    (usb / "someone-else").mkdir()
    (usb / "someone-else" / backup.COPY_OWNER).write_text("0" * 32, encoding="utf-8")
    (gamma / "craft-conductor.toml").write_text(
        TOML + f'[backups]\ndir = {json.dumps(str(chosen_backups / "gamma"))}\ncopy_to = {json.dumps(str(usb))}\n',
        encoding="utf-8")
    exports = tmp_path / "exports-folder"
    exports.mkdir()
    (world["state"] / "hub.json").write_text(json.dumps({
        "locations": {"servers": str(elsewhere), "backups": str(chosen_backups), "exports": str(exports), "chosen": True},
        "extra": [str(extra)]}), encoding="utf-8")
    parts = _parts(world, servers=True, backups=True, exports=True)
    assert sorted(parts["servers"].paths) == sorted([elsewhere, extra])
    assert sorted(parts["backups"].paths) == sorted([chosen_backups, usb / "gamma"])  # (not the USB folder, nor another's copies)
    assert parts["exports"].paths == [exports]
    assert world["alpha"] not in parts["servers"].paths  # (the old default folder isn't the servers folder any more)


def test_keeping_the_lockbox_key_keeps_it_out_of_the_state(world):
    parts = _parts(world, keep_lockbox_key=True)
    assert parts["lockbox"].kept
    state_paths = parts["state"].paths
    assert world["state"] not in state_paths and world["state"] / "backup.key" not in state_paths
    assert world["state"] / "hub.json" in state_paths and world["state"] / "java" in state_paths


def test_a_home_with_nothing_in_it_plans_nothing_present(tmp_path, monkeypatch):
    monkeypatch.setattr(uninstall, "_frozen", lambda: False)
    parts = {p.key: p for p in uninstall.plan(tmp_path / "nothing", Choices(), env={"HOME": str(tmp_path)})}
    for key in ("servers", "backups", "exports", "lockbox", "state"):
        assert not parts[key].present, key


# ------------------------------------------------------------------ safety
def test_safe_to_delete_refuses_the_home_folder_and_what_holds_it(world):
    user = world["user"]
    assert not uninstall.safe_to_delete(user, user, [user])
    assert not uninstall.safe_to_delete(user.parent, user, [user.parent])


def test_safe_to_delete_refuses_drive_roots(world):
    root = Path(world["user"].anchor)
    assert not uninstall.safe_to_delete(root, world["user"], [root])
    assert not uninstall.safe_to_delete(Path("/"), world["user"], [Path("/")])


def test_safe_to_delete_refuses_system_folders(world):
    system = Path(os.environ.get("SystemRoot", r"C:\Windows")) if os.name == "nt" else Path("/usr")
    if not system.is_dir():
        pytest.skip("no system folder here")
    assert not uninstall.safe_to_delete(system, world["user"], [system])


def test_safe_to_delete_refuses_what_is_outside_the_known_places(world, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    assert not uninstall.safe_to_delete(other, world["user"], [world["home"] / "servers"])
    assert uninstall.safe_to_delete(world["alpha"], world["user"], [world["home"] / "servers"])
    assert not uninstall.safe_to_delete(Path("relative/path"), world["user"], [Path("relative")])


def test_safe_to_delete_refuses_a_link(world, tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = world["home"] / "servers" / "linked"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this computer doesn't let the tests make links")
    assert not uninstall.safe_to_delete(link, world["user"], [world["home"] / "servers"])


@pytest.mark.skipif(os.name != "nt", reason="Windows junctions")
def test_safe_to_delete_refuses_a_junction(world, tmp_path):
    import _winapi
    target = tmp_path / "target"
    target.mkdir()
    junction = world["home"] / "servers" / "junction"
    _winapi.CreateJunction(str(target), str(junction))
    assert not uninstall.safe_to_delete(junction, world["user"], [world["home"] / "servers"])


# ------------------------------------------------------------------ doing it
def test_run_deletes_only_the_planned_paths(world):
    runner = FakeRunner()
    parts = uninstall.plan(world["home"], Choices(), env=world["env"])
    report = uninstall.run(parts, runner=runner)
    assert runner.deleted() == [world["state"] / "backup.key", world["state"]]
    assert ("delete_file", world["state"] / "backup.key") in runner.calls
    assert ("delete_tree", world["state"]) in runner.calls
    assert not report.failed
    assert any("backup.key" in line for line in report.removed)
    assert any("Servers" in line for line in report.kept)


def test_kept_parts_never_reach_the_runner(world):
    runner = FakeRunner()
    parts = uninstall.plan(world["home"], Choices(keep_lockbox_key=True), env=world["env"])
    uninstall.run(parts, runner=runner)
    for path in runner.deleted():
        assert not str(path).startswith(str(world["home"] / "servers")), path
        assert path != world["state"] / "backup.key" and path != world["home"] / "exports"


def test_a_failing_part_doesnt_stop_the_rest(world):
    runner = FakeRunner(fail=[world["home"] / "exports"])
    parts = uninstall.plan(world["home"], Choices(exports=True, servers=True, backups=True), env=world["env"])
    report = uninstall.run(parts, runner=runner)
    assert world["home"] / "exports" in runner.deleted()
    assert world["state"] in runner.deleted() and world["home"] / "servers" in runner.deleted()
    assert len(report.failed) == 1 and "exports" in report.failed[0] and "in use" in report.failed[0]


def test_run_checks_every_path_again_right_before_deleting(world, tmp_path):
    parts = {p.key: p for p in uninstall.plan(world["home"], Choices(), env=world["env"])}
    parts["state"].paths.append(tmp_path / "not-ours")  # (as if something changed the plan)
    (tmp_path / "not-ours").mkdir()
    runner = FakeRunner()
    report = uninstall.run(list(parts.values()), runner=runner)
    assert tmp_path / "not-ours" not in runner.deleted()
    assert any("not-ours" in line for line in report.failed)


def test_run_stops_the_servers_first(world):
    runner = FakeRunner()
    seen = []
    parts = uninstall.plan(world["home"], Choices(), env=world["env"])
    uninstall.run(parts, runner=runner, stop_servers=lambda: seen.append(len(runner.calls)))
    assert seen == [0]


def test_a_failure_stopping_the_servers_is_reported_and_the_rest_goes_on(world):
    runner = FakeRunner()

    def stop():
        raise RuntimeError("alpha didn't stop")
    report = uninstall.run(uninstall.plan(world["home"], Choices(), env=world["env"]), runner=runner, stop_servers=stop)
    assert any("alpha didn't stop" in line for line in report.failed)
    assert world["state"] in runner.deleted()


def test_progress_is_told_about_each_part(world):
    seen = []
    uninstall.run(uninstall.plan(world["home"], Choices(), env=world["env"]), runner=FakeRunner(),
                  progress=lambda key, label, status: seen.append((key, status)))
    assert ("state", "done") in seen and ("servers", "kept") in seen


def test_the_report_as_text(world):
    report = uninstall.Report(removed=["Settings and state: deleted X"], failed=["Exports: Y (in use)"],
                              manual=["Run: pipx uninstall craft-conductor"], kept=["Servers and worlds: kept"])
    text = report.as_text()
    for line in ("deleted X", "Y (in use)", "pipx uninstall", "Servers and worlds: kept"):
        assert line in text
    assert text.index("deleted X") < text.index("Y (in use)") < text.index("pipx uninstall")


# ------------------------------------------------------------------ the program itself
def test_the_windows_program_is_deleted_after_it_exits(world, tmp_path, monkeypatch):
    exe = tmp_path / "Downloads" / "craft-conductor-windows-x64.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(uninstall, "_frozen", lambda: True)
    monkeypatch.setattr(uninstall, "_system", lambda: "windows")
    monkeypatch.setattr(uninstall, "_executable", lambda: str(exe))
    env = {**world["env"], "SystemRoot": r"C:\Windows"}
    parts = {p.key: p for p in uninstall.plan(world["home"], Choices(), env=env)}
    program = parts["program"]
    assert program.present and not program.kept and program.paths == [exe] and program.manual is None
    runner = FakeRunner()
    report = uninstall.run([program], runner=runner)
    assert not report.failed
    [call] = runner.calls
    kind, argv, elevated, detached = call
    assert kind == "run" and detached and not elevated
    assert argv[0].lower() == r"c:\windows\system32\cmd.exe"
    script = argv[-1]
    assert str(os.getpid()) in script and f'del /f /q "{exe}"' in script


def test_a_windows_program_path_cmd_would_change_is_left_for_the_person(world, tmp_path, monkeypatch):
    exe = tmp_path / "100%done" / "craft-conductor.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(uninstall, "_frozen", lambda: True)
    monkeypatch.setattr(uninstall, "_system", lambda: "windows")
    monkeypatch.setattr(uninstall, "_executable", lambda: str(exe))
    program = {p.key: p for p in uninstall.plan(world["home"], Choices(), env=world["env"])}["program"]
    runner = FakeRunner()
    report = uninstall.run([program], runner=runner)
    assert runner.calls == []
    assert any(str(exe) in line for line in report.manual)


@pytest.mark.parametrize("system", ["linux", "darwin"])
def test_the_linux_and_mac_program_is_deleted_directly(world, tmp_path, monkeypatch, system):
    exe = tmp_path / "bin" / "craft-conductor"
    exe.parent.mkdir()
    exe.write_bytes(b"\x7fELF")
    monkeypatch.setattr(uninstall, "_frozen", lambda: True)
    monkeypatch.setattr(uninstall, "_system", lambda: system)
    monkeypatch.setattr(uninstall, "_executable", lambda: str(exe))
    program = {p.key: p for p in uninstall.plan(world["home"], Choices(), env=world["env"])}["program"]
    runner = FakeRunner()
    uninstall.run([program], runner=runner)
    assert runner.calls == [("delete_file", exe)]


@pytest.mark.parametrize("prefix, command", [
    ("{tmp}/.local/share/pipx/venvs/craft-conductor", "pipx uninstall craft-conductor"),
    ("{tmp}/venv", "pip uninstall craft-conductor"),
])
def test_pip_and_pipx_installs_are_listed_for_the_person(world, tmp_path, monkeypatch, prefix, command):
    monkeypatch.setattr(uninstall, "_prefix", lambda: prefix.format(tmp=tmp_path))
    program = {p.key: p for p in uninstall.plan(world["home"], Choices(), env=world["env"])}["program"]
    assert program.paths == [] and command in program.manual
    runner = FakeRunner()
    report = uninstall.run([program], runner=runner)
    assert runner.calls == [] and any(command in line for line in report.manual)


def test_docker_is_listed_for_the_person(world):
    env = {**world["env"], "CRAFT_CONDUCTOR_CONTAINER": "1"}
    program = {p.key: p for p in uninstall.plan(world["home"], Choices(), env=env)}["program"]
    assert program.paths == [] and "docker rm" in program.manual and "docker rmi" in program.manual
