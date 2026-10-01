"""Web Push with the standard library only: what's needed to send a notification to a phone.

* P-256 (the elliptic curve Web Push uses): key pairs, ECDH and ECDSA signatures (ES256).
* AES-128-GCM, the cipher the message is encrypted with.
* RFC 8291 message encryption (``aes128gcm``) and RFC 8292 VAPID (the signed token that says who
  sends it).

Speed doesn't matter here (a few notifications, each a few hundred bytes), so this is written to
be simple and checkable rather than fast. The tests check it against the ``cryptography`` package.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import struct
import time

# ------------------------------------------------------------------ P-256
P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
A = P - 3
B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
G = (0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296,
     0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5)


def _add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2:
        if (y1 + y2) % P == 0:
            return None
        lam = (3 * x1 * x1 + A) * pow(2 * y1, -1, P) % P
    else:
        lam = (y2 - y1) * pow(x2 - x1, -1, P) % P
    x3 = (lam * lam - x1 - x2) % P
    return x3, (lam * (x1 - x3) - y1) % P


def _mul(k: int, point):
    result, addend = None, point
    while k:
        if k & 1:
            result = _add(result, addend)
        addend = _add(addend, addend)
        k >>= 1
    return result


def _on_curve(point) -> bool:
    x, y = point
    return 0 <= x < P and 0 <= y < P and (y * y - (x * x * x + A * x + B)) % P == 0


def public_bytes(point) -> bytes:
    """The uncompressed form (65 bytes, starting 0x04) Web Push uses."""
    return b"\x04" + point[0].to_bytes(32, "big") + point[1].to_bytes(32, "big")


def point_from(data: bytes):
    if len(data) != 65 or data[0] != 4:
        raise ValueError("not an uncompressed P-256 public key")
    point = (int.from_bytes(data[1:33], "big"), int.from_bytes(data[33:], "big"))
    if not _on_curve(point):
        raise ValueError("that key isn't on the P-256 curve")
    return point


def new_private() -> int:
    return secrets.randbelow(N - 1) + 1


def public_of(private: int):
    return _mul(private, G)


def ecdh(private: int, public_point) -> bytes:
    return _mul(private, public_point)[0].to_bytes(32, "big")


def sign(private: int, message: bytes) -> bytes:
    """ECDSA over SHA-256: r and s, 32 bytes each (the JWT form)."""
    e = int.from_bytes(hashlib.sha256(message).digest(), "big")
    while True:
        k = secrets.randbelow(N - 1) + 1
        r = _mul(k, G)[0] % N
        if not r:
            continue
        s = pow(k, -1, N) * (e + r * private) % N
        if s:
            return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def verify(public_point, message: bytes, signature: bytes) -> bool:
    r, s = int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
    if not (0 < r < N and 0 < s < N):
        return False
    e = int.from_bytes(hashlib.sha256(message).digest(), "big")
    w = pow(s, -1, N)
    point = _add(_mul(e * w % N, G), _mul(r * w % N, public_point))
    return point is not None and point[0] % N == r


# ---------------------------------------------------------------- AES-GCM
def _sbox() -> list[int]:
    box, p, q = [0] * 256, 1, 1
    while True:  # (the standard construction from the multiplicative inverse in GF(2^8))
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ ((q << 1 | q >> 7) & 0xFF) ^ ((q << 2 | q >> 6) & 0xFF) ^ ((q << 3 | q >> 5) & 0xFF) ^ ((q << 4 | q >> 4) & 0xFF)
        box[p] = x ^ 0x63
        if p == 1:
            break
    box[0] = 0x63
    return box


SBOX = _sbox()


def _xtime(b: int) -> int:
    return ((b << 1) ^ 0x1B) & 0xFF if b & 0x80 else b << 1


def _expand(key: bytes) -> list[list[int]]:
    words = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for i in range(4, 44):
        t = list(words[i - 1])
        if i % 4 == 0:
            t = [SBOX[b] for b in t[1:] + t[:1]]
            t[0] ^= rcon
            rcon = _xtime(rcon)
        words.append([a ^ b for a, b in zip(words[i - 4], t)])
    return [sum(words[r * 4:r * 4 + 4], []) for r in range(11)]


def _encrypt_block(keys: list[list[int]], block: bytes) -> bytes:
    s = [b ^ k for b, k in zip(block, keys[0])]
    for rnd in range(1, 11):
        s = [SBOX[b] for b in s]
        s = [s[(i + 4 * (i % 4)) % 16] for i in range(16)]  # ShiftRows (column-major state)
        if rnd != 10:
            mixed = []
            for c in range(4):
                a = s[4 * c:4 * c + 4]
                t = a[0] ^ a[1] ^ a[2] ^ a[3]
                mixed += [a[i] ^ t ^ _xtime(a[i] ^ a[(i + 1) % 4]) for i in range(4)]
            s = mixed
        s = [b ^ k for b, k in zip(s, keys[rnd])]
    return bytes(s)


def _gmul(x: int, y: int) -> int:
    R = 0xE1 << 120
    z, v = 0, y
    for i in range(127, -1, -1):
        if (x >> i) & 1:
            z ^= v
        v = (v >> 1) ^ R if v & 1 else v >> 1
    return z


def aes_gcm_encrypt(key: bytes, nonce: bytes, plaintext: bytes, aad: bytes = b"") -> bytes:
    """AES-128-GCM with a 12-byte nonce: the ciphertext followed by the 16-byte tag."""
    if len(key) != 16 or len(nonce) != 12:
        raise ValueError("AES-128-GCM needs a 16-byte key and a 12-byte nonce")
    keys = _expand(key)
    h = int.from_bytes(_encrypt_block(keys, bytes(16)), "big")
    out = bytearray()
    for i in range(0, len(plaintext), 16):
        counter = nonce + struct.pack(">I", i // 16 + 2)
        stream = _encrypt_block(keys, counter)
        out += bytes(a ^ b for a, b in zip(plaintext[i:i + 16], stream))

    def blocks(data: bytes):
        for i in range(0, len(data), 16):
            yield int.from_bytes(data[i:i + 16].ljust(16, b"\0"), "big")
    g = 0
    for x in [*blocks(aad), *blocks(bytes(out)), (len(aad) * 8 << 64) | len(out) * 8]:
        g = _gmul(g ^ x, h)
    tag = int.from_bytes(_encrypt_block(keys, nonce + b"\0\0\0\1"), "big") ^ g
    return bytes(out) + tag.to_bytes(16, "big")


# ---------------------------------------------------------------- Web Push
def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _hmac(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def encrypt(plaintext: bytes, ua_public: bytes, auth_secret: bytes, *, as_private: int | None = None,
            salt: bytes | None = None) -> bytes:
    """RFC 8291: ``plaintext`` for the browser whose subscription keys are ``ua_public`` (p256dh)
    and ``auth_secret``; one ``aes128gcm`` record. (``as_private`` and ``salt`` are for tests.)"""
    ua_point = point_from(ua_public)
    as_private = as_private or new_private()
    as_public = public_bytes(public_of(as_private))
    salt = salt or secrets.token_bytes(16)
    shared = ecdh(as_private, ua_point)
    prk_key = _hmac(auth_secret, shared)
    ikm = _hmac(prk_key, b"WebPush: info\0" + ua_public + as_public + b"\x01")
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\0\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\0\x01")[:12]
    body = aes_gcm_encrypt(cek, nonce, plaintext + b"\x02")
    return salt + struct.pack(">I", 4096) + bytes([len(as_public)]) + as_public + body


def vapid_header(private: int, endpoint: str, subject: str, now: float | None = None) -> str:
    """RFC 8292: the ``Authorization`` header for a push to ``endpoint``."""
    from urllib.parse import urlparse
    u = urlparse(endpoint)
    claims = {"aud": f"{u.scheme}://{u.netloc}", "exp": int((now or time.time()) + 12 * 3600), "sub": subject}
    head = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    body = b64u(json.dumps(claims, separators=(",", ":")).encode())
    signing = f"{head}.{body}".encode()
    token = f"{head}.{body}.{b64u(sign(private, signing))}"
    return f"vapid t={token}, k={b64u(public_bytes(public_of(private)))}"
