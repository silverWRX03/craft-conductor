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
    once = list(dict.fromkeys(keys))  # (a builder may give several parts: the tunnels do)
    assert once == [k for k in uninstall.ORDER if k in keys]
    assert keys == sorted(keys, key=once.index)  # (each key's parts together)
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
    # (a server added from elsewhere: only its own files, never its folder whole)
    assert sorted(parts["servers"].paths) == sorted([elsewhere, extra / "server", extra / "craft-conductor.toml"])
    assert parts["servers"].emptied == [extra]
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


def test_a_server_folder_at_a_drive_root_is_never_deleted_and_the_rest_goes_on(world):
    root = Path(world["user"].anchor) if os.name == "nt" else Path("/")
    (world["alpha"] / "craft-conductor.toml").write_text(
        TOML.replace("[server]\n", f"[server]\ndir = {json.dumps(str(root))}\n"), encoding="utf-8")
    parts = uninstall.plan(world["home"], Choices(servers=True), env=world["env"])
    runner = FakeRunner()
    report = uninstall.run(parts, runner=runner)
    assert root not in runner.deleted()
    for path in runner.deleted():  # (nothing on the drive but Craft Conductor's own)
        assert world["home"] in path.parents or path == world["home"], path
    assert any(str(root) in line for line in report.manual)  # (outside the server's folder: listed for the person)
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
    # (a server added from elsewhere: never deleted whole, only Craft Conductor's own files in it)
    assert inside not in runner.deleted()
    assert ((inside / "server") in runner.deleted()) is servers_ticked
    assert ((inside / "craft-conductor.toml") in runner.deleted()) is servers_ticked
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


# ------------------------------------------------------------------ final review: only what Craft Conductor made (Critical 1)
class DeletingRunner(FakeRunner):
    """Really deletes, but only inside ``root`` (the test's temporary folder): for what's left after."""

    def __init__(self, root: Path, **kw):
        super().__init__(**kw)
        self.root = Path(root)

    def _mine(self, path) -> Path:
        assert _under(path, self.root), path
        return Path(path)

    def delete_tree(self, path):
        import shutil
        super().delete_tree(path)
        shutil.rmtree(self._mine(path))

    def delete_file(self, path):
        super().delete_file(path)
        os.unlink(self._mine(path))

    def remove_empty_folder(self, path):
        self.calls.append(("remove_empty_folder", Path(path)))
        os.rmdir(self._mine(path))


def test_a_server_dir_outside_its_server_folder_is_listed_never_deleted(world):
    documents = world["user"] / "Documents"
    (documents / "world").mkdir(parents=True)
    (documents / "taxes.pdf").write_bytes(b"%PDF")
    (world["alpha"] / "craft-conductor.toml").write_text(
        TOML.replace("[server]\n", f"[server]\ndir = {json.dumps(str(documents))}\n"), encoding="utf-8")
    parts = _parts(world, servers=True, backups=True)
    assert not any(_under(p, documents) or _under(documents, p) for p in parts["servers"].paths)
    assert str(documents) in (parts["servers"].manual or "")
    runner = FakeRunner()
    report = uninstall.run(list(parts.values()), runner=runner)
    assert not _held(runner, documents)
    assert any(str(documents) in line for line in report.manual)
    assert world["beta"] in runner.deleted() or world["home"] / "servers" in runner.deleted()


def test_a_shared_backups_folder_loses_only_the_backup_files(world, tmp_path):
    shared = tmp_path / "D_Backups"
    (shared / "holidays").mkdir(parents=True)
    (shared / "holiday.mov").write_bytes(b"mov")
    ours = [shared / "20260101-000000-alpha.tar.gz", shared / "20260101-000000-alpha.tar.gz.json",
            shared / "20260102-000000-alpha.tar.gz.part", shared / ".checks.json"]
    for p in ours:
        p.write_bytes(b"x")
    (world["alpha"] / "craft-conductor.toml").write_text(
        TOML + f'[backups]\ndir = {json.dumps(str(shared))}\n', encoding="utf-8")
    parts = _parts(world, backups=True)
    runner = FakeRunner()
    uninstall.run(list(parts.values()), runner=runner)
    assert shared not in runner.deleted()
    assert not _held(runner, shared / "holiday.mov") and not _held(runner, shared / "holidays")
    assert {p for p in runner.deleted() if _under(p, shared)} == set(ours)


def test_a_backups_folder_holding_only_backups_still_goes_whole(world, tmp_path):
    chosen = tmp_path / "backups-folder"
    (chosen / "alpha").mkdir(parents=True)
    (chosen / "alpha" / "alpha-1.tar.gz").write_bytes(b"backup")
    (chosen / "alpha" / "my-notes.txt").write_text("mine", encoding="utf-8")  # (its own folder there: whole)
    (world["alpha"] / "craft-conductor.toml").write_text(
        TOML + f'[backups]\ndir = {json.dumps(str(chosen / "alpha"))}\n', encoding="utf-8")
    _hub(world, backups=chosen)
    assert _parts(world, backups=True)["backups"].paths == [chosen]


def _added_server(world, folder: Path, photos: bool) -> Path:
    root = _server(folder)
    (root / "craft-conductor.lock.json").write_text("{}", encoding="utf-8")
    (root / "manual-downloads").mkdir()
    (root / ".craft-conductor").mkdir()
    (root / ".craft-conductor" / "daemon.log").write_text("log", encoding="utf-8")
    if photos:
        (root / "family-photos").mkdir()
        (root / "family-photos" / "beach.jpg").write_bytes(b"jpg")
    (world["state"] / "hub.json").write_text(json.dumps({"extra": [str(root)]}), encoding="utf-8")
    return root


def test_a_server_added_from_elsewhere_loses_only_its_own_files(world):
    added = _added_server(world, world["user"] / "Downloads" / "myserver", photos=True)
    parts = _parts(world, servers=True)
    runner = DeletingRunner(world["user"])
    uninstall.run(list(parts.values()), runner=runner)
    assert added not in runner.deleted()
    assert {p for p in runner.deleted() if _under(p, added)} == {
        added / "server", added / "craft-conductor.toml", added / "craft-conductor.lock.json",
        added / "manual-downloads", added / ".craft-conductor"}
    assert (added / "family-photos" / "beach.jpg").read_bytes() == b"jpg"
    assert sorted(p.name for p in added.iterdir()) == ["family-photos"]


