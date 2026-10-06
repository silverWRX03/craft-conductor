"""The web UI: a small JSON API plus a static single-page app, served from ``craft-conductor run --web``.

Security model: listen on localhost by default; every API call (except login)
needs a session cookie obtained with the password or PIN (see webauth.py); the
cookie is HttpOnly and SameSite=Strict, and state-changing requests must also carry
an ``X-CRAFT-CONDUCTOR`` header, which cross-site pages cannot add without a CORS preflight we
never allow. Requests must name this machine in their Host header, so a web page
can't reach the panel through DNS rebinding. PINs only work for browsers on this
computer.
"""

from __future__ import annotations

import functools
import hashlib
import ipaddress
import json
import os
import logging
import re
import secrets
import shutil
import socket
import socketserver
import ssl
import tempfile
import threading
import time
import tomllib
import urllib.parse
import webbrowser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any, Callable

from . import __version__, backup, config as configmod, configs, licenses, limits, notice, passkeys, selfupdate, serverprops, setup as setupmod, stats, webauth
from .config import ConfigError, ModSpec
from .daemon import Daemon, set_current_server
from .process import check_command
from .hub import Hub
from .minecraft import Mojang
from .http import HttpError, sha1_file
from .java import JavaError
from .mods import ModError, Unavailable
from .mods.curseforge import CurseForgeProvider
from .mods.modrinth import ModrinthProvider, keep_buildable
from .planner import lowest
from .players import PlayerError, Players, broadcast_text
from .properties import read_properties, write_properties
from .skins import SkinError, Skins

log = logging.getLogger(__name__)

SESSION_COOKIE = "craft_conductor_session"
SESSION_TTL = 7 * 86400
DEVICE_COOKIE = "craft_conductor_device"
# What a paired phone may do: look at things, and the everyday controls. Not uploads, config
# files, the console, settings, Java, mods, exports or the sign-in itself.
DEVICE_POSTS = {"/api/server/start", "/api/server/stop", "/api/server/restart", "/api/backups/create",
                "/api/updates/check", "/api/updates/apply", "/api/players/action", "/api/logout",
                "/api/join-requests/answer", "/api/broadcast"}
DEVICE_HIDDEN_GETS = {"/api/configs/file", "/api/hub/passkeys", "/api/export/download", "/api/settings", "/api/hub/curseforge",
                      "/api/hub/discord", "/api/hub/discord/guilds", "/api/hub/discord/channels", "/api/hub/discord/roles",
                      "/api/hub/remote", "/api/hub/saves", "/api/doctor/report"}


# A paired phone turning its own notifications on or off (it names itself by its push address).
PHONE_POSTS = {"/api/hub/phone/subscribe", "/api/hub/phone/unsubscribe", "/api/hub/phone/test", "/api/hub/phone/prefs"}


def device_allowed(method: str, path: str, role: str = "helper") -> bool:
    """What a paired device may do: viewers only look (and can sign out)."""
    if method == "POST" and path in PHONE_POSTS:
        return True
    if method == "POST":
        return path == "/api/logout" if role == "viewer" else path in DEVICE_POSTS
    return path not in DEVICE_HIDDEN_GETS
MAX_JSON = 1 << 20
MAX_UPLOAD = 512 << 20
MAX_ARCHIVE = 64 << 30
LANGUAGES = ("es", "pt", "fr", "de", "hi", "zh", "vi", "ar", "ko")  # besides English: src/craft_conductor/webui/i18n/<code>.json
LOCAL_ONLY = {"/api/open", "/api/hub/open", "/api/hub/remote-install/open", "/api/play-here", "/api/hub/singleplayer/install"}  # they act on this computer's screen  # a whole server (worlds and all), for importing
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/rich.js": ("rich.js", "text/javascript; charset=utf-8"),
          "/pager.js": ("pager.js", "text/javascript; charset=utf-8"),
          "/manual.md": ("manual.md", "text/markdown; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8"),
          "/craft-conductor-theme.css": ("craft-conductor-theme.css", "text/css; charset=utf-8"),
          "/icon.png": ("icon.png", "image/png"),
          "/icon-192.png": ("icon-192.png", "image/png"),
          "/icon-512.png": ("icon-512.png", "image/png"),
          "/sw.js": ("sw.js", "text/javascript; charset=utf-8"),  # the installed app's notifications
          "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
          "/help-network.svg": ("help-network.svg", "image/svg+xml"),
          "/help-router.svg": ("help-router.svg", "image/svg+xml"),
          "/i18n.js": ("i18n.js", "text/javascript; charset=utf-8"),
          # the page's words in other languages (see i18n.js)
          **{f"/i18n/{code}.json": (f"i18n/{code}.json", "application/json; charset=utf-8") for code in LANGUAGES}}
# The pictures in Help and the user manual (webui/screenshots, retaken by tests/test_screenshots.py).
SCREENSHOTS = sorted(f.name for f in resources.files("craft_conductor").joinpath("webui", "screenshots").iterdir()
                     if f.name.endswith(".png"))
STATIC.update({f"/screenshots/{name}": (f"screenshots/{name}", "image/png") for name in SCREENSHOTS})
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' https: data:; style-src 'self'; "
                               "script-src 'self'; connect-src 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


# Reachable before the first-run notice has been accepted.
# A sign-in with craft-conductor's one-time password (headless first run) can only replace it.
FIRST_SIGN_IN_OK = {"/api/auth/change", "/api/logout", "/api/hub", "/api/notice", "/api/notice/accept", "/api/licenses"}
NOTICE_EXEMPT = {"/api/notice", "/api/notice/accept", "/api/status", "/api/licenses", "/api/auth/change", "/api/hub"}
# Routes whose request body is a file, streamed to disk rather than parsed as JSON.
RAW_UPLOADS = {"/api/hub/stage", "/api/mods/local", "/api/client/local"}
# Headers a reverse proxy or tunnel adds: a request carrying any of them didn't come straight
# from a browser on this computer.
PROXY_HEADERS = ("X-Forwarded-For", "Forwarded", "X-Real-IP", "X-Forwarded-Host", "X-Forwarded-Proto", "Via",
                 "Tailscale-User-Login", "CF-Connecting-IP", "True-Client-IP")
SERVER_PATH = re.compile(r"^/api/servers/([a-z0-9][a-z0-9-]{0,63})(/.*)$")


@functools.lru_cache(maxsize=None)
def static_file(name: str) -> tuple[bytes, str]:
    """The page's own files: read once (they're part of craft-conductor), with an ETag so browsers can
    keep their copy and just ask whether it changed."""
    body = resources.files("craft_conductor").joinpath("webui", name).read_bytes()
    return body, '"' + hashlib.sha256(body).hexdigest()[:20] + '"'


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def host_allowed(host_header: str | None, extra: list[str]) -> bool:
    """Whether a request's Host header names this machine (guards against DNS rebinding)."""
    if not host_header:
        return True  # HTTP/1.0 clients; browsers always send one
    host = host_header.strip().lower()
    if host.startswith("["):
        host = host[1:host.find("]")] if "]" in host else host
    else:
        host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    host = host.rstrip(".")
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    if host == "localhost" or host.endswith((".localhost", ".local")) or host in extra:
        return True
    name = socket.gethostname().lower()
    return host in (name, name.split(".")[0])


def is_loopback(address: str) -> bool:
    try:
        return ipaddress.ip_address(address.split("%")[0]).is_loopback
    except ValueError:
        return False


class WebUI:
    def __init__(self, hub: Hub, host: str | None = None, port: int | None = None):
        self.hub = hub
        cfg = hub.web
        self.host = host or cfg.host
        self.port = cfg.port if port is None else port
        self.store = webauth.AuthStore(hub)   # the hub has the state_dir and [web] settings
        self.sessions: dict[str, float] = {}
        self.first_sign_in: set[str] = set()   # sessions that may only choose a password
        self.failures: dict[str, list[float]] = {}
        self.devices = webauth.Devices(hub.state_dir)
        self.passkeys = passkeys.Passkeys(hub.state_dir)
        self.lock = threading.Lock()
        self.httpd: ThreadingHTTPServer | None = None
        self._apis: dict[str, Api] = {}
        self.hub_api = HubApi(self)

    @property
    def auth(self) -> webauth.Auth:
        return self.store.get()

    def api_for(self, sid: str) -> Api:
        d = self.hub.get(sid)
        if d is None:
            raise ApiError(404, "there's no server with that id (it may have been removed)")
        api = self._apis.get(sid)
        if api is None or api.d is not d:
            api = self._apis[sid] = Api(self, d, sid)
        return api

    @property
    def api(self) -> Api:
        """The server's API when there is only one (`craft-conductor run`)."""
        only = self.hub.only()
        if not only:
            raise ApiError(404, "pick a server first")
        return self.api_for(only[0])

    @property
    def tls(self) -> bool:
        """HTTPS, with a certificate the user provides (encrypts sign-ins over a network)."""
        cfg = self.hub.web
        return bool(cfg.tls_cert and cfg.tls_key and Path(cfg.tls_cert).is_file() and Path(cfg.tls_key).is_file())

    @property
    def url(self) -> str:
        host = "localhost" if self.host in ("127.0.0.1", "0.0.0.0", "::") else self.host
        return f"{'https' if self.tls else 'http'}://{host}:{self.httpd.server_address[1] if self.httpd else self.port}/"

    def start(self) -> None:
        ui = self

        class Handler(RequestHandler):
            web = ui
        self.httpd = _Server((self.host, self.port), Handler)
        self.httpd.daemon_threads = True
        if self.tls:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            try:
                context.load_cert_chain(self.hub.web.tls_cert, self.hub.web.tls_key)
                self.httpd.tls_context = context
                self.httpd.plain_http_reply = NOT_HTTPS
            except (OSError, ssl.SSLError) as e:
                log.error("couldn't use the HTTPS certificate (%s); the control panel stays on plain HTTP", e)
                self.hub.web.tls_cert = ""
        threading.Thread(target=self.httpd.serve_forever, daemon=True, name="web").start()
        log.info("web UI at %s - password: %s", self.url, webauth.describe(self.auth))

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()

    # ------------------------------------------------------------ sessions
    def login(self, password: str, client: str, local: bool = True) -> str:
        now = time.time()
        auth = self.auth
        if not local and not auth.remote_ready and not auth.temporary:
            raise ApiError(403, "signing in from another device needs a strong password "
                                f"({webauth.STRONG_RULES}); set one in Craft Conductor settings on the server's own computer")
        with self.lock:
            if len(self.failures) > 1000:  # forget old attempts, so the table can't grow without end
                self.failures = {k: v for k, v in self.failures.items() if v and now - v[-1] < 300}
            recent = [t for t in self.failures.get(client, []) if now - t < 300]
            if len(recent) >= 5:
                raise ApiError(429, "too many attempts; wait a few minutes")
            # (counted before the check, not after: tries sent all at once can't slip past the limit)
            self.failures[client] = recent + [now]
        if not auth.check(password):
            raise ApiError(401, "wrong PIN" if auth.mode == "pin" else "wrong password")
        with self.lock:
            self.failures.pop(client, None)
            token = self._new_session(now)
            if auth.temporary:
                self.first_sign_in.add(token)
            return token

    def passkey_login(self, rp_id: str, origins: set[str], b: dict, client: str, local: bool) -> str:
        """Sign in with a fingerprint or face (passkeys.py): the same limits as a password."""
        now = time.time()
        auth = self.auth
        if not local and not auth.remote_ready:
            raise ApiError(403, "signing in from another device needs a strong password set first")
        with self.lock:
            recent = [t for t in self.failures.get(client, []) if now - t < 300]
            if len(recent) >= 5:
                raise ApiError(429, "too many attempts; wait a few minutes")
            self.failures[client] = recent + [now]
        try:
            used = self.passkeys.verify(rp_id, origins, str(b.get("id", "")), str(b.get("client_data", "")),
                                        str(b.get("auth_data", "")), str(b.get("signature", "")))
        except (passkeys.PasskeyError, ValueError) as e:
            raise ApiError(401, str(e)) from None
        log.info("signed in with the passkey %s", used["name"])
        with self.lock:
            self.failures.pop(client, None)
            return self._new_session(now)

    def _new_session(self, now: float) -> str:
        token = secrets.token_urlsafe(32)
        self.sessions = {t: exp for t, exp in self.sessions.items() if exp > now}
        self.sessions[token] = now + SESSION_TTL
        return token

    def change(self, mode: str, secret: str, local: bool) -> str:
        """Change how the panel is protected; signs out everyone else (paired phones too) and
        returns a new session."""
        if self.remote_on() and not (mode == "password" and webauth.strong_password(secret)):
            raise ApiError(400, "remote access is on, so the password must be strong: " + webauth.STRONG_RULES
                           + ". PINs can't be used then")
        if self.auth.temporary and not local and not (mode == "password" and webauth.strong_password(secret)):
            raise ApiError(400, "choose a strong password: " + webauth.STRONG_RULES)
        self.store.set(mode, secret)
        removed = self.devices.remove(None)
        if removed:
            log.info("signed out %d paired phone(s) because the password changed", removed)
        if self.passkeys.remove(None):
            log.info("removed the fingerprint and face sign-ins because the password changed")
        log.info("web UI sign-in changed to %s", mode)
        with self.lock:
            self.sessions.clear()
            self.first_sign_in.clear()
            return self._new_session(time.time())

    def remote_on(self) -> bool:
        """Other devices can reach the panel (network access is on)."""
        return self.hub.web.host not in ("127.0.0.1", "localhost", "::1")

    def reset_to_default(self) -> None:
        self.store.reset()
        self.devices.remove(None)
        self.passkeys.remove(None)
        log.info("web UI password reset to the default from this computer")
        with self.lock:
            self.sessions.clear()
            self.failures.clear()

    def valid(self, token: str | None, local: bool = False) -> bool:
        if not token:
            return False
        with self.lock:
            exp = self.sessions.get(token)
            return exp is not None and exp > time.time()

    def logout(self, token: str | None) -> None:
        with self.lock:
            self.sessions.pop(token or "", None)


HANDSHAKE_SECONDS = 15


def close_gently(sock) -> None:
    """Finish sending, then read what the client sent (unread): closing with unread data makes
    macOS and Windows reset the connection, which can lose the answer before it's read."""
    try:
        sock.shutdown(socket.SHUT_WR)
        sock.settimeout(2)
        received = 0
        while received < 65536:
            chunk = sock.recv(4096)
            if not chunk:
                break
            received += len(chunk)
    except OSError:
        pass


class _Server(ThreadingHTTPServer):
    """One thread per connection, with a cap: connections past MAX_CONNECTIONS are closed at
    once, so a flood of idle connections can't use up threads and memory. (Each handler also
    times out a connection that goes quiet; see REQUEST_TIMEOUT.)"""
    daemon_threads = True
    MAX_CONNECTIONS = 64
    request_queue_size = 64  # (connections waiting to be accepted: a page opening fires off many at once)

    def __init__(self, *args, **kwargs):
        self._slots = threading.BoundedSemaphore(self.MAX_CONNECTIONS)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)  # too busy: drop it rather than queue it
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    # HTTPS: the handshake happens in finish_request, in the connection's own thread, so a slow
    # or silent client can't hold up anyone else (wrapping the listening socket would do it in
    # the one thread that accepts every connection).
    tls_context: ssl.SSLContext | None = None
    plain_http_reply = b""   # for a browser talking plain HTTP to the HTTPS port

    def finish_request(self, request, client_address):
        if self.tls_context is None:
            return super().finish_request(request, client_address)
        request.settimeout(HANDSHAKE_SECONDS)
        try:
            first = request.recv(1, socket.MSG_PEEK)
            if first != b"\x16":  # not a TLS handshake
                if first:
                    request.sendall(self.plain_http_reply)
                    close_gently(request)
                return
            tls = self.tls_context.wrap_socket(request, server_side=True)
        except (OSError, ssl.SSLError) as e:
            log.debug("connection from %s dropped: %s", client_address[0], e)
            return
        try:
            tls.settimeout(self.RequestHandlerClass.timeout)
            self.RequestHandlerClass(tls, client_address, self)
        finally:
            try:
                tls.close()
            except OSError:
                pass

    def server_bind(self):
        # HTTPServer.server_bind() looks up the host's full DNS name, which can take
        # many seconds on macOS. The name isn't needed, so skip the lookup.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


NOT_HTTPS = (b"HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain; charset=utf-8\r\nConnection: close\r\n\r\n"
             b"This is Craft Conductor's control panel, on HTTPS: open it with https:// at the start of the address.\n")
REQUEST_TIMEOUT = 60  # seconds a connection may sit silent before it's closed


