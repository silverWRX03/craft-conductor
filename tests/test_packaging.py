"""The standalone-executable paths: binary self-update, the setup wizard, and no-argument start."""

import hashlib
import os

import pytest

from craft_conductor import cli, selfupdate
from craft_conductor.http import HashMismatch
from craft_conductor.manager import Manager
from craft_conductor.mods import providers_for

from conftest import FakeLoader, FakeMojang


def publish_binary(http, content: bytes, sums_content: bytes | None = None):
    name = selfupdate.asset_name()
    http.files[f"https://dl.test/{name}"] = content
    digest = hashlib.sha256(sums_content if sums_content is not None else content).hexdigest()
    http.files["https://dl.test/SHA256SUMS.txt"] = f"{digest}  {name}\nabc  other-file\n".encode()
    return selfupdate.Release("0.2.0", "v0.2.0", "https://github.test/r", "", {
        name: f"https://dl.test/{name}", "SHA256SUMS.txt": "https://dl.test/SHA256SUMS.txt"})


def test_asset_names_cover_every_build():
    assert selfupdate.asset_name() in {"craft-conductor-linux-x64", "craft-conductor-linux-arm64", "craft-conductor-macos-arm64",
                                       "craft-conductor-macos-x64", "craft-conductor-windows-x64.exe",
                                       "craft-conductor-windows-arm64.exe"}


def test_binary_is_replaced_after_checksum(tmp_path, http):
    folder = tmp_path / "app"
    folder.mkdir()
    exe = folder / "craft-conductor"
    exe.write_bytes(b"old version")
    release = publish_binary(http, b"new version")
    assert selfupdate.install_binary(release, exe, http) == "installed Craft Conductor 0.2.0"
    assert exe.read_bytes() == b"new version"
    if os.name != "nt":
        assert os.access(exe, os.X_OK)
    left = sorted(p.name for p in folder.iterdir())
    # No temp files left behind (Windows keeps the old copy until the next start).
    assert left == (["craft-conductor", "craft-conductor.old"] if os.name == "nt" else ["craft-conductor"])


def test_tampered_binary_is_rejected(tmp_path, http):
    exe = tmp_path / "craft-conductor"
    exe.write_bytes(b"old version")
    release = publish_binary(http, b"evil", sums_content=b"new version")
    with pytest.raises(HashMismatch):
        selfupdate.install_binary(release, exe, http)
    assert exe.read_bytes() == b"old version"


def test_release_without_checksums_is_refused(tmp_path, http):
    exe = tmp_path / "craft-conductor"
    exe.write_bytes(b"old")
    release = publish_binary(http, b"new")
    del release.assets["SHA256SUMS.txt"]
    with pytest.raises(selfupdate.SelfUpdateError, match="SHA256SUMS"):
        selfupdate.install_binary(release, exe, http)


def test_frozen_build_needs_an_asset_for_this_platform(monkeypatch):
    monkeypatch.setattr(selfupdate, "frozen", lambda: True)
    ok, why = selfupdate.install_method(selfupdate.Release("0.2.0", "v0.2.0", "", "", {}))
    assert not ok and selfupdate.asset_name() in why
    monkeypatch.setattr("sys.argv", ["/opt/craft-conductor", "run", "--web"])
    assert selfupdate.restart_argv()[1:] == ["run", "--web"]  # the executable itself, same arguments


def test_the_restarted_download_unpacks_itself_again(monkeypatch):
    """After an update, the standalone download starts a fresh copy of itself. It must not reuse
    this copy's unpacked files (deleted when this copy exits): the new one broke with
    "No such file or directory: ...\\_MEI...\\base_library.zip" on its first download."""
    env = {"PATH": "/bin", "_PYI_APPLICATION_HOME_DIR": "/tmp/_MEI1", "_PYI_ARCHIVE_FILE": "/opt/craft-conductor",
           "_PYI_PARENT_PROCESS_LEVEL": "1", "_MEIPASS2": "/tmp/_MEI1"}
    monkeypatch.setattr(selfupdate, "frozen", lambda: True)
    assert selfupdate.restart_env(env) == {"PATH": "/bin", "PYINSTALLER_RESET_ENVIRONMENT": "1"}
    monkeypatch.setattr(selfupdate, "frozen", lambda: False)
    assert selfupdate.restart_env(env) == env  # (pip installs: nothing to do)

    # On Windows it starts the new copy itself (os.execv doesn't quote paths with spaces) and ends.
    monkeypatch.setattr(selfupdate, "frozen", lambda: True)
    monkeypatch.setattr("sys.argv", [r"C:\Users\Sam Doe\Craft Conductor.exe", "start"])
    monkeypatch.setattr(selfupdate, "WINDOWS", True)
    started, ended = [], []
    monkeypatch.setattr(selfupdate.subprocess, "Popen", lambda argv, env: started.append((argv, env)))
    monkeypatch.setattr(selfupdate.os, "_exit", lambda code: ended.append(code))
    monkeypatch.setattr(selfupdate.os, "execve", lambda *a: pytest.fail("no exec on Windows"))
    selfupdate.restart()
    assert started[0][0][1:] == ["start"] and started[0][1]["PYINSTALLER_RESET_ENVIRONMENT"] == "1" and ended == [0]


