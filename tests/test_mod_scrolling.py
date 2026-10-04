"""The mod browser's results keep coming as it scrolls (pager.js), in a real browser.

Optional, like test_ui_browser.py: set CRAFT_UI_NODE and CRAFT_UI_PLAYWRIGHT to run it.
Modrinth is made up here: 75 mods, where the whole second page (and one more) has no build for
the chosen Minecraft, and the last page starts one early, so one mod comes twice. The friend's
page (More mods, Shaders, Resource packs) is checked the same way.
"""
import os
import subprocess
from pathlib import Path

import pytest

TOTAL = 75
HIDDEN = {f"P{i:05d}" for i in range(20, 40)} | {"P00045"}


@pytest.mark.skipif(not os.environ.get("CRAFT_UI_NODE"), reason="optional browser verification")
def test_results_keep_coming_as_the_list_scrolls(hub_env, monkeypatch):
    from craft_conductor.mods.modrinth import API, ModrinthProvider
    hub, client = hub_env

    def search(params):
        start = int(params["offset"])
        first = start - 1 if start == 60 else start  # (a provider shifting results between pages)
        word = "Top" if params.get("index") == "downloads" else "Mod"
        prefix = "Q" if params.get("query") else "P"  # (words typed: other mods, all with builds)
        hits = [{"project_id": f"{prefix}{i:05d}", "slug": f"mod-{i}", "title": f"{word} {i}", "description": f"Made-up mod number {i}.",
                 "project_type": "mod", "downloads": 1000 - i, "server_side": "required", "client_side": "optional"}
                for i in range(first, min(TOTAL, first + int(params["limit"])))]
        return {"total_hits": TOTAL, "hits": hits}
    hub.http.json[f"{API}/search"] = search
    hub.http.json[f"{API}/project/P00001"] = {"id": "P00001", "slug": "mod-1", "title": "Mod 1", "description": "Made-up mod number 1.",
                                              "body": "The first one.", "project_type": "mod"}
    hub.http.json[f"{API}/project/P00001/version"] = []
    monkeypatch.setattr(ModrinthProvider, "best_channels",
                        lambda self, ids, loaders, mc, workers=6: {i: None if i in HIDDEN else "release" for i in ids})
    result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_scrolling.cjs")), client.base],
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(not os.environ.get("CRAFT_UI_NODE"), reason="optional browser verification")
def test_a_friends_list_keeps_coming_too(tmp_path, http):
    from craft_conductor import join, joinui
    from craft_conductor.mods.modrinth import API
    from test_friends import pack

    def search(params):
        start = int(params["offset"])
        word = "Top" if params.get("index") == "downloads" else "Pack"
        hits = [{"project_id": f"R{i:05d}", "slug": f"pack-{i}", "title": f"{word} {i}", "description": f"Made-up pack number {i}.",
                 "downloads": 1000 - i} for i in range(start, min(45, start + int(params["limit"])))]
        return {"total_hits": 45, "hits": hits}
    http.json[f"{API}/search"] = search
    http.json[f"{API}/tag/category"] = []
    invite = join.Invite("mc.example.com", 8766, "C" * 24, "F" * 43)
    http.json[invite.url + "/pack.json"] = pack(name="Weekend Server")
    (tmp_path / ".minecraft").mkdir()
    ui = joinui.JoinUI(invite, mc_dir=tmp_path / ".minecraft", http=http, prism_dir=tmp_path / "prism", out_dir=tmp_path)
    ui.open_browser = lambda url: None
    url = ui.start()
    try:
        result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_scrolling.cjs")), url, "friend"],
                                capture_output=True, text=True, timeout=180)
        assert result.returncode == 0, result.stdout + result.stderr
    finally:
        ui.stop()
