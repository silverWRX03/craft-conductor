"""Start, Stop and Restart in a real browser (optional, like test_ui_browser.py).

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> pytest tests/test_ui_power_buttons.py

A double-click on each counts once: one request, no "busy: start is running" error beside the
result, and Stop asks its question once.
"""
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not (os.environ.get("CRAFT_UI_NODE") and os.environ.get("CRAFT_UI_PLAYWRIGHT")),
                                reason="optional browser verification")


def test_power_buttons_count_once(hub_env):
    hub, client = hub_env
    result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_power_buttons.cjs")), client.base],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
