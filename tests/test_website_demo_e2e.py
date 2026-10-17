"""Browser smoke tests for the GitHub Pages candidate.

Requires 'playwright' Python package and Chromium browser. These tests run
against the assembled _site directory and never connect to production APIs.
"""
from __future__ import annotations
import contextlib
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import pytest

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "_site"

@pytest.fixture(scope="module")
def base():
    assert (SITE / "demo" / "index.html").exists(), "Run tools/build_website_demo.py first"
    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(SITE)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port) + "/"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

@pytest.fixture()
def page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900},
                                      reduced_motion="reduce")
        pg = context.new_page()
        yield pg
        context.close()
        browser.close()

def test_public_paths_and_links(base, page):
    page.goto(base)
    assert page.title().startswith("Craft Conductor")
    assert page.locator(".sidebar").is_visible()
    assert page.locator("html").get_attribute("data-theme") == "dark"
    for rel in ("testing/", "join/", "googlef2c4a8b5e575e76a.html", "demo/phone-qr.svg"):
        response = page.request.get(base + rel)
        assert response.ok, (rel, response.status)
    assert page.locator("#phone-qr").get_attribute("href").startswith("demo/")

def test_existing_server_renders_real_frontend(base, page):
    external_api = []
    page.on("request", lambda req: external_api.append(req.url)
            if "/api/" in req.url and req.resource_type in ("fetch", "xhr") else None)
    page.goto(base)
    page.get_by_role("button", name="Explore the interactive demo").click()
    assert page.locator("#demo-overlay").is_visible()
    assert page.locator("#leave-demo").is_visible()
    page.locator("#existing-demo").click()
    frame = page.frame_locator("#demo-iframe")
    frame.locator("#app").wait_for(state="visible", timeout=15000)
    assert frame.locator("nav#nav").is_visible()
    assert frame.locator("nav#nav a[href='#s/family-survival/players']").count() == 1
    assert not external_api, "Demo made real API requests: " + repr(external_api)
    page.locator("#preview-phone").click()
    assert "phone-frame" in page.locator("#demo-iframe").get_attribute("class")
    page.locator("#desktop-demo").click()
    assert "phone-frame" not in (page.locator("#demo-iframe").get_attribute("class") or "")
    page.locator("#leave-demo").click()
    assert page.locator("#demo-overlay").is_hidden()

def test_first_run_renders_new_server_page(base, page):
    page.goto(base)
    page.locator(".launch-demo").first.click()
    page.locator("#new-demo").click()
    frame = page.frame_locator("#demo-iframe")
    frame.locator("#app").wait_for(state="visible", timeout=15000)
    assert frame.locator("#main").is_visible()
    assert "#new" in page.locator("#demo-iframe").get_attribute("src") or \
        frame.locator("a[href='#new']").count() >= 1
    assert "mode=new" in page.locator("#demo-iframe").get_attribute("src")

def test_mobile_standalone_is_genuine_production_frontend(base, page):
    page.goto(base + "demo/?mode=existing&mobile=1")
    page.locator("#app").wait_for(state="visible", timeout=15000)
    assert page.locator("#cc-app-menu").count() == 1
    assert page.locator("#nav").count() == 1
    assert page.locator(".cc-demo-ribbon").is_visible()

def test_all_nine_production_server_routes(base, page):
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(base + "demo/?mode=existing")
    page.locator("#app").wait_for(state="visible", timeout=15000)
    for name in ("dashboard", "console", "players", "updates", "mods",
                 "friends", "backups", "java", "settings"):
        page.evaluate("window.location.hash = '#s/family-survival/' + arguments[0]" if False
                      else "(view) => { location.hash = '#s/family-survival/' + view; }", name)
        page.wait_for_timeout(250)
        assert page.locator("#main").is_visible(), name
        assert page.locator("nav#nav a[href='#s/family-survival/" + name + "']").count() == 1, name
    assert not errors, "JavaScript exceptions while rendering production routes:\n" + "\n".join(errors)