def test_a_server_added_from_elsewhere_with_nothing_else_in_it_goes(world):
    added = _added_server(world, world["user"] / "Downloads" / "myserver", photos=False)
    runner = DeletingRunner(world["user"])
    report = uninstall.run(list(_parts(world, servers=True).values()), runner=runner)
    assert not added.exists() and (world["user"] / "Downloads").is_dir()
    assert ("remove_empty_folder", added) in runner.calls
    assert not report.failed


def test_a_server_added_from_elsewhere_is_kept_whole_unless_ticked(world):
    added = _added_server(world, world["user"] / "Downloads" / "myserver", photos=True)
    runner = FakeRunner()
    uninstall.run(list(_parts(world, backups=True, exports=True).values()), runner=runner)
    assert not _held(runner, added)


# ------------------------------------------------------------------ Task 2: the system parts
# Nothing here reaches the real router, Windows Firewall, registry, Tailscale or systemd: the fake
# runner answers every question about the computer, and the modules' own lookups are monkeypatched.
import base64
import dataclasses

from craft_conductor import service, tailscale, tunnels, upnp, urlhandler


class SystemFake(FakeRunner):
    """A fake runner that also answers what only the computer can tell (firewall rules, the registry,
    the router, a running cloudflared). ``codes``: exit code by program name (or "elevated")."""

    def __init__(self, *, rules=None, registry=(), router=(), processes=(), codes=None, raise_on=None):
        super().__init__()
        self.rules, self.registry, self.processes = rules, set(registry), set(processes)
        self.router = router  # None: no router answers; else the ports the router refuses to remove
        self.codes = codes or {}
        self.raise_on = raise_on

    def run(self, argv, *, elevated=False, detached=False):
        super().run(argv, elevated=elevated, detached=detached)
        name = argv[0].replace("\\", "/").rsplit("/", 1)[-1].lower()  # (a Windows path, on Linux too)
        if self.raise_on and self.raise_on in (name, "elevated" if elevated else None):
            raise OSError("the program couldn't be started")
        return self.codes.get("elevated" if elevated else name, 0)

    def firewall_rules(self):
        self.calls.append(("firewall_rules",))
        return self.rules

    def registry_has(self, key):
        self.calls.append(("registry_has", key))
        return key in self.registry

    def router_remove(self, ports):
        self.calls.append(("router_remove", list(ports)))
        if self.router is None:
            raise upnp.UpnpError("no router answered")
        return [(port, proto, "the router said no") for port, proto in ports if (port, proto) in self.router]

    def stop_process(self, pid, exe):
        self.calls.append(("stop_process", pid, exe))
        return pid in self.processes

    def ran(self) -> list[list[str]]:
        return [c[1] for c in self.calls if c[0] == "run"]


def _hub_data(world, data: dict) -> None:
    (world["state"] / "hub.json").write_text(json.dumps(data), encoding="utf-8")


def _system_parts(world, runner, system="windows", monkeypatch=None, env=None) -> dict[str, list[uninstall.Part]]:
    if monkeypatch is not None:
        monkeypatch.setattr(uninstall, "_system", lambda: system)
    out: dict[str, list[uninstall.Part]] = {}
    for p in uninstall.plan(world["home"], Choices(), env=env or world["env"], runner=runner):
        out.setdefault(p.key, []).append(p)
    return out


def _one(parts, key, label_has="") -> uninstall.Part:
    [part] = [p for p in parts[key] if label_has.lower() in p.label.lower()]
    return part


def test_the_system_parts_come_first_in_the_fixed_order(world, monkeypatch):
    keys = [p.key for p in uninstall.plan(world["home"], Choices(), env=world["env"], runner=SystemFake())]
    for key in ("tunnels", "router", "firewall", "service", "invite"):
        assert key in keys, key
    first = [k for k in keys if k in ("tunnels", "router", "firewall", "service", "invite")]
    assert keys[:len(first)] == first
    assert keys.index("invite") < keys.index("exports")


# --- the router
def test_router_mappings_recorded_in_hub_json_are_removed_through_the_router(world, monkeypatch):
    _hub_data(world, {"upnp": {"enabled": True, "mapped": [[25565, "TCP"], [19132, "UDP"]]}})
    runner = SystemFake()
    router = _one(_system_parts(world, runner, monkeypatch=monkeypatch), "router")
    assert router.present and "25565" in router.action and "19132" in router.action
    report = uninstall.run([router], runner=runner)
    assert ("router_remove", [(25565, "TCP"), (19132, "UDP")]) in runner.calls
    assert not report.failed and not report.manual
    assert any("25565" in line for line in report.removed)


def test_no_router_found_lists_the_ports_for_the_person(world, monkeypatch):
    _hub_data(world, {"upnp": {"enabled": False, "mapped": [[25565, "TCP"], [8767, "TCP"]]}})
    runner = SystemFake(router=None)
    report = uninstall.run([_one(_system_parts(world, runner, monkeypatch=monkeypatch), "router")], runner=runner)
    [line] = report.manual
    assert "TCP 25565" in line and "TCP 8767" in line and "router" in line.lower()


def test_ports_the_router_refused_are_listed_and_the_others_removed(world, monkeypatch):
    _hub_data(world, {"upnp": {"mapped": [[25565, "TCP"], [8767, "TCP"]]}})
    runner = SystemFake(router={(8767, "TCP")})
    report = uninstall.run([_one(_system_parts(world, runner, monkeypatch=monkeypatch), "router")], runner=runner)
    assert any("TCP 25565" in line for line in report.removed)
    [line] = report.manual
    assert "TCP 8767" in line and "25565" not in line


def test_a_runner_that_cant_reach_the_router_lists_the_ports(world, monkeypatch):
    _hub_data(world, {"upnp": {"mapped": [[25565, "TCP"]]}})
    runner = FakeRunner()  # (no router_remove: the router is never asked)
    report = uninstall.run([_one(_system_parts(world, runner, monkeypatch=monkeypatch), "router")], runner=runner)
    assert any("TCP 25565" in line for line in report.manual)


@pytest.mark.parametrize("hub", [{}, {"upnp": {"enabled": True, "mapped": []}}, {"upnp": {"mapped": "junk"}},
                                 {"upnp": {"mapped": [[0, "TCP"], [25565, "SCTP"], ["x", "TCP"]]}}])
def test_no_recorded_mappings_means_no_router_part(world, monkeypatch, hub):
    _hub_data(world, hub)
    runner = SystemFake()
    router = _one(_system_parts(world, runner, monkeypatch=monkeypatch), "router")
    assert not router.present
    runner.calls.clear()  # (what planning asked)
    uninstall.run([router], runner=runner)
    assert runner.calls == []


