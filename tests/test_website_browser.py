"""The website and its demo in real browsers (Chromium, and Firefox and WebKit where installed): the
homepage on a computer and a phone, opening and leaving the demo, both ways to start it, going through
the real control panel's pages with the made-up servers (making a server, a friend joining, mods,
backups, updates that work and fail, invites, maps, settings, people), the phone demo, and that the
demo stays apart from the website and never reaches a network. The site is put together the way the
Pages workflow does (tools/build_website.py) and served the way GitHub Pages serves it.

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> pytest tests/test_website_browser.py

CRAFT_WEBSITE_SOURCE=<a release's src/> tests the demo made from that release's control panel (the
Pages workflow does both). CRAFT_WEBSITE_REQUIRED=1 makes a missing Node or Playwright a failure
instead of a skip (the website workflows set it: the site isn't published untested).
CRAFT_UI_BROWSERS picks the browsers (default: chromium; the workflows use chromium,firefox,webkit).
"""
import os
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HAVE = bool(os.environ.get("CRAFT_UI_NODE") and os.environ.get("CRAFT_UI_PLAYWRIGHT"))
if not HAVE and os.environ.get("CRAFT_WEBSITE_REQUIRED") == "1":
    raise RuntimeError("the website's browser tests are required here: set CRAFT_UI_NODE and CRAFT_UI_PLAYWRIGHT")
pytestmark = pytest.mark.skipif(not HAVE, reason="optional browser verification")
SCRIPTS = ["ui_website.cjs", "ui_website_demo.cjs", "ui_website_phone.cjs"]


class PagesHandler(SimpleHTTPRequestHandler):
    """Like GitHub Pages: the site under /craft-conductor/, every file readable from anywhere (CORS *)."""
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript", ".webmanifest": "application/manifest+json",
                      ".svg": "image/svg+xml", ".json": "application/json"}

    def translate_path(self, path):
        p = path.split("?", 1)[0].split("#", 1)[0]
        if not p.startswith("/craft-conductor/"):
            return str(Path(self.directory) / "__not_here__")
        return super().translate_path(p[len("/craft-conductor"):])

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("pages") / "_site"
    source = Path(os.environ.get("CRAFT_WEBSITE_SOURCE") or ROOT / "src")
    version = os.environ.get("CRAFT_WEBSITE_VERSION", "development")
    channel = os.environ.get("CRAFT_WEBSITE_CHANNEL", "development")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "build_website.py"), "--output", str(out), "--source", str(source),
                        "--version", version, "--channel", channel], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(PagesHandler, directory=str(out)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/craft-conductor/", out
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("script", SCRIPTS)
def test_website_in_a_browser(site, script, tmp_path):
    base, out = site
    env = {**os.environ, "CRAFT_WEBSITE_OUT": str(tmp_path), "CRAFT_WEBSITE_DIR": str(out)}
    result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name(script)), base],
                            capture_output=True, text=True, encoding="utf-8", timeout=900, env=env)
    assert result.returncode == 0, result.stdout[-6000:] + result.stderr[-6000:]
