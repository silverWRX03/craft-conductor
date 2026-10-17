"""The control panel's doors for tunnels: Tailscale (private to your own devices) and Cloudflare's
quick tunnel (the internet, for a few hours).

A tunnel's program runs on this computer and passes requests on from elsewhere, so they arrive
from this computer's own address. Each tunnel is given its own door: a listener on 127.0.0.1, on a
port of its own, that only that tunnel's program is pointed at. A request through a door:

* never counts as "on this computer" (no password reset, PIN, or local-only action);
* is only answered for that tunnel's own address (its Host);
* is told apart from other visitors by what that tunnel says about it, which was checked
  (2026-10-16): Tailscale replaces ``X-Forwarded-For`` with the visitor's tailnet address and adds
  ``Tailscale-User-Login`` (removing copies a visitor sends); Cloudflare adds ``Cf-Connecting-Ip``
  (refusing a visitor's own copy) and appends to ``X-Forwarded-For``. A header is only believed at
  its own tunnel's door: anyone can send any header to the control panel's usual port.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import random
import threading
import time
from pathlib import Path

from . import cloudflare, peer

log = logging.getLogger(__name__)

KINDS = ("tailscale", "cloudflare")
PORTS = range(20000, 29999)   # where the doors' ports are picked (on 127.0.0.1 only)


def visitor_ip(kind: str, headers) -> str | None:
    """The visitor's address as this tunnel says it (only called for a request at its own door)."""
    if kind == "tailscale":
        if not headers.get("Tailscale-User-Login"):
            return None  # (Funnel: from the internet, and not checked what Tailscale says then)
        raw = headers.get("X-Forwarded-For") or ""
    elif kind == "cloudflare":
        raw = headers.get("Cf-Connecting-Ip") or ""
    else:
        return None
    try:
        return str(ipaddress.ip_address(raw.strip()))
    except ValueError:
        return None


def visitor_key(kind: str, headers) -> str:
    """Whose sign-in tries these are, for the limits: one visitor's mistakes never lock out another."""
    ip = visitor_ip(kind, headers)
    if kind == "tailscale" and ip is None:
        return "funnel"  # (every Funnel visitor shares this one; your own devices and this computer don't)
    return f"{kind}:{ip or '?'}"


