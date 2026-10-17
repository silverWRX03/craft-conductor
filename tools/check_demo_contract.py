#!/usr/bin/env python3
"""Detect additions to Craft Conductor's production router without silently losing coverage."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
text = (ROOT / "src/craft_conductor/webui/app.js").read_text(encoding="utf8")
spec = (ROOT / "docs/website-demo-spec.md").read_text(encoding="utf8")

server_match = re.search(r"const SERVER_VIEWS\s*=\s*\[(.*?)\];", text, re.S)
if not server_match:
    raise SystemExit("Cannot find SERVER_VIEWS in production app.js")
actual = re.findall(r'\[\s*"([a-z-]+)"\s*,\s*"[^"]+"\s*\]', server_match.group(1))
expected = ["dashboard", "console", "players", "updates", "mods", "friends", "backups", "java", "settings"]
if actual != expected:
    raise SystemExit(f"Production route list changed. Update demo screen/API fixtures and coverage manifest. Expected {expected!r}; found {actual!r}")
for view in ["Servers", "New server", "Dashboard", "Console", "Players", "Updates", "Mods", "Friends", "Backups", "Java", "Settings", "Help", "manual"]:
    if view.lower() not in spec.lower():
        raise SystemExit(f"Missing documented demo coverage for {view}")
print(f"Production router contract: {len(actual)} server views recognized; documented global views present.")
