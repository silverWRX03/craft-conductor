"""playit.gg tunnels: the address, the Minecraft status ping through it, and what the
Dashboard and invites do with it."""

import json
import socket
import struct
import threading

import pytest

from craft_conductor import tunnel
from craft_conductor.config import ConfigError, parse

from test_hub import login


def fake_minecraft(motd: str) -> int:
    """A tiny server that answers a Minecraft status request, like a server behind a tunnel."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen()

    def serve():
        conn, _ = srv.accept()
        with conn:
            conn.recv(1024)
            body = json.dumps({"description": {"text": motd}, "players": {"online": 2, "max": 20},
                               "version": {"name": "1.21.1"}}).encode()
            payload = b"\x00" + tunnel._varint(len(body)) + body
            conn.sendall(tunnel._varint(len(payload)) + payload)
        srv.close()
    threading.Thread(target=serve, daemon=True).start()
    return srv.getsockname()[1]


def test_addresses():
    assert tunnel.parse_address("fox-lake.gl.joinmc.link") == ("fox-lake.gl.joinmc.link", 25565)
    assert tunnel.parse_address("147.185.221.1:12345") == ("147.185.221.1", 12345)
    assert tunnel.parse_address("") is None
    for bad in ("http://x.gl.joinmc.link", "a b", "x.link:99999", "x.link:"):
        with pytest.raises(tunnel.TunnelError):
            tunnel.parse_address(bad)
    with pytest.raises(tunnel.TunnelError, match="add the port"):
        tunnel.parse_address("name.gl.joinmc.link", default_port=0)
    with pytest.raises(ConfigError, match="tunnel.address"):
        parse(__import__("pathlib").Path("."), {"server": {"loader": "fabric"}, "tunnel": {"address": "not an address!"}})


def test_the_check():
    port = fake_minecraft("Weekend Survival")
    assert tunnel.ping("127.0.0.1", port)["motd"] == "Weekend Survival"
    port = fake_minecraft("Weekend Survival")
    ok = tunnel.check(f"127.0.0.1:{port}", "Weekend Survival", running=True)
    assert ok["status"] == "ok" and ok["answer"]["online"] == 2
    port = fake_minecraft("Someone else's server")
    assert tunnel.check(f"127.0.0.1:{port}", "Weekend Survival", running=True)["status"] == "wrong"
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    dead = closed.getsockname()[1]
    closed.close()
    down = tunnel.check(f"127.0.0.1:{dead}", "Weekend Survival", running=True)
    assert down["status"] == "down" and "playit" in down["words"]
    assert tunnel.check(f"127.0.0.1:{dead}", "x", running=False)["status"] == "stopped"
    assert tunnel.check("", "x", running=True)["status"] == "off"
    assert tunnel.agent_running() in (True, False, None)


def test_dashboard_and_invites(hub_env):
    hub, c = hub_env
    login(c)
    assert c.get("/api/servers/alpha/tunnel")[1]["address"] == ""
    assert c.post("/api/servers/alpha/settings", {"tunnel_address": "no good!"})[0] == 400
    assert c.post("/api/servers/alpha/settings", {"tunnel_address": "fox-lake.gl.joinmc.link"})[0] == 200
    r = c.get("/api/servers/alpha/tunnel")[1]
    assert r["address"] == "fox-lake.gl.joinmc.link" and r["status"]["status"] in ("stopped", "down")
    # Friends' downloads never go through playit.gg (a plain TCP tunnel needs its paid plan): the
    # internet link uses the public address, with the download port opened while a link works.
    share = hub.share_settings()
    assert "tunnel" not in share and not hasattr(hub, "share_tunnel")
    assert c.post("/api/hub/share", {"port": share["port"], "address": "203.0.113.9", "tunnel": "fox-lake.gl.joinmc.link:40123"})[0] == 200
    assert "tunnel" not in hub._hub_file()["share"]
    assert c.post("/api/servers/alpha/client", {"enabled": True})[0] == 200
    from craft_conductor import join
    link = c.get("/api/servers/alpha/client")[1]["links"]["internet"]
    invite = join.parse_invite(link)
    assert (invite.host, invite.port) == ("203.0.113.9", share["port"])
