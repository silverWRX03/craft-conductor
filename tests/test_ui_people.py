"""Inviting someone in a real browser, and what they see once signed in (optional, like test_ui_browser.py).

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> pytest tests/test_ui_people.py
"""
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not (os.environ.get("CRAFT_UI_NODE") and os.environ.get("CRAFT_UI_PLAYWRIGHT")),
                                reason="optional browser verification")


def test_inviting_someone_and_what_they_see(hub_env, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="craft_conductor.web")
    hub, client = hub_env
    hub.ui.host = "0.0.0.0"   # (as if restarted with access from other devices on: links can be made)
    hub.save_share(hub.share_settings()["port"], "mc.example.com")
    import time
    from craft_conductor import access
    token, _ = hub.ui.users.invite("Morgan", {"alpha": access.PRESETS["manager"]}, time.time())   # (signs in with the form)
    hub.ui.users.accept(token, "morgan", "Morgan-Strong-Pass-3", time.time())
    result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_people.cjs")), client.base],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    people = hub.ui.users.list(0)
    assert [(p["name"], p["username"]) for p in people] == [("Morgan", "morgan"), ("Riley", "riley")]
    assert people[1]["grants"] == {"alpha": ["players.moderate", "status.view"]}
    # The pages they opened asked only for what they may see: nothing was refused but the two asked on purpose
    # (Morgan, a Manager, opened every page in the menu).
    refused = sorted(r.getMessage() for r in caplog.records if r.getMessage().startswith("refused "))
    assert refused == ["refused GET /api/console on alpha for Riley", "refused GET /api/status on main for Riley"], refused
