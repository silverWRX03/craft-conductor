"""Reaching the control panel from outside (item 15): Tailscale, Cloudflare's quick tunnel, the
"which program is this?" check, the password reset's code, and the safety rules a power user may
switch off.

The tunnels' headers below are what each one really sent (checked 2026-10-16, through
``tailscale serve`` and a ``cloudflared`` quick tunnel to a program that printed them); names and
addresses are replaced by made-up ones.
"""

from __future__ import annotations

import io
import json
import re
import socket
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from craft_conductor import cloudflare, config as configmod, peer, tailscale, tunnels
from craft_conductor.tunnel import AgentError

from test_hub import login, reset_here
from test_remote import STRONG, as_other_device
from test_web import Client, wait_for

TS_NAME = "pc.example-tailnet.ts.net"
CF_NAME = "brave-otter-lake-moon.trycloudflare.com"
# What `tailscale serve` passed on (a visitor's own X-Forwarded-For was replaced, its own
# Tailscale-User-Login removed), and what Cloudflare's quick tunnel did (its X-Forwarded-For keeps
# what the visitor sent in front; a visitor's own Cf-Connecting-Ip is refused at Cloudflare).
TAILSCALE = {"Host": TS_NAME, "Tailscale-Headers-Info": "https://tailscale.com/s/serve-headers",
             "Tailscale-User-Login": "someone@example.com", "Tailscale-User-Name": "someone",
             "X-Forwarded-For": "100.101.102.103", "X-Forwarded-Host": TS_NAME, "X-Forwarded-Proto": "https"}
# Through Funnel (checked 2026-10-17, from the internet): no identity, the visitor's own
# X-Forwarded-For and Tailscale-User-Login replaced or removed, Host passed on as sent.
FUNNEL = {"Host": TS_NAME, "Tailscale-Funnel-Request": "?1", "X-Forwarded-For": "198.51.100.20",
          "X-Forwarded-Host": TS_NAME, "X-Forwarded-Proto": "https"}
CLOUDFLARE = {"Host": CF_NAME, "Cdn-Loop": "cloudflare; loops=1; subreqs=1", "Cf-Connecting-Ip": "198.51.100.7",
              "Cf-Ipcountry": "US", "Cf-Ray": "8f00000000000000-OMA", "Cf-Visitor": '{"scheme":"https"}',
              "Cf-Warp-Tag-Id": "00000000-0000-0000-0000-000000000000", "Cf-Worker": "trycloudflare.com",
              "X-Forwarded-For": "1.2.3.4,198.51.100.7", "X-Forwarded-Proto": "https"}


def at(c, port, headers):
    """A client that talks to the control panel's way in on ``port``, as that tunnel would."""
    door = Client(f"http://127.0.0.1:{port}")
    door.call = (lambda f: (lambda m, p, body=None, headers_=None, raw=None:
                            f(m, p, body, {**headers, **(headers_ or {})}, raw)))(door.call)
    return door


def call(client, method, path, body=None, headers=None):
    return client.call(method, path, body, headers)


def pin_owner(c):
    login(c)
    assert c.post("/api/auth/change", {"mode": "pin", "secret": "2468"})[0] == 200


# ------------------------------------------------------------- which program
def test_a_connection_from_this_program_is_a_person_here():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    with srv, socket.create_connection(srv.getsockname()) as c:
        conn, addr = srv.accept()
        with conn:
            prog = peer.program(addr, srv.getsockname()[1])
            if prog is None:
                pytest.skip("this system doesn't say which program opened a connection")
            assert prog.name.startswith("python") and not prog.other_account
            assert peer.a_person_here(addr, srv.getsockname()[1])
    assert not peer.a_person_here(("10.0.0.2", 50000), 8765)   # (not this computer at all)
    assert not peer.a_person_here(("127.0.0.1", 1), 2)        # (no such connection)


