"""The people the owner invited to the control panel, each with their own sign-in and, per
server, what they may do there (access.py).

They're kept in ``.craft-conductor/users.json`` (owner-only, like the other sign-in files):
a name the owner chose, the username and password the person chose (a salted PBKDF2 hash,
webauth.hash_password), and their grants: server id -> permissions.

The owner invites someone with a link that works **once**, for a day (only its hash is kept).
Opening it shows who it's for; choosing a username and a strong password uses it up. "New
sign-in link" is also how a forgotten password is replaced: it ends the old password and every
session at once. Removing a person ends their sessions, phones and passkeys the same moment.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading

from . import access, private, webauth
from .config import ConfigError

FILE = "users.json"
FORMAT = 1
INVITE_SECONDS = 24 * 3600
MAX_USERS = 50
USERNAME = re.compile(r"[a-z0-9][a-z0-9_.-]{2,31}")
_dummy: list[str] = []   # a hash to check against when there's no such username (as slow either way)


class UserError(ConfigError):
    pass


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def clean_name(name: object) -> str:
    """A person's name as the owner typed it (shown in lists; never used to identify them)."""
    return (re.sub(r"[^\w .'()-]", "", str(name or ""))[:40].strip()) or ""


def check_hashed(stored: str, secret: str) -> bool:
    m = webauth._HASHED.fullmatch(stored or "")
    if not m:
        return False
    return hmac.compare_digest(webauth._hash(secret, bytes.fromhex(m[2]), int(m[1])), m[3])


def _grants(raw: object) -> dict[str, frozenset[str]]:
    out = {}
    for sid, caps in (raw or {}).items() if isinstance(raw, dict) else ():
        try:
            caps = access.valid_caps(caps)
        except ValueError:
            continue   # (a permission this version doesn't know: left out, never guessed)
        if caps:
            out[str(sid)] = caps
    return out


