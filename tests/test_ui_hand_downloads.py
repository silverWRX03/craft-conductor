"""Mods downloaded by hand, found in Downloads and in a folder chosen on the setup page, in a real
browser (optional, like test_ui_browser.py).

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> pytest tests/test_ui_hand_downloads.py
"""
import hashlib
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not (os.environ.get("CRAFT_UI_NODE") and os.environ.get("CRAFT_UI_PLAYWRIGHT")),
                                reason="optional browser verification")


def test_the_setup_page_finds_mods_downloaded_by_hand(hub_env, tmp_path, monkeypatch):
    from craft_conductor import folders
    from craft_conductor.mods import curseforge as cf
    hub, client = hub_env
    monkeypatch.setenv("CRAFT_CONDUCTOR_CURSEFORGE_API_KEY", "test-key-not-real")
    jar = b"fancy jar"
    hub.http.json[f"{cf.API}/mods/22"] = {"data": {"id": 22, "name": "Fancy Client", "slug": "fancy-client"}}
    hub.http.json[f"{cf.API}/mods/22/files"] = {"data": [{
        "id": 2222, "fileName": "fancy-client-2.1.jar", "displayName": "Fancy 2.1", "gameVersions": ["Fabric", "1.21.1"],
        "releaseType": 1, "fileDate": "2026-01-01", "downloadUrl": None, "dependencies": [],
        "hashes": [{"value": hashlib.sha1(jar).hexdigest(), "algo": 1}]}]}
    downloads, saved = tmp_path / "Downloads", tmp_path / "Saved mods"
    downloads.mkdir()
    saved.mkdir()
    monkeypatch.setattr(folders, "downloads_dir", lambda *a, **k: downloads)
    result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_hand_downloads.cjs")), client.base,
                             str(downloads), str(saved)], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
