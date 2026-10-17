"""Cloudflare's free quick tunnel: the control panel on the internet for a few hours.

``cloudflared`` is Cloudflare's own program. Craft Conductor downloads it only when the owner
presses the button: the file for this computer from Cloudflare's GitHub release, checked against
the SHA-256 GitHub lists for it and the one Cloudflare publishes in the release notes, and on
Windows its signature (Cloudflare, Inc.). It is checked again each time before it runs.

While the tunnel is open, cloudflared runs as its own program: Craft Conductor starts it with an
argument list (no shell), without Craft Conductor's secrets or cloudflared's own settings from the
environment, pointed at a door of the control panel's that only it uses (see tunnels.py), and stops
it after HOURS hours, when the owner presses Stop, or when Craft Conductor closes. Cloudflare gives
the tunnel a random ``https://….trycloudflare.com`` address, new each time; no account is needed.
Cloudflare sees what passes through (it decrypts the HTTPS in the middle) and says quick tunnels
are for testing and development, with no uptime promise.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform as pf
import re
import subprocess
import threading
import time
from pathlib import Path

from .tunnel import AgentError, check_signature

log = logging.getLogger(__name__)

RELEASE_API = "https://api.github.com/repos/cloudflare/cloudflared/releases/latest"
RELEASE_DOWNLOADS = "https://github.com/cloudflare/cloudflared/releases/download/"
SIGNER = "Cloudflare, Inc."
MAX_SIZE = 128 << 20
HOURS = 4
URL = re.compile(r"https://[a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com")
TERMS = "https://www.cloudflare.com/website-terms/"
ABOUT = "https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/"
DOWNSIDES = ("Anyone on the internet who has the address can reach the sign-in page, so a strong password is needed",
             "Cloudflare, another company, sits in the middle and can see what passes through, your password too",
             "The address is random and changes every time the tunnel opens: fingerprint sign-in and the installed phone "
             "app made at one address don't work at the next",
             "Cloudflare says quick tunnels are for testing, with no promise they stay up, under its terms of use")
STATE = "cloudflared.json"   # in the tools folder: what was downloaded (version, SHA-256)


def asset_name(system: str | None = None, machine: str | None = None) -> str | None:
    """cloudflared's file for this computer in Cloudflare's release; None on a Mac (Homebrew instead)."""
    system = (system or pf.system()).lower()
    machine = (machine or pf.machine() or "").lower()
    if system == "windows":
        return "cloudflared-windows-386.exe" if machine in ("x86", "i386", "i686") else "cloudflared-windows-amd64.exe"
    if system == "linux":
        arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64",
                "armv7l": "arm", "armv6l": "arm", "i386": "386", "i686": "386"}.get(machine)
        return f"cloudflared-linux-{arch}" if arch else None
    return None


def release_asset(release: dict, name: str) -> dict:
    """{"version", "name", "url", "sha256", "size"} for ``name``: only from Cloudflare's own GitHub
    release, with GitHub's SHA-256 for it matching the one in the release notes."""
    version = str(release.get("tag_name") or "")
    if not re.fullmatch(r"\d{4}\.\d{1,2}\.\d{1,3}", version):
        raise AgentError("Cloudflare's release list didn't look right; try again later")
    published = dict(re.findall(r"(?m)^\s*([A-Za-z0-9._-]+):\s*([0-9a-f]{64})\s*$", str(release.get("body") or "")))
    for asset in release.get("assets") or []:
        if not isinstance(asset, dict) or asset.get("name") != name:
            continue
        url = str(asset.get("browser_download_url") or "")
        if url != RELEASE_DOWNLOADS + version + "/" + name:
            raise AgentError("cloudflared isn't where it should be, so it wasn't downloaded")
        m = re.fullmatch(r"sha256:([0-9a-f]{64})", str(asset.get("digest") or ""))
        if not m:
            raise AgentError("GitHub gives no checksum for cloudflared, so it can't be checked")
        if published.get(name) != m.group(1):
            raise AgentError("cloudflared's checksum in Cloudflare's release notes doesn't match GitHub's, so it wasn't downloaded")
        size = asset.get("size")
        if not isinstance(size, int) or not 0 < size <= MAX_SIZE:
            raise AgentError("cloudflared has an unexpected size, so it wasn't downloaded")
        return {"version": version, "name": name, "url": url, "sha256": m.group(1), "size": size}
    raise AgentError(f"Cloudflare's latest release has no {name}")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _check(path: Path, check=None) -> None:
    if os.name == "nt":
        (check or (lambda p: check_signature(p, signer=SIGNER, whose="Cloudflare", what="cloudflared", done="run")))(path)
    elif check is not None:
        check(path)


def program_path(folder: Path) -> Path:
    return Path(folder) / ("cloudflared.exe" if os.name == "nt" else "cloudflared")


