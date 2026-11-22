"""The Router card (Craft Conductor settings → Connections) in a real browser (optional, like test_ui_browser.py):
it only says the server is open to the internet once the router opened a port (#326).

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> pytest tests/test_ui_router.py
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

from craft_conductor.upnp import EXPOSURE_WARNING

pytestmark = pytest.mark.skipif(not (os.environ.get("CRAFT_UI_NODE") and os.environ.get("CRAFT_UI_PLAYWRIGHT")),
                                reason="optional browser verification")

PORT = {"protocol": "TCP", "port": 25565, "label": "Alpha (Minecraft)"}


def test_the_router_card_only_says_open_when_a_port_is_open(hub_env, monkeypatch):
    hub, client = hub_env
    states = {
        # UPnP off on the router: switched on here, but no router answered.
        "silent": {"enabled": True, "ports": [], "checked": 1, "router": "", "external_ip": "", "warning": "",
                   "error": "no router answered: UPnP is probably switched off on it", "exposure": EXPOSURE_WARNING},
        # The router answered but refused the port.
        "refused": {"enabled": True, "ports": [{**PORT, "ok": False, "error": "the router said no (718)"}], "checked": 1,
                    "router": "Router X", "external_ip": "", "warning": "", "error": "", "exposure": EXPOSURE_WARNING},
        # It worked.
        "open": {"enabled": True, "ports": [{**PORT, "ok": True, "error": ""}], "checked": 1, "router": "Router X",
                 "external_ip": "", "warning": "", "error": "", "exposure": EXPOSURE_WARNING},
    }
    monkeypatch.setattr(type(hub), "upnp_status", lambda self: states[os.environ.get("CRAFT_TEST_ROUTER", "silent")])
    shown = {}
    for name in states:
        monkeypatch.setenv("CRAFT_TEST_ROUTER", name)
        result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_router.cjs")), client.base],
                                capture_output=True, text=True, timeout=300)
        assert result.returncode == 0, result.stdout + result.stderr
        shown[name] = json.loads(result.stdout.strip().splitlines()[-1])
    for name in ("silent", "refused"):
        assert not shown[name]["open"], (name, shown[name])
        assert shown[name]["nothing"], (name, shown[name])
    assert "It didn't work" in shown["silent"]["text"]
    assert shown["open"]["open"] and not shown["open"]["nothing"], shown["open"]
