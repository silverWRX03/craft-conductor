"""Reading an mcsm invite from the clipboard, so friends can copy it and just open mcsm.

The clipboard's text is only looked at here, on this computer, for something that is an
mcsm invite; nothing else is kept or sent anywhere.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

INVITE = re.compile(r"mcsm-[A-Za-z0-9_-]{40,400}|https://\S+/join/[A-Za-z0-9_-]{16,64}#[A-Za-z0-9_-]{43}")
MAX_TEXT = 100_000


def _windows() -> str:
    import ctypes
    from ctypes import wintypes
    user32, kernel32 = ctypes.WinDLL("user32"), ctypes.WinDLL("kernel32")
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
    if not user32.OpenClipboard(None):
        return ""
    try:
        handle = user32.GetClipboardData(13)  # CF_UNICODETEXT
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)[:MAX_TEXT]
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def read_text() -> str:
    """The clipboard's text, or "" if there's none or it can't be read."""
    try:
        if os.name == "nt":
            return _windows()
        if sys.platform == "darwin":
            commands = [["pbpaste"]]
        else:
            commands = [["wl-paste", "--no-newline"], ["xclip", "-o", "-selection", "clipboard"],
                        ["xsel", "--clipboard", "--output"]]
        for cmd in commands:
            if shutil.which(cmd[0]):
                out = subprocess.run(cmd, capture_output=True, timeout=3)
                if out.returncode == 0:
                    return out.stdout[:MAX_TEXT].decode("utf-8", "replace")
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
        pass
    return ""


def find_invite(text: str):
    """The first valid mcsm invite in some text (e.g. a copied Discord message), or None."""
    from .join import JoinError, parse_invite
    for m in INVITE.finditer(text or ""):
        try:
            return parse_invite(m.group(0))
        except JoinError:
            continue
    return None


def invite() -> object | None:
    """An mcsm invite on the clipboard, if there is one."""
    return find_invite(read_text())
