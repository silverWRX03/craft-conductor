from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field

from ..config import ModSpec

CHANNEL_RANK = {"release": 0, "beta": 1, "alpha": 2}

# A mod file's name is whatever its author uploaded, and it becomes a path: in the server's mods
# folder, the folder for manual downloads, and friends' and single-player games. So it must be
# one plain name that means the same file on every system.
_FILE_NAME = re.compile(r"[^/\\:*?\"<>|\x00-\x1f]{1,200}")
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


class ModError(Exception):
    pass


def safe_file_name(name: str) -> bool:
    return (bool(_FILE_NAME.fullmatch(name)) and not name.startswith(".") and not name.endswith((".", " "))
            and name.split(".")[0].rstrip().upper() not in _RESERVED)


@dataclass
class Project:
    source: str
    id: str          # canonical id (slugs can change, ids do not)
    slug: str
    name: str
    server_side: str = "required"  # required | optional | unsupported | unknown
    client_side: str = "required"

    @property
    def key(self) -> str:
        return f"{self.source}:{self.id}"


@dataclass
class ModFile:
    """One concrete mod jar chosen for a Minecraft version."""
    key: str
    source: str
    project_id: str
    name: str
    version_id: str
    version_number: str
    filename: str
    url: str
    sha1: str | None = None
    sha512: str | None = None
    sha256: str | None = None   # (Hangar gives SHA-256)
    #: project ids (same source) this file requires
    dependencies: list[str] = field(default_factory=list)
    required: bool = True
    dependency_of: str | None = None
    #: The actual release channel of this file. Older lock files omit it and default to a release.
    channel: str = "release"
    #: set when the author blocks automatic downloads: a page where a person can download it
    manual_url: str | None = None
    #: a datapack (.zip) for the world's datapacks folder, not a mod for the mods folder
    datapack: bool = False
    #: the craft-conductor.toml entry ("source:id") it's installed for, when it came from the other
    #: site (the mod was picked on Modrinth, which has no build for this Minecraft and loader)
    listed_as: str | None = None

    @property
    def manual(self) -> bool:
        return bool(self.manual_url)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ModFile:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class Unavailable(Exception):
    """The mod has no usable file for this Minecraft version / loader."""


class ClientOnly(Unavailable):
    """The mod does not run on servers; it is skipped rather than treated as a blocker."""


#: How each mod site is named to people
SOURCE_NAMES = {"modrinth": "Modrinth", "curseforge": "CurseForge", "hangar": "Hangar"}
#: The sites a mod's dependency is looked for on, in this order after the site that names it
MOD_SOURCES = ("curseforge", "modrinth")


def not_checked(provider: ModProvider, error: Exception) -> str:
    """For people: a site that couldn't be asked about a mod, and why."""
    name = SOURCE_NAMES.get(provider.source, provider.source)
    if provider.source == "curseforge" and not getattr(provider, "api_key", "?"):
        return f"{name} couldn't be checked: no CurseForge API key (Craft Conductor settings → CurseForge)"
    return f"{name} couldn't be checked: {error}"


def _plain(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def same_project(a: Project, b: Project) -> bool:
    """Whether two projects (on different sites, which share no ids) are the same mod: the
    same name, or the same slug with one name inside the other ("Fabric API" and
    "Fabric API (Fabric)"), ignoring case, spaces and punctuation."""
    na, nb = _plain(a.name), _plain(b.name)
    if not na or not nb:
        return False
    return na == nb or (bool(_plain(a.slug)) and _plain(a.slug) == _plain(b.slug) and (na in nb or nb in na))


class ModProvider(ABC):
    source: str = ""

    @abstractmethod
    def project(self, mod_id: str) -> Project:
        """Look up a project by id or slug."""

    @abstractmethod
    def resolve(self, spec: ModSpec, minecraft: str, loaders: tuple[str, ...], channel: str) -> ModFile:
        """Pick the newest acceptable file, or raise :class:`Unavailable`."""

    @abstractmethod
    def supported_versions(self, spec: ModSpec, loaders: tuple[str, ...], channel: str) -> set[str]:
        """Every Minecraft version the mod has an acceptable file for."""

    def handles(self, loaders: tuple[str, ...]) -> bool:
        """Whether this site has files for any of these loaders at all."""
        return True

    def find_same(self, project: Project) -> Project | None:
        """The same mod as ``project`` (from another site) here, if this site has it: looked
        up by its slug, then by its name. Raises :class:`ModError` when the site can't be asked."""
        return None
