"""How friends outside your home reach a server, and what that means for its whitelist.

Each server has a way (``[reach] way`` in its craft-conductor.toml), chosen in New server, on its
Friends page or in Craft Conductor settings → Sharing with friends:

* ``playit``: a playit.gg tunnel (pre-selected; nothing opened on the router, free for Minecraft);
* ``forward``: a port opened on the router. Craft Conductor picks a free port that isn't
  Minecraft's usual 25565 (bots try that one first), and Router (UPnP) and the Windows
  Firewall rule use it;
* ``home``: only friends on this computer's network.

A server that can be reached from the internet gets its whitelist on by default. Turning it off
is allowed, but the person is asked every time (``WHITELIST_OFF_WARNING``). A server made from
now on that becomes reachable later (Router switched on, a playit.gg address added...) has its
whitelist turned on by itself, with a notice, unless its owner turned it off through that
question. Servers made before this are left as they are (``guarded`` is false for them).
"""

from __future__ import annotations

import json
import logging
import random
import re
import socket
from pathlib import Path

log = logging.getLogger(__name__)

WAYS = ("playit", "forward", "home")
USUAL_PORT = 25565
OPEN_RANGE = (30000, 39999)  # where a port opened on the router is picked from (both ends included)
STATE = "reach.json"         # in the server's .craft-conductor folder

# Said next to the port-forwarding choice, and before Router (UPnP) is switched on.
ROUTER_RISKS = ("Opening a port on your router makes this server reachable by anyone on the internet, not just your friends. "
                "Programs scan the whole internet for Minecraft servers all day, and a server they find can be joined and griefed. "
                "Your home's internet address becomes public: anyone who joins can see it. "
                "Keep the whitelist on, and close the port when you don't need it.")
# Said next to the playit.gg choice (playit.gg's terms and plans checked 2026-10-16).
PLAYIT_DOWNSIDES = ("playit.gg is a separate company's service in the middle: everything players send goes through it, "
                    "you need a playit.gg account (13 or older), and when it has problems friends can't join through it. "
                    "It can add some lag: free tunnels aren't always routed through the nearest place. "
                    "Minecraft Java and Bedrock tunnels are free; playit.gg doesn't publish the free plan's exact limits, "
                    "and its plans can change. Players' own addresses don't reach the server, so IP bans don't work through it.")
WHITELIST_OFF_WARNING = ("This server can be reached from the internet. With the whitelist off, anyone who finds it can join: "
                         "bots look for Minecraft servers all day, and strangers can grief your world.")


# ------------------------------------------------------------------ the state
def _state_path(state_dir: Path) -> Path:
    return state_dir / STATE


