from __future__ import annotations

from ..config import Config
from ..http import HttpClient
from .base import ModError, ModFile, ModProvider, Project, Unavailable
from .curseforge import CurseForgeProvider
from .hangar import HangarProvider
from .modrinth import ModrinthProvider


def providers_for(config: Config, http: HttpClient) -> dict[str, ModProvider]:
    out = {
        "modrinth": ModrinthProvider(http),
        "curseforge": CurseForgeProvider(http, config.curseforge_api_key),
        "hangar": HangarProvider(http),
    }
    hold(out, config.pins)
    return out


def hold(providers: dict[str, ModProvider], pins: dict) -> None:
    """The mods held at one build (config.Pin by "source:project id"), for each site."""
    for p in providers.values():
        p.pins = {k: v for k, v in pins.items() if k.startswith(p.source + ":")}


__all__ = ["ModError", "ModFile", "ModProvider", "Project", "Unavailable", "providers_for", "hold",
           "ModrinthProvider", "CurseForgeProvider", "HangarProvider"]