def test_tunnel_programs_and_programs_that_cant_be_told_arent_here(monkeypatch):
    for name in ("playit.exe", "playitd-service.exe", "playit", "cloudflared.exe", "tailscaled", "ngrok",
                 "ssh.exe", "sshd", "frpc"):
        assert peer.is_tunnel(name), name
    for name in ("chrome.exe", "msedge", "firefox", "Safari", "python3"):
        assert not peer.is_tunnel(name), name
    cases = [peer.Program(1, r"C:\Program Files\playit_gg\bin\playit.exe"),
             peer.Program(1, "/usr/bin/cloudflared"),
             peer.Program(1, other_account=True),             # (a service: Windows won't say which)
             peer.Program(1, "/usr/bin/firefox", other_account=True),
             peer.Program(1, ""), None]
    for prog in cases:
        monkeypatch.setattr(peer, "program", lambda peer_, port, p=prog: p)
        assert not peer.a_person_here(("127.0.0.1", 5), 8765), prog
    monkeypatch.setattr(peer, "program", lambda *a: (_ for _ in ()).throw(OSError("no")))
    assert not peer.a_person_here(("127.0.0.1", 5), 8765)
    monkeypatch.setattr(peer, "program", lambda *a: peer.Program(1, r"C:\Program Files\Google\Chrome\chrome.exe"))
    assert peer.a_person_here(("127.0.0.1", 5), 8765)


def test_linux_connection_table_is_read(tmp_path, monkeypatch):
    """/proc/net/tcp: the connection's account, then the process holding its socket."""
    import os
    import sys
    if sys.byteorder != "little" or not hasattr(os, "readlink"):
        pytest.skip("written for a little-endian computer")
    proc = tmp_path / "proc"
    (proc / "net").mkdir(parents=True)
    uid = os.geteuid() if hasattr(os, "geteuid") else 1000
    monkeypatch.setattr(os, "geteuid", lambda: uid, raising=False)
    # 127.0.0.1:51000 -> 127.0.0.1:8765 (0x1F8D), inode 4242; and one of another account's
    (proc / "net" / "tcp").write_text(
        "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
        f"   0: 0100007F:C738 0100007F:223D 01 00000000:00000000 00:00000000 00000000  {uid}        0 4242 1\n"
        f"   1: 0100007F:C739 0100007F:223D 01 00000000:00000000 00:00000000 00000000  {uid + 1}        0 4343 1\n")
    (proc / "net" / "tcp6").write_text("header\n")
    links = {str(proc / "77" / "fd" / "3"): "socket:[4242]", str(proc / "77" / "exe"): "/usr/bin/firefox"}
    (proc / "77" / "fd").mkdir(parents=True)
    (proc / "77" / "fd" / "1").write_text("")   # (closed while it's looked at: skipped, not the whole process)
    (proc / "77" / "fd" / "3").write_text("")

    def readlink(p):
        if str(p) not in links:
            raise FileNotFoundError(p)
        return links[str(p)]
    monkeypatch.setattr(os, "readlink", readlink)
    import ipaddress
    found = peer._linux(ipaddress.ip_address("127.0.0.1"), 0xC738, 8765, proc=proc)
    assert found == peer.Program(77, "/usr/bin/firefox")
    other = peer._linux(ipaddress.ip_address("127.0.0.1"), 0xC739, 8765, proc=proc)
    assert other.other_account


# ------------------------------------------- a tunnel that adds no header (playit.gg)
def test_a_tunnel_that_adds_no_header_isnt_this_computer(hub_env, monkeypatch):
    """playit.gg's tunnels pass the connection on as it is: it comes from 127.0.0.1, with a Host the
    visitor chose. The connection's program tells it apart: no PIN, no reset, no local-only
    action, and its visitors can't lock out the person at the computer."""
    hub, c = hub_env
    pin_owner(c)
    from craft_conductor import web
    here = {"yes": True}
    real = peer.a_person_here
    monkeypatch.setattr(peer, "a_person_here", lambda addr, port: here["yes"] and real(addr, port))
    here["yes"] = False
    tunnel = Client(c.base)
    assert tunnel.get("/api/auth")[1]["local"] is False
    assert tunnel.post("/api/login", {"password": "2468"})[0] == 403
    assert tunnel.post("/api/auth/reset-code", {})[0] == 403
    assert tunnel.post("/api/auth/reset-local", {})[0] == 403
    assert not (hub.home / web.RESET_FILE).exists()
    for _ in range(6):
        tunnel.post("/api/login", {"password": "wrong"})
    here["yes"] = True
    me = Client(c.base)
    assert me.get("/api/auth")[1]["local"] is True
    assert me.post("/api/login", {"password": "2468"})[0] == 200   # (not locked out by them)
    tunnel.cookie = me.cookie   # (even signed in, a local-only action isn't for them)
    here["yes"] = False
    status, body, _ = tunnel.post("/api/hub/open", {"what": "home"})
    assert status == 403 and "own computer" in body["error"]