class Users:
    def __init__(self, state_dir):
        self.path = state_dir / FILE
        self._lock = threading.RLock()
        self._cache: tuple[tuple, list[dict]] | None = None

    # -------------------------------------------------------------- the file
    def _cached(self) -> list[dict]:
        """The people as last read (not to be changed). Read again only when the file changes,
        since every request from one of them looks them up here."""
        try:
            st = self.path.stat()
            stamp = (st.st_mtime_ns, st.st_size, st.st_ino)
            if self._cache is None or self._cache[0] != stamp:
                data = json.loads(self.path.read_text())
                users = [u for u in data.get("users", []) if isinstance(u, dict) and u.get("id")] \
                    if isinstance(data, dict) else []
                self._cache = (stamp, users)
            return self._cache[1]
        except (OSError, ValueError):
            return []

    def _read(self) -> list[dict]:
        """The people, as copies to change and _write."""
        return [json.loads(json.dumps(u)) for u in self._cached()]

    def _write(self, users: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        private.write_text(self.path, json.dumps({"format": FORMAT, "users": users}, indent=2) + "\n")

    def _find(self, users: list[dict], user_id: str) -> dict:
        for u in users:
            if u.get("id") == user_id:
                return u
        raise UserError("there's no such person (they may have been removed)")

    # -------------------------------------------------------------- reading
    def get(self, user_id: str) -> dict | None:
        u = next((u for u in self._cached() if u.get("id") == user_id), None)
        return json.loads(json.dumps(u)) if u is not None else None

    def list(self, now: float) -> list[dict]:
        out = []
        for u in self._read():
            inv = u.get("invite") or {}
            out.append({"id": u["id"], "name": u.get("name", ""), "username": u.get("username"),
                        "created": u.get("created"), "signed_up": bool(u.get("password")),
                        "invite_expires": inv.get("expires") if inv.get("expires", 0) > now else None,
                        "grants": {sid: sorted(c) for sid, c in _grants(u.get("grants")).items()}})
        return out

    def subject(self, user_id: str, epoch: int | None = None, device: str = "") -> access.Subject | None:
        """Who this person is now, with their current grants; None once they're removed, their
        password was replaced (``epoch``), or before they chose one."""
        u = self.get(user_id)
        if u is None or not u.get("password") or (epoch is not None and u.get("epoch", 0) != epoch):
            return None
        return access.Subject("user", user_id=u["id"], name=u.get("name") or u.get("username", ""),
                              device=device, grants=_grants(u.get("grants")))

    # -------------------------------------------------------------- the owner's changes
    def invite(self, name: object, grants: dict[str, frozenset[str]], now: float) -> tuple[str, dict]:
        """A new person and their one-time link (the token goes after #invite= in the link)."""
        name = clean_name(name)
        if not name:
            raise UserError("type the person's name")
        with self._lock:
            users = self._read()
            if len(users) >= MAX_USERS:
                raise UserError(f"that's {MAX_USERS} people already; remove someone first")
            token = secrets.token_urlsafe(32)
            user = {"id": secrets.token_hex(6), "name": name, "username": None, "password": "", "created": now,
                    "epoch": 0, "grants": {sid: sorted(c) for sid, c in grants.items() if c},
                    "invite": {"digest": _digest(token), "expires": now + INVITE_SECONDS}}
            users.append(user)
            self._write(users)
        return token, user

    def new_link(self, user_id: str, now: float) -> str:
        """A new one-time link for someone (a forgotten password): their password and sessions end now."""
        with self._lock:
            users = self._read()
            u = self._find(users, user_id)
            token = secrets.token_urlsafe(32)
            u.update(password="", epoch=u.get("epoch", 0) + 1,
                     invite={"digest": _digest(token), "expires": now + INVITE_SECONDS})
            self._write(users)
        return token

    def cancel_link(self, user_id: str) -> None:
        with self._lock:
            users = self._read()
            self._find(users, user_id)["invite"] = None
            self._write(users)

    def cancel_all_links(self) -> int:
        """Every link not used yet stops working (the owner's password was reset)."""
        with self._lock:
            users = self._read()
            n = sum(1 for u in users if u.get("invite"))
            for u in users:
                u["invite"] = None
            if n:
                self._write(users)
            return n

    def update(self, user_id: str, name: object = None, grants: dict[str, frozenset[str]] | None = None) -> dict:
        with self._lock:
            users = self._read()
            u = self._find(users, user_id)
            if name is not None:
                u["name"] = clean_name(name) or u.get("name", "")
            if grants is not None:
                u["grants"] = {sid: sorted(c) for sid, c in grants.items() if c}
            self._write(users)
            return u

    def remove(self, user_id: str) -> dict:
        with self._lock:
            users = self._read()
            u = self._find(users, user_id)
            self._write([x for x in users if x is not u])
            return u

    def forget_server(self, sid: str) -> int:
        """A server was deleted: nobody keeps a grant for it (a new server with the same name starts with none)."""
        with self._lock:
            users = self._read()
            n = 0
            for u in users:
                if sid in (u.get("grants") or {}):
                    del u["grants"][sid]
                    n += 1
            if n:
                self._write(users)
            return n

    # -------------------------------------------------------------- the person's own
    def _by_invite(self, users: list[dict], token: str, now: float) -> dict:
        digest = _digest(str(token or "")[:200])
        for u in users:
            inv = u.get("invite") or {}
            if hmac.compare_digest(inv.get("digest", ""), digest) and inv.get("expires", 0) > now:
                return u
        raise UserError("that invite link has expired or was already used; ask for a new one")

    def invite_info(self, token: str, now: float) -> dict:
        """What an invite link is for (opening it doesn't use it up)."""
        u = self._by_invite(self._cached(), token, now)
        return {"name": u.get("name", ""), "username": u.get("username"), "servers": sorted(_grants(u.get("grants")))}

    def accept(self, token: str, username: object, password: str, now: float) -> dict:
        """Use up an invite: the person chooses their username (or keeps it, for a new link) and password."""
        username = str(username or "").strip().lower()
        if not USERNAME.fullmatch(username):
            raise UserError("a username is 3 to 32 letters, digits, dots, dashes or underscores, starting with a letter or digit")
        if not webauth.strong_password(password) or len(password) > 200:
            raise UserError("choose a strong password: " + webauth.STRONG_RULES)
        if password.lower() == username:
            raise UserError("the password can't be the username")
        with self._lock:
            users = self._read()
            u = self._by_invite(users, token, now)
            if u.get("username") and u["username"] != username:
                raise UserError(f"your username is {u['username']}")
            if any(x.get("username") == username and x is not u for x in users):
                raise UserError("that username is taken; pick another")
            u.update(username=username, password=webauth.hash_password(password), invite=None,
                     epoch=u.get("epoch", 0) + 1)
            self._write(users)
            return u

    def check(self, username: object, password: str) -> dict | None:
        """The person with this username and password, or None (as slow either way)."""
        username = str(username or "").strip().lower()
        u = next((x for x in self._cached() if x.get("username") == username and x.get("password")), None)
        if not _dummy:
            _dummy.append(webauth.hash_password(secrets.token_hex(8)))
        ok = check_hashed(u["password"] if u else _dummy[0], password)
        return u if u and ok else None

    def set_password(self, user_id: str, old: str, new: str) -> dict:
        """Change one's own password (knowing the current one): their other sessions end."""
        if not webauth.strong_password(new) or len(new) > 200:
            raise UserError("choose a strong password: " + webauth.STRONG_RULES)
        with self._lock:
            users = self._read()
            u = self._find(users, user_id)
            if not check_hashed(u.get("password", ""), old):
                raise UserError("that isn't your current password")
            if new.lower() == (u.get("username") or ""):
                raise UserError("the password can't be the username")
            u.update(password=webauth.hash_password(new), epoch=u.get("epoch", 0) + 1)
            self._write(users)
            return u
