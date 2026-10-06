"""Optional real-browser regressions against the test hub.

Set CRAFT_UI_NODE and CRAFT_UI_PLAYWRIGHT to run (CRAFT_UI_CHANNEL picks the browser: msedge on
Windows unless set). The pictures in the manual and Help come from test_screenshots.py.
The server and Minecraft data are fixtures, never a user's running server.
"""
import os
from pathlib import Path
import subprocess
import shutil
import time

import pytest


@pytest.mark.skipif(not os.environ.get("CRAFT_UI_NODE"), reason="optional browser verification")
def test_browser_regressions(hub_env, modrinth, monkeypatch):
    from craft_conductor import preview
    from test_preview import chunk, write_world
    hub, client = hub_env
    from craft_conductor import config as configmod
    from craft_conductor.config import ModSpec
    from test_manager import update
    m = hub.get("alpha").m
    configmod.append_mod(m.config.path, ModSpec("modrinth", "fabric-api"))
    m.reload_config()
    assert update(m).ok
    hub.get("alpha").m.mojang.set_releases(["1.21.1", "1.21.2"])
    modrinth.version("FAPI", "0.2", ["1.21.2"])
    now = time.time()
    for day in range(1, 8):
        hub.get("alpha").activity.joined("Alex", now - day * 86400)
        hub.get("alpha").activity.left("Alex", now - day * 86400 + 3600)
    # A small deterministic world exercises the actual PNG/tile HTTP endpoints.
    modrinth.project("CHUNKY", "chunky", "Chunky")
    modrinth.version("CHUNKY", "1.0", ["1.21.1"])
    # Release worldgen mod with a beta-only required library, as with TerraBlender.
    modrinth.project("LAND", "example-worldgen", "Example world generation")
    modrinth.version("LAND", "1.0", ["1.21.1"], deps=["LIB"])
    modrinth.project("LIB", "example-library", "Example required library")
    modrinth.version("LIB", "1.0", ["1.21.1"], version_type="beta")
    # A mod whose required library has no build for the newest Minecraft (B6): the version stays.
    modrinth.project("NEEDS", "needs-gone", "Needs Gone")
    modrinth.version("NEEDS", "1.0", ["1.21.1", "1.21.2"], deps=["GONE"])
    modrinth.project("GONE", "gone-library", "Gone Library")
    modrinth.version("GONE", "1.0", ["1.21.1"])
    from craft_conductor.mods.modrinth import API
    hub.http.json[f"{API}/search"] = {"total_hits": 1, "hits": [
        {"project_id": "LAND", "slug": "example-worldgen", "title": "Example world generation",
         "description": "Adds new terrain and biomes. Requires Example required library.",
         "project_type": "mod", "downloads": 100, "server_side": "required", "client_side": "required"}]}

    def generate(session, center, radius, report=None):
        if os.environ.get("CRAFT_UI_WORLD"):
            shutil.copytree(os.environ["CRAFT_UI_WORLD"], session.world, dirs_exist_ok=True)
            return
        write_world(session.world, {(x, z): chunk(x, z, block="minecraft:grass_block" if x < 0 else "minecraft:water")
                                   for x in range(-8, 8) for z in range(-8, 8)}, spawn=(8, 8))
    monkeypatch.setattr(preview.MapSession, "generate", generate)
    result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_browser.cjs")), client.base],
                            capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
