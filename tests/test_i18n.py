"""Languages: each page's translations are complete, well-formed, and served."""

import json
import re
from pathlib import Path

import pytest

from mcsm import joinui, web
from test_web import running  # noqa: F401  (the fixture)

ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "src" / "mcsm" / "webui"
SITE = ROOT / "site" / "join"


def catalog(code):
    return json.loads((WEBUI / "i18n" / f"{code}.json").read_text(encoding="utf-8"))


def site_catalogs():
    text = (SITE / "i18n.js").read_text(encoding="utf-8")
    return json.loads(text[text.index("{"):text.rindex("}") + 1])


@pytest.mark.parametrize("code", web.LANGUAGES)
def test_every_language_has_a_catalog(code):
    cat = catalog(code)
    assert len(cat) > 400
    assert all(isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in cat.items())
    # the everyday words are all there
    for word in ("Save", "Start", "Stop", "Settings", "Servers", "Language", "Sign in"):
        assert word in cat, (code, word)
    # the page lists the same languages as the server serves
    js = (WEBUI / "i18n.js").read_text(encoding="utf-8")
    assert re.search(rf"\b{code}: \"", js)


def test_translations_keep_their_symbols():
    """A leading ✓ / emoji, an ellipsis and {placeholders} survive translation."""
    for code in web.LANGUAGES:
        for en, tr in catalog(code).items():
            if en[:1] in "✓🌐🎮💬📁📦🔎🔐🩺":
                assert tr.startswith(en[:1]), (code, en, tr)
            if en.endswith("…"):
                assert "…" in tr, (code, en, tr)
    for code, cat in site_catalogs().items():
        for en, tr in cat.items():
            assert set(re.findall(r"\{\w+\}", en)) == set(re.findall(r"\{\w+\}", tr)), (code, en, tr)


def test_the_text_translated_is_on_the_pages():
    """Keys are text the pages actually show (a renamed button needs its translation renamed)."""
    sources = "".join((WEBUI / n).read_text(encoding="utf-8") for n in ("app.js", "join.js", "index.html", "join.html"))
    # (and labels the server sends, like the server settings' names)
    sources += "".join(p.read_text(encoding="utf-8") for p in (ROOT / "src" / "mcsm").glob("*.py"))
    missing = [k for k in catalog("es") if k not in sources and k.replace('"', '\\"') not in sources]
    assert not missing, missing[:10]
    site = (SITE / "join.js").read_text(encoding="utf-8")
    for code, cat in site_catalogs().items():
        assert code in web.LANGUAGES
        missing = [k for k in cat if k not in site and k.replace('"', '\\"') not in site]
        assert not missing, (code, missing[:5])


def test_the_invite_page_loads_its_translations_without_requests():
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert "connect-src 'none'" in html
    assert html.index('src="i18n.js"') < html.index('src="join.js"')


def test_catalogs_are_served(running):
    _, c, _ = running
    for code in web.LANGUAGES:
        status, body, headers = c.get(f"/i18n/{code}.json")
        assert status == 200 and headers["Content-Type"].startswith("application/json")
        assert (body if isinstance(body, dict) else json.loads(body))["Save"]
    status, body, _ = c.get("/i18n.js")
    assert status == 200 and "loadLanguage" in body
    assert c.get("/i18n/xx.json")[0] == 404
    assert all(f"i18n/{code}.json" in joinui.STATIC for code in web.LANGUAGES)
