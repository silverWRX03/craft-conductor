"""mcsm's own TLS certificate, for the share server friends' mcsm connects to.

There's no domain name to get a certificate for, so mcsm makes its own (self-signed) and
puts its fingerprint in the invite: a friend's mcsm checks the server presents exactly
this certificate, which nobody else can fake without the private key. Browsers aren't
involved, so nobody sees a warning.

Python's standard library can use certificates but not make them, so this builds one by
hand: an RSA-2048 key (Miller-Rabin primes from ``secrets``), and an X.509 v3 certificate
signed with it (SHA-256, PKCS #1 v1.5), in DER/PEM for ``ssl.SSLContext.load_cert_chain``.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import json
import os
import secrets
import ssl
from pathlib import Path

E = 65537
KEY_BITS = 2048
VALID_DAYS = 3650          # pinned by fingerprint, so a long life is fine
RENEW_DAYS = 30            # make a new one this close to the end (invites then change)
CERT_FILE, KEY_FILE = "share-cert.pem", "share-key.pem"


# ------------------------------------------------------------------ DER
def _len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def _tlv(tag: int, content: bytes) -> bytes:
    return bytes([tag]) + _len(len(content)) + content


def _int(n: int) -> bytes:
    raw = n.to_bytes(n.bit_length() // 8 + 1, "big")  # room for a sign bit
    return _tlv(0x02, raw)


def _seq(*items: bytes) -> bytes:
    return _tlv(0x30, b"".join(items))


def _oid(dotted: str) -> bytes:
    parts = [int(x) for x in dotted.split(".")]
    out = bytes([40 * parts[0] + parts[1]])
    for p in parts[2:]:
        chunk = [p & 0x7F]
        p >>= 7
        while p:
            chunk.append(0x80 | (p & 0x7F))
            p >>= 7
        out += bytes(reversed(chunk))
    return _tlv(0x06, out)


def _time(t: datetime.datetime) -> bytes:
    if t.year < 2050:
        return _tlv(0x17, t.strftime("%y%m%d%H%M%SZ").encode())      # UTCTime
    return _tlv(0x18, t.strftime("%Y%m%d%H%M%SZ").encode())          # GeneralizedTime


NULL = b"\x05\x00"
SHA256_RSA = _seq(_oid("1.2.840.113549.1.1.11"), NULL)
RSA_KEY = _seq(_oid("1.2.840.113549.1.1.1"), NULL)
SHA256 = _seq(_oid("2.16.840.1.101.3.4.2.1"), NULL)


# ------------------------------------------------------------------ RSA
_SMALL_PRIMES = [p for p in range(3, 2000) if all(p % d for d in range(2, int(p ** 0.5) + 1))]


def _probably_prime(n: int, rounds: int = 40) -> bool:
    if any(n % p == 0 for p in _SMALL_PRIMES):
        return n in _SMALL_PRIMES
    d, s = n - 1, 0
    while d % 2 == 0:
        d, s = d // 2, s + 1
    for _ in range(rounds):
        x = pow(secrets.randbelow(n - 3) + 2, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _prime(bits: int) -> int:
    while True:
        n = secrets.randbits(bits) | (0b11 << (bits - 2)) | 1  # full length, odd
        if (n - 1) % E and _probably_prime(n):
            return n


def generate_key(bits: int = KEY_BITS) -> dict:
    while True:
        p, q = _prime(bits // 2), _prime(bits // 2)
        n = p * q
        if p != q and n.bit_length() == bits:
            break
    d = pow(E, -1, (p - 1) * (q - 1))
    return {"n": n, "e": E, "d": d, "p": p, "q": q}


def _sign(key: dict, data: bytes) -> bytes:
    k = (key["n"].bit_length() + 7) // 8
    digest_info = _seq(SHA256, _tlv(0x04, hashlib.sha256(data).digest()))
    em = b"\x00\x01" + b"\xff" * (k - len(digest_info) - 3) + b"\x00" + digest_info
    return pow(int.from_bytes(em, "big"), key["d"], key["n"]).to_bytes(k, "big")


def key_pem(key: dict) -> str:
    p, q, d = key["p"], key["q"], key["d"]
    der = _seq(_int(0), _int(key["n"]), _int(key["e"]), _int(d), _int(p), _int(q),
               _int(d % (p - 1)), _int(d % (q - 1)), _int(pow(q, -1, p)))
    return _pem("RSA PRIVATE KEY", der)


def _pem(label: str, der: bytes) -> str:
    b64 = base64.b64encode(der).decode()
    lines = "\n".join(b64[i:i + 64] for i in range(0, len(b64), 64))
    return f"-----BEGIN {label}-----\n{lines}\n-----END {label}-----\n"


# ----------------------------------------------------------- certificate
def make_certificate(key: dict, name: str = "mcsm", now: datetime.datetime | None = None,
                     days: int = VALID_DAYS) -> bytes:
    """A self-signed X.509 v3 certificate (DER) for ``key``."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    subject = _seq(_tlv(0x31, _seq(_oid("2.5.4.3"), _tlv(0x0C, name.encode()))))  # CN=name
    public = _seq(_int(key["n"]), _int(key["e"]))
    spki = _seq(RSA_KEY, _tlv(0x03, b"\x00" + public))
    extensions = _tlv(0xA3, _seq(
        _seq(_oid("2.5.29.19"), _tlv(0x04, _seq())),                              # basicConstraints: not a CA
        _seq(_oid("2.5.29.17"), _tlv(0x04, _seq(_tlv(0x82, name.encode())))),     # subjectAltName: DNS:name
    ))
    tbs = _seq(
        _tlv(0xA0, _int(2)),                                   # v3
        _int(secrets.randbits(127) | 1),                       # serial
        SHA256_RSA,
        subject,                                               # issuer: itself
        _seq(_time(now - datetime.timedelta(days=1)), _time(now + datetime.timedelta(days=days))),
        subject,
        spki,
        extensions,
    )
    return _seq(tbs, SHA256_RSA, _tlv(0x03, b"\x00" + _sign(key, tbs)))


