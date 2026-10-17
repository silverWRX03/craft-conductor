"""Reaching the control panel from outside, in a real browser (optional, like test_ui_browser.py):
the Tailscale / Cloudflare chooser, a safety rule switched off (and its alert), and the forgotten
password's code.

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> pytest tests/test_ui_outside.py
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

from craft_conductor import cloudflare, tailscale

from test_remote import STRONG
from test_tunnels import CF_NAME, TS_NAME, FakeCloudflared

pytestmark = pytest.mark.skipif(not (os.environ.get("CRAFT_UI_NODE") and os.environ.get("CRAFT_UI_PLAYWRIGHT")),
                                reason="optional browser verification")


def test_the_chooser_a_safety_rule_and_the_reset_code(hub_env, monkeypatch):
    hub, client = hub_env
    served = []
    state = {"serving": False}
    monkeypatch.setattr(tailscale, "exe", lambda: "tailscale")
    monkeypatch.setattr(tailscale, "status", lambda port: {"installed": True, "running": True, "name": TS_NAME,
                                                           "serving": state["serving"] and port == hub.ui.doors.port("tailscale"),
                                                           "funnel": False})

    def serve(port, funnel=False):
        served.append((port, funnel))
        state["serving"] = True
        return {"ok": True, "message": "", "enable_url": None}
    monkeypatch.setattr(tailscale, "serve", serve)
    tools = hub.ui.doors.tools()   # (cloudflared, as if downloaded and checked; it's a stand-in that never connects)
    cloudflare.program_path(tools).write_bytes(b"cloudflared")
    (tools / cloudflare.STATE).write_text(json.dumps({"version": "2026.10.1", "sha256": cloudflare._sha256(cloudflare.program_path(tools))}))
    monkeypatch.setattr(cloudflare, "_check", lambda path, check=None: None)
    real = cloudflare.QuickTunnel
    monkeypatch.setattr(cloudflare, "QuickTunnel", lambda *a, **kw: real(*a, **{**kw, "popen": FakeCloudflared}))
    downloads = []
    monkeypatch.setattr(cloudflare, "download", lambda *a, **kw: downloads.append(1))
    result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_outside.cjs")), client.base,
                             STRONG, CF_NAME, TS_NAME], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert served == [(hub.ui.doors.saved_tailscale().get("port") or served[0][0], False)]
    assert downloads == []   # (cloudflared was there already: nothing downloaded)
    assert hub.web.accept_risks == []   # (switched off, then back on)
    assert hub.ui.auth.default  # (the reset, with the code from the file)
