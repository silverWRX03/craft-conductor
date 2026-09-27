"""Check my setup: the things that most often stop a server from running or friends from
joining, each with what to do about it, in plain words.

Every check is local and quick, except reaching the server from the internet, which asks an
outside service (ifconfig.co) to try the port, and only when the person asks for it. The
report for a bug report (``report_zip``) leaves out secrets: invite tokens, keys, passwords
and webhooks are replaced before anything is written.
"""

from __future__ import annotations

import io
import json
import os
import platform
import re
import shutil
import socket
import time
import zipfile
from dataclasses import asdict, dataclass

from . import __version__
from .properties import read_properties

OK, WARN, BAD, INFO = "ok", "warn", "bad", "info"
PORT_CHECK = "https://ifconfig.co/port/{port}"


@dataclass
class Check:
    id: str
    title: str
    status: str          # ok | warn | bad | info
    detail: str
    fix: str = ""        # what to do, when there's something to do


def _gb(n: float) -> str:
    return f"{n:.0f} GB" if n >= 10 else f"{n:.1f} GB"


def server_memory_gb(memory: str) -> float:
    from .setup import suggested_memory_gb
    if memory == "auto":
        return float(suggested_memory_gb())
    return int(memory[:-1]) / (1024 if memory.upper().endswith("M") else 1)


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Something is listening on this TCP port on this computer."""
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def run(m, state: str, *, total_gb: float | None = None, share: dict | None = None,
        self_update: dict | None = None) -> list[Check]:
    """The checks for one server. ``state`` is the daemon's (running, stopped, ...)."""
    from .setup import total_ram_gb
    checks: list[Check] = []
    cfg, lk = m.config, m.lock
    props = read_properties(m.server_dir / "server.properties")

    # Installed, and the EULA
    if not lk.installed:
        checks.append(Check("installed", "Server installed", BAD, "The server isn't installed yet.",
                            "Finish its setup (Servers → Finish setup)."))
    else:
        checks.append(Check("installed", "Server installed", OK, f"Minecraft {lk.minecraft} with {lk.loader or cfg.server.loader}."))
    eula = m.server_dir / "eula.txt"
    if lk.installed and not (eula.exists() and "eula=true" in eula.read_text(errors="replace").lower()):
        checks.append(Check("eula", "Minecraft EULA", BAD, "The Minecraft EULA hasn't been accepted, so the server won't start.",
                            "Accept it in the server's setup, or set eula=true in eula.txt in the server folder."))

    # Java
    if lk.installed:
        from .java import JavaError
        try:
            java = m.java.select(lk.java_major or 8, install=False)
            checks.append(Check("java", "Java", OK, f"Java {lk.java_major or 8} is ready ({java})."))
        except (JavaError, OSError) as e:
            checks.append(Check("java", "Java", WARN, f"Java {lk.java_major or 8} isn't on this computer yet ({e}).",
                                "mcsm downloads it when the server starts; if that fails, see the Java page."))

    # Memory
    total = total_gb if total_gb is not None else total_ram_gb()
    want = server_memory_gb(cfg.server.memory)
    if total:
        spare = total - want
        if spare < 1.5:
            checks.append(Check("memory", "Memory", BAD, f"The server is set to use {_gb(want)}, and this computer has {_gb(total)}.",
                                "Give the server less memory (Settings → Memory), leaving at least 2 GB for the rest of the computer."))
        elif spare < 3:
            checks.append(Check("memory", "Memory", WARN, f"The server uses {_gb(want)} of this computer's {_gb(total)}: little is left for anything else.",
                                "Fine on a computer that only runs the server; playing on it too will be slow."))
        else:
            checks.append(Check("memory", "Memory", OK, f"The server uses {_gb(want)} of this computer's {_gb(total)}."))

    # Disk space
    try:
        free = shutil.disk_usage(m.server_dir if m.server_dir.exists() else cfg.root).free / 1024 ** 3
        if free < 2:
            checks.append(Check("disk", "Disk space", BAD, f"Only {_gb(free)} free where the server is.",
                                "Free some space: worlds, backups and updates need room (Backups keeps the newest; lower how many it keeps in Settings)."))
        elif free < 10:
            checks.append(Check("disk", "Disk space", WARN, f"{_gb(free)} free where the server is.", "Backups and updates need room; keep an eye on it."))
        else:
            checks.append(Check("disk", "Disk space", OK, f"{_gb(free)} free."))
    except OSError:
        pass

    # The port
    port = int(props.get("server-port", "25565") or 25565)
    listening = port_in_use(port)
    if state == "running":
        checks.append(Check("port", f"Port {port}", OK if listening else BAD,
                            "The server is taking connections on this computer." if listening else "The server is running but not taking connections yet.",
                            "" if listening else "Wait for it to finish starting; if it stays like this, look at the Console."))
    elif listening:
        checks.append(Check("port", f"Port {port}", BAD, f"Another program is using port {port}, so this server can't start.",
                            "Stop the other program (or the other server), or pick another port on the Settings page."))
    else:
        checks.append(Check("port", f"Port {port}", OK, f"Port {port} is free for the server."))

    # Online mode and the whitelist
    if props.get("online-mode", "true").lower() == "false":
        checks.append(Check("online-mode", "Accounts", WARN, "online-mode is off: anyone can join with any name.",
                            "Turn it on (Settings → Advanced server settings) unless you know you need it off."))

    # Friends' downloads
    if cfg.client.enabled and share is not None:
        if not share.get("running"):
            checks.append(Check("share", "Friends' downloads", BAD, "The friends' download port isn't running" +
                                (f": {share['error']}" if share.get("error") else "."),
                                "mcsm settings → Sharing with friends: pick another port if it's busy, then reopen mcsm."))
        elif not share.get("address"):
            checks.append(Check("share", "Friends' downloads", INFO, f"Running on port {share.get('port')}. No public address is set.",
                                "Friends outside your home need one: press Use my public IP on the Friends page."))
        else:
            checks.append(Check("share", "Friends' downloads", OK, f"Running on port {share.get('port')}, for {share['address']}."))

    # Windows Firewall (it can't be checked without administrator rights: say what to look for)
    if os.name == "nt":
        checks.append(Check("firewall", "Windows Firewall", INFO, "Windows asks the first time the server starts whether Java may accept connections.",
                            "Choose Allow (private networks). If you pressed Cancel: Windows Security → Firewall → Allow an app through firewall → tick Java."))

    # mcsm itself
    if self_update and self_update.get("available"):
        checks.append(Check("mcsm", "mcsm", INFO, f"mcsm {self_update.get('version')} is available (you have {__version__}).",
                            "Update from the message at the top, or mcsm settings → Check for mcsm updates."))
    return checks


