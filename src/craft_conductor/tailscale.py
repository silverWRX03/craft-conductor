"""Tailscale, for reaching the control panel from a phone over trusted HTTPS.

Phones only install web apps and deliver their notifications for pages with a real certificate.
``tailscale serve`` gives this computer one, at ``https://<computer>.<tailnet>.ts.net``, reachable
only from your own devices signed in to the same Tailscale account (it isn't on the internet). It
passes requests on to the control panel on this computer, through a door of the control panel's
that only Tailscale uses (tunnels.py), so they're treated as coming from another device (they need
the strong password or a paired phone, as always). Funnel puts that address on the internet for
anyone: only when the owner accepted that risk ([web] accept_risks "tailscale-funnel").
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

URL = re.compile(r"https://login\.tailscale\.com/\S+")


def exe() -> str | None:
    return shutil.which("tailscale") or next((p for p in (r"C:\Program Files\Tailscale\tailscale.exe",
                                                          "/Applications/Tailscale.app/Contents/MacOS/Tailscale")
                                               if os.path.exists(p)), None)


def _argv(args: list[str]) -> list[str] | None:
    path = exe()
    return [path, *args] if path else None


def _run(args: list[str], timeout: float = 8) -> subprocess.CompletedProcess | None:
    from .desktop import NO_WINDOW
    argv = _argv(args)
    if not argv:
        return None
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, **NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None


def status(port: int) -> dict:
    """{"installed", "running", "name" (this computer's ts.net name), "serving" (the control panel,
    on ``port``), "funnel" (on the internet too)}."""
    out = {"installed": exe() is not None, "running": False, "name": "", "serving": False, "funnel": False}
    r = _run(["status", "--json"])
    if r is None or r.returncode != 0:
        return out
    try:
        data = json.loads(r.stdout)
    except ValueError:
        return out
    out["running"] = data.get("BackendState") == "Running"
    name = str((data.get("Self") or {}).get("DNSName") or "").rstrip(".").lower()
    out["name"] = name if re.fullmatch(r"[a-z0-9.-]+\.ts\.net", name) else ""
    s = _run(["serve", "status", "--json"])
    if s is not None and s.returncode == 0 and s.stdout.strip():
        try:
            config = json.loads(s.stdout)
        except ValueError:
            config = {}
        proxies = [h.get("Proxy", "") for web in (config.get("Web") or {}).values()
                   for h in ((web or {}).get("Handlers") or {}).values()]
        out["serving"] = any(p.rstrip("/").endswith(f"127.0.0.1:{port}") or p.rstrip("/").endswith(f"localhost:{port}")
                             for p in proxies)
        out["funnel"] = out["serving"] and any((config.get("AllowFunnel") or {}).values())
    return out


def serve(port: int, funnel: bool = False, timeout: float = 25) -> dict:
    """Serve the control panel over HTTPS on the tailnet: {"ok", "message", "enable_url"}.

    When Serve or HTTPS isn't switched on for the account yet, ``tailscale serve`` prints a link to
    do it and then waits (for as long as it takes): the link is passed on as soon as it's printed,
    rather than the wait ending in a timeout that looked like Tailscale wasn't installed."""
    import threading
    from .desktop import NO_WINDOW
    argv = _argv(["funnel" if funnel else "serve", "--bg", "--https=443", f"http://127.0.0.1:{port}"])
    if not argv:
        return {"ok": False, "message": "Tailscale isn't installed on this computer", "enable_url": None}
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, **NO_WINDOW)
    except OSError as e:
        return {"ok": False, "message": f"Tailscale couldn't be run: {e}", "enable_url": None}
    lines: list[str] = []
    found = threading.Event()

    def read() -> None:
        for line in proc.stdout:
            lines.append(line.rstrip())
            if URL.search(line):
                found.set()
        found.set()  # (the output ended)
    threading.Thread(target=read, daemon=True, name="tailscale-serve").start()
    found.wait(timeout)
    text = "\n".join(lines).strip()
    link = URL.search(text)
    if not link:
        try:
            proc.wait(5)  # (the output ends a moment before the program does)
        except subprocess.TimeoutExpired:
            pass
    if link or proc.poll() is None:  # waiting for Serve/HTTPS to be switched on (or taking too long)
        proc.kill()
        message = next((x.strip() for x in lines if x.strip() and not URL.search(x)), "") or "Tailscale is still busy"
        return {"ok": False, "message": message[:300], "enable_url": link.group(0) if link else None}
    if proc.wait() != 0:
        return {"ok": False, "message": text.splitlines()[-1][:300] if text else "tailscale serve failed", "enable_url": None}
    return {"ok": True, "message": "", "enable_url": None}


def unserve(funnel: bool = False) -> bool:
    if funnel:
        _run(["funnel", "--https=443", "off"], timeout=15)
    r = _run(["serve", "--https=443", "off"], timeout=15)
    return r is not None and r.returncode == 0