def read_state(state_dir: Path) -> dict:
    """{"guarded", "opted_out", "port_test": {"port", "ok", "at"}} (missing keys: false/none)."""
    try:
        data = json.loads(_state_path(state_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_state(state_dir: Path, **changes) -> dict:
    data = {**read_state(state_dir), **changes}
    state_dir.mkdir(parents=True, exist_ok=True)
    path = _state_path(state_dir)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(path)
    return data


def why_reachable(way: str, tunnel_address: str, upnp_on: bool, public_address: str, port_test: dict | None,
                  port: int) -> list[str]:
    """Why this server can be reached from the internet (empty: it can't, as far as Craft Conductor knows)."""
    out = []
    if way in ("playit", "forward"):
        out.append("playit.gg is chosen for friends outside" if way == "playit" else "port forwarding is chosen for friends outside")
    if tunnel_address:
        out.append("it has a playit.gg address")
    if upnp_on:
        out.append("Router (UPnP) opens its port")
    if public_address:
        out.append("a public address is set in Sharing with friends")
    if port_test and port_test.get("ok") and int(port_test.get("port") or 0) == port:
        out.append("Check my setup reached it from the internet")
    return out


# ------------------------------------------------------------------ ports
def udp_free(port: int) -> bool:
    """Whether nothing on this computer has a UDP port (Bedrock players come in on UDP)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def pick_port(taken: set[int], free, rng: random.Random | None = None, tries: int = 400) -> int:
    """A port in OPEN_RANGE: not 25565, not ``taken`` (other servers', Craft Conductor's own), and
    ``free(port)`` on this computer. Random, so it isn't one a scanner would try next to 25565."""
    rng = rng or random.SystemRandom()
    lo, hi = OPEN_RANGE
    for _ in range(tries):
        port = rng.randint(lo, hi)
        if port != USUAL_PORT and port not in taken and free(port):
            return port
    for port in range(lo, hi + 1):  # (nearly everything taken: look at each one)
        if port not in taken and free(port):
            return port
    raise RuntimeError(f"no free port between {lo} and {hi}: close some programs and try again")


def in_open_range(port: int) -> bool:
    return OPEN_RANGE[0] <= port <= OPEN_RANGE[1]


# ------------------------------------------------------------- Geyser's port
GEYSER_CONFIGS = ("config/Geyser-Fabric/config.yml", "config/Geyser-NeoForge/config.yml", "plugins/Geyser-Spigot/config.yml")
_PORT_LINE = re.compile(r"[ \t]+port:[ \t]*(\d{1,5})")


def _bedrock_port(text: str) -> tuple[int, int, int] | None:
    """Where the port is in the ``bedrock:`` section of Geyser's config.yml: (the line, and where the
    number starts and ends in it). Read line by line (a pattern over the whole file could take very
    long on an odd file); the section ends at the next line that isn't indented, blank or a comment."""
    inside = False
    for i, line in enumerate(text.splitlines()):
        if not inside:
            inside = line.rstrip(" \t") == "bedrock:"
            continue
        if line.strip() and not line.strip().startswith("#") and line[:1] not in (" ", "\t"):
            return None  # (the next section)
        m = _PORT_LINE.match(line)
        if m:
            return i, m.start(1), m.end(1)
    return None


def geyser_config(server_dir: Path) -> Path | None:
    for rel in GEYSER_CONFIGS:
        path = server_dir / rel
        if path.is_file():
            return path
    return None


def geyser_port(server_dir: Path) -> int:
    """The UDP port Bedrock players use (Geyser's config.yml; 19132 until Geyser has written it)."""
    path = geyser_config(server_dir)
    if path is not None:
        text = path.read_text(encoding="utf-8", errors="replace")
        found = _bedrock_port(text)
        if found:
            i, start, end = found
            port = int(text.splitlines()[i][start:end])
            if 1 <= port <= 65535:
                return port
    return 19132


# Geyser 2.12 and later default to Bedrock's new connection method (NetherNet: "transport: nethernet"),
# which doesn't answer the classic one (RakNet) that a server added by address is reached with. With
# "both", Geyser takes both: TCP on its port (NetherNet's signaling), UDP on it (RakNet), and UDP on
# "webrtc-port" (NetherNet's game traffic; 0 means its port, which RakNet then has) (#211).
_KEY_LINE = re.compile(r"([ \t]+)([A-Za-z-]+):[ \t]*([^#\r\n]*?)[ \t]*(?:#.*)?$")


def _bedrock_keys(text: str) -> dict[str, tuple[int, int, int]]:
    """The ``bedrock:`` section's own settings (not those of a section inside it, like signaling's):
    key -> (the line, and where its value starts and ends in it)."""
    out: dict[str, tuple[int, int, int]] = {}
    inside, indent = False, None
    for i, line in enumerate(text.splitlines()):
        if not inside:
            inside = line.rstrip(" \t") == "bedrock:"
            continue
        if not line.strip() or line.strip().startswith("#"):
            continue
        if line[:1] not in (" ", "\t"):
            break  # (the next section)
        m = _KEY_LINE.match(line)
        if not m:
            continue
        if indent is None:
            indent = m.group(1)
        if m.group(1) == indent:
            out.setdefault(m.group(2), (i, m.start(3), m.end(3)))
    return out


def _value(text: str, key: str) -> str | None:
    found = _bedrock_keys(text).get(key)
    if found is None:
        return None
    i, start, end = found
    return text.splitlines()[i][start:end].strip("\"'")


def geyser_transport(server_dir: Path) -> str:
    """How Bedrock players reach Geyser: raknet (Geyser before 2.12, which has no such setting),
    nethernet or both."""
    path = geyser_config(server_dir)
    if path is None:
        return "raknet"
    return (_value(path.read_text(encoding="utf-8", errors="replace"), "transport") or "raknet").lower()


def geyser_webrtc_port(server_dir: Path) -> int | None:
    """The UDP port of Bedrock's new connection method when it's apart from Geyser's port (with
    "both"), or None."""
    path = geyser_config(server_dir)
    if path is None:
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    if (_value(text, "transport") or "").lower() != "both":
        return None
    try:
        port = int(_value(text, "webrtc-port") or 0)
    except ValueError:
        return None
    return port if 1 <= port <= 65535 else None


def geyser_ports(server_dir: Path) -> list[tuple[int, str]]:
    """(port, protocol) Bedrock players come in on, through Geyser (none without its config)."""
    if geyser_config(server_dir) is None:
        return []
    port, transport = geyser_port(server_dir), geyser_transport(server_dir)
    out = [(port, "UDP")]
    if transport in ("nethernet", "both"):
        out.append((port, "TCP"))  # (NetherNet's signaling)
    webrtc = geyser_webrtc_port(server_dir)
    if webrtc is not None and webrtc != port:
        out.append((webrtc, "UDP"))
    return out


def set_geyser_both(server_dir: Path, webrtc_port: int, replace: bool = False) -> bool:
    """Let current and older Bedrock players join by address: Geyser's ``transport: nethernet`` (its
    default from 2.12) becomes ``both``, with NetherNet's UDP traffic on ``webrtc_port``. A setup
    already on both keeps its webrtc-port unless it's 0 (or ``replace``); raknet (or an older Geyser)
    is left alone.
    True when the file was changed."""
    if not 1 <= int(webrtc_port) <= 65535:
        raise ValueError("that isn't a port")
    path = geyser_config(server_dir)
    if path is None:
        return False
    with path.open(encoding="utf-8", errors="replace", newline="") as f:  # (its own line endings, kept)
        text = f.read()
    keys = _bedrock_keys(text)
    transport = (_value(text, "transport") or "").lower()
    if transport not in ("nethernet", "both") or "transport" not in keys:
        return False
    lines = text.splitlines(keepends=True)
    i, start, end = keys["transport"]
    if transport == "nethernet":
        lines[i] = lines[i][:start] + "both" + lines[i][end:]
    if "webrtc-port" in keys:
        j, start, end = keys["webrtc-port"]
        try:
            current = int(lines[j][start:end].strip("\"'") or 0)
        except ValueError:
            current = 0
        if transport == "nethernet" or replace or not 1 <= current <= 65535:
            lines[j] = lines[j][:start] + str(int(webrtc_port)) + lines[j][end:]
    else:  # (after the transport line, indented the same)
        line = lines[i]
        indent = line[:len(line) - len(line.lstrip(" \t"))]
        ending = "\r\n" if line.endswith("\r\n") else "\n"
        if not line.endswith(("\n", "\r")):
            lines[i] = line + ending
        lines.insert(i + 1, f"{indent}webrtc-port: {int(webrtc_port)}{ending}")
    new = "".join(lines)
    if new == text:
        return False
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(new, encoding="utf-8", newline="")
    tmp.replace(path)
    log.info("Bedrock players can join by address with both connection methods (UDP port %s for the new one; %s)",
             webrtc_port, path.name)
    return True


def set_geyser_port(server_dir: Path, port: int) -> bool:
    """Write the Bedrock port into Geyser's config.yml (only its ``bedrock: port:``). False when
    Geyser hasn't written its config yet (it does on the server's first start)."""
    if not 1 <= int(port) <= 65535:
        raise ValueError("that isn't a port")
    path = geyser_config(server_dir)
    if path is None:
        return False
    with path.open(encoding="utf-8", errors="replace", newline="") as f:  # (its own line endings, kept)
        text = f.read()
    found = _bedrock_port(text)
    if found is None:
        return False
    i, start, end = found
    lines = text.splitlines(keepends=True)
    lines[i] = lines[i][:start] + str(int(port)) + lines[i][end:]
    new = "".join(lines)
    if new != text:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(new, encoding="utf-8", newline="")
        tmp.replace(path)
        log.info("Bedrock players now use UDP port %s (%s)", port, path.name)
    return True

