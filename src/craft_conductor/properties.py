"""Reading and editing ``server.properties`` without disturbing lines craft-conductor doesn't touch.

It's a Java properties file. Minecraft reads it as UTF-8 (or, failing that, ISO-8859-1, which is
how older versions kept it) and understands escapes such as ``\\u00e9``. The file is read the same
way here, never in this computer's own text encoding (Windows': mostly not UTF-8), and the values
craft-conductor writes are escaped, so a server name in any language reads back as it was typed in
every Minecraft version.
"""

from __future__ import annotations

import os
import re
from pathlib import Path


_cache: dict[str, tuple[tuple, dict[str, str]]] = {}  # path -> (its stat when read, what it said)
_ESCAPES = {"t": "\t", "n": "\n", "r": "\r", "f": "\f"}
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_FORMATTING = re.compile(r"§.?", re.DOTALL)  # Minecraft's colour and style codes (§a, §l, ...)


def server_name(props: dict[str, str], default: str = "") -> str:
    """A server's name as Craft Conductor shows and sends it (the server list, invites, friends'
    launchers): its motd as one line of plain text. A two-line motd (``\\n`` in the file) shows as
    one, colour codes (``§a``) are left out, and no other control character gets through;
    ``default`` when there's nothing left."""
    return " ".join(_CONTROL.sub(" ", _FORMATTING.sub("", props.get("motd", ""))).split()) or default


def _read_lines(path: Path) -> tuple[list[str], str, str]:
    """The file's lines, and the encoding and line ending it has (to write it back with)."""
    raw = path.read_bytes()
    try:
        text, encoding = raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        text, encoding = raw.decode("latin-1"), "latin-1"
    newline = "\r\n" if "\r\n" in text else "\n" if "\n" in text else os.linesep
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines, encoding, newline


def _unescape(value: str) -> str:
    """A value as Java reads it: ``\\t``, ``\\n``, ``\\uXXXX``..., and ``\\`` before anything else is dropped."""
    if "\\" not in value:
        return value
    out, i = [], 0
    while i < len(value):
        c = value[i]
        i += 1
        if c != "\\" or i == len(value):
            out.append(c)
            continue
        c = value[i]
        i += 1
        if c == "u" and len(value) >= i + 4:
            try:
                out.append(chr(int(value[i:i + 4], 16)))
                i += 4
                continue
            except ValueError:
                pass
        out.append(_ESCAPES.get(c, c))
    # (characters past ￿ arrive as two escapes, a surrogate pair)
    return "".join(out).encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")


def _escape(value: str) -> str:
    """A value as Java's properties format writes it: plain ASCII, so the file reads the same everywhere."""
    out = []
    for c in value:
        if c == "\\":
            out.append("\\\\")
        elif c in "\t\n\r\f":
            out.append("\\" + {"\t": "t", "\n": "n", "\r": "r", "\f": "f"}[c])
        elif " " <= c <= "~":
            out.append(c)
        else:
            units = c.encode("utf-16-be")  # (one or two UTF-16 units: an emoji is two)
            out += [f"\\u{int.from_bytes(units[i:i + 2], 'big'):04X}" for i in range(0, len(units), 2)]
    if out and out[0] == " ":
        out[0] = "\\ "  # (Java drops spaces at the start of a value)
    return "".join(out)


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
    lines, _, _ = _read_lines(path)
    props = {}
    for line in lines:
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            props[k.strip()] = _unescape(v.strip())
    if len(_cache) > 256:  # (one per server folder: this only happens with many copies and tests)
        _cache.clear()
    _cache[str(path)] = (stamp, props)
    return dict(props)


def write_properties(path: Path, updates: dict[str, str]) -> None:
    """Set keys in ``server.properties``. Minecraft fills in every other default on first start."""
    lines, encoding, newline = _read_lines(path) if path.exists() else ([], "utf-8", os.linesep)
    remaining = {k: _escape(str(v)) for k, v in updates.items()}
    for i, line in enumerate(lines):
        if line and not line.startswith("#") and "=" in line:
            key = line.partition("=")[0].strip()
            if key in remaining:
                lines[i] = f"{key}={remaining.pop(key)}"
    lines += [f"{k}={v}" for k, v in remaining.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    # Replace the file in one step, so nothing ever reads it half-written.
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(newline.join(lines) + newline, encoding=encoding, newline="")  # (the file's own line endings)
    os.replace(tmp, path)
