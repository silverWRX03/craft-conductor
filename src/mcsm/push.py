"""Phone notifications (the installed app): Web Push to the phones and computers that asked for it.

A device turns notifications on in the app; its browser gives an address at its push service (Google,
Apple, Mozilla or Microsoft) and two keys. Every message Craft Conductor would post to Discord (a
crash, a friend asking to join, an update held back, lag...) is then encrypted for each device and
handed to its push service, which delivers it even when the app is closed.

Kept in ``<hub state>/push.json`` (readable by its owner only): this computer's VAPID key, and the
subscriptions. Only the push services' own addresses are accepted, so a subscription can't make
Craft Conductor send requests anywhere else.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from . import __version__, webpush

log = logging.getLogger(__name__)

FILE = "push.json"
MAX_SUBSCRIPTIONS = 20
SUBJECT = "https://github.com/silverWRX03/craft-conductor"
TTL = 24 * 3600          # a phone that's off gets it when it's back on, within a day
PUSH_HOSTS = re.compile(
    r"(fcm\.googleapis\.com|android\.googleapis\.com|updates\.push\.services\.mozilla\.com|"
    r"push\.services\.mozilla\.com|web\.push\.apple\.com|[a-z0-9-]+\.push\.apple\.com|"
    r"[a-z0-9-]+\.notify\.windows\.com)")


# What each device can choose to hear about (Craft Conductor settings → Phone app); all but
# "status" (the server started or stopped) are on for a new device.
KINDS = {
    "crash": "A server crashed, stopped unexpectedly or wouldn't start",
    "join": "A friend asks to join, or was let in",
    "updates": "Updates: available, installed, held back or waiting on mods",
    "lag": "The server keeps lagging",
    "backups": "A backup doesn't look right",
    "tunnel": "The playit.gg tunnel stopped or works again",
    "computer": "This computer: low disk space, a busy CPU, low memory",
    "status": "A server started",
    "other": "Everything else",
}
DEFAULT_KINDS = [k for k in KINDS if k != "status"]
_KIND_WORDS = [  # (the first that matches; checked against the message in lower case)
    ("crash", ("crashed", "stopped unexpectedly", "didn't start", "did not finish starting", "failed")),
    ("join", ("asks to join", "was let in")),
    ("lag", ("falling behind", "lagging", "lag")),
    ("backups", ("backup",)),
    ("tunnel", ("tunnel",)),
    ("updates", ("update", "is out", "held back", "is available", "rolled back")),
    ("status", ("server is up",)),
]


def kind_of(message: str) -> str:
    """Which kind of notification a server's message is (see KINDS)."""
    text = message.lower()
    for kind, words in _KIND_WORDS:
        if any(w in text for w in words):
            return kind
    return "other"


class PushError(ValueError):
    pass


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # (a push service answers; it never sends the message anywhere else)


_OPENER = urllib.request.build_opener(_NoRedirects)


def allowed_endpoint(endpoint: str) -> bool:
    u = urlparse(endpoint)
    return u.scheme == "https" and u.port in (None, 443) and bool(u.hostname) and \
        bool(PUSH_HOSTS.fullmatch(u.hostname.lower())) and len(endpoint) <= 1000


