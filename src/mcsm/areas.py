"""Backups you can trust, and undoing damage in one place.

* :func:`verify`: reads a whole backup (every file, so a damaged or cut-short archive shows),
  and checks it holds a world Minecraft can open (level.dat and region files). Results are
  kept next to the backups (``.checks.json``) so each backup is only read once.
* :func:`restore_area`: puts back the chunks in a rectangle from a backup, leaving the rest
  of the world as it is now: griefing or a bad explosion undone without losing everyone
  else's building since. Chunks are copied as they are in Minecraft's region files (the
  blocks, the entities and points of interest there); a chunk that didn't exist in the
  backup is removed, so Minecraft makes it again.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import struct
import tarfile
import time
import zlib
from pathlib import Path, PurePosixPath

log = logging.getLogger(__name__)

CHECKS = ".checks.json"
DIMENSIONS = {"overworld": "", "nether": "DIM-1", "end": "DIM1"}
PAPER_DIMENSION_FOLDERS = {"nether": "_nether", "end": "_the_end"}  # Paper keeps them in world_nether/DIM-1, ...
KINDS = ("region", "entities", "poi")
MAX_BLOCKS = 4096  # the widest area that can be put back at once (in blocks, each way)


class AreaError(ValueError):
    pass


# ------------------------------------------------------------------ checking
def verify(archive: Path, level: str = "world") -> dict:
    """{ok, files, regions, detail} for one backup. Reads all of it (a fast check can't tell
    that the end of a file was cut off)."""
    files = regions = 0
    level_dat = None
    try:
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar:
                if not member.isfile():
                    continue
                files += 1
                parts = PurePosixPath(member.name).parts
                is_level = parts[1:] == (level, "level.dat")
                f = tar.extractfile(member)
                data = b""
                while chunk := f.read(1 << 20):  # (reading it all is what checks it)
                    if is_level:
                        data += chunk
                if is_level:
                    level_dat = data
                if len(parts) >= 3 and parts[-2] == "region" and parts[-1].endswith(".mca"):
                    regions += 1
    except (tarfile.TarError, OSError, EOFError, zlib.error) as e:
        return {"ok": False, "files": files, "regions": regions, "detail": f"the backup is damaged: {e}"}
    if level_dat is None:
        return {"ok": True, "files": files, "regions": regions, "detail": "no world in it (the server hadn't made one yet)"}
    try:
        from . import nbt
        nbt.loads(gzip.decompress(level_dat))
    except Exception:
        return {"ok": False, "files": files, "regions": regions, "detail": "the world's level.dat can't be read"}
    return {"ok": True, "files": files, "regions": regions, "detail": f"{files} files, a world with {regions} region file(s)"}


def load_checks(backups_dir: Path) -> dict:
    try:
        data = json.loads((backups_dir / CHECKS).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def check(backups_dir: Path, name: str, level: str = "world") -> dict:
    """Verify one backup and remember the result (forgetting backups that are gone)."""
    result = {**verify(backups_dir / name, level), "checked": time.time()}
    checks = load_checks(backups_dir)
    checks[name] = result
    checks = {k: v for k, v in checks.items() if (backups_dir / k).is_file()}
    tmp = backups_dir / (CHECKS + ".tmp")
    tmp.write_text(json.dumps(checks, indent=1))
    os.replace(tmp, backups_dir / CHECKS)
    return result


# ------------------------------------------------------------ region files
def read_region(data: bytes) -> dict[int, tuple[bytes, int]]:
    """chunk index (0-1023) -> (its stored bytes: length, compression and data; its timestamp)."""
    out: dict[int, tuple[bytes, int]] = {}
    if len(data) < 8192:
        return out
    for i in range(1024):
        entry = struct.unpack(">I", data[i * 4:i * 4 + 4])[0]
        offset, sectors = entry >> 8, entry & 0xFF
        if not offset or not sectors or offset < 2:
            continue
        start = offset * 4096
        if start + 5 > len(data):
            continue
        length = struct.unpack(">I", data[start:start + 4])[0]
        if length < 1 or start + 4 + length > len(data):
            continue
        stamp = struct.unpack(">I", data[4096 + i * 4:4096 + i * 4 + 4])[0]
        out[i] = (data[start:start + 4 + length], stamp)
    return out


def write_region(chunks: dict[int, tuple[bytes, int]]) -> bytes:
    locations, stamps, body = bytearray(4096), bytearray(4096), bytearray()
    for i in sorted(chunks):
        blob, stamp = chunks[i]
        blob += b"\x00" * (-len(blob) % 4096)
        sectors = len(blob) // 4096
        if sectors > 255:  # (Minecraft keeps such chunks in a separate file; leave them out)
            continue
        offset = 2 + len(body) // 4096
        locations[i * 4:i * 4 + 4] = struct.pack(">I", (offset << 8) | sectors)
        stamps[i * 4:i * 4 + 4] = struct.pack(">I", stamp)
        body += blob
    return bytes(locations) + bytes(stamps) + bytes(body)


def dimension_dir(level: str, dimension: str, server_dir: Path | None = None) -> str:
    """The dimension's folder, relative to the server folder."""
    if dimension not in DIMENSIONS:
        raise AreaError("pick the Overworld, the Nether or the End")
    if not level or level in (".", "..") or any(c in level for c in '/\\:') or level.startswith("."):
        raise AreaError("the world's folder name (level-name) isn't a plain folder name")
    sub = DIMENSIONS[dimension]
    if sub and server_dir is not None and (server_dir / (level + PAPER_DIMENSION_FOLDERS[dimension])).is_dir():
        return f"{level}{PAPER_DIMENSION_FOLDERS[dimension]}/{sub}"
    return f"{level}/{sub}" if sub else level


