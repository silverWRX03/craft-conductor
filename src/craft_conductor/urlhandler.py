"""Open ``craft-conductor://join/<invite>`` links with this craft-conductor, so a friend who already has craft-conductor can
press "Open in craft-conductor" on an invite page and go straight to setting up their game.

Registered for the current user only (no administrator rights needed), each time a friend
joins with the standalone craft-conductor, so it follows the file if it's moved: on Windows in the
user's registry (HKCU\\Software\\Classes\\craft-conductor), on Linux as a desktop entry. macOS needs an
app bundle for this, which craft-conductor isn't; there the invite page copies the invite instead.

What a link carries is only ever used as an invite: `craft-conductor join` checks it strictly.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)
SCHEME = "craft-conductor"
DESKTOP_FILE = "craft-conductor-invite.desktop"


def register(exe: str | None = None) -> bool:
    """Make craft-conductor:// links open this craft-conductor (standalone builds only). Returns whether it did."""
    from . import selfupdate
    if exe is None:
        if not selfupdate.frozen():
            return False
        exe = sys.executable
    try:
        if os.name == "nt":
            return _windows(exe)
        if sys.platform.startswith("linux"):
            return _linux(exe)
    except OSError as e:
        log.debug("couldn't register craft-conductor:// links: %s", e)
    return False


def _windows(exe: str) -> bool:
    import winreg
    if '"' in exe or "\n" in exe:
        return False
    base = rf"Software\Classes\{SCHEME}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "URL:craft-conductor invite")
        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r"\shell\open\command") as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, f'"{exe}" join -- "%1"')  # "--": a link is only ever the invite
    return True


def _linux(exe: str) -> bool:
    if any(c in exe for c in '"\n\r%`$\\'):
        return False  # keep the desktop entry's Exec line simple and unambiguous
    folder = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "applications"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / DESKTOP_FILE).write_text(
        "[Desktop Entry]\nType=Application\nName=Craft Conductor (join a Minecraft server)\n"
        f'Exec="{exe}" join -- %u\nMimeType=x-scheme-handler/{SCHEME};\nNoDisplay=true\nTerminal=false\n', encoding="utf-8")
    if shutil.which("xdg-mime"):
        subprocess.run(["xdg-mime", "default", DESKTOP_FILE, f"x-scheme-handler/{SCHEME}"],
                       capture_output=True, timeout=10)
    return True
