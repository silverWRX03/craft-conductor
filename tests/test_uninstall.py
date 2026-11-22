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
    (home / "exports" / "alpha.craft-conductor.zip").write_bytes(b"zip")
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
    (exports / "gamma.craft-conductor.zip").write_bytes(b"zip")
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


# ------------------------------------------------------------------ fix round 1 (review findings, rulings R10, R12, R13)
def _link(link: Path, target: Path, kind: str) -> None:
    """A junction (Windows) or a symlink, as ``kind`` says; skips when this computer can't make one."""
    target.mkdir(parents=True, exist_ok=True)
    try:
        if kind == "junction":
            if os.name != "nt":
                pytest.skip("Windows junctions")
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        else:
            link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this computer doesn't let the tests make links")


def _any_link_kind() -> str:
    return "junction" if os.name == "nt" else "symlink"


def _hub(world, **places) -> None:
    (world["state"] / "hub.json").write_text(json.dumps({"locations": {k: str(v) for k, v in places.items()}}),
                                             encoding="utf-8")


def _held(runner: FakeRunner, path: Path) -> bool:
    """The runner was told to delete ``path``, something inside it, or something holding it."""
    p = os.path.normcase(str(path))
    for d in runner.deleted():
        d = os.path.normcase(str(d))
        if d == p or d.startswith(p + os.sep) or p.startswith(d.rstrip(os.sep) + os.sep):
            return True
    return False


def test_a_chosen_exports_folder_keeps_the_persons_own_files(world):
    documents = world["user"] / "Documents"
    (documents / "alpha").mkdir(parents=True)
    (documents / "alpha" / "alpha-1.craft-conductor.zip").write_bytes(b"zip")
    (documents / "beta.craft-conductor.zip").write_bytes(b"zip")
    (documents / "taxes.pdf").write_bytes(b"%PDF")
    _hub(world, exports=documents)
    parts = _parts(world, exports=True)
    assert sorted(parts["exports"].paths) == sorted([documents / "alpha", documents / "beta.craft-conductor.zip"])
    runner = FakeRunner()
    uninstall.run(list(parts.values()), runner=runner)
    assert documents not in runner.deleted() and documents / "taxes.pdf" not in runner.deleted()
    assert documents / "alpha" in runner.deleted()


def test_an_empty_chosen_exports_folder_isnt_deleted(world):
    documents = world["user"] / "Documents"
    documents.mkdir()
    _hub(world, exports=documents)
    assert documents not in _parts(world, exports=True)["exports"].paths


@pytest.mark.parametrize("kind", ["junction", "symlink"])
def test_nothing_is_deleted_through_a_linked_backups_place(world, tmp_path, kind):
    link = tmp_path / "backups-link"
    _link(link, tmp_path / "real-backups", kind)
    (tmp_path / "real-backups" / "alpha").mkdir()
    (tmp_path / "real-backups" / "alpha" / "alpha-1.tar.gz").write_bytes(b"backup")
    (world["alpha"] / "craft-conductor.toml").write_text(
        TOML + f'[backups]\ndir = {json.dumps(str(link / "alpha"))}\n', encoding="utf-8")
    _hub(world, backups=link)
    part = _parts(world, backups=True)["backups"]
    assert not any(str(p).startswith(str(link)) for p in part.paths)
    assert part.manual and str(link) in part.manual
    runner = FakeRunner()
    report = uninstall.run([part], runner=runner)
    assert not _held(runner, link) and not _held(runner, tmp_path / "real-backups")
    assert any(str(link) in line for line in report.manual)


@pytest.mark.parametrize("kind", ["junction", "symlink"])
def test_the_run_check_refuses_a_path_reached_through_a_link(world, tmp_path, kind):
    link = world["home"] / "servers" / "linked"
    _link(link, tmp_path / "elsewhere", kind)
    (tmp_path / "elsewhere" / "world").mkdir()
    assert not uninstall.safe_to_delete(link / "world", world["user"], [world["home"] / "servers"])
    assert not uninstall.safe_to_delete(link / "world", world["user"], [link])


def test_nothing_is_deleted_through_a_linked_copy_folder(world, tmp_path):
    from craft_conductor import backup
    link = tmp_path / "usb-link"
    _link(link, tmp_path / "usb", _any_link_kind())
    (tmp_path / "usb" / "alpha").mkdir()
    (tmp_path / "usb" / "alpha" / backup.COPY_OWNER).write_text(backup.copy_owner(world["alpha"]), encoding="utf-8")
    (world["alpha"] / "craft-conductor.toml").write_text(
        TOML + f'[backups]\ncopy_to = {json.dumps(str(link))}\n', encoding="utf-8")
    part = _parts(world, backups=True)["backups"]
    runner = FakeRunner()
    uninstall.run([part], runner=runner)
    assert not _held(runner, link) and not _held(runner, tmp_path / "usb")
    assert part.manual and str(link) in part.manual


