"""playit.gg tunnels: friends join through an address playit.gg gives you, without port
forwarding on your router.

playit.gg is an outside service, run by its own company: craft-conductor doesn't control it, and when it
has problems (or its agent program isn't running on this computer), friends can't connect
through it however healthy the server is. So craft-conductor checks the tunnel the way a friend's game
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
            # (playit.gg's agent: playitd.exe as a service, or playit*.exe run by hand; its tray icon,
            # playitd-tray.exe, can run without the agent, so it doesn't count)
            return any(not name.lower().endswith("-tray.exe")
                       for name in re.findall(r'^"(playit[^"]*\.exe)"', out, re.I | re.M))
        proc = "/proc"
        if os.path.isdir(proc):
            for pid in os.listdir(proc):
                if pid.isdigit():
                    try:
                        with open(f"{proc}/{pid}/comm") as f:
                            comm = f.read().strip().lower()
                            if comm.startswith("playit") and "tray" not in comm:
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


# ------------------------------------------------------- getting the agent
# playit.gg's program (its "agent") is made by playit.gg's company, Developed Methods LLC, and is
# published on GitHub. Craft Conductor downloads it only when the person presses the button,
# only from that release, and runs nothing it hasn't checked twice: the SHA-256 GitHub publishes
# for the file, and (on Windows) the file's code signature, which must be valid and
# Developed Methods LLC's. Then playit.gg's own installer runs: it sets the agent up as its own
# program (a Windows service with a tray icon) that keeps running without Craft Conductor.
RELEASE_API = "https://api.github.com/repos/playit-cloud/playit-agent/releases/latest"
RELEASE_DOWNLOADS = "https://github.com/playit-cloud/playit-agent/releases/download/"
SIGNER = "Developed Methods LLC"
MAX_INSTALLER = 64 << 20
# Linux: playit.gg's own package repository (its packages are signed with its key). Shown to copy:
# they need sudo, which Craft Conductor never asks for.
APT_STEPS = (
    "curl -SsL https://playit-cloud.github.io/ppa/key.gpg | gpg --dearmor | sudo tee /etc/apt/trusted.gpg.d/playit.gpg >/dev/null",
    'echo "deb [signed-by=/etc/apt/trusted.gpg.d/playit.gpg] https://playit-cloud.github.io/ppa/data ./" '
    "| sudo tee /etc/apt/sources.list.d/playit-cloud.list",
    "sudo apt update",
    "sudo apt install playit",
)


class AgentError(RuntimeError):
    pass


def platform() -> str:
    """"windows" (a checked download and playit.gg's installer), "linux" (playit.gg's own package
    repository), or "other" (macOS and the rest: playit.gg's download page)."""
    import sys
    return "windows" if os.name == "nt" else "linux" if sys.platform.startswith("linux") else "other"


def installer_asset(release: dict, machine: str | None = None) -> dict:
    """The Windows installer in a playit-agent release: {"version", "name", "url", "sha256", "size"}.
    Only a signed .msi from playit.gg's own GitHub release, with the SHA-256 GitHub lists for it."""
    import platform as pf
    machine = (machine or pf.machine() or "").lower()
    arch = "x86_64" if machine in ("amd64", "x86_64", "arm64", "aarch64") else "x86"  # (Windows on Arm runs x86_64)
    name = f"playit-windows-{arch}-signed.msi"
    version = str(release.get("tag_name") or "")
    if not re.fullmatch(r"v?\d+(\.\d+){1,3}", version):
        raise AgentError("playit.gg's release list didn't look right; try again later")
    for asset in release.get("assets") or []:
        if not isinstance(asset, dict) or asset.get("name") != name:
            continue
        url = str(asset.get("browser_download_url") or "")
        digest = str(asset.get("digest") or "")
        size = asset.get("size")
        if url != RELEASE_DOWNLOADS + version + "/" + name:
            raise AgentError("playit.gg's installer isn't where it should be, so it wasn't downloaded")
        m = re.fullmatch(r"sha256:([0-9a-f]{64})", digest)
        if not m:
            raise AgentError("GitHub gives no checksum for playit.gg's installer, so it can't be checked: "
                             "get it from playit.gg/download instead")
        if not isinstance(size, int) or not 0 < size <= MAX_INSTALLER:
            raise AgentError("playit.gg's installer has an unexpected size, so it wasn't downloaded")
        return {"version": version.lstrip("v"), "name": name, "url": url, "sha256": m.group(1), "size": size}
    raise AgentError(f"playit.gg's latest release has no {name}: get it from playit.gg/download")


SIGNATURE_SCRIPT = """$ErrorActionPreference = 'Stop'
$s = Get-AuthenticodeSignature -LiteralPath {path}
[pscustomobject]@{{ status = "$($s.Status)"; subject = "$($s.SignerCertificate.Subject)" }} | ConvertTo-Json -Compress
"""


def _subject_organization(subject: str) -> str:
    """The O= part of a certificate's subject (as PowerShell writes it: comma-separated, quoted when needed)."""
    for part in re.findall(r'(?:[^,"]|"[^"]*")+', subject):
        key, _, value = part.strip().partition("=")
        if key.strip().upper() == "O":
            return value.strip().strip('"')
    return ""


def check_signature(path, run=None, signer: str = SIGNER, whose: str = "playit.gg's company",
                    what: str = "the installer", done: str = "opened") -> None:
    """The file is signed, the signature is valid (Windows checks the certificate chain), and
    the signer is ``signer`` (playit.gg's company unless said). Raises AgentError otherwise."""
    import base64
    from .firewall import _ps_string, UTF8_OUTPUT
    script = UTF8_OUTPUT + SIGNATURE_SCRIPT.format(path=_ps_string(str(path)))  # (a signer or folder with accents, #150)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    # (Windows' own PowerShell by its full path: never one found in the current folder or on PATH)
    powershell = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    args = [powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]
    try:
        if run is None:
            from .desktop import NO_WINDOW
            out = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                                 **NO_WINDOW).stdout
        else:
            out = run(args)
        data = json.loads(out or "null")
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        raise AgentError(f"Windows couldn't check {what}'s signature ({e}), so it wasn't {done}") from None
    if not isinstance(data, dict) or data.get("status") != "Valid":
        raise AgentError(f"{what}'s signature isn't valid, so it wasn't {done} (it may have been changed)")
    if _subject_organization(str(data.get("subject") or "")) != signer:
        raise AgentError(f"{what} isn't signed by {signer} ({whose}), so it wasn't {done}")


def download_installer(http, folder, progress=None, check=check_signature):
    """Download playit.gg's Windows installer into ``folder`` and check it (SHA-256 while it
    downloads, then its signature). Returns (path, version). Nothing is kept that fails a check."""
    from pathlib import Path
    asset = installer_asset(http.get_json(RELEASE_API, headers={"Accept": "application/vnd.github+json"}, cache=False))
    folder = Path(folder)
    dest = folder / asset["name"]
    try:
        http.download(asset["url"], dest, sha256=asset["sha256"], max_bytes=asset["size"], progress=progress)
        check(dest)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return dest, asset["version"]


def open_installer(path, check=check_signature, popen=subprocess.Popen) -> None:
    """Check the downloaded installer again, then open it with Windows Installer (msiexec, by its
    full path, with an argument list): playit.gg's installer asks Windows for permission itself."""
    check(path)
    msiexec = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "msiexec.exe")
    from .desktop import child_env
    popen([msiexec, "/i", str(path)], env=child_env(), close_fds=True)
