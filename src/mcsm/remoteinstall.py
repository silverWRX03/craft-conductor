"""Installing mcsm on a Linux computer without a screen, from the New server page.

mcsm opens a terminal window on this computer running OpenSSH (built into Windows 10/11,
macOS and Linux), which connects to the other computer and runs mcsm's installer there
(packaging/install.sh: downloads the newest release, checks its SHA256SUMS, sets it up as
a service, prints the control panel's address and a one-time password).

OpenSSH does all the talking: the password or key, and the "do you trust this computer?"
question the first time, happen in that window. mcsm never sees them. Only a host name or
address, a user name and a port go into the command, and each is checked strictly first.
"""

from __future__ import annotations

import ipaddress
import os
import re
import shlex
import shutil
import subprocess
import sys

INSTALLER = "https://raw.githubusercontent.com/silverWRX03/mc-server-management/main/packaging/install.sh"
PANEL_PORT = 8765
HOST = re.compile(r"(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?)*\.?")
USER = re.compile(r"[a-z_][a-z0-9_.-]{0,31}")
# Run on the Linux computer (the same as docs/headless.md, with wget if there's no curl).
REMOTE = f"(curl -fsSL {INSTALLER} || wget -qO- {INSTALLER}) | sh"
# A rented server (a VPS) is on the internet: its control panel stays on the server itself
# (127.0.0.1), and you reach it through SSH (an encrypted tunnel to this computer's LOCAL_PORT).
REMOTE_RENTED = f"(curl -fsSL {INSTALLER} || wget -qO- {INSTALLER}) | MCSM_PANEL_LOCAL=1 sh"
LOCAL_PORT = 8775  # (not 8765: this computer's own mcsm uses that)


class RemoteInstallError(Exception):
    pass


def check(host: str, user: str, port) -> tuple[str, str, int]:
    host, user = str(host).strip(), str(user).strip()
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise RemoteInstallError("the SSH port must be a number (usually 22)") from None
    try:
        host = str(ipaddress.ip_address(host.strip("[]")))
    except ValueError:
        if not HOST.fullmatch(host):
            raise RemoteInstallError("that doesn't look like a computer's name or address (e.g. 192.168.1.50)") from None
    if not USER.fullmatch(user):
        raise RemoteInstallError("that doesn't look like a Linux user name (lowercase, e.g. minecraft)")
    if user == "root":
        raise RemoteInstallError("use a normal user, not root (e.g. make one on that computer: sudo adduser minecraft)")
    if not 1 <= port <= 65535:
        raise RemoteInstallError("the SSH port must be between 1 and 65535")
    return host, user, port


def on_home_network(host: str) -> bool:
    """A computer at home (a private address, or a local name) rather than a rented server on
    the internet."""
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
        home = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "fc00::/7")  # (100.64: Tailscale)
        return ip.is_loopback or ip.is_link_local or any(ip in ipaddress.ip_network(n) for n in home if ip.version == ipaddress.ip_network(n).version)
    except ValueError:
        return "." not in host.rstrip(".") or host.lower().rstrip(".").endswith((".local", ".lan", ".home", ".internal"))


def _target(host: str, user: str) -> str:
    return f"{user}@{host}" if ":" not in host else f"{user}@[{host}]"


def ssh_args(host: str, user: str, port: int, rented: bool = False) -> list[str]:
    # -t: a terminal, so the installer's output shows up as it happens. accept-new: the first
    # time, OpenSSH remembers the computer's key (and refuses if it ever changes after that).
    return ["ssh", "-t", "-p", str(port), "-o", "StrictHostKeyChecking=accept-new", _target(host, user),
            REMOTE_RENTED if rented else REMOTE]


def tunnel_args(host: str, user: str, port: int) -> list[str]:
    """Reach a rented server's control panel: forward this computer's LOCAL_PORT to the panel
    there, over SSH, while the window stays open."""
    return ["ssh", "-N", "-p", str(port), "-o", "StrictHostKeyChecking=accept-new", "-o", "ExitOnForwardFailure=yes",
            "-L", f"{LOCAL_PORT}:127.0.0.1:{PANEL_PORT}", _target(host, user)]


def command_line(host: str, user: str, port: int, rented: bool = False) -> str:
    """The same thing to type yourself (shown on the page, e.g. when no terminal can be opened)."""
    *args, remote = ssh_args(host, user, port, rented)
    return " ".join(shlex.quote(a) for a in args) + f' "{remote}"'  # double quotes: works in PowerShell too


def tunnel_command(host: str, user: str, port: int) -> str:
    return " ".join(shlex.quote(a) for a in tunnel_args(host, user, port))


def panel_url(host: str, rented: bool = False) -> str:
    if rented:
        return f"http://localhost:{LOCAL_PORT}/"
    return f"http://{host if ':' not in host else f'[{host}]'}:{PANEL_PORT}/"


def _ssh_exe() -> str | None:
    found = shutil.which("ssh")
    if found:
        return found
    if os.name == "nt":  # Windows' own OpenSSH, even if it's not on PATH
        path = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "OpenSSH", "ssh.exe")
        return path if os.path.exists(path) else None
    return None


def launch(host: str, user: str, port: int, popen=subprocess.Popen, rented: bool = False, tunnel: bool = False) -> None:
    """Open a terminal window running the SSH install (or, with ``tunnel``, the SSH tunnel to a
    rented server's control panel). Raises if there's no ssh or terminal."""
    ssh = _ssh_exe()
    if ssh is None:
        raise RemoteInstallError("OpenSSH isn't installed on this computer (on Windows: Settings → Apps → "
                                 "Optional features → OpenSSH Client)")
    args = [ssh, *(tunnel_args(host, user, port) if tunnel else ssh_args(host, user, port, rented))[1:]]
    title = f"mcsm: {'control panel of' if tunnel else 'installing on'} {host}"
    if os.name == "nt":
        # A console of its own that stays open afterwards (cmd /k), so the address and password can be read.
        popen(["cmd", "/k", "title", title, "&", *args], creationflags=0x00000010)  # CREATE_NEW_CONSOLE
        return
    line = " ".join(shlex.quote(a) for a in args) + "; echo; echo 'You can close this window.'"
    if sys.platform == "darwin":
        script = f'tell application "Terminal" to do script "{_applescript(line)}"'
        popen(["osascript", "-e", script, "-e", 'tell application "Terminal" to activate'])
        return
    keep_open = f"{line}; read -r _"
    for term in (["x-terminal-emulator", "-e"], ["gnome-terminal", "--"], ["konsole", "-e"],
                 ["xfce4-terminal", "-x"], ["xterm", "-e"]):
        if shutil.which(term[0]):
            popen([*term, "sh", "-c", keep_open], start_new_session=True)
            return
    raise RemoteInstallError("couldn't open a terminal window; run the command below in one yourself")


def _applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')
