"""Mod conflict memory: combinations that failed together, shared anonymously if you opt in.

When "Find which mods break it" finds a mod that doesn't work (alone, or with the mods its crash
names), Craft Conductor can send that to Craft Conductor's relay (relay/worker.js, a Cloudflare
Worker): only the loader, the Minecraft version and mod ids. Nothing about you or your server.
The relay lists a conflict once several different people have reported it, and every Craft
Conductor reads that list (at most once a day) to warn before those mods are used together.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

# Craft Conductor's relay; CRAFT_CONDUCTOR_CONFLICTS_URL points elsewhere (or "off"). Empty until it's set up.
RELAY = ""
FILE = "known-conflicts.json"
REFRESH = 86400
ID = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")
VERSION = re.compile(r"\d+\.\d+(\.\d+)?(-[a-z0-9.]{1,20})?")
LOADERS = ("fabric", "quilt", "neoforge", "forge", "paper", "purpur")


def relay_url() -> str:
    url = os.environ.get("CRAFT_CONDUCTOR_CONFLICTS_URL", RELAY).strip().rstrip("/")
    return "" if url == "off" or not url.startswith("https://") else url


def reports_for(loader: str, minecraft: str, result: dict) -> list[dict]:
    """What a finished "Find which mods break it" would share: one report per mod that didn't
    work, with the other tested mods its crash named (ids only)."""
    loader, minecraft = (loader or "").lower(), (minecraft or "").lower()
    if loader not in LOADERS or not VERSION.fullmatch(minecraft) or not result.get("bisected"):
        return []
    working = {str(x).lower() for x in result.get("working", [])}
    out = []
    for o in result.get("outliers", [])[:10]:
        mod = str(o.get("id", "")).lower()
        if o.get("source", "modrinth") != "modrinth" or not ID.fullmatch(mod):
            continue
        partners = sorted({str(x).lower() for x in o.get("suspect_ids", [])} & working - {mod})[:4]
        out.append({"loader": loader, "minecraft": minecraft, "mod": mod, "with": partners})
    return out


def share(http, reports: list[dict]) -> int:
    """Send reports to the relay (in the background's thread); returns how many went."""
    url = relay_url()
    sent = 0
    for r in reports if url else []:
        try:
            http.post_json(f"{url}/report", r)
            sent += 1
        except Exception as e:  # (sharing is a courtesy: never let it get in the way)
            log.debug("couldn't share a mod conflict: %s", e)
    if sent:
        log.info("shared %d mod conflict(s) anonymously", sent)
    return sent


class Known:
    """The shared list, kept in the Craft Conductor folder and refreshed at most once a day."""

    def __init__(self, state_dir: Path, http):
        self.path = state_dir / FILE
        self.http = http
        self._lock = threading.Lock()
        self._items: list[dict] | None = None
        self._fetching = False

    def _load(self) -> list[dict]:
        if self._items is None:
            try:
                data = json.loads(self.path.read_text())
                self._items = [c for c in data.get("conflicts", []) if isinstance(c, dict)]
            except (OSError, ValueError, AttributeError):
                self._items = []
        return self._items

    def _stale(self) -> bool:
        try:
            return time.time() - self.path.stat().st_mtime > REFRESH
        except OSError:
            return True

    def refresh(self) -> None:
        url = relay_url()
        if not url:
            return
        try:
            data = self.http.get_json(f"{url}/conflicts.json", cache=False)
            items = [c for c in data.get("conflicts", []) if isinstance(c, dict)][:20000]
        except Exception as e:
            log.debug("couldn't fetch the shared mod conflicts: %s", e)
            items = None
        with self._lock:
            if items is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps({"fetched": time.time(), "conflicts": items}))
                os.replace(tmp, self.path)
                self._items = items
            else:
                try:
                    self.path.touch()  # (try again tomorrow, not on every page)
                except OSError:
                    pass
            self._fetching = False

    def matching(self, loader: str, minecraft: str, mod_ids) -> list[dict]:
        """Known conflicts among these mods (on this loader and Minecraft version). Starts a
        refresh in the background when the list is a day old."""
        if relay_url() and self._stale():
            with self._lock:
                start, self._fetching = not self._fetching, True
            if start:
                threading.Thread(target=self.refresh, daemon=True, name="conflicts").start()
        ids = {str(x).lower() for x in mod_ids}
        with self._lock:
            items = list(self._load())
        return [c for c in items
                if c.get("loader") == (loader or "").lower() and c.get("minecraft") == (minecraft or "").lower()
                and c.get("mod") in ids and all(w in ids for w in c.get("with") or [])]
