"""Keyboard focus survives live updates, in a real browser (optional, like test_ui_browser.py).

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> pytest tests/test_ui_focus.py
"""
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not (os.environ.get("CRAFT_UI_NODE") and os.environ.get("CRAFT_UI_PLAYWRIGHT")),
                                reason="optional browser verification")


def test_focus_stays_where_it_was(hub_env):
    hub, client = hub_env
    config = hub.get("alpha").m.server_dir / "config"  # (a config file for the editor)
    config.mkdir(exist_ok=True)
    (config / "sample.properties").write_text("enabled=true\nview-distance=12\n", encoding="utf-8")
    result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_focus.cjs")), client.base],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
