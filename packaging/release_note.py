"""The "Before you update" note of a version, from CHANGELOG.md, for the top of its release notes.

Craft Conductor's update prompt shows the first lines of the release notes (app.js releaseBlurb),
so a change people must know about before they update (one that stops something working) goes
under its version in the changelog as a line starting with ``**Before you update:**``. The
release workflow puts it first. Prints nothing when the version has none.

    python packaging/release_note.py 0.29.0
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
MARK = "**Before you update:**"


def note(version: str, text: str) -> str:
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if re.match(rf"## {re.escape(version)} \(", line)), None)
    if start is None:
        return ""
    out = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        if line.startswith(MARK) or line.startswith("- " + MARK):
            out.append("> " + line.removeprefix("- ").strip())
    return "\n>\n".join(out)


if __name__ == "__main__":
    print(note(sys.argv[1].removeprefix("v"), CHANGELOG.read_text(encoding="utf-8")))
