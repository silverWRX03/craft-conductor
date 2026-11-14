"""The project website (site/), as GitHub Pages publishes it: the pages it must keep (the invite page,
the testing dashboard, Google's verification file), the homepage's download links and policy, the
demo's isolation (a sandbox without allow-same-origin, no network for the control panel, a service
worker for demo/ only) and the site put together by tools/build_website.py. The browsers' side is
test_website_browser.py; the simulated backend against the real one is test_website_demo_contract.py.
"""
import json
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
sys.path.insert(0, str(ROOT / "tools"))
import build_website  # noqa: E402
sys.path.pop(0)
sys.path.insert(0, str(ROOT / "src"))
from craft_conductor import qr  # noqa: E402
sys.path.pop(0)


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def tags(path: Path):
    p = Tags()
    p.feed(path.read_text(encoding="utf-8"))
    return p.tags


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("site") / "_site"
    info = build_website.build_site(out, ROOT / "src", "development", "development")
    return out, info


def test_the_pages_that_must_stay():
    for path in ("index.html", "website.js", "nav.js", "css/website.css", "sitemap.xml", "join/index.html", "join/join.js",
                 "testing/index.html", "testing/app.js", "testing/testing.css", "googlef2c4a8b5e575e76a.html", "demo/index.html", "demo/host.js", "demo/sw.js",
                 "demo/manifest.webmanifest", "demo/app/sim/boot.js"):
        assert (SITE / path).is_file(), path
    assert not (SITE / "preview").exists(), "the old hand-made dashboard imitation is gone"


def test_pages_load_only_their_own_scripts_and_styles():
    """No script or style written into the pages (their CSP allows none), nothing from other sites."""
    for page in ("index.html", "testing/index.html", "demo/index.html"):
        text = (SITE / page).read_text(encoding="utf-8")
        assert 'http-equiv="Content-Security-Policy"' in text, page
        csp = re.search(r'Content-Security-Policy" content="([^"]+)"', text).group(1)
        assert "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp and "default-src 'self'" in csp
        for tag, attrs in tags(SITE / page):
            assert not any(k.startswith("on") for k in attrs), f"{page}: an inline event handler on <{tag}>"
            assert "style" not in attrs, f"{page}: an inline style on <{tag}>"
            if tag == "script":
                assert attrs.get("src") and not attrs["src"].startswith(("http", "//")), f"{page}: {attrs}"
            if tag == "link" and attrs.get("rel") == "stylesheet":
                assert not attrs["href"].startswith(("http", "//")), f"{page}: {attrs}"
        assert "<style" not in text, page


def test_the_website_has_its_own_font_and_license(built):
    out, _ = built
    source = ROOT / "src" / "craft_conductor" / "webui" / "fonts"
    for name in ("roboto-latin.woff2", "roboto-symbols.woff2", "OFL.txt"):
        assert (out / "fonts" / name).read_bytes() == (source / name).read_bytes()
    for page in ("index.html", "testing/index.html"):
        assert "fonts.googleapis.com" not in (out / page).read_text(encoding="utf-8")


def test_the_homepage_walkthrough_loads_only_when_requested():
    text = (SITE / "index.html").read_text(encoding="utf-8")
    home = text.split('id="home"', 1)[1].split("</section>", 1)[0]
    parser = Tags()
    parser.feed(home)
    placeholders = [attrs for _, attrs in parser.tags if "video-placeholder" in attrs.get("class", "").split()]
    assert len(placeholders) == 1
    assert "walkthrough" in placeholders[0].get("aria-label", "").lower()
    assert placeholders[0]["id"] == "watch-video"
    assert 'src="images/walkthrough-thumbnail.webp"' in home
    assert (SITE / "images" / "walkthrough-thumbnail.webp").is_file()
    assert not any(tag in {"iframe", "video"} for tag, _ in parser.tags)
    assert not any(attrs.get("href") in {"#demo", "#download"} for _, attrs in parser.tags)
    csp = re.search(r'Content-Security-Policy" content="([^"]+)"', text).group(1)
    assert "frame-src 'self' https://www.youtube-nocookie.com;" in csp
    assert "video-note" not in home


