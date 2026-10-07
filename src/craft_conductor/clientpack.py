"""What a friend's Minecraft needs to join a server: the "client pack".

The pack is a small JSON description (Minecraft and loader version, the server's
address, and a download link and hash for every mod a player needs). The friend's
copy of craft-conductor (`craft-conductor join`, see join.py) fetches it from the share server and sets up
an installation in their own Minecraft Launcher. Nothing is redistributed: every mod
is downloaded by the player straight from Modrinth or CurseForge.

Which mods go in: every mod the server runs that also runs on clients (Modrinth's
``client_side`` isn't "unsupported"; CurseForge doesn't say, so those are included),
plus client-only extras the server's admin picked (a minimap, JEI, Sodium ...) and
their required dependencies, and a CurseForge modpack's mods that only run on players' computers
(``curseforge:<id>`` entries; the pack lists their dependencies itself).
"""

from __future__ import annotations

import base64
import logging
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlparse

from .config import DEFAULT_LINK_DAYS, LINK_DAYS, ConfigError, ModSpec
from .http import HttpError, sha1_file
from .mods.base import ModError, ModFile, Unavailable
from .mods.modrinth import ModrinthProvider

log = logging.getLogger(__name__)

FORMAT = 1
# Where a pack may send players' downloads (HTTPS only). Anything else is refused on
# both ends, so a tampered pack can't point players at arbitrary files.
DOWNLOAD_HOSTS = ("cdn.modrinth.com", "edge.forgecdn.net", "mediafilez.forgecdn.net")
CACHE_SECONDS = 300
CLIENT_DIR = "client-mods"  # next to craft-conductor.toml: your own .jar files for players
LOCAL_URL = "local:"        # in a pack: served by the share server (share.py fills in the address)
JAR_NAME = re.compile(r"[A-Za-z0-9 ()\[\]+_.,'-]{1,120}\.jar")


def client_dir(config) -> Path:
    return config.root / CLIENT_DIR


def local_jars(config) -> list[Path]:
    """Your own mod files for players, from the client-mods folder."""
    folder = client_dir(config)
    return sorted(p for p in folder.glob("*.jar") if JAR_NAME.fullmatch(p.name) and p.is_file()) if folder.is_dir() else []


def new_token() -> str:
    return secrets.token_urlsafe(18)


# A friends' invite link is shared (in a Discord channel, a group chat), so it's not single-use:
# everyone with it can set up. Instead it stops working after the time the owner picked (7 days
# unless they choose otherwise), and the owner can stop it, or replace it, whenever they like.
def checked_link_days(days) -> int:
    try:
        days = int(days)
    except (TypeError, ValueError):
        raise ConfigError("pick how long the links work") from None
    if days not in LINK_DAYS:
        raise ConfigError("pick how long the links work: 1, 7 or 30 days, or until you make new ones")
    return days


def link_expiry(days: int, now: float | None = None) -> int:
    """When a link made (or renewed) now stops working; 0 = until a new one is made."""
    return int((time.time() if now is None else now) + days * 86400) if days else 0


def make_link(config_path: Path, days: int = DEFAULT_LINK_DAYS, now: float | None = None) -> None:
    """A new invite link (the previous one stops working at once), working for ``days``."""
    from . import config as configmod
    days = checked_link_days(days)
    configmod.set_value(config_path, "client", "token", f'"{new_token()}"')
    configmod.set_value(config_path, "client", "link_days", str(days))
    configmod.set_value(config_path, "client", "expires", str(link_expiry(days, now)))


def renew_link(config_path: Path, days: int, now: float | None = None) -> None:
    """Keep the link, working for ``days`` from now (or until a new one is made)."""
    from . import config as configmod
    days = checked_link_days(days)
    configmod.set_value(config_path, "client", "link_days", str(days))
    configmod.set_value(config_path, "client", "expires", str(link_expiry(days, now)))


def stop_link(config_path: Path, now: float | None = None) -> None:
    """The link stops working now (friends who already set up keep playing)."""
    from . import config as configmod
    configmod.set_value(config_path, "client", "expires", str(max(1, int(time.time() if now is None else now))))


def allowed_url(url: str) -> bool:
    u = urlparse(url)
    return u.scheme == "https" and u.hostname in DOWNLOAD_HOSTS


def _entry(m: ModFile, side: str) -> dict:
    return {"name": m.name, "filename": m.filename, "url": m.url, "sha1": m.sha1, "sha512": m.sha512,
            "project": m.key, "source": m.source, "version": m.version_number, "channel": m.channel, "side": side}


