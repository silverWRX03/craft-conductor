"""The "Friends outside your home" chooser and the whitelist question, in a real browser (optional,
like test_ui_browser.py).

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> pytest tests/test_ui_reach.py
"""
import os
import subprocess
from pathlib import Path

import pytest

from craft_conductor import reach
from craft_conductor.properties import read_properties

pytestmark = pytest.mark.skipif(not (os.environ.get("CRAFT_UI_NODE") and os.environ.get("CRAFT_UI_PLAYWRIGHT")),
                                reason="optional browser verification")


def test_the_chooser_and_the_whitelist_question(hub_env, monkeypatch):
    hub, client = hub_env
    asked = []
    monkeypatch.setattr(hub, "playit_install", lambda: asked.append(1) or hub.playit_status())  # (never downloads here)
    result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_reach.cjs")), client.base],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    d = hub.get("alpha")
    port = int(read_properties(d.m.server_dir / "server.properties")["server-port"])
    assert d.m.config.reach_way == "forward" and reach.in_open_range(port)
    assert read_properties(d.m.server_dir / "server.properties")["white-list"] == "false"  # (turned off, after the question)
    assert asked == []  # nothing downloaded: the button was never pressed
