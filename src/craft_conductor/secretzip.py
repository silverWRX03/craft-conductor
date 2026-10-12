"""A small zip whose files are encrypted with a password: the passwords, keys and IP bans a
server export carries when they're chosen (transfer.py).

It's WinZip's AES-256 format ("AE-2", the one 7-Zip makes with ``-mem=AES256``): each file is
AES-256 encrypted in counter mode and authenticated with HMAC-SHA1, under keys derived from the
password with PBKDF2 (1,000 rounds, as the format fixes; the password is random and long, see
``new_password``, so guessing it is out of reach anyway). 7-Zip, WinZip and Craft Conductor's own
**Import a server...** open it; the zip folders built into Windows and macOS can't.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import secrets
import struct
import time
import zipfile
import zlib

from . import aes

ROUNDS = 1000            # PBKDF2 rounds: fixed by the format
SALT = 16                # bytes, for AES-256
WORDS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # (no 0/O, 1/I/L: read aloud or copied by hand)


class BadPassword(ValueError):
    pass


def new_password() -> str:
    """Six groups of four, like ``K7QM-2XHD-...``: 120 random bits."""
    return "-".join("".join(secrets.choice(WORDS) for _ in range(4)) for _ in range(6))


def _keys(password: str, salt: bytes) -> tuple[bytes, bytes, bytes]:
    derived = hashlib.pbkdf2_hmac("sha1", password.encode("utf-8"), salt, ROUNDS, 2 * 32 + 2)
    return derived[:32], derived[32:64], derived[64:]


def _dos_time(t: float) -> tuple[int, int]:
    y, mo, d, h, mi, s = time.localtime(t)[:6]
    return (h << 11) | (mi << 5) | (s // 2), ((max(y, 1980) - 1980) << 9) | (mo << 5) | d


def encrypt(files: dict[str, bytes], password: str) -> bytes:
    """A zip of ``files`` (name: content), every one encrypted with ``password``."""
    out, central = io.BytesIO(), []
    clock, day = _dos_time(time.time())
    for name, data in files.items():
        packed = zlib.compressobj(9, zlib.DEFLATED, -15)
        compressed = packed.compress(data) + packed.flush()
        salt = secrets.token_bytes(SALT)
        enc_key, mac_key, check = _keys(password, salt)
        body = aes.ctr_little_endian(enc_key, compressed)
        payload = salt + check + body + hmac.new(mac_key, body, "sha1").digest()[:10]
        raw = name.encode("utf-8")
        extra = struct.pack("<HHH2sBH", 0x9901, 7, 2, b"AE", 3, 8)  # AE-2, AES-256, deflated inside
        offset = out.tell()
        out.write(struct.pack("<IHHHHHIIIHH", 0x04034B50, 51, 0x0801, 99, clock, day, 0,
                              len(payload), len(data), len(raw), len(extra)) + raw + extra + payload)
        central.append(struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 63, 51, 0x0801, 99, clock, day, 0,
                                   len(payload), len(data), len(raw), len(extra), 0, 0, 0, 0, offset) + raw + extra)
    start = out.tell()
    for entry in central:
        out.write(entry)
    out.write(struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(central), len(central), out.tell() - start, start, 0))
    return out.getvalue()


def decrypt(data: bytes, password: str) -> dict[str, bytes]:
    """The files in a zip made by ``encrypt`` (or by 7-Zip with AES-256). BadPassword if the
    password isn't the one it was locked with; ValueError if it's damaged or something else."""
    files = {}
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ValueError("the locked part of the export is damaged") from e
    with z:
        for info in z.infolist():
            if info.is_dir():
                continue
            if info.compress_type != 99:
                raise ValueError(f"{info.filename} in the locked part isn't encrypted")
            strength, inner = _aes_extra(info.extra)
            if strength != 3:
                raise ValueError(f"{info.filename} isn't AES-256 encrypted")
            if data[info.header_offset:info.header_offset + 4] != b"PK\x03\x04":
                raise ValueError("the locked part of the export is damaged")
            name_len, extra_len = struct.unpack("<HH", data[info.header_offset + 26:info.header_offset + 30])
            start = info.header_offset + 30 + name_len + extra_len
            payload = data[start:start + info.compress_size]
            if len(payload) < SALT + 12:
                raise ValueError("the locked part of the export is damaged")
            salt, check, body, mac = payload[:SALT], payload[SALT:SALT + 2], payload[SALT + 2:-10], payload[-10:]
            enc_key, mac_key, expected = _keys(password, salt)
            if not hmac.compare_digest(check, expected):
                raise BadPassword("that password isn't the one this export was locked with")
            if not hmac.compare_digest(hmac.new(mac_key, body, "sha1").digest()[:10], mac):
                raise ValueError("the locked part of the export was changed or damaged")
            plain = aes.ctr_little_endian(enc_key, body)
            if inner == 8:
                plain = zlib.decompress(plain, -15)
            elif inner != 0:
                raise ValueError(f"{info.filename} is packed in a way Craft Conductor can't read")
            if len(plain) != info.file_size:
                raise ValueError("the locked part of the export is damaged")
            files[info.filename] = plain
    return files


def _aes_extra(extra: bytes) -> tuple[int, int]:
    """(AES strength, the compression inside) from a zip entry's extra field."""
    i = 0
    while i + 4 <= len(extra):
        tag, size = struct.unpack("<HH", extra[i:i + 4])
        if tag == 0x9901 and size >= 7:
            _version, vendor, strength, inner = struct.unpack("<H2sBH", extra[i + 4:i + 11])
            if vendor == b"AE":
                return strength, inner
        i += 4 + size
    raise ValueError("a file in the locked part isn't AES encrypted")