def fingerprint(cert_der: bytes) -> str:
    """What an invite carries: the certificate's SHA-256, in 43 URL-safe characters."""
    return base64.urlsafe_b64encode(hashlib.sha256(cert_der).digest()).decode().rstrip("=")


def _expires(cert_path: Path) -> datetime.datetime | None:
    """When the certificate runs out (recorded next to it when it was made)."""
    try:
        ts = float(json.loads(cert_path.with_suffix(".json").read_text())["expires"])
        return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def ensure(folder: Path) -> tuple[Path, Path, str]:
    """This computer's share certificate (made once, renewed near the end of its life):
    (certificate file, key file, fingerprint)."""
    cert_path, key_path = folder / CERT_FILE, folder / KEY_FILE
    expires = _expires(cert_path) if cert_path.exists() and key_path.exists() else None
    now = datetime.datetime.now(datetime.timezone.utc)
    if expires is None or expires - now < datetime.timedelta(days=RENEW_DAYS):
        folder.mkdir(parents=True, exist_ok=True)
        key = generate_key()
        tmp = key_path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # the private key: owner only
        with os.fdopen(fd, "w") as f:
            f.write(key_pem(key))
        os.replace(tmp, key_path)
        cert_path.write_text(_pem("CERTIFICATE", make_certificate(key, now=now)))
        cert_path.with_suffix(".json").write_text(json.dumps({"expires": (now + datetime.timedelta(days=VALID_DAYS)).timestamp()}))
    der = ssl.PEM_cert_to_DER_cert(cert_path.read_text())
    return cert_path, key_path, fingerprint(der)


def server_context(cert_path: Path, key_path: Path) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert_path, key_path)
    return ctx
