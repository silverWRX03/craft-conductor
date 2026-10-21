"""Where files are kept, in a real browser (optional, like test_ui_browser.py): the first-use page
after the password, Craft Conductor settings → Folders moving the servers, and Import a server…'s
list of exports.

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> pytest tests/test_ui_locations.py
"""
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not (os.environ.get("CRAFT_UI_NODE") and os.environ.get("CRAFT_UI_PLAYWRIGHT")),
                                reason="optional browser verification")


def test_choosing_where_files_are_kept(hub_env, tmp_path):
    hub, client = hub_env
    hub._save_locations(hub.locations(), chosen=False)  # (a new install: the page asks)
    elsewhere = tmp_path / "Elsewhere"
    elsewhere.mkdir()
    result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_locations.cjs")), client.base,
                             str(hub.home), str(elsewhere)], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    places = hub.locations()
    assert places["chosen"] and places["exports"] == Path(os.path.realpath(elsewhere / "Exports here"))
    assert places["servers"] == Path(os.path.realpath(elsewhere / "Servers"))
    assert (places["servers"] / "alpha" / "craft-conductor.toml").exists()


def test_a_move_put_back_at_the_start_is_said_once(hub_env, monkeypatch):
    """A move cut off by a stop, put back at the next start: Craft Conductor settings → Folders says
    so once, not at every visit (#141)."""
    from craft_conductor import locations as locmod
    hub, client = hub_env
    monkeypatch.setattr(locmod, "recover", lambda state_dir, put_back: "moving the servers was stopped halfway: "
                                                                       "everything was put back in X")
    hub.recover_move()
    assert hub.moving()["recovered"] and hub.moving()["ok"] is False
    result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_move_put_back.cjs")), client.base],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