def restore_area(archive: Path, server_dir: Path, level: str, dimension: str,
                 x1: int, z1: int, x2: int, z2: int) -> dict:
    """Put back the chunks covering blocks (x1, z1)-(x2, z2) from the backup. The server must
    be stopped. Returns {chunks, regions}."""
    if max(abs(x2 - x1), abs(z2 - z1)) >= MAX_BLOCKS:
        raise AreaError(f"that's a big area: put back at most {MAX_BLOCKS} × {MAX_BLOCKS} blocks at a time")
    cx1, cx2 = sorted((x1 >> 4, x2 >> 4))
    cz1, cz2 = sorted((z1 >> 4, z2 >> 4))
    folder = dimension_dir(level, dimension, server_dir)
    wanted: dict[str, set[int]] = {}  # region file name -> chunk indexes in it
    for cx in range(cx1, cx2 + 1):
        for cz in range(cz1, cz2 + 1):
            wanted.setdefault(f"r.{cx >> 5}.{cz >> 5}.mca", set()).add((cx & 31) + (cz & 31) * 32)
    members: dict[str, bytes] = {}
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            parts = PurePosixPath(member.name).parts
            if member.isfile() and len(parts) >= 3 and parts[0] == "server":
                rel = "/".join(parts[1:])
                kind_dir, name = "/".join(parts[1:-1]), parts[-1]
                if name in wanted and kind_dir in {f"{folder}/{k}" for k in KINDS}:
                    members[rel] = tar.extractfile(member).read()
    chunks = 0
    touched = 0
    for kind in KINDS:
        for name, indexes in wanted.items():
            rel = f"{folder}/{kind}/{name}"
            live_path = server_dir / rel
            old = members.get(rel, b"")
            if not old and not live_path.exists():
                continue
            live = read_region(live_path.read_bytes()) if live_path.exists() else {}
            then = read_region(old)
            for i in indexes:
                if i in then:
                    live[i] = then[i]
                else:
                    live.pop(i, None)
                if kind == "region":
                    chunks += 1
            live_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = live_path.with_name(live_path.name + ".tmp")
            tmp.write_bytes(write_region(live))
            os.replace(tmp, live_path)
            touched += 1
    if not touched:
        raise AreaError("there's nothing of that area in the backup or the world")
    log.info("put back %d chunk(s) of %s from %s", chunks, folder, archive.name)
    return {"chunks": chunks, "regions": touched}