def test_a_home_that_is_the_persons_own_home_folder_loses_only_craft_conductors_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(uninstall, "_frozen", lambda: False)
    user = tmp_path / "user"
    (user / ".craft-conductor").mkdir(parents=True)
    (user / ".craft-conductor" / "hub.json").write_text("{}", encoding="utf-8")
    alpha = _server(user / "servers" / "alpha")
    (alpha / "backups").mkdir()
    (user / "exports").mkdir()
    (user / "exports" / "alpha.craft-conductor.zip").write_bytes(b"zip")
    (user / "Documents").mkdir()
    (user / "Documents" / "taxes.pdf").write_bytes(b"%PDF")
    (user / "notes.txt").write_text("mine", encoding="utf-8")
    env = {"HOME": str(user), "USERPROFILE": str(user)}
    parts = uninstall.plan(user, Choices(servers=True, backups=True, exports=True, games=True), env=env)
    runner = FakeRunner()
    report = uninstall.run(parts, runner=runner)
    assert not report.failed
    ours = [user / ".craft-conductor", user / "servers", user / "exports"]
    assert runner.deleted()
    for path in runner.deleted():
        assert any(path == p or p in path.parents for p in ours), path
    assert not _held(runner, user / "Documents") and not _held(runner, user / "notes.txt")
    assert user not in runner.deleted()


def test_a_server_folder_at_a_drive_root_is_refused_and_the_rest_goes_on(world):
    root = Path(world["user"].anchor) if os.name == "nt" else Path("/")
    (world["alpha"] / "craft-conductor.toml").write_text(
        TOML.replace("[server]\n", f"[server]\ndir = {json.dumps(str(root))}\n"), encoding="utf-8")
    parts = uninstall.plan(world["home"], Choices(servers=True), env=world["env"])
    runner = FakeRunner()
    report = uninstall.run(parts, runner=runner)
    assert root not in runner.deleted()
    for path in runner.deleted():  # (nothing on the drive but Craft Conductor's own)
        assert world["home"] in path.parents or path == world["home"], path
    assert any(str(root) in line and "top of a drive" in line for line in report.failed)
    assert world["beta"] in runner.deleted() and world["state"] in runner.deleted()


@pytest.mark.parametrize("servers_ticked", [True, False])
def test_a_server_inside_the_backups_folder(world, tmp_path, servers_ticked):
    chosen = tmp_path / "backups-folder"
    (chosen / "alpha").mkdir(parents=True)
    (chosen / "alpha" / "alpha-1.tar.gz").write_bytes(b"backup")
    inside = _server(chosen / "inside")
    (world["alpha"] / "craft-conductor.toml").write_text(
        TOML + f'[backups]\ndir = {json.dumps(str(chosen / "alpha"))}\n', encoding="utf-8")
    (world["state"] / "hub.json").write_text(
        json.dumps({"locations": {"backups": str(chosen)}, "extra": [str(inside)]}), encoding="utf-8")
    runner = FakeRunner()
    uninstall.run(uninstall.plan(world["home"], Choices(servers=servers_ticked, backups=True), env=world["env"]),
                  runner=runner)
    deleted = [os.path.normcase(str(p)) for p in runner.deleted()]
    assert len(deleted) == len(set(deleted))  # (nothing deleted twice)
    assert chosen not in runner.deleted()  # (it holds a server, not only backups)
    assert chosen / "alpha" in runner.deleted()
    assert (inside in runner.deleted()) is servers_ticked
    if not servers_ticked:
        assert not _held(runner, inside)


def test_a_server_that_didnt_stop_is_kept_with_its_backups(world):
    runner = FakeRunner()
    parts = uninstall.plan(world["home"], Choices(servers=True, backups=True), env=world["env"])
    report = uninstall.run(parts, runner=runner, stop_servers=lambda: [world["alpha"]])
    assert not _held(runner, world["alpha"])  # (its folder and its own backups in it)
    assert world["home"] / "servers" not in runner.deleted()
    assert world["beta"] in runner.deleted() and world["state"] in runner.deleted()
    assert any(str(world["alpha"]) in line and "running" in line for line in report.failed + report.kept)


def test_a_server_that_didnt_stop_keeps_its_backups_kept_elsewhere(world, tmp_path):
    chosen = tmp_path / "backups-folder"
    for sid in ("alpha", "beta"):
        (chosen / sid).mkdir(parents=True)
        (world[sid] / "craft-conductor.toml").write_text(
            TOML + f'[backups]\ndir = {json.dumps(str(chosen / sid))}\n', encoding="utf-8")
    _hub(world, backups=chosen)
    runner = FakeRunner()
    uninstall.run(uninstall.plan(world["home"], Choices(servers=True, backups=True), env=world["env"]), runner=runner,
                  stop_servers=lambda: [world["alpha"]])
    assert not _held(runner, chosen / "alpha") and not _held(runner, world["alpha"])
    assert chosen / "beta" in runner.deleted() and world["beta"] in runner.deleted()


def test_when_stopping_the_servers_fails_outright_every_server_is_kept(world):
    runner = FakeRunner()

    def stop():
        raise RuntimeError("couldn't reach the servers")
    parts = uninstall.plan(world["home"], Choices(servers=True, backups=True, exports=True), env=world["env"])
    report = uninstall.run(parts, runner=runner, stop_servers=stop)
    assert not _held(runner, world["home"] / "servers")
    assert world["home"] / "exports" in runner.deleted() and world["state"] in runner.deleted()
    assert any("couldn't reach the servers" in line for line in report.failed)
