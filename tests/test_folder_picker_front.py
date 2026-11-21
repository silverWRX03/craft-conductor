"""Browse…'s folder picker opens in front of the browser on Windows (#304), on a real desktop
(optional: it opens a window for a moment, and needs a signed-in Windows session):

    CRAFT_UI_DESKTOP=1 pytest tests/test_folder_picker_front.py

Craft Conductor runs in the background (the browser is in front), and Windows doesn't let a program
there take the foreground: the picker opened behind the browser. This test opens it the same way,
from a program that isn't in front, and checks it is the window in front; then closes it.
"""
import os
import threading
import time

import pytest

from craft_conductor import folderpicker

pytestmark = pytest.mark.skipif(os.name != "nt" or not os.environ.get("CRAFT_UI_DESKTOP"),
                                reason="optional Windows desktop verification")


def test_the_picker_is_the_window_in_front():
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    title = "Craft Conductor test 1048"
    done = {}
    picking = threading.Thread(target=lambda: done.setdefault("path", folderpicker.pick("", title)), daemon=True)
    picking.start()
    dialog, in_front = None, False
    deadline = time.monotonic() + 30
    try:
        while time.monotonic() < deadline and not in_front:
            time.sleep(0.2)
            dialog = dialog or user32.FindWindowW("#32770", "Browse For Folder")
            in_front = bool(dialog) and user32.GetForegroundWindow() == dialog
    finally:
        if dialog:
            user32.PostMessageW(dialog, 0x0010, 0, 0)  # (WM_CLOSE: closed without a folder)
        picking.join(15)
    assert dialog, "the picker didn't open"
    assert in_front, "the picker opened behind the window in front"
    assert done.get("path") is None
