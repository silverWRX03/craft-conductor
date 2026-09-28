"""Whitelist through Discord: the websocket, the /whitelist command and what it answers."""

import json
import socket
import struct

import pytest

from mcsm import discordbot
from mcsm.discordbot import WebSocket, WhitelistBot, command_definition

GUILD = "123456789012345678"
ROLE = "223456789012345678"


def server_frame(payload: bytes, opcode=1, fin=True) -> bytes:
    """A frame as a server sends it (not masked)."""
    n = len(payload)
    head = bytes([(0x80 if fin else 0) | opcode])
    head += bytes([n]) if n < 126 else bytes([126]) + struct.pack(">H", n) if n < 65536 else bytes([127]) + struct.pack(">Q", n)
    return head + payload


def unmask(frame: bytes) -> tuple[int, bytes]:
    n, i = frame[1] & 0x7F, 2
    if n == 126:
        n, i = struct.unpack(">H", frame[2:4])[0], 4
    mask = frame[i:i + 4]
    return frame[0] & 0x0F, bytes(b ^ mask[k % 4] for k, b in enumerate(frame[i + 4:i + 4 + n]))


def test_websocket_frames():
    a, b = socket.socketpair()
    ws = WebSocket(a)
    ws.send_json({"op": 1, "d": None})
    op, data = unmask(b.recv(1000))
    assert op == 1 and json.loads(data) == {"op": 1, "d": None}
    big = json.dumps({"x": "y" * 30000}).encode()
    b.sendall(server_frame(b'{"op":10,') + server_frame(b"x", 9))  # a message, then a ping
    b.sendall(server_frame(big[:10], 1, fin=False) + server_frame(big[10:], 0))
    got = []
    for _ in range(20):
        got += ws.poll(0.2)
        if len(got) == 2:
            break
    assert got[0] == '{"op":10,' and json.loads(got[1]) == {"x": "y" * 30000}
    op, data = unmask(b.recv(1000))
    assert op == 10 and data == b"x"  # the ping was answered
    b.sendall(server_frame(struct.pack(">H", 4004) + b"bad token", 8))
    with pytest.raises(discordbot.GatewayError) as e:
        ws.poll(0.5)
    assert e.value.code == 4004
    a.close()
    b.close()


def test_the_command_lists_servers_only_when_there_are_several():
    one = command_definition([{"id": "alpha", "name": "Alpha"}])
    assert one["name"] == "whitelist" and [o["name"] for o in one["options"]] == ["name"]
    two = command_definition([{"id": "alpha", "name": "Alpha"}, {"id": "beta", "name": "Beta"}])
    assert two["options"][1]["choices"] == [{"name": "Alpha", "value": "alpha"}, {"name": "Beta", "value": "beta"}]


class FakeHub:
    def __init__(self, servers):
        self.servers = servers
        self.asked, self.allowed = [], []
        self.http = None

    def summary_for_discord(self):
        return self.servers

    def add_join_request(self, sid, name, ip):
        self.asked.append((sid, name, ip))
        return "asked"

    def whitelist_from_discord(self, sid, name, who):
        self.allowed.append((sid, name, who))
        return f"added {name} to the whitelist"


def interaction(name, server=None, roles=()):
    options = [{"name": "name", "type": 3, "value": name}] + ([{"name": "server", "type": 3, "value": server}] if server else [])
    return {"type": 2, "guild_id": GUILD, "data": {"name": "whitelist", "options": options},
            "member": {"roles": list(roles), "user": {"id": "42", "username": "steve_discord"}}}


def test_asking_goes_to_the_players_page():
    hub = FakeHub([{"id": "alpha", "name": "Alpha"}])
    bot = WhitelistBot(hub, "x" * 60, {"mode": "ask"})
    assert "will let Steve in" in bot.handle(interaction("Steve"))
    assert hub.asked == [("alpha", "Steve", "discord:42")] and not hub.allowed
    assert "isn't a Minecraft name" in bot.handle(interaction("no spaces allowed"))
    assert "direct message" in bot.handle({**interaction("Steve"), "guild_id": None})


def test_letting_in_and_the_role():
    hub = FakeHub([{"id": "alpha", "name": "Alpha"}, {"id": "beta", "name": "Beta"}])
    bot = WhitelistBot(hub, "x" * 60, {"mode": "allow", "role": ROLE})
    assert "Pick which" in bot.handle(interaction("Steve"))
    assert "can join Beta now" in bot.handle(interaction("Steve", "beta", roles=[ROLE]))
    assert hub.allowed == [("beta", "Steve", "steve_discord")]
    bot.handle(interaction("Alex", "beta", roles=[]))  # without the role: asked for instead
    assert hub.asked == [("beta", "Alex", "discord:42")]


def test_turning_it_on_needs_a_bot(hub_env):
    from test_hub import login
    hub, c = hub_env
    login(c)
    status, r, _ = c.post("/api/hub/discord/whitelist", {"enabled": True, "mode": "ask"})
    assert status == 400
    with pytest.raises(ValueError):
        discordbot.check_settings("everyone", "")
    with pytest.raises(ValueError):
        discordbot.check_settings("allow", "not-a-role")