class RequestHandler(BaseHTTPRequestHandler):
    web: WebUI
    server_version = f"craft-conductor/{__version__}"
    timeout = REQUEST_TIMEOUT
    _body_read = False  # whether this request's body was read (see _fail)

    def log_message(self, fmt, *args):  # keep the server console clean
        log.debug("web: " + fmt, *args)

    # --------------------------------------------------------------- utils
    def _send(self, status: int, body: bytes, content_type: str, headers: dict[str, str] | None = None):
        self._drain()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        headers = {"Cache-Control": "no-store", **SECURITY_HEADERS, **(headers or {})}
        if self.web.tls:
            headers["Strict-Transport-Security"] = "max-age=31536000"
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path):
        """Stream a file from disk as a download."""
        size = path.stat().st_size
        self._drain()
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(size))
        quoted = urllib.parse.quote(path.name)
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quoted}")
        for k, v in {"Cache-Control": "no-store", **SECURITY_HEADERS}.items():
            self.send_header(k, v)
        self.end_headers()
        with open(path, "rb") as f:
            shutil.copyfileobj(f, self.wfile, 1 << 20)

    def _json(self, status: int, obj: Any, headers: dict[str, str] | None = None):
        self._send(status, json.dumps(obj).encode(), "application/json", headers)

    def _token(self) -> str | None:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        return cookie[SESSION_COOKIE].value if SESSION_COOKIE in cookie else None

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "bad Content-Length") from None
        if length > MAX_JSON:
            raise ApiError(413, "request too large")
        if length < 0:  # (reading -1 bytes would read until the client stops sending)
            raise ApiError(400, "bad Content-Length")
        self._body_read = True
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            raise ApiError(400, "invalid JSON") from None
        if not isinstance(data, dict):
            raise ApiError(400, "expected a JSON object")
        return data

    def _cookie(self, token: str, name: str = SESSION_COOKIE, ttl: int = SESSION_TTL) -> str:
        secure = "; Secure" if self.web.tls else ""
        return f"{name}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={ttl}{secure}"

    def _cookie_value(self, name: str) -> str | None:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        return cookie[name].value if name in cookie else None

    def _pair(self):
        """A phone that scanned the pairing QR code: swap the one-time code for its own key."""
        now = time.time()
        client = self.client_address[0]
        if not self.web.auth.remote_ready:
            raise ApiError(403, "set a strong password on the server's computer before pairing a phone")
        with self.web.lock:
            recent = [t for t in self.web.failures.get("pair:" + client, []) if now - t < 300]
            if len(recent) >= 5:
                raise ApiError(429, "too many attempts; wait a few minutes")
            self.web.failures["pair:" + client] = recent + [now]  # (forgotten again if it works)
        b = self._body()
        try:
            token, device = self.web.devices.pair(str(b.get("code", "")), str(b.get("name", "")), client, now)
        except ConfigError as e:
            raise ApiError(400, str(e)) from None
        with self.web.lock:
            self.web.failures.pop("pair:" + client, None)
        log.info("paired %s as a %s (from %s)", device["name"], device["role"], client)
        return self._json(200, {"ok": True, "name": device["name"]},
                          {"Set-Cookie": self._cookie(token, DEVICE_COOKIE, webauth.DEVICE_DAYS * 86400)})

    def _local(self) -> bool:
        """A browser on this computer, talking to us directly (not through a proxy).

        "Local" unlocks the PIN and no-password modes and the forgotten-password reset, so
        anything that looks like a proxy on this computer (nginx, Caddy, `tailscale serve`,
        a tunnel) counts as remote, and so does a Host that isn't this computer's loopback name."""
        if not is_loopback(self.client_address[0]) or any(self.headers.get(h) for h in PROXY_HEADERS):
            return False
        host = (self.headers.get("Host") or "localhost").strip().lower()
        host = host[1:host.find("]")] if host.startswith("[") and "]" in host else host.rsplit(":", 1)[0]
        return host in ("localhost", "127.0.0.1", "::1")

    def _rp(self) -> tuple[str, set[str]]:
        """The passkey "relying party": this address's host name, and the page origins that may
        use it (passkeys.py). Browsers only allow them on HTTPS or localhost, never an IP address."""
        raw = (self.headers.get("Host") or "").strip().lower()
        host = raw[1:raw.find("]")] if raw.startswith("[") and "]" in raw else raw.rsplit(":", 1)[0] if raw.count(":") == 1 else raw
        try:
            ipaddress.ip_address(host)
            raise ApiError(400, "fingerprint and face sign-in needs a host name (like the Tailscale address), not an IP address")
        except ValueError:
            pass
        if not re.fullmatch(r"[a-z0-9.-]{1,253}", host):
            raise ApiError(400, "that address can't use fingerprint or face sign-in")
        origins = {f"https://{raw}"}
        if host == "localhost" or host.endswith(".localhost"):
            origins.add(f"http://{raw}")
        return host, origins

    def _host_ok(self) -> bool:
        if host_allowed(self.headers.get("Host"), self.web.hub.web.allowed_hosts):
            return True
        self._send(421, b"This address isn't allowed. If you reach craft-conductor through a reverse proxy or a custom "
                        b"host name, add it to [web] allowed_hosts in craft-conductor.toml.\n", "text/plain; charset=utf-8")
        return False

    # ------------------------------------------------------------ routing
    def do_GET(self):
        if not self._host_ok():
            return
        path, _, qs = self.path.partition("?")
        if path in STATIC:
            name, ctype = STATIC[path]
            body, etag = static_file(name)
            if self.headers.get("If-None-Match") == etag:  # the browser's copy is current
                self.send_response(304)
                self.send_header("ETag", etag)
                self.end_headers()
                return None
            return self._send(200, body, ctype, {"ETag": etag, "Cache-Control": "no-cache"})
        self._dispatch("GET", path, urllib.parse.parse_qs(qs))

    def do_POST(self):
        self._body_read = False  # (the same handler answers each request on a kept-open connection)
        if not self._host_ok():
            return
        path, _, qs = self.path.partition("?")
        self._dispatch("POST", path, urllib.parse.parse_qs(qs))

    def _dispatch(self, method: str, path: str, query: dict[str, list[str]]):
        try:
            if not path.startswith("/api/"):
                raise ApiError(404, "not found")
            if method == "POST" and self.headers.get("X-CRAFT-CONDUCTOR") != "1":
                raise ApiError(403, "missing X-CRAFT-CONDUCTOR header")
            local = self._local()
            if path == "/api/auth" and method == "GET":
                info = self.web.auth.info()
                try:
                    info = {**info, "passkeys": self.web.passkeys.count(self._rp()[0]) > 0}
                except ApiError:
                    info = {**info, "passkeys": False}
                # (the sign-in dialog lists what a new password needs: a strong one with remote
                # access on, or when replacing a one-time password from another device)
                return self._json(200, {**info, "local": local,
                                        "strong_required": self.web.remote_on() or (bool(info.get("temporary")) and not local)})
            if path == "/api/login" and method == "POST":
                token = self.web.login(str(self._body().get("password", "")), self.client_address[0], local)
                return self._json(200, {"ok": True}, {"Set-Cookie": self._cookie(token)})
            if path == "/api/pair" and method == "POST":
                return self._pair()
            if path == "/api/passkey/options" and method == "POST":  # signing in with a fingerprint or face
                rp_id, _ = self._rp()
                if not self.web.passkeys.count(rp_id):
                    raise ApiError(404, "no fingerprint or face sign-in has been added at this address")
                return self._json(200, self.web.passkeys.request_options(rp_id))
            if path == "/api/passkey/login" and method == "POST":
                rp_id, origins = self._rp()
                token = self.web.passkey_login(rp_id, origins, self._body(), self.client_address[0], local)
                return self._json(200, {"ok": True}, {"Set-Cookie": self._cookie(token)})
            if path == "/api/auth/reset-local" and method == "POST":
                # Forgot the password? Whoever sits at the server's own computer can go back to
                # the default (the same as `craft-conductor web-password --reset`); never over the network.
                if not local:
                    raise ApiError(403, "this only works in a browser on the server's own computer")
                self.web.reset_to_default()
                return self._json(200, {"ok": True, **self.web.auth.info()})
            device = None
            if not self.web.valid(self._token(), local):
                device = self.web.devices.find(self._cookie_value(DEVICE_COOKIE), time.time())
                if device is None or not self.web.auth.remote_ready:
                    raise ApiError(401, "login required")
                self.web.devices.seen(device["id"], self.client_address[0], time.time())
                if path == "/api/logout":  # a phone signing out forgets its key
                    self.web.devices.remove(device["id"])
                    log.info("paired phone %s signed out", device["name"])
                    return self._json(200, {"ok": True}, {"Set-Cookie": f"{DEVICE_COOKIE}=; Max-Age=0; Path=/; SameSite=Strict"})
                if path == "/api/auth/change":
                    raise ApiError(403, "a paired phone can't change the password; use the server's computer")
            elif self._token() in self.web.first_sign_in and path not in FIRST_SIGN_IN_OK:
                raise ApiError(403, "choose your own password first (Craft Conductor settings → Sign-in)")
            if path == "/api/auth/change" and method == "POST":
                b = self._body()
                token = self.web.change(str(b.get("mode", "")), str(b.get("secret", "")), local)
                return self._json(200, {"ok": True, **self.web.auth.info()}, {"Set-Cookie": self._cookie(token)})
            if path == "/api/logout":
                self.web.logout(self._token())
                return self._json(200, {"ok": True},
                                  {"Set-Cookie": f"{SESSION_COOKIE}=; Max-Age=0; Path=/; SameSite=Strict"})
            q = {k: v[-1] for k, v in query.items()}
            if path in LOCAL_ONLY and not local:
                raise ApiError(403, "that only works in a browser on the server's own computer")
            handler = self.web.hub_api.routes.get((method, path))
            if handler is not None:
                if device and not device_allowed(method, path, device.get("role") or "helper"):
                    raise ApiError(403, "a paired phone can't do that; use the server's computer")
                if path not in NOTICE_EXEMPT and not notice.accepted(self.web.hub.root):
                    raise ApiError(428, "accept the notice first")
                if path in RAW_UPLOADS:
                    return self._json(200, handler(q, self))
                if path == "/api/hub/preview/map":  # a map preview's picture
                    return self._send(200, handler(q, {}), "image/png", {"Cache-Control": "private, max-age=86400"})
                if path == "/api/hub/map/tile":  # a square of an explorable map (the page adds ?v= when land is added)
                    return self._send(200, handler(q, {}), "image/png", {"Cache-Control": "private, max-age=3600"})
                body = self._body() if method == "POST" else {}
                if path in ("/api/hub/passkeys/options", "/api/hub/passkeys/add"):
                    body = {**body, "__rp": self._rp()}  # (from this request's address, not the page's say-so)
                result = handler(q, body)
                if path == "/api/hub":  # whether "Open folder" buttons can work; who's signed in
                    result = {**result, "local": local, "device": device["name"] if device else None,
                              "role": (device.get("role") or "helper") if device else "owner"}
                return self._json(200, result)
            if m := SERVER_PATH.match(path):
                sid, path = m.group(1), "/api" + m.group(2)
            elif only := self.web.hub.only():  # single server: the short URLs still work
                sid = only[0]
            else:
                raise ApiError(404, "not found")
            if path not in NOTICE_EXEMPT and not notice.accepted(self.web.hub.root):
                raise ApiError(428, "accept the notice first")
            if path in LOCAL_ONLY and not local:
                raise ApiError(403, "that only works in a browser on the server's own computer")
            if device and not device_allowed(method, path, device.get("role") or "helper"):
                raise ApiError(403, "a paired phone can't do that; use the server's computer")
            api = self.web.api_for(sid)
            set_current_server(api.d.server_id)  # so this server's activity feed shows what happens
            if device and method == "POST":
                log.info("paired phone %s: %s", device["name"], path.removeprefix("/api/"))
            handler = api.routes.get((method, path))
            if handler is None:
                raise ApiError(404, "not found")
            if path == "/api/manual/upload":
                return self._json(200, api.upload(self, q))
            if path in RAW_UPLOADS:
                return self._json(200, handler(q, self))
            if path == "/api/export/download":
                return self._send_file(api.export_file(q.get("name", "")))
            if path == "/api/modsets/export":
                entry = api.modset_export(q.get("name", ""))
                safe = re.sub(r"[^A-Za-z0-9._ -]+", "_", entry["name"]).strip() or "mods"
                return self._send(200, json.dumps(entry, indent=2).encode(), "application/json",
                                  {"Content-Disposition": f'attachment; filename="craft-conductor-mods-{safe}.json"'})
            if path == "/api/doctor/report":
                name = f"craft-conductor-report-{time.strftime('%Y%m%d-%H%M%S')}.zip"
                return self._send(200, api.doctor_report(), "application/zip",
                                  {"Content-Disposition": f'attachment; filename="{name}"'})
            if path == "/api/players/skin":
                try:
                    png = api.skins.png(q.get("name", ""))
                except SkinError as e:
                    raise ApiError(404, str(e)) from None
                return self._send(200, png, "image/png", {"Cache-Control": "private, max-age=3600"})
            body = self._body() if method == "POST" else {}
            if path == "/api/doctor/fix":
                body = {**body, "__local": local and device is None}  # (from this request, not the page's say-so)
            return self._json(200, handler(q, body))
        except ApiError as e:
            self._fail(e.status, str(e))
        except HttpError as e:  # a website craft-conductor depends on didn't answer
            log.warning("web request needed %s, which failed: %s", e.url, e)
            self._fail(502, e.friendly)
        except (ConfigError, ModError, Unavailable, JavaError, PlayerError, RuntimeError, ValueError, OSError) as e:
            self._fail(400, str(e))
        except Exception as e:  # pragma: no cover - last resort
            log.exception("web request failed")
            self._fail(500, f"internal error: {e}")

    def _fail(self, status: int, error: str) -> None:
        self._json(status, {"error": error})

    def _drain(self) -> None:
        """Before any answer: a small request body not read yet (a refused request, or one like
        /api/logout that needs none) is read first. Windows resets a connection closed with data
        still unread, and the browser then gets "connection reset" instead of the answer."""
        if self.command == "POST" and not self._body_read:
            self._body_read = True
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if 0 < length <= MAX_JSON:
                    self.rfile.read(length)
            except (ValueError, OSError):
                pass


def setup_options(mojang: Mojang) -> dict:
    """The choices on the setup page."""
    versions, betas, error = [], [], None
    try:
        versions = list(reversed(mojang.releases()))[:40]
        betas = mojang.betas()
    except Exception as e:  # offline: "latest" still works once the network is back
        error = f"couldn't load the list of Minecraft versions: {e}"
    total = setupmod.total_ram_gb()
    return {
        "loaders": [{"name": n, "label": label, "description": desc, "mods": mods}
                    for n, label, desc, mods in setupmod.LOADER_INFO],
        "versions": versions,
        "betas": betas,
        "versions_error": error,
        "total_ram_gb": round(total, 1) if total else None,
        "memory_gb": setupmod.suggested_memory_gb(total),
        "difficulties": setupmod.DIFFICULTIES,
        "gamemodes": setupmod.GAMEMODES,
        "properties_schema": serverprops.schema(),
    }


def newest_for_loader(http, mojang: Mojang, q: dict) -> dict:
    """What "Newest release" on the setup page means for a server type: the newest release it
    has a build for. The mods don't change it."""
    from .loaders import LOADERS, get_loader
    from .planner import newest_release
    loader = q.get("loader", "")
    if loader not in LOADERS:
        raise ApiError(400, "unknown server type")
    try:
        return {"loader": loader, "minecraft": newest_release(mojang, get_loader(loader, http, mojang))}
    except HttpError as e:
        raise ApiError(502, f"couldn't load the list of Minecraft versions: {e}") from None


def search_mods(provider: ModrinthProvider, q: dict, listed: set[str], default_loader: str,
                default_version: str | None = None) -> dict:
    """Modrinth search for the setup and Mods pages; with ``top=1`` and no query, the 20 most popular."""
    query = q.get("q", "").strip()
    top = q.get("top") == "1"
    if not query and not top:
        return {"results": []}
    loader_name = q.get("loader") or default_loader
    from .loaders import LOADERS
    if loader_name not in LOADERS:
        raise ApiError(400, "unknown loader")
    if not LOADERS[loader_name].mod_loaders:
        return {"results": []}  # vanilla: no mods
    version = q.get("version", default_version) or None  # only mods with a build for it
    if version and not re.fullmatch(r"[A-Za-z0-9.+-]{1,32}", version):
        raise ApiError(400, "bad Minecraft version")
    loaders = LOADERS[loader_name].mod_loaders
    results = provider.search(query, loaders, limit=20, index="relevance" if query else "downloads", minecraft=version)
    for r in results:
        r["listed"] = r["id"] in listed or r["slug"] in listed
    if not version:
        return {"results": results, "hidden": 0, "early_hidden": 0}
    # Only mods with a build for this loader *and* version (the search can't tell).
    return keep_buildable(provider.best_channels([r["id"] for r in results], loaders, version), results,
                          early=q.get("early") == "1")


def tailscale_ip() -> str | None:
    """This computer's Tailscale address, if Tailscale is installed and connected."""
    import shutil
    import subprocess
    from .desktop import NO_WINDOW
    exe = shutil.which("tailscale") or next((p for p in (r"C:\Program Files\Tailscale\tailscale.exe",
                                                         "/Applications/Tailscale.app/Contents/MacOS/Tailscale")
                                              if os.path.exists(p)), None)
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=4, **NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    ip = out.strip().splitlines()[0].strip() if out.strip() else ""
    try:
        return ip if ipaddress.ip_address(ip) in ipaddress.ip_network("100.64.0.0/10") else None
    except ValueError:
        return None


def early_channel(b: dict, mod: str) -> str | None:
    """The early channel a mod was picked with (``"channels": {mod: "beta"}``), if any."""
    channels = b.get("channels")
    value = channels.get(mod) if isinstance(channels, dict) else None
    return value if value in ("beta", "alpha") else None


def run_check(hub, b: dict, work) -> dict:
    """A quick mod check: in the background with ``"background": true`` (poll GET
    /api/hub/mods/check?id=...), otherwise answered straight away."""
    from . import trial
    if not b.get("background"):
        return work(None)
    hub.checks = {k: v for k, v in hub.checks.items() if v.state == "running" or time.time() - v.started < 600}
    if len(hub.checks) >= 20:
        raise ApiError(429, "too many checks at once; wait for one to finish")
    job = trial.CheckJob(work).start()
    hub.checks[job.id] = job
    return {"ok": True, "id": job.id}


_RELEASE = re.compile(r"\d+(\.\d+)+")


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in version.split("."))


def mod_requirements(provider: ModrinthProvider, mod_id: str, loaders: tuple[str, ...], minecraft: str | None,
                     channel: str = "release", limit: int = 30, curseforge=None) -> dict:
    """Whether a mod has a build for ``minecraft`` (any version when None), and the mods it needs
    (their dependencies too), so pickers can select them along with it. ``mod_id`` is a Modrinth
    mod, or with ``curseforge`` (the CurseForge provider) also ``curseforge:<id>``.

    The Minecraft version and loaders are fixed: a mod the picked one needs is looked for on the
    site that names it, then (with ``curseforge``) as the same mod on the other site. When one
    can't be found on either, the answer says which chain of mods needs it, where it looked, and
    which Minecraft versions appear to work instead (``suggestions``, never applied here)."""
    from .mods.base import SOURCE_NAMES, ModFile, not_checked, same_project
    from .planner import LOADER_NAMES
    sites = {"modrinth": provider}
    if curseforge is not None and curseforge.handles(loaders):
        sites["curseforge"] = curseforge
    loader_name = LOADER_NAMES.get(loaders[0], loaders[0]) if loaders else ""

    def newest(project_id: str):
        ok = [v for v in provider._versions(project_id, loaders, minecraft) if provider._acceptable(v, channel)
              and (minecraft is None or minecraft in v.get("game_versions", []))]
        return max(ok, key=lambda v: v.get("date_published", "")) if ok else None

    def build(source: str, project) -> dict | None:
        """The build of ``project`` that would be used: what it needs, and its channel; or None."""
        if source == "modrinth":
            version = newest(project.id)
            return None if version is None else {
                "deps": [("modrinth", x) for x in provider.required_projects(version)],
                "channel": version.get("version_type", "release")}
        spec = ModSpec(source, project.id)
        version = minecraft
        if version is None:  # any version: its newest one
            found = sorted((v for v in sites[source].supported_versions(spec, loaders, channel) if _RELEASE.fullmatch(v)),
                           key=_version_key)
            if not found:
                return None
            version = found[-1]
        try:
            f: ModFile = sites[source].resolve(spec, version, loaders, channel)
        except Unavailable:
            return None
        return {"deps": [(source, x) for x in f.dependencies], "channel": None}

    same: dict[tuple[str, str], Any] = {}

    def counterpart(project, source: str):
        if (project.key, source) not in same:
            same[(project.key, source)] = sites[source].find_same(project)
        return same[(project.key, source)]

    def anywhere(source: str, project, checked: list[str], unchecked: list[str]):
        """(project, site, build) where a build was found, the site that names it first."""
        checked.append(SOURCE_NAMES.get(source, source))
        found = build(source, project)
        if found is not None:
            return project, source, found
        for other_source in [s for s in sites if s != source]:
            name = SOURCE_NAMES.get(other_source, other_source)
            try:
                other = counterpart(project, other_source)
            except ModError as e:
                unchecked.append(not_checked(sites[other_source], e))
                continue
            checked.append(name)
            if other is not None:
                found = build(other_source, other)
                if found is not None:
                    return other, other_source, found
        return None

    def suggestions(chain: list) -> list[str]:
        """Releases every mod in ``chain`` ((site, project), the picked mod first) has a build for."""
        common: set[str] | None = None
        for i, (source, project) in enumerate(chain):
            versions = set()
            options = [(source, project)]
            if i:  # (the picked mod comes from where it was picked; what it needs, from either site)
                for other_source in [s for s in sites if s != source]:
                    try:
                        other = counterpart(project, other_source)
                    except ModError:
                        other = None
                    if other is not None:
                        options.append((other_source, other))
            for site, proj in options:
                try:
                    versions |= sites[site].supported_versions(ModSpec(site, proj.id), loaders, channel)
                except (ModError, HttpError):
                    pass
            common = versions if common is None else common & versions
        found = [v for v in (common or set()) if _RELEASE.fullmatch(v) and v != minecraft]
        return sorted(found, key=_version_key, reverse=True)[:3]

    root_source, root_id = ("curseforge", mod_id.split(":", 1)[1]) if mod_id.startswith("curseforge:") else ("modrinth", mod_id)
    if root_source not in sites:
        raise ModError("CurseForge mods need a CurseForge API key")
    project = sites[root_source].project(root_id)
    info = {"id": project.id, "slug": project.slug, "name": project.name, "source": root_source}
    base = {"project": info, "minecraft": minecraft, "loader": loader_name, "chain": [], "checked": [], "suggestions": []}
    root = build(root_source, project)
    if root is None:
        where = f"Minecraft {minecraft}" if minecraft else "this server type"
        return {**base, "compatible": False, "reason": f"{project.name} has no build for {where}", "deps": [],
                "companions": [], "chain": [project.name], "checked": [SOURCE_NAMES.get(root_source, root_source)],
                "suggestions": suggestions([(root_source, project)]) if minecraft else []}
    base["channel"] = root.get("channel") or "release"
    deps, companions = [], []
    seen, seen_projects = {project.key}, [project]
    queue = [(src, pid, [(root_source, project)]) for src, pid in root["deps"]]
    failure = None
    while queue and len(seen) < limit:
        source, pid, chain = queue.pop(0)
        if f"{source}:{pid}" in seen:
            continue
        seen.add(f"{source}:{pid}")
        needed_by = chain[-1][1].name
        try:
            dep = sites[source].project(pid) if source in sites else None
        except ModError as e:
            dep, error = None, e
        else:
            error = ModError("CurseForge mods need a CurseForge API key") if dep is None else None
        if dep is None:
            return {**base, "compatible": False, "reason": f"couldn't check a required mod: {error}",
                    "deps": deps, "companions": companions}
        if any(same_project(dep, other) for other in seen_projects if other.source != dep.source):
            continue  # the same mod, already here from the other site
        seen.add(dep.key)
        seen_projects.append(dep)
        if dep.server_side == "unsupported":  # only players need it: it goes in friends' downloads
            companions.append({"id": dep.id, "slug": dep.slug, "name": dep.name, "needed_by": needed_by})
            continue
        checked, unchecked = [], []
        hit = anywhere(source, dep, checked, unchecked)
        used, used_source, found = hit if hit else (dep, source, None)
        if used.server_side == "unsupported":
            companions.append({"id": used.id, "slug": used.slug, "name": used.name, "needed_by": needed_by})
            continue
        if used is not dep:
            seen.add(used.key)
            seen_projects.append(used)
        deps.append({"id": used.id, "slug": used.slug, "name": used.name, "needed_by": needed_by, "source": used_source,
                     "compatible": found is not None, "channel": found["channel"] if found else None,
                     "checked": checked})
        if found is None:
            if failure is None:
                failure = (chain + [(source, dep)], checked, unchecked)
            continue
        queue += [(src, x, chain + [(used_source, used)]) for src, x in found["deps"]]
    if queue:
        return {**base, "compatible": False, "reason": "too many required mods to check; check this set before installing",
                "deps": deps, "companions": companions}
    if failure is None:
        return {**base, "compatible": True, "deps": deps, "companions": companions, "reason": ""}
    chain, checked, unchecked = failure
    names = [p.name for _, p in chain]
    needs = "".join(f", which requires {n}" for n in names[2:])
    reason = (f"{names[0]} requires {names[1]}{needs}, but no compatible {names[-1]} release was found for "
              f"Minecraft {minecraft} using {loader_name}." if minecraft else
              f"{names[0]} requires {names[1]}{needs}, which has no build for this server type.")
    reason += f" Craft Conductor checked {' and '.join(checked)}" + (f" ({'; '.join(unchecked)})" if unchecked else "") + "."
    return {**base, "compatible": False, "deps": deps, "companions": companions, "reason": reason, "chain": names,
            "checked": checked, "suggestions": suggestions(chain) if minecraft else []}


def requirements_query(provider: ModrinthProvider, q: dict, manager=None, curseforge=None) -> dict:
    from .loaders import LOADERS
    mod_id = q.get("id", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}|curseforge:\d{1,10}", mod_id):
        raise ApiError(400, "bad mod id")
    loader = q.get("loader") or (manager.config.server.loader if manager else "")
    if loader not in LOADERS or not LOADERS[loader].mod_loaders:
        raise ApiError(400, "that server type doesn't run mods")
    version = q.get("version")
    if version is None and manager is not None:
        version = manager.lock.minecraft
    channel = manager.config.updates.mod_channel if manager else "release"
    try:
        return mod_requirements(provider, mod_id, LOADERS[loader].mod_loaders, version or None, curseforge=curseforge,
                                channel=lowest(channel, q.get("channel") if q.get("channel") in ("beta", "alpha") else None))
    except ModError as e:
        raise ApiError(400, str(e)) from None


def browse_search(browser, q: dict, manager=None) -> dict:
    from .browse import BrowseError
    kind = q.get("type", "mod")
    loader = q.get("loader") or (manager.config.server.loader if manager else None)
    if loader == "vanilla":
        loader = None
    version = q.get("version")
    if version is None and manager is not None:
        version = manager.lock.minecraft or None
    try:
        return browser.search(q.get("source", "modrinth"), kind, q.get("q", "").strip()[:100], loader or None,
                              version or None, q.get("category") or None, q.get("sort", "relevance"),
                              int(q.get("offset", 0) or 0), early=q.get("early") == "1",
                              side="client" if q.get("side") == "client" else "server", env=q.get("env", ""))
    except BrowseError as e:
        raise ApiError(400, str(e)) from None


