"""Turning players' ping on and off from the Connected Players card, and the helper's row in Manage Mods,
in a real browser (optional, like test_ui_browser.py).

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> pytest tests/test_ui_player_ping.py
"""
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not (os.environ.get("CRAFT_UI_NODE") and os.environ.get("CRAFT_UI_PLAYWRIGHT")),
                                reason="optional browser verification")


def test_turning_ping_on_and_off(hub_env):
    hub, client = hub_env
    mods = hub.get("alpha").m.mods_dir     # (as if the server had been started with ping on)
    mods.mkdir(parents=True, exist_ok=True)
    (mods / "craft_conductor_ping-fabric-1.0.0.jar").write_bytes(b"fake")
    result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_player_ping.cjs")), client.base],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
