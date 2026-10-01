from __future__ import annotations

import hashlib
from pathlib import Path

from ..http import HttpError
from .base import LoaderError, Runtime
from .paper import PaperLoader

API = "https://api.purpurmc.org/v2/purpur"
JAR = "purpur.jar"


class PurpurLoader(PaperLoader):
    """Purpur: Paper with many more settings to tweak gameplay (``purpur.yml``). Runs the same
    plugins as Paper, from ``plugins/``.

    Builds come from Purpur's API; only builds that succeeded are used. The loader "version" is
    the build number.
    """
    name = "purpur"
    #: Modrinth loaders for plugins Purpur runs (Paper's too)
    mod_loaders = ("purpur", "paper", "spigot", "bukkit")
    mods_folder = "plugins"

    def _build_numbers(self, minecraft: str) -> list[str]:
        """Build numbers for a Minecraft version, newest first (empty when Purpur doesn't have it)."""
        try:
            data = self.http.get_json(f"{API}/{minecraft}")
        except HttpError as e:
            if e.status == 404:
                return []
            raise
        builds = (data.get("builds") or {}).get("all") or [] if isinstance(data, dict) else []
        return sorted((str(b) for b in builds if str(b).isdigit()), key=int, reverse=True)

    def _build(self, minecraft: str, build: str) -> dict:
        return self.http.get_json(f"{API}/{minecraft}/{build}")

    def latest_version(self, minecraft: str) -> str | None:
        def fetch():
            for build in self._build_numbers(minecraft)[:5]:  # (the newest that built fine)
                if str(self._build(minecraft, build).get("result", "SUCCESS")).upper() == "SUCCESS":
                    return build
            return None
        return self._safe_latest(fetch)

    def install(self, minecraft: str, version: str, dest: Path, java: str) -> Runtime:
        if not str(version).isdigit():
            raise LoaderError(f"Purpur build {version!r} isn't a build number")
        info = self._build(minecraft, str(version))
        if str(info.get("result", "SUCCESS")).upper() != "SUCCESS":
            raise LoaderError(f"Purpur build {version} for Minecraft {minecraft} didn't build")
        jar = self.http.download(f"{API}/{minecraft}/{version}/download", dest / JAR)
        md5 = str(info.get("md5") or "").lower()
        if md5 and hashlib.md5(jar.read_bytes(), usedforsecurity=False).hexdigest() != md5:
            jar.unlink(missing_ok=True)
            raise LoaderError(f"the Purpur download for build {version} was damaged (checksum differs); try again")
        # Like Paper, Purpur fetches and patches the vanilla server into cache/ on first start.
        return Runtime(files=[JAR], launch=["-jar", JAR, "--nogui"])
