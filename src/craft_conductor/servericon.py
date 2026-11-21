"""The picture players see next to a server in Minecraft's server list: ``server-icon.png`` in the
server's folder, a 64 × 64 PNG. Minecraft reads it when the server starts.

The page shrinks whatever picture is chosen to 64 × 64 before sending it; here it's only checked
(the standard library has no image library): a PNG signature, then an intact IHDR chunk saying
64 × 64. Anything else is refused and the icon there stays as it was.
"""

from __future__ import annotations

import os
import stat
import struct
import zlib
from pathlib import Path

FILE = "server-icon.png"
MAX_BYTES = 64 * 1024   # (a 64 × 64 picture is a few KB; Minecraft refuses big ones anyway)
SIGNATURE = b"\x89PNG\r\n\x1a\n"


def check(data: bytes) -> None:
    """Raise ValueError, in plain words, unless ``data`` is a 64 × 64 PNG."""
    if len(data) > MAX_BYTES:
        raise ValueError(f"that picture is too big ({len(data) // 1024} KB); a server icon is at most "
                         f"{MAX_BYTES // 1024} KB")
    if len(data) < 33 or not data.startswith(SIGNATURE) or data[12:16] != b"IHDR":
        raise ValueError("a server icon has to be a PNG picture")
    length, = struct.unpack(">I", data[8:12])
    if length != 13:
        raise ValueError("that PNG picture is damaged")
    body, crc = data[12:29], struct.unpack(">I", data[29:33])[0]
    if zlib.crc32(body) & 0xFFFFFFFF != crc:
        raise ValueError("that PNG picture is damaged")
    width, height = struct.unpack(">II", data[16:24])
    if (width, height) != (64, 64):
        raise ValueError(f"a server icon must be 64 × 64 pixels (this one is {width} × {height})")


def save(server_dir: Path, data: bytes) -> None:
    """Check ``data`` and put it in place whole (a new file, then renamed over the old one)."""
    check(data)
    dest = Path(server_dir) / FILE
    tmp = dest.with_name(FILE + ".tmp")
    tmp.unlink(missing_ok=True)  # (a leftover, or a link: never written through)
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0), 0o644)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)


def remove(server_dir: Path) -> bool:
    """Back to Minecraft's default picture. False when there was no icon."""
    try:
        (Path(server_dir) / FILE).unlink()
        return True
    except FileNotFoundError:
        return False


def _plain(server_dir: Path) -> os.stat_result | None:
    """The icon file's own details, unless it's missing, a link (or junction), not a plain file, or too big."""
    from .folders import link_stat
    try:
        st = os.lstat(Path(server_dir) / FILE)
    except OSError:
        return None
    if link_stat(st) or not stat.S_ISREG(st.st_mode) or st.st_size > MAX_BYTES:
        return None
    return st


def read(server_dir: Path) -> bytes | None:
    """The icon, only if it's a real one: anything else called server-icon.png (put there by hand, by a mod,
    or a link to another file) is never sent to the page."""
    if _plain(server_dir) is None:
        return None
    try:
        fd = os.open(Path(server_dir) / FILE, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as f:
            data = f.read(MAX_BYTES + 1)
        check(data)
    except (OSError, ValueError):
        return None
    return data


def stamp(server_dir: Path) -> int | None:
    """When the icon last changed (milliseconds), for the page to ask for the new one; None without one.
    (Only the file's details: the server list asks often.)"""
    st = _plain(server_dir)
    return st.st_mtime_ns // 1_000_000 if st else None
