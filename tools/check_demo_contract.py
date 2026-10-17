#!/usr/bin/env python3
"""Does the website demo's simulation answer everything a control panel asks for?

    python tools/check_demo_contract.py                                  # this checkout's panel
    python tools/check_demo_contract.py --app <release>/src/craft_conductor/webui/app.js

Every /api/ address the panel's script names must have a route in site/demo/app/sim/routes-*.js (by
any method). The Pages workflow runs it on the release the demo will show, before it's built: a
release whose panel calls something new isn't published until the simulation answers it (the demo
would show "isn't simulated" on that page). tests/test_website_demo_contract.py checks the answers'
shapes against the real backend; the website's browser tests go through the pages themselves.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "site" / "demo" / "app" / "sim"
APP = ROOT / "src" / "craft_conductor" / "webui" / "app.js"
# /api/server/start, stop and restart: the card's buttons make them with ${action}.
MADE_UP_PARTS = {"/api/server"}


def app_paths(app_js: str) -> set[str]:
    """Every API address the control panel's script names (a ${...} part ends it; queries are left off)."""
    found = set()
    for raw in re.findall(r'"(/api/[^"\n]*)"|`(/api/[^`\n]*)`', app_js):
        text = raw[0] or raw[1]
        while "${" in text:  # (a ${...} part, with any brackets inside it, stands for one value)
            start = text.index("${")
            depth, end = 0, len(text) - 1
            for i in range(start + 1, len(text)):
                depth += {"{": 1, "}": -1}.get(text[i], 0)
                if depth == 0:
                    end = i
                    break
            text = text[:start] + "\0" + text[end + 1:]
        p = re.sub(r"^/api/servers/\0/", "/api/", text.split("?")[0]).rstrip("/")
        p = p.split("\0")[0].rstrip("/")  # (/api/hub/phone${...}: the address before the value)
        if p not in ("/api", "/api/servers"):
            found.add(p)
    return found


def demo_paths(sim: Path = SIM) -> set[str]:
    """The addresses the simulation has a route for."""
    keys = set()
    for f in sim.glob("routes-*.js"):
        keys |= set(re.findall(r'"(?:GET|POST) (/api/[^"]+)"', f.read_text(encoding="utf-8")))
    return keys


def missing(app_js: str, sim: Path = SIM) -> list[str]:
    known = demo_paths(sim)
    return sorted(p for p in app_paths(app_js) if p not in known and p not in MADE_UP_PARTS
                  and not any(k.startswith(p + "/") for k in known))


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    a.add_argument("--app", type=Path, default=APP, help="the control panel's app.js")
    args = a.parse_args()
    text = args.app.read_text(encoding="utf-8")
    gaps = missing(text)
    if gaps:
        sys.exit("check_demo_contract: the website demo doesn't answer these addresses the control panel uses:\n  "
                 + "\n  ".join(gaps) + "\nAdd them to site/demo/app/sim/routes-*.js (see docs/website.md).")
    print(f"check_demo_contract: all {len(app_paths(text))} API addresses the control panel uses are simulated.")


if __name__ == "__main__":
    main()