def download(http, folder: Path, progress=None, check=None, name: str | None = None) -> Path:
    """Download cloudflared into ``folder`` and check it (SHA-256 while it downloads, then on
    Windows its signature). Nothing is kept that fails a check."""
    name = name or asset_name()
    if name is None:
        raise AgentError("on a Mac, install cloudflared with Homebrew (brew install cloudflared), then press the button again")
    asset = release_asset(http.get_json(RELEASE_API, headers={"Accept": "application/vnd.github+json"}, cache=False), name)
    folder = Path(folder)
    dest = program_path(folder)
    part = folder / (dest.name + ".download")
    try:
        http.download(asset["url"], part, sha256=asset["sha256"], max_bytes=asset["size"], progress=progress)
        _check(part, check)
        if os.name != "nt":
            part.chmod(0o755)
        os.replace(part, dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    (folder / STATE).write_text(json.dumps({"version": asset["version"], "sha256": asset["sha256"]}) + "\n")
    log.info("downloaded cloudflared %s (checked)", asset["version"])
    return dest


def installed(folder: Path) -> dict:
    """{"path", "version", "ours"}: the cloudflared Craft Conductor downloaded, else one installed
    with Homebrew on a Mac (not ours to check); {} when there's none."""
    path = program_path(folder)
    try:
        state = json.loads((Path(folder) / STATE).read_text())
    except (OSError, ValueError):
        state = {}
    if path.is_file() and isinstance(state, dict) and state.get("sha256"):
        return {"path": str(path), "version": str(state.get("version", "")), "ours": True}
    if pf.system() == "Darwin":
        for brew in ("/opt/homebrew/bin/cloudflared", "/usr/local/bin/cloudflared"):
            if os.path.isfile(brew):
                return {"path": brew, "version": "", "ours": False}
    return {}


def verify(folder: Path, check=None) -> str:
    """Check the downloaded cloudflared again (unchanged since it was checked, and its signature),
    right before it runs; returns its path."""
    found = installed(folder)
    if not found:
        raise AgentError("cloudflared isn't downloaded yet")
    if found["ours"]:
        state = json.loads((Path(folder) / STATE).read_text())
        if _sha256(Path(found["path"])) != state["sha256"]:
            raise AgentError("cloudflared changed since it was downloaded, so it wasn't run: download it again")
        _check(Path(found["path"]), check)
    return found["path"]


def child_env() -> dict[str, str]:
    """Craft Conductor's environment without its secrets, and without cloudflared's own settings
    (TUNNEL_…, which could send the tunnel somewhere else)."""
    from .desktop import child_env as base
    return {k: v for k, v in base().items() if not k.upper().startswith(("TUNNEL", "CLOUDFLARED"))}


class QuickTunnel:
    """One running quick tunnel to ``http://127.0.0.1:<port>``: its address once Cloudflare gives
    one, and when it stops by itself."""

    def __init__(self, exe: str, port: int, config: Path, on_end=None, popen=subprocess.Popen,
                 hours: float = HOURS):
        self.port = port
        self.address = ""
        self.error = ""
        self.started = time.time()
        self.ends = self.started + hours * 3600
        self._on_end = on_end
        self._ready = threading.Event()
        self._stopped = False
        self.why = ""   # why it ended: "asked", "time" (HOURS went by), "closing", or "failed"
        Path(config).write_text("no-autoupdate: true\n")  # (its own settings file: never the one in ~/.cloudflared)
        from .desktop import NO_WINDOW
        argv = [exe, "tunnel", "--config", str(config), "--no-autoupdate", "--metrics", "127.0.0.1:0",
                "--url", f"http://127.0.0.1:{port}"]
        self.proc = popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                          text=True, encoding="utf-8", errors="replace", env=child_env(), close_fds=True, **NO_WINDOW)
        threading.Thread(target=self._read, daemon=True, name="cloudflared").start()
        self._timer = threading.Timer(max(0.0, self.ends - time.time()), self.stop, kwargs={"why": "time"})
        self._timer.daemon = True
        self._timer.start()

    def _read(self) -> None:
        last = ""
        for line in self.proc.stdout:
            line = line.rstrip()
            if line:
                last = line
                log.debug("cloudflared: %s", line)
            if not self.address and (m := URL.search(line)) and "api.trycloudflare.com" not in m.group(0):
                self.address = m.group(0)
                self._ready.set()
        code = self.proc.wait()
        if not self._stopped:
            self.error = (re.sub(r"^\S+\s+(ERR|INF|WRN)\s+", "", last)[:300] or f"cloudflared stopped (code {code})")
            log.warning("the Cloudflare tunnel stopped by itself: %s", self.error)
        self._ready.set()
        self._timer.cancel()
        if not self._stopped:
            self.why = "failed"
        if self._on_end is not None:
            self._on_end(self, self.why)

    def wait(self, timeout: float = 45) -> str:
        """The address, once Cloudflare gave it ("" if it didn't in time, or cloudflared stopped)."""
        self._ready.wait(timeout)
        return self.address

    def running(self) -> bool:
        return self.proc.poll() is None

    def stop(self, why: str = "asked") -> None:
        if why == "time":
            log.info("the Cloudflare tunnel closed after %s hours", HOURS)
        self._stopped, self.why = True, self.why or why
        self._timer.cancel()
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
