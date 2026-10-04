"""The wiki: every manual section becomes a page, the sidebar finds them all, nothing links nowhere."""

import importlib.util
import json
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
            assert (wiki.SHOTS / name).is_file(), name
    manual = wiki.MANUAL.read_text(encoding="utf-8")
    for title in wiki.IMAGES:
        assert re.search(rf"^###? {re.escape(title)}$", manual, re.M), f"no manual section {title!r} for its screenshots"


def test_the_app_and_the_wiki_show_the_same_screenshots():
    """The manual's "See this screen" in the app (MANUAL_PICTURES) and the wiki's pictures (IMAGES) match,
    and every picture that ships with craft-conductor is shown somewhere."""
    app = (wiki.ROOT / "src" / "craft_conductor" / "webui" / "app.js").read_text(encoding="utf-8")
    block = app[app.index("const MANUAL_PICTURES = {") + len("const MANUAL_PICTURES = "):]
    block = block[:block.index("\n};") + 2]
    pictures = json.loads(re.sub(r",(\s*[}\]])", r"\1", block))
    assert pictures == {title: [[name[:-4], caption] for name, caption in shots] for title, shots in wiki.IMAGES.items()}
    used = {name for shots in wiki.IMAGES.values() for name, _ in shots}
    used |= {f"{name}.png" for name in re.findall(r'screenshot\("([a-z-]+)"', app)}
    assert {p.name for p in wiki.SHOTS.glob("*.png")} == used
