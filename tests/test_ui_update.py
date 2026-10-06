"""Craft Conductor's own update in a real browser (optional, like test_ui_browser.py).

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> pytest tests/test_ui_update.py

The release and the installer are stand-ins (nothing is downloaded or installed, and the control panel
doesn't really restart): what's checked is the page. The prompt closes at once on Update now, the update
screen follows the stages, the same tab reloads into the new version (never a second tab), Later keeps the
prompt away for the run while the red dots stay, Check for Craft Conductor updates offers it again, and a
failed update or restart is a clear message, not a loop.
"""
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from craft_conductor import selfupdate

from test_notice_update import release

pytestmark = pytest.mark.skipif(not (os.environ.get("CRAFT_UI_NODE") and os.environ.get("CRAFT_UI_PLAYWRIGHT")),
                                reason="optional browser verification")


def run_scenario(hub, client, monkeypatch, scenario, install):
    monkeypatch.setattr(selfupdate, "install_method", lambda release=None: (True, ""))
    monkeypatch.setattr(selfupdate, "install", install)
    release(hub.http, "v9.9.9")
    assert hub.check_self_update() == "Craft Conductor 9.9.9 is available"

    def apply_without_restarting():  # (the real one stops this control panel: it isn't restarted here)
        message = hub.updater.run_install(hub.http)
        return message
    hub.apply_self_update = apply_without_restarting
    result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_update.cjs")), client.base, scenario],
                            capture_output=True, text=True, timeout=180,
                            env={**os.environ, "NODE_PATH": os.environ.get("NODE_PATH", ""), "CRAFT_UI_VERSION": selfupdate.__version__})
    assert result.returncode == 0, result.stdout + result.stderr


def stages_install(calls):
    def install(rel, **kw):
        calls.append(rel.tag)
        progress = kw["progress"]
        progress("preparing", None, None)
        for done in (0, 40, 80, 100):
            progress("downloading", done, 100)
            time.sleep(0.2)
        progress("verifying", None, None)
        time.sleep(0.3)
        progress("installing", None, None)
        time.sleep(1.2)
        return f"installed Craft Conductor {rel.version}"
    return install


def test_later_and_the_red_dots(hub_env, monkeypatch):
    hub, client = hub_env
    run_scenario(hub, client, monkeypatch, "later", stages_install([]))
    assert hub.updater.snapshot()["deferred"] is True and hub.updater.snapshot()["phase"] == "available"


def test_update_now_and_the_same_tab_reload(hub_env, monkeypatch):
    hub, client = hub_env
    calls = []
    run_scenario(hub, client, monkeypatch, "update", stages_install(calls))
    assert calls == ["v9.9.9"]  # three presses, one update


def test_a_restart_that_never_answers(hub_env, monkeypatch):
    hub, client = hub_env
    calls = []
    run_scenario(hub, client, monkeypatch, "restart-timeout", stages_install(calls))
    assert calls == ["v9.9.9"]


def test_a_failed_update_is_a_message_not_a_loop(hub_env, monkeypatch):
    hub, client = hub_env
    calls = []

    def failing(rel, **kw):
        calls.append(rel.tag)
        kw["progress"]("downloading", 1, 2)
        raise selfupdate.VerificationError("the download of the update doesn't match the release's published checksum")
    run_scenario(hub, client, monkeypatch, "failure", failing)
    assert len(calls) == 3  # Update now, Update now (About & updates), Try again: each pressed by a person
    assert hub.updater.snapshot()["phase"] == "failed" and hub.updater.snapshot()["version"] == "9.9.9"


def test_other_tabs_are_asked_before_they_reload(hub_env, monkeypatch):
    """The update is done from one browser: another tab is told, then offered the new version, and only
    reloads when the person accepts."""
    hub, client = hub_env
    calls = []
    run_scenario(hub, client, monkeypatch, "other-tab", stages_install(calls))
    assert calls == ["v9.9.9"]


def test_an_update_that_was_reverted_reloads_the_tab_and_says_so(hub_env, monkeypatch):
    hub, client = hub_env
    calls = []
    run_scenario(hub, client, monkeypatch, "revert", stages_install(calls))
    assert calls == ["v9.9.9"]
