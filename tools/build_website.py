#!/usr/bin/env python3
"""Put together the whole GitHub Pages site (_site/): the homepage, the invite page (join/), the
real-world testing dashboard (testing/, with its data), Google's site verification file, and the
interactive demo (demo/) made from a released Craft Conductor's own control panel.

    python tools/build_website.py --output _site                      # this checkout's panel ("development")
    python tools/build_website.py --output _site --source <release>/src --version 0.28.0 --channel beta \\
        --release-url https://github.com/silverWRX03/craft-conductor/releases/tag/v0.28.0

``--source`` is the src/ folder of the release the demo shows (the Pages workflow extracts it from the
release's tag): its webui/ is the demo's page, unchanged, and its Python code supplies Craft Conductor's
own texts (setup choices, server settings, permissions, the notice). The simulated backend is
site/demo/app/sim/ (this checkout's). Nothing here downloads anything.

The panel's page is put in demo/app/ with a Content-Security-Policy that allows no network connections,
and its scripts load only after the simulation (sim/boot.js) has taken the network's place. The page
refuses to run except inside the website's sandboxed frame (site/demo/host.js).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
SITE_URL = "https://silverwrx03.github.io/craft-conductor/"
# The phone demo the homepage's QR code opens (a page of the website: GitHub Pages).
PHONE_PATH = "demo/?mode=existing&mobile=1"
# Made-up links the demo shows: .invalid addresses never lead anywhere (RFC 2606).
DEMO_LINKS = {"invite": "https://craft-conductor.demo.invalid/#invite=DEMO-NOT-A-REAL-INVITE",
              "pair": "https://craft-conductor.demo.invalid/#pair=DEMO-ONLY"}
# The control panel's page in the demo: its own files only, no connections at all (sim/boot.js answers).
APP_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'none'; "
           "font-src 'self'; media-src 'none'; frame-src 'none'; worker-src 'none'; manifest-src 'none'; "
           "object-src 'none'; base-uri 'none'; form-action 'none'")
SIM_SCRIPTS = ["catalog-release.js", "core.js", "catalog.js", "engine.js", "world.js", "routes-hub.js",
               "routes-server.js", "routes-mods.js", "ui.js"]
# What the real app's own files are: everything in webui/ the demo shows (not its service worker,
# manifest or the friends' join page, which aren't part of the control panel).
SKIP_ASSETS = {"index.html", "sw.js", "manifest.webmanifest", "join.html", "join.js"}
# Minecraft's own defaults for the game rules World tools shows (worldtools.RULES has the words).
RULE_DEFAULTS = {"keepInventory": "false", "doDaylightCycle": "true", "doWeatherCycle": "true", "doMobSpawning": "true",
                 "mobGriefing": "true", "doFireTick": "true", "doInsomnia": "true", "naturalRegeneration": "true",
                 "playersSleepingPercentage": "100", "announceAdvancements": "true", "showDeathMessages": "true",
                 "spawnRadius": "10"}
REQUIRED = ("index.html", "website.js", "css/website.css", "join/index.html", "testing/index.html", "testing/data",
            "googlef2c4a8b5e575e76a.html", "icon.png", "demo/index.html", "demo/host.js", "demo/sw.js",
            "demo/manifest.webmanifest", "demo/phone-qr.svg", "demo/version.json", "demo/app/index.html",
            "demo/app/assets/app.js", "demo/app/sim/boot.js", "demo/app/sim/catalog-release.js", "demo/app/files/manual.md.js")


class BuildError(Exception):
    pass


# What a release's Python code says (run as its own program, so this checkout's craft_conductor
# isn't mixed in). Older releases may lack a part: it's left out, and the demo does without.
CATALOG_SCRIPT = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
import craft_conductor
from craft_conductor import config, notice, serverprops, setup
out = {"version": craft_conductor.__version__,
       "loaders": [{"name": n, "label": l, "description": d, "mods": m} for n, l, d, m in setup.LOADER_INFO],
       "difficulties": list(setup.DIFFICULTIES), "gamemodes": list(setup.GAMEMODES),
       "properties_schema": serverprops.schema(),
       "notice": {"version": notice.NOTICE_VERSION, "title": notice.TITLE, "points": list(notice.POINTS)},
       "link_days": list(getattr(config, "LINK_DAYS", (1, 3, 7))), "missing": []}
def part(name, fn):
    try:
        out[name] = fn()
    except Exception as e:  # (an older release without it)
        out["missing"].append(f"{name}: {e.__class__.__name__}")
def access():
    from craft_conductor import access
    return access.catalog()
def risks():
    return [{"name": k, "text": v} for k, v in config.RISKS.items()]
def licenses():
    from craft_conductor import licenses
    return licenses.as_dict()
def guide():
    from craft_conductor import guide
    out["guide_manual"] = sorted(guide.MANUAL)
    return [{"id": i, "title": t, "how": h} for i, t, h in guide.STEPS]
def rules():
    from craft_conductor import worldtools
    return [{"id": i, "kind": k, "words": w} for i, k, w in worldtools.RULES]
def push():
    from craft_conductor import push
    return dict(push.KINDS)
def users():
    from craft_conductor import users
    return users.INVITE_SECONDS // 3600
def strong():
    from craft_conductor import webauth
    return webauth.STRONG_RULES
def upnp():
    from craft_conductor import upnp
    return upnp.EXPOSURE_WARNING
def reach():
    from craft_conductor import reach
    out["router_risks"], out["playit_downsides"] = reach.ROUTER_RISKS, reach.PLAYIT_DOWNSIDES
    return reach.WHITELIST_OFF_WARNING
def cloudflare():
    from craft_conductor import cloudflare
    return {"downsides": list(cloudflare.DOWNSIDES), "hours": cloudflare.HOURS, "about": cloudflare.ABOUT}
def playit():
    from craft_conductor import tunnel
    return {"apt": list(tunnel.APT_STEPS)}
for name, fn in [("access", access), ("risks", risks), ("licenses", licenses), ("guide", guide), ("gamerules", rules), ("push_kinds", push), ("invite_hours", users), ("strong_rules", strong),
                 ("upnp_warning", upnp), ("whitelist_warning", reach), ("cloudflare", cloudflare), ("playit", playit)]:
    part(name, fn)
json.dump(out, sys.stdout)
'''


def release_catalog(source: Path) -> dict:
    """Craft Conductor's own texts, from the release's Python source (``source`` is its src/)."""
    if not (source / "craft_conductor" / "__init__.py").is_file():
        raise BuildError(f"{source} isn't a Craft Conductor src/ folder (no craft_conductor/__init__.py)")
    r = subprocess.run([sys.executable, "-S", "-c", CATALOG_SCRIPT, str(source)], capture_output=True, text=True,
                       encoding="utf-8", cwd=source, timeout=120)
    if r.returncode != 0:
        raise BuildError("couldn't read the release's texts:\n" + r.stderr[-3000:])
    data = json.loads(r.stdout)
    for g in data.get("gamerules", []):
        g["default"] = RULE_DEFAULTS.get(g["id"], "true" if g["kind"] == "bool" else "0")
    return data


def _qr(text: str) -> str:
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from craft_conductor import qr  # (this checkout's QR code maker; the standard library only)
    finally:
        sys.path.pop(0)
    return qr.svg(text)


def _script_file(path: str, text: str) -> str:
    """One of the app's own text files as a script the sandboxed page can load (it has no connections)."""
    return f"CCSim.file({json.dumps(path)}, {json.dumps(text, ensure_ascii=False)});\n".replace("</", "<\\/")