# --------------------------------------------------------------- Tailscale
@pytest.fixture
def tailscale_door(hub_env):
    hub, c = hub_env
    pin_owner(c)
    assert c.post("/api/auth/change", {"mode": "password", "secret": STRONG})[0] == 200
    port = hub.ui.doors.open("tailscale")
    hub.ui.doors.hosts["tailscale"] = TS_NAME
    return hub, c, port


def test_tailscale_requests_are_from_elsewhere(tailscale_door):
    hub, c, port = tailscale_door
    ts = at(c, port, TAILSCALE)
    info = ts.get("/api/auth")[1]
    assert info["local"] is False
    assert ts.post("/api/auth/reset-code", {})[0] == 403 and ts.post("/api/auth/reset-local", {})[0] == 403
    # The visitor names the computer itself: Tailscale passes Host on as sent, so it's refused here.
    assert call(ts, "GET", "/api/auth", headers={"Host": "localhost"})[0] == 421
    assert call(ts, "GET", "/api/auth", headers={"Host": "127.0.0.1"})[0] == 421
    assert ts.post("/api/login", {"password": STRONG})[0] == 200
    assert ts.get("/api/hub")[0] == 200
    status, _, headers = at(c, port, TAILSCALE).call("POST", "/api/login", {"password": STRONG})
    assert "Secure" in headers["Set-Cookie"]   # (its address is HTTPS)
    status, body, _ = ts.call("POST", "/api/hub/open", {"what": "home"})
    assert status == 403 and "own computer" in body["error"]


def test_tailscale_visitors_are_told_apart(tailscale_door):
    hub, c, port = tailscale_door
    one = at(c, port, TAILSCALE)
    for _ in range(5):
        assert one.post("/api/login", {"password": "wrong"})[0] == 401
    assert one.post("/api/login", {"password": STRONG})[0] == 429
    other = at(c, port, {**TAILSCALE, "X-Forwarded-For": "100.101.102.104"})
    assert other.post("/api/login", {"password": STRONG})[0] == 200   # (another device of yours)
    assert Client(c.base).post("/api/login", {"password": STRONG})[0] == 200  # (and this computer)
    # Funnel's visitors are told apart by their internet address too (Tailscale replaces theirs).
    stranger = at(c, port, {**FUNNEL, "X-Forwarded-For": "203.0.113.5"})
    for _ in range(5):
        stranger.post("/api/login", {"password": "wrong"})
    assert stranger.post("/api/login", {"password": STRONG})[0] == 429
    assert stranger.get("/api/auth")[1]["local"] is False
    assert at(c, port, FUNNEL).post("/api/login", {"password": STRONG})[0] == 200          # (another visitor)
    assert at(c, port, {**TAILSCALE, "X-Forwarded-For": "203.0.113.5"}).post("/api/login", {"password": STRONG})[0] == 200
    assert call(at(c, port, FUNNEL), "GET", "/api/auth", headers={"Host": "localhost"})[0] == 421


