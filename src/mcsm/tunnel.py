"""playit.gg tunnels: friends join through an address playit.gg gives you, without port
forwarding on your router.

playit.gg is an outside service, run by its own company: mcsm doesn't control it, and when it
has problems (or its agent program isn't running on this computer), friends can't connect
through it however healthy the server is. So mcsm checks the tunnel the way a friend's game
does: it asks for the server's status through the tunnel address (a Minecraft "server list
ping") and says whether that reached *this* server.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import struct
import subprocess
import time

STATUS_PAGE = "https://status.playit.gg"
DOWNLOAD = "https://playit.gg/download"
GUIDE = "https://playit.gg/support/"
HOST = re.compile(r"(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*")


class TunnelError(ValueError):
    pass


def parse_address(text: str, default_port: int = 25565) -> tuple[str, int] | None:
    """``host`` or ``host:port`` (as playit.gg shows it); None for empty."""
    text = (text or "").strip()
    if not text:
        return None
    m = re.fullmatch(r"([^:\s]+)(?::(\d{1,5}))?", text)
    if not m or not HOST.fullmatch(m.group(1)):
        raise TunnelError("the tunnel address should look like name.gl.joinmc.link or 147.185.221.1:12345")
    if m.group(2) is None and not default_port:
        raise TunnelError("add the port playit.gg gives the tunnel, like name.gl.joinmc.link:12345")
    port = int(m.group(2) or default_port)
    if not 1 <= port <= 65535:
        raise TunnelError("the port must be between 1 and 65535")
    return m.group(1), port


# ------------------------------------------------------ Minecraft server list ping
def _varint(n: int) -> bytes:
    out = bytearray()
    n &= 0xFFFFFFFF
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _read_varint(sock) -> int:
    n = shift = 0
    for _ in range(5):
        b = sock.recv(1)
        if not b:
            raise OSError("the connection closed")
        n |= (b[0] & 0x7F) << shift
        if not b[0] & 0x80:
            return n
        shift += 7
    raise OSError("not a Minecraft server")


def _recv_exact(sock, n: int) -> bytes:
    data = b""
    while len(data) < n:
        chunk = sock.recv(min(65536, n - len(data)))
        if not chunk:
            raise OSError("the connection closed")
        data += chunk
    return data


def ping(host: str, port: int, timeout: float = 6) -> dict:
    """Ask a Minecraft server (through whatever is in between) for its status: motd, players,
    version. Raises OSError when nothing answers like a Minecraft server."""
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.settimeout(timeout)
        h = host.encode()
        handshake = b"\x00" + _varint(767) + _varint(len(h)) + h + struct.pack(">H", port) + _varint(1)
        s.sendall(_varint(len(handshake)) + handshake + b"\x01\x00")  # + status request
        length = _read_varint(s)
        if not 0 < length <= 1 << 20:
            raise OSError("not a Minecraft server")
        body = _recv_exact(s, length)
    if body[:1] != b"\x00":
        raise OSError("not a Minecraft server")
    # skip the packet id and the string's length (a varint)
    i = 1
    while i < len(body) and body[i] & 0x80:
        i += 1
    try:
        data = json.loads(body[i + 1:].decode("utf-8", "replace"))
    except ValueError:
        raise OSError("not a Minecraft server") from None
    desc = data.get("description", "")
    motd = desc if isinstance(desc, str) else _text(desc)
    return {"motd": re.sub(r"§.", "", motd), "online": (data.get("players") or {}).get("online"),
            "max": (data.get("players") or {}).get("max"), "version": (data.get("version") or {}).get("name")}


def _text(component) -> str:
    """The plain text of a chat component (the motd can be one)."""
    if isinstance(component, str):
        return component
    if isinstance(component, list):
        return "".join(_text(c) for c in component)
    if isinstance(component, dict):
        return str(component.get("text", "")) + "".join(_text(c) for c in component.get("extra", []))
    return ""


# ------------------------------------------------------------------ the agent
def agent_running() -> bool | None:
    """Whether playit.gg's agent program runs on this computer (None if it can't be told)."""
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=10,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            return bool(re.search(r'^"playit[^"]*\.exe"', out, re.I | re.M))
        proc = "/proc"
        if os.path.isdir(proc):
            for pid in os.listdir(proc):
                if pid.isdigit():
                    try:
                        with open(f"{proc}/{pid}/comm") as f:
                            if f.read().strip().lower().startswith("playit"):
                                return True
                    except OSError:
                        continue
            return False
        if shutil.which("pgrep"):
            return subprocess.run(["pgrep", "-i", "playit"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        pass
    return None


# ----------------------------------------------------------------- the check
def check(address: str, motd: str, running: bool, pinger=ping) -> dict:
    """Is the tunnel working? {"status": ok|wrong|down|stopped|off, "words", "checked"}."""
    now = time.time()
    try:
        where = parse_address(address)
    except TunnelError as e:
        return {"status": "down", "words": str(e), "checked": now}
    if where is None:
        return {"status": "off", "words": "No tunnel set.", "checked": now}
    if not running:
        return {"status": "stopped", "words": "The server is stopped, so there's nothing to reach through the tunnel.", "checked": now}
    try:
        got = pinger(*where)
    except OSError as e:
        return {"status": "down", "checked": now, "detail": str(e),
                "words": "Friends can't reach the server through playit.gg right now. Check that the playit program is "
                         "running on this computer, and playit.gg's status page: an outage there is out of Craft Conductor's hands."}
    if motd and motd.strip() and motd.strip() not in got["motd"]:
        return {"status": "wrong", "checked": now, "answer": got,
                "words": f"The tunnel answers, but with another server (\"{got['motd'][:60]}\"): in playit.gg, point it at this server's port."}
    return {"status": "ok", "checked": now, "answer": got, "words": "Working: friends can join through playit.gg."}