# --- Windows Firewall
FIREWALL_RULE = "Craft Conductor: alpha (TCP 25565)"


def _script(argv: list[str]) -> str:
    return base64.b64decode(argv[argv.index("-EncodedCommand") + 1]).decode("utf-16-le")


def test_the_firewall_rules_are_removed_with_one_administrator_prompt(world, monkeypatch):
    runner = SystemFake(rules=[FIREWALL_RULE])
    fw = _one(_system_parts(world, runner, monkeypatch=monkeypatch), "firewall")
    assert fw.present and "administrator" in fw.action
    report = uninstall.run([fw], runner=runner)
    [call] = [c for c in runner.calls if c[0] == "run"]
    _, argv, elevated, detached = call
    assert elevated and not detached and argv[0].lower() == "powershell.exe"
    script = _script(argv)
    assert FIREWALL_RULE in script and "'Craft Conductor'" in script
    assert not report.failed and not report.manual and report.removed


def test_the_firewall_prompt_answered_no_lists_the_command(world, monkeypatch):
    runner = SystemFake(rules=[FIREWALL_RULE], codes={"elevated": uninstall.DECLINED})
    report = uninstall.run([_one(_system_parts(world, runner, monkeypatch=monkeypatch), "firewall")], runner=runner)
    assert not report.removed
    assert any("craft-conductor firewall remove" in line for line in report.manual)


def test_the_firewall_removal_failing_is_reported_with_the_command(world, monkeypatch):
    runner = SystemFake(rules=[FIREWALL_RULE], codes={"elevated": 1})
    report = uninstall.run([_one(_system_parts(world, runner, monkeypatch=monkeypatch), "firewall")], runner=runner)
    assert report.failed and any("craft-conductor firewall remove" in line for line in report.manual)


def test_no_firewall_rules_means_no_prompt(world, monkeypatch):
    runner = SystemFake(rules=[])
    fw = _one(_system_parts(world, runner, monkeypatch=monkeypatch), "firewall")
    assert not fw.present
    uninstall.run([fw], runner=runner)
    assert runner.ran() == []


def test_firewall_rules_that_cant_be_read_are_removed_by_their_group(world, monkeypatch):
    runner = SystemFake(rules=None)  # (Windows couldn't say)
    fw = _one(_system_parts(world, runner, monkeypatch=monkeypatch), "firewall")
    assert fw.present
    uninstall.run([fw], runner=runner)
    [argv] = runner.ran()
    script = _script(argv)
    assert "-Group 'Craft Conductor'" in script and "Remove-NetFirewallRule" in script


@pytest.mark.parametrize("system", ["linux", "darwin"])
def test_there_is_no_firewall_part_off_windows(world, monkeypatch, system):
    runner = SystemFake(rules=[FIREWALL_RULE])
    fw = _one(_system_parts(world, runner, system=system, monkeypatch=monkeypatch), "firewall")
    assert not fw.present and ("firewall_rules",) not in runner.calls


# --- Tailscale and the Cloudflare quick tunnel
TS = r"C:\Program Files\Tailscale\tailscale.exe"


@pytest.mark.parametrize("funnel", [False, True])
def test_tailscale_serve_set_by_craft_conductor_is_switched_off(world, monkeypatch, funnel):
    _hub_data(world, {"tunnels": {"tailscale": {"port": 20001, "name": "pc.example.ts.net", "funnel": funnel}}})
    monkeypatch.setattr(tailscale, "exe", lambda: TS)
    runner = SystemFake()
    part = _one(_system_parts(world, runner, monkeypatch=monkeypatch), "tunnels", "tailscale")
    assert part.present
    report = uninstall.run([part], runner=runner)
    expected = ([[TS, "funnel", "--https=443", "off"]] if funnel else []) + [[TS, "serve", "--https=443", "off"]]
    assert runner.ran() == expected
    assert report.removed and not report.failed


def test_tailscale_not_installed_means_no_tailscale_part(world, monkeypatch):
    _hub_data(world, {"tunnels": {"tailscale": {"port": 20001, "name": "pc.example.ts.net", "funnel": False}}})
    monkeypatch.setattr(tailscale, "exe", lambda: None)
    runner = SystemFake()
    part = _one(_system_parts(world, runner, monkeypatch=monkeypatch), "tunnels", "tailscale")
    assert not part.present
    runner.calls.clear()  # (what planning asked)
    uninstall.run([part], runner=runner)
    assert runner.calls == []


def test_tailscale_never_set_up_means_no_tailscale_part(world, monkeypatch):
    seen = []
    monkeypatch.setattr(tailscale, "exe", lambda: seen.append(1) or TS)
    part = _one(_system_parts(world, SystemFake(), monkeypatch=monkeypatch), "tunnels", "tailscale")
    assert not part.present and not seen


def test_tailscale_failing_to_switch_off_says_what_to_run(world, monkeypatch):
    _hub_data(world, {"tunnels": {"tailscale": {"port": 20001, "name": "pc.example.ts.net", "funnel": False}}})
    monkeypatch.setattr(tailscale, "exe", lambda: TS)
    runner = SystemFake(codes={"tailscale.exe": 1})
    report = uninstall.run([_one(_system_parts(world, runner, monkeypatch=monkeypatch), "tunnels", "tailscale")],
                           runner=runner)
    assert report.failed and any("tailscale serve --https=443 off" in line for line in report.manual)


def test_a_running_cloudflare_tunnel_is_stopped(world, monkeypatch):
    exe = str(world["state"] / "tools" / "cloudflared.exe")
    (world["state"] / "tools" / "cloudflared.pid").write_text(json.dumps({"pid": 4242, "exe": exe}))
    runner = SystemFake(processes={4242})
    part = _one(_system_parts(world, runner, monkeypatch=monkeypatch), "tunnels", "cloudflare")
    assert part.present
    report = uninstall.run([part], runner=runner)
    assert ("stop_process", 4242, exe) in runner.calls
    assert report.removed and not report.failed


@pytest.mark.parametrize("pid_file", [None, "not json", json.dumps({"pid": "x"})])
def test_no_recorded_cloudflare_tunnel_means_no_cloudflare_part(world, monkeypatch, pid_file):
    if pid_file is not None:
        (world["state"] / "tools" / "cloudflared.pid").write_text(pid_file)
    part = _one(_system_parts(world, SystemFake(), monkeypatch=monkeypatch), "tunnels", "cloudflare")
    assert not part.present


