"""Installing mcsm on a Linux computer over SSH, from the New server page."""

import pytest

from mcsm import remoteinstall as ri

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
    monkeypatch.setattr(ri, "launch", lambda *a: launched.append(a))
    assert c.post("/api/hub/remote-install/open", body)[0] == 200 and launched == [("192.168.1.50", "minecraft", 22)]
    # A terminal opens on the server's own screen: never for a browser elsewhere.
    status, _, _ = c.call("POST", "/api/hub/remote-install/open", body, headers=AWAY)
    assert status in (401, 403) and len(launched) == 1
