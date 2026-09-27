"""The web pages' scripts must at least parse (a typo would leave a page blank)."""

import shutil
import subprocess
from pathlib import Path

import pytest

WEBUI = Path(__file__).resolve().parents[1] / "src" / "mcsm" / "webui"


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
@pytest.mark.parametrize("script", sorted(p.name for p in WEBUI.glob("*.js")))
def test_script_parses(script):
    r = subprocess.run(["node", "--check", str(WEBUI / script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
