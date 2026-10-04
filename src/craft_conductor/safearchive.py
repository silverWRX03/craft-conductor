"""Unpacking archives (worlds, modpacks, server exports, backups) safely.

Every name inside an archive is untrusted: it may try to climb out of the folder (``../``),
start at the top of the disk (``/etc``, ``C:\\``, ``\\\\server\\share``), hide a Windows data
stream (``level.dat:evil``), name a Windows device (``NUL``, ``COM1.txt``), or carry control
characters that garble logs. An archive may also expand to far more than it looks (a zip bomb),
list millions of members (each costs memory before a single file is written), or arrive while
the disk is nearly full. The helpers here refuse all of that, and say why in the log.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import struct
from pathlib import Path
from typing import BinaryIO, Callable

log = logging.getLogger(__name__)

#: free space left over after an import or a restore (Minecraft still has to save the world)
DISK_RESERVE = 256 << 20

# Names Windows keeps for devices, in every folder and with any extension ("NUL.txt" is NUL).
_RESERVED = re.compile(r"(?i)^(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³]|conin\$|conout\$)(\..*)?$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
# Shown escaped in logs: control characters, and the ones that reverse how text reads.
_UNPRINTABLE = re.compile(r"[\x00-\x1f\x7f\u200e\u200f\u202a-\u202e\u2066-\u2069]")
_isjunction = getattr(os.path, "isjunction", lambda path: False)  # (Python 3.12+; Windows only)


def is_link(path: Path) -> bool:
    """A symbolic link, or a Windows junction (a link to a folder)."""
    return path.is_symlink() or _isjunction(path)


class UnsafeName(ValueError):
    """An archive member that can't be written where it says."""


def printable(name: str, limit: int = 120) -> str:
    """``name`` safe to put in a log line: control characters escaped, long names cut short."""
    shown = _UNPRINTABLE.sub(lambda m: f"\\u{ord(m.group()):04x}", name)
    return shown if len(shown) <= limit else shown[:limit] + "…"


def parts(name: str) -> tuple[str, ...]:
    """The folders and file name of an archive member, checked; raises :class:`UnsafeName`."""
    if not name:
        raise UnsafeName("it has no name")
    if _CONTROL.search(name):
        raise UnsafeName("its name has a control character")
    norm = name.replace("\\", "/")
    if norm.startswith("/"):
        raise UnsafeName("it's an absolute path")
    out = []
    for part in norm.split("/"):
        if part == ".":
            continue
        if part == "":
            raise UnsafeName("its name has an empty folder name")
        if part == "..":
            raise UnsafeName("it points outside the folder (..)")
        if ":" in part:
            raise UnsafeName("its name has a colon (a drive letter or a hidden Windows data stream)")
        if part != part.rstrip(". "):
            raise UnsafeName("a name in it ends with a dot or a space, which Windows changes")
        if _RESERVED.match(part):
            raise UnsafeName(f"{part!r} is the name of a device on Windows")
        out.append(part)
    if not out:
        raise UnsafeName("it has no name")
    return tuple(out)


def plain_name(name: str) -> bool:
    """True for a single, ordinary folder or file name (no path, not hidden)."""
    try:
        return len(parts(name)) == 1 and not name.startswith(".") and "/" not in name and "\\" not in name
    except UnsafeName:
        return False


class Skipped:
    """Members left out of an archive, logged once at the end: an archive with a million bad
    names makes one warning, not a million."""

    EXAMPLES = 5

    def __init__(self, what: str):
        self.what = what
        self.count = 0
        self.examples: list[str] = []

    def add(self, name: str, reason: str) -> None:
        self.count += 1
        if len(self.examples) < self.EXAMPLES:
            self.examples.append(f"{printable(name)} ({reason})")

    def log(self) -> None:
        if self.count:
            more = f" and {self.count - len(self.examples)} more" if self.count > len(self.examples) else ""
            log.warning("left %d file(s) out of %s because they could have been written outside their folder "
                        "or can't be made on every computer: %s%s",
                        self.count, self.what, "; ".join(self.examples), more)


