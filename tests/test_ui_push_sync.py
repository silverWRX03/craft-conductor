"""A device's notifications follow whoever is signed in, in a real browser (optional, like test_ui_browser.py):
a subscription this Craft Conductor doesn't know (#309) or that is the person's before (#313) is turned on again
by itself; Sign out takes it away. The browser's push service is a stand-in (headless browsers have none).

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> pytest tests/test_ui_push_sync.py
"""
import os
import subprocess
import time
from pathlib import Path

import pytest

from test_push import FCM, phone

pytestmark = pytest.mark.skipif(not (os.environ.get("CRAFT_UI_NODE") and os.environ.get("CRAFT_UI_PLAYWRIGHT")),
                                reason="optional browser verification")


def test_the_device_follows_who_is_signed_in(hub_env):
    hub, client = hub_env
    hub.ui.host = "0.0.0.0"   # (people can be invited)
    token, _ = hub.ui.users.invite("Sam", {"alpha": ["status.view"]}, time.time())
    hub.ui.users.accept(token, "sam", "Sam-Strong-Pass-4", time.time())
    _, key, auth = phone()
    # The phone had notifications on as Sam (#313).
    hub.push.subscribe(FCM, key, auth, "Phone", who=hub.ui.users.list(0)[0] and f"user:{hub.ui.users.list(0)[0]['id']}")
    assert [d["who"] for d in hub.push.subscriptions()] != ["owner"]
    result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_push_sync.cjs")), client.base,
                             FCM, key, auth], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    # (after the page signed in as the owner, turned it on for them, and signed out again)
    assert hub.push.subscriptions() == []
    assert "turned on: owner" in result.stdout, result.stdout