def test_tailscale_headers_sent_to_the_usual_port_are_not_believed(tailscale_door):
    """Only Tailscale's own way in believes what Tailscale says: anyone (a playit.gg visitor, say)
    can send those headers to the usual port, and choosing a new X-Forwarded-For each time
    mustn't get them past the limit."""
    hub, c, port = tailscale_door
    for i in range(6):
        Client(c.base).call("POST", "/api/login", {"password": "wrong"},
                            {**TAILSCALE, "Host": "127.0.0.1", "X-Forwarded-For": f"100.64.0.{i}"})
    status, _, _ = Client(c.base).call("POST", "/api/login", {"password": STRONG}, {"Via": "1.1 proxy", "Host": "127.0.0.1"})
    assert status == 429


def test_a_serve_from_an_earlier_version_moves_to_tailscales_door(hub_env):
    hub, c = hub_env
    calls = []
    panel = hub.ui.httpd.server_address[1]

    def status(port):
        return {"installed": True, "running": True, "name": TS_NAME, "serving": port == panel, "funnel": False}

    def serve(port, funnel):
        calls.append((port, funnel))
        return {"ok": True}
    hub.ui.doors.resume(status, serve)
    door = hub.ui.doors.port("tailscale")
    assert calls == [(door, False)] and door != panel
    assert hub.ui.doors.saved_tailscale() == {"port": door, "name": TS_NAME, "funnel": False}
    assert at(c, door, TAILSCALE).get("/api/auth")[0] == 200
    # Next start: the same door again, and Tailscale left as it is.
    hub.ui.doors.close("tailscale")
    calls.clear()
    hub.ui.doors.resume(status, serve)
    assert hub.ui.doors.port("tailscale") == door and calls == []


def test_tailscale_serve_and_funnel_commands(monkeypatch):
    seen = []

    class P:
        def __init__(self, argv, **kw):
            seen.append(argv)
            self.stdout = io.StringIO("")

        def poll(self):
            return 0

        def wait(self, *a):
            return 0

        def kill(self):
            pass
    monkeypatch.setattr(tailscale, "exe", lambda: "/usr/bin/tailscale")
    monkeypatch.setattr(tailscale.subprocess, "Popen", P)
    assert tailscale.serve(23456)["ok"] and tailscale.serve(23456, funnel=True)["ok"]
    assert seen == [["/usr/bin/tailscale", "serve", "--bg", "--https=443", "http://127.0.0.1:23456"],
                    ["/usr/bin/tailscale", "funnel", "--bg", "--https=443", "http://127.0.0.1:23456"]]


# --------------------------------------------------------------- Cloudflare
class FakeCloudflared:
    """Stands in for cloudflared: says its address like the real one, and stops when told."""
    instances: list = []

    def __init__(self, argv, **kw):
        self.argv, self.kw = argv, kw
        self.pid = 4242
        self._done = threading.Event()
        self._r, self._ws = socket.socketpair()
        self.stdout = self._r.makefile("r", encoding="utf-8")
        self._w = self._ws.makefile("w", encoding="utf-8")
        self._w.write("2026-10-16T00:00:00Z INF Requesting new quick Tunnel on trycloudflare.com...\n")
        self._w.write(f"2026-10-16T00:00:03Z INF |  https://{CF_NAME}                    |\n")
        self._w.flush()
        FakeCloudflared.instances.append(self)

    def poll(self):
        return 0 if self._done.is_set() else None

    def wait(self, timeout=None):
        if not self._done.wait(timeout if timeout is not None else 30):
            import subprocess
            raise subprocess.TimeoutExpired("cloudflared", timeout)
        return 0

    def terminate(self):
        self._w.close()
        self._ws.close()
        self._done.set()

    kill = terminate


@pytest.fixture
def cloudflare_door(hub_env, monkeypatch):
    hub, c = hub_env
    login(c)
    assert c.post("/api/auth/change", {"mode": "password", "secret": STRONG})[0] == 200
    tools = hub.ui.doors.tools()
    (tools / cloudflare.program_path(tools).name).write_bytes(b"cloudflared")
    (tools / cloudflare.STATE).write_text(json.dumps({"version": "2026.10.1", "sha256": cloudflare._sha256(cloudflare.program_path(tools))}))
    monkeypatch.setattr(cloudflare, "_check", lambda path, check=None: None)
    FakeCloudflared.instances.clear()
    real = cloudflare.QuickTunnel
    monkeypatch.setattr(cloudflare, "QuickTunnel", lambda *a, **kw: real(*a, **{**kw, "popen": FakeCloudflared}))
    return hub, c


