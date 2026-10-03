"""Optional real-browser regressions and documentation captures against the test hub.

Set CRAFT_UI_NODE and CRAFT_UI_PLAYWRIGHT to run; CRAFT_UI_SCREENSHOTS saves captures.
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