def test_tunnels_recorded_cloudflared_reads_the_pid_file(tmp_path):
    assert tunnels.recorded_cloudflared(tmp_path) is None
    (tmp_path / "cloudflared.pid").write_text(json.dumps({"pid": 7, "exe": "/x/cloudflared"}))
    assert tunnels.recorded_cloudflared(tmp_path) == (7, "/x/cloudflared")


def test_tailscale_unserve_commands_switch_off_funnel_first():
    assert tailscale.unserve_commands(False) == [["serve", "--https=443", "off"]]
    assert tailscale.unserve_commands(True) == [["funnel", "--https=443", "off"], ["serve", "--https=443", "off"]]


# --- the background service (Linux)
def _units(world, tmp_path, monkeypatch, user="steve"):
    """Linux, with the person's systemd user folder and the lingering folder in the temporary home."""
    config = tmp_path / "config"
    linger = tmp_path / "linger"
    linger.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setattr(uninstall, "LINGER", linger)
    monkeypatch.setattr(uninstall, "_euid", lambda: 1000)
    _system_units(monkeypatch, tmp_path / "etc")
    env = {**world["env"], "USER": user}
    return config / "systemd" / "user", linger, env


def _system_units(monkeypatch, where: Path):
    """service.plan with its system folder (/etc/systemd/system) moved into the temporary home."""
    real = service.plan

    def plan(root, system=None, home=None, panel=False):
        p = real(root, system, home, panel)
        return dataclasses.replace(p, path=where / p.name) if p.system else p
    monkeypatch.setattr(service, "plan", plan)


def _install_unit(root: Path, panel=False, system=False) -> Path:
    p = service.plan(root, system, panel=panel)
    p.path.parent.mkdir(parents=True, exist_ok=True)
    p.path.write_text(p.text)
    return p.path


def test_the_panel_and_server_services_are_removed_and_lingering_switched_off(world, tmp_path, monkeypatch):
    folder, linger, env = _units(world, tmp_path, monkeypatch)
    panel = _install_unit(world["home"], panel=True)
    alpha = _install_unit(world["alpha"])
    (linger / "steve").write_text("")
    runner = SystemFake()
    part = _one(_system_parts(world, runner, system="linux", monkeypatch=monkeypatch, env=env), "service")
    assert part.present and "craft_conductor.service" in part.action and alpha.name in part.action
    report = uninstall.run([part], runner=runner)
    ran = runner.ran()
    assert ["systemctl", "--user", "disable", "--now", "craft_conductor.service"] in ran
    assert ["systemctl", "--user", "disable", "--now", alpha.name] in ran
    assert ["loginctl", "disable-linger", "steve"] in ran
    assert not panel.exists() and not alpha.exists()
    assert not report.failed and len(report.removed) >= 2


class InsideUnit(SystemFake):
    """Craft Conductor running as its own service (the panel's unit): what systemd says this process is in."""

    def own_unit(self):
        self.calls.append(("own_unit",))
        return "craft_conductor.service"


def test_the_panels_own_service_is_disabled_without_stopping_the_uninstall(world, tmp_path, monkeypatch):
    """R15: run from the control panel running as the service, `disable --now` would stop the panel
    half-way through: its own unit is disabled and removed without stopping it (it ends when Craft
    Conductor closes, at the end), and lingering, which would end it too, is left for the person."""
    folder, linger, env = _units(world, tmp_path, monkeypatch)
    panel = _install_unit(world["home"], panel=True)
    alpha = _install_unit(world["alpha"])
    (linger / "steve").write_text("")
    runner = InsideUnit()
    part = _one(_system_parts(world, runner, system="linux", monkeypatch=monkeypatch, env=env), "service")
    report = uninstall.run([part], runner=runner)
    ran = runner.ran()
    assert ["systemctl", "--user", "disable", "craft_conductor.service"] in ran
    assert ["systemctl", "--user", "disable", "--now", "craft_conductor.service"] not in ran
    assert ["systemctl", "--user", "disable", "--now", alpha.name] in ran  # (a server's own unit still stops)
    assert ran[-1] == ["systemctl", "--user", "daemon-reload"]  # (nothing after the panel's own unit)
    assert not any(argv[0] == "loginctl" for argv in ran)
    assert not panel.exists() and not alpha.exists()
    assert any("craft_conductor.service" in line and "closes" in line for line in report.removed)
    assert any("loginctl disable-linger steve" in line for line in report.manual)
    assert not report.failed


def test_the_worlds_count_and_the_empty_home_are_the_modules_own(world, tmp_path, monkeypatch):
    """Shared by the command and the page (the second confirmation, and the folder left empty)."""
    assert uninstall.count_worlds([world["alpha"], world["beta"], tmp_path / "nothing"]) == 2
    empty = tmp_path / "me" / "craft-conductor"
    empty.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "me"))
    assert "deleted the empty folder" in uninstall.remove_empty_home(empty.resolve())
    assert not empty.exists()
    other = tmp_path / "elsewhere"
    other.mkdir()
    assert uninstall.remove_empty_home(other) is None and other.exists()


def test_lingering_is_left_on_when_other_units_use_it(world, tmp_path, monkeypatch):
    folder, linger, env = _units(world, tmp_path, monkeypatch)
    _install_unit(world["home"], panel=True)
    (folder / "syncthing.service").write_text("[Service]\n")
    (linger / "steve").write_text("")
    runner = SystemFake()
    uninstall.run([_one(_system_parts(world, runner, system="linux", monkeypatch=monkeypatch, env=env), "service")],
                  runner=runner)
    assert not any(argv[0] == "loginctl" for argv in runner.ran())


def test_a_unit_of_the_same_name_for_another_folder_is_not_touched(world, tmp_path, monkeypatch):
    folder, linger, env = _units(world, tmp_path, monkeypatch)
    other = _install_unit(tmp_path / "elsewhere" / "alpha")  # (same file name: craft-conductor-alpha.service)
    assert other.name == service.unit_name(world["alpha"])
    runner = SystemFake()
    part = _one(_system_parts(world, runner, system="linux", monkeypatch=monkeypatch, env=env), "service")
    assert not part.present
    uninstall.run([part], runner=runner)
    assert other.exists() and runner.calls == []


def test_a_system_service_needs_root_so_it_is_listed_with_the_commands(world, tmp_path, monkeypatch):
    folder, linger, env = _units(world, tmp_path, monkeypatch)
    unit = _install_unit(world["home"], panel=True, system=True)
    runner = SystemFake()
    part = _one(_system_parts(world, runner, system="linux", monkeypatch=monkeypatch, env=env), "service")
    assert part.present
    report = uninstall.run([part], runner=runner)
    assert unit.exists() and runner.ran() == []
    [line] = report.manual
    assert "sudo systemctl disable --now craft_conductor.service" in line and str(unit) in line


