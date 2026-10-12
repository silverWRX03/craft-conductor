"""Locked to this computer and account: the sensitive part of a backup (passwords, keys, players'
IP addresses, logs). Craft Conductor here opens it; another computer, or another account on this
one, can't.

The key is made once per installation, in ``<home>/.craft-conductor/backup.key``. On Windows the
file holds it sealed with Windows' own protection for this account (DPAPI), so a copy of the
file is useless elsewhere; on Linux and macOS it's readable by this account only (private.py).
Data is encrypted with keyed BLAKE2b in counter mode (a pseudorandom function as a stream
cipher) and authenticated with HMAC-SHA256: all from the standard library, at tens of megabytes
a second, where AES in plain Python would take minutes for a big log folder.

Losing the key (deleting the file, a new Windows account) loses only what was locked: restoring
such a backup keeps the server's current passwords, keys and IP bans.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import threading
from pathlib import Path

from . import private

log = logging.getLogger(__name__)

MAGIC = b"CCLOCK1\n"
KEY_FILE = "backup.key"
CHUNK = 1 << 20
_lock = threading.Lock()


class LockedElsewhere(ValueError):
    """Locked on another computer or account (or with a key that's gone)."""


def key_file() -> Path:
    home = Path(os.environ.get("CRAFT_CONDUCTOR_HOME") or Path.home() / "craft-conductor")
    return home.resolve() / ".craft-conductor" / KEY_FILE


def _key(create: bool) -> bytes | None:
    path = key_file()
    with _lock:
        try:
            stored = path.read_bytes()
        except FileNotFoundError:
            if not create:
                return None
            key = secrets.token_bytes(32)
            path.parent.mkdir(parents=True, exist_ok=True)
            private.write_bytes(path, _seal(key))
            log.info("made the key that locks backups' passwords, keys and logs to this computer (%s)", path)
            return key
        try:
            key = _unseal(stored)
        except OSError as e:
            raise LockedElsewhere(f"this computer's backup key ({path}) can't be opened by this account: {e}") from None
        if len(key) != 32:
            raise LockedElsewhere(f"this computer's backup key ({path}) is damaged")
        return key


def _key_id(key: bytes) -> bytes:
    return hashlib.sha256(b"craft-conductor backup key\0" + key).digest()[:8]


def _subkeys(key: bytes) -> tuple[bytes, bytes]:
    return (hashlib.blake2b(b"encrypt", key=key, digest_size=32).digest(),
            hashlib.blake2b(b"authenticate", key=key, digest_size=32).digest())


def _keystream(enc_key: bytes, nonce: bytes, first_block: int, length: int) -> bytes:
    blocks = (length + 63) // 64
    return b"".join(hashlib.blake2b(nonce + (first_block + i).to_bytes(8, "little"), key=enc_key, digest_size=64).digest()
                    for i in range(blocks))[:length]


def _xor(data: bytes, stream: bytes) -> bytes:
    return (int.from_bytes(data, "little") ^ int.from_bytes(stream, "little")).to_bytes(len(data), "little")


def lock_file(src: Path, dst: Path) -> None:
    """``dst``: ``src`` locked to this computer and account (``dst`` is this account's only)."""
    key = _key(create=True)
    enc_key, mac_key = _subkeys(key)
    nonce = secrets.token_bytes(16)
    header = MAGIC + _key_id(key) + nonce
    mac = hmac.new(mac_key, header, "sha256")
    os.close(os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600))
    private.protect(dst)
    with open(src, "rb") as f, open(dst, "wb") as out:
        out.write(header)
        block = 0
        while chunk := f.read(CHUNK):
            body = _xor(chunk, _keystream(enc_key, nonce, block, len(chunk)))
            block += len(chunk) // 64  # (CHUNK is a whole number of 64-byte blocks)
            mac.update(body)
            out.write(body)
        out.write(mac.digest())