class Push:
    def __init__(self, state_dir: Path):
        self.path = state_dir / FILE
        self.lock = threading.Lock()
        self.queue: queue.Queue = queue.Queue(maxsize=200)
        self.thread: threading.Thread | None = None
        self.sent = 0
        self.last_error = ""

    # --------------------------------------------------------------- the file
    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(FILE + ".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        try:
            tmp.chmod(0o600)  # (the private key)
        except OSError:
            pass
        os.replace(tmp, self.path)

    def _key(self, data: dict) -> int:
        if not data.get("vapid"):
            data["vapid"] = hex(webpush.new_private())
            self._save(data)
        return int(data["vapid"], 16)

    def public_key(self) -> str:
        """What a browser subscribes with (applicationServerKey)."""
        with self.lock:
            data = self._load()
            return webpush.b64u(webpush.public_bytes(webpush.public_of(self._key(data))))

    # -------------------------------------------------------- subscriptions
    def subscriptions(self) -> list[dict]:
        with self.lock:
            return [{**{k: s[k] for k in ("id", "name", "created", "service")}, "kinds": s.get("kinds", DEFAULT_KINDS)}
                    for s in self._load().get("subscriptions", [])]

    def kinds_for(self, endpoint: str) -> list[str] | None:
        with self.lock:
            sub = next((s for s in self._load().get("subscriptions", []) if s["endpoint"] == endpoint), None)
        return sub.get("kinds", DEFAULT_KINDS) if sub else None

    def set_kinds(self, endpoint: str, kinds: list) -> list[str]:
        """What this device wants to hear about (its own push address names it)."""
        chosen = [k for k in KINDS if k in {str(x) for x in kinds or []}]
        with self.lock:
            data = self._load()
            sub = next((s for s in data.get("subscriptions", []) if s["endpoint"] == endpoint), None)
            if sub is None:
                raise PushError("this device doesn't have notifications on")
            sub["kinds"] = chosen
            self._save(data)
        return chosen

    def subscribe(self, endpoint: str, p256dh: str, auth: str, name: str) -> dict:
        if not isinstance(endpoint, str) or not allowed_endpoint(endpoint):
            raise PushError("that isn't a push service Craft Conductor knows (Google, Apple, Mozilla or Microsoft)")
        try:
            webpush.point_from(webpush.unb64u(str(p256dh)))
            if len(webpush.unb64u(str(auth))) != 16:
                raise ValueError
        except (ValueError, TypeError):
            raise PushError("the browser's notification keys aren't right; try turning notifications on again") from None
        name = re.sub(r"[^\w .,'()-]", "", str(name or ""))[:40].strip() or "A device"
        with self.lock:
            data = self._load()
            self._key(data)
            subs = [s for s in data.get("subscriptions", []) if s["endpoint"] != endpoint]
            if len(subs) >= MAX_SUBSCRIPTIONS:
                raise PushError(f"up to {MAX_SUBSCRIPTIONS} devices can get notifications; turn one off first")
            before = next((s for s in data.get("subscriptions", []) if s["endpoint"] == endpoint), None)
            sub = {"id": secrets.token_hex(6), "endpoint": endpoint, "p256dh": p256dh, "auth": auth, "name": name,
                   "created": time.time(), "service": urlparse(endpoint).hostname,
                   "kinds": before.get("kinds", DEFAULT_KINDS) if before else DEFAULT_KINDS}
            data["subscriptions"] = subs + [sub]
            self._save(data)
        log.info("phone notifications turned on for %s", name)
        return {k: sub[k] for k in ("id", "name", "created", "service", "kinds")}

    def unsubscribe(self, endpoint: str | None = None, sub_id: str | None = None) -> int:
        with self.lock:
            data = self._load()
            subs = data.get("subscriptions", [])
            keep = [s for s in subs if s["endpoint"] != endpoint and s["id"] != sub_id]
            data["subscriptions"] = keep
            self._save(data)
            return len(subs) - len(keep)

    # ---------------------------------------------------------------- sending
    def notify(self, title: str, body: str, url: str = "/", tag: str = "", kind: str | None = None) -> None:
        """Queue a notification for every device that wants this kind (sent in the background: never
        slows anything)."""
        if not self.path.exists():
            return  # nobody asked for notifications yet
        try:
            self.queue.put_nowait({"title": title[:80], "body": body[:300], "url": url, "tag": tag[:60],
                                   "kind": kind if kind in KINDS else kind_of(body)})
        except queue.Full:
            log.warning("too many phone notifications waiting; dropping one")
            return
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._worker, daemon=True, name="push")
            self.thread.start()

    def _worker(self) -> None:
        while True:
            try:
                message = self.queue.get(timeout=30)
            except queue.Empty:
                return
            self.send_now(message)

    def send_now(self, message: dict, only: str | None = None) -> list[dict]:
        """Send to every device (or the one with id ``only``); forget devices whose push service says
        they're gone. The results, for the test button."""
        with self.lock:
            data = self._load()
            key = self._key(data) if data.get("subscriptions") else None
            subs = [s for s in data.get("subscriptions", []) if only is None or s["id"] == only]
        kind = message.get("kind")
        if only is None and kind:  # (a test goes to its device whatever it chose)
            subs = [s for s in subs if kind in s.get("kinds", DEFAULT_KINDS)]
        message = {k: v for k, v in message.items() if k != "kind"}
        payload = json.dumps(message, separators=(",", ":")).encode()
        results, gone = [], []
        for s in subs:
            try:
                status = self._post(key, s, payload, message.get("tag") or "")
            except (OSError, ValueError) as e:
                status, err = None, str(e)
            else:
                err = ""
            if status in (404, 410):
                gone.append(s["id"])
            ok = status is not None and 200 <= status < 300
            if ok:
                self.sent += 1
            else:
                self.last_error = err or f"HTTP {status}"
                log.warning("phone notification to %s failed: %s", s["name"], self.last_error)
            results.append({"id": s["id"], "name": s["name"], "ok": ok, "status": status, "error": err})
        for sub_id in gone:
            self.unsubscribe(sub_id=sub_id)
        return results

    def _post(self, key: int, sub: dict, payload: bytes, tag: str) -> int:
        if not allowed_endpoint(sub["endpoint"]):
            raise ValueError("not a push service")
        body = webpush.encrypt(payload, webpush.unb64u(sub["p256dh"]), webpush.unb64u(sub["auth"]))
        headers = {"TTL": str(TTL), "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
                   "Urgency": "normal", "Authorization": webpush.vapid_header(key, sub["endpoint"], SUBJECT),
                   "User-Agent": f"CraftConductor/{__version__}"}
        if tag and re.fullmatch(r"[A-Za-z0-9_-]{1,32}", tag):
            headers["Topic"] = tag  # (a newer one replaces an older one still waiting)
        req = urllib.request.Request(sub["endpoint"], data=body, headers=headers, method="POST")
        try:
            with _OPENER.open(req, timeout=15) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
