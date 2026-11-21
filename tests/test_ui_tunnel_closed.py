"""The Cloudflare tunnel that closed by itself after its hours, in a real browser (optional, like test_ui_browser.py):
the Away from home card says when it closed (#323).

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> pytest tests/test_ui_tunnel_closed.py
"""
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from craft_conductor import cloudflare

from test_remote import STRONG

pytestmark = pytest.mark.skipif(not (os.environ.get("CRAFT_UI_NODE") and os.environ.get("CRAFT_UI_PLAYWRIGHT")),
                                reason="optional browser verification")


def test_the_card_says_the_tunnel_closed_after_its_hours(hub_env, monkeypatch):
    hub, client = hub_env
    tools = hub.ui.doors.tools()   # (cloudflared, as if downloaded and checked)
    cloudflare.program_path(tools).write_bytes(b"cloudflared")
    (tools / cloudflare.STATE).write_text(json.dumps({"version": "2026.10.1", "sha256": cloudflare._sha256(cloudflare.program_path(tools))}))
    monkeypatch.setattr(cloudflare, "_check", lambda path, check=None: None)
    closed = time.time() - 60
    hub.ui.doors.quick_closed = closed
    shown = time.strftime(":%M", time.localtime(closed))  # (the browser's own 12- or 24-hour clock)
    result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_tunnel_closed.cjs")), client.base, STRONG],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    text = result.stdout.strip().splitlines()[-1]
    assert f"after {cloudflare.HOURS} hours: the control panel is off the internet again." in text, text
    assert text.startswith("Closed at ") and shown in text, (shown, text)
