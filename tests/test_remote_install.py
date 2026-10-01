"""Installing craft-conductor on a Linux computer over SSH, from the New server page."""

import pytest

from craft_conductor import remoteinstall as ri

from test_hub import login
from test_remote import AWAY


def test_only_plain_names_go_into_the_command():
    assert ri.check(" 192.168.1.50 ", "minecraft", "22") == ("192.168.1.50", "minecraft", 22)
    assert ri.check("[fe80::1]", "mc", 2222) == ("fe80::1", "mc", 2222)
    assert ri.check("pi.local", "pi", 22)[0] == "pi.local"
    for host, user, port in (("1.2.3.4;reboot", "mc", 22), ("$(id)", "mc", 22), ("-oProxyCommand=x", "mc", 22),
                             ("host", "root", 22), ("host", "Bad User", 22), ("host", "mc", 0), ("host", "mc", "x")):
        with pytest.raises(ri.RemoteInstallError):
            ri.check(host, user, port)
    cmd = ri.command_line("192.168.1.50", "minecraft", 22)
    assert cmd.startswith("ssh -t -p 22 -o StrictHostKeyChecking=accept-new minecraft@192.168.1.50 ")
    assert ri.INSTALLER in cmd and cmd.endswith('| sh"')
    assert ri.panel_url("192.168.1.50") == "http://192.168.1.50:8765/"


@pytest.mark.parametrize("platform", ["linux", "darwin", "nt"])
def test_a_terminal_window_runs_ssh(monkeypatch, platform):
    opened = []
    monkeypatch.setattr(ri, "_ssh_exe", lambda: "/usr/bin/ssh")
    monkeypatch.setattr(ri.shutil, "which", lambda name: f"/usr/bin/{name}" if name in ("ssh", "gnome-terminal") else None)
    monkeypatch.setattr(ri.os, "name", "nt" if platform == "nt" else "posix")
    monkeypatch.setattr(ri.sys, "platform", "win32" if platform == "nt" else platform)
    ri.launch("192.168.1.50", "minecraft", 22, popen=lambda args, **kw: opened.append((args, kw)))
    args, kw = opened[0]
    text = " ".join(args)
    assert "minecraft@192.168.1.50" in text and "StrictHostKeyChecking=accept-new" in text and ri.INSTALLER in text
    if platform == "nt":
        assert args[:2] == ["cmd", "/k"] and kw["creationflags"] == 0x10
    elif platform == "darwin":
        assert args[0] == "osascript"
    else:
        assert args[:2] == ["gnome-terminal", "--"]


def test_no_ssh_or_terminal_says_so(monkeypatch):
    monkeypatch.setattr(ri, "_ssh_exe", lambda: None)
    with pytest.raises(ri.RemoteInstallError, match="OpenSSH"):
        ri.launch("h", "mc", 22, popen=lambda *a, **k: None)


def test_install_over_ssh_from_the_panel(hub_env, monkeypatch):
    hub, c = hub_env
    login(c)
    body = {"host": "192.168.1.50", "user": "minecraft", "port": 22}
    r = c.post("/api/hub/remote-install", body)[1]
    assert r["panel"] == "http://192.168.1.50:8765/" and "minecraft@192.168.1.50" in r["command"]
    assert c.post("/api/hub/remote-install", {**body, "host": "x;y"})[0] == 400
    launched = []
    monkeypatch.setattr(ri, "launch", lambda *a, **kw: launched.append((*a, kw)))
    assert c.post("/api/hub/remote-install/open", body)[0] == 200
    assert launched == [("192.168.1.50", "minecraft", 22, {"rented": False, "tunnel": False})]
    # A terminal opens on the server's own screen: never for a browser elsewhere.
    status, _, _ = c.call("POST", "/api/hub/remote-install/open", body, headers=AWAY)
    assert status in (401, 403) and len(launched) == 1


def test_a_rented_server_keeps_its_panel_private(hub_env, monkeypatch):
    """A server on the internet (a VPS): the installer keeps its control panel on the server
    (CRAFT_CONDUCTOR_PANEL_LOCAL=1 -> --local-only), and it's reached through an SSH tunnel."""
    from craft_conductor import remoteinstall
    assert remoteinstall.on_home_network("192.168.1.50") and remoteinstall.on_home_network("raspberrypi.local")
    assert not remoteinstall.on_home_network("203.0.113.7") and not remoteinstall.on_home_network("mc.example.com")
    hub, c = hub_env
    login(c)
    r = c.post("/api/hub/remote-install", {"host": "203.0.113.7", "user": "minecraft", "port": 22})[1]
    assert r["rented"] and "CRAFT_CONDUCTOR_PANEL_LOCAL=1 sh" in r["command"] and r["panel"] == "http://localhost:8775/"
    assert "-L 8775:127.0.0.1:8765" in r["tunnel_command"] and "minecraft@203.0.113.7" in r["tunnel_command"]
    home = c.post("/api/hub/remote-install", {"host": "203.0.113.7", "user": "minecraft", "port": 22, "rented": False})[1]
    assert not home["rented"] and "CRAFT_CONDUCTOR_PANEL_LOCAL" not in home["command"] and home["tunnel_command"] is None
    opened = []
    monkeypatch.setattr(remoteinstall, "launch", lambda *a, **kw: opened.append(kw))
    assert c.post("/api/hub/remote-install/open", {"host": "203.0.113.7", "user": "minecraft", "port": 22, "tunnel": True})[0] == 200
    assert opened[-1] == {"rented": True, "tunnel": True}


def test_the_panel_service_can_stay_local(tmp_path, monkeypatch, capsys):
    from craft_conductor import cli, service
    monkeypatch.setattr(cli, "default_home", lambda: tmp_path)
    monkeypatch.setattr(service, "install", lambda home, panel: ["installed (pretend)"])
    args = cli.build_parser().parse_args(["service", "install", "--panel", "--local-only"])
    assert cli._panel_service(args) == 0
    out = capsys.readouterr().out
    assert "ssh -N -L 8775:127.0.0.1:" in out and "0.0.0.0" not in out
    from craft_conductor.hub import Hub
    assert Hub(tmp_path).web.host == "127.0.0.1"