def unlock_file(src: Path, dst: Path) -> None:
    """``dst``: what ``lock_file`` locked into ``src``. LockedElsewhere if it was locked on another
    computer or account; ValueError if it was changed or damaged. Nothing is written then."""
    key = _key(create=False)
    size = src.stat().st_size
    with open(src, "rb") as f:
        header = f.read(len(MAGIC) + 24)
        if len(header) < len(MAGIC) + 24 or not header.startswith(MAGIC) or size < len(header) + 32:
            raise ValueError("the locked part of the backup is damaged")
        if key is None or not hmac.compare_digest(header[len(MAGIC):len(MAGIC) + 8], _key_id(key)):
            raise LockedElsewhere("it was locked on another computer or account")
        enc_key, mac_key = _subkeys(key)
        nonce = header[len(MAGIC) + 8:]
        body_size = size - len(header) - 32
        mac = hmac.new(mac_key, header, "sha256")
        left = body_size
        while left:  # first: is it whole and unchanged? (nothing is written before that's known)
            chunk = f.read(min(CHUNK, left))
            if not chunk:
                raise ValueError("the locked part of the backup is cut short")
            mac.update(chunk)
            left -= len(chunk)
        if not hmac.compare_digest(mac.digest(), f.read(32)):
            raise ValueError("the locked part of the backup was changed or damaged")
        f.seek(len(header))
        with open(dst, "wb") as out:
            block, left = 0, body_size
            while left:
                chunk = f.read(min(CHUNK, left))
                out.write(_xor(chunk, _keystream(enc_key, nonce, block, len(chunk))))
                block += len(chunk) // 64
                left -= len(chunk)


def lock(data: bytes) -> bytes:
    """``data`` locked to this computer and account (for small things, like a backup's note)."""
    key = _key(create=True)
    enc_key, mac_key = _subkeys(key)
    nonce = secrets.token_bytes(16)
    header = MAGIC + _key_id(key) + nonce
    body = _xor(data, _keystream(enc_key, nonce, 0, len(data)))
    return header + body + hmac.new(mac_key, header + body, "sha256").digest()


def unlock(blob: bytes) -> bytes:
    key = _key(create=False)
    if len(blob) < len(MAGIC) + 56 or not blob.startswith(MAGIC):
        raise ValueError("the locked part is damaged")
    header, body, tag = blob[:len(MAGIC) + 24], blob[len(MAGIC) + 24:-32], blob[-32:]
    if key is None or not hmac.compare_digest(header[len(MAGIC):len(MAGIC) + 8], _key_id(key)):
        raise LockedElsewhere("it was locked on another computer or account")
    enc_key, mac_key = _subkeys(key)
    if not hmac.compare_digest(hmac.new(mac_key, header + body, "sha256").digest(), tag):
        raise ValueError("the locked part was changed or damaged")
    return _xor(body, _keystream(enc_key, header[len(MAGIC) + 8:], 0, len(body)))


# --------------------------------------------------------- the key on disk
def _seal(key: bytes) -> bytes:
    return b"DPAPI\n" + _dpapi(key, protect=True) if os.name == "nt" else key


def _unseal(stored: bytes) -> bytes:
    if stored.startswith(b"DPAPI\n"):
        if os.name != "nt":
            raise OSError("it was sealed by Windows")
        return _dpapi(stored[6:], protect=False)
    return stored


def _dpapi(data: bytes, protect: bool) -> bytes:
    """Windows' own protection for this account (CryptProtectData / CryptUnprotectData)."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    for fn in (crypt32.CryptProtectData, crypt32.CryptUnprotectData):
        fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p,
                       ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        fn.restype = wintypes.BOOL
    buf, purpose = ctypes.create_string_buffer(data, len(data)), b"craft-conductor backup key"
    pbuf = ctypes.create_string_buffer(purpose, len(purpose))
    inp = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    entropy = Blob(len(purpose), ctypes.cast(pbuf, ctypes.POINTER(ctypes.c_char)))
    out = Blob()
    UI_FORBIDDEN = 0x1
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(inp), None, ctypes.byref(entropy), None, None, UI_FORBIDDEN, ctypes.byref(out)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))
