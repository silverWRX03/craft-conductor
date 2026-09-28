"""Tailscale, for reaching the control panel from a phone over trusted HTTPS.

Phones only install web apps and deliver their notifications for pages with a real certificate.
``tailscale serve`` gives this computer one, at ``https://<computer>.<tailnet>.ts.net``, reachable
only from your own devices signed in to the same Tailscale account (it isn't on the internet). It
passes requests on to the control panel on this computer, which treats them as coming from another
device (so they need the strong password or a paired phone, as always).
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


def _run(args: list[str], timeout: float = 8) -> subprocess.CompletedProcess | None:
    from .desktop import NO_WINDOW
    path = exe()
    if not path:
        return None
    try:
        return subprocess.run([path, *args], capture_output=True, text=True, timeout=timeout, **NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None


def status(port: int) -> dict:
    """{"installed", "running", "name" (this computer's ts.net name), "serving" (the control panel)}."""
    out = {"installed": exe() is not None, "running": False, "name": "", "serving": False}
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
    return out


def serve(port: int) -> dict:
    """Serve the control panel over HTTPS on the tailnet: {"ok", "message", "enable_url"}."""
    r = _run(["serve", "--bg", "--https=443", f"http://127.0.0.1:{port}"], timeout=25)
    if r is None:
        return {"ok": False, "message": "Tailscale isn't installed on this computer", "enable_url": None}
    text = (r.stdout + r.stderr).strip()
    link = URL.search(text)
    if r.returncode != 0 or link:
        # Most often: HTTPS isn't switched on for this Tailscale account yet (a link to do it).
        return {"ok": False, "message": text.splitlines()[-1][:300] if text else "tailscale serve failed",
                "enable_url": link.group(0) if link else None}
    return {"ok": True, "message": "", "enable_url": None}


def unserve() -> bool:
    r = _run(["serve", "--https=443", "off"], timeout=15)
    return r is not None and r.returncode == 0
