"""Someone invited with Manage mods, while a server's setup waits for a mod downloaded by hand, in a real
browser (optional, like test_ui_browser.py): they reach the drop box (#334).

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> pytest tests/test_ui_invited_hand_downloads.py
"""
import os
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not (os.environ.get("CRAFT_UI_NODE") and os.environ.get("CRAFT_UI_PLAYWRIGHT")),
                                reason="optional browser verification")


def test_manage_mods_reaches_the_drop_box_while_setup_waits(hub_env, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="craft_conductor.web")
    hub, client = hub_env
    hub.ui.host = "0.0.0.0"   # (as if restarted with access from other devices on: people can be invited)
    d = hub.get("main")   # (never set up: its setup is pending)
    assert d.setup_pending
    # Setup waits for a mod whose author doesn't let other apps download it.
    d.job = {"name": "set up server", "started": time.time() - 30, "can_stop": False}
    d.last_check = {"checked_at": time.time(), "installed": None, "latest": "1.21.1", "target": "1.21.1", "fingerprint": None,
                    "loader_version": None, "up_to_date": False, "changes": [], "dropped": [], "blocked": [], "manual": [{"name": "Player Animation Library", "filename": "player-animation-lib-fabric-1.2.8.jar",
                                "url": "https://www.curseforge.com/minecraft/mc-mods/playeranimator/files/1", "sha1": "a" * 40}]}
    d.waiting_for_manual = True
    token, _ = hub.ui.users.invite("Sam", {"main": ["status.view", "mods.manage"]}, time.time())
    hub.ui.users.accept(token, "sam", "Sam-Strong-Pass-4", time.time())
    try:
        result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_invited_hand_downloads.cjs")),
                                 client.base], capture_output=True, text=True, timeout=300)
    finally:
        d.job, d.waiting_for_manual = None, False
    assert result.returncode == 0, result.stdout + result.stderr
    # The page asked only for what Sam may have: nothing about the setup form (the owner's choices).
    refused = sorted(r.getMessage() for r in caplog.records if r.getMessage().startswith("refused ") and "Sam" in r.getMessage())
    assert refused == [], refused
