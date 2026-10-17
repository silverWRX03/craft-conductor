#!/usr/bin/env python3
"""Assemble the public GitHub Pages project site and the isolated, release-matched demo.

The marketing site and /testing/ always come from the checked-out main branch.
Only the app UI assets may come from an already published release checkout.
No real backend or privileged process is included in the generated pages.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "/craft-conductor/demo/"
SCREENS = (
    "dashboard", "console", "players", "updates", "mods", "friends",
    "backups", "java", "settings",
)
GLOBAL = ("servers", "new", "craft-conductor", "help", "manual", "browse", "setup")


def build(out: Path, ui: Path, version: str) -> None:
    site = ROOT / "site"
    if not (ui / "index.html").is_file() or not (ui / "app.js").is_file():
        raise SystemExit("Cannot build demo without a matching application frontend")
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(site, out)
    screenshots = out / "assets"
    screenshots.mkdir(parents=True, exist_ok=True)
    for name in ("dashboard.png", "connected-players.png"):
        src = ui / "screenshots" / name
        if not src.is_file():
            raise SystemExit("Required UI screenshot missing: " + str(src))
        shutil.copy2(src, screenshots / name)
    shutil.copy2(ui / "icon.png", out / "icon.png")
    demo = out / "demo"
    demo.mkdir(exist_ok=True)
    for name in ("app.js", "i18n.js", "rich.js", "pager.js", "style.css", "craft-conductor-theme.css", "icon.png", "icon-192.png", "icon-512.png"):
        src = ui / name
        if not src.is_file():
            raise SystemExit("Missing production UI asset: " + name)
        content = src.read_text(encoding="utf-8") if src.suffix in (".js", ".css") else None
        if name == "app.js":
            # The actual app registers a push service worker and resolves translations
            # relative to /. Both are inappropriate inside the static demo.
            if "  registerWorker();" not in content or 'loadLanguage("/")' not in content:
                raise SystemExit("Production app bootstrap changed; update demo adapter before publishing")
            content = content.replace("  registerWorker();", "  // No production service worker in public demo.")
            content = content.replace('loadLanguage("/")', 'loadLanguage("./")')
        if content is None:
            shutil.copy2(src, demo / name)
        else:
            (demo / name).write_text(content, encoding="utf-8")
    # Include existing translations, images and manual from exactly the same app version.
    if (ui / "i18n").is_dir():
        shutil.copytree(ui / "i18n", demo / "i18n", dirs_exist_ok=True)
    if (ui / "screenshots").is_dir():
        shutil.copytree(ui / "screenshots", demo / "screenshots", dirs_exist_ok=True)
    if (ui / "manual.md").is_file():
        shutil.copy2(ui / "manual.md", demo / "manual.md")

    page = (ui / "index.html").read_text(encoding="utf-8")
    # Relative links work at /craft-conductor/demo/ and during local validation.
    page = re.sub(r'(?<=[="])/(icon\.png|manifest\.webmanifest|style\.css|craft-conductor-theme\.css|i18n\.js|rich\.js|pager\.js|app\.js)', r'\1', page)
    page = re.sub(r'<link rel="manifest"[^>]+>', "", page)
    if '<script src="app.js"></script>' not in page:
        raise SystemExit("Production UI script structure changed; do not publish broken demo")
    page = page.replace('<script src="app.js"></script>',
        '<script src="demo-runtime.js"></script>\n'
        '<script src="app.js"></script>')
    page = page.replace('</head>', '<meta http-equiv="Content-Security-Policy" '
        'content="default-src &#39;none&#39;; script-src &#39;self&#39;; style-src &#39;self&#39;; '
        'img-src &#39;self&#39; data:; connect-src &#39;self&#39;; font-src &#39;self&#39;; ' 
        'worker-src &#39;self&#39;; manifest-src &#39;self&#39;; '
        'base-uri &#39;self&#39;; frame-ancestors &#39;self&#39;; form-action &#39;none&#39;; object-src &#39;none&#39;">'
        '<link rel="manifest" href="manifest.webmanifest">' 
        '<link rel="stylesheet" href="demo-runtime.css"></head>')
    # Version is informational: the build source is pinned to the published release.
    page = page.replace('<script src="demo-runtime.js"></script>',
        '<script>window.CC_DEMO_VERSION='+json.dumps(version)+'</script>\n'
        '<script src="demo-runtime.js"></script>')
    # Remove inline bootstrap by writing the version to a separately loaded file.
    page = re.sub(r'<script>window\.CC_DEMO_VERSION=.*?</script>',
                  '<script src="demo-version.js"></script>', page)
    (demo / "demo-version.js").write_text(
        "window.CC_DEMO_VERSION=" + json.dumps(version) + ";\n", encoding="utf-8")
    (demo / "index.html").write_text(page, encoding="utf-8")
    (demo / "release.json").write_text(json.dumps(
        {"version": version, "channel": "beta-and-stable", "source": "published-release",
         "simulation": True}, indent=2) + "\n", encoding="utf-8")

    # The QR code points to a public page that works independently on any device.
    try:
        import qrcode
        from qrcode.image.svg import SvgPathImage
    except ImportError as err:
        raise SystemExit("Run pip install qrcode==8.2 before building the public website") from err
    url = "https://silverwrx03.github.io/craft-conductor/demo/?scenario=example&phone=1"
    qr = qrcode.make(url, image_factory=SvgPathImage, border=2, box_size=6)
    qr.save(str(demo / "phone-qr.svg"))

    code = (ui / "app.js").read_text(encoding="utf-8")
    missing = [screen for screen in SCREENS if
               not re.search(r"views\." + re.escape(screen) + r"\s*=", code)]
    if missing:
        raise SystemExit("Application routes removed/renamed: " + ", ".join(missing))
    (demo / "coverage.json").write_text(json.dumps({
        "application_version": version,
        "server_routes": list(SCREENS),
        "global_routes": list(GLOBAL),
        "fully_simulated": ["servers", "dashboard", "console", "players"],
        "partial_simulation": ["new", "mods", "backups", "settings"],
        "remaining_to_validate": ["updates", "friends", "java", "setup", "craft-conductor", "help", "manual", "browse"],
        "notes": "Routes are extracted from the real frontend. Partial simulation is not full API coverage."
    }, indent=2) + "\n", encoding="utf-8")
    # The separate testing tracker publishes only sanitized public data.
    from subprocess import run
    run(["python", str(ROOT / "tools" / "real_world_tests.py"),
         "publish", "--output", str(out / "testing" / "data")],
        check=True, cwd=ROOT)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "_site")
    parser.add_argument("--ui-root", type=Path, default=ROOT / "src/craft_conductor/webui")
    parser.add_argument("--version", default="development")
    a = parser.parse_args()
    build(a.output.resolve(), a.ui_root.resolve(), a.version)
    print("Built public website from", a.ui_root, "at", a.output)
