"""Release selection must be predictable and require an explicit stable-only flip."""
import importlib.util
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("demo_release",ROOT/"tools/select_website_release.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

FIXTURES=[
    {"tag_name":"v0.29.0b1","prerelease":True,"draft":False,"published_at":"2026-10-18T12:00:00Z","id":5},
    {"tag_name":"v0.28.0","prerelease":False,"draft":False,"published_at":"2026-10-17T12:00:00Z","id":4},
    {"tag_name":"v0.30.0b2","prerelease":True,"draft":True,"published_at":"2026-10-19T12:00:00Z","id":6},
]
def test_beta_and_stable_are_allowed_before_transition():
    assert mod.choose(FIXTURES,"both")["tag"]=="v0.29.0b1"
    assert mod.choose(FIXTURES,"both")["channel"]=="beta"

def test_explicit_stable_only_transition_rejects_new_beta():
    assert mod.choose(FIXTURES,"stable")["tag"]=="v0.28.0"
    assert mod.choose(FIXTURES,"stable")["channel"]=="stable"

def test_failed_selection_blocks_publish():
    with pytest.raises(ValueError):
        mod.choose([], "stable")
    with pytest.raises(ValueError):
        mod.choose(FIXTURES, "unknown")

def test_published_tag_must_not_include_path_or_whitespace():
    bad=[{"tag_name":"v1/../../unsafe","prerelease":False,"draft":False,
         "published_at":"2026-10-17T12:00:00Z","id":10}]
    with pytest.raises(ValueError):
        mod.choose(bad,"stable")
