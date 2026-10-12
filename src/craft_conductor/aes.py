"""AES (FIPS-197) for the password-protected part of a server export (secretzip.py).

Plain Python, as Craft Conductor uses only the standard library: a few hundred kilobytes a
second, plenty for the few kilobytes of passwords and keys it protects. Only encryption is
needed (counter mode).
"""

from __future__ import annotations


def _xtime(b: int) -> int:
    return ((b << 1) ^ 0x1B) & 0xFF if b & 0x80 else b << 1


def _sbox() -> list[int]:
    box, p, q = [0] * 256, 1, 1
    while True:  # (the multiplicative inverse in GF(2^8), then the affine map)
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
# One round's SubBytes, ShiftRows and MixColumns as table lookups, a column at a time.
_T0 = [(_xtime(s) << 24) | (s << 16) | (s << 8) | (_xtime(s) ^ s) for s in SBOX]
_T1 = [((t >> 8) | (t << 24)) & 0xFFFFFFFF for t in _T0]
_T2 = [((t >> 16) | (t << 16)) & 0xFFFFFFFF for t in _T0]
_T3 = [((t >> 24) | (t << 8)) & 0xFFFFFFFF for t in _T0]


def _sub_word(w: int) -> int:
    return SBOX[w >> 24] << 24 | SBOX[(w >> 16) & 255] << 16 | SBOX[(w >> 8) & 255] << 8 | SBOX[w & 255]


def expand(key: bytes) -> list[int]:
    """The round keys for a 16-, 24- or 32-byte key, as 32-bit words."""
    if len(key) not in (16, 24, 32):
        raise ValueError("an AES key is 16, 24 or 32 bytes")
    nk = len(key) // 4
    words = [int.from_bytes(key[4 * i:4 * i + 4], "big") for i in range(nk)]
    rcon = 1
    for i in range(nk, 4 * (nk + 7)):
        t = words[i - 1]
        if i % nk == 0:
            t = _sub_word(((t << 8) | (t >> 24)) & 0xFFFFFFFF) ^ (rcon << 24)
            rcon = _xtime(rcon)
        elif nk > 6 and i % nk == 4:
            t = _sub_word(t)
        words.append(words[i - nk] ^ t)
    return words


def encrypt_block(rk: list[int], block: bytes) -> bytes:
    """One 16-byte block, with round keys from expand()."""
    t0, t1, t2, t3 = _T0, _T1, _T2, _T3
    s0 = int.from_bytes(block[0:4], "big") ^ rk[0]
    s1 = int.from_bytes(block[4:8], "big") ^ rk[1]
    s2 = int.from_bytes(block[8:12], "big") ^ rk[2]
    s3 = int.from_bytes(block[12:16], "big") ^ rk[3]
    rounds = len(rk) // 4 - 1
    for r in range(4, 4 * rounds, 4):
        s0, s1, s2, s3 = (
            t0[s0 >> 24] ^ t1[(s1 >> 16) & 255] ^ t2[(s2 >> 8) & 255] ^ t3[s3 & 255] ^ rk[r],
            t0[s1 >> 24] ^ t1[(s2 >> 16) & 255] ^ t2[(s3 >> 8) & 255] ^ t3[s0 & 255] ^ rk[r + 1],
            t0[s2 >> 24] ^ t1[(s3 >> 16) & 255] ^ t2[(s0 >> 8) & 255] ^ t3[s1 & 255] ^ rk[r + 2],
            t0[s3 >> 24] ^ t1[(s0 >> 16) & 255] ^ t2[(s1 >> 8) & 255] ^ t3[s2 & 255] ^ rk[r + 3])
    s, r = SBOX, 4 * rounds  # (the last round has no MixColumns)
    out = (
        (s[s0 >> 24] << 24 | s[(s1 >> 16) & 255] << 16 | s[(s2 >> 8) & 255] << 8 | s[s3 & 255]) ^ rk[r],
        (s[s1 >> 24] << 24 | s[(s2 >> 16) & 255] << 16 | s[(s3 >> 8) & 255] << 8 | s[s0 & 255]) ^ rk[r + 1],
        (s[s2 >> 24] << 24 | s[(s3 >> 16) & 255] << 16 | s[(s0 >> 8) & 255] << 8 | s[s1 & 255]) ^ rk[r + 2],
        (s[s3 >> 24] << 24 | s[(s0 >> 16) & 255] << 16 | s[(s1 >> 8) & 255] << 8 | s[s2 & 255]) ^ rk[r + 3])
    return b"".join(w.to_bytes(4, "big") for w in out)


def ctr_little_endian(key: bytes, data: bytes, first: int = 1) -> bytes:
    """``data`` encrypted (or decrypted: it's the same) in counter mode with the counter as a
    16-byte little-endian number from ``first``, as WinZip's AES zips do."""
    rk = expand(key)
    blocks = (len(data) + 15) // 16
    stream = b"".join(encrypt_block(rk, (first + i).to_bytes(16, "little")) for i in range(blocks))[:len(data)]
    return (int.from_bytes(data, "big") ^ int.from_bytes(stream, "big")).to_bytes(len(data), "big")