def test_a_system_service_is_removed_when_running_as_root(world, tmp_path, monkeypatch):
    folder, linger, env = _units(world, tmp_path, monkeypatch)
    monkeypatch.setattr(uninstall, "_euid", lambda: 0)
    unit = _install_unit(world["home"], panel=True, system=True)
    runner = SystemFake()
    report = uninstall.run([_one(_system_parts(world, runner, system="linux", monkeypatch=monkeypatch, env=env),
                                 "service")], runner=runner)
    assert not unit.exists()
    assert ["systemctl", "disable", "--now", "craft_conductor.service"] in runner.ran()
    assert not report.failed and not report.manual


@pytest.mark.parametrize("system", ["windows", "darwin"])
def test_there_is_no_service_part_off_linux(world, tmp_path, monkeypatch, system):
    folder, linger, env = _units(world, tmp_path, monkeypatch)
    _install_unit(world["home"], panel=True)
    part = _one(_system_parts(world, SystemFake(), system=system, monkeypatch=monkeypatch, env=env), "service")
    assert not part.present


def test_the_service_runner_adapter_is_shaped_like_subprocess_run():
    runner = SystemFake(codes={"systemctl": 5})
    proc = uninstall.subprocess_runner(runner)(["systemctl", "--user", "daemon-reload"], capture_output=True, text=True)
    assert proc.returncode == 5 and proc.stdout == "" and proc.stderr == ""
    assert runner.ran() == [["systemctl", "--user", "daemon-reload"]]


# --- the invite link handler
def test_unregister_removes_exactly_the_windows_key():
    runner = SystemFake()
    urlhandler.unregister(runner, system="windows")
    assert runner.calls == [("registry_delete", "HKCU\\Software\\Classes\\craft-conductor")]


def test_unregister_removes_exactly_the_linux_desktop_file(tmp_path):
    entry = tmp_path / "data" / "applications" / "craft-conductor-invite.desktop"
    entry.parent.mkdir(parents=True)
    entry.write_text("[Desktop Entry]\n")
    (entry.parent / "other.desktop").write_text("[Desktop Entry]\n")
    runner = SystemFake()
    urlhandler.unregister(runner, system="linux", env={"XDG_DATA_HOME": str(tmp_path / "data")})
    assert runner.calls == [("delete_file", entry)]


def test_unregister_does_nothing_on_a_mac():
    runner = SystemFake()
    assert urlhandler.unregister(runner, system="darwin") is None
    assert runner.calls == []


def test_the_invite_handler_part_on_windows(world, monkeypatch):
    key = "HKCU\\Software\\Classes\\craft-conductor"
    runner = SystemFake(registry={key})
    part = _one(_system_parts(world, runner, monkeypatch=monkeypatch), "invite")
    assert part.present
    report = uninstall.run([part], runner=runner)
    assert ("registry_delete", key) in runner.calls and report.removed
    absent = _one(_system_parts(world, SystemFake(), monkeypatch=monkeypatch), "invite")
    assert not absent.present


def test_the_invite_handler_part_on_linux(world, tmp_path, monkeypatch):
    entry = world["user"] / ".local" / "share" / "applications" / "craft-conductor-invite.desktop"
    runner = SystemFake()
    assert not _one(_system_parts(world, runner, system="linux", monkeypatch=monkeypatch), "invite").present
    entry.parent.mkdir(parents=True)
    entry.write_text("[Desktop Entry]\n")
    part = _one(_system_parts(world, runner, system="linux", monkeypatch=monkeypatch), "invite")
    assert part.present
    uninstall.run([part], runner=runner)
    assert ("delete_file", entry) in runner.calls


def test_there_is_no_invite_handler_on_a_mac(world, monkeypatch):
    assert not _one(_system_parts(world, SystemFake(), system="darwin", monkeypatch=monkeypatch), "invite").present


# --- what's listed for the person, and one part failing
def test_what_craft_conductor_cant_reach_is_listed_for_the_person(world, monkeypatch):
    runner = SystemFake()
    listed = _one(_system_parts(world, runner, monkeypatch=monkeypatch), "listed")
    assert listed.present
    report = uninstall.run([listed], runner=runner)
    text = " ".join(report.manual)
    for word in ("Tailscale", "playit.gg", "phone", "browser", "SSH", "Docker"):
        assert word in text, word
    assert [c for c in runner.calls if c[0] not in ("firewall_rules", "registry_has")] == []


def test_a_system_part_failing_doesnt_stop_the_rest(world, monkeypatch):
    _hub_data(world, {"upnp": {"mapped": [[25565, "TCP"]]}})
    runner = SystemFake(rules=[FIREWALL_RULE], raise_on="elevated", registry={"HKCU\\Software\\Classes\\craft-conductor"})
    monkeypatch.setattr(uninstall, "_system", lambda: "windows")
    report = uninstall.run(uninstall.plan(world["home"], Choices(), env=world["env"], runner=runner), runner=runner)
    assert any("Firewall" in line for line in report.failed)
    assert ("router_remove", [(25565, "TCP")]) in runner.calls
    assert ("registry_delete", "HKCU\\Software\\Classes\\craft-conductor") in runner.calls
    assert world["state"] in runner.deleted()


# --- the real runner's own questions, with the modules monkeypatched (no router, no processes)
def test_the_system_runner_removes_router_ports_through_upnp(monkeypatch):
    removed = []
    gw = upnp.Gateway("http://192.168.1.1/ctl", upnp.SERVICES[0], "192.168.1.5")

    def remove(g, port, proto="TCP"):
        if port == 8767:
            raise upnp.UpnpError("the router said no")
        removed.append((g, port, proto))
    monkeypatch.setattr(upnp, "find", lambda timeout=3.0: gw)
    monkeypatch.setattr(upnp, "remove", remove)
    failed = uninstall.SystemRunner().router_remove([(25565, "TCP"), (8767, "TCP")])
    assert removed == [(gw, 25565, "TCP")]
    assert failed == [(8767, "TCP", "the router said no")]