def build_demo(dest: Path, frontend: Path, catalog: dict, release: dict) -> None:
    """demo/app/: the release's control panel page with the simulation in front of it."""
    index = (frontend / "index.html").read_text(encoding="utf-8")
    if "app.js" not in index or not (frontend / "app.js").is_file():
        raise BuildError(f"{frontend} has no control panel (index.html and app.js)")
    scripts = re.findall(r'<script src="/([\w.-]+\.js)"></script>', index)
    if not scripts or scripts[-1] != "app.js":
        raise BuildError(f"the panel's scripts weren't found where expected in index.html: {scripts!r}")
    assets = dest / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    for item in frontend.iterdir():
        if item.name in SKIP_ASSETS or item.name == "i18n":
            continue
        if item.is_dir():
            shutil.copytree(item, assets / item.name, dirs_exist_ok=True)
        elif item.suffix in (".js", ".css", ".png", ".svg"):
            shutil.copy2(item, assets / item.name)
    # The panel's own text files (the manual, translations), as scripts.
    files = dest / "files"
    (files / "i18n").mkdir(parents=True, exist_ok=True)
    (files / "manual.md.js").write_text(_script_file("/manual.md", (frontend / "manual.md").read_text(encoding="utf-8")), encoding="utf-8")
    for lang in sorted((frontend / "i18n").glob("*.json")) if (frontend / "i18n").is_dir() else []:
        (files / "i18n" / f"{lang.name}.js").write_text(_script_file(f"/i18n/{lang.name}", lang.read_text(encoding="utf-8")), encoding="utf-8")

    # The page: the same markup, its own files next to it, no manifest, and the simulation first.
    page = index
    page = re.sub(r'\s*<link rel="manifest"[^>]*>', "", page)
    page = re.sub(r'(href|src)="/([\w./-]+\.(?:png|css|svg))"', r'\1="assets/\2"', page)
    page = page.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n  <meta http-equiv="Content-Security-Policy" content="'
                        + APP_CSP + '">\n  <meta name="referrer" content="no-referrer">\n  <meta name="robots" content="noindex">', 1)
    if APP_CSP not in page:
        raise BuildError("couldn't put the demo's Content-Security-Policy in the page (no <meta charset=\"utf-8\">)")
    page = page.replace("</head>", '  <link rel="stylesheet" href="sim/demo.css">\n</head>', 1)
    block = re.search(r'(\s*<script src="/[\w.-]+\.js"></script>)+', page)
    sim = "".join(f'\n  <script src="sim/{name}"></script>' for name in SIM_SCRIPTS)
    boot = f'\n  <script src="sim/boot.js" data-app="{" ".join("assets/" + s for s in scripts)}"></script>'
    page = page[:block.start()] + sim + boot + page[block.end():]
    # The sign-in page can show (after Sign out): the demo says no password is needed.
    page = page.replace('<form id="login-form" class="login-card">', '<form id="login-form" class="login-card">\n      '
                        '<p class="notice cc-demo-signin">Demo: no password is needed, just press Sign in. Never type a real password here.</p>', 1)
    if re.search(r'(?:src|href)="/(?!/)', page):
        raise BuildError("the demo page still points at the site's root: " + ", ".join(re.findall(r'(?:src|href)="/[^"]*"', page)))
    (dest / "index.html").write_text(page, encoding="utf-8")

    data = {**catalog, **release, "qr": {k: _qr(v) for k, v in DEMO_LINKS.items()}, "links": DEMO_LINKS}
    (dest / "sim" / "catalog-release.js").write_text(
        "\"use strict\";\n// Made by tools/build_website.py from the release the demo shows. Don't edit.\nwindow.CC_DEMO_RELEASE = "
        + json.dumps(data, ensure_ascii=False, indent=None).replace("</", "<\\/") + ";\n", encoding="utf-8")


