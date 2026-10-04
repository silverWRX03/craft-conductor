"""NeoForge and Forge (1.17+, which use the ``@args`` launch files)."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from ..http import HttpError
from .base import Loader, LoaderError, Runtime, args_file_name, run_installer, version_key

NEOFORGE_MAVEN = "https://maven.neoforged.net/releases/net/neoforged/neoforge"
NEOFORGE_VERSIONS = "https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge"
FORGE_MAVEN = "https://maven.minecraftforge.net/net/minecraftforge/forge"
FORGE_PROMOS = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"

log = logging.getLogger(__name__)

# Everything the installers create that belongs to the loader, not the world.
INSTALLER_FILES = ["libraries", "run.sh", "run.bat"]

# NeoForge has published thousands of builds since 2023. A list shorter than this is NeoForge's
# site having trouble (on 2026-09-28 both of its lists held only "26.3.0.33-beta" for hours),
# not every older Minecraft version losing its builds.
INCOMPLETE_LIST = 50
# What a NeoForge version looks like (21.1.77, 26.3.0.33-beta). Versions go into download
# addresses and file paths, so anything else in its lists is ignored.
_VERSION = re.compile(r"\d{1,4}(?:\.\d{1,6}){1,4}(?:-[0-9A-Za-z.]{1,20})?")


def neoforge_prefix(minecraft: str) -> str:
    """NeoForge versions encode the Minecraft version: 1.21.1 -> 21.1.x, 1.21 -> 21.0.x, 26.1 -> 26.1.x."""
    parts = minecraft.split(".")
    if parts[0] == "1":
        major = parts[1]
        minor = parts[2] if len(parts) > 2 else "0"
        return f"{major}.{minor}."
    return f"{minecraft}."


class NeoForgeLoader(Loader):
    name = "neoforge"
    mod_loaders = ("neoforge",)

    def _api_versions(self) -> list[str]:
        try:
            return [str(v) for v in self.http.get_json(NEOFORGE_VERSIONS)["versions"] if _VERSION.fullmatch(str(v))]
        except (HttpError, KeyError, TypeError, ValueError) as e:
            log.debug("NeoForge's version list didn't answer (%s)", e)
            return []

    def _maven_versions(self) -> list[str]:
        # The full list is large and an update check asks about many Minecraft versions, so it's
        # kept as long as the HTTP client keeps its other answers.
        cached = getattr(self, "_maven", None)
        if cached and time.monotonic() - cached[0] < getattr(self.http, "cache_ttl", 300.0):
            return cached[1]
        text = self.http.get_text(f"{NEOFORGE_MAVEN}/maven-metadata.xml", limit=4 << 20)
        versions = [v for v in re.findall(r"<version>([^<]{1,40})</version>", text) if _VERSION.fullmatch(v)]
        self._maven = (time.monotonic(), versions)
        return versions

    def latest_version(self, minecraft: str) -> str | None:
        prefix = neoforge_prefix(minecraft)

        def pick(versions):
            found = [v for v in versions if v.startswith(prefix) and "-" not in v]
            return max(found, key=version_key) if found else None

        def fetch():
            # NeoForge's API, then (when it doesn't answer, or leaves older builds out) the full
            # list in its maven-metadata.xml.
            return pick(self._api_versions()) or pick(self._maven_versions())
        return self._safe_latest(fetch)

    def missing_reason(self, minecraft: str) -> str | None:
        listed = set(self._api_versions())
        try:
            listed.update(self._maven_versions())
        except HttpError:
            pass
        if len(listed) >= INCOMPLETE_LIST or any(v.startswith(neoforge_prefix(minecraft)) for v in listed):
            return None
        if not listed:
            return "NeoForge's download site didn't give its list of builds just now: try again later"
        return (f"NeoForge's download site lists only {len(listed)} build{'' if len(listed) == 1 else 's'} right "
                f"now, none for Minecraft {minecraft}. Its list is incomplete, which is a problem on NeoForge's "
                "side that usually clears up within hours: try again later")

    def install(self, minecraft: str, version: str, dest: Path, java: str) -> Runtime:
        jar = dest / "neoforge-installer.jar"
        self.http.download(f"{NEOFORGE_MAVEN}/{version}/neoforge-{version}-installer.jar", jar)
        run_installer(java, jar, ["--installServer"], cwd=dest)
        args = f"libraries/net/neoforged/neoforge/{version}/{args_file_name()}"
        if not (dest / args).exists():
            raise LoaderError(f"NeoForge installer did not produce {args}")
        return Runtime(files=list(INSTALLER_FILES), launch=[f"@{args}", "nogui"])


class ForgeLoader(Loader):
    name = "forge"
    mod_loaders = ("forge",)

    def latest_version(self, minecraft: str) -> str | None:
        def fetch():
            promos = self.http.get_json(FORGE_PROMOS)["promos"]
            return promos.get(f"{minecraft}-recommended") or promos.get(f"{minecraft}-latest")
        return self._safe_latest(fetch)

    def install(self, minecraft: str, version: str, dest: Path, java: str) -> Runtime:
        full = f"{minecraft}-{version}"
        jar = dest / "forge-installer.jar"
        self.http.download(f"{FORGE_MAVEN}/{full}/forge-{full}-installer.jar", jar)
        run_installer(java, jar, ["--installServer"], cwd=dest)
        args = f"libraries/net/minecraftforge/forge/{full}/{args_file_name()}"
        if not (dest / args).exists():
            raise LoaderError(f"Forge installer did not produce {args} (only Minecraft 1.17+ is supported)")
        return Runtime(files=list(INSTALLER_FILES), launch=[f"@{args}", "nogui"])
