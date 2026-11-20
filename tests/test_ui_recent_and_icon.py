"""Recent servers in the left panel, the Server icon card and the Discord webhook help link, in a real
browser (optional, like test_ui_browser.py).

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> pytest tests/test_ui_recent_and_icon.py
"""
import os
import struct
import subprocess
from pathlib import Path

import pytest

from test_server_icon import png

pytestmark = pytest.mark.skipif(not (os.environ.get("CRAFT_UI_NODE") and os.environ.get("CRAFT_UI_PLAYWRIGHT")),
                                reason="optional browser verification")


def test_recent_servers_and_the_icon_card(hub_env, http, tmp_path):
    hub, client = hub_env
    from craft_conductor import config as configmod, setup as setupmod
    from test_manager import manager, update
    from test_web import wait_for
    beta = hub.home / "servers" / "beta"
    setupmod.configure(beta, setupmod.SetupSpec.from_dict({"loader": "fabric", "minecraft": "1.21.1",
                                                           "motd": "Beta", "accept_eula": True}))
    assert update(manager(configmod.load(beta), http, ["1.21.1"])).ok
    wait_for(lambda: hub.get("beta") is not None, timeout=30)
    hub.last_started().update(alpha=100.0, beta=200.0)  # (beta ran last)
    picture = tmp_path / "wide.png"
    picture.write_bytes(png(100, 50))
    result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_recent_and_icon.cjs")),
                             client.base, str(picture)], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    saved = (hub.get("alpha").m.server_dir / "server-icon.png").read_bytes()
    assert saved.startswith(b"\x89PNG") and struct.unpack(">II", saved[16:24]) == (64, 64)
