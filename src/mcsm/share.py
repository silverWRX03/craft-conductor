"""The share server: the one part of mcsm meant for friends on the internet.

It listens on its own port (8766 by default; forward it on your router along with the
Minecraft port) and answers friends' mcsm only, over HTTPS, per server with a friend
download switched on:

* ``/join/<secret>/pack.json``: what the friend's Minecraft needs (clientpack.py);
* ``/join/<secret>/mods/<file>``: your own mod files for players (the server's client-mods folder).

The certificate is mcsm's own (tlscert.py). Its fingerprint is part of the invite, and a
friend's mcsm refuses any other certificate, so nobody in between can read or change
what's sent. mcsm itself isn't handed out here: friends download it from GitHub.

There is no sign-in and nothing to change here; the secret in the invite keeps servers
from being found by guessing. The control panel stays on its own, private port.
"""

from __future__ import annotations

import hmac
import json
import logging
import re
import shutil
import threading
from http.server import BaseHTTPRequestHandler
from urllib.parse import quote, unquote

from . import __version__, tlscert
from .clientpack import PackBuilder
from .join import Invite
from .properties import read_properties

log = logging.getLogger(__name__)

DEFAULT_PORT = 8766
RELEASES = "https://github.com/silverWRX03/craft-conductor/releases/latest"
HEADERS = {
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
# For a browser (or an old mcsm) that talks plain HTTP to this port.
NOT_HTTPS = (b"HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain; charset=utf-8\r\nConnection: close\r\n\r\n"
             b"This is an mcsm server's secure invite port. To join, get mcsm from GitHub "
             b"(silverWRX03/craft-conductor), open it and paste the invite you were sent.\n")


def _is_local(host: str) -> bool:
    import ipaddress
    try:
        addr = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return host.endswith(".local") or host == "localhost"
    return addr.is_private or addr.is_loopback or addr.is_link_local


class ShareServer:
    def __init__(self, hub, port: int = DEFAULT_PORT, host: str = "0.0.0.0"):
        self.hub = hub
        self.port = port
        self.host = host
        self.httpd = None
        self.fingerprint = ""  # of the certificate: part of every invite
        self._builders: dict[str, tuple[object, PackBuilder]] = {}

    # ---------------------------------------------------------- lookups
    def server_for(self, token: str):
        for sid, d in list(self.hub.daemons.items()):
            c = d.m.config.client
            if c.enabled and c.token and hmac.compare_digest(c.token.encode(), token.encode()):
                return sid, d
        return None, None

    def builder(self, sid: str, d) -> PackBuilder:
        cached = self._builders.get(sid)
        if cached is None or cached[0] is not d.m:
            cached = self._builders[sid] = (d.m, PackBuilder(d.m))
        return cached[1]

    def address(self, d, request_host: str) -> str:
        """host:port players connect Minecraft to."""
        # A friend who reached this server through its local address is on the same
        # network, so they join through it too; everyone else uses the public address.
        tunnel = getattr(getattr(d.m, "config", None), "tunnel_address", "")
        if tunnel and not _is_local(request_host):
            return tunnel  # friends outside join through the playit.gg tunnel
        public = request_host if _is_local(request_host) else \
            (self.hub.share_settings().get("address") or "").strip() or request_host
        port = read_properties(d.m.server_dir / "server.properties").get("server-port", "25565")
        return public if port == "25565" else f"{public}:{port}"

    # ------------------------------------------------------------ server
    def start(self) -> None:
        from .web import _Server
        cert, key, self.fingerprint = tlscert.ensure(self.hub.state_dir / "tls")
        context = tlscert.server_context(cert, key)
        share = self

        class Handler(ShareHandler):
            server_ref = share

        self.httpd = _Server((self.host, self.port), Handler)  # (HTTPS only: see _Server.finish_request)
        self.httpd.tls_context, self.httpd.plain_http_reply = context, NOT_HTTPS
        threading.Thread(target=self.httpd.serve_forever, daemon=True, name="share").start()
        log.info("sharing with friends on port %s (HTTPS)", self.port)

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None


class ShareHandler(BaseHTTPRequestHandler):
    server_ref: ShareServer
    server_version = f"mcsm/{__version__}"
    timeout = 30  # reachable from the internet: don't hold on to connections that go quiet

    def log_message(self, fmt, *args):
        log.debug("share: " + fmt, *args)

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in HEADERS.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _text(self, status: int, message: str) -> None:
        self._send(status, (message + "\n").encode(), "text/plain; charset=utf-8")

    def _request_host(self) -> tuple[str, int]:
        raw = (self.headers.get("Host") or "").strip()
        m = re.fullmatch(r"\[?([A-Za-z0-9.:-]{1,253}?)\]?(?::(\d{1,5}))?", raw)
        host = m.group(1) if m else "localhost"
        port = int(m.group(2)) if m and m.group(2) else self.server_ref.port
        return host, port

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        """``/join/<secret>/request``: a friend with the invite asks to be let in (their Minecraft
        name, for the whitelist). Small, checked, and limited: the owner decides in mcsm."""
        m = re.fullmatch(r"/join/([A-Za-z0-9_-]{16,64})/request/?", self.path.split("?")[0])
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not m:
            if 0 < length <= 1024:  # (read first: Windows resets a connection closed with data unread)
                self.rfile.read(length)
            return self._text(404, "Nothing here.")
        if not 0 < length <= 1024:
            return self._text(413 if length > 1024 else 400, "Send a short JSON body.")
        sid, d = self.server_ref.server_for(m.group(1))
        if d is None:
            self.rfile.read(length)
            return self._text(404, "This invite isn't valid any more. Ask the server's owner for a new one.")
        try:
            name = str(json.loads(self.rfile.read(length) or b"{}").get("name", "")).strip()
        except (ValueError, AttributeError):
            name = ""
        if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", name):
            return self._text(400, "That isn't a Minecraft name (3 to 16 letters, numbers or _).")
        result = self.server_ref.hub.add_join_request(sid, name, self.client_address[0])
        # (a plain 200 even for "slow down": HTTP 429 would make the friend's mcsm wait and retry)
        return self._send(200, json.dumps({"ok": result != "slow down", "result": result}).encode(), "application/json")

    def do_GET(self):
        m = re.fullmatch(r"/join/([A-Za-z0-9_-]{16,64})(/pack\.json|/mods/([^/]{1,400}))?/?", self.path.split("?")[0])
        if not m:
            return self._text(404, "Nothing here. Open Craft Conductor and paste the invite you were sent.")
        token = m.group(1)
        sid, d = self.server_ref.server_for(token)
        if d is None:
            return self._text(404, "This invite isn't valid any more. Ask the server's owner for a new one.")
        if not m.group(2):  # someone opened the invite link in a browser
            return self._text(200, f"This is an invite to an Craft Conductor server. Get Craft Conductor from {RELEASES}, "
                                   "open it, and paste the invite you were sent.")
        host, port = self._request_host()
        try:
            pack = self.server_ref.builder(sid, d).build(self.server_ref.address(d, host))
        except Exception as e:
            log.warning("couldn't build the friend download for %s: %s", sid, e)
            return self._text(503, "The server isn't ready for players yet. Try again later.")  # details stay in the log
        if m.group(2) == "/pack.json":
            # Your own files come from here: point them at this address, as the friend reached it.
            base = Invite(host, port, token).url
            mods = [{**x, "url": f"{base}/mods/{quote(x['filename'])}"} if x.get("local") else x
                    for x in pack.get("mods", [])]
            whitelist = read_properties(d.m.server_dir / "server.properties").get("white-list", "false") == "true"
            return self._send(200, json.dumps({**pack, "mods": mods, "whitelist": whitelist}).encode(), "application/json")
        from .clientpack import JAR_NAME, local_jars
        name = unquote(m.group(3))
        jar = next((p for p in local_jars(d.m.config) if p.name == name), None) if JAR_NAME.fullmatch(name) else None
        if jar is None:
            return self._text(404, "No such file.")
        self.send_response(200)
        for k, v in {**HEADERS, "Content-Type": "application/java-archive", "Content-Length": str(jar.stat().st_size)}.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            with open(jar, "rb") as fh:
                shutil.copyfileobj(fh, self.wfile, 1 << 16)
        return None