class PackBuilder:
    def __init__(self, manager):
        self.m = manager
        self._cache: dict[str, tuple[tuple, float, dict]] = {}  # by address: local and internet friends differ

    def build(self, address: str) -> dict:
        m = self.m
        lk, cfg = m.lock, m.config
        if not lk.installed:
            raise ModError("the server isn't installed yet")
        key = (lk.updated_at, lk.minecraft, tuple(cfg.client.mods), cfg.client.memory_gb, address,
               cfg.server.dir, tuple((p.name, p.stat().st_mtime) for p in local_jars(cfg)))
        cached = self._cache.get(address)
        if cached and cached[0] == key and time.monotonic() - cached[1] < CACHE_SECONDS:
            return cached[2]
        pack = self._build(address)
        if len(self._cache) >= 8:  # addresses come from requests: keep only a few
            self._cache.clear()
        self._cache[address] = (key, time.monotonic(), pack)
        return pack

    def _build(self, address: str) -> dict:
        m = self.m
        lk, cfg = m.lock, m.config
        modrinth = m.providers.get("modrinth") or ModrinthProvider(m.http)
        # Paper's plugins only run on the server: players join with plain Minecraft.
        plugins = m.loader.mods_folder != "mods"
        loaders = () if plugins else m.loader.mod_loaders
        mods: list[dict] = []
        manual: list[dict] = []
        skipped: list[dict] = []
        included: set[str] = set()

        # The server's own mods, unless they only run on servers.
        sides = {}
        ids = [x.project_id for x in lk.mods if x.source == "modrinth" and not plugins]
        if ids:
            try:
                sides = {pid: p.get("client_side", "unknown") for pid, p in modrinth.projects(ids).items()}
            except Exception as e:  # can't tell: include them all (a spare server mod is harmless)
                log.warning("couldn't look up which mods players need (%s); including all of them", e)
        for x in ([] if plugins else lk.mods):
            if x.source == "modrinth" and sides.get(x.project_id) == "unsupported":
                continue
            included.add(x.key)
            if x.manual or not allowed_url(x.url):
                manual.append({"name": x.name, "filename": x.filename, "url": x.manual_url or x.url, "sha1": x.sha1})
            else:
                mods.append(_entry(x, "both"))

        # Mods the server's mods need on players' computers only (the server skips those),
        # then the extras you picked for players; each with its required dependencies.
        names = {x.key: x.name for x in lk.mods}
        todo = [ModSpec("modrinth", dep, dependency_of=names.get(x.key, x.name))
                for x in ([] if plugins else lk.mods) if x.source == "modrinth"
                for dep in x.dependencies if f"modrinth:{dep}" not in included]
        todo += [ModSpec("modrinth", slug) for slug in cfg.client.mods if not slug.startswith("curseforge:")]
        while todo and loaders:
            spec = todo.pop(0)
            try:
                f = modrinth.resolve(spec, lk.minecraft, loaders, cfg.updates.mod_channel, side="client")
            except (Unavailable, ModError) as e:
                if spec.dependency_of is None:
                    skipped.append({"name": spec.id, "reason": str(e)})
                continue
            if f.key in included:
                continue
            included.add(f.key)
            entry = _entry(f, "client")
            if spec.dependency_of:
                entry["needed_by"] = spec.dependency_of  # a companion another mod needs
            (mods if allowed_url(f.url) else manual).append(entry)
            todo += [ModSpec("modrinth", dep, dependency_of=f.name) for dep in f.dependencies
                     if f"modrinth:{dep}" not in included]

        # A CurseForge modpack's mods for players' computers only.
        curseforge = m.providers.get("curseforge")
        for item in cfg.client.mods if loaders else []:
            if not item.startswith("curseforge:"):
                continue
            spec = ModSpec("curseforge", item.split(":", 1)[1])
            try:
                if curseforge is None:
                    raise ModError("CurseForge mods need a CurseForge API key")
                f = curseforge.resolve(spec, lk.minecraft, loaders, cfg.updates.mod_channel)
            except (Unavailable, ModError, HttpError) as e:
                skipped.append({"name": item, "reason": str(e)})
                continue
            if f.key in included:
                continue
            included.add(f.key)
            if f.manual or not allowed_url(f.url):
                manual.append({"name": f.name, "filename": f.filename, "url": f.manual_url or f.url, "sha1": f.sha1})
            else:
                mods.append(_entry(f, "client"))

        # Your own files for players (the share server hands them out).
        for jar in ([] if plugins else local_jars(cfg)):
            mods.append({"name": jar.stem, "filename": jar.name, "url": LOCAL_URL + jar.name, "sha1": sha1_file(jar),
                         "sha512": None, "project": f"local:{jar.name}", "side": "client", "local": True})

        from .properties import read_properties
        props = read_properties(m.server_dir / "server.properties")
        icon = m.server_dir / "server-icon.png"
        return {
            "format": FORMAT,
            "name": props.get("motd") or cfg.root.name,
            "minecraft": lk.minecraft,
            "loader": "vanilla" if plugins else lk.loader,
            "loader_version": None if plugins else lk.loader_version,
            "java_major": lk.java_major,
            "address": address,
            "memory_gb": cfg.client.memory_gb,
            "mods": mods,
            "manual": manual,
            "skipped": skipped,
            "icon": ("data:image/png;base64," + base64.b64encode(icon.read_bytes()).decode())
                    if icon.is_file() and icon.stat().st_size < 64 * 1024 else None,
            "updated": lk.updated_at,
        }
