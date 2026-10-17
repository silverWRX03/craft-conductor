"""Which published release the website's demo shows (tools/select_website_release.py): the newest beta
or stable one for now, the newest stable one only once the policy says so; never a draft, never a
tag that doesn't look like Craft Conductor's."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("select_website_release", ROOT / "tools" / "select_website_release.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def release(tag, published, prerelease=False, draft=False, name=None, rid=1):
    return {"tag_name": tag, "name": name if name is not None else f"Craft Conductor {tag} (beta)", "prerelease": prerelease,
            "draft": draft, "published_at": published, "id": rid,
            "html_url": f"https://github.com/silverWRX03/craft-conductor/releases/tag/{tag}"}


RELEASES = [
    release("v0.28.0", "2026-10-16T20:59:51Z", rid=1),
    release("v0.29.0b1", "2026-10-18T12:00:00Z", prerelease=True, rid=2),
    release("v0.30.0", "2026-10-19T12:00:00Z", draft=True, rid=3),
]


def test_a_beta_titled_release_is_a_beta():
    assert mod.channel_of(release("v0.28.0", "x")) == "beta", "release.yml titles every release (beta) for now"
    assert mod.channel_of(release("v0.29.0b1", "x", prerelease=True, name="Craft Conductor v0.29.0b1")) == "beta"
    assert mod.channel_of(release("v1.0.0", "x", name="Craft Conductor v1.0.0")) == "stable"


def test_beta_and_stable_shows_the_newest_published():
    chosen = mod.choose(RELEASES, "beta-and-stable")
    assert chosen["tag"] == "v0.29.0b1" and chosen["channel"] == "beta" and chosen["version"] == "0.29.0b1"


def test_drafts_never_count():
    assert mod.choose(RELEASES[:1] + RELEASES[2:], "beta-and-stable")["tag"] == "v0.28.0"


def test_stable_only_waits_for_a_stable_release():
    with pytest.raises(mod.PolicyError, match="every release so far is a beta"):
        mod.choose(RELEASES, "stable")
    stable = RELEASES + [release("v1.0.0", "2026-11-01T12:00:00Z", name="Craft Conductor v1.0.0", rid=4),
                         release("v1.1.0b1", "2026-11-05T12:00:00Z", prerelease=True, rid=5)]
    chosen = mod.choose(stable, "stable")
    assert chosen["tag"] == "v1.0.0" and chosen["channel"] == "stable", "a newer beta doesn't replace it"
    assert mod.choose(stable, "beta-and-stable")["tag"] == "v1.1.0b1"


def test_an_odd_tag_or_page_stops_publishing():
    for tag in ("v1/../../x", "latest", "v1.0", "v1.0.0 ", "v1.0.0\n"):
        with pytest.raises(mod.PolicyError):
            mod.choose([release(tag, "2026-10-17T00:00:00Z")], "beta-and-stable")
    bad = release("v1.0.0", "2026-10-17T00:00:00Z")
    bad["html_url"] = "https://example.com/release"
    with pytest.raises(mod.PolicyError):
        mod.choose([bad], "beta-and-stable")
    with pytest.raises(mod.PolicyError):
        mod.choose([], "beta-and-stable")
    with pytest.raises(mod.PolicyError):
        mod.choose(RELEASES, "everything")


def test_the_policy_file(tmp_path):
    assert mod.load_policy() == "beta-and-stable", "for now: the owner switches it to stable"
    wrong = tmp_path / "policy.json"
    wrong.write_text(json.dumps({"channel": "both"}))
    with pytest.raises(mod.PolicyError):
        mod.load_policy(wrong)


def test_the_tool_writes_what_the_workflow_reads(tmp_path):
    import subprocess
    import sys
    data, out = tmp_path / "releases.json", tmp_path / "github_output"
    data.write_text(json.dumps(RELEASES))
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "select_website_release.py"), "--releases-file", str(data),
                        "--github-output", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert out.read_text().splitlines() == ["tag=v0.29.0b1", "version=0.29.0b1", "channel=beta",
                                            "url=https://github.com/silverWRX03/craft-conductor/releases/tag/v0.29.0b1"]
