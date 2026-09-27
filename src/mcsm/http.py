"""Minimal HTTP client built on urllib (no third-party dependencies)."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import ssl
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from . import __version__

log = logging.getLogger(__name__)

USER_AGENT = f"silverWRX03/mc-server-management/{__version__} (+https://github.com/silverWRX03/mc-server-management)"


class HttpError(Exception):
    def __init__(self, url: str, status: int | None, message: str):
        super().__init__(f"{message} ({url})")
        self.url = url
        self.status = status
        self.reason = message

    @property
    def friendly(self) -> str:
        """For people: which site, and what went wrong, without the full URL."""
        host = urllib.parse.urlsplit(self.url).hostname or "the internet"
        if self.reason.startswith(("the server's security certificate", "that server must be reached")):
            return self.reason  # a security refusal: say exactly why
        if self.status == 404:
            return f"{host} doesn't have that (not found)"
        if self.status == 429:
            return f"{host} is busy (too many requests); try again in a minute"
        if self.status is not None and self.status >= 500:
            return f"{host} is having trouble (HTTP {self.status}); try again in a few minutes"
        if "timed out" in self.reason.lower():
            return f"{host} took too long to answer; check your internet connection and try again"
        if self.status is None:
            return f"couldn't reach {host}; check your internet connection and try again"
        return f"{host} refused the request (HTTP {self.status})"


class HashMismatch(Exception):
    pass


class PinMismatch(ConnectionError):
    """A pinned server presented a different certificate: someone may be in the middle."""


def _pinned_opener(fp: str) -> urllib.request.OpenerDirector:
    """HTTPS that trusts exactly one certificate: the one whose fingerprint is ``fp``."""
    import http.client
    from .tlscert import fingerprint

    class Connection(http.client.HTTPSConnection):
        def __init__(self, *args, **kwargs):
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.check_hostname = False     # self-signed: the fingerprint below is the check
            ctx.verify_mode = ssl.CERT_NONE
            kwargs["context"] = ctx
            super().__init__(*args, **kwargs)

        def connect(self):
            super().connect()
            der = self.sock.getpeercert(binary_form=True)
            if not der or not hmac.compare_digest(fingerprint(der), fp):
                self.sock.close()
                raise PinMismatch("the server's certificate doesn't match the invite")

    class Handler(urllib.request.HTTPSHandler):
        def https_open(self, req):
            return self.do_open(Connection, req)

    return urllib.request.build_opener(Handler)


def with_query(url: str, params: dict[str, Any] | None) -> str:
    if not params:
        return url
    return f"{url}?{urllib.parse.urlencode(params)}"


RATE_LIMIT_DELAYS = (5, 10, 20, 30)
RATE_LIMIT_RETRIES = len(RATE_LIMIT_DELAYS)
MAX_RATE_LIMIT_DELAY = 60


def _retry_after(e: urllib.error.HTTPError) -> float | None:
    try:
        value = float((e.headers or {}).get("Retry-After", ""))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


class HttpClient:
    """GET/POST JSON and verified downloads, with retries and a short-lived GET cache.

    The cache lets one update check ask about many Minecraft versions without
    re-fetching the same data; it expires so a long-running daemon sees new releases.
    """

    def __init__(self, retries: int = 3, timeout: float = 30.0, cache_ttl: float = 300.0,
                 rate_limit_retries: int = RATE_LIMIT_RETRIES):
        self.retries = retries
        self.rate_limit_retries = rate_limit_retries
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, Any]] = {}
        self._pins: dict[str, urllib.request.OpenerDirector] = {}

    def clear_cache(self) -> None:
        self._cache.clear()

    def pin(self, netloc: str, fp: str) -> None:
        """Only talk to ``netloc`` (host:port) over HTTPS, and only if it presents the certificate
        with this fingerprint (a friend's mcsm and the server it was invited to)."""
        self._pins[netloc.lower()] = _pinned_opener(fp)

    def _open(self, req: urllib.request.Request):
        last: Exception | None = None
        attempt = limited = 0
        while attempt < self.retries:
            try:
                u = urllib.parse.urlsplit(req.full_url)
                pinned = self._pins.get(u.netloc.lower())
                if pinned is None:
                    return urllib.request.urlopen(req, timeout=self.timeout)
                if u.scheme != "https":
                    raise HttpError(req.full_url, None, "that server must be reached over HTTPS")
                return pinned.open(req, timeout=self.timeout)
            except urllib.error.HTTPError as e:
                # 4xx (other than rate limiting and timeouts) will not succeed on retry.
                if e.code not in (408, 429) and e.code < 500:
                    raise HttpError(req.full_url, e.code, f"HTTP {e.code}") from e
                last = e
                if e.code == 429 and limited < self.rate_limit_retries:
                    # Rate limited (Mojang's lookup API does this readily): wait as asked, or long
                    # enough for the limit to reset, without using up the normal retries.
                    delay = min(_retry_after(e) or RATE_LIMIT_DELAYS[limited], MAX_RATE_LIMIT_DELAY)
                    limited += 1
                    log.info("%s is busy (rate limited); trying again in %ss", req.host, delay)
                    time.sleep(delay)
                    continue
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if isinstance(getattr(e, "reason", e), PinMismatch):  # never retried or ignored
                    raise HttpError(req.full_url, None, "the server's security certificate doesn't match the "
                                                        "invite, so mcsm didn't connect. Ask for a new invite; if "
                                                        "you get the same error, someone may be interfering") from e
                last = e
            delay = 2**attempt
            attempt += 1
            if attempt < self.retries:
                log.debug("request to %s failed (%s); retrying in %ss", req.full_url, last, delay)
                time.sleep(delay)
        status = last.code if isinstance(last, urllib.error.HTTPError) else None
        raise HttpError(req.full_url, status, f"request failed: {last}")

    def get_json(self, url: str, params: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None, cache: bool = True) -> Any:
        """GET JSON. Answers are reused for a few minutes unless ``cache`` is False (use that
        when the answer depends on who asks, e.g. a token in ``headers``)."""
        full = with_query(url, params)
        hit = self._cache.get(full) if cache else None
        if hit and time.monotonic() - hit[0] < self.cache_ttl:
            return hit[1]
        req = urllib.request.Request(full, headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                                                    **(headers or {})})
        for attempt in range(self.retries):
            try:
                with self._open(req) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                break
            except (TimeoutError, ConnectionError) as e:  # the answer stopped part way
                if attempt + 1 >= self.retries:
                    raise HttpError(full, None, f"request failed: {e}") from e
                time.sleep(2**attempt)
        if cache:
            self._cache[full] = (time.monotonic(), data)
        return data

    def get_text(self, url: str, headers: dict[str, str] | None = None, limit: int = 1 << 20) -> str:
        """GET a text page (at most ``limit`` bytes), e.g. a plugin's description."""
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
        with self._open(req) as resp:
            return resp.read(limit).decode("utf-8", "replace")

    def post_json(self, url: str, body: Any, headers: dict[str, str] | None = None) -> Any:
        return self.send_json("POST", url, body, headers)

    def patch_json(self, url: str, body: Any, headers: dict[str, str] | None = None) -> Any:
        return self.send_json("PATCH", url, body, headers)

    def send_json(self, method: str, url: str, body: Any, headers: dict[str, str] | None = None) -> Any:
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), method=method,
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/json",
                     "Accept": "application/json", **(headers or {})})
        with self._open(req) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def download(self, url: str, dest: Path, sha1: str | None = None, sha512: str | None = None,
                 headers: dict[str, str] | None = None, sha256: str | None = None) -> Path:
        """Download to ``dest`` atomically, verifying hashes when given."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
        h1, h256, h512 = hashlib.sha1(), hashlib.sha256(), hashlib.sha512()
        fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".part-")
        out = os.fdopen(fd, "wb")  # owned from here, so it's always closed (Windows can't delete an open file)
        try:
            with out, self._open(req) as resp:
                while chunk := resp.read(1 << 16):
                    h1.update(chunk)
                    h256.update(chunk)
                    h512.update(chunk)
                    out.write(chunk)
            if sha1 and h1.hexdigest() != sha1.lower():
                raise HashMismatch(f"sha1 mismatch for {url}: expected {sha1}, got {h1.hexdigest()}")
            if sha256 and h256.hexdigest() != sha256.lower():
                raise HashMismatch(f"sha256 mismatch for {url}")
            if sha512 and h512.hexdigest() != sha512.lower():
                raise HashMismatch(f"sha512 mismatch for {url}")
            _replace(tmp, dest)
        except BaseException:
            out.close()
            try:
                Path(tmp).unlink(missing_ok=True)
            except OSError:
                pass  # tidying up mustn't hide why the download failed
            raise
        return dest


def _replace(src: str, dest: Path, tries: int = 8) -> None:
    """Move a finished download into place. On Windows, antivirus often holds a new file
    open for a moment to scan it ("used by another process"), so wait a little and retry."""
    for attempt in range(tries):
        try:
            os.replace(src, dest)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(0.25 * (attempt + 1))


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 16):
            h.update(chunk)
    return h.hexdigest()
