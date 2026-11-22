"""The mod browser on a phone, in a real browser (optional, like test_ui_browser.py): the results get most of
the screen, the Add selected bar stays at its bottom, the filters fold into Filters, and a mod's page opens
over the list (#331).

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> pytest tests/test_ui_phone_mod_browser.py
"""
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not (os.environ.get("CRAFT_UI_NODE") and os.environ.get("CRAFT_UI_PLAYWRIGHT")),
                                reason="optional browser verification")


def test_the_mod_browser_on_a_phone(hub_env, monkeypatch):
    from craft_conductor.mods.modrinth import API, ModrinthProvider
    hub, client = hub_env

    def search(params):
        start = int(params["offset"])
        hits = [{"project_id": f"P{i:05d}", "slug": f"mod-{i}", "title": f"Mod {i}", "description": f"Made-up mod number {i}.",
                 "project_type": "mod", "downloads": 1000 - i, "server_side": "required", "client_side": "optional"}
                for i in range(start, min(60, start + int(params["limit"])))]
        return {"total_hits": 60, "hits": hits}
    hub.http.json[f"{API}/search"] = search
    hub.http.json[f"{API}/tag/category"] = []
    hub.http.json[f"{API}/project/P00001"] = {"id": "P00001", "slug": "mod-1", "title": "Mod 1", "description": "Made-up mod number 1.",
                                              "body": "The first one.", "project_type": "mod"}
    hub.http.json[f"{API}/project/P00001/version"] = []
    monkeypatch.setattr(ModrinthProvider, "best_channels", lambda self, ids, loaders, mc, workers=6: {i: "release" for i in ids})
    result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_phone_mod_browser.cjs")), client.base],
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
