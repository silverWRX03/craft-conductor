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
