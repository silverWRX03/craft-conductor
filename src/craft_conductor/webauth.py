"""How the web UI is protected: a password (or a PIN, on the server's own computer).

The choice lives in ``.craft-conductor/web-auth.json`` as a salted PBKDF2 hash. A new server
starts with the password ``PASSWORD`` and the web UI asks to change it at the
first sign-in. ``[web] password`` in craft-conductor.toml overrides all of this; a password typed
there is swapped for its hash (``hash_password``) the first time Craft Conductor reads it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from dataclasses import dataclass

from . import private
from .config import Config, ConfigError

DEFAULT_PASSWORD = "PASSWORD"
MODES = ("password", "pin")  # (craft-conductor 0.8 and older also had "none": no password on this computer)
FILE = "web-auth.json"
LEGACY_FILE = "web-password"   # craft-conductor 0.1 kept a generated password here in plain text
ITERATIONS = 200_000
FORMAT = 2   # files without it came from craft-conductor 0.2.0, which could carry over 0.1's random password


def _hash(secret: str, salt: bytes, iterations: int = ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac("sha256", secret.encode(), salt, iterations).hex()


# A [web] password as craft-conductor.toml (or hub.json) keeps it: iterations, salt, hash, and
# whether the password met STRONG_RULES (needed for sign-ins from other devices).
_HASHED = re.compile(r"pbkdf2-sha256\$(\d{4,7})\$([0-9a-f]{32})\$([0-9a-f]{64})(\$strong)?")


def hash_password(secret: str) -> str:
    salt = secrets.token_bytes(16)
    return (f"pbkdf2-sha256${ITERATIONS}${salt.hex()}${_hash(secret, salt)}"
            + ("$strong" if strong_password(secret) else ""))


def is_hashed(value: str) -> bool:
    return bool(_HASHED.fullmatch(value))


STRONG_RULES = "at least 12 characters, with an uppercase letter, a lowercase letter and a special character (like ! ? # or %)"


def strong_password(secret: str) -> bool:
    """Good enough to put the control panel on a network: long, mixed case, a special character."""
    return (len(secret) >= 12 and any(c.isupper() for c in secret) and any(c.islower() for c in secret)
            and any(not c.isalnum() and not c.isspace() for c in secret))


def validate(mode: str, secret: str) -> None:
    if mode not in MODES:
        raise ConfigError(f"unknown sign-in mode {mode!r}")
    if mode == "pin" and not re.fullmatch(r"\d{4,8}", secret):
        raise ConfigError("a PIN is 4 to 8 digits")
    if mode == "password":
        if len(secret) < 4:
            raise ConfigError("use a password of at least 4 characters")
        if len(secret) > 200:
            raise ConfigError("that password is too long")
        if secret == DEFAULT_PASSWORD:
            raise ConfigError("pick something other than the default password")


@dataclass
class Auth:
    mode: str = "password"
    salt: str = ""
    hash: str = ""
    iterations: int = ITERATIONS
    default: bool = False      # still the built-in PASSWORD
    managed: bool = False      # set by [web] password in craft-conductor.toml; can't be changed from the UI
    strong: bool = False       # meets STRONG_RULES (required for sign-ins from other devices)
    temporary: bool = False    # a one-time password craft-conductor made (headless first run); must be replaced

    @property
    def remote_ready(self) -> bool:
        return self.mode == "password" and self.strong and not self.default and not self.temporary

    def check(self, secret: str) -> bool:
        if not self.hash:
            return False
        if self.default:  # the built-in password is forgiving about case and stray spaces
            secret = secret.strip().upper()
        return hmac.compare_digest(_hash(secret, bytes.fromhex(self.salt), self.iterations), self.hash)

    def info(self) -> dict:
        return {"mode": self.mode, "default": self.default or self.temporary, "managed": self.managed,
                "strong": self.remote_ready, "temporary": self.temporary}


def _hashed(mode: str, secret: str, default: bool = False) -> Auth:
    salt = secrets.token_bytes(16)
    return Auth(mode=mode, salt=salt.hex(), hash=_hash(secret, salt), default=default,
                strong=mode == "password" and not default and strong_password(secret))


def _managed(value: str) -> Auth:
    """The sign-in for ``[web] password``: its hash, or the password itself where the file couldn't
    take the hash (mounted read-only)."""
    m = _HASHED.fullmatch(value)
    auth = (Auth(mode="password", salt=m[2], hash=m[3], iterations=int(m[1]), strong=bool(m[4])) if m
            else _hashed("password", value))
    auth.managed = True
    return auth


class AuthStore:
    """Reads and writes the sign-in settings; notices changes made by `craft-conductor web-password`."""

    def __init__(self, config: Config):
        self.config = config
        self.path = config.state_dir / FILE
        self._lock = threading.Lock()
        self._auth: Auth | None = None
        self._mtime: float | None = None
        self._managed_for: str | None = None

    def get(self) -> Auth:
        if self.config.web.password:
            with self._lock:
                if self._auth is None or self._managed_for != self.config.web.password:
                    self._auth = _managed(self.config.web.password)
                    self._managed_for = self.config.web.password
                return self._auth
        self._managed_for = None
        with self._lock:
            mtime = self.path.stat().st_mtime if self.path.exists() else None
            if self._auth is None or self._auth.managed or mtime != self._mtime:
                self._auth = self._load()
                self._mtime = self.path.stat().st_mtime
            return self._auth

    def _load(self) -> Auth:
        if self.path.exists():
            try:
                d = json.loads(self.path.read_text())
                if d.get("format") is None and d.get("mode") == "password" and not d.get("default"):
                    # craft-conductor 0.2.0 turned 0.1's generated password (which nobody chose or saw) into
                    # this file, so PASSWORD never worked afterwards. Start over from the default.
                    auth = _hashed("password", DEFAULT_PASSWORD, default=True)
                    self._save(auth)
                    return auth
                if d.get("mode") == "none":
                    # "No password" was removed: back to the default, and the prompt to pick your own.
                    auth = _hashed("password", DEFAULT_PASSWORD, default=True)
                    self._save(auth)
                    return auth
                if d.get("mode") in MODES:
                    return Auth(mode=d["mode"], salt=d.get("salt", ""), hash=d.get("hash", ""),
                                iterations=int(d.get("iterations", ITERATIONS)), default=bool(d.get("default")),
                                strong=bool(d.get("strong")), temporary=bool(d.get("temporary")))
            except (ValueError, TypeError):
                pass
        # craft-conductor 0.1 generated a random password into a plain-text file; nobody chose it, so
        # start over with the default (and the prompt to pick your own).
        (self.config.state_dir / LEGACY_FILE).unlink(missing_ok=True)
        auth = _hashed("password", DEFAULT_PASSWORD, default=True)
        self._save(auth)
        return auth

    def _save(self, auth: Auth) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        private.write_text(self.path, json.dumps({
            "format": FORMAT, "mode": auth.mode, "salt": auth.salt, "hash": auth.hash, "iterations": auth.iterations,
            "default": auth.default, "strong": auth.strong, "temporary": auth.temporary}, indent=2) + "\n")

    def set(self, mode: str, secret: str = "") -> Auth:
        if self.config.web.password:
            raise ConfigError("the password is set in craft-conductor.toml ([web] password); change it there")
        validate(mode, secret)
        auth = _hashed(mode, secret)
        (self.path.parent / "first-password.txt").unlink(missing_ok=True)
        with self._lock:
            self._save(auth)
            self._auth, self._mtime = auth, self.path.stat().st_mtime
        return auth

    def exists(self) -> bool:
        return self.path.exists()

    def first_run_password(self) -> str | None:
        """For a computer without a screen (a headless PC, Docker): it's only reachable from other
        devices, which need more than the built-in PASSWORD. Use CRAFT_CONDUCTOR_INITIAL_PASSWORD if it's
        strong; otherwise make a random one-time password (printed on the console) that must be
        replaced at the first sign-in. Returns the one-time password, if one was made."""
        if self.config.web.password or self.path.exists():
            return None
        initial = os.environ.get("CRAFT_CONDUCTOR_INITIAL_PASSWORD", "")
        if initial and strong_password(initial):
            auth = _hashed("password", initial)
            with self._lock:
                self._save(auth)
                self._auth, self._mtime = auth, self.path.stat().st_mtime
            return None
        words = "-".join(secrets.token_hex(3) for _ in range(3))
        password = f"Craft-Conductor-{words}!"  # e.g. Craft-Conductor-1a2b3c-4d5e6f-7a8b9c!
        auth = _hashed("password", password)
        auth.temporary = True
        with self._lock:
            self._save(auth)
            self._auth, self._mtime = auth, self.path.stat().st_mtime
        private.write_text(self.path.parent / "first-password.txt",
                           f"craft-conductor's one-time password for the first sign-in: {password}\n"
                           "You'll be asked to choose your own; this file is deleted then.\n")
        return password

    def reset(self) -> Auth:
        """Back to the default PASSWORD (for a forgotten password)."""
        auth = _hashed("password", DEFAULT_PASSWORD, default=True)
        with self._lock:
            self._save(auth)
            self._auth, self._mtime = auth, self.path.stat().st_mtime
        return auth


def describe(auth: Auth) -> str:
    """One line for the console: how to sign in to the control panel."""
    if auth.managed:
        return "the password from [web] in craft-conductor.toml"
    if auth.default:
        return f"{DEFAULT_PASSWORD}  (you'll be asked to choose your own)"
    if auth.temporary:
        return "the one-time password shown when Craft Conductor first started (you'll be asked to choose your own)"
    return ("the PIN you chose" if auth.mode == "pin" else "the password you chose") + \
        "  (forgot it? run `craft-conductor web-password --reset`)"


# ------------------------------------------------------------ paired phones
DEVICES_FILE = "devices.json"
PAIR_SECONDS = 300            # a pairing code works once, for five minutes (and can be cancelled before)
MAX_CODES = 5                 # pairing codes waiting to be used at once (the oldest goes first)
# Pairing codes are short enough to type (an iPhone's Home Screen app doesn't share Safari's
# sign-in, so it's paired by typing the code): 12 letters and digits that can't be mixed up,
# about 59 bits, with five tries per five minutes (web.py).
CODE_LETTERS = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
DEVICE_DAYS = 180             # a paired phone signs in by itself for this long (unless removed)


def pair_code(typed: str) -> str:
    """A pairing code as typed: any case, with or without dashes or spaces, O for 0, I or L for 1."""
    return re.sub(r"[^0-9A-Z]", "", str(typed)[:64].upper()).translate(str.maketrans("OIL", "011"))


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# A paired phone belongs to one invited person (users.py) and can do exactly what they can, on
# their servers, never more (access.py). Phones paired before that (the old "helper" and
# "viewer" phones, which could act on every server) no longer sign in: pair them again for a person.


class Devices:
    """Phones paired by scanning a QR code: each has its own key (only its hash is kept here),
    belongs to one invited person, and can be removed on its own."""

    def __init__(self, state_dir):
        self.path = state_dir / DEVICES_FILE
        self._lock = threading.Lock()
        self._codes: dict[str, tuple[float, str]] = {}   # digest of a pairing code -> (when it expires, the person's id)
        self._cache: tuple[tuple, list[dict]] | None = None  # (the file's stat, its devices)

    def _read(self) -> list[dict]:
        """The paired devices (copies: change them and _write). Read again only when the file
        changes, since a paired phone's every request looks itself up here."""
        try:
            st = self.path.stat()
            stamp = (st.st_mtime_ns, st.st_size, st.st_ino)
            if self._cache is None or self._cache[0] != stamp:
                data = json.loads(self.path.read_text())
                devices = [d for d in data.get("devices", []) if isinstance(d, dict)] if isinstance(data, dict) else []
                self._cache = (stamp, devices)
            return [dict(d) for d in self._cache[1]]
        except (OSError, ValueError):
            return []

    def _write(self, devices: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        private.write_text(self.path, json.dumps({"devices": devices}, indent=2) + "\n")

    def drop_unowned(self) -> int:
        """Forget phones that belong to nobody (paired before phones belonged to a person)."""
        with self._lock:
            devices = self._read()
            kept = [d for d in devices if d.get("user_id")]
            if len(kept) != len(devices):
                self._write(kept)
            return len(devices) - len(kept)

    def new_code(self, now: float, user_id: str) -> str:
        """A one-time pairing code for a phone of this person, who's decided here, by the owner,
        never by whoever uses the code."""
        if not user_id:
            raise ConfigError("pick the person whose phone this is")
        raw = "".join(secrets.choice(CODE_LETTERS) for _ in range(12))
        with self._lock:
            live = sorted(((c, v) for c, v in self._codes.items() if v[0] > now), key=lambda x: x[1][0])
            self._codes = dict(live[-(MAX_CODES - 1):])
            self._codes[_digest(raw)] = (now + PAIR_SECONDS, user_id)
        return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"

    def cancel_codes(self, user_id: str | None = None) -> int:
        """Pairing codes not used yet stop working (e.g. the QR code was shown to the wrong person)."""
        with self._lock:
            kept = {c: v for c, v in self._codes.items() if user_id is not None and v[1] != user_id}
            n, self._codes = len(self._codes) - len(kept), kept
        return n

    def pair(self, code: str, name: str, ip: str, now: float) -> tuple[str, dict]:
        """Use up a pairing code; returns the new phone's key and its record."""
        with self._lock:
            exp, user_id = self._codes.pop(_digest(pair_code(code)), (None, None))
            if exp is None or exp < now:
                raise ConfigError("that pairing code has expired or was already used; make a new one")
            token = secrets.token_urlsafe(32)
            device = {"id": secrets.token_hex(6), "name": (re.sub(r"[^\w .'()-]", "", name).strip() or "Phone")[:40],
                      "hash": _digest(token), "created": now, "expires": now + DEVICE_DAYS * 86400,
                      "last_seen": now, "last_ip": ip, "user_id": user_id}
            devices = self._read()
            devices.append(device)
            self._write(devices)
        return token, device

    def find(self, token: str | None, now: float) -> dict | None:
        if not token:
            return None
        digest = _digest(token)
        with self._lock:
            devices = self._read()
            for d in devices:
                if hmac.compare_digest(d.get("hash", ""), digest) and d.get("expires", 0) > now and d.get("user_id"):
                    return d
        return None

    def seen(self, device_id: str, ip: str, now: float) -> None:
        with self._lock:
            devices = self._read()
            for d in devices:
                if d.get("id") == device_id and now - d.get("last_seen", 0) > 60:
                    d.update(last_seen=now, last_ip=ip)
                    self._write(devices)
                    return

    def list(self) -> list[dict]:
        return [{k: d.get(k) for k in ("id", "name", "created", "last_seen", "last_ip", "expires", "user_id")}
                for d in self._read() if d.get("user_id")]

    def remove(self, device_id: str | None = None, user_id: str | None = None) -> int:
        """Remove one phone, a person's phones, or all of them (both ``None``: pairing codes not
        used yet stop working too)."""
        with self._lock:
            if device_id is None and user_id is None:
                self._codes = {}
            elif user_id is not None:
                self._codes = {c: v for c, v in self._codes.items() if v[1] != user_id}
            devices = self._read()
            if device_id is None and user_id is None:
                kept = []
            else:
                kept = [d for d in devices if not (d.get("id") == device_id or (user_id is not None and d.get("user_id") == user_id))]
            self._write(kept)
            return len(devices) - len(kept)
