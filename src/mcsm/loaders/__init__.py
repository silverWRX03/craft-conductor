from __future__ import annotations

from ..http import HttpClient
from ..minecraft import Mojang
from ..mods.modrinth import PLUGIN_LOADERS  # Modrinth loaders for server plugins
from .base import Loader, LoaderError, Runtime
from .fabric import FabricLoader, QuiltLoader
from .forge import ForgeLoader, NeoForgeLoader
from .paper import PaperLoader
from .purpur import PurpurLoader
from .vanilla import VanillaLoader

LOADERS: dict[str, type[Loader]] = {
    cls.name: cls for cls in (FabricLoader, QuiltLoader, NeoForgeLoader, ForgeLoader, PaperLoader, PurpurLoader, VanillaLoader)
}


# Servers that run plugins (in plugins/) rather than mods; players join with plain Minecraft.
PLUGIN_SERVERS = ("paper", "purpur")


def runs_plugins(loader: str) -> bool:
    return loader in PLUGIN_SERVERS


def mods_folder(loader: str) -> str:
    return LOADERS[loader].mods_folder if loader in LOADERS else "mods"


def get_loader(name: str, http: HttpClient, mojang: Mojang) -> Loader:
    return LOADERS[name](http, mojang)


__all__ = ["Loader", "LoaderError", "Runtime", "LOADERS", "PLUGIN_LOADERS", "PLUGIN_SERVERS", "runs_plugins", "get_loader", "mods_folder"]
