"""Signing in with a fingerprint or face (passkeys, WebAuthn), mostly for the phone app.

The owner, signed in with the password, adds a passkey on a device: the device's own lock
(fingerprint, face or its PIN) guards a key pair made for this address; only the public key is
kept here, in ``.mcsm/passkeys.json``. Signing in, the device signs a one-time challenge and
Craft Conductor checks the signature (ES256 on P-256, or RS256), that it's for this address,
that the person was verified on the device, and that the device's counter only goes up.

Browsers only offer passkeys on a secure address (HTTPS, or localhost), and a passkey only works
at the address it was added at. Attestation (which make of device it is) isn't asked for.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

from . import webpush

FILE = "passkeys.json"
CHALLENGE_SECONDS = 120
MAX_PASSKEYS = 20
ES256, RS256 = -7, -257
UP, UV, AT = 0x01, 0x04, 0x40   # authenticator data flags: user present, verified, credential data


class PasskeyError(ValueError):
    pass


# ------------------------------------------------------------------ CBOR (the parts WebAuthn uses)
def cbor_decode(data: bytes):
    value, end = _cbor(data, 0)
    return value, end


def _cbor(data: bytes, i: int, depth: int = 0):
    if depth > 16 or i >= len(data):
        raise PasskeyError("damaged passkey data")
    head = data[i]
    major, info = head >> 5, head & 31
    i += 1
    if info < 24:
        arg = info
    elif info in (24, 25, 26, 27):
        size = 1 << (info - 24)
        if i + size > len(data):
            raise PasskeyError("damaged passkey data")
        arg = int.from_bytes(data[i:i + size], "big")
        i += size
    else:
        raise PasskeyError("unsupported passkey data")
    if major == 0:
        return arg, i
    if major == 1:
        return -1 - arg, i
    if major in (2, 3):
        if i + arg > len(data):
            raise PasskeyError("damaged passkey data")
        raw = data[i:i + arg]
        return (raw if major == 2 else raw.decode("utf-8", "replace")), i + arg
    if major == 4:
        if arg > 64:
            raise PasskeyError("damaged passkey data")
        out = []
        for _ in range(arg):
            item, i = _cbor(data, i, depth + 1)
            out.append(item)
        return out, i
    if major == 5:
        if arg > 64:
            raise PasskeyError("damaged passkey data")
        out = {}
        for _ in range(arg):
            key, i = _cbor(data, i, depth + 1)
            out[key], i = _cbor(data, i, depth + 1)
        return out, i
    if major == 7 and info in (20, 21, 22):
        return {20: False, 21: True, 22: None}[info], i
    raise PasskeyError("unsupported passkey data")


# ------------------------------------------------------------------ keys and signatures
def _der_to_raw(sig: bytes) -> bytes:
    """An ECDSA signature in DER (what WebAuthn sends) as r || s, 32 bytes each."""
    try:
        if sig[0] != 0x30 or sig[2] != 0x02:
            raise ValueError
        rlen = sig[3]
        r = sig[4:4 + rlen]
        if sig[4 + rlen] != 0x02:
            raise ValueError
        slen = sig[5 + rlen]
        s = sig[6 + rlen:6 + rlen + slen]
        return int.from_bytes(r, "big").to_bytes(32, "big") + int.from_bytes(s, "big").to_bytes(32, "big")
    except (IndexError, ValueError, OverflowError):
        raise PasskeyError("damaged signature") from None


def public_key(cose: dict) -> dict:
    """The parts of a COSE key we keep: {"alg", and x/y or n/e as hex}."""
    alg = cose.get(3)
    if cose.get(1) == 2 and alg == ES256 and cose.get(-1) == 1:
        x, y = cose.get(-2), cose.get(-3)
        if not (isinstance(x, bytes) and isinstance(y, bytes) and len(x) == len(y) == 32):
            raise PasskeyError("damaged passkey key")
        webpush.point_from(b"\x04" + x + y)  # (must be on the curve)
        return {"alg": ES256, "x": x.hex(), "y": y.hex()}
    if cose.get(1) == 3 and alg == RS256:
        n, e = cose.get(-1), cose.get(-2)
        if not (isinstance(n, bytes) and isinstance(e, bytes) and 256 <= len(n) <= 512 and 1 <= len(e) <= 4):
            raise PasskeyError("damaged passkey key")
        return {"alg": RS256, "n": n.hex(), "e": e.hex()}
    raise PasskeyError("this device's passkey type isn't supported (only ES256 and RS256)")


_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")  # PKCS#1 v1.5 DigestInfo


def check_signature(key: dict, message: bytes, signature: bytes) -> bool:
    if key["alg"] == ES256:
        point = (int(key["x"], 16), int(key["y"], 16))
        return webpush.verify(point, message, _der_to_raw(signature))
    if key["alg"] == RS256:
        n, e = int(key["n"], 16), int(key["e"], 16)
        size = (n.bit_length() + 7) // 8
        if len(signature) != size:
            return False
        em = pow(int.from_bytes(signature, "big"), e, n).to_bytes(size, "big")
        digest = _SHA256_PREFIX + hashlib.sha256(message).digest()
        expected = b"\x00\x01" + b"\xff" * (size - 3 - len(digest)) + b"\x00" + digest
        return hmac.compare_digest(em, expected)
    return False


def parse_auth_data(data: bytes) -> dict:
    if len(data) < 37:
        raise PasskeyError("damaged passkey data")
    out = {"rp_hash": data[:32], "flags": data[32], "count": int.from_bytes(data[33:37], "big")}
    if data[32] & AT:
        if len(data) < 55:
            raise PasskeyError("damaged passkey data")
        n = int.from_bytes(data[53:55], "big")
        out["credential_id"] = data[55:55 + n]
        out["cose"], _ = cbor_decode(data[55 + n:])
        if len(out["credential_id"]) != n or not isinstance(out["cose"], dict):
            raise PasskeyError("damaged passkey data")
    return out


# ------------------------------------------------------------------ the store
class Passkeys:
    def __init__(self, state_dir: Path):
        self.path = state_dir / FILE
        self._lock = threading.Lock()
        self._challenges: dict[str, tuple[float, str, str]] = {}   # challenge -> (expires, "create"/"get", rp id)

    def _read(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text())
            return [c for c in data.get("passkeys", []) if isinstance(c, dict)] if isinstance(data, dict) else []
        except (OSError, ValueError):
            return []

    def _write(self, items: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"passkeys": items}, indent=2) + "\n")
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        os.replace(tmp, self.path)

    def list(self) -> list[dict]:
        return [{k: c.get(k) for k in ("id", "name", "rp_id", "created", "last_used")} for c in self._read()]

    def count(self, rp_id: str | None = None) -> int:
        return sum(1 for c in self._read() if rp_id is None or c.get("rp_id") == rp_id)

    def remove(self, cred_id: str | None = None) -> int:
        """Remove one passkey, or all of them (``None``)."""
        with self._lock:
            items = self._read()
            kept = [c for c in items if cred_id is not None and c.get("id") != cred_id]
            self._write(kept)
            return len(items) - len(kept)

    def _challenge(self, kind: str, rp_id: str) -> str:
        now = time.time()
        challenge = webpush.b64u(secrets.token_bytes(32))
        with self._lock:
            self._challenges = {c: v for c, v in self._challenges.items() if v[0] > now}
            if len(self._challenges) > 200:  # (a flood of sign-in pages: forget the oldest)
                self._challenges = dict(sorted(self._challenges.items(), key=lambda kv: kv[1][0])[-100:])
            self._challenges[challenge] = (now + CHALLENGE_SECONDS, kind, rp_id)
        return challenge

    def _use_challenge(self, client: dict, kind: str, rp_id: str, origins: set[str]) -> None:
        if client.get("type") != f"webauthn.{kind}":
            raise PasskeyError("that isn't a passkey answer")
        with self._lock:
            found = self._challenges.pop(str(client.get("challenge", "")), None)
        if found is None or found[0] < time.time() or found[1] != kind or found[2] != rp_id:
            raise PasskeyError("that sign-in took too long or was already used; try again")
        if client.get("origin") not in origins:
            raise PasskeyError("that passkey answer came from another address")

    @staticmethod
    def _client(client_data: str) -> tuple[bytes, dict]:
        raw = webpush.unb64u(client_data)
        try:
            data = json.loads(raw)
        except ValueError:
            raise PasskeyError("damaged passkey answer") from None
        if not isinstance(data, dict):
            raise PasskeyError("damaged passkey answer")
        return raw, data

    # -------------------------------------------------------------- adding one
    def creation_options(self, rp_id: str) -> dict:
        existing = [{"type": "public-key", "id": c["id"]} for c in self._read() if c.get("rp_id") == rp_id]
        return {"challenge": self._challenge("create", rp_id), "rp": {"id": rp_id, "name": "Craft Conductor"},
                "user": {"id": webpush.b64u(hashlib.sha256(b"craft-conductor-owner").digest()[:16]),
                         "name": "owner", "displayName": "Craft Conductor"},
                "pubKeyCredParams": [{"type": "public-key", "alg": ES256}, {"type": "public-key", "alg": RS256}],
                "authenticatorSelection": {"userVerification": "required", "residentKey": "preferred"},
                "excludeCredentials": existing, "attestation": "none", "timeout": CHALLENGE_SECONDS * 1000}

    def add(self, rp_id: str, origins: set[str], client_data: str, attestation: str, name: str) -> dict:
        raw_client, client = self._client(client_data)
        self._use_challenge(client, "create", rp_id, origins)
        obj, _ = cbor_decode(webpush.unb64u(attestation))
        if not isinstance(obj, dict) or not isinstance(obj.get("authData"), bytes):
            raise PasskeyError("damaged passkey data")
        auth = parse_auth_data(obj["authData"])
        if not hmac.compare_digest(auth["rp_hash"], hashlib.sha256(rp_id.encode()).digest()):
            raise PasskeyError("that passkey was made for another address")
        if not (auth["flags"] & UP and auth["flags"] & UV):
            raise PasskeyError("the device didn't check your fingerprint, face or PIN")
        if "cose" not in auth:
            raise PasskeyError("damaged passkey data")
        key = public_key(auth["cose"])
        cred_id = webpush.b64u(auth["credential_id"])
        now = time.time()
        item = {"id": cred_id, "name": (" ".join(str(name).split()) or "Passkey")[:40], "rp_id": rp_id, "key": key,
                "count": auth["count"], "created": now, "last_used": None}
        with self._lock:
            items = [c for c in self._read() if c.get("id") != cred_id]
            if len(items) >= MAX_PASSKEYS:
                raise PasskeyError(f"there are already {MAX_PASSKEYS} passkeys; remove one first")
            items.append(item)
            self._write(items)
        return {k: item[k] for k in ("id", "name", "rp_id", "created", "last_used")}

    # -------------------------------------------------------------- signing in
    def request_options(self, rp_id: str) -> dict:
        allowed = [{"type": "public-key", "id": c["id"]} for c in self._read() if c.get("rp_id") == rp_id]
        return {"challenge": self._challenge("get", rp_id), "rpId": rp_id, "allowCredentials": allowed,
                "userVerification": "required", "timeout": CHALLENGE_SECONDS * 1000}

    def verify(self, rp_id: str, origins: set[str], cred_id: str, client_data: str, auth_data: str, signature: str) -> dict:
        """Check a sign-in; returns the passkey's record (its counter updated)."""
        raw_client, client = self._client(client_data)
        self._use_challenge(client, "get", rp_id, origins)
        with self._lock:
            items = self._read()
            item = next((c for c in items if c.get("id") == cred_id and c.get("rp_id") == rp_id), None)
            if item is None:
                raise PasskeyError("that passkey isn't known here (it may have been removed)")
            raw_auth = webpush.unb64u(auth_data)
            auth = parse_auth_data(raw_auth)
            if not hmac.compare_digest(auth["rp_hash"], hashlib.sha256(rp_id.encode()).digest()):
                raise PasskeyError("that passkey was made for another address")
            if not (auth["flags"] & UP and auth["flags"] & UV):
                raise PasskeyError("the device didn't check your fingerprint, face or PIN")
            message = raw_auth + hashlib.sha256(raw_client).digest()
            if not check_signature(item["key"], message, webpush.unb64u(signature)):
                raise PasskeyError("the passkey's signature doesn't match")
            if (auth["count"] or item.get("count")) and auth["count"] <= int(item.get("count") or 0):
                raise PasskeyError("that passkey looks copied (its counter went backwards); remove it and add it again")
            item["count"], item["last_used"] = auth["count"], time.time()
            self._write(items)
        return {k: item[k] for k in ("id", "name", "rp_id", "created", "last_used")}
