from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from craft_conductor.process import ServerProcess
from craft_conductor.web import Api, ApiError


def _running_server_process(tmp_path):
    server = ServerProcess(["java", "-jar", "server.jar"], tmp_path)
    child = MagicMock()
    child.poll.return_value = None
    child.stdin = MagicMock()
    server.proc = child
    return server, child.stdin


@pytest.mark.parametrize(
    "payload",
    [
        "say hello\nstop",
        "say hello\rstop",
        "say hello\r\nstop",
        "list\n/op attacker",
        "save-all\rstop",
    ],
)
def test_server_stdin_rejects_multiline_command_injection(tmp_path, payload: str) -> None:
    server, stdin = _running_server_process(tmp_path)

    with pytest.raises(ValueError, match="one line"):
        server.send(payload)

    stdin.write.assert_not_called()
    stdin.flush.assert_not_called()


def test_shell_metacharacters_are_written_literally_to_minecraft_stdin(tmp_path) -> None:
    server, stdin = _running_server_process(tmp_path)
    marker = tmp_path / "owned"
    payload = f'say hello; touch "{marker}" && $(whoami) | powershell -Command calc'

    server.send(payload)

    stdin.write.assert_called_once_with(payload + "\n")
    stdin.flush.assert_called_once_with()
    assert not marker.exists(), "console text must never be evaluated by a local OS shell"


def test_server_start_uses_argv_not_shell(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import craft_conductor.process as processmod
    import craft_conductor.limits as limits

    child = MagicMock()
    child.poll.return_value = None
    child.pid = 12345
    child.stdout = []
    child.stdin = MagicMock()
    popen = MagicMock(return_value=child)
    thread = MagicMock()
    monkeypatch.setattr(processmod.subprocess, "Popen", popen)
    monkeypatch.setattr(processmod.threading, "Thread", MagicMock(return_value=thread))
    monkeypatch.setattr(limits, "popen_options", lambda cpu_cores, priority: {})

    argv = ["java", "-Xmx4G", "-jar", "server.jar", "nogui"]
    server = ServerProcess(argv, tmp_path)
    server.start()

    args, kwargs = popen.call_args
    assert args[0] == argv
    assert kwargs.get("shell", False) is False, "Minecraft must be launched without an OS shell"
    assert kwargs["cwd"] == tmp_path
    assert kwargs["stdin"] is processmod.subprocess.PIPE
    thread.start.assert_called_once_with()


def _api_with_command_spy():
    api = Api.__new__(Api)
    send = MagicMock()
    api.d = SimpleNamespace(send_command=send)
    return api, send


def test_web_console_rejects_newline_before_reaching_daemon() -> None:
    api, send = _api_with_command_spy()

    with pytest.raises(ApiError, match="single command"):
        api.command({}, {"command": "/say first\nstop"})

    send.assert_not_called()


def test_web_console_forwards_shell_syntax_as_plain_minecraft_text() -> None:
    api, send = _api_with_command_spy()
    payload = "/say ; && | $(whoami) `id` %COMSPEC%"

    api.command({}, {"command": payload})

    send.assert_called_once_with(payload.lstrip("/"))


def test_daemon_boundary_does_not_bypass_serverprocess_crlf_guard(tmp_path) -> None:
    """The web layer only checks LF today; the stdin boundary must remain the final CR/LF guard."""
    from craft_conductor.daemon import Daemon

    process, stdin = _running_server_process(tmp_path)
    daemon = Daemon.__new__(Daemon)
    daemon.proc = process
    daemon.console = MagicMock()

    with pytest.raises(ValueError, match="one line"):
        Daemon.send_command(daemon, "say first\rstop")

    stdin.write.assert_not_called()


# ------------------------------------------------- control characters, length, logs
@pytest.mark.parametrize("payload", ["say hi\x00op attacker", "say \x1b[2Jcleared", "say a\x08\x08\x08stop",
                                     "say " + "x" * 40000])
def test_server_stdin_rejects_control_characters_and_overlong_commands(tmp_path, payload: str) -> None:
    server, stdin = _running_server_process(tmp_path)
    with pytest.raises(ValueError, match="control characters|too long"):
        server.send(payload)
    stdin.write.assert_not_called()


def test_tabs_and_unicode_are_ordinary_console_text(tmp_path) -> None:
    server, stdin = _running_server_process(tmp_path)
    server.send("say\tgrüße 日本 ✓")
    stdin.write.assert_called_once_with("say\tgrüße 日本 ✓\n")


@pytest.mark.parametrize("payload", ["/say hi\rstop", "/say hi\x00", "/say \x1b]0;title\x07", "/say " + "y" * 40000])
def test_web_console_refuses_and_logs_without_echoing_the_command(payload: str, caplog) -> None:
    import logging
    api, send = _api_with_command_spy()

    with caplog.at_level(logging.WARNING), pytest.raises(ApiError) as e:
        api.command({}, {"command": payload})

    assert e.value.status == 400
    send.assert_not_called()
    logged = [r.getMessage() for r in caplog.records if "refused a console command" in r.getMessage()]
    assert logged, "a refusal must be logged"
    assert all("stop" not in m and "\x00" not in m and "yyyy" not in m for m in logged), \
        "the log says why, not what was typed"


def test_daemon_does_not_show_a_refused_command_as_if_it_ran(tmp_path) -> None:
    from craft_conductor.daemon import Daemon, LogBuffer

    process, stdin = _running_server_process(tmp_path)
    daemon = Daemon.__new__(Daemon)
    daemon.proc = process
    daemon.console = LogBuffer(10)

    with pytest.raises(ValueError):
        Daemon.send_command(daemon, "say hi\x00")

    assert daemon.console.since(0)[0] == []
    stdin.write.assert_not_called()


def test_say_flattens_names_it_did_not_choose_instead_of_failing(tmp_path) -> None:
    """Countdown messages are built from mod and version names: one with a line break used to
    raise in the middle of an update's countdown."""
    server, stdin = _running_server_process(tmp_path)
    server.say("Server restarting in 1 minute: Minecraft 1.21 -> evil\nstop\r\x00mod")
    stdin.write.assert_called_once_with("say Server restarting in 1 minute: Minecraft 1.21 -> evil stop mod\n")