class Doors:
    """The tunnels' listeners for one control panel (WebUI), and the Cloudflare tunnel itself."""

    def __init__(self, ui):
        self.ui = ui
        self.servers: dict[str, object] = {}
        self.hosts: dict[str, str] = {}      # each door answers only for its tunnel's address
        self.quick: cloudflare.QuickTunnel | None = None
        self.quick_error = ""
        self.downloading: dict = {"state": "idle"}
        self.lock = threading.RLock()

    # ------------------------------------------------------------- doors
    def open(self, kind: str, port: int = 0) -> int:
        """Open (or keep) ``kind``'s door; returns its port. ``port`` 0 picks a free one."""
        from .web import _Server
        with self.lock:
            if kind in self.servers:
                return self.servers[kind].server_address[1]
            server = None
            if port:
                try:
                    server = _Server(("127.0.0.1", port), self.ui.handler_class)
                except OSError:
                    server = None
            if server is None:
                server = self._free(kind)
            server.daemon_threads = True
            server.tunnel = kind
            self.servers[kind] = server
            threading.Thread(target=server.serve_forever, daemon=True, name=f"web-{kind}").start()
            return server.server_address[1]

    def panel_port(self) -> int:
        """The control panel's usual way in (the port it's on this time)."""
        return self.ui.httpd.server_address[1] if self.ui.httpd else self.ui.port

    def _free(self, kind: str):
        from .web import _Server
        taken = set(self.ui.hub.reserved_ports()) | {self.panel_port()}
        for p in random.sample(PORTS, 200):
            if p in taken:
                continue
            try:
                return _Server(("127.0.0.1", p), self.ui.handler_class)
            except OSError:
                continue
        return _Server(("127.0.0.1", 0), self.ui.handler_class)

    def close(self, kind: str) -> None:
        with self.lock:
            server = self.servers.pop(kind, None)
            self.hosts.pop(kind, None)
        if server is not None:
            server.shutdown()
            server.server_close()

    def port(self, kind: str) -> int | None:
        server = self.servers.get(kind)
        return server.server_address[1] if server is not None else None

    def ports(self) -> list[int]:
        return [s.server_address[1] for s in list(self.servers.values())]

    def host_ok(self, kind: str, host_header: str | None) -> bool:
        want = self.hosts.get(kind)
        if not want or not host_header:
            return False
        host = host_header.strip().lower()
        host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
        return host.rstrip(".") == want

    def close_all(self) -> None:
        self.stop_quick("closing")
        for kind in list(self.servers):
            self.close(kind)

    # --------------------------------------------------------- Tailscale
    def saved_tailscale(self) -> dict:
        t = self.ui.hub._hub_file().get("tunnels", {})
        t = t.get("tailscale") if isinstance(t, dict) else None
        return t if isinstance(t, dict) else {}

    def _save_tailscale(self, value: dict | None) -> None:
        def change(data: dict) -> None:
            t = data.setdefault("tunnels", {})
            if value is None:
                t.pop("tailscale", None)
            else:
                t["tailscale"] = value
        self.ui.hub._update_hub_file(change)

    def tailscale_on(self, name: str, funnel: bool, serve) -> dict:
        """Point ``tailscale serve`` (or Funnel) at Tailscale's door. ``serve(port, funnel)`` runs it."""
        saved = self.saved_tailscale()
        port = self.open("tailscale", int(saved.get("port") or 0))
        self.hosts["tailscale"] = name
        result = serve(port, funnel)
        if result.get("ok"):
            self._save_tailscale({"port": port, "name": name, "funnel": bool(funnel)})
        elif not saved:
            self.close("tailscale")
        return result

    def tailscale_off(self, unserve) -> None:
        saved = self.saved_tailscale()
        unserve(bool(saved.get("funnel")))
        self._save_tailscale(None)
        self.close("tailscale")

    def resume(self, status, serve) -> None:
        """At start: open Tailscale's door again, and move a ``tailscale serve`` that still points at
        the control panel's usual port (set up by an earlier version) to it. ``status(port)`` and
        ``serve(port, funnel)`` are tailscale.py's."""
        saved = self.saved_tailscale()
        if saved.get("port"):
            port = self.open("tailscale", int(saved["port"]))
            self.hosts["tailscale"] = str(saved.get("name") or "")
            if port != int(saved["port"]):  # (its port was taken this time: Tailscale is pointed at the new one)
                log.info("Tailscale's door moved to port %s", port)
                if serve(port, bool(saved.get("funnel"))).get("ok"):
                    self._save_tailscale({**saved, "port": port})
            return
        st = status(self.panel_port())
        if st.get("serving") and st.get("name"):
            log.info("moving the secure Tailscale address to a door of its own (requests through it never "
                     "count as on this computer)")
            self.tailscale_on(st["name"], False, serve)

    # -------------------------------------------------------- Cloudflare
    def tools(self) -> Path:
        folder = self.ui.hub.state_dir / "tools"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def quick_info(self) -> dict:
        q = self.quick
        found = cloudflare.installed(self.tools())
        info = {"installed": bool(found), "version": found.get("version", "") if found else "",
                "download": dict(self.downloading), "hours": cloudflare.HOURS,
                "downsides": list(cloudflare.DOWNSIDES), "terms": cloudflare.TERMS, "about": cloudflare.ABOUT,
                "error": self.quick_error, "running": False, "address": "", "ends": None,
                "mac": cloudflare.asset_name() is None}
        if q is not None and q.running():
            info.update(running=True, address=q.address, ends=int(q.ends), starting=not q.address)
        return info

    def download(self, http) -> None:
        """Download cloudflared in the background (the page asks how it's going)."""
        with self.lock:
            if self.downloading.get("state") == "downloading":
                return
            self.downloading = {"state": "downloading", "got": 0, "size": None}

        def progress(got, size):
            self.downloading.update(got=got, size=size)

        def run():
            try:
                cloudflare.download(http, self.tools(), progress=progress)
                self.downloading = {"state": "done"}
            except Exception as e:  # (anything: said on the page, nothing kept)
                log.warning("cloudflared wasn't downloaded: %s", e)
                self.downloading = {"state": "error", "error": str(e)}
        threading.Thread(target=run, daemon=True, name="cloudflared-download").start()

    def start_quick(self, popen=None, check=None) -> dict:
        with self.lock:
            if self.quick is not None and self.quick.running():
                return self.quick_info()
            exe = cloudflare.verify(self.tools(), check=check)
            self.leftover()
            port = self.open("cloudflare")
            self.quick_error = ""
            kwargs = {"popen": popen} if popen is not None else {}
            self.quick = cloudflare.QuickTunnel(exe, port, self.tools() / "cloudflared-config.yml",
                                                on_end=self._quick_ended, **kwargs)
            self._pid(self.quick.proc.pid, exe)
        address = self.quick.wait()
        if address:
            self.hosts["cloudflare"] = address.removeprefix("https://")
            log.info("the control panel is on the internet at %s until %s (Cloudflare quick tunnel)", address,
                     time.strftime("%H:%M", time.localtime(self.quick.ends)))
        elif self.quick.running():
            self.quick.stop("failed")
            self.quick_error = "Cloudflare didn't give the tunnel an address in time; try again later"
        return self.quick_info()

    def stop_quick(self, why: str = "asked") -> None:
        q = self.quick
        if q is not None:
            q.stop(why)

    def _quick_ended(self, q, why: str) -> None:
        if q is not self.quick:
            return
        if why == "failed" and q.error:
            self.quick_error = q.error
        self.close("cloudflare")
        self._pid(None)
        if why in ("time", "failed"):
            message = (f"The control panel is off the internet again: the Cloudflare tunnel closed after {cloudflare.HOURS} hours"
                       if why == "time" else f"The Cloudflare tunnel stopped: {q.error}")
            log.warning("%s", message)

    def _pid(self, pid: int | None, exe: str = "") -> None:
        path = self.tools() / "cloudflared.pid"
        if pid is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(json.dumps({"pid": pid, "exe": exe}))

    def leftover(self) -> None:
        """A cloudflared Craft Conductor started and couldn't stop (it closed suddenly): stopped now."""
        path = self.tools() / "cloudflared.pid"
        try:
            saved = json.loads(path.read_text())
            pid, exe = int(saved["pid"]), str(saved["exe"])
        except (OSError, ValueError, KeyError, TypeError):
            return
        path.unlink(missing_ok=True)
        if exe and peer.program_file(pid).lower() == exe.lower():
            import os
            import signal
            try:
                os.kill(pid, signal.SIGTERM)
                log.info("stopped the Cloudflare tunnel left from before Craft Conductor closed")
            except OSError:
                pass
