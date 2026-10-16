"""Old firewall rules in Check my setup, and every rule in Craft Conductor settings, in a real browser (optional,
like test_ui_browser.py).

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> pytest tests/test_ui_firewall_cleanup.py
"""
import os
import subprocess
from pathlib import Path

import pytest

from craft_conductor import firewall
from craft_conductor.properties import write_properties

pytestmark = pytest.mark.skipif(not (os.environ.get("CRAFT_UI_NODE") and os.environ.get("CRAFT_UI_PLAYWRIGHT")),
                                reason="optional browser verification")


def test_old_rules_are_offered_above_the_panel(hub_env, monkeypatch):
    hub, client = hub_env
    write_properties(hub.get("alpha").m.server_dir / "server.properties", {"server-port": "25599"})

    def rule(port, name):
        return {"action": 2, "profile": 0, "program": "Any", "protocol": "TCP", "ports": [str(port)], "package": "", "service": "Any",
                "group": "Craft Conductor", "name": name}
    state = {"profiles": [], "networks": [], "rules": [rule(25599, "Craft Conductor: Alpha (TCP 25599)"),
                                                       rule(25611, "Craft Conductor: Old (TCP 25611)")]}
    removed = []
    monkeypatch.setattr(firewall, "available", lambda: True)
    monkeypatch.setattr(firewall, "read", lambda timeout=30, fresh=False: state)
    monkeypatch.setattr(firewall, "remove", lambda names, timeout=300: removed.append(names))
    result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_firewall_cleanup.cjs")), client.base],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert removed == [["Craft Conductor: Old (TCP 25611)"]]
