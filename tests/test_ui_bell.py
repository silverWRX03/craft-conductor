"""The bell in a real browser: messages land in it, the dot shows and clears, it works with the keyboard and
on a phone, and one person's messages never reach another (optional, like test_ui_browser.py).

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> pytest tests/test_ui_bell.py
"""
import os
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not (os.environ.get("CRAFT_UI_NODE") and os.environ.get("CRAFT_UI_PLAYWRIGHT")),
                                reason="optional browser verification")


def test_the_bell_keeps_each_persons_messages(hub_env):
    hub, client = hub_env
    from craft_conductor import access
    token, _ = hub.ui.users.invite("Morgan", {"alpha": access.PRESETS["manager"]}, time.time())
    person = hub.ui.users.accept(token, "morgan", "Morgan-Strong-Pass-3", time.time())
    result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_bell.cjs")), client.base, person["id"]],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