def check_downloads(output: Path, assets: set[str]) -> list[str]:
    """The homepage's download links whose file the release doesn't have (asked of GitHub by the workflow)."""
    page = (output / "index.html").read_text(encoding="utf-8")
    linked = re.findall(r'href="https://github\.com/silverWRX03/craft-conductor/releases/latest/download/([^"]+)"', page)
    if not linked:
        return ["(no download links on the homepage)"]
    return [name for name in linked if name not in assets]


def build_site(output: Path, source: Path, version: str, channel: str, release_url: str = "", site_url: str = SITE_URL,
               testing: bool = True) -> dict:
    frontend = source / "craft_conductor" / "webui"
    if output.exists() and any(output.iterdir()):
        # Only an earlier build is replaced: a mistyped --output (the checkout itself) is never deleted.
        if (output / ".git").exists() or not (output / "demo" / "version.json").is_file():
            raise BuildError(f"{output} isn't empty and isn't an earlier site build: pick another --output")
        shutil.rmtree(output)
    shutil.copytree(SITE, output, ignore=shutil.ignore_patterns("catalog-release.js", "__pycache__"))
    shutil.copy2(frontend / "icon.png", output / "icon.png")
    for name in ("icon-192.png", "icon-512.png"):
        shutil.copy2(frontend / name, output / "demo" / name)
    if testing:  # the real-world testing dashboard's public data (no notes, testers or evidence)
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "real_world_tests.py"), "publish", "--output", str(output / "testing" / "data")],
                           capture_output=True, text=True, cwd=ROOT)
        if r.returncode != 0:
            raise BuildError("the testing dashboard's data couldn't be made:\n" + r.stdout + r.stderr)
    catalog = release_catalog(source)
    if version not in ("development", catalog["version"]):
        raise BuildError(f"the release is {version} but its source says {catalog['version']}")
    shown = catalog["version"] if version == "development" else version
    release = {"version": shown, "channel": channel, "release_url": release_url, "frontend": "development" if channel == "development" else "release"}
    build_demo(output / "demo" / "app", frontend, catalog, release)
    (output / "demo" / "phone-qr.svg").write_text(_qr(site_url + PHONE_PATH), encoding="utf-8")
    info = {**release, "simulated": True, "phone_url": site_url + PHONE_PATH, "missing": catalog.get("missing", [])}
    (output / "demo" / "version.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    missing = [p for p in REQUIRED if not (output / p).exists() and not (p == "testing/data" and not testing)]
    if missing:
        raise BuildError("the site is missing " + ", ".join(missing))
    return info


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--output", type=Path, default=ROOT / "_site")
    p.add_argument("--source", type=Path, default=ROOT / "src", help="the src/ folder of the release the demo shows")
    p.add_argument("--version", default="development")
    p.add_argument("--channel", choices=["beta", "stable", "development"], default="development")
    p.add_argument("--release-url", default="")
    p.add_argument("--site-url", default=SITE_URL)
    p.add_argument("--no-testing-data", action="store_true", help="leave out the testing dashboard's data (tests)")
    p.add_argument("--release-assets", type=Path, help="GitHub's answer about the release (JSON with assets): every download "
                   "link on the homepage must be one of its files")
    a = p.parse_args()
    try:
        info = build_site(a.output.resolve(), a.source.resolve(), a.version, a.channel, a.release_url, a.site_url, testing=not a.no_testing_data)
        if a.release_assets:
            assets = {x["name"] for x in json.loads(a.release_assets.read_text(encoding="utf-8")).get("assets", [])}
            if gaps := check_downloads(a.output.resolve(), assets):
                raise BuildError(f"the release has no file for these download links: {', '.join(gaps)}")
    except BuildError as e:
        sys.exit(f"build_website: {e}")
    print(f"Built {a.output}: demo of Craft Conductor {info['version']} ({info['channel']})"
          + (f"; parts this release doesn't have: {', '.join(info['missing'])}" if info["missing"] else ""))


if __name__ == "__main__":
    main()
