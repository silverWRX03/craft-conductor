"""The web pages' scripts must at least parse (a typo would leave a page blank)."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted([*(ROOT / "src" / "mcsm" / "webui").glob("*.js"), *(ROOT / "site").rglob("*.js")])  # (site/: the invite page)


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
@pytest.mark.parametrize("script", [str(p.relative_to(ROOT)) for p in SCRIPTS])
def test_script_parses(script):
    r = subprocess.run(["node", "--check", str(ROOT / script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_the_control_panel_asks_in_its_own_dialog():
    """Questions use ask() (mcsm's dialog, with "Don't ask me again" for the everyday ones),
    never the browser's confirm(), and the page guards against closing mid-upload or unsaved."""
    import re
    app = (ROOT / "src" / "mcsm" / "webui" / "app.js").read_text(encoding="utf-8")
    assert not re.search(r"(?<![\w.])confirm\(", app)
    assert "beforeunload" in app and "Don't ask me again" in app
