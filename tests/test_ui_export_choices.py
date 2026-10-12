"""Export server… and Import a server… in a real browser (optional, like test_ui_browser.py).

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> pytest tests/test_ui_export_choices.py

The export window offers the parts and the secrets this server has; a secret picked goes in
locked with a password shown once; the import asks for that password, again after a wrong one.
"""
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not (os.environ.get("CRAFT_UI_NODE") and os.environ.get("CRAFT_UI_PLAYWRIGHT")),
                                reason="optional browser verification")


def test_export_choices_and_the_import_password(hub_env):
    from craft_conductor import config as configmod
    hub, client = hub_env
    d = hub.get("alpha")
    (d.m.server_dir / "world").mkdir(exist_ok=True)
    (d.m.server_dir / "world" / "level.dat").write_bytes(b"level")
    configmod.set_value(d.m.config.path, "curseforge", "api_key", '"fake-curseforge-key-for-tests"')
    d.m.reload_config()
    result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_export_choices.cjs")), client.base],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    sid = result.stdout.split("IMPORTED ", 1)[1].split()[0]
    new = hub.get(sid).m
    assert new.config.curseforge_api_key == "fake-curseforge-key-for-tests"  # (it came along, locked)
    assert not (new.server_dir / "world").exists()  # (left out)
