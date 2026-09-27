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