def zip_entries(path: Path) -> tuple[int, int] | None:
    """(members, size of the member list) a zip declares in its end record, read before the
    zipfile module loads every member into memory. None when the record can't be found."""
    try:
        with open(path, "rb") as f:
            size = f.seek(0, os.SEEK_END)
            tail_len = min(size, 22 + 0xFFFF)
            f.seek(size - tail_len)
            tail = f.read(tail_len)
            at = tail.rfind(b"PK\x05\x06")
            if at < 0 or len(tail) - at < 22:
                return None
            entries, cd_size = struct.unpack("<HL", tail[at + 10:at + 16])
            if entries != 0xFFFF and cd_size != 0xFFFFFFFF:
                return entries, cd_size
            # Zip64: the real numbers are in another record, found through the locator just before.
            loc = tail[at - 20:at] if at >= 20 else b""
            if loc[:4] != b"PK\x06\x07":
                return None
            (offset,) = struct.unpack("<Q", loc[8:16])
            f.seek(offset)
            record = f.read(56)
            if record[:4] != b"PK\x06\x06":
                return None
            return struct.unpack("<QQ", record[32:48])
    except (OSError, struct.error):
        return None


def check_zip(path: Path, max_entries: int, error: Callable[[str], Exception]) -> None:
    """Refuse a zip that lists more than ``max_entries`` members, before opening it (each costs
    the zipfile module about half a kilobyte of memory). The zipfile module reads the member
    list by its size, not by the count, so a list bigger than ``max_entries`` entries with long
    names (200 bytes each) is refused too, whatever count the zip claims."""
    found = zip_entries(path)
    if found is None:
        return  # (not a zip, or damaged: opening it says so)
    entries, cd_size = found
    if entries > max_entries or cd_size > max_entries * 200:
        log.warning("refused %s: it lists %d files (at most %d)", printable(path.name), entries, max_entries)
        raise error(f"that file holds too many files ({entries:,}; at most {max_entries:,} can be unpacked)")


def free_bytes(path: Path) -> int | None:
    """Free space on the disk ``path`` is (or would be) on."""
    p = path
    while not p.exists() and p.parent != p:
        p = p.parent
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return None


def size_words(n: int) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{max(n, 0) / 1e6:.0f} MB"


def ensure_space(path: Path, needed: int, error: Callable[[str], Exception], what: str = "that") -> None:
    """Refuse to start writing ``needed`` bytes under ``path`` when the disk can't hold them and
    still keep :data:`DISK_RESERVE` free."""
    free = free_bytes(path)
    if free is not None and needed + DISK_RESERVE > free:
        log.warning("refused to unpack %s: it needs %s and the disk has %s free", what, size_words(needed),
                    size_words(free))
        raise error(f"there isn't enough free disk space for {what}: it needs {size_words(needed)} "
                    f"(and {size_words(DISK_RESERVE)} to spare), and the disk has {size_words(free)} free")


def open_new(base: Path, names: tuple[str, ...]) -> BinaryIO:
    """Open ``base/names...`` for writing, making its folders, without going through links: no
    link inside ``base`` (one already there, or one an archive made) can send the write
    elsewhere. Raises :class:`UnsafeName` when a link, or a file where a folder should be, is
    in the way."""
    folder = base
    for name in names[:-1]:
        folder = folder / name
        if is_link(folder):
            raise UnsafeName(f"{'/'.join(names)} would be written through a link")
        if folder.exists() and not folder.is_dir():
            raise UnsafeName(f"a file is where the folder {name!r} should be")
        folder.mkdir(exist_ok=True)
    target = folder / names[-1]
    if is_link(target):
        raise UnsafeName("it would replace a link")
    if target.is_dir():
        raise UnsafeName("a folder of the same name is already there")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    return os.fdopen(os.open(target, flags, 0o644), "wb")