def test_the_system_runner_stops_only_that_cloudflared(monkeypatch):
    killed = []
    monkeypatch.setattr(tunnels.peer, "program_file", lambda pid: r"C:\cc\tools\cloudflared.exe" if pid == 7 else "")
    monkeypatch.setattr(tunnels.os, "kill", lambda pid, sig: killed.append(pid))
    runner = uninstall.SystemRunner()
    assert runner.stop_process(7, r"c:\CC\tools\cloudflared.exe") is True
    assert runner.stop_process(8, r"C:\cc\tools\cloudflared.exe") is False
    assert killed == [7]


def test_the_system_runner_reads_only_craft_conductors_firewall_rules(monkeypatch):
    from craft_conductor import firewall
    state = {"rules": [
        {"name": FIREWALL_RULE, "group": "Craft Conductor", "action": 2, "protocol": "TCP", "ports": ["25565"]},
        {"name": "Someone else's", "group": "Other", "action": 2, "protocol": "TCP", "ports": ["80"]}]}
    monkeypatch.setattr(firewall, "available", lambda: True)
    monkeypatch.setattr(firewall, "read", lambda timeout=30, fresh=False: state)
    assert uninstall.SystemRunner().firewall_rules() == [FIREWALL_RULE]
    monkeypatch.setattr(firewall, "read", lambda timeout=30, fresh=False: None)
    assert uninstall.SystemRunner().firewall_rules() is None


# ------------------------------------------------------------------ games in launchers (Task 3)
from craft_conductor import join as joinmod  # noqa: E402
from craft_conductor import launchers as launchersmod  # noqa: E402

GAME_MARK = joinmod.MANIFEST  # (what join.sync_mods writes in every game folder it makes)


class GameRunner(FakeRunner):
    """Also answers whether a launcher is open, and writes a launcher's file, only inside ``root``
    (the test's temporary folder)."""

    def __init__(self, root: Path, running=(), **kw):
        super().__init__(**kw)
        self.root, self.running = Path(root), set(running)

    def launcher_running(self, key):
        self.calls.append(("launcher_running", key))
        return key in self.running

    def write_text(self, path, text):
        assert str(Path(path).resolve()).lower().startswith(str(self.root.resolve()).lower()), path
        self.calls.append(("write_text", Path(path)))
        Path(path).write_text(text, encoding="utf-8")


def _game_folder(folder: Path, worlds=("World",)) -> Path:
    (folder / "mods").mkdir(parents=True)
    (folder / "mods" / "sodium.jar").write_bytes(b"jar")
    (folder / GAME_MARK).write_text('{"mods": ["sodium.jar"]}', encoding="utf-8")
    for w in worlds:
        (folder / "saves" / w).mkdir(parents=True)
        (folder / "saves" / w / "level.dat").write_bytes(b"level")
    return folder


def _version(versions: Path, vid: str) -> Path:
    (versions / vid).mkdir(parents=True)
    (versions / vid / f"{vid}.json").write_text(json.dumps({"id": vid, "inheritsFrom": "1.21.1"}), encoding="utf-8")
    return versions / vid


@pytest.fixture
def games(world, tmp_path, monkeypatch):
    """The person's launchers, in the temporary folder: the Minecraft Launcher with two installations
    Craft Conductor made (a friend's server, a single-player game), the person's own, one named like
    Craft Conductor's that points elsewhere, and one from before the rename (mcsm-); Prism with
    Craft Conductor's instance, the person's own and an unmarked one; the Modrinth App."""
    roaming = world["user"] / "AppData" / "Roaming"
    mc = roaming / ".minecraft"
    ours = mc / "craft-conductor"
    alpha = _game_folder(ours / "alpha", worlds=("Survival", "Creative"))
    sky = _game_folder(ours / "sky")
    (ours / "servers.json").write_text('{"0123456789abcdef": "alpha"}', encoding="utf-8")
    (ours / "invites.json").write_text("[]", encoding="utf-8")
    (ours / "extras").mkdir()
    (ours / "extras" / "alpha.json").write_text('{"items": []}', encoding="utf-8")
    (ours / ".craft-conductor" / "java" / "21").mkdir(parents=True)
    versions = mc / "versions"
    _version(versions, "craft-conductor-alpha")
    _version(versions, "craft-conductor-sky")
    _version(versions, "craft-conductor-moved")
    _version(versions, "fabric-loader-0.16.9-1.21.1")
    _version(versions, "mcsm-old")
    (mc / "mcsm" / "old").mkdir(parents=True)
    (world["user"] / "mine").mkdir()
    profiles = {
        "profiles": {
            "4f1c0e0a2b": {"name": "My own", "type": "custom", "gameDir": str(world["user"] / "mine"),
                           "lastVersionId": "fabric-loader-0.16.9-1.21.1", "created": "2026-01-01T00:00:00.000Z"},
            "craft-conductor-alpha": {"name": "Alpha", "type": "custom", "gameDir": str(alpha),
                                      "lastVersionId": "craft-conductor-alpha", "javaArgs": "-Xmx4G -XX:+UseG1GC"},
            "craft-conductor-sky": {"name": "Sky", "type": "custom", "gameDir": str(sky),
                                    "lastVersionId": "craft-conductor-sky", "icon": "Grass"},
            "craft-conductor-moved": {"name": "Moved", "type": "custom", "gameDir": str(world["user"] / "elsewhere"),
                                      "lastVersionId": "craft-conductor-moved"},
            "mcsm-old": {"name": "Old one", "type": "custom", "gameDir": str(mc / "mcsm" / "old"),
                         "lastVersionId": "mcsm-old"},
            "latest-release": {"name": "", "type": "latest-release", "lastVersionId": "latest-release"},
        },
        "settings": {"locale": "en-us", "keepLauncherOpen": True, "crashAssistance": False},
        "version": 3,
    }
    (mc / "launcher_profiles.json").write_text(json.dumps(profiles, indent=2), encoding="utf-8")
    (mc / "launcher_profiles.json.craft-conductor-backup").write_text("{}", encoding="utf-8")
    prism = roaming / "PrismLauncher"
    instances = prism / "instances"
    p_alpha = instances / "craft-conductor-alpha"
    _game_folder(p_alpha / ".minecraft")
    (p_alpha / "instance.cfg").write_text("[General]\nname=Alpha\n", encoding="utf-8")
    (instances / "My Pack" / ".minecraft").mkdir(parents=True)
    (instances / "My Pack" / "instance.cfg").write_text("[General]\nname=My Pack\n", encoding="utf-8")
    (instances / "craft-conductor-nomark").mkdir()
    (instances / "craft-conductor-nomark" / "instance.cfg").write_text("[General]\nname=No mark\n", encoding="utf-8")
    modrinth = roaming / "ModrinthApp"
    (modrinth / "profiles" / "Sky").mkdir(parents=True)
    sp = world["state"] / "singleplayer"
    sp.mkdir()
    (sp / "a1b2c3d4e5f6.json").write_text(json.dumps({"id": "a1b2c3d4e5f6", "name": "Sky", "created": 1,
                                                       "launchers": ["minecraft", "modrinth"]}), encoding="utf-8")
    # (the launchers are found here, never in this computer's real folders)
    monkeypatch.setattr(joinmod, "minecraft_dir", lambda *a, **k: mc)
    monkeypatch.setattr(launchersmod, "prism_dirs", lambda *a, **k: [prism])
    monkeypatch.setattr(launchersmod, "modrinth_dirs", lambda *a, **k: [modrinth])
    monkeypatch.setattr(launchersmod, "curseforge_dirs", lambda *a, **k: [world["user"] / "no-curseforge"])
    return {**world, "mc": mc, "ours": ours, "alpha_game": alpha, "sky_game": sky, "versions": versions,
            "prism": prism, "instances": instances, "p_alpha": p_alpha, "modrinth": modrinth,
            "profiles_text": (mc / "launcher_profiles.json").read_text(encoding="utf-8")}


