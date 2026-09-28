"""What went wrong, in plain words, with the fixes mcsm can do: when a server crashes or won't
start, the Dashboard says why and offers buttons (remove the mod to blame, add the one that's
missing, give it more memory, pick the right Java, use a free port...).

The causes that aren't a mod's fault are recognised by the messages Java and Minecraft print;
the mods to blame come from :mod:`diagnose`. Nothing is changed until a button is pressed.
"""

from __future__ import annotations

import re
import time

from .diagnose import diagnose

# (pattern, id, title, words, action) for problems that aren't one mod's fault
CAUSES = [
    (re.compile(r"You need to agree to the EULA", re.I), "eula", "The Minecraft EULA hasn't been accepted",
     "Minecraft won't start a server until its EULA (Mojang's terms) is accepted.", {"kind": "eula", "label": "Read and accept the EULA"}),
    (re.compile(r"OutOfMemoryError|Java heap space|GC overhead limit exceeded", re.I), "memory", "The server ran out of memory",
     "Minecraft used all the memory it was given and stopped. More mods, players and loaded chunks need more.",
     {"kind": "memory-up", "label": "Give it more memory"}),
    (re.compile(r"FAILED TO BIND TO PORT|Address already in use|BindException", re.I), "port", "Another program is using the server's port",
     "Only one program can use a port. Another server, or another copy of this one, may still be running.",
     {"kind": "port", "label": "Use a free port"}),
    (re.compile(r"UnsupportedClassVersionError|compiled by a more recent version of the Java Runtime|requires (?:at least )?Java \d+", re.I),
     "java", "The server needs a different Java", "The Minecraft version (or a mod) needs a newer Java than the one used.",
     {"kind": "java-auto", "label": "Let Craft Conductor pick the Java version"}),
    (re.compile(r"Failed to load level|Couldn't load (?:level|chunk)|Exception reading .*level\.dat|Chunk file at .* is in the wrong location|"
                r"Failed to read level\.dat|DataFixer.*failed", re.I), "world", "The world looks damaged",
     "Minecraft couldn't read part of the world. Restoring the last backup made before this is the safest fix.",
     {"kind": "backups", "label": "Open Backups"}),
]
# A mod that another mod needs is missing.
MISSING = [
    re.compile(r"requires [^\n]*?of (?:mod )?'([^']+)' \(([\w.-]+)\)[^\n]*?(?:missing|isn't installed|is not installed)", re.I),
    re.compile(r"Mod ID: '([\w.-]+)', Requested by: '[\w.-]+', Expected range: '[^']*', Actual version: '\[MISSING\]'"),
]
SKIP = {"minecraft", "java", "fabricloader", "fabric", "forge", "neoforge", "quilt_loader"}


def _line(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return text[start:end if end != -1 else len(text)].strip()[:300]


def explain(lines: list[str], server_dir=None, mods=(), since: float | None = None, kind: str = "crash") -> dict | None:
    """What went wrong, with buttons; None when nothing is recognised."""
    text = "\n".join(lines)
    now = time.time()
    base = {"kind": kind, "time": now}
    for pattern, cause, title, words, action in CAUSES:
        m = pattern.search(text)
        if m:
            return {**base, "cause": cause, "title": title, "words": words, "evidence": _line(text, m.start()), "actions": [action]}
    for pattern in MISSING:
        m = pattern.search(text)
        if m:
            name, mod_id = (m.group(1), m.group(2)) if pattern.groups == 2 else (m.group(1), m.group(1))
            if mod_id.lower() in SKIP:
                continue
            return {**base, "cause": "missing", "title": f"A mod needs {name}, which isn't installed",
                    "words": f"Add {name} (Craft Conductor looks for it on Modrinth), or remove the mod that needs it.",
                    "evidence": _line(text, m.start()),
                    "actions": [{"kind": "add-mod", "id": mod_id, "name": name, "label": f"Add {name}"}]}
    d = diagnose(lines, server_dir, mods, since=since)
    if d.suspects:
        by_file = {m.filename: m for m in mods}
        actions = []
        for s in d.suspects[:3]:
            managed = s.filename in by_file
            actions.append({"kind": "remove-mod" if managed else "disable-jar", "filename": s.filename, "name": s.name,
                            "label": f"Remove {s.name}" if managed else f"Switch {s.name} off"})
        names = ", ".join(s.name for s in d.suspects[:3])
        first = d.suspects[0]
        return {**base, "cause": "mod", "title": f"{names} stopped the server" if len(d.suspects) == 1 else f"These mods look to blame: {names}",
                "words": f"{first.name}: {first.reason}. Removing it (or switching it off) usually gets the server going; "
                         "check for an update of it later.",
                "evidence": first.evidence[:300], "actions": [a for a in actions if a["filename"]]}
    return None
