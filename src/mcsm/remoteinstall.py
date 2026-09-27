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


def ssh_args(host: str, user: str, port: int) -> list[str]:
    target = f"{user}@{host}" if ":" not in host else f"{user}@[{host}]"
    # -t: a terminal, so the installer's output shows up as it happens. accept-new: the first
    # time, OpenSSH remembers the computer's key (and refuses if it ever changes after that).
    return ["ssh", "-t", "-p", str(port), "-o", "StrictHostKeyChecking=accept-new", target, REMOTE]


def command_line(host: str, user: str, port: int) -> str:
    """The same thing to type yourself (shown on the page, e.g. when no terminal can be opened)."""
    *args, remote = ssh_args(host, user, port)
    return " ".join(shlex.quote(a) for a in args) + f' "{remote}"'  # double quotes: works in PowerShell too


def panel_url(host: str) -> str:
    return f"http://{host if ':' not in host else f'[{host}]'}:{PANEL_PORT}/"


def _ssh_exe() -> str | None:
    found = shutil.which("ssh")
    if found:
        return found
    if os.name == "nt":  # Windows' own OpenSSH, even if it's not on PATH
        path = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "OpenSSH", "ssh.exe")
        return path if os.path.exists(path) else None
    return None


def launch(host: str, user: str, port: int, popen=subprocess.Popen) -> None:
    """Open a terminal window running the SSH install. Raises if there's no ssh or terminal."""
    ssh = _ssh_exe()
    if ssh is None:
        raise RemoteInstallError("OpenSSH isn't installed on this computer (on Windows: Settings → Apps → "
                                 "Optional features → OpenSSH Client)")
    args = [ssh, *ssh_args(host, user, port)[1:]]
    title = f"mcsm: installing on {host}"
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