def test_no_arguments_means_start(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "cmd_start", lambda args: called.append(args.command) or 0)
    assert cli.main([]) == 0
    assert called == ["start"]


def test_wizard_builds_a_server(tmp_path, http, modrinth, fake_java, monkeypatch):
    modrinth.project("FAPI", "fabric-api", "Fabric API")
    modrinth.version("FAPI", "0.1", ["1.21.1"])
    modrinth.project("LITH", "lithium", "Lithium")
    modrinth.version("LITH", "1.0", ["1.21.1"])

    def fake_manager(cfg, echo=True):
        cfg.java_default = str(fake_java)
        mojang = FakeMojang(http, ["1.21.1"])
        return Manager(cfg, http=http, mojang=mojang, loader=FakeLoader(http, mojang),
                       providers=providers_for(cfg, http), echo=False)
    monkeypatch.setattr(cli, "Manager", fake_manager)
    monkeypatch.setattr(cli, "HttpClient", lambda: http)

    # loader (default fabric), version, memory, mods, network access, EULA
    answers = iter(["", "1.21.1", "6G", "lithium", "yes", "yes"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    root = tmp_path / "home" / "craft-conductor"
    assert cli._wizard(root)
    toml = (root / "craft-conductor.toml").read_text()
    assert 'id = "fabric-api"' in toml and 'id = "lithium"' in toml  # fabric-api added for fabric
    assert 'memory = "6G"' in toml
    assert "eula=true" in (root / "server" / "eula.txt").read_text()
    assert (root / "server" / "mods" / "LITH-1.0.jar").exists()
    assert 'host = "0.0.0.0"' in toml  # reachable from other devices, as asked


def test_wizard_stops_without_eula(tmp_path, monkeypatch):
    answers = iter(["fabric", "latest", "4G", "", "no", "no"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert not cli._wizard(tmp_path / "x")
    assert not (tmp_path / "x").exists()


def test_start_defaults_to_home_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("CRAFT_CONDUCTOR_HOME", str(tmp_path / "home"))
    assert cli.default_home() == (tmp_path / "home").resolve()


def test_headless_linux_has_no_browser(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert not cli.has_display()
    monkeypatch.setenv("DISPLAY", ":0")
    assert cli.has_display()


# ------------------------------------------------------------------ service
def test_service_unit_user_and_system(tmp_path, monkeypatch):
    from craft_conductor import service
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr(service, "craft_conductor_command", lambda: ["/opt/my apps/craft-conductor"])
    root = tmp_path / "My Server"
    user = service.plan(root, system=False)
    assert user.name == "craft-conductor-my-server.service"
    assert user.path == tmp_path / "cfg" / "systemd" / "user" / "craft-conductor-my-server.service"
    assert 'ExecStart="/opt/my apps/craft-conductor" run --web' in user.text
    assert f"WorkingDirectory={root}" in user.text and "WantedBy=default.target" in user.text
    system = service.plan(root, system=True)
    assert str(system.path).replace("\\", "/") == "/etc/systemd/system/craft-conductor-my-server.service"
    assert "WantedBy=multi-user.target" in system.text and system.systemctl == ["systemctl"]


def test_service_install_and_uninstall(tmp_path, monkeypatch):
    import subprocess

    from craft_conductor import notice, service
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr(service, "supported", lambda: True)
    calls = []

    def runner(args, **kw):
        calls.append(args)
        return subprocess.CompletedProcess(args, 1 if args[0] == "loginctl" else 0, "", "not allowed")
    root = tmp_path / "srv"
    root.mkdir()
    messages = service.install(root, runner, system=False)
    unit = tmp_path / "cfg" / "systemd" / "user" / "craft-conductor-srv.service"
    assert unit.exists()
    assert ["systemctl", "--user", "enable", "--now", "craft-conductor-srv.service"] in calls
    assert any("sudo loginctl enable-linger" in m for m in messages)  # linger failed -> tell the user
    assert notice.accepted(root)  # the service can't answer the prompt, so it's recorded for this server

    assert service.uninstall(root, runner, system=False) == "removed craft-conductor-srv.service"
    assert not unit.exists()
    with pytest.raises(service.ServiceError):
        service.uninstall(root, runner, system=False)


def test_cmd_goes_through_the_real_parser(tmp_path, capsys):
    """`craft-conductor cmd` once crashed: its argument clashed with the subcommand's name."""
    assert cli.main(["-C", str(tmp_path), "--accept-notice", "init"]) == 0
    assert cli.main(["-C", str(tmp_path), "cmd", "say", "hello"]) == 1  # RCON is off: a clean error
    assert "RCON is disabled" in capsys.readouterr().out


def test_panel_service_for_a_computer_without_a_screen(tmp_path, monkeypatch, capsys):
    """`craft-conductor service install --panel`: the whole control panel at boot, managed from another PC."""
    import subprocess

    from craft_conductor import service
    home = tmp_path / "craft-conductor"
    monkeypatch.setenv("CRAFT_CONDUCTOR_HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("CRAFT_CONDUCTOR_LAN_IP", "192.168.1.50")
    monkeypatch.setattr(service, "supported", lambda: True)
    monkeypatch.setattr(service, "craft_conductor_command", lambda: ["/home/me/.local/bin/craft-conductor"])
    calls = []
    fake = lambda args, **kw: calls.append(args) or subprocess.CompletedProcess(args, 0, "", "")  # noqa: E731
    real_install = service.install
    monkeypatch.setattr(service, "install", lambda root, **kw: real_install(root, runner=fake, system=False, **kw))
    p = service.plan(home, system=False, panel=True)
    assert p.name == "craft_conductor.service"
    assert "ExecStart=/home/me/.local/bin/craft-conductor start --no-browser --web-host 0.0.0.0" in p.text
    assert "Environment=CRAFT_CONDUCTOR_HOME=" in p.text and str(home) in p.text

    assert cli.main(["service", "install", "--panel"]) == 0
    out = capsys.readouterr().out
    assert "http://192.168.1.50:8765/" in out and "first sign-in password: Craft-Conductor-" in out
    assert ["systemctl", "--user", "enable", "--now", "craft_conductor.service"] in calls
    import json
    assert json.loads((home / ".craft-conductor" / "hub.json").read_text())["web"]["host"] == "0.0.0.0"


def test_the_friends_download_opens_into_joining_and_updates_as_itself(monkeypatch, tmp_path):
    """craft-conductor-join-... is the same craft-conductor under a friendly name: it always opens into joining a
    server (even where servers run), and updates itself to the craft-conductor-join file."""
    monkeypatch.setattr(selfupdate.sys, "frozen", True, raising=False)
    monkeypatch.setattr(selfupdate.sys, "executable", str(tmp_path / "craft-conductor-join-windows-x64 (1).exe"))
    assert selfupdate.friend_build()  # a browser can add a duplicate-download suffix
    assert selfupdate.asset_name().startswith("craft-conductor-join-")
    assert selfupdate.asset_name(friend=False).startswith("craft-conductor-") and "join" not in selfupdate.asset_name(friend=False)
    monkeypatch.setattr(selfupdate.sys, "executable", str(tmp_path / "craft-conductor-join-windows-x64.exe"))
    assert selfupdate.friend_build()
    monkeypatch.setattr(cli, "default_home", lambda: tmp_path)
    (tmp_path / "servers").mkdir()  # this computer runs servers too
    assert cli._first_run_joining()
    monkeypatch.setattr(selfupdate.sys, "executable", str(tmp_path / "craft-conductor-windows-x64.exe"))
    assert not selfupdate.friend_build() and not cli._first_run_joining()


def test_service_and_restart_use_the_importable_python_module(monkeypatch):
    from craft_conductor import service

    monkeypatch.setattr(selfupdate, "frozen", lambda: False)
    monkeypatch.setattr(service.shutil, "which", lambda _: None)
    monkeypatch.setattr("sys.argv", ["craft-conductor", "start", "--no-browser"])
    assert service.craft_conductor_command()[1:] == ["-m", "craft_conductor"]
    assert selfupdate.restart_argv()[1:] == ["-m", "craft_conductor", "start", "--no-browser"]
