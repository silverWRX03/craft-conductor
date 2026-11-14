"""Browse…: the computer's own folder picker, for the folder browser (#229).

A web page never learns a real path from the browser, so the page can't open File Explorer itself.
Craft Conductor opens the picker on the computer it runs on and hands the chosen path back to the page,
which checks it as it checks a typed one. That only helps someone at that computer: the page offers it
only in a browser there (web.LOCAL_ONLY refuses it from anywhere else).

Standard library only: Windows' folder dialog through PowerShell, macOS's ``choose folder`` through
osascript, and zenity or kdialog on Linux when there's a screen. The title and the folder it opens on
reach the picker as environment variables, never as part of a command or script.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading

from .desktop import NO_WINDOW, child_env

TIMEOUT = 15 * 60  # a picker nobody answers is closed after this long
_busy = threading.Lock()  # one picker at a time

_WINDOWS = r"""
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
$f = New-Object System.Windows.Forms.FolderBrowserDialog
$f.Description = $env:CC_PICK_TITLE
$f.ShowNewFolderButton = $true
if ($env:CC_PICK_START -and (Test-Path -LiteralPath $env:CC_PICK_START -PathType Container)) { $f.SelectedPath = $env:CC_PICK_START }
$owner = New-Object System.Windows.Forms.Form -Property @{ TopMost = $true; ShowInTaskbar = $false; Opacity = 0 }
$owner.Show(); $owner.Activate()
$r = $f.ShowDialog($owner)
$owner.Close()
if ($r -eq [System.Windows.Forms.DialogResult]::OK) {
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  [Console]::Out.Write($f.SelectedPath)
}
"""
_MAC = ('set t to system attribute "CC_PICK_TITLE"\n'
        'set s to system attribute "CC_PICK_START"\n'
        'tell me to activate\n'
        'if s is "" then\n  set f to choose folder with prompt t\n'
        'else\n  set f to choose folder with prompt t default location (POSIX file s)\nend if\n'
        'return POSIX path of f')


class PickerError(Exception):
    pass


def _linux_tool() -> str | None:
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return None  # (no screen: a service, SSH)
    return next((t for t in ("zenity", "kdialog") if shutil.which(t)), None)


def available() -> bool:
    """Whether this computer has a folder picker Craft Conductor can open."""
    if os.name == "nt":
        return bool(shutil.which("powershell"))
    if sys.platform == "darwin":
        return bool(shutil.which("osascript"))
    return _linux_tool() is not None


def _command(start: str) -> list[str]:
    if os.name == "nt":
        return [shutil.which("powershell") or "powershell", "-NoProfile", "-NonInteractive", "-STA",
                "-ExecutionPolicy", "Bypass", "-Command", _WINDOWS]
    if sys.platform == "darwin":
        return ["osascript", "-e", _MAC]
    tool = _linux_tool()
    if tool == "zenity":  # (the title is the one fixed string; the folder it opens on goes in as a value)
        return ["zenity", "--file-selection", "--directory", "--title=Choose a folder",
                *([f"--filename={start.rstrip('/')}/"] if start else [])]
    if tool == "kdialog":
        return ["kdialog", "--getexistingdirectory", start or os.path.expanduser("~"), "--title", "Choose a folder"]
    raise PickerError("this computer has no folder picker Craft Conductor can open: type the folder's path instead")


def pick(start: str = "", title: str = "Choose a folder") -> str | None:
    """Open the picker on this computer's screen and wait for it: the folder chosen, or None if it
    was closed without one. Raises PickerError when one is open already or it can't be opened."""
    if not _busy.acquire(blocking=False):
        raise PickerError("a folder picker is open on this computer already: choose there, or close it")
    try:
        start = start if start and os.path.isdir(start) else ""
        env = {**child_env(), "CC_PICK_TITLE": " ".join(str(title).split())[:200], "CC_PICK_START": start}
        try:
            out = subprocess.run(_command(start), capture_output=True, timeout=TIMEOUT, env=env, **NO_WINDOW)
        except subprocess.TimeoutExpired:
            return None
        except OSError as e:
            raise PickerError(f"the folder picker couldn't be opened ({e}): type the folder's path instead") from e
        path = out.stdout.decode("utf-8", "replace").strip()
        if out.returncode != 0 or not path:
            return None  # (closed with Cancel)
        return path.rstrip("/\\") if len(path) > 3 and path.rstrip("/\\") else path
    finally:
        _busy.release()
