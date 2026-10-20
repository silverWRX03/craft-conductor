"""Classic and Modern in a real browser (optional, like test_ui_browser.py).

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> pytest tests/test_ui_styles.py

CRAFT_UI_SHOTS=<folder> also saves a picture of each style and theme to look at.
"""
import os
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not (os.environ.get("CRAFT_UI_NODE") and os.environ.get("CRAFT_UI_PLAYWRIGHT")),
                                reason="optional browser verification")


def test_classic_and_modern(hub_env):
    from craft_conductor import access
    hub, client = hub_env
    token, _ = hub.ui.users.invite("Morgan", {"alpha": access.PRESETS["manager"]}, time.time())  # (someone else on the same browser)
    hub.ui.users.accept(token, "morgan", "Morgan-Strong-Pass-3", time.time())
    result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_styles.cjs")), client.base],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    assert result.returncode == 0, result.stdout + result.stderr