def test_the_quick_tunnel_opens_for_hours_and_its_requests_are_from_elsewhere(cloudflare_door, monkeypatch):
    hub, c = cloudflare_door
    monkeypatch.setenv("TUNNEL_URL", "http://127.0.0.1:1")         # (cloudflared's own settings: never passed on)
    monkeypatch.setenv("CRAFT_CONDUCTOR_CURSEFORGE_API_KEY", "not-a-real-key")
    status, info, _ = c.post("/api/hub/cloudflare/start", {})
    assert status == 200 and info["running"] and info["address"] == f"https://{CF_NAME}"
    assert abs(info["ends"] - (time.time() + cloudflare.HOURS * 3600)) < 60
    p = FakeCloudflared.instances[-1]
    port = hub.ui.doors.port("cloudflare")
    assert p.argv[1:] == ["tunnel", "--config", str(hub.ui.doors.tools() / "cloudflared-config.yml"), "--no-autoupdate",
                          "--metrics", "127.0.0.1:0", "--url", f"http://127.0.0.1:{port}"]
    assert "TUNNEL_URL" not in p.kw["env"] and "CRAFT_CONDUCTOR_CURSEFORGE_API_KEY" not in p.kw["env"]
    assert "shell" not in p.kw and port != hub.ui.httpd.server_address[1]
    cf = at(c, port, CLOUDFLARE)
    assert cf.get("/api/auth")[1]["local"] is False
    assert cf.post("/api/auth/reset-code", {})[0] == 403 and cf.post("/api/auth/reset-local", {})[0] == 403
    assert call(cf, "GET", "/api/auth", headers={"Host": "localhost"})[0] == 421
    # Visitors are told apart by Cloudflare's Cf-Connecting-Ip, not the X-Forwarded-For they wrote.
    for _ in range(5):
        cf.post("/api/login", {"password": "wrong"})
    assert cf.post("/api/login", {"password": STRONG})[0] == 429
    assert at(c, port, {**CLOUDFLARE, "Cf-Connecting-Ip": "198.51.100.8"}).post("/api/login", {"password": STRONG})[0] == 200
    assert Client(c.base).post("/api/login", {"password": STRONG})[0] == 200
    # Stop: the door closes with it.
    assert c.post("/api/hub/cloudflare/stop", {})[1]["running"] is False
    wait_for(lambda: hub.ui.doors.port("cloudflare") is None)
    with pytest.raises(OSError):
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/auth", timeout=3)


def test_the_quick_tunnel_closes_by_itself_after_its_hours(cloudflare_door, tmp_path):
    hub, c = cloudflare_door
    ended = []
    q = cloudflare.QuickTunnel("cloudflared", 1, tmp_path / "c.yml", on_end=lambda t, why: ended.append(why),
                               popen=FakeCloudflared, hours=0.5 / 3600)
    assert q.wait(5) == f"https://{CF_NAME}"
    wait_for(lambda: ended == ["time"])
    assert not q.running()


def test_the_quick_tunnel_needs_a_strong_password(hub_env):
    hub, c = hub_env
    login(c)
    status, body, _ = c.post("/api/hub/cloudflare/start", {})
    assert status == 400 and "strong password" in body["error"]


def test_the_quick_tunnel_is_the_owners(cloudflare_door):
    from craft_conductor import access
    for path in ("/api/hub/cloudflare/start", "/api/hub/cloudflare/stop", "/api/hub/cloudflare/download", "/api/hub/risks"):
        assert access.hub_route_need("POST", path) == access.OWNER, path