def browse_project(browser, q: dict) -> dict:
    from .browse import BrowseError
    pid = q.get("id", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", pid):
        raise ApiError(400, "bad project id")
    try:
        return browser.project(q.get("source", "modrinth"), pid)
    except BrowseError as e:
        raise ApiError(400, str(e)) from None


def browse_categories(browser, q: dict) -> dict:
    from .browse import BrowseError
    try:
        return {"categories": browser.categories(q.get("source", "modrinth"), q.get("type", "mod")),
                "sources": browser.sources}
    except BrowseError as e:
        raise ApiError(400, str(e)) from None


class HubApi:
    """The parts of the API that aren't about one server: the server list, new servers,
    the first-run notice, licenses and craft-conductor's own updates."""

    def __init__(self, web: WebUI):
        self.web = web
        self.hub = web.hub
        self._mojang: Mojang | None = None
        r: dict[tuple[str, str], Callable[[dict, dict], Any]] = {}
        r[("GET", "/api/hub")] = self.overview
        r[("GET", "/api/hub/setup")] = self.new_server_options
        r[("GET", "/api/hub/setup/newest")] = lambda q, b: newest_for_loader(self.hub.http, self._get_mojang(), q)
        r[("GET", "/api/hub/mods/requires")] = lambda q, b: requirements_query(
            ModrinthProvider(self.hub.http), q, curseforge=CurseForgeProvider(self.hub.http, self.curseforge_key_now()))
        r[("GET", "/api/hub/mods/search")] = lambda q, b: search_mods(ModrinthProvider(self.hub.http), q, set(), "fabric")
        r[("GET", "/api/hub/modpack/preview")] = self.modpack_preview
        r[("POST", "/api/hub/create")] = self.create
        r[("POST", "/api/hub/remote-install")] = self.remote_install
        r[("POST", "/api/hub/remote-install/open")] = self.remote_install_open
        r[("POST", "/api/hub/network")] = self.network
        r[("POST", "/api/hub/share")] = self.save_share
        r[("GET", "/api/hub/port")] = self.port_check
        r[("POST", "/api/hub/stage")] = self.stage
        r[("POST", "/api/hub/open")] = self.open_folder
        r[("POST", "/api/hub/quit")] = self.quit
        r[("GET", "/api/hub/curseforge")] = self.curseforge_info
        r[("POST", "/api/hub/curseforge")] = self.save_curseforge
        r[("POST", "/api/hub/share/public-ip")] = self.use_public_ip
        r[("GET", "/api/hub/remote")] = self.remote_info
        r[("GET", "/api/hub/conflicts")] = self.conflicts_info
        r[("POST", "/api/hub/conflicts")] = self.save_conflicts
        r[("GET", "/api/hub/passkeys")] = self.passkey_list
        r[("POST", "/api/hub/passkeys/options")] = self.passkey_options
        r[("POST", "/api/hub/passkeys/add")] = self.passkey_add
        r[("POST", "/api/hub/passkeys/remove")] = self.passkey_remove
        r[("POST", "/api/hub/remote/tls")] = self.save_tls
        r[("POST", "/api/hub/devices/pair")] = self.pair_device
        r[("POST", "/api/hub/devices/remove")] = self.remove_device
        r[("POST", "/api/hub/devices/cancel-pairing")] = self.cancel_pairing
        r[("GET", "/api/hub/discord")] = self.discord_info
        r[("POST", "/api/hub/discord")] = self.save_discord
        r[("GET", "/api/hub/discord/guilds")] = lambda q, b: {"guilds": self._discord().guilds()}
        r[("GET", "/api/hub/discord/channels")] = lambda q, b: {"channels": self._discord().channels(q.get("guild", ""))}
        r[("POST", "/api/hub/discord/status")] = self.discord_status
        r[("GET", "/api/hub/memory")] = lambda q, b: self.hub.memory_plan(q.get("adding") or None)
        r[("GET", "/api/hub/discord/roles")] = lambda q, b: {"roles": self._discord().roles(q.get("guild", ""))}
        r[("POST", "/api/hub/discord/whitelist")] = self.discord_whitelist
        r[("POST", "/api/hub/mods/check")] = self.check_mods
        r[("GET", "/api/hub/mods/check")] = self.check_status
        r[("POST", "/api/hub/trial")] = self.start_trial
        r[("GET", "/api/hub/trial")] = self.trial_status
        r[("POST", "/api/hub/trial/cancel")] = self.cancel_trial
        r[("GET", "/api/hub/upnp")] = lambda q, b: self.hub.upnp_status()
        r[("POST", "/api/hub/upnp")] = self.set_upnp
        r[("POST", "/api/hub/preview")] = self.start_preview
        r[("GET", "/api/hub/preview")] = self.preview_status
        r[("GET", "/api/hub/preview/map")] = self.preview_map
        r[("POST", "/api/hub/preview/cancel")] = self.cancel_preview
        r[("POST", "/api/hub/preview/gallery")] = self.start_gallery
        r[("GET", "/api/hub/preview/gallery")] = self.gallery_status
        r[("POST", "/api/hub/preview/gallery/cancel")] = self.cancel_gallery
        r[("GET", "/api/hub/map")] = self.map_info
        r[("GET", "/api/hub/map/tile")] = self.map_tile
        r[("GET", "/api/hub/map/biome")] = self.map_biome
        r[("POST", "/api/hub/map/explore")] = self.map_explore
        r[("POST", "/api/hub/map/stop")] = self.map_stop
        r[("GET", "/api/hub/saves")] = self.saves
        r[("POST", "/api/hub/import")] = lambda q, b: {"ok": True, "id": self.hub.import_server(str(b.get("id", "")))}
        r[("GET", "/api/hub/browse/search")] = lambda q, b: browse_search(self.browser(), q)
        r[("GET", "/api/hub/browse/project")] = lambda q, b: browse_project(self.browser(), q)
        r[("GET", "/api/hub/browse/categories")] = lambda q, b: browse_categories(self.browser(), q)
        r[("POST", "/api/hub/delete")] = lambda q, b: {
            "ok": True, "message": self.hub.delete(str(b.get("id", "")), b.get("delete_files") is True)}
        r[("GET", "/api/notice")] = lambda q, b: {"accepted": notice.accepted(self.hub.root), "version": notice.NOTICE_VERSION,
                                                  "title": notice.TITLE, "points": notice.POINTS}
        r[("POST", "/api/notice/accept")] = self.accept_notice
        r[("GET", "/api/hub/guide")] = self.guide_status
        r[("GET", "/api/hub/phone")] = self.phone_info
        r[("POST", "/api/hub/phone/subscribe")] = self.phone_subscribe
        r[("POST", "/api/hub/phone/unsubscribe")] = self.phone_unsubscribe
        r[("POST", "/api/hub/phone/test")] = self.phone_test
        r[("POST", "/api/hub/phone/prefs")] = self.phone_prefs
        r[("POST", "/api/hub/phone/remove")] = self.phone_remove
        r[("POST", "/api/hub/phone/tailscale")] = self.phone_tailscale
        r[("GET", "/api/hub/singleplayer")] = self.sp_list
        r[("POST", "/api/hub/singleplayer")] = self.sp_create
        r[("POST", "/api/hub/singleplayer/edit")] = self.sp_edit
        r[("POST", "/api/hub/singleplayer/delete")] = self.sp_delete
        r[("POST", "/api/hub/singleplayer/check")] = self.sp_check
        r[("POST", "/api/hub/singleplayer/preview")] = self.sp_preview
        r[("POST", "/api/hub/singleplayer/install")] = self.sp_install
        r[("POST", "/api/hub/guide")] = self.guide_action
        r[("GET", "/api/licenses")] = lambda q, b: licenses.as_dict()
        r[("POST", "/api/self-update/check")] = lambda q, b: {"ok": True, "message": self.hub.check_self_update()}
        r[("POST", "/api/self-update/apply")] = self.apply_self_update
        r[("POST", "/api/self-update/channel")] = self.set_update_channel
        self.routes = r

    def overview(self, q, b) -> dict:
        hub = self.hub
        return {
            "version": __version__,
            "single": hub.is_single,
            "notice_accepted": notice.accepted(hub.root),
            "self_update": hub.self_update_info(),
            "update_channel": hub.update_channel(),
            "auth": self.web.auth.info(),
            "home": str(hub.home),
            "network_access": hub.web.host in ("0.0.0.0", "::"),
            "servers": hub.summary(),
            "share": hub.share_status() if not hub.is_single else None,
            "guide": None if hub.is_single else self._guide_state(),
            "health": hub._health.warnings if getattr(hub, "_health", None) else [],  # (checked every minute: health.py)
        }

    def modpack_preview(self, q, b) -> dict:
        """The mods a selected Modrinth modpack would add, for the setup management drawer."""
        from . import modpack
        try:
            return modpack.preview(self.hub.http, str(q.get("version", "")))
        except (ModError, HttpError) as e:
            raise ApiError(400 if isinstance(e, ModError) else 502, str(e)) from None

    # ------------------------------------------- modded single-player games
    def _sp(self):
        from . import singleplayer
        if self.hub.is_single:
            raise ApiError(400, "single-player games need the full Craft Conductor (not `craft-conductor run`)")
        return singleplayer

    def sp_list(self, q, b) -> dict:
        sp = self._sp()
        return {"games": sp.games(self.hub), "loaders": list(sp.LOADERS)}

    def sp_create(self, q, b) -> dict:
        sp = self._sp()
        try:
            return sp.create(self.hub, name=b.get("name"), loader=b.get("loader"), minecraft=b.get("minecraft"),
                             mods=b.get("mods") or [], memory_gb=b.get("memory_gb"))
        except sp.SingleplayerError as e:
            raise ApiError(400, str(e)) from None

    def sp_edit(self, q, b) -> dict:
        sp = self._sp()
        try:
            game = sp.load(self.hub, str(b.get("id", "")))
            recipe = sp.check_recipe(b.get("name", game["name"]), b.get("loader", game["loader"]),
                                     b.get("minecraft", game["minecraft"]), b.get("mods", game["mods"]),
                                     b.get("memory_gb", game["memory_gb"]))
            if recipe["loader"] != game["loader"] and game.get("installed"):
                raise sp.SingleplayerError("a game's mod loader can't change once it's installed: make a new game instead")
            return sp.save(self.hub, {**game, **recipe})
        except sp.SingleplayerError as e:
            raise ApiError(400, str(e)) from None

    def sp_delete(self, q, b) -> dict:
        sp = self._sp()
        try:
            sp.load(self.hub, str(b.get("id", "")))
            sp.delete(self.hub, str(b.get("id", "")))
        except sp.SingleplayerError as e:
            raise ApiError(404, str(e)) from None
        return {"ok": True}

    def _sp_pack(self, game_id: str) -> tuple[dict, dict]:
        sp = self._sp()
        try:
            game = sp.load(self.hub, game_id)
            return game, sp.resolve(self.hub, game)
        except sp.SingleplayerError as e:
            raise ApiError(400, str(e)) from None
        except HttpError as e:
            raise ApiError(502, f"couldn't reach Modrinth or Mojang: {e.friendly}") from None

    @staticmethod
    def _sp_mods(pack: dict) -> list[dict]:
        """Display-safe resolved mod metadata shared by single-player check and preview."""
        def one(m, manual=False):
            return {"name": m["name"], "project": m.get("project"), "source": m.get("source", "modrinth"),
                    "version": m.get("version", ""), "channel": m.get("channel", "release"),
                    "needed_by": m.get("needed_by"), "selected": bool(m.get("selected")),
                    "requested": m.get("requested"), "manual": manual}
        return [one(m) for m in pack["mods"]] + [one(m, True) for m in pack["manual"]]

    def sp_check(self, q, b) -> dict:
        """What installing (or updating) the game now would put in."""
        sp = self._sp()
        game, pack = self._sp_pack(str(b.get("id", "")))
        return {"id": game["id"], "minecraft": pack["minecraft"], "loader": pack["loader"],
                "loader_version": pack["loader_version"], "changes": sp.changes(game.get("installed"), pack),
                "skipped": pack["skipped"], "manual": pack["manual"], "mods": self._sp_mods(pack)}

    def sp_preview(self, q, b) -> dict:
        """Resolve unsaved single-player choices so the editor can show dependencies and versions."""
        sp = self._sp()
        try:
            recipe = sp.check_recipe(str(b.get("name") or "Preview"), b.get("loader"), b.get("minecraft"),
                                     b.get("mods") or [], b.get("memory_gb") or 4)
            pack = sp.resolve(self.hub, recipe)
        except sp.SingleplayerError as e:
            raise ApiError(400, str(e)) from None
        except HttpError as e:
            raise ApiError(502, f"couldn't reach Modrinth or Mojang: {e.friendly}") from None
        return {"minecraft": pack["minecraft"], "loader": pack["loader"], "loader_version": pack["loader_version"],
                "skipped": pack["skipped"], "mods": self._sp_mods(pack)}

    def sp_install(self, q, b) -> dict:
        """Put the game into this computer's launchers (the same page friends use to join), and keep
        a note of what went in. Only from a browser on this computer (LOCAL_ONLY)."""
        from . import joinui
        sp = self._sp()
        game, pack = self._sp_pack(str(b.get("id", "")))
        old = getattr(self.hub, "_play_ui", None)
        if old is not None and not old.done.is_set():
            old.stop()
        ui = joinui.JoinUI(None, pack=pack, http=self.hub.http)
        url = ui.start()
        self.hub._play_ui = ui
        hub = self.hub

        def run():
            noted = None

            def note():  # as soon as a launcher has it (the page may stay open a while)
                nonlocal noted
                ok = [r for r in ui.results if r.get("ok")]
                if ok and noted is not ui.results:
                    noted = ui.results
                    fresh = sp.load(hub, game["id"])
                    sp.save(hub, {**fresh, "installed": sp.summary(pack), "launchers": sorted({r["launcher"] for r in ok})})
            try:
                while not ui.done.wait(2):
                    note()
                    if not ui.running and time.monotonic() - ui.last_seen > joinui.IDLE_SECONDS:
                        break
                note()
            except sp.SingleplayerError:
                pass  # (the game was deleted meanwhile)
            finally:
                ui.stop()
        threading.Thread(target=run, daemon=True, name="singleplayer-install").start()
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
        return {"ok": True, "url": url}

    # ------------------------------------------------- the phone app (push)
    def _port(self) -> int:
        return self.web.httpd.server_address[1] if self.web.httpd else self.web.port

    def phone_info(self, q, b) -> dict:
        from . import tailscale
        ts = tailscale.status(self._port()) if q.get("tailscale") == "1" else None
        if ts and ts["serving"]:
            self._allow_host(ts["name"])  # (it's offered as the secure address)
        return {"public_key": self.hub.push.public_key(), "devices": self.hub.push.subscriptions(),
                "tailscale": ts, "secure_url": f"https://{ts['name']}/" if ts and ts["serving"] and ts["name"] else None,
                "strong": self.web.auth.remote_ready}

    def phone_subscribe(self, q, b) -> dict:
        from .push import PushError
        keys = b.get("keys") if isinstance(b.get("keys"), dict) else {}
        try:
            sub = self.hub.push.subscribe(b.get("endpoint"), keys.get("p256dh", ""), keys.get("auth", ""), b.get("name", ""))
        except PushError as e:
            raise ApiError(400, str(e)) from None
        return {"ok": True, "device": sub}

    def phone_unsubscribe(self, q, b) -> dict:
        return {"ok": True, "removed": self.hub.push.unsubscribe(endpoint=str(b.get("endpoint", "")))}

    def phone_test(self, q, b) -> dict:
        """A test notification to this device (it names itself by its push address)."""
        endpoint = str(b.get("endpoint", ""))
        with self.hub.push.lock:
            match = [s["id"] for s in self.hub.push._load().get("subscriptions", []) if s["endpoint"] == endpoint]
        if not match:
            raise ApiError(404, "notifications aren't on for this device")
        results = self.hub.push.send_now({"title": "Craft Conductor", "body": "Notifications work on this device.",
                                          "url": "/", "tag": "test"}, only=match[0])
        return {"ok": all(r["ok"] for r in results), "results": results}

    def phone_prefs(self, q, b) -> dict:
        """Which notifications this device gets (it names itself by its push address); with
        "kinds", change them."""
        from .push import KINDS, PushError
        endpoint = str(b.get("endpoint", ""))
        try:
            if "kinds" in b:
                if not isinstance(b["kinds"], list):
                    raise ApiError(400, "kinds must be a list")
                kinds = self.hub.push.set_kinds(endpoint, b["kinds"])
            else:
                kinds = self.hub.push.kinds_for(endpoint)
        except PushError as e:
            raise ApiError(404, str(e)) from None
        if kinds is None:
            raise ApiError(404, "notifications aren't on for this device")
        return {"kinds": kinds, "all": KINDS}

    def phone_remove(self, q, b) -> dict:
        n = self.hub.push.unsubscribe(sub_id=str(b.get("id", "")))
        if not n:
            raise ApiError(404, "no such device")
        return {"ok": True, "devices": self.hub.push.subscriptions()}

    def phone_tailscale(self, q, b) -> dict:
        """Reach the control panel over trusted HTTPS with Tailscale (the phone app needs it), or stop."""
        from . import tailscale
        if self.hub.is_single:
            raise ApiError(400, "the phone app needs the full Craft Conductor (not `craft-conductor run`)")
        port = self._port()
        if b.get("on") is False:
            tailscale.unserve()
            return {"ok": True, "tailscale": tailscale.status(port)}
        if not self.web.auth.remote_ready:
            raise ApiError(400, "first set a strong password (" + webauth.STRONG_RULES + "): the phone signs in from another device")
        st = tailscale.status(port)
        if not st["installed"]:
            raise ApiError(400, "Tailscale isn't installed on this computer: get it from tailscale.com/download, sign in, then try again")
        if not st["running"] or not st["name"]:
            raise ApiError(400, "Tailscale is installed but not signed in and connected on this computer")
        r = tailscale.serve(port)
        if not r["ok"]:
            return {"ok": False, "message": r["message"], "enable_url": r["enable_url"], "tailscale": st}
        self._allow_host(st["name"])
        log.info("the control panel is on %s over HTTPS (Tailscale)", st["name"])
        return {"ok": True, "url": f"https://{st['name']}/", "tailscale": tailscale.status(port)}

    def _allow_host(self, name: str) -> None:
        """Let the control panel answer at this host name (Tailscale's address for this computer)."""
        if name and name not in self.hub.web.allowed_hosts:
            self.hub.save_web(allowed_hosts=sorted({*self.hub.web.allowed_hosts, name}))

    def _guide_state(self) -> dict:
        from . import guide
        g = guide.state(self.hub)
        # Someone who already has a server doesn't need to be offered it (Help still starts it).
        has_server = any(not d.setup_pending for d in list(self.hub.daemons.values()))
        return {"asked": g["asked"] or has_server, "active": g["active"]}

    def guide_status(self, q, b) -> dict:
        from . import guide
        if self.hub.is_single:
            raise ApiError(400, "the guided setup needs the full Craft Conductor (not `craft-conductor run`)")
        return guide.steps(self.hub)

    def guide_action(self, q, b) -> dict:
        """Start, skip or stop the guided setup, or tick a step craft-conductor can't see by itself."""
        from . import guide
        if self.hub.is_single:
            raise ApiError(400, "the guided setup needs the full Craft Conductor (not `craft-conductor run`)")
        action, step = str(b.get("action", "")), str(b.get("step", ""))
        g = guide.state(self.hub)
        if action == "start":
            guide.save(self.hub, asked=True, active=True)
        elif action in ("skip", "stop"):
            guide.save(self.hub, asked=True, active=False)
        elif action in ("tick", "untick") and step in guide.MANUAL:
            ticked = set(g["ticked"]) | {step} if action == "tick" else set(g["ticked"]) - {step}
            guide.save(self.hub, ticked=sorted(ticked))
        else:
            raise ApiError(400, "start, skip, stop, or tick a step")
        return guide.steps(self.hub)

    def browser(self):
        from .browse import Browser
        return Browser(self.hub.http, self.hub.curseforge_key() if not self.hub.is_single else
                       os.environ.get("CRAFT_CONDUCTOR_CURSEFORGE_API_KEY", ""))

    # ------------------------------------------------ try before you buy
    def check_mods(self, q, b) -> dict:
        """The instant check: builds for this version, required mods, declared conflicts."""
        from . import trial
        from .loaders import LOADERS
        loader = str(b.get("loader", ""))
        if loader not in LOADERS or not LOADERS[loader].mod_loaders:
            raise ApiError(400, "that server type doesn't run mods")
        mods = [str(x) for x in (b.get("mods") or []) if re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", str(x))]
        minecraft = str(b.get("minecraft") or "") or None
        provider = ModrinthProvider(self.hub.http)
        channels = {m: early_channel(b, m) for m in mods if early_channel(b, m)}
        return run_check(self.hub, b, lambda progress: trial.check(provider, LOADERS[loader].mod_loaders, minecraft, mods,
                                                                    progress=progress, channels=channels))

    def check_status(self, q, b) -> dict:
        job = self.hub.checks.get(q.get("id", ""))
        if job is None:
            raise ApiError(404, "that check isn't running any more")
        return job.to_dict()

    def start_trial(self, q, b) -> dict:
        """A test boot of a set of mods, in a throwaway server; ``bisect`` finds culprits."""
        from . import trial
        if any(t.state == "running" for t in self.hub.trials.values()):
            raise ApiError(409, "a test is already running; wait for it or stop it")
        sid = b.get("server")
        if sid:  # the mods of an existing server
            d = self.hub.get(str(sid))
            if d is None:
                raise ApiError(404, "no such server")
            cfg = d.m.config
            loader = cfg.server.loader
            minecraft = d.m.lock.minecraft or cfg.server.minecraft
            mods = [ModSpec(s.source, s.id, channel=s.channel) for s in cfg.mods]
        else:
            loader = str(b.get("loader", ""))
            minecraft = str(b.get("minecraft") or "latest")
            items = b.get("mods") or []
            if not isinstance(items, list) or len(items) > 200:
                raise ApiError(400, "pick up to 200 mods")
            mods = []
            for item in items:
                source, _, mod_id = str(item).partition(":") if ":" in str(item) else ("modrinth", "", str(item))
                if source not in configmod.MOD_SOURCES or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", mod_id):
                    raise ApiError(400, f"{item!r} isn't a mod id")
                mods.append(ModSpec(source, mod_id, channel=early_channel(b, str(item))))
        if loader not in configmod.LOADERS or loader == "vanilla" and mods:
            raise ApiError(400, "pick a server type that runs mods")
        t = trial.Trial(self.hub, loader, minecraft, mods, bisect=bool(b.get("bisect")))
        self.hub.trials = {k: v for k, v in self.hub.trials.items() if v.state == "running"}  # forget old ones
        self.hub.trials[t.id] = t.start()
        return {"ok": True, "id": t.id}

    def trial_status(self, q, b) -> dict:
        t = self.hub.trials.get(q.get("id", ""))
        if t is None:
            raise ApiError(404, "that test isn't running any more")
        return t.to_dict(int(q.get("since", 0) or 0))

    def cancel_trial(self, q, b) -> dict:
        t = self.hub.trials.get(str(b.get("id", "")))
        if t is None:
            raise ApiError(404, "that test isn't running any more")
        t.cancel.set()
        return {"ok": True}

    # ------------------------------------------- router port forwarding
    def set_upnp(self, q, b) -> dict:
        """Switch automatic port forwarding on or off (``refresh`` re-checks it)."""
        if self.hub.is_single:
            raise ApiError(400, "automatic port forwarding needs the full Craft Conductor (not `craft-conductor run`)")
        enabled = b.get("enabled")
        if enabled is not None and not isinstance(enabled, bool):
            raise ApiError(400, "enabled must be true or false")
        self._upnp_consent(enabled, b)
        status = self.hub.upnp_sync(enabled)
        log.info("automatic port forwarding %s", "on" if status["enabled"] else "off")
        return status

    def _upnp_consent(self, enabled: bool | None, b: dict) -> None:
        """Opening the router is the owner's decision, made knowing what it means: switching it on
        needs ``accept`` (the page asks first, showing upnp.EXPOSURE_WARNING)."""
        from .upnp import EXPOSURE_WARNING
        if enabled is True and not self.hub.upnp_settings()["enabled"] and b.get("accept") is not True:
            raise ApiError(400, f"confirm first: {EXPOSURE_WARNING}")

    # ---------------------------------------------------- map previews
    def start_preview(self, q, b) -> dict:
        """A map of a seed with these mods: a throwaway server makes the world (see preview.py)."""
        from . import preview
        self._previews_idle()
        loader = str(b.get("loader", ""))
        if loader not in configmod.LOADERS:
            raise ApiError(400, "pick a server type")
        items = b.get("mods") or []
        if not isinstance(items, list) or len(items) > 200:
            raise ApiError(400, "pick up to 200 mods")
        mods = []
        for item in items:
            source, _, mod_id = str(item).partition(":") if ":" in str(item) else ("modrinth", "", str(item))
            if source not in configmod.MOD_SOURCES or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", mod_id):
                raise ApiError(400, f"{item!r} isn't a mod id")
            mods.append(ModSpec(source, mod_id, channel=early_channel(b, str(item))))
        if loader == "vanilla" and mods:
            raise ApiError(400, "pick a server type that runs mods")
        try:
            radius = int(b.get("radius", 256))
            p = preview.Preview(self.hub, loader, str(b.get("minecraft") or "latest"), mods, str(b.get("seed") or ""),
                                str(b.get("level_type") or "minecraft:normal"), bool(b.get("structures", True)), radius)
        except (TypeError, ValueError) as e:
            raise ApiError(400, str(e) or "check the map settings") from None
        keep = {k: v for k, v in self.hub.previews.items() if v.state == "done"}
        self.hub.previews = {**dict(list(keep.items())[-preview.KEEP:]), p.id: p.start()}
        return {"ok": True, "id": p.id, "seed": p.seed}

    def _previews_idle(self) -> None:
        if any(p.state == "running" for p in self.hub.previews.values()) or \
                (self.hub.gallery is not None and self.hub.gallery.state == "running"):
            raise ApiError(409, "a map is already being made; wait for it or stop it")
        if any(t.state == "running" for t in self.hub.trials.values()):
            raise ApiError(409, "a mod test is running; try again when it's finished")

    def start_gallery(self, q, b) -> dict:
        """Maps of several random seeds side by side (see preview.Gallery)."""
        from . import preview
        self._previews_idle()
        loader = str(b.get("loader", ""))
        if loader not in configmod.LOADERS:
            raise ApiError(400, "pick a server type")
        items = b.get("mods") or []
        if not isinstance(items, list) or len(items) > 200:
            raise ApiError(400, "pick up to 200 mods")
        mods = []
        for item in items:
            source, _, mod_id = str(item).partition(":") if ":" in str(item) else ("modrinth", "", str(item))
            if source not in configmod.MOD_SOURCES or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", mod_id):
                raise ApiError(400, f"{item!r} isn't a mod id")
            mods.append(ModSpec(source, mod_id, channel=early_channel(b, str(item))))
        if loader == "vanilla" and mods:
            raise ApiError(400, "pick a server type that runs mods")
        count = b.get("count", preview.GALLERY_MAX)
        if not isinstance(count, int) or isinstance(count, bool):
            raise ApiError(400, f"compare 2 to {preview.GALLERY_MAX} seeds")
        try:
            g = preview.Gallery(self.hub, count, loader=loader, minecraft=str(b.get("minecraft") or "latest"), mods=mods,
                                level_type=str(b.get("level_type") or "minecraft:normal"),
                                structures=bool(b.get("structures", True)), radius=int(b.get("radius", 128)))
        except (TypeError, ValueError) as e:
            raise ApiError(400, str(e) or "check the map settings") from None
        self.hub.previews = {k: v for k, v in self.hub.previews.items() if v.state == "done"}
        self.hub.gallery = g.start()
        return {"ok": True, "id": g.id}

    def gallery_status(self, q, b) -> dict:
        g = self.hub.gallery
        if g is None or g.id != str(q.get("id", "")):
            raise ApiError(404, "that seed gallery isn't here any more")
        return g.to_dict()

    def cancel_gallery(self, q, b) -> dict:
        g = self.hub.gallery
        if g is None or g.id != str(b.get("id", "")):
            raise ApiError(404, "that seed gallery isn't here any more")
        g.cancel.set()
        return {"ok": True}

    def _preview(self, preview_id) -> object:
        p = self.hub.previews.get(str(preview_id or ""))
        if p is None:
            raise ApiError(404, "that map isn't here any more")
        return p

    def preview_status(self, q, b) -> dict:
        return self._preview(q.get("id")).to_dict()

    def preview_map(self, q, b) -> bytes:
        from . import preview
        try:
            return preview.image(self.hub, q.get("id", ""))
        except preview.PreviewError as e:
            raise ApiError(404, str(e)) from None

    # (the last previewed world, to move around, zoom out and grow)
    def _map(self, map_id):
        session = self.hub.map_session
        if session is None or session.id != str(map_id or ""):
            raise ApiError(404, "this map's world is gone (a newer preview replaced it); preview it again to explore it")
        return session

    @staticmethod
    def _ints(q, *names, limit=30_000_000) -> list[int]:
        try:
            values = [int(q.get(n, "")) for n in names]
        except (TypeError, ValueError):
            raise ApiError(400, "whole numbers, please") from None
        if any(abs(v) > limit for v in values):
            raise ApiError(400, "that's outside the world")
        return values

    def map_info(self, q, b) -> dict:
        return self._map(q.get("id")).to_dict()

    def map_tile(self, q, b) -> bytes:
        from . import preview
        session = self._map(q.get("id"))
        scale, tx, tz = self._ints(q, "s", "x", "z", limit=200_000)
        try:
            return preview.tile(session.surfaces, scale, tx, tz)
        except preview.PreviewError as e:
            raise ApiError(400, str(e)) from None

    def map_biome(self, q, b) -> dict:
        session = self._map(q.get("id"))
        x, z = self._ints(q, "x", "z")
        c = session.surfaces.chunk(x >> 4, z >> 4)
        return {"biome": c.biome if c else "", "made": c is not None}

    def map_explore(self, q, b) -> dict:
        from . import preview
        session = self._map(b.get("id"))
        x, z, radius = self._ints(b, "x", "z", "radius")
        if any(p.state == "running" for p in self.hub.previews.values()):
            raise ApiError(409, "a map is being made; wait for it")
        try:
            return session.explore(x, z, radius)
        except preview.PreviewError as e:
            raise ApiError(409 if "already" in str(e) else 400, str(e)) from None

    def map_stop(self, q, b) -> dict:
        session = self._map(b.get("id"))
        session.cancel.set()
        return {"ok": True}

    def cancel_preview(self, q, b) -> dict:
        self._preview(b.get("id")).cancel.set()
        return {"ok": True}

    # ---------------------------------------------------- remote access
    def _addresses(self) -> list[dict]:
        """Addresses a phone might reach this computer at: the home network, a Tailscale
        network (private and encrypted, works away from home), and an address you set."""
        from .cli import lan_ip
        out = []
        lan = lan_ip()
        if lan:
            out.append({"label": f"Home network ({lan})", "host": lan, "kind": "lan"})
        from . import tailscale
        st = tailscale.status(self._port())
        if st["serving"] and st["name"]:  # (HTTPS with a real certificate: the phone app works there; listed first)
            self._allow_host(st["name"])  # (Serve may have been on already, from before: the address must open)
            out.insert(0, {"label": f"Tailscale, secure ({st['name']}): for the phone app", "host": st["name"], "kind": "tailscale-https"})
        ts = tailscale_ip()
        if ts:
            out.append({"label": f"Tailscale ({ts}), works away from home", "host": ts, "kind": "tailscale"})
        custom = (self.hub.share_settings().get("address") or "").strip("[]")
        if custom and custom not in {a["host"] for a in out}:
            out.append({"label": f"Your address ({custom})", "host": custom, "kind": "custom"})
        return out

    # ------------------------------------------------------ mod conflict memory
    def conflicts_info(self, q, b) -> dict:
        from . import conflicts
        return {"enabled": self.hub.share_conflicts(), "available": bool(conflicts.relay_url()) and not self.hub.is_single,
                "relay": conflicts.relay_url()}

    def save_conflicts(self, q, b) -> dict:
        if self.hub.is_single:
            raise ApiError(400, "sharing mod conflicts needs `craft-conductor start` (the server list)")
        self.hub.set_share_conflicts(b.get("enabled") is True)
        log.info("sharing mod conflicts anonymously: %s", "on" if b.get("enabled") is True else "off")
        return {"ok": True, **self.conflicts_info(q, b)}

    # ---------------------------------------- fingerprint and face sign-in (passkeys)
    def passkey_list(self, q, b) -> dict:
        auth = self.web.auth
        return {"passkeys": self.web.passkeys.list(), "allowed": not (auth.default or auth.temporary or auth.managed)}

    def _passkey_rp(self, handler_rp) -> tuple[str, set[str]]:
        auth = self.web.auth
        if auth.default or auth.temporary:
            raise ApiError(400, "choose your own password first (Sign-in above)")
        if auth.managed:
            raise ApiError(400, "the password is set in craft-conductor.toml, so fingerprint and face sign-in isn't available")
        return handler_rp

    def passkey_options(self, q, b) -> dict:
        rp_id, _ = self._passkey_rp(b["__rp"])
        return self.web.passkeys.creation_options(rp_id)

    def passkey_add(self, q, b) -> dict:
        rp_id, origins = self._passkey_rp(b["__rp"])
        added = self.web.passkeys.add(rp_id, origins, str(b.get("client_data", "")), str(b.get("attestation", "")),
                                      str(b.get("name", "")))
        log.info("added the passkey %s (fingerprint or face sign-in at %s)", added["name"], rp_id)
        return {"ok": True, "passkey": added, "passkeys": self.web.passkeys.list()}

    def passkey_remove(self, q, b) -> dict:
        if not self.web.passkeys.remove(str(b.get("id", ""))):
            raise ApiError(404, "no such passkey")
        log.info("removed a passkey")
        return {"ok": True, "passkeys": self.web.passkeys.list()}

    def remote_info(self, q, b) -> dict:
        auth = self.web.auth
        return {"available": not self.hub.is_single, "network_access": self.web.remote_on(),
                "configured": self.hub.web.host not in ("127.0.0.1", "localhost", "::1"),
                "running_on_network": self.web.host not in ("127.0.0.1", "localhost", "::1"),
                "strong": auth.remote_ready, "mode": auth.mode, "rules": webauth.STRONG_RULES,
                "port": self.web.httpd.server_address[1] if self.web.httpd else self.web.port,
                "tls": self.web.tls, "tls_cert": self.hub.web.tls_cert, "tls_key": self.hub.web.tls_key,
                "addresses": self._addresses(), "devices": self.web.devices.list()}

    def save_tls(self, q, b) -> dict:
        if self.hub.is_single:
            raise ApiError(400, "set [web] tls_cert and tls_key in craft-conductor.toml for `craft-conductor run`")
        cert, key = str(b.get("cert", "")).strip(), str(b.get("key", "")).strip()
        if bool(cert) != bool(key):
            raise ApiError(400, "give both the certificate file and its key file (or neither)")
        if cert:
            import ssl
            for p in (cert, key):
                if not Path(p).is_file():
                    raise ApiError(400, f"{p} doesn't exist")
            try:
                ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(cert, key)
            except (OSError, ssl.SSLError) as e:
                raise ApiError(400, f"that certificate and key don't work together ({e})") from None
        self.hub.save_web(tls_cert=cert, tls_key=key)
        log.info("HTTPS for the control panel %s (applies when Craft Conductor restarts)", "set up" if cert else "turned off")
        return {"ok": True, "restart_needed": True}

    def pair_device(self, q, b) -> dict:
        """A one-time code, as a QR code, for a phone to scan (five minutes, once)."""
        from . import qr
        if self.hub.is_single:
            raise ApiError(400, "phone pairing needs `craft-conductor start` (the server list)")
        if not self.web.auth.remote_ready:
            raise ApiError(400, "first set a strong password (" + webauth.STRONG_RULES + ")")
        host = str(b.get("host", ""))
        addresses = {a["host"]: a for a in self._addresses()}
        if host not in addresses:
            raise ApiError(400, "pick one of the addresses listed")
        secure = addresses[host]["kind"] == "tailscale-https"  # (Tailscale passes it on: no network access needed)
        if not secure and (not self.web.remote_on() or self.web.host in ("127.0.0.1", "localhost", "::1")):
            raise ApiError(400, "turn on access from other devices first (and restart Craft Conductor), so the phone can reach this computer")
        role = str(b.get("role") or "helper")
        if role not in webauth.ROLES:
            raise ApiError(400, "pick helper or viewer")
        code = self.web.devices.new_code(time.time(), role)
        port = self.web.httpd.server_address[1] if self.web.httpd else self.web.port
        shown = f"[{host}]" if ":" in host else host
        url = f"https://{host}/#pair={code}" if secure else f"{'https' if self.web.tls else 'http'}://{shown}:{port}/#pair={code}"
        log.info("made a pairing code for a %s (valid for five minutes)", role)
        return {"url": url, "qr": qr.svg(url), "code": code, "secure": secure, "expires_in": webauth.PAIR_SECONDS}

    def cancel_pairing(self, q, b) -> dict:
        n = self.web.devices.cancel_codes()
        if n:
            log.info("cancelled %d pairing code(s) that weren't used", n)
        return {"ok": True, "cancelled": n}

    def remove_device(self, q, b) -> dict:
        which = b.get("id")
        n = self.web.devices.remove(None if which == "all" else str(which or ""))
        if not n:
            raise ApiError(404, "no such phone")
        log.info("removed %d paired phone(s)", n)
        return {"ok": True, "devices": self.web.devices.list()}

    # --------------------------------------------------------- Discord
    def _discord(self):
        if self.hub.is_single:
            raise ApiError(400, "posting to Discord needs `craft-conductor start` (the server list)")
        bot = self.hub.discord()
        if bot is None:
            raise ApiError(400, "set up the Discord bot first")
        return bot

    def discord_info(self, q, b) -> dict:
        from .discord import DEVELOPER_PORTAL, Discord
        s = self.hub.discord_settings() if not self.hub.is_single else {"set": False, "bot": None}
        return {**s, "portal": DEVELOPER_PORTAL,
                "invite_url": Discord.invite_url(s["bot"]["id"]) if s.get("bot") else None,
                "whitelist": self.hub.discord_whitelist() if not self.hub.is_single else None}

    def discord_whitelist(self, q, b) -> dict:
        """Whitelist through Discord: on or off, ask first or let them in, and an optional role."""
        self._discord()
        try:
            self.hub.set_discord_whitelist(b.get("enabled") is True, str(b.get("mode", "ask")), str(b.get("role", "")))
        except ValueError as e:
            raise ApiError(400, str(e)) from None
        return {"ok": True, "whitelist": self.hub.discord_whitelist()}

    def save_discord(self, q, b) -> dict:
        if self.hub.is_single:
            raise ApiError(400, "posting to Discord needs `craft-conductor start` (the server list)")
        bot = self.hub.save_discord_token(str(b.get("token", "")))
        return self.discord_info(q, b) | {"ok": True, "bot": bot}

    def use_public_ip(self, q, b) -> dict:
        """Find this network's public address and use it for friends' invite links."""
        if self.hub.is_single:
            raise ApiError(400, "friend downloads need `craft-conductor start` (the server list)")
        ip = self.hub.public_ip()
        self.hub.save_share(self.hub.share_settings()["port"], ip)
        log.info("friends outside your network now use %s", ip)
        return {"ok": True, "ip": ip, "share": self.hub.share_status()}

    def curseforge_info(self, q, b) -> dict:
        from .mods.curseforge import bundled_key
        key = self.curseforge_key_now()
        own = bool(key) and key != bundled_key()
        return {"set": bool(key), "own": own, "builtin": bool(bundled_key())}

    def curseforge_key_now(self) -> str:
        return self.hub.curseforge_key() if not self.hub.is_single else os.environ.get("CRAFT_CONDUCTOR_CURSEFORGE_API_KEY", "")

    def save_curseforge(self, q, b) -> dict:
        if self.hub.is_single:
            raise ApiError(400, "set [curseforge] api_key in craft-conductor.toml for a server run with `craft-conductor run`")
        self.hub.save_curseforge_key(str(b.get("key", "")))
        log.info("CurseForge API key %s", "saved" if b.get("key") else "removed")
        return {"ok": True, "set": bool(self.hub.curseforge_key())}

    def quit(self, q, b) -> dict:
        """Close craft-conductor (stopping every server), for when there's no window to close."""
        if self.hub.is_single:
            raise ApiError(400, "this Craft Conductor was started with `craft-conductor run`; stop it where it runs")
        log.info("quitting (asked from the web UI)")
        threading.Timer(0.5, self.hub.stop_requested.set).start()  # after this reply is sent
        return {"ok": True}

    def saves(self, q, b) -> dict:
        """Singleplayer worlds on this computer, to start a server from (or put on one)."""
        from . import world
        return {"worlds": world.list_saves()}

    def discord_status(self, q, b) -> dict:
        """Keep a live status message in a channel ("" stops it)."""
        try:
            self.hub.set_discord_status(str(b.get("channel", "")).strip())
        except ValueError as e:
            raise ApiError(400, str(e)) from None
        return {"ok": True, **self.hub.discord_settings()}

    def open_folder(self, q, b) -> dict:
        from . import opener
        where = {"home": self.hub.home, "exports": self.hub.exports_dir}.get(str(b.get("what", "")))
        if where is None:
            raise ApiError(400, "unknown folder")
        where.mkdir(parents=True, exist_ok=True)
        if not opener.open_path(where):
            raise ApiError(500, f"couldn't open a file manager; the folder is {where}")
        return {"ok": True, "path": str(where)}

    # ------------------------------------------- a server on another computer (SSH)
    def remote_install(self, q, b) -> dict:
        """The SSH command that installs craft-conductor on a Linux computer, and where its panel will be."""
        from . import remoteinstall
        try:
            host, user, port = remoteinstall.check(b.get("host", ""), b.get("user", ""), b.get("port", 22))
        except remoteinstall.RemoteInstallError as e:
            raise ApiError(400, str(e)) from None
        rented = b.get("rented")
        rented = (not remoteinstall.on_home_network(host)) if rented is None else bool(rented)
        return {"command": remoteinstall.command_line(host, user, port, rented), "panel": remoteinstall.panel_url(host, rented),
                "rented": rented, "tunnel_command": remoteinstall.tunnel_command(host, user, port) if rented else None}

    def remote_install_open(self, q, b) -> dict:
        """Open a terminal on this computer running that command (OpenSSH asks for the password there)."""
        from . import remoteinstall
        info = self.remote_install(q, b)
        host, user, port = remoteinstall.check(b.get("host", ""), b.get("user", ""), b.get("port", 22))
        tunnel = b.get("tunnel") is True and info["rented"]
        try:
            remoteinstall.launch(host, user, port, rented=info["rented"], tunnel=tunnel)
        except (remoteinstall.RemoteInstallError, OSError) as e:
            raise ApiError(400, str(e)) from None
        log.info("opened an SSH window %s %s@%s", "to the control panel of" if tunnel else "to install Craft Conductor on", user, host)
        return {**info, "ok": True}

    def stage(self, q, handler) -> dict:
        if handler.headers.get("X-CRAFT-CONDUCTOR") != "1":
            raise ApiError(403, "missing X-CRAFT-CONDUCTOR header")
        name = q.get("filename", "")
        if not re.fullmatch(r"[A-Za-z0-9 ()\[\]+_.,'-]{1,120}\.(jar|zip)", name):
            raise ApiError(400, "only .jar and .zip files can be added here")
        return self.hub.stage_upload(handler, name, MAX_ARCHIVE if name.endswith(".zip") else MAX_UPLOAD)

    def port_check(self, q, b) -> dict:
        try:
            port = int(q.get("port", ""))
        except ValueError:
            raise ApiError(400, "the port must be a number") from None
        if not 1024 <= port <= 65535:
            raise ApiError(400, "pick a port between 1024 and 65535")
        return self.hub.port_info(port, exclude=q.get("exclude") or None)

    def save_share(self, q, b) -> dict:
        if self.hub.is_single:
            raise ApiError(400, "friend downloads need `craft-conductor start` (the server list)")
        try:
            port = int(b.get("port", 8766))
        except (TypeError, ValueError):
            raise ApiError(400, "the port must be a number") from None
        if not 1024 <= port <= 65535 or port == self.web.port:
            raise ApiError(400, "pick a port between 1024 and 65535 that the control panel isn't using")
        address = str(b.get("address", "")).strip()
        if address and not re.fullmatch(r"[A-Za-z0-9.-]{1,253}|\[[0-9A-Fa-f:]{2,45}\]|[0-9A-Fa-f:]{2,45}", address):
            raise ApiError(400, "the address should be a host name or IP address, without http:// or a port")
        tunnel_text = b.get("tunnel")
        if tunnel_text is not None:
            from .tunnel import TunnelError, parse_address
            tunnel_text = str(tunnel_text).strip()
            try:
                parse_address(tunnel_text, default_port=0)
            except TunnelError as e:
                raise ApiError(400, str(e)) from None
        self.hub.save_share(port, address, tunnel_text)
        log.info("friend download settings: port %s, address %s%s", port, address or "(automatic)",
                 f", playit.gg tunnel {tunnel_text}" if tunnel_text else "")
        return {"ok": True, "share": self.hub.share_status()}

    def _get_mojang(self) -> Mojang:
        if self._mojang is None:
            self._mojang = Mojang(self.hub.http)
        return self._mojang

    def new_server_options(self, q, b) -> dict:
        return {**setup_options(self._get_mojang()), "pending": True, "network_option": False,
                "port": self.hub.free_port(),
                "server_dir": str(self.hub.home / "servers" / "<name>"), "current": None}

    def create(self, q, b) -> dict:
        spec = setupmod.SetupSpec.from_dict(b)
        return {"ok": True, "id": self.hub.create(spec)}

    def network(self, q, b) -> dict:
        if self.hub.is_single:
            raise ApiError(400, "set [web] host in craft-conductor.toml for `craft-conductor run`")
        enabled = b.get("enabled") is True
        if enabled and not self.web.auth.remote_ready:
            raise ApiError(400, "first set a strong password (" + webauth.STRONG_RULES + "); "
                                "PINs can't be used for access from other devices")
        self.hub.save_web(host="0.0.0.0" if enabled else "127.0.0.1")
        if not enabled:
            self.web.devices.cancel_codes()  # (a pairing code shown for the network is no use now)
        log.info("network access to the control panel turned %s (applies when Craft Conductor restarts)", "on" if enabled else "off")
        return {"ok": True, "restart_needed": enabled != (self.web.host in ("0.0.0.0", "::"))}

    def accept_notice(self, q, b) -> dict:
        if b.get("version") != notice.NOTICE_VERSION:
            raise ApiError(409, "the notice has changed; reload the page")
        notice.accept(self.hub.root, by="web")
        log.info("first-run notice accepted in the web UI")
        return {"ok": True}

    def apply_self_update(self, q, b) -> dict:
        info = self.hub.self_update_info()
        if not info:
            raise ApiError(404, "no craft-conductor update is available")
        if not info.get("can_install"):
            raise ApiError(400, info.get("reason") or "Craft Conductor can't update itself here")
        if b.get("version") != info["version"]:
            raise ApiError(409, "a different version is available now; reload the page")
        self.hub.run_job(f"update Craft Conductor to {info['version']}", self.hub.apply_self_update)
        return {"ok": True}

    def set_update_channel(self, q, b) -> dict:
        """Stable releases only (the default), or betas too; then look on that channel."""
        channel = b.get("channel")
        if channel not in selfupdate.CHANNELS:
            raise ApiError(400, "pick stable or beta")
        self.hub.set_update_channel(channel)
        return {"ok": True, "channel": channel, "message": self.hub.check_self_update(),
                "self_update": self.hub.self_update_info()}


class Api:
    """One server's part of the API: /api/servers/<id>/... (or /api/... with a single server)."""

    def __init__(self, web: WebUI, daemon: Daemon, sid: str):
        from .webmap import Availability
        self.web = web
        self.d = daemon
        self.sid = sid
        self._webmaps = Availability()  # which web maps Modrinth has a build of (asked rarely)
        r: dict[tuple[str, str], Callable[[dict, dict], Any]] = {}
        get = lambda p, f: r.__setitem__(("GET", p), f)    # noqa: E731
        post = lambda p, f: r.__setitem__(("POST", p), f)  # noqa: E731
        get("/api/status", self.status)
        get("/api/console", self.console)
        get("/api/events", self.events)
        post("/api/command", self.command)
        post("/api/server/start", lambda q, b: self._job("start", self.d.start_server))
        post("/api/server/stop", lambda q, b: self._job("stop", self.d.stop_server))
        post("/api/server/restart", lambda q, b: self._job("restart", self.d.restart_server))
        get("/api/updates", lambda q, b: {"check": self.d.last_check})
        get("/api/updates/readiness", self.readiness)
        get("/api/beta", self.betas)
        post("/api/updates/check", lambda q, b: self._job("update check", self.d.check_only, b.get("target")))
        post("/api/updates/apply", lambda q, b: self._job(
            "update", self.d.check_for_updates, True, b.get("target") or None))
        get("/api/setup", self.setup_options)
        post("/api/setup", self.setup_apply)
        get("/api/mods", self.mods)
        get("/api/mods/search", self.search)
        post("/api/mods/add", self.add_mod)
        post("/api/mods/remove", self.remove_mod)
        post("/api/mods/jar", self.set_jar)
        post("/api/mods/required", self.set_required)
        post("/api/manual/upload", lambda q, b: None)  # handled specially (raw body)
        get("/api/players/skin", lambda q, b: None)    # handled specially (an image)
        get("/api/backups", self.backups)
        post("/api/backups/create", self.create_backup)
        post("/api/backups/restore", self.restore_backup)
        get("/api/backups/changes", self.backup_changes)
        post("/api/backups/check", self.check_backup)
        post("/api/backups/area", self.restore_area)
        post("/api/open", self.open_folder)
        get("/api/play-here", self.play_here_info)
        get("/api/doctor", self.doctor)
        get("/api/performance", self.performance)
        get("/api/join-requests", self.join_requests)
        get("/api/bedrock", self.bedrock)
        get("/api/bedrock/check", self.bedrock_check)
        get("/api/tunnel", self.tunnel)
        get("/api/world/tools", self.world_tools)
        get("/api/modsets", self.modsets)
        post("/api/modsets/save", self.modset_save)
        post("/api/modsets/restore", self.modset_restore)
        post("/api/modsets/delete", self.modset_delete)
        post("/api/modsets/import", self.modset_import)
        get("/api/modsets/export", lambda q, b: None)  # sent by the request handler (a .json file)
        post("/api/world/rule", self.world_rule)
        post("/api/world/border", self.world_border)
        post("/api/world/chunky", self.world_chunky)
        get("/api/webmap", self.webmap)
        post("/api/webmap/add", self.webmap_add)
        post("/api/webmap/accept", self.webmap_accept)
        post("/api/webmap/port", self.webmap_port)
        post("/api/join-requests/answer", self.answer_join_request)
        post("/api/performance/spark", self.spark_profile)
        get("/api/performance/lag", self.lag_status)
        post("/api/performance/lag", self.start_lag_finder)
        post("/api/performance/lag/stop", self.stop_lag_finder)
        post("/api/doctor/internet", self.doctor_internet)
        post("/api/doctor/fix", self.doctor_fix)
        post("/api/problem/fix", self.problem_fix)
        get("/api/doctor/report", lambda q, b: None)  # sent by the request handler (a zip)
        post("/api/play-here", self.play_here)
        post("/api/world/replace", self.replace_world)
        post("/api/updates/remove-and-upgrade", self.remove_and_upgrade)
        get("/api/updates/rehearsal", self.rehearsal_status)
        post("/api/updates/rehearsal", self.start_rehearsal)
        post("/api/updates/rehearsal/stop", self.stop_rehearsal)
        post("/api/mods/check", lambda q, b: self._check(b, client=False))
        post("/api/client/check", lambda q, b: self._check(b, client=True))
        post("/api/beta/test", self.test_beta)
        get("/api/configs", lambda q, b: configs.grouped(self.m.server_dir, self.m.lock.mods))
        get("/api/configs/file", lambda q, b: configs.read(self.m.server_dir, q.get("path", "")))
        post("/api/configs/file", self.save_config)
        get("/api/export", self.exports)
        post("/api/export", self.export)
        post("/api/export/delete", self.delete_export)
        get("/api/export/download", self.exports)  # streamed by the request handler
        get("/api/players", self.players)
        get("/api/players/online", self.players_online)
        post("/api/broadcast", self.broadcast)
        get("/api/players/activity", self.player_activity)
        post("/api/players/action", self.player_action)
        get("/api/java", self.java)
        post("/api/java/install", self.java_install)
        post("/api/java/use", self.java_use)
        post("/api/java/scan", self.java_scan)
        post("/api/java/update", self.java_update)
        post("/api/java/remove", self.java_remove)
        get("/api/settings", self.settings)
        post("/api/settings", self.save_settings)
        get("/api/browse/search", lambda q, b: browse_search(self._browser(), q, self.m))
        get("/api/browse/project", lambda q, b: browse_project(self._browser(), q))
        get("/api/browse/categories", lambda q, b: browse_categories(self._browser(), q))
        post("/api/mods/add-many", self.add_many)
        get("/api/mods/requires", lambda q, b: requirements_query(self._modrinth(), q, self.m, self.m.providers.get("curseforge")))
        post("/api/mods/local", self.upload_local)
        get("/api/client", self.client)
        post("/api/client", self.save_client)
        post("/api/client/new-link", self.new_client_link)
        post("/api/client/stop-link", self.stop_client_link)
        post("/api/client/discord", self.post_to_discord)
        post("/api/client/local", self.upload_client_jar)
        post("/api/client/local/remove", self.remove_client_jar)
        get("/api/client/search", self.client_search)
        self.routes = r
        self.sampler = stats.Sampler()
        self._skins: Skins | None = None

    @property
    def skins(self) -> Skins:
        if self._skins is None or self._skins.server_dir != self.m.server_dir:  # the config may change
            self._skins = Skins(self.m.config.state_dir / "skins", self.m.server_dir)
        return self._skins

    @property
    def m(self):
        return self.d.m

    def _job(self, name: str, fn, *args) -> dict:
        if not self.d.submit(name, fn, *args):
            raise ApiError(409, f"busy: {self.d.job['name'] if self.d.job else 'another task'} is running")
        return {"ok": True, "job": name}

    # -------------------------------------------------------------- status
    def status(self, q, b) -> dict:
        d, m, lk = self.d, self.m, self.m.lock
        props = read_properties(m.server_dir / "server.properties")
        return {
            "version": __version__,
            "state": d.state,
            "job": d.job,
            "last_job": d.last_job,
            "want_running": d.want_running,
            "uptime": time.time() - d.started_at if d.started_at and d.state == "running" else None,
            "minecraft": lk.minecraft,
            "loader": lk.loader or m.config.server.loader,
            "loader_version": lk.loader_version,
            "java_major": lk.java_major,
            "java_forced": m.config.java_version,
            "mods": len(lk.mods),
            "players": sorted(d.players),
            "max_players": int(props.get("max-players", "20") or 20),
            "motd": props.get("motd", ""),
            "port": props.get("server-port", "25565"),
            "server_dir": str(m.server_dir),
            "strategy": m.config.updates.strategy,
            "auto_upgrade": m.config.updates.auto_upgrade,
            "update": self._update_summary(),
            "notice_accepted": notice.accepted(self.web.hub.root),
            "setup_pending": d.setup_pending,
            "self_update": self.web.hub.self_update_info(),
            "update_channel": self.web.hub.update_channel(),
            "id": self.sid,
            "auth": self.web.auth.info(),
            "resources": self._resources(),
            "disk": self._disk_usage(),
            "problem": d.problem,
        }

    def _disk_usage(self) -> dict | None:
        """Filesystem capacity, without recursively scanning world or backup files."""
        try:
            volume = shutil.disk_usage(self.m.server_dir if self.m.server_dir.exists() else self.m.config.root)
            return {"total_bytes": volume.total, "used_bytes": volume.used, "free_bytes": volume.free}
        except OSError:
            return None

    def _resources(self) -> dict | None:
        """CPU and memory use of the running server, for the dashboard's bars."""
        proc = self.d.proc
        pid = proc.proc.pid if proc and proc.running and getattr(proc, "proc", None) else None
        usage = self.sampler.read(pid)
        if usage is None:
            return None
        total = setupmod.total_ram_gb()
        return {**usage,
                "memory_max_bytes": stats.heap_bytes(self.m.config.server.memory, setupmod.suggested_memory_gb(total)),
                "system_memory_bytes": int(total * 1024 ** 3) if total else None}

    def readiness(self, q, b) -> dict:
        """For one Minecraft version (default: the newest release): is the loader ready, and does
        each installed mod have a build for it? green: a release; yellow: only alpha/beta
        builds; red: nothing yet; unknown: couldn't tell (a file of your own, or a lookup failed)."""
        from .mods.base import CHANNEL_RANK
        from .mods.modrinth import ModrinthProvider
        version = q.get("version") or self.m.mojang.latest_release()
        if not re.fullmatch(r"\d+(\.\d+){1,3}(-[A-Za-z0-9.]+)?|\d{2}w\d{2}[a-z]", version):
            raise ApiError(400, "that isn't a Minecraft version")
        loader = self.m.loader
        try:
            loader_version = loader.latest_version(version)
            # (red: the loader has nothing for it yet; unknown: its list is incomplete just now)
            loader_state = "green" if loader_version else "unknown" if loader.missing_reason(version) else "red"
        except HttpError:
            loader_version, loader_state = None, "unknown"
        mods = list(self.m.lock.mods)
        loaders = loader.mod_loaders
        channels: dict[str, str | None] = {}
        modrinth_ids = [x.project_id for x in mods if x.source == "modrinth" and not x.manual]
        from . import webmap
        # A web map that was added but isn't installed yet counts like any installed mod.
        pending_map = None if webmap.installed(mods) else webmap.installed(self.m.config.mods)
        if pending_map and loaders:
            modrinth_ids.append(webmap.MAPS[pending_map]["project"])
        if modrinth_ids and loaders:
            provider = self.m.providers.get("modrinth")
            channels.update((provider if isinstance(provider, ModrinthProvider) else ModrinthProvider(self.m.http))
                            .best_channels(modrinth_ids, loaders, version))
        names = {x.key: x.name for x in mods}
        out = []
        for x in mods:
            if x.source == "modrinth" and x.project_id in channels:
                channel = channels[x.project_id]
            else:  # CurseForge and others: ask the provider which versions each channel covers
                provider = self.m.providers.get(x.source)
                channel = "unknown"
                if provider is not None and loaders:
                    try:
                        spec = ModSpec(x.source, x.project_id)
                        channel = next((c for c in sorted(CHANNEL_RANK, key=CHANNEL_RANK.get)
                                        if version in provider.supported_versions(spec, loaders, c)), None)
                    except (HttpError, ModError):
                        channel = "unknown"
            state = {"release": "green", None: "red", "unknown": "unknown"}.get(channel, "yellow")
            out.append({"name": x.name, "key": x.key, "version": x.version_number, "state": state,
                        "channel": channel if channel not in (None, "unknown") else None,
                        "required": x.required, "needed_by": names.get(x.dependency_of or "", None)})
        order = {"red": 0, "yellow": 1, "unknown": 2, "green": 3}
        if pending_map:
            spec = webmap.MAPS[pending_map]
            channel = channels.get(spec["project"], "unknown") if loaders else "unknown"
            listed = next((m for m in self.m.config.mods if webmap.installed([m])), None)
            out.append({"name": spec["name"], "key": f"modrinth:{spec['project']}", "version": "", "installed": False,
                        "state": {"release": "green", None: "red", "unknown": "unknown"}.get(channel, "yellow"),
                        "channel": channel if channel not in (None, "unknown") else None,
                        "required": listed.required if listed else False, "needed_by": None})
        for name in self.m.unmanaged_jars():
            out.append({"name": name, "key": f"local:{name}", "version": "local file", "state": "unknown",
                        "channel": None, "required": True, "needed_by": None})
        out.sort(key=lambda m: (order[m["state"]], m["name"].lower()))
        return {"minecraft": version, "installed": self.m.lock.minecraft,
                "strategy": self.m.config.updates.strategy,
                "loader": {"name": loader.name, "state": loader_state, "version": loader_version},
                "mods": out, "counts": {k: sum(m["state"] == k for m in out) for k in order}}

    def _update_summary(self) -> dict | None:
        c = self.d.last_check
        if not c:
            return None
        return {"checked_at": c["checked_at"], "up_to_date": c["up_to_date"], "target": c["target"],
                "latest": c["latest"], "manual": len(c["manual"]), "lagging": c.get("lagging")}

    def console(self, q, b) -> dict:
        items, last = self.d.console.since(int(q.get("since", 0) or 0), 1000)
        return {"lines": [{"seq": i["seq"], "text": i["text"], "user": i.get("source") == "user"} for i in items],
                "last": last}

    def events(self, q, b) -> dict:
        items, last = self.d.events.since(int(q.get("since", 0) or 0), 200)
        return {"events": items, "last": last}

    def command(self, q, b) -> dict:
        command = str(b.get("command", "")).strip().lstrip("/")
        if not command:
            raise ApiError(400, "enter a command")
        if "\n" in command or "\r" in command:
            log.warning("refused a console command from the control panel: it had a line break")
            raise ApiError(400, "enter a single command (it can't have line breaks)")
        try:
            check_command(command)
        except ValueError as e:
            log.warning("refused a console command from the control panel: %s", e)
            raise ApiError(400, str(e)) from None
        self.d.send_command(command)
        return {"ok": True}

    # --------------------------------------------------------------- setup
    def setup_options(self, q, b) -> dict:
        return {**setup_options(self.m.mojang), "pending": self.d.setup_pending,
                "server_dir": str(self.m.server_dir),
                "network_option": self.web.hub.is_single,  # with several servers it's an craft-conductor setting
                "network_access": self.m.config.web.host in ("0.0.0.0", "::"),
                "current": self._current_setup()}

    def _current_setup(self) -> dict | None:
        """What an existing craft-conductor.toml already asks for, so the setup page can start from it."""
        cfg = self.m.config
        mods = [{"slug": s.id, "required": s.required} for s in cfg.mods
                if s.source == "modrinth" and s.id != "fabric-api"]
        if not mods and cfg.server.minecraft == "latest" and cfg.server.loader == "fabric":
            return None  # the untouched default
        mem = re.fullmatch(r"(\d+)G", cfg.server.memory)
        return {"loader": cfg.server.loader, "minecraft": cfg.server.minecraft, "mods": mods,
                "memory_gb": int(mem.group(1)) if mem and 1 <= int(mem.group(1)) <= 64 else None}

    def setup_apply(self, q, b) -> dict:
        if not self.d.setup_pending:
            raise ApiError(409, "this server is already set up")
        spec = setupmod.SetupSpec.from_dict(b)
        spec.world_source = self.web.hub.world_source(spec.world)
        if spec.local_mods:
            self.web.hub.take_staged(spec.local_mods, self.m.mods_dir)
        if spec.client_local:
            from .clientpack import client_dir
            self.web.hub.take_staged(spec.client_local, client_dir(self.m.config))  # friends' own files
        return self._job("set up server", self.d.run_setup, spec)

    # ---------------------------------------------------------------- mods
    def mods(self, q, b) -> dict:
        lk = self.m.lock
        return {
            "loader": self.m.config.server.loader,
            "minecraft": lk.minecraft,
            "installed": [{"key": x.key, "name": x.name, "version": x.version_number, "filename": x.filename,
                           "source": x.source, "dependency_of": x.dependency_of, "channel": x.channel, "manual": x.manual}
                          for x in lk.mods],
            "configured": self._configured_with_deps(),
            "skipped": [{"key": k, "reason": v} for k, v in lk.skipped.items()],
            "unmanaged": self.m.unmanaged_jars(),
            "disabled": self.m.disabled_jars(),
            # combinations other people found don't work (conflicts.py; empty until the list exists)
            "known_conflicts": self.web.hub.known_conflicts.matching(
                lk.loader or self.m.config.server.loader, lk.minecraft or "", [s.id for s in self.m.config.mods]),
        }

    def set_jar(self, q, b) -> dict:
        from .manager import UpgradeError
        action = str(b.get("action", ""))
        if action not in ("enable", "disable", "remove"):
            raise ApiError(400, "unknown action")
        try:
            message = self.m.set_jar(str(b.get("name", "")), action)
        except UpgradeError as e:
            raise ApiError(400, str(e)) from None
        log.info("%s", message)
        return {"ok": True, "message": message}

    def _modrinth(self) -> ModrinthProvider:
        return self.m.providers.get("modrinth") or ModrinthProvider(self.m.http)

    def _check(self, b, client: bool) -> dict:
        """The instant check for this server's mods (with the players' mods too, for the Friends page)."""
        from . import trial
        loaders = self.m.loader.mod_loaders
        if not loaders:
            return {"ok": True, "mods": [], "conflicts": [], "problems": [], "minecraft": self.m.lock.minecraft}
        mods = [s.id for s in self.m.config.mods if s.source == "modrinth"]
        channels = {s.id: s.channel for s in self.m.config.mods if s.channel}
        if client:
            mods += list(self.m.config.client.mods)
        minecraft = self.m.lock.minecraft or (None if self.m.config.server.minecraft == "latest" else self.m.config.server.minecraft)
        provider = self._modrinth()
        channel = self.m.config.updates.mod_channel
        return run_check(self.web.hub, b, lambda progress: trial.check(provider, loaders, minecraft, mods, channel=channel,
                                                                        progress=progress, channels=channels))

    def _configured_with_deps(self) -> list[dict]:
        """The mods in craft-conductor.toml, each with the dependencies installed for it (several mods can share one)."""
        lk = self.m.lock
        installed = {x.key: x for x in lk.mods}
        out = []
        for spec in self.m.config.mods:
            key = f"{spec.source}:{spec.id}"
            if key not in installed:
                match = next((x for x in lk.mods if x.source == spec.source and x.project_id == spec.id), None)
                if match:
                    key = match.key
                elif spec.source == "modrinth":
                    try:
                        key = self._modrinth().project(spec.id).key  # a slug in craft-conductor.toml
                    except Exception:
                        pass
            deps, todo, seen = [], [key], {key}
            while todo:  # follow each installed mod's own list of what it needs
                mod = installed.get(todo.pop(0))
                for pid in (mod.dependencies if mod else []):
                    dk = f"{mod.source}:{pid}"
                    if dk in installed and dk not in seen:
                        seen.add(dk)
                        d = installed[dk]
                        deps.append({"key": dk, "name": d.name, "source": d.source, "version": d.version_number,
                                     "channel": d.channel, "dependency_of": d.dependency_of})
                        todo.append(dk)
            current = installed.get(key)
            out.append({"source": spec.source, "id": spec.id, "required": spec.required, "key": key,
                        "channel": current.channel if current else (spec.channel or "release"),
                        "version": current.version_number if current else "",
                        "name": current.name if current else spec.id, "deps": deps})
        return out

    def search(self, q, b) -> dict:
        listed = {s.id for s in self.m.config.mods if s.source == "modrinth"}
        return search_mods(self._modrinth(), q, listed, self.m.config.server.loader, self.m.lock.minecraft)

    def add_mod(self, q, b) -> dict:
        source = b.get("source", "modrinth")
        if source not in configmod.MOD_SOURCES:
            raise ApiError(400, "unknown source")
        mod_id = str(b.get("id", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", mod_id):
            raise ApiError(400, "invalid mod id")
        plugins = self.m.loader.mods_folder != "mods"
        if source == "curseforge" and plugins:
            raise ApiError(400, "Paper plugins come from Modrinth or Hangar")
        if source == "hangar" and not plugins:
            raise ApiError(400, "Hangar has Paper plugins, not mods")
        project = self.m.providers[source].project(mod_id)
        if project.server_side == "unsupported":
            raise ApiError(400, f"{project.name} is client-side only")
        if any(s.source == source and s.id in (mod_id, project.id, project.slug) for s in self.m.config.mods):
            raise ApiError(409, f"{project.name} is already listed")
        early = b.get("channel") if b.get("channel") in ("beta", "alpha") else None  # picked with only early builds
        deps = self._list_server_mod(source, project, bool(b.get("required", True)), early)
        return {"ok": True, "name": project.name, "deps": deps}

    def _list_server_mod(self, source: str, project, required: bool, early: str | None = None) -> list[str]:
        """Put a mod in craft-conductor.toml (it's installed with the next update); returns the names of the
        mods it needs, which come along. A Modrinth mod without a build for this server is refused."""
        deps = []
        if source == "modrinth" and self.m.loader.mod_loaders:
            # Only mods that work on this server's Minecraft, and say what comes along with them.
            try:
                req = mod_requirements(self._modrinth(), project.id, self.m.loader.mod_loaders, self.m.lock.minecraft,
                                       channel=lowest(self.m.config.updates.mod_channel, early),
                                       curseforge=self.m.providers.get("curseforge"))
            except (ModError, HttpError, Unavailable) as e:
                raise ApiError(400, f"couldn't check {project.name}'s required mods: {e}") from e
            if req is not None:
                if not req["compatible"] and self.m.lock.minecraft:
                    raise ApiError(400, f"can't add {project.name}: " + (req["reason"] or "no compatible build"))
                deps = [d["name"] for d in req["deps"]]
        # The name written to craft-conductor.toml comes from the site's answer (Modrinth allows quote marks in a
        # slug): only a plain name is written, else the project's id, else it's refused.
        ident = next((x for x in (project.slug, project.id) if x and re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", x)), None)
        if ident is None:
            raise ApiError(400, f"{project.name} has a name that isn't safe to save, so it can't be added")
        configmod.append_mod(self.m.config.path, ModSpec(source, ident, required=required, channel=early))
        self.m.reload_config()
        log.info("added %s%s", project.name, f" (with {', '.join(deps)})" if deps else "")
        return deps

    def _browser(self):
        from .browse import Browser
        return Browser(self.m.http, self.m.config.curseforge_api_key)

    def add_many(self, q, b) -> dict:
        """Add the mods ticked in the mod browser."""
        items = b.get("mods")
        if not isinstance(items, list) or not 0 < len(items) <= 100:
            raise ApiError(400, "pick between 1 and 100 mods")
        added, skipped = [], []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                added.append(self.add_mod(q, {"source": item.get("source", "modrinth"), "id": item.get("id"),
                                              "required": b.get("required", True) is not False,
                                              "channel": item.get("channel")})["name"])
            except (ApiError, ModError, ConfigError) as e:
                skipped.append({"name": item.get("name") or item.get("id"), "reason": str(e)})
        return {"ok": True, "added": added, "skipped": skipped}

    def upload_local(self, q, handler) -> dict:
        """A mod jar from this computer ("Local files"). If Modrinth knows it, it becomes a normal
        mod that craft-conductor keeps up to date; otherwise it stays as your own file in mods/."""
        from .hub import receive
        if handler.headers.get("X-CRAFT-CONDUCTOR") != "1":
            raise ApiError(403, "missing X-CRAFT-CONDUCTOR header")
        name = q.get("filename", "")
        if not re.fullmatch(r"[A-Za-z0-9 ()\[\]+_.,'-]{1,120}\.jar", name):
            raise ApiError(400, "only .jar files can be added as mods")
        mods_dir = self.m.mods_dir
        dest = receive(handler, mods_dir / name, MAX_UPLOAD)
        try:
            found = self._modrinth().identify([sha1_file(dest)])
        except Exception:
            found = {}
        version = next(iter(found.values()), None)
        if version:
            try:
                r = self.add_mod(q, {"source": "modrinth", "id": version["project_id"]})
                dest.unlink(missing_ok=True)  # craft-conductor downloads the right file for each version from now on
                return {"ok": True, "name": r["name"], "managed": True}
            except ApiError as e:
                if e.status == 409:  # already one of the server's mods
                    dest.unlink(missing_ok=True)
                    return {"ok": True, "name": name, "managed": True, "already": True}
                log.info("%s is on Modrinth but can't be added (%s); keeping it as a local file", name, e)
        log.info("added %s as a local mod (Craft Conductor won't update it)", name)
        return {"ok": True, "name": name, "managed": False}

    def remove_mod(self, q, b) -> dict:
        if not configmod.remove_mod(self.m.config.path, b.get("source", "modrinth"), str(b.get("id", ""))):
            raise ApiError(404, "not listed in craft-conductor.toml")
        self.m.reload_config()
        log.info("removed %s from craft-conductor.toml", b.get("id"))
        return {"ok": True}

    def set_required(self, q, b) -> dict:
        source, mod_id = b.get("source", "modrinth"), str(b.get("id", ""))
        if not configmod.remove_mod(self.m.config.path, source, mod_id):
            raise ApiError(404, "not listed in craft-conductor.toml")
        configmod.append_mod(self.m.config.path, ModSpec(source, mod_id, required=bool(b.get("required"))))
        self.m.reload_config()
        return {"ok": True}

    def upload(self, handler: RequestHandler, q: dict) -> dict:
        """Receive a manually downloaded mod (for authors who block third-party downloads)."""
        if handler.headers.get("X-CRAFT-CONDUCTOR") != "1":
            raise ApiError(403, "missing X-CRAFT-CONDUCTOR header")
        filename = q.get("filename", "")
        expected = {x["filename"]: x for x in (self.d.last_check or {}).get("manual", [])}
        if filename not in expected or Path(filename).name != filename:
            raise ApiError(400, "that file isn't one of the manual downloads Craft Conductor is waiting for")
        length = int(handler.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_UPLOAD:
            raise ApiError(413, "file is empty or too large")
        folder = self.m.config.manual_dir
        folder.mkdir(parents=True, exist_ok=True)
        handler._body_read = True
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".upload-")
        try:
            with open(fd, "wb") as out:
                remaining = length
                while remaining:
                    chunk = handler.rfile.read(min(1 << 16, remaining))
                    if not chunk:
                        raise ApiError(400, "upload interrupted")
                    out.write(chunk)
                    remaining -= len(chunk)
            decision_mod = next((x for x in self._planned_mods() if x.filename == filename), None)
            if decision_mod and decision_mod.sha1 and sha1_file(Path(tmp)) != decision_mod.sha1.lower():
                raise ApiError(400, "that file doesn't match the one CurseForge lists (checksum differs); "
                                    "make sure you downloaded the exact file from the link")
            shutil.move(tmp, folder / filename)
        finally:
            Path(tmp).unlink(missing_ok=True)
        log.info("received manual download %s", filename)
        c = self.d.last_check
        if c:
            c["manual"] = [x for x in c["manual"] if x["filename"] != filename]
        return {"ok": True}

    def _planned_mods(self):
        target = (self.d.last_check or {}).get("target")
        if not target:
            return []
        return self.m.planner().plan_for(target).mods

    # ------------------------------------------------------------- players
    def _players(self) -> Players:
        running = self.d.state == "running"
        return Players(self.m.server_dir, self.m.http, self.d.send_command if running else None)

    def players(self, q, b) -> dict:
        return self._players().summary(self.d.players)

    def players_online(self, q, b) -> dict:
        """The Dashboard's Connected Players card (polled): who is online with their role and ping, the
        player limit, whether the whitelist is on (and its names with ?whitelist=1). Reads files only."""
        return self._players().roster(self.d.players, whitelist=q.get("whitelist") == "1")

    def broadcast(self, q, b) -> dict:
        """A message to everyone online, through the server's ``say``."""
        try:
            text = broadcast_text(b.get("message"))
        except PlayerError as e:
            log.warning("refused a broadcast from the control panel: %s", e)
            raise ApiError(400, str(e)) from None
        if self.d.state != "running":
            raise ApiError(409, "the server isn't running, so nobody can hear it")
        try:
            self.d.send_command(f"say {text}")
        except RuntimeError:  # (stopped just now)
            raise ApiError(409, "the server isn't running, so nobody can hear it") from None
        log.info("broadcast to everyone online (%d characters)", len(text))
        return {"ok": True, "message": "sent to everyone online"}

    def player_activity(self, q, b) -> dict:
        """Who played when (activity.py): the Players page's Player activity."""
        days = q.get("days", "30")
        return {**self.d.activity.summary(int(days) if days.isdigit() else 30),
                "schedule_restart": self.m.config.schedule.restart,
                "schedule_restart_words": self._schedule_info()["schedule_restart_words"]}

    # ------------------------------------------------------ saved mod lists
    def modsets(self, q, b) -> dict:
        from . import modsets
        return {"sets": [{"name": x["name"], "saved": x.get("saved"), "minecraft": x.get("minecraft"),
                          "mods": [m["id"] for m in x["mods"]], "client_mods": x.get("client_mods", [])}
                         for x in modsets.load(self.m.config)]}

    def _modset(self, fn, *args):
        from . import modsets
        try:
            return fn(self.m.config, *args)
        except modsets.ModSetError as e:
            raise ApiError(400, str(e)) from None

    def modset_save(self, q, b) -> dict:
        from . import modsets
        entry = self._modset(modsets.save, str(b.get("name", "")), self.m.lock.minecraft)
        return {"ok": True, "message": f"saved {entry['name']!r} ({len(entry['mods'])} mods)"}

    def modset_restore(self, q, b) -> dict:
        from . import modsets
        if self.d.job:
            raise ApiError(409, f"busy: {self.d.job['name']} is running")
        message = self._modset(modsets.restore, str(b.get("name", "")), self.m.lock.minecraft)
        self.m.reload_config()
        log.info("mod list %s", message)
        return {"ok": True, "message": message}

    def modset_delete(self, q, b) -> dict:
        from . import modsets
        if not self._modset(modsets.delete, str(b.get("name", ""))):
            raise ApiError(404, "no such list")
        return {"ok": True}

    def modset_import(self, q, b) -> dict:
        from . import modsets
        entry = b.get("set")
        if not isinstance(entry, dict):
            raise ApiError(400, "choose a mod list file saved from Craft Conductor")
        entry = self._modset(modsets.add, entry)
        return {"ok": True, "message": f"loaded {entry['name']!r} ({len(entry['mods'])} mods)"}

    def modset_export(self, name: str) -> dict:
        from . import modsets
        entry = next((x for x in modsets.load(self.m.config) if x["name"] == name), None)
        if entry is None:
            raise ApiError(404, "no such list")
        return entry

    # ------------------------------------------------------ world tools
    def _running_proc(self):
        if not (self.d.proc and self.d.proc.running and self.d.state == "running"):
            raise ApiError(409, "start the server first: these use the server's own commands")
        return self.d.proc

    def world_tools(self, q, b) -> dict:
        from . import worldtools
        chunky = any("chunky" in (x.name or "").lower() for x in self.m.lock.mods)
        if self.d.state != "running" or not self.d.proc:
            return {"running": False, "chunky": chunky}
        proc = self.d.proc
        return {"running": True, "rules": worldtools.read_rules(proc), "border": worldtools.border_size(proc),
                "chunky": chunky, "progress": worldtools.chunky_progress(proc.tail(300)) if chunky else None}

    def world_rule(self, q, b) -> dict:
        from . import worldtools
        try:
            message = worldtools.set_rule(self._running_proc(), str(b.get("rule", "")), str(b.get("value", "")).lower())
        except ValueError as e:
            raise ApiError(400, str(e))
        log.info("game rule: %s", message)
        return {"ok": True, "message": message}

    def world_border(self, q, b) -> dict:
        from . import worldtools
        try:
            diameter, x, z = int(b.get("diameter", 0)), int(b.get("x", 0)), int(b.get("z", 0))
        except (TypeError, ValueError):
            raise ApiError(400, "use whole numbers") from None
        try:
            message = worldtools.set_border(self._running_proc(), diameter, x, z)
        except ValueError as e:
            raise ApiError(400, str(e)) from None
        log.info("%s", message)
        return {"ok": True, "message": message}

    def world_chunky(self, q, b) -> dict:
        from . import worldtools
        if not any("chunky" in (x.name or "").lower() for x in self.m.lock.mods):
            raise ApiError(400, "add the Chunky mod first")
        proc = self._running_proc()
        action = str(b.get("action", ""))
        try:
            if action == "start":
                try:
                    radius, x, z = int(b.get("radius", 0)), int(b.get("x", 0)), int(b.get("z", 0))
                except (TypeError, ValueError):
                    raise ValueError("use whole numbers") from None
                message = worldtools.chunky_start(proc, radius, x, z)
            elif action in worldtools.CHUNKY_ACTIONS:
                proc.send(worldtools.CHUNKY_ACTIONS[action])
                message = f"pre-generation: {action}"
            else:
                raise ApiError(400, "unknown action")
        except ValueError as e:
            raise ApiError(400, str(e)) from None
        log.info("%s", message)
        return {"ok": True, "message": message}

    # ------------------------------------------------------- web map
    def _webmap_builds(self) -> tuple[str, dict]:
        """The Minecraft version the maps are for (the installed one, or a new install's target),
        and for each map whether Modrinth has a build for it on this server's loader (True or
        False; None when that couldn't be checked). Cached: see webmap.Availability."""
        cfg = self.m.config
        try:
            version = self.m.lock.minecraft or (self.m.mojang.latest_release() if cfg.server.minecraft == "latest"
                                                else cfg.server.minecraft)
        except (HttpError, KeyError):
            version = ""
        return version, self._webmaps.check(self._modrinth(), self.m.loader.mod_loaders, version, cfg.updates.mod_channel)

    def webmap(self, q, b) -> dict:
        """BlueMap or Dynmap (webmap.py): which one, its port, whether it answers, its address.
        With none added, also which ones Modrinth has a build of for this server."""
        from . import webmap
        from .cli import lan_ip
        loader = self.m.lock.loader or self.m.config.server.loader
        kind = webmap.installed(self.m.lock.mods)
        listed = webmap.installed(self.m.config.mods)
        out = {"kind": kind, "listed": listed, "maps": {k: v["name"] for k, v in webmap.MAPS.items()},
               "running": self.d.state == "running"}
        if not (kind or listed):  # (only when the Add buttons are to be shown)
            version, builds = self._webmap_builds()
            out.update(minecraft=version, available=builds, runs_mods=bool(self.m.loader.mod_loaders))
        if kind:
            port = webmap.port(self.m.server_dir, kind, loader)
            ip = lan_ip()
            out.update(name=webmap.MAPS[kind]["name"], port=port, answers=webmap.answers(port),
                       configured=webmap.config_file(self.m.server_dir, kind, loader).exists(),
                       local_url=f"http://localhost:{port}/", lan_url=f"http://{ip}:{port}/" if ip else None,
                       accepted=webmap.download_accepted(self.m.server_dir, loader) if kind == "bluemap" else True)
        return out

    def webmap_add(self, q, b) -> dict:
        from . import webmap
        kind = str(b.get("kind", ""))
        if kind not in webmap.MAPS:
            raise ApiError(400, "pick BlueMap or Dynmap")
        other = webmap.installed(self.m.config.mods)
        if other and other != kind:
            raise ApiError(409, f"this server already has {webmap.MAPS[other]['name']}: one web map is enough")
        if not other:  # (adding the one that's already listed is add_mod's "already listed")
            name = webmap.MAPS[kind]["name"]
            if not self.m.loader.mod_loaders:
                raise ApiError(400, f"{name} needs a server that runs mods or plugins, and this one runs plain Minecraft")
            version, builds = self._webmap_builds()
            if builds[kind] is False:
                raise ApiError(400, f"{name} has no {self.m.loader.name} build for Minecraft {version} yet, so it can't be added")
        return self.add_mod(q, {"source": "modrinth", "id": webmap.MAPS[kind]["project"], "required": False})

    def webmap_accept(self, q, b) -> dict:
        """The user's OK for BlueMap to download Minecraft's textures from Mojang."""
        from . import webmap
        loader = self.m.lock.loader or self.m.config.server.loader
        try:
            webmap.accept_download(self.m.server_dir, loader)
        except webmap.WebMapError as e:
            raise ApiError(400, str(e)) from None
        if self.d.state == "running" and self.d.proc:
            self.d.send_command("bluemap reload")  # (it starts drawing without a restart)
        log.info("BlueMap may download Minecraft's textures now")
        return {"ok": True}

    def webmap_port(self, q, b) -> dict:
        from . import webmap
        kind = webmap.installed(self.m.lock.mods)
        if not kind:
            raise ApiError(400, "add a web map first")
        try:
            new = int(b.get("port", 0))
        except (TypeError, ValueError):
            raise ApiError(400, "the port must be a number") from None
        props = read_properties(self.m.server_dir / "server.properties")
        taken = set(self.web.hub.ports().keys()) | {int(props.get("server-port", "25565") or 25565), self.web.port}
        try:
            message = webmap.set_port(self.m.server_dir, kind, self.m.lock.loader or self.m.config.server.loader, new, taken)
        except webmap.WebMapError as e:
            raise ApiError(400, str(e)) from None
        log.info("%s", message)
        return {"ok": True, "message": message}

    # ------------------------------------------------- playit.gg tunnel
    def tunnel(self, q, b) -> dict:
        from . import tunnel
        status = self.d.tunnel_check(force=q.get("now") == "1")
        return {"address": self.m.config.tunnel_address, "status": status,
                "agent": tunnel.agent_running() if status else None,
                "status_page": tunnel.STATUS_PAGE, "download": tunnel.DOWNLOAD}

    # ------------------------------------------- Bedrock players (Geyser)
    BEDROCK_LOADERS = ("fabric", "quilt", "neoforge", "paper", "purpur")
    GEYSER_CONFIGS = ("config/Geyser-Fabric/config.yml", "config/Geyser-NeoForge/config.yml", "plugins/Geyser-Spigot/config.yml")

    def bedrock(self, q, b) -> dict:
        """Whether Bedrock players (phones, tablets, consoles, Windows) can join through Geyser, and
        the port they use (UDP; Geyser's config says, 19132 until it's written)."""
        loader = self.m.lock.loader or self.m.config.server.loader
        ids = {s.id.lower() for s in self.m.config.mods}
        port = 19132
        for rel in self.GEYSER_CONFIGS:
            path = self.m.server_dir / rel
            if path.exists():
                m = re.search(r"^bedrock:\s*$.*?^\s+port:\s*(\d{2,5})", path.read_text(errors="replace"), re.M | re.S)
                if m:
                    port = int(m.group(1))
                break
        return {"supported": loader in self.BEDROCK_LOADERS, "geyser": "geyser" in ids, "floodgate": "floodgate" in ids,
                "installed": any(x.name.lower().startswith("geyser") for x in self.m.lock.mods), "port": port,
                "minecraft": self.m.lock.minecraft}

    def bedrock_check(self, q, b) -> dict:
        """Preflight both bridge mods, including explicitly offered early builds."""
        if not self.bedrock({}, {})["supported"]:
            raise ApiError(400, "this server type doesn't support Geyser")
        version = self.m.lock.minecraft or self.m.planner().current_version()
        provider = self._modrinth()
        mods = []
        for slug in ("geyser", "floodgate"):
            project = provider.project(slug)
            channel = provider.best_channels([project.id], self.m.loader.mod_loaders, version)[project.id]
            if channel == "unknown":
                raise ApiError(502, f"couldn't check {project.name}; try again in a moment")
            if channel is None:
                raise ApiError(400, f"{project.name} has no {self.m.loader.name} build for Minecraft {version}")
            req = mod_requirements(provider, project.id, self.m.loader.mod_loaders, version, channel=channel)
            if not req["compatible"]:
                raise ApiError(400, req["reason"])
            mods.append({"id": slug, "name": project.name, "source": "modrinth", "channel": channel})
        return {"mods": mods, "minecraft": version}

    # ------------------------------------------- friends asking to join
    def join_requests(self, q, b) -> dict:
        props = read_properties(self.m.server_dir / "server.properties")
        return {"requests": list(self.web.hub.join_requests.get(self.sid, [])),
                "whitelist_on": props.get("white-list", "false") == "true"}

    def answer_join_request(self, q, b) -> dict:
        name = str(b.get("name", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", name):
            raise ApiError(400, "that isn't a Minecraft name")
        message = f"ignored {name}"
        if b.get("allow") is True:
            message = self._players().act("whitelist-add", name)
            log.info("let %s in (whitelist)", name)
        self.web.hub.answer_join_request(self.sid, name)
        return {"ok": True, "message": message}

    def player_action(self, q, b) -> dict:
        if self.d.state == "starting" or (self.d.state == "stopped" and self.d.job):
            # Editing the JSON files now could race with the server starting up.
            raise ApiError(409, "the server is starting; try again in a moment")
        action = str(b.get("action", ""))
        message = self._players().act(action, str(b.get("name", "")), b.get("reason"))
        log.info("players: %s", message)
        return {"ok": True, "message": message}

    # ------------------------------------------------------------- friends
    def _invite_links(self) -> dict:
        """The invite links for friends on this network (local) and for everyone else (internet):
        craft-conductor's invite page with the invite after the #. Each invite carries the share
        certificate's fingerprint, so friends' craft-conductor only ever talks to this computer (over HTTPS)."""
        c = self.m.config.client
        if not c.link_works(time.time()):
            return {}  # (none yet, expired or stopped: nothing that would work to hand out)
        from .cli import lan_ip
        from .join import Invite
        hub = self.web.hub
        share, fp = hub.share_settings(), hub.share_fingerprint()
        name = read_properties(self.m.server_dir / "server.properties").get("motd", "")
        lan = lan_ip()
        out = {"local": Invite(lan, share["port"], c.token, fp).page_link(name) if lan else None, "internet": None}
        if (tunnel := hub.share_tunnel()) is not None:  # friends outside reach the downloads through playit.gg
            out["internet"] = Invite(tunnel[0], tunnel[1], c.token, fp).page_link(name)
        elif share["address"]:
            out["internet"] = Invite(share["address"].strip("[]"), share["port"], c.token, fp).page_link(name)
        bedrock = self.bedrock({}, {})
        if bedrock["supported"] and bedrock["geyser"]:
            from .join import INVITE_PAGE
            from urllib.parse import urlencode
            # Java and download tunnels are TCP; never advertise them as a Bedrock UDP endpoint.
            for kind, host in (("local", lan), ("internet", share["address"].strip("[]"))):
                out[f"bedrock_{kind}"] = (INVITE_PAGE + "#bedrock?" + urlencode({
                    "host": host, "port": bedrock["port"], "name": name.strip()[:60],
                })) if host else None
        return out

    def upload_client_jar(self, q, handler) -> dict:
        """One of your own mod files for players (e.g. a mod that isn't on Modrinth)."""
        from .clientpack import JAR_NAME, client_dir
        from .hub import receive
        if handler.headers.get("X-CRAFT-CONDUCTOR") != "1":
            raise ApiError(403, "missing X-CRAFT-CONDUCTOR header")
        name = q.get("filename", "")
        if not JAR_NAME.fullmatch(name):
            raise ApiError(400, "only .jar files can be added for players")
        folder = client_dir(self.m.config)
        folder.mkdir(parents=True, exist_ok=True)
        receive(handler, folder / name, MAX_UPLOAD)
        log.info("added %s for players", name)
        return {"ok": True, "name": name}

    def remove_client_jar(self, q, b) -> dict:
        from .clientpack import local_jars
        jar = next((p for p in local_jars(self.m.config) if p.name == str(b.get("name", ""))), None)
        if jar is None:
            raise ApiError(404, "no such file")
        jar.unlink()
        log.info("removed %s for players", jar.name)
        return {"ok": True}

    def post_to_discord(self, q, b) -> dict:
        """Post this server's invite to a Discord channel (the links come from here, not the page)."""
        from .discord import SNOWFLAKE, invite_message
        from .properties import read_properties
        hub = self.web.hub
        if hub.is_single:
            raise ApiError(400, "posting to Discord needs `craft-conductor start` (the server list)")
        bot = hub.discord()
        if bot is None:
            raise ApiError(400, "set up the Discord bot first")
        if not self.m.config.client.enabled:
            raise ApiError(400, "turn on the friends' download first")
        guild, channel = str(b.get("guild", "")), str(b.get("channel", ""))
        if not (SNOWFLAKE.fullmatch(guild) and SNOWFLAKE.fullmatch(channel)):
            raise ApiError(400, "pick a Discord server and channel")
        if channel not in {c["id"] for c in bot.channels(guild)}:
            raise ApiError(400, "that channel isn't in that Discord server")
        wanted = [x for x in (b.get("links") or ["internet"])
                  if x in ("internet", "local", "bedrock_internet", "bedrock_local")]
        if not self.m.config.client.link_works(time.time()):
            raise ApiError(400, "the invite links have expired or were stopped; make new links first")
        links = {k: v for k, v in self._invite_links().items() if k in wanted and v}
        if not links:
            raise ApiError(400, "there's no invite link to post yet"
                           + ("; set your internet address (or use your public IP) first" if "internet" in wanted else ""))
        name = read_properties(self.m.server_dir / "server.properties").get("motd") or self.d.server_id
        text, embed = invite_message(str(b.get("message", "")), name, self.m.lock.minecraft or "", links,
                                     expires=self.m.config.client.expires)
        r = bot.post(channel, text, embed)
        hub.remember_discord_channel(guild, channel)
        log.info("posted the friends' invite to Discord")
        return {"ok": True, **r}

    # ------------------------------------------------------ performance
    def performance(self, q, b) -> dict:
        """How fast the server keeps up (TPS/MSPT), measured now and then while someone looks."""
        from . import perf
        d, lk = self.d, self.m.lock
        if getattr(d, "meter", None) is None:
            d.meter = perf.Meter()
        loader = lk.loader or self.m.config.server.loader
        command = perf.command_for(loader, lk.minecraft or "")
        current = d.meter.sample(d.proc, loader, lk.minecraft or "") if d.state == "running" and command else None
        status, words = perf.verdict(current["tps"] if current else None)
        spark = any("spark" in (x.name or "").lower() for x in lk.mods)
        urls = [u for line in (d.proc.tail(300) if d.proc else []) for u in perf.SPARK_URL.findall(line)]
        return {"supported": bool(command), "running": d.state == "running", "current": current,
                "status": status, "words": words, "samples": list(d.meter.samples),
                "spark": spark, "spark_url": urls[-1] if urls else None}

    def lag_status(self, q, b) -> dict:
        from . import lagfinder
        f = self.d.lag
        return {"finder": f.to_dict() if f else None, "report": lagfinder.load_report(self.m.config)}

    def start_lag_finder(self, q, b) -> dict:
        """Look for what's making the server lag: 30 seconds of Minecraft's profiler, then the world's files."""
        if not (self.d.proc and self.d.proc.running):
            raise ApiError(409, "start the server first")
        if self.d.lag is not None and self.d.lag.state == "running":
            raise ApiError(409, "already looking; it takes about half a minute")
        self.d.find_lag()
        return {"ok": True}

    def stop_lag_finder(self, q, b) -> dict:
        f = self.d.lag
        if f is None or f.state != "running":
            raise ApiError(404, "nothing is being looked at")
        f.cancel.set()
        return {"ok": True}

    def spark_profile(self, q, b) -> dict:
        """Profile the server for 30 seconds with the spark mod (power users): the report's link
        appears in the console and on the Dashboard."""
        if not any("spark" in (x.name or "").lower() for x in self.m.lock.mods):
            raise ApiError(400, "add the spark mod first (Mods → Download mods → spark)")
        if not (self.d.proc and self.d.proc.running):
            raise ApiError(409, "start the server first")
        self.d.proc.send("spark profiler start --timeout 30")
        return {"ok": True, "message": "profiling for 30 seconds; the report's link appears here and in the console"}

    # ------------------------------------------------------ Check my setup
    def _doctor_checks(self):
        from . import doctor
        hub = self.web.hub
        info = hub.self_update_info()
        share = None if hub.is_single else hub.share_status()
        return doctor.run(self.m, self.d.state, share=share,
                          self_update={"available": True, **info} if info else None,
                          upnp=None if hub.is_single else hub.upnp_status(), firewall=self._firewall(share))

    def _firewall_ports(self, share: dict | None) -> list[dict]:
        """What should get through Windows Firewall: the Minecraft port (Java listens on it) and
        the friends' download (Craft Conductor itself), when it's on."""
        import sys
        from .java import JavaError
        props = read_properties(self.m.server_dir / "server.properties")
        port = int(props.get("server-port", "25565") or 25565)
        try:
            java = self.m.java.choose(self.m.lock.java_major or 8).binary if self.m.lock.installed else None
        except (JavaError, OSError):
            java = None
        ports = [{"port": port, "label": f"{props.get('motd') or self.d.server_id or 'server'} (Minecraft)", "program": java}]
        if self.m.config.client.enabled and share and share.get("running") and share.get("port"):
            ports.append({"port": int(share["port"]), "label": "friends' downloads", "program": sys.executable})
        return ports

    def _firewall(self, share: dict | None, fresh: bool = False) -> dict | None:
        from . import firewall, upnp
        if not firewall.available():
            return None
        state = firewall.read(fresh=fresh)
        return firewall.assess(state, upnp._lan_address(), self._firewall_ports(share)) if state else None

    def doctor(self, q, b) -> dict:
        from dataclasses import asdict
        from .doctor import BAD, OK, Check
        checks = self._doctor_checks()
        if (st := self.d.tunnel_check()) and st["status"] != "stopped":
            checks.append(Check("tunnel", "playit.gg tunnel", OK if st["status"] == "ok" else BAD, st["words"],
                                "" if st["status"] == "ok" else "playit.gg is an outside service: check its program runs here and status.playit.gg."))
        return {"checks": [asdict(c) for c in checks]}

    def doctor_internet(self, q, b) -> dict:
        """Ask an outside service to connect to the server's port (only when asked to)."""
        from dataclasses import asdict
        from . import doctor
        port = int(read_properties(self.m.server_dir / "server.properties").get("server-port", "25565") or 25565)
        return asdict(doctor.internet_check(self.m.http, port, self.d.state == "running"))

    def doctor_fix(self, q, b) -> dict:
        """Check my setup's fix buttons: each does one small, safe thing (and says what it did)."""
        from . import backup, doctor
        from .properties import write_properties
        action = str(b.get("action", ""))
        if action not in doctor.FIXES:
            raise ApiError(400, "unknown fix")
        offered = {c.action for c in self._doctor_checks()}
        if action not in offered:
            raise ApiError(409, "that's already fine: press Check again")
        props = self.m.server_dir / "server.properties"
        hub = self.web.hub
        if action == "eula":
            if b.get("accept") is not True:
                raise ApiError(400, "accept the EULA first")
            (self.m.server_dir / "eula.txt").write_text("# accepted in Craft Conductor's Check my setup\neula=true\n")
            message = "EULA accepted"
        elif action == "java":
            major = self.m.lock.java_major or 8
            return {**self._job(f"install Java {major}", lambda: f"installed {self.m.java.install(major).release}"),
                    "message": f"Downloading Java {major}: it shows on the Dashboard"}
        elif action == "memory":
            from .setup import total_ram_gb
            gb = max(1, int((total_ram_gb() or 4) - 3))
            configmod.set_value(self.m.config.path, "server", "memory", json.dumps(f"{gb}G"))
            self.m.reload_config()
            message = f"The server gets {gb} GB from its next start"
        elif action == "prune-backups":
            gone = backup.prune(self.m.config.backups.dir, doctor.KEEP_WHEN_FULL)
            message = f"Deleted {len(gone)} old backup(s); the newest {doctor.KEEP_WHEN_FULL} are kept"
        elif action == "port":
            if self.d.state == "running":
                raise ApiError(409, "stop the server first")
            port = hub.free_port(int(read_properties(props).get("server-port", "25565") or 25565) + 1)
            write_properties(props, {"server-port": str(port)})
            message = f"The server now uses port {port}" + ("" if port == 25565 else f": friends connect with your address followed by :{port}")
        elif action == "online-mode":
            write_properties(props, {"online-mode": "true"})
            message = "Accounts are checked again from the next start"
        elif action == "public-ip":
            ip = hub.public_ip()
            s = hub.share_settings()
            hub.save_share(s["port"], ip)
            message = f"Friends outside your home now get {ip}"
        elif action == "firewall":
            # (Windows' administrator prompt shows on this computer: only someone at it can answer)
            if b.get("__local") is not True:
                raise ApiError(403, "that only works in a browser on the server's own computer")
            from . import firewall
            ports = self._firewall_ports(None if hub.is_single else hub.share_status())
            own_java = self.m.java.dir.resolve()

            def ours(program: str | None) -> str | None:  # (only Craft Conductor's own Java is unblocked)
                return program if program and own_java in Path(program).resolve().parents else None
            try:
                firewall.let_through([{**p, "unblock": ours(p["program"])} for p in ports])
            except firewall.FirewallError as e:
                raise ApiError(400, str(e)) from None
            after = self._firewall(None if hub.is_single else hub.share_status(), fresh=True)  # (said only once it's so)
            shut = [p["port"] for p in (after or {}).get("ports", []) if not p["allowed"]] if after and after.get("on") else []
            if shut:
                raise ApiError(400, "Windows still doesn't let port " + ", ".join(map(str, shut)) + " through: "
                                    "see Windows Security → Firewall → Advanced settings → Inbound Rules")
            message = "Windows Firewall lets port " + ", ".join(str(p["port"]) for p in ports) + " through now"
        else:  # upnp
            self.web.hub_api._upnp_consent(True, b)
            st = hub.upnp_sync(True)
            if st["error"]:
                raise ApiError(400, f"your router didn't do it: {st['error']}")
            message = "Your router forwards the ports now"
        log.info("check my setup: %s", message)
        return {"ok": True, "message": message}

    def problem_fix(self, q, b) -> dict:
        """The Dashboard's "What went wrong" buttons (only the ones it offered)."""
        problem = self.d.problem
        kind = str(b.get("kind", ""))
        if kind == "dismiss":
            self.d.problem = None
            return {"ok": True, "message": "Dismissed"}
        offered = [a for a in (problem or {}).get("actions", []) if a.get("kind") == kind]
        if not offered:
            raise ApiError(409, "that's not on offer any more")
        action = offered[0] if len(offered) == 1 else next((a for a in offered if a.get("filename") == b.get("filename")), None)
        if action is None:
            raise ApiError(400, "which one?")
        if kind in ("eula", "port"):
            if kind == "eula" and b.get("accept") is not True:
                raise ApiError(400, "accept the EULA first")
            message = self.doctor_fix(q, {"action": kind, "accept": True})["message"]
        elif kind == "memory-up":
            from .doctor import server_memory_gb
            total = setupmod.total_ram_gb() or 0
            now = server_memory_gb(self.m.config.server.memory)
            gb = int(min(now + 2, max(now, total - 3))) if total else int(now + 2)
            if gb <= now:
                raise ApiError(400, f"this computer ({total:.0f} GB) has no more to give: use fewer mods or a lower view distance")
            configmod.set_value(self.m.config.path, "server", "memory", json.dumps(f"{gb}G"))
            self.m.reload_config()
            message = f"The server gets {gb} GB from its next start"
        elif kind == "java-auto":
            configmod.set_value(self.m.config.path, "java", "version", json.dumps("auto"))
            self.m.reload_config()
            message = "Craft Conductor picks the Java version Minecraft needs from the next start"
        elif kind == "add-mod":
            try:
                self.add_mod(q, {"source": "modrinth", "id": action["id"]})
            except (ApiError, ModError, HttpError) as e:
                raise ApiError(400, f"couldn't add {action['name']} ({e}): look for it in Download mods") from None
            message = f"Added {action['name']}: it's installed with the next update check or start"
        elif kind == "remove-mod":
            mf = next((m for m in self.m.lock.mods if m.filename == action["filename"]), None)
            if mf is None:
                raise ApiError(409, "it's not installed any more")
            removed = []
            for entry in self._configured_with_deps():  # the mod itself, or the mods that brought it
                if entry["key"] == mf.key or any(dep["key"] == mf.key for dep in entry.get("deps", [])):
                    if configmod.remove_mod(self.m.config.path, entry["source"], entry["id"]):
                        removed.append(entry["id"])
            if not removed:
                raise ApiError(409, f"{mf.name} isn't in the mod list: remove it on the Mods page")
            self.m.reload_config()
            message = f"Removed {', '.join(removed)}: it's gone at the next update check or start"
        elif kind == "disable-jar":
            from .manager import UpgradeError
            try:
                message = self.m.set_jar(action["filename"], "disable")
            except UpgradeError as e:
                raise ApiError(400, str(e)) from None
        else:  # backups: the page opens them
            return {"ok": True, "message": ""}
        self.d.problem = {**problem, "fixed": message}
        log.info("what went wrong: %s", message)
        return {"ok": True, "message": message}

    def doctor_report(self) -> bytes:
        from . import doctor
        from .desktop import log_path
        return doctor.report_zip(self.m, self._doctor_checks(), log_path())

    # ------------------------------------------- playing on this computer too
    def play_here_info(self, q, b) -> dict:
        """What running the server and the game on one computer needs (the page warns first)."""
        from .setup import suggested_memory_gb, total_ram_gb
        cfg = self.m.config
        mem = cfg.server.memory
        server_gb = suggested_memory_gb() if mem == "auto" else int(mem[:-1]) / (1024 if mem.endswith("M") else 1)
        props = read_properties(self.m.server_dir / "server.properties")
        total = total_ram_gb()
        return {"installed": self.m.lock.installed, "system_gb": round(total, 1) if total else None,
                "cpus": os.cpu_count() or 1, "server_gb": round(server_gb, 1), "game_gb": cfg.client.memory_gb,
                "mods": len(self.m.lock.mods), "max_players": int(props.get("max-players", "20") or 20)}

    def play_here(self, q, b) -> dict:
        """Set up this computer's Minecraft for this server (the friends' page, pointed at
        localhost), and open it. Only from a browser on this computer (LOCAL_ONLY)."""
        from .clientpack import PackBuilder
        from . import joinui
        if not self.m.lock.installed:
            raise ApiError(400, "the server isn't installed yet")
        old = getattr(self.web.hub, "_play_ui", None)
        if old is not None and not old.done.is_set():
            old.reopen("")  # already open: show it again
            return {"ok": True, "url": old.url}
        port = read_properties(self.m.server_dir / "server.properties").get("server-port", "25565") or "25565"
        try:
            pack = PackBuilder(self.m).build("localhost" if port == "25565" else f"localhost:{port}")
        except ModError as e:
            raise ApiError(400, str(e))
        ui = joinui.JoinUI(None, pack=pack, http=self.m.http)
        url = ui.start()
        self.web.hub._play_ui = ui

        def run():
            try:
                ui.wait()
            finally:
                ui.stop()
        threading.Thread(target=run, daemon=True, name="play-here").start()
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
        return {"ok": True, "url": url}

    def _invite_link(self) -> str | None:
        links = self._invite_links()
        return links.get("internet") or links.get("local")

    def client(self, q, b) -> dict:
        from .clientpack import local_jars
        c = self.m.config.client
        hub = self.web.hub
        preview, error = None, None
        if c.enabled and self.m.lock.installed:
            from .clientpack import PackBuilder
            if getattr(self, "_pack_builder", None) is None or self._pack_builder.m is not self.m:
                self._pack_builder = PackBuilder(self.m)
            try:
                share = hub.share_settings()
                preview = self._pack_builder.build(share["address"] or "<your address>")
            except Exception as e:
                error = str(e)
        works = c.link_works(time.time())
        mod_details = []
        if c.mods:
            try:
                projects = self._modrinth().projects(list(c.mods))
                by_name = {}
                for p in projects.values():
                    by_name[p.get("id", "")] = p
                    by_name[p.get("slug", "")] = p
                mod_details = [{"slug": slug, "id": (by_name.get(slug) or {}).get("id", ""),
                                "name": (by_name.get(slug) or {}).get("title") or slug}
                               for slug in c.mods]
            except (ModError, HttpError):
                mod_details = [{"slug": slug, "id": "", "name": slug} for slug in c.mods]
        return {
            "available": not hub.is_single,
            "enabled": c.enabled, "mods": c.mods, "mod_details": mod_details, "memory_gb": c.memory_gb,
            "mods_on_server": self._players_mods_on_server(c.mods),
            "link": self._invite_link() if c.enabled else None,
            "links": self._invite_links() if c.enabled else {},
            # How long the links work: shared links can't be single-use, so they expire instead.
            "expires": c.expires or None, "expired": bool(c.enabled and c.token and not works),
            "link_days": c.link_days, "link_day_choices": list(configmod.LINK_DAYS),
            "share": hub.share_status() if not hub.is_single else None,
            "pack": preview, "pack_error": error,
            "loader": self.m.config.server.loader, "minecraft": self.m.lock.minecraft or "",
            "local_mods": [p.name for p in local_jars(self.m.config)],
        }

    def _players_mods_on_server(self, slugs: list[str]) -> list[str]:
        """Which of the mods picked for players are also among the server's own mods."""
        listed = {s.id for s in self.m.config.mods if s.source == "modrinth"}
        return [x for x in slugs if x in listed]

    def _also_on_server(self, slugs: list[str]) -> tuple[list[dict], list[dict]]:
        """Mods picked for players that run on both sides (Modrinth's environment tags) are also
        added to the server's own mods, with what they need, the way any server mod is. Returns
        what was added (with its dependencies) and what couldn't be (with why). Mods that only
        run on players' computers, and ones the server already has, are left as they are."""
        from .browse import environment
        added, skipped = [], []
        if not self.m.loader.mod_loaders or self.m.loader.mods_folder != "mods":
            return added, skipped  # (plain Minecraft, or plugins: players need nothing)
        provider = self._modrinth()
        for slug in slugs:
            try:
                project = provider.project(slug)
            except (ModError, HttpError):
                continue  # (the download's own check says what's wrong with it)
            if environment(project.client_side, project.server_side) != "both":
                continue
            if any(s.source == "modrinth" and s.id in (slug, project.id, project.slug) for s in self.m.config.mods):
                continue
            try:
                deps = self._list_server_mod("modrinth", project, required=project.server_side == "required")
            except ApiError as e:
                skipped.append({"name": project.name, "reason": str(e)})
                continue
            added.append({"name": project.name, "deps": deps})
        return added, skipped

    def save_client(self, q, b) -> dict:
        if self.web.hub.is_single:
            raise ApiError(400, "friend downloads need `craft-conductor start` (the server list)")
        path = self.m.config.path
        c = self.m.config.client
        from .clientpack import checked_link_days, make_link, renew_link
        if "enabled" in b:
            configmod.set_value(path, "client", "enabled", "true" if b["enabled"] is True else "false")
            if b["enabled"] is True and (not c.token or (c.expires and c.expires <= time.time())):
                make_link(path, c.link_days)  # (switched on again after the old link ran out: a new one)
        if "link_days" in b:
            try:
                if c.link_works(time.time()):
                    renew_link(path, b["link_days"])  # this link, from now
                else:  # (a stopped or expired link stays stopped: only new links get it)
                    configmod.set_value(path, "client", "link_days", str(checked_link_days(b["link_days"])))
            except ConfigError as e:
                raise ApiError(400, str(e)) from None
        if "mods" in b:
            mods = b["mods"]
            if not isinstance(mods, list) or not all(isinstance(x, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", x)
                                                     for x in mods):
                raise ApiError(400, "mods must be a list of Modrinth project names")
            before = list(c.mods)
            mods = list(dict.fromkeys(mods))
            configmod.set_value(path, "client", "mods", json.dumps(mods))
            self.m.reload_config()
            also, skipped = self._also_on_server([x for x in mods if x not in before])
            drop = b.get("remove_from_server")
            if drop is not None:  # "remove it from the server too": a mod that's no longer on the players' list
                if not isinstance(drop, list) or not all(isinstance(x, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", x)
                                                         for x in drop):
                    raise ApiError(400, "remove_from_server must be a list of mod names")
                for x in drop:
                    if x not in mods and configmod.remove_mod(path, "modrinth", x):
                        log.info("removed %s from the server's mods too (it left the players' list)", x)
        if "memory_gb" in b:
            try:
                memory = int(b["memory_gb"])
            except (TypeError, ValueError):
                raise ApiError(400, "memory must be a number") from None
            if not 1 <= memory <= 32:
                raise ApiError(400, "memory must be between 1 and 32 GB")
            configmod.set_value(path, "client", "memory_gb", str(memory))
        self.m.reload_config()
        self.web.hub.update_share()
        log.info("friend download settings saved")
        out = self.client(q, {})
        if "mods" in b:
            out.update(also_on_server=also, server_skipped=skipped)  # (this save's doing; the page says so once)
        return out

    def new_client_link(self, q, b) -> dict:
        from .clientpack import make_link
        try:
            make_link(self.m.config.path, b.get("days", self.m.config.client.link_days))
        except ConfigError as e:
            raise ApiError(400, str(e)) from None
        self.m.reload_config()
        self.web.hub.update_share()
        log.info("made a new invite link; the old one no longer works")
        return self.client(q, {})

    def stop_client_link(self, q, b) -> dict:
        """Stop the invite link now, without making a new one (friends who set up keep playing)."""
        from .clientpack import stop_link
        if not self.m.config.client.token:
            raise ApiError(404, "there's no invite link to stop")
        stop_link(self.m.config.path)
        self.m.reload_config()
        self.web.hub.update_share()
        log.info("stopped the invite link; it no longer works")
        return self.client(q, {})

    def client_search(self, q, b) -> dict:
        from .loaders import LOADERS
        loaders = LOADERS[self.m.config.server.loader].mod_loaders
        if not loaders or LOADERS[self.m.config.server.loader].mods_folder != "mods":
            return {"results": []}  # vanilla, or Paper: players join with plain Minecraft
        query = q.get("q", "").strip()
        if not query and q.get("top") != "1":
            return {"results": []}
        minecraft = self.m.lock.minecraft or (
            None if self.m.config.server.minecraft == "latest" else self.m.config.server.minecraft)
        provider = self._modrinth()
        results = provider.search(query, loaders, limit=20, index="relevance" if query else "downloads",
                                  side="client", minecraft=minecraft)
        listed = set(self.m.config.client.mods)
        for r in results:
            r["listed"] = r["id"] in listed or r["slug"] in listed
        if not minecraft:
            return {"results": results}
        # Players' mods follow the server's release channel.
        return keep_buildable(provider.best_channels([r["id"] for r in results], loaders, minecraft), results,
                              early=self.m.config.updates.mod_channel != "release")

    # ------------------------------------------------------------- backups
    def backups(self, q, b) -> dict:
        from . import areas, snapshots
        checks = areas.load_checks(self.m.config.backups.dir)
        notes = snapshots.listing(self.m.config.backups.dir)
        return {"backups": [{"name": p.name, "size": p.stat().st_size, "time": p.stat().st_mtime, "check": checks.get(p.name),
                             **notes.get(p.name, {})}
                            for p in reversed(backup.list_backups(self.m.config.backups.dir))]}

    def backup_changes(self, q, b) -> dict:
        """What rolling back to a backup would undo (what changed since it was made)."""
        from . import snapshots
        path = self._backup_path(q)
        note = snapshots.load(path)
        if note is None:
            return {"snapshot": False, "undo": None}
        return {"snapshot": True, "undo": snapshots.changes(note, snapshots.describe(self.m))}

    def _backup_path(self, b) -> Path:
        name = str(b.get("name", ""))
        path = self.m.config.backups.dir / name
        if Path(name).name != name or not name.endswith(backup.SUFFIX) or not path.is_file():
            raise ApiError(404, "no such backup")
        return path

    def _level(self) -> str:
        return read_properties(self.m.server_dir / "server.properties").get("level-name") or "world"

    def check_backup(self, q, b) -> dict:
        """Read a whole backup to make sure it can be restored."""
        from . import areas
        path = self._backup_path(b)
        level = self._level()

        def run():
            r = areas.check(path.parent, path.name, level)
            if not r["ok"]:
                raise RuntimeError(f"{path.name} doesn't look right: {r['detail']}")
            return f"{path.name} is fine: {r['detail']}"
        return self._job("check backup", run)

    def restore_area(self, q, b) -> dict:
        """Put back one area of the world from a backup (after backing up what's there now)."""
        from . import areas
        path = self._backup_path(b)
        if self.d.state != "stopped":
            raise ApiError(409, "stop the server before putting an area back")
        try:
            coords = [int(b.get(k)) for k in ("x1", "z1", "x2", "z2")]
        except (TypeError, ValueError):
            raise ApiError(400, "the corners are whole numbers (x and z, from F3 in the game)") from None
        if any(abs(c) > 30_000_000 for c in coords):
            raise ApiError(400, "those coordinates are outside the world")
        dimension = str(b.get("dimension", "overworld"))
        level = self._level()
        try:
            areas.dimension_dir(level, dimension)
        except areas.AreaError as e:
            raise ApiError(400, str(e)) from None
        if max(abs(coords[2] - coords[0]), abs(coords[3] - coords[1])) >= areas.MAX_BLOCKS:
            raise ApiError(400, f"put back at most {areas.MAX_BLOCKS} × {areas.MAX_BLOCKS} blocks at a time")

        def run():
            before = backup.create(self.m.server_dir, self.m.config.backups.dir, "before-putting-an-area-back",
                                   self.m.config.backups.exclude)
            r = areas.restore_area(path, self.m.server_dir, level, dimension, *coords)
            return (f"put back {r['chunks']} chunk(s) from {path.name}; what was there is in the backup {before.name}")
        return self._job("put back an area", run)

    def create_backup(self, q, b) -> dict:
        label = re.sub(r"[^A-Za-z0-9_-]", "_", str(b.get("label") or "manual"))[:40]
        return self._job("backup", self.d.backup_now, label)

    # ---------------------------------------------------------- open folder
    FOLDERS = ("server", "files", "world", "mods", "config", "logs", "crash", "backups", "exports", "manual", "java",
               "old-java")

    def folder(self, what: str) -> Path:
        """One of the server's folders, by name (never an arbitrary path)."""
        cfg, sd = self.m.config, self.m.server_dir
        if what == "world":
            from . import world
            return world.level_dir(sd)  # (never outside the server: level-name is checked)
        paths = {"server": cfg.root, "files": sd, "mods": sd / "mods", "config": sd / "config", "logs": sd / "logs",
                 "crash": sd / "crash-reports", "backups": cfg.backups.dir, "exports": self.exports_dir,
                 "manual": cfg.manual_dir, "java": self.m.java.dir, "old-java": cfg.state_dir / "java",
                 "reports": cfg.state_dir / "logs"}
        if what not in paths:
            raise ApiError(400, "unknown folder")
        return paths[what]

    def open_folder(self, q, b) -> dict:
        from . import opener
        where = self.folder(str(b.get("what", "")))
        if not where.exists():
            if str(b.get("what")) in ("world", "logs", "crash", "java", "old-java"):
                raise ApiError(404, f"{where} doesn't exist yet (it appears once the server has run)")
            where.mkdir(parents=True, exist_ok=True)
        if not opener.open_path(where):
            raise ApiError(500, f"couldn't open a file manager; the folder is {where}")
        return {"ok": True, "path": str(where)}

    def save_config(self, q, b) -> dict:
        """Save a mod's config file (the previous version is kept in .craft-conductor/config-backups/)."""
        text = b.get("text")
        if not isinstance(text, str):
            raise ApiError(400, "nothing to save")
        modified = b.get("modified")
        result = configs.write(self.m.server_dir, self.m.config.state_dir / "config-backups", str(b.get("path", "")),
                               text, float(modified) if isinstance(modified, (int, float)) else None)
        log.info("saved %s", b.get("path"))
        return {**result, "running": bool(self.d.proc and self.d.proc.running)}

    def betas(self, q, b) -> dict:
        try:
            versions = self.m.mojang.betas()
        except Exception as e:
            raise ApiError(502, f"couldn't load Minecraft's beta versions: {e}") from None
        return {"betas": versions, "current": self.m.lock.minecraft,
                "copies": not self.web.hub.is_single}

    def test_beta(self, q, b) -> dict:
        """Try a beta Minecraft on a copy of this server; the server itself isn't touched."""
        from . import transfer
        hub = self.web.hub
        if hub.is_single:
            raise ApiError(400, "testing betas needs `craft-conductor start` (the server list)")
        version = str(b.get("version", ""))
        if version not in self.m.mojang.betas():
            raise ApiError(400, "pick one of the beta versions in the list")
        name = read_properties(self.m.server_dir / "server.properties").get("motd") or self.sid

        def prepare(root: Path) -> None:
            path = root / configmod.CONFIG_NAME
            configmod.set_value(path, "server", "minecraft", json.dumps(version))
            configmod.set_value(path, "updates", "strategy", '"mods-only"')  # stays on the beta
            for spec in configmod.load(root).mods:  # run with whichever mods support the beta
                configmod.remove_mod(path, spec.source, spec.id)
                configmod.append_mod(path, ModSpec(spec.source, spec.id, required=False))

        def run():
            running = self.d.proc and self.d.proc.running
            if running:
                self.d.proc.send("save-off")
                self.d.proc.send("save-all flush")
                time.sleep(5)
            tmp = hub.staging_dir / f"beta-{time.time_ns()}"
            try:
                archive = transfer.export(self.m, tmp / "copy.zip")
            finally:
                if running and self.d.proc and self.d.proc.running:
                    self.d.proc.send("save-on")
            try:
                sid = hub.import_archive(archive, f"{name} (beta {version})", prepare)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            copy = hub.get(sid)
            if copy is None or not copy.submit("install beta", copy.check_for_updates, True, version):
                raise RuntimeError("the copy was made but couldn't start installing; open it and press Update")
            return f"made a copy, \"{name} (beta {version})\", and is installing Minecraft {version} on it"
        return self._job("beta test copy", run)

    def rehearsal_status(self, q, b) -> dict:
        from . import rehearsal
        r = self.d.rehearsal
        return {"rehearsal": r.to_dict() if r else None, "report": rehearsal.load_report(self.m.config)}

    def start_rehearsal(self, q, b) -> dict:
        """Try the update on a copy of this server first (see rehearsal.py); the server isn't touched."""
        from . import rehearsal
        if not self.m.lock.installed:
            raise ApiError(400, "the server isn't installed yet")
        target = b.get("target") or None
        if target is not None and not (isinstance(target, str) and re.fullmatch(r"[A-Za-z0-9._+ -]{1,40}", target)):
            raise ApiError(400, "that isn't a Minecraft version")
        minutes = b.get("minutes", rehearsal.WATCH_DEFAULT)
        if not isinstance(minutes, int) or isinstance(minutes, bool) or not 1 <= minutes <= rehearsal.WATCH_MAX:
            raise ApiError(400, f"watch the copy for 1 to {rehearsal.WATCH_MAX} minutes")
        daemons = self.web.hub.daemons.values() if not self.web.hub.is_single else [self.d]
        if any(d.rehearsal is not None and d.rehearsal.state == "running" for d in daemons):
            raise ApiError(409, "an update rehearsal is already running; wait for it or stop it")
        if self.d.job:
            raise ApiError(409, f"busy: {self.d.job['name']} is running")
        r = self.d.start_rehearsal(target, minutes)
        return {"ok": True, "id": r.id}

    def stop_rehearsal(self, q, b) -> dict:
        r = self.d.rehearsal
        if r is None or r.state != "running":
            raise ApiError(404, "no rehearsal is running")
        r.cancel.set()
        return {"ok": True}

    def remove_and_upgrade(self, q, b) -> dict:
        lag = (self.d.last_check or {}).get("lagging")
        version, mods = str(b.get("version", "")), b.get("mods")
        if not lag or lag["version"] != version:
            raise ApiError(409, "that's out of date; check for updates and try again")
        allowed = {x["config"] for x in lag["mods"] if x["config"]}
        if not isinstance(mods, list) or not mods or not set(map(str, mods)) <= allowed:
            raise ApiError(400, "pick mods from the list of mods holding the update back")
        return self._job("update", self.d.remove_and_upgrade, version, [str(x) for x in mods])

    def replace_world(self, q, b) -> dict:
        """Swap the server's world for another one (a backup is made first)."""
        from . import world
        if self.d.state != "stopped":
            raise ApiError(409, "stop the server before replacing its world")
        choice = str(b.get("world", ""))
        if not re.fullmatch(r"(save:)?[a-f0-9]{16}", choice):
            raise ApiError(400, "pick a world first")
        source = self.web.hub.world_source(choice)
        dest = self.folder("world")  # (refused now, before anything is touched, if level-name isn't plain)

        def run():
            sd, cfg = self.m.server_dir, self.m.config
            if dest.exists():
                path = backup.create(sd, cfg.backups.dir, "before-new-world", cfg.backups.exclude)
                log.info("backed up the old world to %s", path.name)
            info = world.replace(source, dest)
            if source.parent.parent == self.web.hub.staging_dir:
                shutil.rmtree(source.parent, ignore_errors=True)
            return f"the world is now {info.get('name') or dest.name}; press Start to play it"
        return self._job("replace world", run)

    # --------------------------------------------------------------- export
    @property
    def exports_dir(self) -> Path:
        hub = self.web.hub
        return (hub.exports_dir if not hub.is_single else self.m.config.root / "exports") / self.sid

    def exports(self, q, b) -> dict:
        d = self.exports_dir
        files = sorted(d.glob("*.craft-conductor.zip"), key=lambda p: p.stat().st_mtime, reverse=True) if d.is_dir() else []
        return {"folder": str(d), "exports": [{"name": p.name, "size": p.stat().st_size, "created": p.stat().st_mtime}
                                               for p in files]}

    def export_file(self, name: str) -> Path:
        path = self.exports_dir / name
        if Path(name).name != name or not name.endswith(".craft-conductor.zip") or not path.is_file():
            raise ApiError(404, "no such export")
        return path

    def export(self, q, b) -> dict:
        from . import transfer
        include_backups = bool(b.get("backups"))

        def run():
            running = self.d.proc and self.d.proc.running
            if running:  # write everything to disk and hold it there while copying
                self.d.proc.send("save-off")
                self.d.proc.send("save-all flush")
                time.sleep(5)
            try:
                from .properties import read_properties
                name = read_properties(self.m.server_dir / "server.properties").get("motd") or self.sid
                path = transfer.export(self.m, self.exports_dir / transfer.export_name(name), include_backups)
            finally:
                if running and self.d.proc and self.d.proc.running:
                    self.d.proc.send("save-on")
            return f"exported to {path.name}"
        return self._job("export", run)

    def delete_export(self, q, b) -> dict:
        self.export_file(str(b.get("name", ""))).unlink()
        return {"ok": True}

    def restore_backup(self, q, b) -> dict:
        name = str(b.get("name", ""))
        path = self.m.config.backups.dir / name
        if Path(name).name != name or not path.is_file():
            raise ApiError(404, "no such backup")
        if self.d.state != "stopped":
            raise ApiError(409, "stop the server before restoring a backup")

        def run():
            from . import snapshots
            return snapshots.roll_back(path, self.m)
        return self._job("roll back", run)

    # ----------------------------------------------------------------- java
    def _old_java(self) -> tuple[Path | None, int]:
        """The Java folder servers had of their own before 0.23 (unused now, deleted by hand), and its size."""
        old = self.m.config.state_dir / "java"
        try:
            if not old.is_dir() or old.is_symlink() or old.resolve() == self.m.java.dir.resolve():
                return None, 0
            key = (str(old), old.stat().st_mtime_ns)
        except OSError:
            return None, 0
        cached = getattr(self, "_old_java_size", None)
        if not cached or cached[0] != key:
            from .java import folder_size
            size = folder_size(old)
            self._old_java_size = cached = (key, size)
        return old, cached[1]

    def java(self, q, b) -> dict:
        jm, lk = self.m.java, self.m.lock
        choice = None
        if lk.java_major:
            try:
                c = jm.choose(lk.java_major, offers=True)
                choice = {"source": c.source, "binary": c.binary, "major": c.major, "wanted": c.wanted,
                          "release": c.release, "note": c.note,
                          "also": [u.get("name") or Path(u["root"]).name for u in jm.users_of(c)] if c.binary else [],
                          "newer": [{"major": f.info.major, "path": f.path, "source": f.source} for f in c.newer]}
            except JavaError as e:
                choice = {"source": "missing", "note": str(e), "also": [], "newer": []}
        users = jm.store.users()
        shared = []
        for major, rels in jm.store.releases().items():
            used = [u.get("name") or Path(u["root"]).name for u in users if u.get("shared") and u.get("major") == major]
            shared.append({"major": major, "used_by": used, "releases": [
                {"release": j.release, "path": str(j.binary), "bytes": j.size, "running": bool(jm.store.running(j)),
                 "newest": i == 0} for i, j in enumerate(rels)]})
        old, old_bytes = self._old_java()
        return {
            "required": lk.java_major,
            "forced": self.m.config.java_version,
            "auto_install": self.m.config.java_auto_install,
            "choice": choice,
            "store": str(jm.dir),
            "shared": shared,
            "found": [{"path": f.path, "source": f.source, "major": f.info.major if f.info else None,
                       "arch": f.info.arch if f.info else None, "vendor": f.info.vendor if f.info else "",
                       "version": f.info.version if f.info else "", "problem": f.problem} for f in jm.found()],
            "configured": [{"major": k, "path": v} for k, v in sorted(self.m.config.java_versions.items())],
            "default": self.m.config.java_default,
            "old_folder": str(old) if old else None,
            "old_bytes": old_bytes,
        }

    def java_scan(self, q, b) -> dict:
        """Look for Java on this computer again (each new one is run with -version once)."""
        found = self.m.java.found(refresh=True)
        return {"ok": True, "count": sum(1 for f in found if f.info)}

    def java_install(self, q, b) -> dict:
        major = int(b.get("major", 0))
        if not 8 <= major <= 99:
            raise ApiError(400, "invalid Java version")
        return self._job(f"install Java {major}", lambda: f"installed {self.m.java.install(major).release}")

    def java_update(self, q, b) -> dict:
        def run():
            changed = self.m.java.update()
            if not changed:
                return "the shared Java is up to date"
            return "; ".join(f"Java {major}: {new} (servers move to it at their next start)" for major, _, new in changed)
        return self._job("update the shared Java", run)

    def java_remove(self, q, b) -> dict:
        major = b.get("major")
        if not isinstance(major, int) or isinstance(major, bool):
            raise ApiError(400, "invalid Java version")
        try:
            if not self.m.java.remove(major):
                raise ApiError(404, f"there's no shared Java {major}")
        except JavaError as e:
            raise ApiError(409, str(e)) from None
        return {"ok": True}

    def java_use(self, q, b) -> dict:
        """What the server runs on from its next start: "auto" (the version Minecraft needs), a newer
        version (asked for: some loaders and older mods break on one), a Java found on this computer
        (only one the scan found, never any path), or "shared" (drop its own Java for the shared one)."""
        cfg, required = self.m.config, self.m.lock.java_major
        value = str(b.get("version", "auto"))
        path = b.get("path")
        if value == "shared":
            if not required:
                raise ApiError(400, "nothing is installed yet")
            wanted = cfg.java_version or required
            configmod.unset_value(cfg.path, "java.versions", str(wanted))
            self.m.reload_config()
            return {"ok": True, "note": "applies the next time the server starts"}
        if value != "auto":
            if not value.isdigit():
                raise ApiError(400, 'use a major version such as 21, or "auto"')
            if required and int(value) < required:
                raise ApiError(400, f"Minecraft {self.m.lock.minecraft} needs Java {required}+")
        if path is not None:
            match = next((f for f in self.m.java.found() if f.path == path), None)
            if match is None or match.info is None or match.problem:
                raise ApiError(400, "that Java isn't one Craft Conductor found on this computer: press Look again")
            major = match.info.major
            if value != ("auto" if major == required else str(major)):
                raise ApiError(400, f"that's Java {major}")
            configmod.set_value(cfg.path, "java.versions", str(major), json.dumps(match.path))
        configmod.set_value(cfg.path, "java", "version", json.dumps(value) if value == "auto" else value)
        self.m.reload_config()
        return {"ok": True, "note": "applies the next time the server starts"}

    # ------------------------------------------------------------- settings
    SETTINGS = {
        # key: (table, toml key, type)
        "memory": ("server", "memory", str),
        "aikar_flags": ("server", "aikar_flags", bool),
        "find_lag": ("server", "find_lag", bool),
        "cpu_cores": ("server", "cpu_cores", int),
        "priority": ("server", "priority", str),
        "restart_on_crash": ("server", "restart_on_crash", bool),
        "strategy": ("updates", "strategy", str),
        "mod_channel": ("updates", "mod_channel", str),
        "auto_upgrade": ("updates", "auto_upgrade", bool),
        "check_interval": ("updates", "check_interval", str),
        "warn_minutes": ("updates", "warn_minutes", list),
        "wait_for_empty": ("updates", "wait_for_empty", bool),
        "rehearse": ("updates", "rehearse", bool),
        "verify_boot": ("updates", "verify_boot", bool),
        "backups_keep": ("backups", "keep", int),
        "discord_webhook": ("notify", "discord_webhook", str),
        "schedule_restart": ("schedule", "restart", str),
        "schedule_backup": ("schedule", "backup", str),
        "restart_when_empty": ("schedule", "restart_when_empty", bool),
        "backup_copy_to": ("backups", "copy_to", str),
        "backup_copy_keep": ("backups", "copy_keep", int),
        "tunnel_address": ("tunnel", "address", str),
    }

    def settings(self, q, b) -> dict:
        c = self.m.config
        interval = c.updates.check_interval
        return {
            "memory": c.server.memory, "aikar_flags": c.server.aikar_flags, "find_lag": c.server.find_lag,
            "cpu_cores": c.server.cpu_cores, "priority": c.server.priority, "cpu_count": limits.cpu_count(),
            "can_pin_cores": limits.can_pin_cores(),
            "restart_on_crash": c.restart_on_crash,
            "strategy": c.updates.strategy, "mod_channel": c.updates.mod_channel,
            "auto_upgrade": c.updates.auto_upgrade,
            "check_interval": f"{interval // 3600}h" if interval % 3600 == 0 else f"{interval // 60}m",
            "warn_minutes": c.updates.warn_minutes, "wait_for_empty": c.updates.wait_for_empty,
            "verify_boot": c.updates.verify_boot, "rehearse": c.updates.rehearse, "backups_keep": c.backups.keep,
            "discord_webhook": c.discord_webhook,
            **self._schedule_info(),
            "tunnel_address": c.tunnel_address,
            "port": int(read_properties(self.m.server_dir / "server.properties").get("server-port", "25565") or 25565),
            "properties": serverprops.current(read_properties(self.m.server_dir / "server.properties")),
            "properties_schema": serverprops.schema(),
            "choices": {"strategy": configmod.STRATEGIES, "mod_channel": configmod.CHANNELS},
        }

    def _schedule_info(self) -> dict:
        import datetime as dt
        from . import schedule
        c = self.m.config
        out = {"schedule_restart": c.schedule.restart, "schedule_backup": c.schedule.backup,
               "restart_when_empty": c.schedule.restart_when_empty,
               "backup_copy_to": str(c.backups.copy_to or ""), "backup_copy_keep": c.backups.copy_keep,
               "backup_copy_ok": c.backups.copy_to is None or c.backups.copy_to.is_dir()}
        for name in ("restart", "backup"):
            expr = getattr(c.schedule, name)
            nxt = schedule.parse(expr).next_after(dt.datetime.now()) if expr else None
            out[f"schedule_{name}_words"] = schedule.describe(expr)
            out[f"schedule_{name}_next"] = nxt.timestamp() if nxt else None
        return out

    def save_settings(self, q, b) -> dict:
        b = dict(b)
        advanced = serverprops.validate(b.pop("properties", None))
        port = b.pop("port", None)
        if port is not None:
            try:
                port = int(port)
            except (TypeError, ValueError):
                raise ApiError(400, "the port must be a number") from None
            if not 1024 <= port <= 65535:
                raise ApiError(400, "the port must be between 1024 and 65535")
            clash = self.web.hub.ports(exclude=self.sid).get(port)
            if clash:
                raise ApiError(400, f"port {port} is already used by another server here ({clash})")
        path = self.m.config.path
        original = path.read_text()
        try:
            for key, value in b.items():
                if key not in self.SETTINGS:
                    raise ApiError(400, f"unknown setting {key}")
                table, toml_key, kind = self.SETTINGS[key]
                if kind is bool:
                    literal = "true" if value is True else "false" if value is False else None
                elif kind is int:
                    try:
                        literal = str(int(value))
                    except (TypeError, ValueError):
                        raise ApiError(400, f"{key} must be a whole number") from None
                elif kind is list:
                    literal = json.dumps([int(x) for x in value])
                else:
                    literal = json.dumps(str(value))
                if literal is None:
                    raise ApiError(400, f"{key} must be true or false")
                configmod.set_value(path, table, toml_key, literal)
            configmod.parse(self.m.config.root, tomllib.loads(path.read_text()))  # validate
            self.m.reload_config()
        except Exception:
            path.write_text(original)
            raise
        props = self.m.server_dir / "server.properties"
        existing = read_properties(props)
        changed = {k: v for k, v in advanced.items() if existing.get(k, serverprops.BY_KEY[k].default) != v}
        if port is not None and str(port) != existing.get("server-port"):
            changed["server-port"] = str(port)
        if changed:
            self.m.server_dir.mkdir(parents=True, exist_ok=True)
            write_properties(props, changed)
        log.info("settings saved")
        return {"ok": True}
