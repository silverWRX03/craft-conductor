"""Whitelist through Discord: friends type ``/whitelist <their Minecraft name>`` in the user's
Discord server, and are asked for on the Players page (or let straight in, if the user chose that,
optionally only for members with a role).

The bot (the same one that posts invites, see discord.py) listens on Discord's gateway, a
websocket, for the command only: it asks for no intents, so it never sees messages. Slash
commands are registered in each Discord server the bot is in, and answered privately (only the
person who typed it sees the answer). The websocket is a small client on the standard library.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import random
import re
import socket
import ssl
import struct
import threading
import time
from urllib.parse import urlparse

from . import __version__
from .discord import API, SNOWFLAKE, Discord, DiscordError

log = logging.getLogger(__name__)

GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"
NAME = re.compile(r"[A-Za-z0-9_]{3,16}")
COMMAND = "whitelist"
MODES = ("ask", "allow")   # ask: the Players page's requests; allow: straight onto the whitelist
MAX_FRAME = 4 << 20
EPHEMERAL = 64


class GatewayError(OSError):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code  # (Discord's close code, if it closed the connection)


# ------------------------------------------------------------------ the websocket
class WebSocket:
    """Just enough of RFC 6455 for Discord's gateway: text frames, ping/pong, close."""

    def __init__(self, sock):
        self.sock = sock
        self.buf = b""
        self.parts: list[bytes] = []

    @classmethod
    def connect(cls, url: str, timeout: float = 20) -> "WebSocket":
        u = urlparse(url)
        if u.scheme != "wss" or not u.hostname:
            raise GatewayError("the gateway address isn't a secure websocket")
        raw = socket.create_connection((u.hostname, u.port or 443), timeout=timeout)
        sock = ssl.create_default_context().wrap_socket(raw, server_hostname=u.hostname)
        key = base64.b64encode(os.urandom(16)).decode()
        path = (u.path or "/") + (f"?{u.query}" if u.query else "")
        sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {u.hostname}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                      f"User-Agent: CraftConductor/{__version__}\r\n\r\n").encode())
        ws = cls(sock)
        head = ws._read_until(b"\r\n\r\n")
        status = head.split(b"\r\n", 1)[0]
        if b" 101 " not in status + b" ":
            raise GatewayError(f"Discord's gateway said no ({status.decode(errors='replace')})")
        import hashlib
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
        if accept.lower() not in head.lower():
            raise GatewayError("Discord's gateway answered strangely")
        return ws

    def _read_until(self, marker: bytes) -> bytes:
        while marker not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise GatewayError("the connection closed")
            self.buf += chunk
            if len(self.buf) > 65536:
                raise GatewayError("the gateway's answer is too long")
        head, self.buf = self.buf.split(marker, 1)
        return head

    def send(self, data: bytes, opcode: int = 1) -> None:
        mask = os.urandom(4)
        n = len(data)
        head = bytes([0x80 | opcode])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(head + mask + masked)

    def send_json(self, obj) -> None:
        self.send(json.dumps(obj, separators=(",", ":")).encode())

    def _frame(self):
        """A whole frame from the buffer, or None if more is needed: (fin, opcode, payload)."""
        b = self.buf
        if len(b) < 2:
            return None
        fin, opcode, masked, n = b[0] & 0x80, b[0] & 0x0F, b[1] & 0x80, b[1] & 0x7F
        i = 2
        if n == 126:
            if len(b) < 4:
                return None
            n, i = struct.unpack(">H", b[2:4])[0], 4
        elif n == 127:
            if len(b) < 10:
                return None
            n, i = struct.unpack(">Q", b[2:10])[0], 10
        if n > MAX_FRAME:
            raise GatewayError("a message from the gateway is too big")
        mask = b""
        if masked:
            if len(b) < i + 4:
                return None
            mask, i = b[i:i + 4], i + 4
        if len(b) < i + n:
            return None
        payload, self.buf = b[i:i + n], b[i + n:]
        if mask:
            payload = bytes(x ^ mask[k % 4] for k, x in enumerate(payload))
        return bool(fin), opcode, payload

    def poll(self, wait: float) -> list[str]:
        """Text messages that arrived within ``wait`` seconds (answers pings; raises on close)."""
        out = []
        self.sock.settimeout(max(0.05, wait))
        try:
            chunk = self.sock.recv(65536)
        except (socket.timeout, TimeoutError):
            chunk = None
        except ssl.SSLWantReadError:
            chunk = None
        if chunk == b"":
            raise GatewayError("the connection closed")
        if chunk:
            self.buf += chunk
        while (f := self._frame()) is not None:
            fin, opcode, payload = f
            if opcode == 9:
                self.send(payload, 10)
            elif opcode == 8:
                code = struct.unpack(">H", payload[:2])[0] if len(payload) >= 2 else 1000
                raise GatewayError(f"Discord closed the connection ({code})", code)
            elif opcode in (0, 1, 2):
                self.parts.append(payload)
                if fin:
                    out.append(b"".join(self.parts).decode("utf-8", errors="replace"))
                    self.parts = []
        return out

    def close(self) -> None:
        try:
            self.send(struct.pack(">H", 1000), 8)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


