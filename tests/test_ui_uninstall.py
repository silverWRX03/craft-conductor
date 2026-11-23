"""Uninstall Craft Conductor… in a real browser (optional, like test_ui_browser.py).

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> pytest tests/test_ui_uninstall.py

The dialog lists the plan with every box off; ticking Delete my servers and worlds asks again, naming
how many; Uninstall (with the PIN typed again) shows the progress and then the report, which stays on
the page after Craft Conductor has closed. The test hub's runner only records: nothing is removed.
"""
import os
import subprocess
from pathlib import Path

import pytest

from craft_conductor import folders, uninstall

from test_cli_uninstall import FakeRunner

pytestmark = pytest.mark.skipif(not (os.environ.get("CRAFT_UI_NODE") and os.environ.get("CRAFT_UI_PLAYWRIGHT")),
                                reason="optional browser verification")


def test_the_dialog_the_second_confirmation_progress_and_the_report_that_stays(hub_env, tmp_path, monkeypatch):
    hub, client = hub_env
    user = tmp_path / "user"
    downloads = user / "Downloads"
    downloads.mkdir(parents=True)
    env = {"HOME": str(user), "USERPROFILE": str(user), "XDG_CONFIG_HOME": str(tmp_path / "xdg"),
           "XDG_DATA_HOME": str(user / ".local" / "share")}
    for name in ("HOME", "USERPROFILE", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, env[name])
    monkeypatch.delenv("CRAFT_CONDUCTOR_CONTAINER", raising=False)
    monkeypatch.setattr(folders, "downloads_dir", lambda *a, **k: downloads)
    monkeypatch.setattr(uninstall, "_frozen", lambda: False)
    monkeypatch.setattr(uninstall, "_prefix", lambda: str(tmp_path / "venv"))
    # alpha has a world; the unfinished server in the home folder hasn't.
    level = uninstall.game_dir(hub.get("alpha").m.config.root) / "world" / "level.dat"
    level.parent.mkdir(parents=True, exist_ok=True)
    level.write_bytes(b"level")
    runner = FakeRunner()
    hub.ui.hub_api.uninstall_runner = runner
    hub.ui.hub_api.uninstall_env = env
    result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_uninstall.cjs")), client.base],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert hub.stop_requested.is_set()
    assert runner.gone(hub.home / ".craft-conductor" / "hub.json") or runner.gone(hub.home / ".craft-conductor")
    assert (downloads / "Craft Conductor uninstall report.txt").is_file()