RELEASE = {"tag_name": "2026.10.1", "body": "### SHA256 Checksums:\n```\ncloudflared-windows-amd64.exe: " + "a" * 64
           + "\ncloudflared-linux-amd64: " + "b" * 64 + "\n```",
           "assets": [{"name": "cloudflared-windows-amd64.exe", "size": 55325120, "digest": "sha256:" + "a" * 64,
                       "browser_download_url": cloudflare.RELEASE_DOWNLOADS + "2026.10.1/cloudflared-windows-amd64.exe"},
                      {"name": "cloudflared-linux-amd64", "size": 40227032, "digest": "sha256:" + "c" * 64,
                       "browser_download_url": cloudflare.RELEASE_DOWNLOADS + "2026.10.1/cloudflared-linux-amd64"}]}


def test_cloudflared_comes_only_from_cloudflares_release_with_matching_checksums():
    a = cloudflare.release_asset(RELEASE, "cloudflared-windows-amd64.exe")
    assert a["sha256"] == "a" * 64 and a["url"].startswith("https://github.com/cloudflare/cloudflared/releases/download/")
    with pytest.raises(AgentError, match="doesn't match"):   # (GitHub's and the release notes' differ)
        cloudflare.release_asset(RELEASE, "cloudflared-linux-amd64")
    bad = json.loads(json.dumps(RELEASE))
    bad["assets"][0]["browser_download_url"] = "https://example.com/cloudflared.exe"
    with pytest.raises(AgentError, match="isn't where it should be"):
        cloudflare.release_asset(bad, "cloudflared-windows-amd64.exe")
    bad = json.loads(json.dumps(RELEASE))
    del bad["assets"][0]["digest"]
    with pytest.raises(AgentError, match="no checksum"):
        cloudflare.release_asset(bad, "cloudflared-windows-amd64.exe")
    bad = json.loads(json.dumps(RELEASE))
    bad["assets"][0]["size"] = 1 << 30
    with pytest.raises(AgentError, match="size"):
        cloudflare.release_asset(bad, "cloudflared-windows-amd64.exe")
    with pytest.raises(AgentError, match="didn't look right"):
        cloudflare.release_asset({**RELEASE, "tag_name": "../x"}, "cloudflared-windows-amd64.exe")
    assert cloudflare.asset_name("Windows", "AMD64") == "cloudflared-windows-amd64.exe"
    assert cloudflare.asset_name("Linux", "aarch64") == "cloudflared-linux-arm64"
    assert cloudflare.asset_name("Darwin", "arm64") is None   # (Homebrew on a Mac)


class FakeHttp:
    def __init__(self, release, content):
        self.release, self.content, self.downloads = release, content, []

    def get_json(self, url, **kw):
        assert url == cloudflare.RELEASE_API
        return self.release

    def download(self, url, dest, sha256=None, max_bytes=None, progress=None):
        import hashlib
        self.downloads.append(url)
        dest.write_bytes(self.content)
        if hashlib.sha256(self.content).hexdigest() != sha256:
            dest.unlink()
            raise ValueError("checksum mismatch")
        return dest


def test_a_cloudflared_download_is_checked_and_nothing_bad_is_kept(tmp_path):
    import hashlib
    tmp_path = tmp_path / "tools"
    tmp_path.mkdir()
    good = b"the real cloudflared"
    release = json.loads(json.dumps(RELEASE))
    digest = hashlib.sha256(good).hexdigest()
    release["assets"][0]["digest"] = "sha256:" + digest
    release["body"] = release["body"].replace("a" * 64, digest)
    name = "cloudflared-windows-amd64.exe"
    with pytest.raises(ValueError):   # (changed on the way)
        cloudflare.download(FakeHttp(release, b"something else"), tmp_path, name=name, check=lambda p: None)
    assert not cloudflare.installed(tmp_path) and not list(tmp_path.iterdir())

    def unsigned(path):
        raise AgentError("cloudflared's signature isn't valid, so it wasn't run")
    if cloudflare.os.name == "nt":
        with pytest.raises(AgentError, match="signature"):
            cloudflare.download(FakeHttp(release, good), tmp_path, name=name, check=unsigned)
        assert not cloudflare.installed(tmp_path)
    path = cloudflare.download(FakeHttp(release, good), tmp_path, name=name, check=lambda p: None)
    assert path.read_bytes() == good and cloudflare.installed(tmp_path)["version"] == "2026.10.1"
    assert cloudflare.verify(tmp_path, check=lambda p: None) == str(path)
    path.write_bytes(b"changed afterwards")
    with pytest.raises(AgentError, match="changed since"):
        cloudflare.verify(tmp_path, check=lambda p: None)