def internet_check(http, port: int, running: bool) -> Check:
    """Ask ifconfig.co to connect to this network's public address on the port."""
    title = f"Reachable from the internet (port {port})"
    if not running:
        return Check("internet", title, INFO, "Start the server first: the test connects to it.")
    try:
        r = http.get_json(PORT_CHECK.format(port=port), headers={"Accept": "application/json"})
    except Exception as e:  # the outside service is down or unreachable
        return Check("internet", title, INFO, f"Couldn't run the test ({e}).", "Try again later, or ask a friend outside your home to connect.")
    ip = str(r.get("ip", "your public address"))
    if r.get("reachable"):
        return Check("internet", title, OK, f"Friends outside your home can reach {ip}:{port}.")
    return Check("internet", title, BAD, f"{ip}:{port} can't be reached from the internet.",
                 f"Forward TCP port {port} on your router to this computer (Help → Router setup), and allow Java through the firewall. "
                 "Some internet providers don't allow it at all (CGNAT); Tailscale or a VPN works then.")


# --------------------------------------------------------------- the report
_SECRET_KEY = re.compile(r"(token|secret|password|passwd|webhook|api[_-]?key|key)\b", re.I)
_SECRET_TEXT = [
    (re.compile(r"https://(discord(app)?\.com)/api/webhooks/\S+"), r"https://\1/api/webhooks/<removed>"),
    (re.compile(r"/join/[A-Za-z0-9_-]{8,}"), "/join/<removed>"),
    (re.compile(r"\bmcsm-[A-Za-z0-9_-]{40,}"), "mcsm-<invite removed>"),
    (re.compile(r"\$2[aby]\$[^\s\"']+|\$argon2[^\s\"']+|pbkdf2[^\s\"']+", re.I), "<removed>"),
    # players' and friends' addresses (logs show who connected from where); this computer's stay
    (re.compile(r"\b(?!127\.0\.0\.1\b)(?:\d{1,3}\.){3}\d{1,3}\b"), "<ip>"),
    (re.compile(r"\[[0-9a-fA-F:]{6,}(?:%\w+)?\]"), "[<ip>]"),
]


def redact(text: str) -> str:
    """Take secrets out of a config file or log: values of keys that name one, and things that
    look like one (webhooks, invite secrets, password hashes)."""
    out = []
    for line in text.splitlines():
        m = re.match(r"^(\s*[\"']?([\w.-]+)[\"']?\s*[=:]\s*)(.+)$", line)
        if m and _SECRET_KEY.search(m.group(2)) and m.group(3).strip() not in ('""', "''", "[]", "{}"):
            line = m.group(1) + '"<removed>"'
        out.append(line)
    text = "\n".join(out)
    for pattern, repl in _SECRET_TEXT:
        text = pattern.sub(repl, text)
    return text


def _tail(path, limit: int = 400_000) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - limit))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def report_zip(m, checks: list[Check], log_file) -> bytes:
    """A zip to attach to a bug report: the checks, versions, the server's config (secrets
    removed) and the ends of mcsm's and the server's logs (secrets removed)."""
    from .config import CONFIG_NAME
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", "mcsm diagnostic report. Secrets (invite tokens, keys, passwords, webhooks) were removed.\n"
                   "Look through it before sharing it.\n")
        z.writestr("checks.json", json.dumps([asdict(c) for c in checks], indent=2))
        z.writestr("system.json", json.dumps({
            "mcsm": __version__, "os": platform.platform(), "python": platform.python_version(),
            "machine": platform.machine(), "cpus": os.cpu_count(), "time": time.strftime("%Y-%m-%d %H:%M:%S %z"),
            "minecraft": m.lock.minecraft, "loader": m.lock.loader, "loader_version": m.lock.loader_version,
            "java_major": m.lock.java_major, "mods": [f"{x.name} {x.version_number}" for x in m.lock.mods]}, indent=2))
        for name, path in ((CONFIG_NAME, m.config.root / CONFIG_NAME), ("server.properties", m.server_dir / "server.properties")):
            if path.exists():
                z.writestr(name, redact(path.read_text(errors="replace")))
        if log_file:
            z.writestr("mcsm.log", redact(_tail(log_file)))
        z.writestr("latest.log", redact(_tail(m.server_dir / "logs" / "latest.log")))
    return buf.getvalue()