def test_the_homepage_links():
    page = tags(SITE / "index.html")
    links = [a["href"] for t, a in page if t == "a" and "href" in a]
    for href in links:
        assert href.startswith(("#", "https://github.com/silverWRX03/craft-conductor", "testing/", "demo/")) or href == "https://youtu.be/7facGOmax5M", href
    assert "testing/" in links, "the real-world testing dashboard is linked"
    downloads = [h for h in links if "/releases/latest/download/" in h]
    names = [h.rsplit("/", 1)[1] for h in downloads]
    # The files every release has (release.yml makes them and lists them in its notes).
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    for name in names:
        assert f"`{name}`" in release, f"{name} isn't a file the releases have"
    assert names == ["craft-conductor-windows-x64.exe", "craft-conductor-macos-arm64", "craft-conductor-linux-x64",
                     "craft-conductor-linux-arm64"]


def sidebar(page: str) -> list:
    """The sidebar's links: (address, words)."""
    class Links(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links, self.inside, self.href = [], False, None

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "aside" and attrs.get("id") == "site-nav":
                self.inside = True
            elif self.inside and tag == "a" and "nav-link" in attrs.get("class", ""):
                self.href = attrs["href"]
                self.links.append([self.href, ""])

        def handle_endtag(self, tag):
            if tag == "aside":
                self.inside = False
            elif tag == "a":
                self.href = None

        def handle_data(self, data):
            if self.href is not None and data.strip():
                self.links[-1][1] += data.strip()
    p = Links()
    p.feed((SITE / page).read_text(encoding="utf-8"))
    return [tuple(x) for x in p.links]


def test_the_testing_page_has_the_homepages_sidebar():
    """The same links, in the same order, from one folder down; Real-world testing is the page on show."""
    home, testing = sidebar("index.html"), sidebar("testing/index.html")
    assert len(home) >= 9 and [w for _, w in testing] == [w for _, w in home]
    for (h, _), (t, words) in zip(home, testing):
        expected = "./" if h == "testing/" else h if h.startswith("https://") else "../" + h
        assert t == expected, f"{words}: {t}"
    text = (SITE / "testing" / "index.html").read_text(encoding="utf-8")
    assert '<a href="./" class="nav-link active" aria-current="page">' in text
    assert '<script src="../nav.js" defer></script>' in text and 'href="../css/website.css"' in text


def test_the_sitemap():
    """Every page search engines are told about exists, isn't marked noindex, and is on this site; the invite page
    and the demo are kept out of search."""
    import xml.etree.ElementTree as ET
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = [u.text for u in ET.parse(SITE / "sitemap.xml").getroot().findall("s:url/s:loc", ns)]
    assert urls == [build_website.SITE_URL, build_website.SITE_URL + "testing/"]
    for url in urls:
        page = SITE / url.removeprefix(build_website.SITE_URL) / "index.html"
        assert page.is_file(), url
        assert not any(t == "meta" and a.get("name") == "robots" for t, a in tags(page)), f"{url} says noindex"
    for page in ("join/index.html", "demo/index.html"):  # useful only from an invite link / the homepage
        assert ("meta", {"name": "robots", "content": "noindex"}) in tags(SITE / page), f"{page} is kept out of search"


def test_the_demo_frame_is_kept_apart():
    host = (SITE / "demo" / "host.js").read_text(encoding="utf-8")
    sandbox = re.search(r'setAttribute\("sandbox", "([^"]+)"\)', host).group(1).split()
    assert "allow-scripts" in sandbox and "allow-same-origin" not in sandbox, sandbox
    assert not {"allow-top-navigation", "allow-top-navigation-by-user-activation", "allow-modals", "allow-downloads"} & set(sandbox)
    assert 'e.origin !== "null"' in host, "messages are taken only from the sandboxed frame"
    boot = (SITE / "demo" / "app" / "sim" / "boot.js").read_text(encoding="utf-8")
    assert 'self.origin !== "null" || window.parent === window' in boot, "it refuses to run outside the frame"
    assert "postMessage({ type, session: demoSession, ...data }, origin)" in boot, "it only ever tells the website"


def test_only_the_phone_demo_has_a_service_worker():
    regs = {}
    for f in SITE.rglob("*.js"):
        text = f.read_text(encoding="utf-8")
        if "serviceWorker.register(" in text:
            regs[f.relative_to(SITE).as_posix()] = text
    assert set(regs) <= {"demo/shell.js", "demo/app/sim/boot.js"}, set(regs)
    assert 'register("sw.js", { scope: "./" })' in regs["demo/shell.js"]
    sw = (SITE / "demo" / "sw.js").read_text(encoding="utf-8")
    assert "url.pathname.startsWith(scope.pathname)" in sw, "it only answers for demo/"
    manifest = json.loads((SITE / "demo" / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["scope"] == "./" and manifest["display"] == "standalone"


def test_the_site_as_published(built):
    out, info = built
    for path in build_website.REQUIRED:
        assert (out / path).exists(), path
    for page in ("join/index.html", "join/join.js", "testing/index.html", "testing/app.js", "testing/testing.css", "nav.js",
                 "sitemap.xml", "googlef2c4a8b5e575e76a.html"):
        assert (out / page).read_bytes() == (SITE / page).read_bytes(), f"{page} is published as it is"
    assert (out / "testing" / "data").is_dir() and any((out / "testing" / "data").iterdir()), "the testing dashboard's data"
    assert info["channel"] == "development" and info["simulated"]
    version = json.loads((out / "demo" / "version.json").read_text(encoding="utf-8"))
    assert version["version"] == info["version"]


def test_the_demo_page_is_the_real_one_with_no_network(built):
    out, _ = built
    page = (out / "demo" / "app" / "index.html").read_text(encoding="utf-8")
    real = (ROOT / "src" / "craft_conductor" / "webui" / "index.html").read_text(encoding="utf-8")
    assert build_website.APP_CSP in page and "connect-src 'none'" in build_website.APP_CSP
    assert '<link rel="manifest"' not in page, "the panel's page doesn't install itself (the phone demo does)"
    assert not re.search(r'(?:src|href)="/', page), "nothing at the site's root"
    for marker in ('id="app"', 'id="nav"', 'id="btn-start"', 'id="login-form"'):
        assert marker in page and marker in real
    scripts = re.findall(r'<script src="([^"]+)"', page)
    assert scripts[-1] == "sim/boot.js", "the simulation goes first; boot.js loads the real scripts"
    assert re.search(r'data-app="assets/i18n\.js assets/rich\.js assets/pager\.js assets/app\.js"', page)
    for name in ("app.js", "style.css", "craft-conductor-theme.css", "i18n.js"):
        assert (out / "demo" / "app" / "assets" / name).read_bytes() == (ROOT / "src" / "craft_conductor" / "webui" / name).read_bytes(), \
            f"{name} is the real one, unchanged"
    manual = (out / "demo" / "app" / "files" / "manual.md.js").read_text(encoding="utf-8")
    assert manual.startswith('CCSim.file("/manual.md", ') and "</script" not in manual.lower()


def test_the_qr_code_opens_the_phone_demo(built):
    out, info = built
    assert info["phone_url"] == "https://silverwrx03.github.io/craft-conductor/demo/?mode=existing&mobile=1"
    assert (out / "demo" / "phone-qr.svg").read_text(encoding="utf-8") == qr.svg(info["phone_url"])


def test_craft_conductors_own_texts_come_from_the_release(built):
    out, _ = built
    text = (out / "demo" / "app" / "sim" / "catalog-release.js").read_text(encoding="utf-8")
    data = json.loads(text.split("window.CC_DEMO_RELEASE = ", 1)[1].rstrip().rstrip(";"))
    from craft_conductor import serverprops, setup  # (this checkout's)
    assert data["properties_schema"] == serverprops.schema()
    assert [x["name"] for x in data["loaders"]] == [x[0] for x in setup.LOADER_INFO]
    assert data["links"]["invite"].startswith("https://craft-conductor.demo.invalid/")
    assert not data["missing"], data["missing"]


def test_an_older_release_without_some_parts_still_builds(tmp_path):
    """A release from before a module existed (reach.py, cloudflare.py): built without those texts."""
    src = tmp_path / "src"
    shutil.copytree(ROOT / "src" / "craft_conductor", src / "craft_conductor", ignore=shutil.ignore_patterns("__pycache__", "screenshots"))
    shutil.copytree(ROOT / "src" / "craft_conductor" / "webui" / "screenshots", src / "craft_conductor" / "webui" / "screenshots")
    (src / "craft_conductor" / "reach.py").unlink()
    (src / "craft_conductor" / "cloudflare.py").unlink()
    data = build_website.release_catalog(src)
    assert {m.split(":")[0] for m in data["missing"]} >= {"whitelist_warning", "cloudflare"}
    assert data["properties_schema"]


def test_a_broken_release_is_refused(tmp_path):
    with pytest.raises(build_website.BuildError):
        build_website.release_catalog(tmp_path)
    (tmp_path / "craft_conductor").mkdir()
    (tmp_path / "craft_conductor" / "__init__.py").write_text("raise ImportError('broken')\n")
    with pytest.raises(build_website.BuildError, match="couldn't read the release's texts"):
        build_website.release_catalog(tmp_path)


def test_the_website_tools_run_alone():
    for tool in ("build_website.py", "select_website_release.py", "check_demo_contract.py"):
        r = subprocess.run([sys.executable, str(ROOT / "tools" / tool), "--help"], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_the_build_never_deletes_what_isnt_a_build(tmp_path):
    """--output pointing at the checkout (or any folder of yours) is refused, not emptied."""
    precious = tmp_path / "mine"
    precious.mkdir()
    (precious / "notes.txt").write_text("keep me")
    with pytest.raises(build_website.BuildError, match="isn't an earlier site build"):
        build_website.build_site(precious, ROOT / "src", "development", "development", testing=False)
    assert (precious / "notes.txt").read_text() == "keep me"
    with pytest.raises(build_website.BuildError):
        build_website.build_site(ROOT, ROOT / "src", "development", "development", testing=False)


def test_only_the_current_frame_can_save_the_demo():
    host = (SITE / "demo" / "host.js").read_text(encoding="utf-8")
    assert "crypto.getRandomValues" in host and 'msg.session !== session' in host, "a random token for each load of the frame"


def test_a_failed_publish_is_reported_and_only_pages_publishes():
    """pages.yml is the one publisher; a failure opens (or comments on) one issue, closed when it works again."""
    flows = ROOT / ".github" / "workflows"
    publishers = [f.name for f in flows.glob("*.yml") if "deploy-pages@" in f.read_text(encoding="utf-8")]
    assert publishers == ["pages.yml"], publishers
    pages = (flows / "pages.yml").read_text(encoding="utf-8")
    assert "needs: build" in pages and "pages-artifact: true" in pages, "it publishes only what website-build.yml checked"
    assert "if: failure()" in pages and 'title="Website not published"' in pages and "gh issue close" in pages
    release = (flows / "release.yml").read_text(encoding="utf-8")
    call = release[release.index("  invite-page:"):release.index("uses: ./.github/workflows/pages.yml")]
    for permission in ("pages: write", "id-token: write", "issues: write"):
        assert permission in call, f"release.yml's call to pages.yml needs {permission}"