def test_nothing_is_downloaded_until_the_button(hub_env, monkeypatch):
    hub, c = hub_env
    login(c)
    asked = []
    monkeypatch.setattr(cloudflare, "download", lambda *a, **kw: asked.append(1))
    info = c.get("/api/hub/cloudflare")[1]
    assert not info["installed"] and info["hours"] == 4 and info["downsides"] and not asked
    assert c.post("/api/hub/cloudflare/download", {})[0] == 200
    wait_for(lambda: asked == [1])


def test_cloudflared_signer_is_cloudflare():
    seen = {}

    def run(args):
        seen["args"] = args
        return json.dumps({"status": "Valid", "subject": 'CN="Cloudflare, Inc.", O="Cloudflare, Inc.", L=San Francisco, C=US'})
    from craft_conductor.tunnel import check_signature
    check_signature("x.exe", run=run, signer=cloudflare.SIGNER)
    with pytest.raises(AgentError, match="isn't signed by Cloudflare"):
        check_signature("x.exe", run=lambda a: json.dumps({"status": "Valid", "subject": "CN=Someone, O=Someone"}),
                        signer=cloudflare.SIGNER, whose="Cloudflare", what="cloudflared", done="run")
    assert seen["args"][0].replace("\\", "/").lower().endswith("system32/windowspowershell/v1.0/powershell.exe")


# --------------------------------------------------------- the reset's code
def test_the_reset_needs_the_code_from_the_file(hub_env):
    hub, c = hub_env
    pin_owner(c)
    me = Client(c.base)
    assert me.post("/api/auth/reset-local", {"code": "AAAA-BBBB"})[0] == 401
    first = me.post("/api/auth/reset-code", {})[1]["file"]
    old = re.search(r"[A-Z0-9]{4}-[A-Z0-9]{4}", Path(first).read_text()).group(0)
    assert Path(first).parent == hub.home and "works once, for 10 minutes" in Path(first).read_text()
    me.post("/api/auth/reset-code", {})   # (a new code: the old one stops)
    assert me.post("/api/auth/reset-local", {"code": old})[0] == 401
    hub.ui.reset_code = (hub.ui.reset_code[0], time.time() - 1)   # (ten minutes later)
    code = hub.ui.reset_code[0]
    assert me.post("/api/auth/reset-local", {"code": code})[0] == 401
    assert reset_here(me)[0] == 200
    assert me.post("/api/login", {"password": "PASSWORD"})[0] == 200


def test_wrong_reset_codes_are_limited(hub_env):
    hub, c = hub_env
    me = Client(c.base)
    me.post("/api/auth/reset-code", {})
    for _ in range(4):
        assert me.post("/api/auth/reset-local", {"code": "WRONG-CODE"})[0] == 401
    code = hub.ui.reset_code[0]
    assert me.post("/api/auth/reset-local", {"code": "WRONG-CODE"})[0] == 401
    assert me.post("/api/auth/reset-local", {"code": code})[0] == 429


# ------------------------------------------------ safety rules switched off
def test_a_safety_rule_is_switched_off_only_at_this_computer_and_back_on_anywhere(hub_env):
    hub, c = hub_env
    login(c)
    assert c.post("/api/auth/change", {"mode": "password", "secret": STRONG})[0] == 200
    away = as_other_device(Client(c.base))
    assert away.post("/api/login", {"password": STRONG})[0] == 200
    status, body, _ = away.post("/api/hub/risks", {"name": "no-sign-in-limit", "on": True})
    assert status == 403 and "own computer" in body["error"]
    info = c.post("/api/hub/risks", {"name": "no-sign-in-limit", "on": True})[1]
    assert {r["name"]: r["on"] for r in info["risks"]}["no-sign-in-limit"]
    assert hub.web.accept_risks == ["no-sign-in-limit"]
    assert json.loads((hub.state_dir / "hub.json").read_text())["web"]["accept_risks"] == ["no-sign-in-limit"]
    assert away.post("/api/hub/risks", {"name": "no-sign-in-limit", "on": False})[0] == 200
    assert hub.web.accept_risks == []
    assert c.post("/api/hub/risks", {"name": "made-up", "on": True})[0] == 400
    from craft_conductor import access
    assert access.hub_route_need("GET", "/api/hub/risks") == access.OWNER


