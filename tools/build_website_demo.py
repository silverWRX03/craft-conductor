#!/usr/bin/env python3
"""Build a static GitHub Pages demo from the authentic Craft Conductor frontend.

The copied production app must never register its service worker on GitHub Pages.
Only the development/Pages artifact is modified; production source remains untouched.
"""
from __future__ import annotations
from pathlib import Path
import argparse
import json
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "craft_conductor" / "webui"
SITE = ROOT / "site"

def build(destination: Path, version: str, channel: str, source: Path = SOURCE) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    assets = destination / "assets"
    assets.mkdir(exist_ok=True)
    original = (source / "index.html").read_text(encoding="utf8")
    required = ("icon.png", "icon-192.png", "icon-512.png",
                "style.css", "craft-conductor-theme.css", "manual.md",
                "help-network.svg", "help-router.svg",
                "i18n.js", "rich.js", "pager.js", "app.js")
    for asset in required:
        original = original.replace('"/' + asset + '"', '"assets/' + asset + '"')
    original = original.replace(
        '<link rel="manifest" href="/manifest.webmanifest">',
        '<link rel="manifest" href="manifest.webmanifest">'
    )
    original = original.replace(
        '<script src="assets/i18n.js">',
        '<script src="mock-api.js"></script>\n  <script src="assets/i18n.js">'
    )
    if '<script src="mock-api.js"></script>' not in original:
        raise SystemExit("Cannot insert mock API ahead of production app")
    original = original.replace("</head>", '<meta name="robots" content="noindex">\n'
        '<style>.cc-demo-ribbon{position:fixed;right:0;top:0;background:#ff3e00;'
        'color:white;z-index:200;padding:3px 8px;font:700 11px system-ui;'
        'pointer-events:none}</style>\n</head>')
    original = original.replace("<body>", '<body><div class="cc-demo-ribbon">DEMO — SIMULATED DATA</div>')
    (destination / "index.html").write_text(original, encoding="utf8")
    for asset in required:
        if asset == "app.js":
            app = (source / asset).read_text(encoding="utf8")
            before = app
            app = app.replace("  registerWorker();", "  // GitHub Pages demo: service worker deliberately disabled.")
            app = app.replace('loadLanguage("/")', 'loadLanguage("./assets/")')
            # The production manual/help use server-root URLs. In GitHub Pages
            # the isolated demo lives under /craft-conductor/demo/.
            app = app.replace('fetch("/manual.md"', 'fetch("assets/manual.md"')
            app = app.replace('/screenshots/${name}.png', 'assets/screenshots/${name}.png')
            app = app.replace('/help-network.svg', 'assets/help-network.svg')
            app = app.replace('/help-router.svg', 'assets/help-router.svg')
            app = app.replace('/icon-192.png', 'assets/icon-192.png')
            app = app.replace('/icon-512.png', 'assets/icon-512.png')
            if app == before or "registerWorker();" in app:
                raise SystemExit("Demo build failed to disable service worker or relocate i18n")
            (assets / "app.js").write_text(app, encoding="utf8")
        else:
            shutil.copy2(SOURCE / asset, assets / asset)
    if (source / "screenshots").is_dir():
        shutil.copytree(source / "screenshots", assets / "screenshots", dirs_exist_ok=True)
    if (source / "i18n").is_dir():
        shutil.copytree(SOURCE / "i18n", assets / "i18n", dirs_exist_ok=True)
    mock = (SITE / "demo" / "mock-api.js").read_text(encoding="utf8")
    mock = mock.replace('const version = "demo";', "const version = " + json.dumps(version) + ";")
    (destination / "mock-api.js").write_text(mock, encoding="utf8")
    manifest = {
        "id": "./?mobile=1", "start_url": "./?mode=existing&mobile=1",
        "scope": "./", "name": "Craft Conductor Demo", "short_name": "CC Demo",
        "description": "Interactive simulation only — does not control a Minecraft server.",
        "display": "standalone", "background_color": "#0a0a0a",
        "theme_color": "#0a0a0a",
        "icons": [{"src": "assets/icon.png", "sizes": "256x256", "type": "image/png"}],
    }
    (destination / "manifest.webmanifest").write_text(json.dumps(manifest, indent=2), encoding="utf8")
    # A real QR code for the standalone phone route; generated offline during CI.
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError as exc:
        raise SystemExit("Website build needs qrcode: python -m pip install qrcode") from exc
    qr_url = "https://silverwrx03.github.io/craft-conductor/demo/?mode=existing&mobile=1"
    qr = qrcode.make(qr_url, image_factory=qrcode.image.svg.SvgPathImage)
    qr.save(str(destination / "phone-qr.svg"))
    # Installable standalone phone demo, scoped ONLY to /craft-conductor/demo/.
    # Unlike the production worker, this one has no push/network control logic
    # and does not cache stale application assets between releases.
    (destination / "demo-sw.js").write_text("""\
"use strict";
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method === "GET" && url.origin === self.location.origin)
    event.respondWith(fetch(event.request));
});
""", encoding="utf8")
    (destination / "demo-pwa.js").write_text("""\
"use strict";
// Never register a worker at the project site root or on invitation/testing pages.
if ("serviceWorker" in navigator)
  navigator.serviceWorker.register("./demo-sw.js", { scope: "./" }).catch(() => {});
""", encoding="utf8")
    original = (destination / "index.html").read_text(encoding="utf8")
    original = original.replace('</body>', '<script src="demo-pwa.js" defer></script></body>')
    (destination / "index.html").write_text(original, encoding="utf8")
    (destination / "version.json").write_text(json.dumps({"version": version, "channel": channel, "source": "production-frontend", "simulated": True}), encoding="utf8")

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, default=ROOT / "_site" / "demo")
    p.add_argument("--version", default="development")
    p.add_argument("--source", type=Path, default=SOURCE)
    p.add_argument("--channel", choices=["beta", "stable", "development"], default="development")
    a = p.parse_args()
    build(a.output, a.version, a.channel, source=a.source)
    print(f"Built demo from production frontend: {a.output}")

if __name__ == "__main__":
    main()
