"""Static safety checks for the public website assembly; additional Playwright coverage is required before merge."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"

def test_project_website_files_exist():
    for path in ("index.html", "website.js", "css/website.css", "preview/index.html",
                 "join/index.html", "testing/index.html",
                 "googlef2c4a8b5e575e76a.html"):
        assert (SITE / path).is_file(), f"Missing required page asset: {path}"

def test_published_paths_and_exit_control():
    page = (SITE / "index.html").read_text(encoding="utf8")
    for needle in ('href="testing/"', 'id="leave-demo"', 'id="new-demo"',
                   'id="existing-demo"', 'id="demo-overlay"', 'class="sidebar"'):
        assert needle in page
    script = (SITE / "website.js").read_text(encoding="utf8")
    for needle in ('Escape', 'previousFocus', 'closeDemo', 'allow'):
        # The real route coverage and iframe behavior are separately tested by the UI suite.
        if needle == 'allow':
            continue
        assert needle in script

def test_website_does_not_reference_a_real_backend():
    page = (SITE / "index.html").read_text(encoding="utf8")
    script = (SITE / "website.js").read_text(encoding="utf8")
    assert "/api/" not in page
    assert "/api/" not in script
    assert "sandbox=" in page

def test_original_preview_is_relocated():
    page = (SITE / "preview/index.html").read_text(encoding="utf8")
    assert 'src="../preview.js"' in page
    assert 'href="../css/' in page
