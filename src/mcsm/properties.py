"""Reading and editing ``server.properties`` without disturbing lines mcsm doesn't touch."""

from __future__ import annotations

import os
from pathlib import Path


_cache: dict[str, tuple[tuple, dict[str, str]]] = {}  # path -> (its stat when read, what it said)


def read_properties(path: Path) -> dict[str, str]:
    """The file's keys and values (a copy: change it freely). Read again only when the file
    changes: pages ask for every server's settings every few seconds."""
    try:
        st = path.stat()
    except OSError:
        return {}
    stamp = (st.st_mtime_ns, st.st_size, st.st_ino)
    cached = _cache.get(str(path))
    if cached and cached[0] == stamp:
        return dict(cached[1])
    props = {}
    for line in path.read_text(errors="replace").splitlines():
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            props[k.strip()] = v.strip()
    if len(_cache) > 256:  # (one per server folder: this only happens with many copies and tests)
        _cache.clear()
    _cache[str(path)] = (stamp, props)
    return dict(props)


def write_properties(path: Path, updates: dict[str, str]) -> None:
    """Set keys in ``server.properties``. Minecraft fills in every other default on first start."""
    lines = path.read_text(errors="replace").splitlines() if path.exists() else []
    remaining = dict(updates)
    for i, line in enumerate(lines):
        if line and not line.startswith("#") and "=" in line:
            key = line.partition("=")[0].strip()
            if key in remaining:
                lines[i] = f"{key}={remaining.pop(key)}"
    lines += [f"{k}={v}" for k, v in remaining.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    # Replace the file in one step, so nothing ever reads it half-written.
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text("\n".join(lines) + "\n")
    os.replace(tmp, path)