# ------------------------------------------------------------------- the bot
def command_definition(servers: list[dict]) -> dict:
    """/whitelist name:<Minecraft name> [server:<which one>] (the server only when there are several)."""
    options = [{"type": 3, "name": "name", "description": "Your Minecraft name", "required": True,
                "min_length": 3, "max_length": 16}]
    if len(servers) > 1:
        options.append({"type": 3, "name": "server", "description": "Which Minecraft server", "required": True,
                        "choices": [{"name": str(s["name"])[:100], "value": s["id"]} for s in servers[:25]]})
    return {"name": COMMAND, "type": 1, "description": "Ask to be let into the Minecraft server",
            "options": options, "dm_permission": False}


class WhitelistBot:
    """Runs in its own thread while Whitelist through Discord is on (hub.discord_whitelist)."""

    def __init__(self, hub, token: str, settings: dict):
        self.hub = hub
        self.discord = Discord(hub.http, token)
        self.token = token
        self.settings = settings
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.state = "starting"       # starting, connected, retrying, stopped
        self.error = ""
        self.guilds: set[str] = set()
        self.app_id: str | None = None
        self._registered: str | None = None   # the command registered (so it's only sent when it changes)

    # --------------------------------------------------------------- running
    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, daemon=True, name="discord-whitelist")
        self.thread.start()

    def close(self) -> None:
        self.stop.set()

    def _run(self) -> None:
        delay = 5
        while not self.stop.is_set():
            started = time.monotonic()
            try:
                self._session()
            except (OSError, ValueError, DiscordError) as e:
                self.error = str(e)
                code = e.code if isinstance(e, GatewayError) else None
                if code in (4004, 4010, 4011, 4012, 4013, 4014):  # a bad token or settings: retrying won't help
                    log.warning("Whitelist through Discord stopped: %s", e)
                    self.state = "stopped"
                    return
                log.info("Discord connection lost (%s); trying again", e)
            if self.stop.is_set():
                break
            self.state = "retrying"
            delay = 5 if time.monotonic() - started > 300 else min(300, delay * 2)
            self.stop.wait(delay + random.random() * 3)
        self.state = "stopped"

    def _session(self) -> None:
        ws = WebSocket.connect(GATEWAY)
        try:
            hello = None
            while hello is None and not self.stop.is_set():
                for text in ws.poll(10):
                    msg = json.loads(text)
                    if msg.get("op") == 10:
                        hello = msg["d"]
                if hello is None:
                    raise GatewayError("Discord's gateway didn't say hello")
            interval = float(hello["heartbeat_interval"]) / 1000
            seq = None
            ws.send_json({"op": 2, "d": {"token": self.token, "intents": 0,
                                         "properties": {"os": os.name, "browser": "craft-conductor", "device": "craft-conductor"}}})
            next_beat = time.monotonic() + interval * random.random()
            acked = True
            while not self.stop.is_set():
                now = time.monotonic()
                if now >= next_beat:
                    if not acked:
                        raise GatewayError("Discord stopped answering")
                    ws.send_json({"op": 1, "d": seq})
                    acked, next_beat = False, now + interval
                for text in ws.poll(min(1.0, max(0.05, next_beat - time.monotonic()))):
                    msg = json.loads(text)
                    op = msg.get("op")
                    if msg.get("s") is not None:
                        seq = msg["s"]
                    if op == 11:
                        acked = True
                    elif op == 1:
                        ws.send_json({"op": 1, "d": seq})
                    elif op in (7, 9):
                        raise GatewayError("Discord asked to reconnect")
                    elif op == 0:
                        self._dispatch(msg.get("t"), msg.get("d") or {})
        finally:
            ws.close()

    def _dispatch(self, kind: str, d: dict) -> None:
        if kind == "READY":
            self.app_id = str(d.get("application", {}).get("id") or d.get("user", {}).get("id") or "")
            self.guilds = {str(g["id"]) for g in d.get("guilds", []) if SNOWFLAKE.fullmatch(str(g.get("id", "")))}
            self.state, self.error = "connected", ""
            log.info("Whitelist through Discord is on (in %d Discord server(s))", len(self.guilds))
            threading.Thread(target=self.register, daemon=True, name="discord-commands").start()
        elif kind == "GUILD_CREATE" and SNOWFLAKE.fullmatch(str(d.get("id", ""))):
            if str(d["id"]) not in self.guilds:
                self.guilds.add(str(d["id"]))
                self._registered = None
                threading.Thread(target=self.register, daemon=True, name="discord-commands").start()
        elif kind == "INTERACTION_CREATE":
            threading.Thread(target=self.answer, args=(d,), daemon=True, name="discord-interaction").start()

    # ---------------------------------------------------------------- commands
    def register(self, force: bool = False) -> None:
        """Put /whitelist in each Discord server the bot is in (again when the servers change)."""
        if not self.app_id:
            return
        body = [command_definition(self.hub.summary_for_discord())]
        sig = json.dumps(body, sort_keys=True) + ",".join(sorted(self.guilds))
        if sig == self._registered and not force:
            return
        for guild in sorted(self.guilds):
            try:
                self.hub.http.send_json("PUT", f"{API}/applications/{self.app_id}/guilds/{guild}/commands", body,
                                        headers=self.discord._headers)
            except Exception as e:
                log.warning("couldn't add /whitelist to a Discord server: %s", e)
                return
        self._registered = sig

    def unregister(self) -> None:
        for guild in sorted(self.guilds):
            try:
                self.hub.http.send_json("PUT", f"{API}/applications/{self.app_id}/guilds/{guild}/commands", [],
                                        headers=self.discord._headers)
            except Exception as e:
                log.warning("couldn't take /whitelist out of a Discord server: %s", e)

    def answer(self, interaction: dict) -> None:
        """Answer at once ("thinking…", seen only by them), then with the result."""
        iid, token = str(interaction.get("id", "")), str(interaction.get("token", ""))
        if interaction.get("type") != 2 or not SNOWFLAKE.fullmatch(iid) or not re.fullmatch(r"[A-Za-z0-9_.-]{20,500}", token):
            return
        try:
            self.hub.http.post_json(f"{API}/interactions/{iid}/{token}/callback", {"type": 5, "data": {"flags": EPHEMERAL}},
                                    headers=self.discord._headers)
        except Exception as e:
            log.warning("couldn't answer on Discord: %s", e)
            return
        try:
            text = self.handle(interaction)
        except Exception as e:
            log.exception("Whitelist through Discord failed")
            text = f"Something went wrong: {e}"
        try:
            self.hub.http.patch_json(f"{API}/webhooks/{self.app_id or interaction.get('application_id')}/{token}/messages/@original",
                                     {"content": text[:1900], "allowed_mentions": {"parse": []}}, headers=self.discord._headers)
        except Exception as e:
            log.warning("couldn't answer on Discord: %s", e)

    def handle(self, interaction: dict) -> str:
        """What to answer someone who typed /whitelist."""
        data = interaction.get("data") or {}
        if data.get("name") != COMMAND:
            return "Craft Conductor doesn't know that command."
        if not interaction.get("guild_id"):
            return "Use /whitelist in the Discord server, not in a direct message."
        opts = {str(o.get("name")): o.get("value") for o in data.get("options") or [] if isinstance(o, dict)}
        name = str(opts.get("name") or "").strip()
        if not NAME.fullmatch(name):
            return "That isn't a Minecraft name: 3 to 16 letters, numbers and _ (as it shows in the game)."
        servers = self.hub.summary_for_discord()
        sid = str(opts.get("server") or (servers[0]["id"] if len(servers) == 1 else ""))
        server = next((s for s in servers if s["id"] == sid), None)
        if server is None:
            return "Pick which Minecraft server (the server option)."
        member = interaction.get("member") or {}
        user = member.get("user") or {}
        who = str(user.get("global_name") or user.get("username") or "someone")[:40]
        role = str(self.settings.get("role") or "")
        may_allow = self.settings.get("mode") == "allow" and (not role or role in [str(r) for r in member.get("roles") or []])
        if may_allow:
            message = self.hub.whitelist_from_discord(sid, name, who)
            return f"✓ {name} can join {server['name']} now. ({message})"
        result = self.hub.add_join_request(sid, name, f"discord:{user.get('id', '')}")
        if result == "already allowed":
            return f"{name} is already on the whitelist of {server['name']}: just join."
        if result == "slow down":
            return "You asked a moment ago; wait a few seconds."
        return f"Asked. The owner of {server['name']} will let {name} in (Craft Conductor tells them)."

    def status(self) -> dict:
        return {"state": self.state, "error": self.error, "guilds": len(self.guilds)}


def check_settings(mode: str, role: str) -> tuple[str, str]:
    if mode not in MODES:
        raise ValueError("pick Ask me first or Let them in")
    role = str(role or "").strip()
    if role and not SNOWFLAKE.fullmatch(role):
        raise ValueError("that isn't a Discord role")
    return mode, role