def _games_parts(where, **choices) -> list[uninstall.Part]:
    return [p for p in uninstall.plan(where["home"], Choices(**choices), env=where["env"]) if p.key == "games"]


def _profiles(games, name="launcher_profiles.json") -> dict:
    return json.loads((games["mc"] / name).read_text(encoding="utf-8"))


def _under(path: Path, folder: Path) -> bool:
    """``path`` is ``folder`` or inside it (as written, ignoring case)."""
    p, f = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(folder))
    return p == f or p.startswith(f.rstrip("\\/") + os.sep)


def test_games_are_kept_unless_ticked(games):
    parts = _games_parts(games)
    assert parts and all(p.kept for p in parts if p.present)
    text = " ".join(p.action for p in parts)
    assert "Alpha" in text and "Sky" in text
    runner = GameRunner(games["user"], running=())
    report = uninstall.run(parts, runner=runner)
    assert runner.calls == []
    assert any("Alpha" in line for line in report.kept)
    assert (games["mc"] / "launcher_profiles.json").read_text(encoding="utf-8") == games["profiles_text"]


def test_kept_games_are_never_deleted_with_a_folder_around_them(games):
    inv = uninstall._inventory(games["home"], Choices(), games["env"], None)
    uninstall.BUILDERS["games"](inv)
    assert any(uninstall._same(k, games["alpha_game"]) for k in inv.keep)
    assert any(uninstall._same(k, games["p_alpha"]) for k in inv.keep)


def test_ticked_removes_only_the_recorded_installations(games):
    runner = GameRunner(games["user"], running=())
    report = uninstall.run(_games_parts(games, games=True), runner=runner)
    assert report.failed == []
    profiles = _profiles(games)["profiles"]
    before = json.loads(games["profiles_text"])
    # Craft Conductor's two recorded installations are gone; everything else is exactly as it was
    assert "craft-conductor-alpha" not in profiles and "craft-conductor-sky" not in profiles
    for key in ("4f1c0e0a2b", "craft-conductor-moved", "mcsm-old", "latest-release"):
        assert profiles[key] == before["profiles"][key], key
    assert list(profiles) == [k for k in before["profiles"] if k in profiles]  # (the order kept too)
    after = _profiles(games)
    assert {k: v for k, v in after.items() if k != "profiles"} == {k: v for k, v in before.items() if k != "profiles"}
    deleted = set(runner.deleted())
    mc, versions = games["mc"], games["versions"]
    assert deleted == {
        games["ours"],  # (it holds nothing but Craft Conductor's games and notes)
        versions / "craft-conductor-alpha", versions / "craft-conductor-sky",
        mc / "launcher_profiles.json.craft-conductor-backup",
        games["p_alpha"],
    }
    assert [p.name for p in mc.iterdir() if p.name.endswith(".tmp")] == []
    lines = " ".join(report.removed)
    assert "Alpha" in lines and "Sky" in lines


def test_an_unrecorded_or_older_install_is_listed_never_guessed(games):
    runner = GameRunner(games["user"], running=())
    report = uninstall.run(_games_parts(games, games=True), runner=runner)
    deleted = runner.deleted()
    for kept in (games["versions"] / "craft-conductor-moved", games["versions"] / "mcsm-old", games["mc"] / "mcsm",
                 games["user"] / "elsewhere", games["instances"] / "craft-conductor-nomark",
                 games["instances"] / "My Pack", games["user"] / "mine",
                 games["versions"] / "fabric-loader-0.16.9-1.21.1", games["modrinth"]):
        assert not any(_under(kept, d) or _under(d, kept) for d in deleted), kept
    manual = " ".join(report.manual)
    assert "Moved" in manual  # (named like Craft Conductor's, but its folder isn't the one it made)
    assert "mcsm" in manual and "Old one" in manual  # (from before the rename)
    assert "craft-conductor-nomark" in manual  # (a Prism instance without Craft Conductor's mark)
    assert "Modrinth App" in manual and "Sky" in manual  # (the app made that profile itself: no record)


def test_the_microsoft_store_launchers_file_is_cleaned_too(games):
    store = games["mc"] / "launcher_profiles_microsoft_store.json"
    store.write_text(json.dumps({"profiles": {
        "craft-conductor-alpha": {"name": "Alpha", "type": "custom", "gameDir": str(games["alpha_game"])},
        "abc": {"name": "Theirs", "type": "custom"}}}, indent=2), encoding="utf-8")
    uninstall.run(_games_parts(games, games=True), runner=GameRunner(games["user"], running=()))
    assert list(_profiles(games, store.name)["profiles"]) == ["abc"]


@pytest.mark.parametrize("runner_kind", ["open", "cant-tell"])
def test_an_open_launcher_is_left_alone_and_listed(games, runner_kind):
    if runner_kind == "open":
        runner = GameRunner(games["user"], running={"minecraft", "prism"})
    else:
        runner = FakeRunner()  # (it can't tell whether a launcher is open: the cautious answer)
    report = uninstall.run(_games_parts(games, games=True), runner=runner)
    assert (games["mc"] / "launcher_profiles.json").read_text(encoding="utf-8") == games["profiles_text"]
    assert not any(_under(d, games["mc"]) or _under(d, games["prism"]) for d in runner.deleted())
    manual = " ".join(report.manual)
    assert "Minecraft Launcher is open" in manual and "Alpha" in manual and "Prism Launcher is open" in manual


