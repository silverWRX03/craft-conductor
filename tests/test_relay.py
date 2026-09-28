"""The mod-conflict relay (relay/worker.js), run in Node against fake Cloudflare storage."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
def test_reports_are_counted_per_person_and_listed_from_three(tmp_path):
    worker = tmp_path / "worker.mjs"  # (an ES module, as Cloudflare runs it)
    shutil.copy(ROOT / "relay" / "worker.js", worker)
    r = subprocess.run(["node", str(ROOT / "tests" / "relay" / "run_worker.mjs"), str(worker)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["first"] == 200 and out["same_person"] == 1  # the same person twice counts once
    assert out["listed_at_two"] == 0
    [c] = out["listed_at_three"]
    assert (c["loader"], c["minecraft"], c["mod"], c["with"], c["reports"]) == ("fabric", "1.21.1", "badmod", ["sodium"], 3)
    assert out["bad_loader"] == out["bad_id"] == out["bad_json"] == 400
    assert out["last_flood"] == 429  # one address can't flood it
    assert not out["stored_ips"]  # addresses are never kept, only salted hashes
