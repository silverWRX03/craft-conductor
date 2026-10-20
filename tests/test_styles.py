"""Classic and Modern: the switch, Modern's rules kept to Modern, the font served from Craft Conductor itself, and
the colours that must stay readable. (How they look is checked in a real browser: tests/ui_styles.cjs.)"""

import re
from pathlib import Path

from craft_conductor import joinui
from craft_conductor.web import FONTS, SECURITY_HEADERS, STATIC, static_file
from test_web import running, login  # noqa: F401  (the fixture)

ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "src" / "craft_conductor" / "webui"
MODERN = '[data-style="modern"]'


def css_rules(text):
    """(selector list, body) of each rule, at-rules opened (their own line isn't a selector)."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out, depth, start, selector = [], 0, 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            head = text[start:i].strip()
            if head.startswith("@") and "font-face" not in head:
                start = i + 1
                continue
            selector, start, depth = head, i + 1, depth + 1
        elif ch == "}":
            if selector is not None:
                out.append((selector, text[start:i]))
                selector = None
            start = i + 1
    return out


def split_selectors(selector):
    parts, depth, cur = [], 0, ""
    for ch in selector:
        depth += ch in "(["
        depth -= ch in ")]"
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return [*parts, cur.strip()]


def luminance(hex_colour):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_colour.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_every_modern_rule_is_only_for_modern():
    """Nothing in craft-conductor-modern.css can change Classic."""
    rules = css_rules((WEBUI / "craft-conductor-modern.css").read_text(encoding="utf-8"))
    assert len(rules) > 40
    for selector, _ in rules:
        for one in split_selectors(selector):
            assert one.startswith(":root" + MODERN), one


def test_classic_keeps_its_square_corners_and_modern_does_not_get_them():
    theme = (WEBUI / "craft-conductor-theme.css").read_text(encoding="utf-8")
    assert "*, *::before, *::after { border-radius:0 !important; }" not in theme
    assert ':root:not([data-style="modern"]) * ' in theme or ':root:not([data-style="modern"]) *,' in theme


def test_the_switch_is_two_labelled_choices_and_modern_is_the_default():
    page = (WEBUI / "index.html").read_text(encoding="utf-8")
    assert '<html lang="en" data-style="modern">' in page
    switch = re.search(r'<fieldset id="cc-style".*?</fieldset>', page, re.S).group(0)
    assert "<legend" in switch and "Interface style" in switch
    radios = re.findall(r'<input type="radio" name="cc-style" value="(\w+)" data-style-choice( checked)?>', switch)
    assert radios == [("classic", ""), ("modern", " checked")]
    assert ">Classic<" in switch and ">Modern<" in switch
    # applied in <head>, before the page is drawn, after the stylesheets
    head = page.split("</head>")[0]
    assert head.index("craft-conductor-modern.css") < head.index('<script src="/appearance.js"></script>')
    # the friend's invite page is Modern, without a switch
    join = (WEBUI / "join.html").read_text(encoding="utf-8")
    assert 'data-style="modern"' in join and "craft-conductor-modern.css" in join and "cc-style" not in join


def test_the_style_is_kept_per_person_apart_from_day_and_night():
    app = (WEBUI / "app.js").read_text(encoding="utf-8")
    boot = (WEBUI / "appearance.js").read_text(encoding="utf-8")
    assert 'const STYLE_KEY = "craft-conductor-style"' in app and '"craft-conductor-style"' in boot
    assert "`${STYLE_KEY}:${who}`" in app            # each person's own
    assert '|| "modern"' in app                      # Modern until they pick
    assert app.count("styleSignedIn(") >= 3          # defined, and with each look at /api/hub
    assert "styleSignedOut();" in app
    assert "craft-conductor-theme" in boot and "THEME_KEY" in app  # day / night stays its own setting
    # only the two known values are ever applied
    assert 'STYLES.includes(v) ? v : null' in app and '(style === "classic" || style === "modern")' in boot


def test_the_font_is_bundled_with_its_license_and_served_locally():
    assert "roboto-latin.woff2" in FONTS and len(FONTS) >= 6
    assert (WEBUI / "fonts" / "OFL.txt").read_text(encoding="utf-8").count("SIL Open Font License") >= 1
    for name in FONTS:
        assert STATIC[f"/fonts/{name}"] == (f"fonts/{name}", "font/woff2")
        assert joinui.STATIC[f"fonts/{name}"] == (f"fonts/{name}", "font/woff2")
        assert static_file(f"fonts/{name}")[0][:4] == b"wOF2"
    css = (WEBUI / "style.css").read_text(encoding="utf-8")
    faces = re.findall(r"@font-face \{(.*?)\}", css, re.S)
    assert len(faces) == len(FONTS)
    for face in faces:
        assert "font-display: swap" in face and re.search(r"url\(fonts/roboto-[\w-]+\.woff2\)", face) and "http" not in face
    assert re.search(r"--sans: Roboto, .*sans-serif;", css)
    # no font service: the Content-Security-Policy still allows only this server's own files
    assert "default-src 'self'" in SECURITY_HEADERS["Content-Security-Policy"] and "font-src" not in SECURITY_HEADERS["Content-Security-Policy"]


def test_text_is_at_least_16px_and_the_console_and_editor_stay_monospace():
    css = (WEBUI / "style.css").read_text(encoding="utf-8")
    theme = (WEBUI / "craft-conductor-theme.css").read_text(encoding="utf-8")
    assert "font: 16px/1.5 var(--sans)" in css and "font:16px/1.5 var(--sans)" in theme
    assert re.search(r"\.console \{[^}]*font: 13px/1\.5 var\(--mono\)", css)
    assert re.search(r"\.code-editor \{[^}]*monospace", css)


def test_the_keyboard_ring_is_one_rule_for_everything():
    css = (WEBUI / "style.css").read_text(encoding="utf-8")
    assert "*:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }" in css
    rules = css_rules(css) + css_rules((WEBUI / "craft-conductor-theme.css").read_text(encoding="utf-8"))
    for selector, body in rules:
        if ":focus" in selector and "outline" in body and "outline-offset" not in body:
            assert "outline: none" in body or "outline:none" in body, selector  # (only where the ring is drawn elsewhere)
        assert not re.search(r"outline:\s*2px solid var\(--(info|focus)\)", body) or "contrast" in selector, selector


def test_touch_targets_are_at_least_44px():
    theme = (WEBUI / "craft-conductor-theme.css").read_text(encoding="utf-8")
    coarse = theme.split("@media (pointer: coarse) {", 1)[1]
    for what in (".btn,", ".sidebar nav a { min-height:44px; }", ".bell, .cc-menu-trigger { width:44px; height:44px; }",
                 ".cc-style-switch label { min-height:44px; min-width:44px; }", ".cc-theme-switch::after"):
        assert what in coarse, what


def tokens(css, selector_start):
    block = re.search(re.escape(selector_start) + r"[^{]*\{([^}]*)\}", css).group(1)
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6})\b", block))


def test_colours_stay_readable():
    theme = (WEBUI / "craft-conductor-theme.css").read_text(encoding="utf-8")
    modern = (WEBUI / "craft-conductor-modern.css").read_text(encoding="utf-8")
    sets = {
        "classic day": tokens(theme, ':root[data-theme="day"], :root[data-theme="light"]'),
        "classic night": tokens(theme, ':root, :root[data-theme="night"]'),
        "modern night": tokens(modern, ':root[data-style="modern"]:not([data-contrast="high"]):not('),
        "modern day": tokens(modern, ':root[data-style="modern"]:not([data-contrast="high"]):is('),
    }
    assert sets["classic day"]["accent"].upper() == "#C53000" and contrast("#C53000", "#F4F4F4") >= 4.5
    for name, c in sets.items():
        bg, panel = c.get("bg", sets["classic night"]["bg"]), c.get("panel", sets["classic night"]["panel"])
        for fg in ("text", "muted", "accent"):
            if fg in c:
                for surface in (bg, panel):
                    assert contrast(c[fg], surface) >= 4.5, (name, fg, c[fg], surface)
        assert contrast(c["on-accent"], c["accent"]) >= 4.5, (name, "button text")
        if "warn" in c:
            assert contrast(c["warn"], panel) >= 4.5, (name, "warn")
    assert sets["modern day"]["accent"].upper() == "#0969DA" and sets["modern night"]["accent"].upper() == "#3FB950"
    for name in ("modern day", "modern night"):
        c = sets[name]
        assert contrast(c["console-fg"], c["console-bg"]) >= 4.5
        assert contrast(c["accent"], c["selected-bg"]) >= 4.5, (name, "the open page in the menu")
        assert contrast(c["info"], c["panel-2"]) >= 4.5, (name, "links in a notice")
        assert contrast(c["on-accent"], c["accent-hover"]) >= 4.5, (name, "button text, hovered")
        assert contrast(c["field-border"], c["panel"]) >= 3, (name, "a field's edge")
        assert luminance(c["console-bg"]) < 0.05, (name, "the console stays dark")


def test_the_new_files_are_served(running):  # noqa: F811
    daemon, client, config = running
    login(client)
    for path, kind in (("/craft-conductor-modern.css", "text/css"), ("/appearance.js", "text/javascript"),
                       ("/fonts/roboto-latin.woff2", "font/woff2"), ("/fonts/OFL.txt", "text/plain")):
        status, _, headers = client.get(path)
        assert status == 200 and headers["Content-Type"].startswith(kind), path
    assert client.get("/fonts/../web.py")[0] == 404