def test_a_duplicated_installation_keeps_the_folder_it_shares(games):
    data = json.loads(games["profiles_text"])
    data["profiles"]["9d9d9d9d"] = {"name": "Alpha copy", "type": "custom", "gameDir": str(games["alpha_game"]),
                                    "lastVersionId": "craft-conductor-alpha"}
    (games["mc"] / "launcher_profiles.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    runner = GameRunner(games["user"], running=())
    report = uninstall.run(_games_parts(games, games=True), runner=runner)
    profiles = _profiles(games)["profiles"]
    assert "craft-conductor-alpha" not in profiles and "9d9d9d9d" in profiles
    deleted = runner.deleted()
    assert not any(_under(games["alpha_game"], d) or _under(d, games["alpha_game"]) for d in deleted)
    assert games["versions"] / "craft-conductor-alpha" not in deleted
    assert games["sky_game"] in deleted  # (Sky's folder goes; the shared one stays, so the rest goes one by one)
    assert "Alpha copy" in " ".join(report.manual)


def test_a_change_made_after_the_plan_is_kept(games):
    parts = _games_parts(games, games=True)
    data = json.loads(games["profiles_text"])
    data["profiles"]["craft-conductor-sky"]["gameDir"] = str(games["user"] / "my-sky")  # (the person moved it)
    data["profiles"]["new1"] = {"name": "Made just now", "type": "custom"}
    (games["mc"] / "launcher_profiles.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    runner = GameRunner(games["user"], running=())
    report = uninstall.run(parts, runner=runner)
    profiles = _profiles(games)["profiles"]
    assert "craft-conductor-alpha" not in profiles
    assert profiles["craft-conductor-sky"]["gameDir"] == str(games["user"] / "my-sky") and "new1" in profiles
    deleted = runner.deleted()
    assert not any(_under(games["sky_game"], d) or _under(d, games["sky_game"]) for d in deleted)
    assert games["versions"] / "craft-conductor-sky" not in deleted
    assert "Sky" in " ".join(report.manual)


def test_an_unreadable_launchers_file_is_never_rewritten(games):
    (games["mc"] / "launcher_profiles.json").write_text("{not json", encoding="utf-8")
    runner = GameRunner(games["user"], running=())
    report = uninstall.run(_games_parts(games, games=True), runner=runner)
    assert (games["mc"] / "launcher_profiles.json").read_text(encoding="utf-8") == "{not json"
    deleted = runner.deleted()
    for game in (games["alpha_game"], games["sky_game"]):  # (their installations may still be in that file)
        assert not any(_under(game, d) or _under(d, game) for d in deleted), game
    assert games["p_alpha"] in deleted  # (Prism is apart)
    assert "launcher_profiles.json" in " ".join(report.manual)


def test_an_unknown_folder_in_craft_conductors_minecraft_folder_stays(games):
    (games["ours"] / "half-done" / "mods").mkdir(parents=True)  # (a setup that never finished: no mark)
    runner = GameRunner(games["user"], running=())
    report = uninstall.run(_games_parts(games, games=True), runner=runner)
    deleted = runner.deleted()
    assert games["ours"] not in deleted
    assert {games["alpha_game"], games["sky_game"], games["ours"] / "servers.json", games["ours"] / "extras"} <= set(deleted)
    assert not any(_under(d, games["ours"] / "half-done") for d in deleted)
    assert "half-done" in " ".join(report.manual)


@pytest.mark.parametrize("kind", ["junction", "symlink"])
def test_a_game_folder_reached_through_a_link_isnt_deleted(games, tmp_path, kind):
    import shutil
    elsewhere = tmp_path / "other-drive" / "instances"
    elsewhere.parent.mkdir()
    shutil.move(str(games["instances"]), str(elsewhere))
    _link(games["instances"], elsewhere, kind)
    runner = GameRunner(games["user"], running=())
    report = uninstall.run(_games_parts(games, games=True), runner=runner)
    assert not any(_under(d, games["instances"]) or _under(d, elsewhere) for d in runner.deleted())
    assert any("craft-conductor-alpha" in line for line in report.failed + report.manual)


def test_no_launchers_means_no_games(world):
    parts = _parts(world, games=True)
    assert not parts["games"].present


def test_the_plan_looks_for_launchers_in_the_persons_own_folders(world):
    """Without the tests' stand-ins, the launchers are looked for from the environment and home folder
    given to plan() (here: the temporary home), never this process's own."""
    user = world["user"]
    env = {**world["env"], "APPDATA": str(user / "AppData" / "Roaming")}
    mc = joinmod.minecraft_dir(env, user)
    assert _under(mc, user)
    for found in (launchersmod.prism_dirs(env, user), launchersmod.modrinth_dirs(env, user),
                  launchersmod.curseforge_dirs(env, user)):
        assert found and all(_under(d, user) for d in found)
    game = _game_folder(mc / "craft-conductor" / "alpha")
    (mc / "launcher_profiles.json").write_text(json.dumps({"profiles": {
        "craft-conductor-alpha": {"name": "Alpha", "type": "custom", "gameDir": str(game)}}}), encoding="utf-8")
    parts = [p for p in uninstall.plan(world["home"], Choices(games=True), env=env) if p.key == "games"]
    assert any(p.present and "Alpha" in p.action for p in parts)


def test_the_system_runner_replaces_a_file_whole(tmp_path):
    target = tmp_path / "mc" / "launcher_profiles.json"
    target.parent.mkdir()
    target.write_text("{}", encoding="utf-8")
    uninstall.SystemRunner().write_text(target, '{"profiles": {}}\n')
    assert target.read_text(encoding="utf-8") == '{"profiles": {}}\n'
    assert [p.name for p in target.parent.iterdir()] == ["launcher_profiles.json"]


def test_the_system_runner_tells_whether_a_launcher_is_open(monkeypatch):
    names = ["explorer.exe", "minecraftlauncher.exe", "javaw.exe"]
    monkeypatch.setattr(uninstall, "_process_names", lambda: names)
    runner = uninstall.SystemRunner()
    assert runner.launcher_running("minecraft") is True
    assert runner.launcher_running("prism") is False
    names[:] = ["/applications/prism launcher.app/contents/macos/prismlauncher"]
    assert runner.launcher_running("prism") is True
    monkeypatch.setattr(uninstall, "_process_names", lambda: None)  # (the process list can't be read)
    assert runner.launcher_running("minecraft") is None