def test_safety_rules_from_craft_conductor_toml(tmp_path):
    root = tmp_path / "s"
    root.mkdir()
    path = root / configmod.CONFIG_NAME
    path.write_text(configmod.render_template("fabric", "latest").replace(
        "[web]\n", '[web]\naccept_risks = ["any-port", "no-such-rule", "reset-without-code"]\n', 1))
    web = configmod.load(root).web
    assert web.accept_risks == ["reset-without-code", "any-port"] == web.risks_in_file
    path.write_text(path.read_text().replace('accept_risks = ["any-port", "no-such-rule", "reset-without-code"]',
                                             'accept_risks = "any-port"'))
    with pytest.raises(configmod.ConfigError):
        configmod.load(root)


def test_risks_set_in_the_file_cant_be_undone_on_the_page(hub_env):
    hub, c = hub_env
    login(c)
    hub.web.risks_in_file = ["any-port"]
    hub.web.accept_risks = ["any-port"]
    status, body, _ = c.post("/api/hub/risks", {"name": "any-port", "on": False})
    assert status == 409 and "craft-conductor.toml" in body["error"]


def test_weak_remote_password_allows_a_pin_but_never_the_default(hub_env):
    hub, c = hub_env
    login(c)
    away = as_other_device(Client(c.base))
    assert away.post("/api/login", {"password": "PASSWORD"})[0] == 403
    assert c.post("/api/hub/risks", {"name": "weak-remote-password", "on": True})[0] == 200
    assert away.post("/api/login", {"password": "PASSWORD"})[0] == 403   # (never the default)
    assert c.post("/api/auth/change", {"mode": "pin", "secret": "2468"})[0] == 200
    assert away.post("/api/login", {"password": "2468"})[0] == 200
    assert c.post("/api/hub/network", {"enabled": True})[0] == 200    # (and the network, with a PIN)


def test_no_sign_in_limit_and_reset_without_code(hub_env):
    hub, c = hub_env
    pin_owner(c)
    assert c.post("/api/hub/risks", {"name": "no-sign-in-limit", "on": True})[0] == 200
    other = Client(c.base)
    for _ in range(8):
        assert other.post("/api/login", {"password": "1111"})[0] == 401
    assert other.post("/api/login", {"password": "2468"})[0] == 200
    assert other.post("/api/hub/risks", {"name": "reset-without-code", "on": True})[0] == 200
    assert other.get("/api/auth")[1]["reset_code"] is False
    assert Client(c.base).post("/api/auth/reset-local", {})[0] == 200   # (still only at this computer)


def test_funnel_only_when_its_rule_is_off(hub_env, monkeypatch):
    hub, c = hub_env
    login(c)
    assert c.post("/api/auth/change", {"mode": "password", "secret": STRONG})[0] == 200
    status, body, _ = c.post("/api/hub/phone/tailscale", {"on": True, "funnel": True})
    assert status == 403 and "Advanced" in body["error"]
    served = []
    monkeypatch.setattr(tailscale, "status", lambda port: {"installed": True, "running": True, "name": TS_NAME,
                                                           "serving": False, "funnel": False})
    monkeypatch.setattr(tailscale, "serve", lambda port, funnel=False: served.append((port, funnel)) or {"ok": True})
    assert c.post("/api/hub/risks", {"name": "tailscale-funnel", "on": True})[0] == 200
    assert c.post("/api/hub/phone/tailscale", {"on": True, "funnel": True})[1]["ok"]
    assert served == [(hub.ui.doors.port("tailscale"), True)]
