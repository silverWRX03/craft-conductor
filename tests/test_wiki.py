"""The wiki: every manual section becomes a page, the sidebar finds them all, nothing links nowhere."""

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("wiki", ROOT / "packaging" / "wiki.py")
wiki = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wiki)


def test_the_wiki_builds_with_no_broken_links(tmp_path):
    names = wiki.build(tmp_path)
    assert not wiki.links(tmp_path)
    sections = re.findall(r"^## (.+)$", wiki.MANUAL.read_text(encoding="utf-8"), re.M)
    for title in sections:  # a page for every section of the manual, all in the sidebar
        assert (tmp_path / f"{wiki.page_name(title)}.md").is_file(), title
    sidebar = (tmp_path / "_Sidebar.md").read_text(encoding="utf-8")
    for name in names:
        if name not in ("Home", wiki.START) and not name.startswith("_"):
            assert f"]({name})" in sidebar, name
    # the Power users section comes after the manual in the sidebar
    assert sidebar.index("**User manual**") < sidebar.index("**Power users**") < sidebar.index("(Command-line)")
    assert (tmp_path / "Home.md").is_file() and (tmp_path / "Craft-Conductor-Manual.md").is_file()


def test_every_screenshot_is_there():
    for shots in wiki.IMAGES.values():
        for name, _ in shots:
            assert (wiki.PAGES / "images" / name).is_file(), name
    manual = wiki.MANUAL.read_text(encoding="utf-8")
    for title in wiki.IMAGES:
        assert f"## {title}\n" in manual, f"no manual section {title!r} for its screenshots"
