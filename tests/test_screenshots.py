"""The pictures in the user manual, the Help page, the wiki and the README: every page of the control
panel, with example servers made up here (like the rest of the tests, never anyone's real server).

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> \\
    CRAFT_UI_SCREENSHOTS=src/craft_conductor/webui/screenshots pytest tests/test_screenshots.py

It needs Pillow (pip install pillow) to keep the pictures small: they ship with Craft Conductor.
CRAFT_UI_CHANNEL picks the browser (msedge on Windows unless set). The map preview needs a real
world to draw: set CRAFT_UI_WORLD to a world folder to retake it, otherwise the one there is kept.
Run it twice when the Help page changes: Help shows the pictures taken the time before.
"""

import base64
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from example_hub import MODS, example_hub, grass_icon
from test_friends import pack
from test_web import Client

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(not (os.environ.get("CRAFT_UI_NODE") and os.environ.get("CRAFT_UI_SCREENSHOTS")),
                                reason="documentation screenshots, taken on request")


def shrink(path: Path) -> None:
    """256 colours: a third of the size, and screens of flat colours look the same."""
    from PIL import Image
    with Image.open(path) as image:
        small = image.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    small.save(path, "PNG", optimize=True)


def test_documentation_screenshots(tmp_path, http, modrinth, fake_java, monkeypatch):
    pytest.importorskip("PIL", reason="pip install pillow (it keeps the pictures small)")
    from craft_conductor import join, joinui

    with example_hub(tmp_path, http, modrinth, fake_java, monkeypatch) as hub:
        # A friend's side: the invite page as GitHub Pages has it (.github/workflows/pages.yml), and
        # their Craft Conductor's page for setting up Minecraft.
        site = tmp_path / "_site"
        shutil.copytree(ROOT / "site", site)
        shutil.copy2(ROOT / "src" / "craft_conductor" / "webui" / "icon.png", site / "icon.png")
        invite = join.Invite("203.0.113.25", 8766, "A" * 24, "F" * 43)
        mods = [{"name": title, "filename": filename, "url": f"https://cdn.modrinth.com/data/{slug.upper()}/{filename}",
                 "sha1": "0" * 40, "side": "both"} for slug, title, _, filename, _ in MODS
                if slug in ("fabric-api", "simple-voice-chat", "xaeros-minimap")]
        http.json[invite.url + "/pack.json"] = pack(name="Survival with friends", address="203.0.113.25", mods=mods,
                                                    loader_version="0.16.9", whitelist=True,
                                                    icon="data:image/png;base64," + base64.b64encode(grass_icon()).decode())
        mc = tmp_path / "friend" / ".minecraft"
        mc.mkdir(parents=True)
        (mc / "launcher_profiles.json").write_text("{}")
        friend = joinui.JoinUI(invite, mc_dir=mc, http=http, prism_dir=tmp_path / "friend" / "prism", out_dir=tmp_path / "friend")
        friend.open_browser = lambda url: None
        friend_url = friend.start()
        try:
            env = {**os.environ, "CRAFT_UI_HOME": str(tmp_path / "home"), "CRAFT_UI_FRIEND": friend_url,
                   "CRAFT_UI_PROGRAMS": str(tmp_path / "Program Files"),
                   "CRAFT_UI_INVITE": invite.page_link("Survival with friends").split("#", 1)[1],
                   "CRAFT_UI_SITE": str(site / "join" / "index.html")}
            result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_screenshots.cjs")),
                                     Client(hub.ui.url.rstrip("/")).base], capture_output=True, text=True, timeout=600, env=env)
            assert result.returncode == 0, result.stdout + result.stderr
            for line in result.stdout.splitlines():
                if line.startswith("took "):
                    shrink(Path(os.environ["CRAFT_UI_SCREENSHOTS"]) / f"{line[5:]}.png")
        finally:
            friend.stop()
