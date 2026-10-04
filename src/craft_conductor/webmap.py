"""A live web map of the world: BlueMap (3D) or Dynmap, added as a mod or plugin.

Both run their own small web server next to Minecraft (BlueMap on port 8100, Dynmap on 8123), so
the map opens in a browser at http://<this computer>:<port>. Craft Conductor adds the mod from
Modrinth, reads and changes the port in its config file, says whether the map answers, and, for
BlueMap, records the user's OK for it to download Minecraft's own textures from Mojang (BlueMap
won't draw anything until that's given: ``accept-download`` in its core.conf).
"""

from __future__ import annotations

import re
import socket
import threading
import time
from pathlib import Path

from .mods.base import CHANNEL_RANK

MAPS = {
    "bluemap": {"name": "BlueMap", "project": "bluemap", "port": 8100, "key": "port",
                "folders": ("config/bluemap", "plugins/BlueMap"), "file": "webserver.conf"},
    "dynmap": {"name": "Dynmap", "project": "dynmap", "port": 8123, "key": "webserver-port",
               "folders": ("dynmap", "plugins/dynmap"), "file": "configuration.txt"},
}
PLUGIN_LOADERS = {"paper", "purpur", "spigot", "bukkit"}


class WebMapError(ValueError):
    pass


class Availability:
    """Which web maps have a build for a server's loader and Minecraft version, asked of Modrinth.

    One request per map, remembered for a while (and for less time when a lookup failed), so
    opening the World page again and again asks Modrinth nothing. Each answer is True (a build
    the server's release channel accepts), False (none), or None (couldn't ask)."""

    TTL = 900.0    # seconds an answer is kept
    RETRY = 60.0   # ... when a lookup failed: try again soon, but not on every page view

    def __init__(self, ttl: float | None = None, retry: float | None = None):
        self.ttl = self.TTL if ttl is None else ttl
        self.retry = self.RETRY if retry is None else retry
        self._lock = threading.Lock()
        self._cache: dict[tuple, tuple[float, dict[str, bool | None]]] = {}

    def check(self, provider, loaders: tuple[str, ...], minecraft: str | None, channel: str = "release") -> dict[str, bool | None]:
        if not loaders:
            return {kind: False for kind in MAPS}  # vanilla: nothing runs a map
        if not minecraft:
            return {kind: None for kind in MAPS}
        key = (tuple(loaders), minecraft, channel)
        with self._lock:  # (one lookup at a time: simultaneous page loads share its answer)
            hit = self._cache.get(key)
            if hit and time.monotonic() < hit[0]:
                return dict(hit[1])
            found = provider.best_channels([spec["project"] for spec in MAPS.values()], tuple(loaders), minecraft)
            answer: dict[str, bool | None] = {}
            for kind, spec in MAPS.items():
                best = found.get(spec["project"])
                answer[kind] = None if best == "unknown" else (
                    best is not None and CHANNEL_RANK.get(best, 9) <= CHANNEL_RANK.get(channel, 0))
            if len(self._cache) >= 16:  # (the version and loader come from the server's own settings)
                self._cache.clear()
            self._cache[key] = (time.monotonic() + (self.retry if None in answer.values() else self.ttl), answer)
            return dict(answer)


def installed(mods) -> str | None:
    """Which web map the server has (from its mod list), if any."""
    for m in mods:
        name = " ".join(str(getattr(m, a, "") or "") for a in ("name", "id", "key", "filename")).lower()
        for kind in MAPS:
            if kind in name:
                return kind
    return None


def _folder(server_dir: Path, kind: str, loader: str | None) -> Path:
    mods_folder, plugins_folder = MAPS[kind]["folders"]
    plugin = (loader or "").lower() in PLUGIN_LOADERS
    first = server_dir / (plugins_folder if plugin else mods_folder)
    other = server_dir / (mods_folder if plugin else plugins_folder)
    return other if not first.exists() and other.exists() else first


def config_file(server_dir: Path, kind: str, loader: str | None) -> Path:
    return _folder(server_dir, kind, loader) / MAPS[kind]["file"]


def _port_line(kind: str) -> re.Pattern:
    return re.compile(rf"^(\s*{re.escape(MAPS[kind]['key'])}\s*[:=]\s*)(\d+)", re.M)


def port(server_dir: Path, kind: str, loader: str | None) -> int:
    try:
        m = _port_line(kind).search(config_file(server_dir, kind, loader).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        m = None
    return int(m.group(2)) if m else MAPS[kind]["port"]


def set_port(server_dir: Path, kind: str, loader: str | None, new: int, taken: set[int] = frozenset()) -> str:
    if not 1024 <= new <= 65535:
        raise WebMapError("the port must be between 1024 and 65535")
    if new in taken:
        raise WebMapError(f"port {new} is already used here")
    path = config_file(server_dir, kind, loader)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise WebMapError(f"{MAPS[kind]['name']} makes its settings the first time the server starts with it: start it once, then change the port") from None
    pattern = _port_line(kind)
    if not pattern.search(text):
        raise WebMapError(f"couldn't find the port in {path.name}")
    path.write_text(pattern.sub(lambda m: f"{m.group(1)}{new}", text, count=1), encoding="utf-8")
    return f"{MAPS[kind]['name']} uses port {new} from the next restart"


ACCEPT = re.compile(r"^(\s*accept-download\s*:\s*)(true|false)", re.M)


def download_accepted(server_dir: Path, loader: str | None) -> bool | None:
    """BlueMap only: None until its core.conf exists (the first start with it makes it)."""
    try:
        m = ACCEPT.search((_folder(server_dir, "bluemap", loader) / "core.conf").read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    return bool(m and m.group(2) == "true")


def accept_download(server_dir: Path, loader: str | None) -> None:
    path = _folder(server_dir, "bluemap", loader) / "core.conf"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise WebMapError("BlueMap makes its settings the first time the server starts with it: start it once, then try again") from None
    if not ACCEPT.search(text):
        raise WebMapError("couldn't find accept-download in BlueMap's core.conf")
    path.write_text(ACCEPT.sub(lambda m: m.group(1) + "true", text, count=1), encoding="utf-8")


def answers(port_: int, timeout: float = 0.3) -> bool:
    """Whether something listens on the map's port on this computer."""
    try:
        with socket.create_connection(("127.0.0.1", port_), timeout=timeout):
            return True
    except OSError:
        return False
