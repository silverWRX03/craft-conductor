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
    page.on("pageerror", lambda exc: errors.append(page.url + ": " + str(exc)))
    page.goto(base + "demo/?mode=existing")
    page.locator("#app").wait_for(state="visible", timeout=15000)
    for name in ("dashboard", "console", "players", "updates", "mods",
                 "friends", "backups", "java", "settings"):
        page.evaluate("(view) => { location.hash = '#s/family-survival/' + view; }", name)
        page.wait_for_timeout(250)
        assert page.locator("#main").is_visible(), name
        assert page.locator("nav#nav a[href='#s/family-survival/" + name + "']").count() == 1, name
        assert not errors, "Uncaught demo error in route " + name + ": " + repr(errors)
    assert not errors, "JavaScript exceptions while rendering production routes:\n" + "\n".join(errors)


def test_whitelist_request_and_player_actions_are_consistent(base, page):
    page.goto(base + "demo/?mode=existing")
    page.locator("#app").wait_for(state="visible", timeout=15000)
    page.evaluate("location.hash = '#s/family-survival/players'")
    page.get_by_text("Sam_Builds", exact=False).first.wait_for(timeout=8000)
    # Press the actual production UI control, not a fake test-only control.
    page.locator("#main").get_by_role("button", name="Allow").first.click()
    page.wait_for_function("""async () => {
        const r=await (await fetch('/api/players')).json();
        return r.whitelist.some(x=>x.name==='Sam_Builds')
          && !(await (await fetch('/api/join-requests')).json()).requests
              .some(x=>x.name==='Sam_Builds');
    }""")
    page.evaluate("window.CraftDemo.playerJoin('JordanMC')")
    values = page.evaluate("""async () => {
      const r=await (await fetch('/api/players')).json();
      const h=await (await fetch('/api/hub')).json();
      return {players:r.online,hub:h.servers[0].players};
    }""")
    assert "JordanMC" in values["players"]
    assert values["hub"] == len(values["players"])
    page.evaluate("location.hash = '#s/family-survival/dashboard'")
    page.get_by_text("JordanMC").first.wait_for(timeout=8000)


def test_server_create_power_and_backup_share_state(base, page):
    page.goto(base + "demo/?mode=new")
    page.locator("#app").wait_for(state="visible", timeout=15000)
    first = page.evaluate("""async () => (await (await fetch('/api/hub')).json()).servers""")
    assert first == []
    created = page.evaluate("""async () => {
      const res=await fetch('/api/hub/create',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({motd:'My Demo World',loader:'fabric',minecraft:'1.21.1'})});
      return await res.json();
    }""")
    assert created["id"]
    page.evaluate("(id) => {location.hash='#s/'+id+'/dashboard'}", created["id"])
    page.wait_for_function("""async () => (await (await fetch('/api/hub')).json()).servers.length===1""")
    page.evaluate("""async () => {
        const r=await fetch('/api/servers/server-1/server/start',{method:'POST'});
        if(!r.ok)throw Error((await r.json()).error);
    }""")
    # Production hub reflects the same server as its status endpoint.
    result = page.evaluate("""async () => {
      const hub=await(await fetch('/api/hub')).json();
      const status=await(await fetch('/api/servers/server-1/status')).json();
      return {hub:hub.servers[0].state, status:status.state};
    }""")
    assert result == {"hub":"running","status":"running"}
    page.evaluate("""async () => {
      const res=await fetch('/api/servers/server-1/backups/create',{method:'POST'});
      if(!res.ok)throw Error((await res.json()).error);
    }""")
    backups=page.evaluate("""async()=> (await(await fetch('/api/servers/server-1/backups')).json()).backups""")
    assert len(backups)==1
    assert backups[0]["name"].endswith(".tar.gz")


def test_mock_denies_unknown_requests_without_network(base, page):
    actual = []
    page.on("request",lambda req:actual.append(req.url)
            if req.url.endswith("/api/never-allowed") else None)
    page.goto(base + "demo/?mode=existing")
    page.locator("#app").wait_for(state="visible",timeout=15000)
    result=page.evaluate("""async()=>{
      const r=await fetch('/api/never-allowed');
      return {status:r.status,body:await r.json()};
    }""")
    assert result["status"]==501
    assert "No real request" in result["body"]["error"]
    assert not actual, "Unrecognized API escaped the browser-only adapter"
