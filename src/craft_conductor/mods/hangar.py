"""Hangar (hangar.papermc.io), PaperMC's own plugin site - for Paper servers, next to Modrinth.

API v1 (no key needed): projects by slug, their versions per platform (PAPER) with the
Minecraft versions each supports (single versions or ranges like ``1.20-1.21.4``), the file's
SHA-256, and the plugins it needs. Plugins whose files are hosted elsewhere (an external link)
are treated like CurseForge's blocked downloads: craft-conductor gives the link, you download it.
"""

from __future__ import annotations

import re

from ..config import ModSpec
from ..http import HttpClient, HttpError
from .base import CHANNEL_RANK, ModError, ModFile, ModProvider, Project, Unavailable

API = "https://hangar.papermc.io/api/v1"
WEBSITE = "https://hangar.papermc.io"
PLATFORM = "PAPER"
SLUG = re.compile(r"[A-Za-z0-9_.-]{1,100}")
_NUM = re.compile(r"\d+")


def _key(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in _NUM.findall(version)[:4])


def supports(minecraft: str, spec: str) -> bool:
    """Whether a Hangar platform version ("1.21", "1.20.4", "1.20-1.21.4") covers ``minecraft``."""
    spec = spec.strip()
    if "-" in spec:
        lo, hi = (s.strip() for s in spec.split("-", 1))
        mk = _key(minecraft)
        # "1.20-1.21" also covers 1.21.x: compare only as many parts as the upper end names
        return _key(lo) <= mk and mk[:len(_key(hi))] <= _key(hi)
    return minecraft == spec or (len(_key(spec)) == 2 and _key(minecraft)[:2] == _key(spec))


class VersionSet(set):
    """The Minecraft versions a plugin has builds for, ranges included (``in`` checks them)."""

    def __init__(self, specs):
        super().__init__(specs)

    def __contains__(self, minecraft) -> bool:
        return any(supports(str(minecraft), s) for s in set.__iter__(self))


def _channel(name: str) -> str:
    n = (name or "").lower()
    return "release" if n == "release" else "alpha" if n in ("alpha", "snapshot", "dev") else "beta"


class HangarProvider(ModProvider):
    source = "hangar"

    def __init__(self, http: HttpClient):
        self.http = http

    def project(self, mod_id: str) -> Project:
        if not SLUG.fullmatch(mod_id):
            raise ModError(f"{mod_id!r} isn't a Hangar project")
        try:
            p = self.http.get_json(f"{API}/projects/{mod_id}")
        except HttpError as e:
            if e.status == 404:
                raise ModError(f"no Hangar plugin called {mod_id!r}") from e
            raise
        slug = str((p.get("namespace") or {}).get("slug") or p.get("name") or mod_id)
        return Project("hangar", slug, slug, str(p.get("name") or slug), server_side="required", client_side="unsupported")

    def _versions(self, slug: str) -> list[dict]:
        data = self.http.get_json(f"{API}/projects/{slug}/versions", params={"limit": 50, "offset": 0, "platform": PLATFORM})
        return [v for v in data.get("result", []) if (v.get("downloads") or {}).get(PLATFORM)]

    def resolve(self, spec: ModSpec, minecraft: str, loaders: tuple[str, ...], channel: str) -> ModFile:
        project = self.project(spec.id)
        allowed = CHANNEL_RANK[spec.channel or channel]
        for v in self._versions(project.slug):  # newest first
            if CHANNEL_RANK[_channel((v.get("channel") or {}).get("name", ""))] > allowed:
                continue
            if not any(supports(minecraft, s) for s in (v.get("platformDependencies") or {}).get(PLATFORM, [])):
                continue
            dl = v["downloads"][PLATFORM]
            info = dl.get("fileInfo") or {}
            deps = [str(d["name"]) for d in (v.get("pluginDependencies") or {}).get(PLATFORM, [])
                    if d.get("required") and not d.get("externalUrl") and SLUG.fullmatch(str(d.get("name", "")))]
            name = str(info.get("name") or f"{project.slug}-{v.get('name')}.jar")
            if not re.fullmatch(r"[^/\\:*?\"<>|]{1,200}\.jar", name):
                raise ModError(f"{project.name}: an odd file name ({name!r})")
            external = dl.get("externalUrl")
            return ModFile(
                key=project.key, source="hangar", project_id=project.slug, name=project.name,
                version_id=str(v.get("id") or v.get("name")), version_number=str(v.get("name", "")),
                filename=name, url=str(dl.get("downloadUrl") or ""), sha256=info.get("sha256Hash"),
                dependencies=deps, required=spec.required,
                channel=_channel((v.get("channel") or {}).get("name", "")),
                manual_url=f"{WEBSITE}/{(project.slug)}" if external or not dl.get("downloadUrl") else None)
        raise Unavailable(f"{project.name} has no Paper build for Minecraft {minecraft}")

    def supported_versions(self, spec: ModSpec, loaders: tuple[str, ...], channel: str) -> set[str]:
        allowed = CHANNEL_RANK[spec.channel or channel]
        specs = set()
        for v in self._versions(self.project(spec.id).slug):
            if CHANNEL_RANK[_channel((v.get("channel") or {}).get("name", ""))] <= allowed:
                specs.update((v.get("platformDependencies") or {}).get(PLATFORM, []))
        return VersionSet(specs)

    def search(self, query: str, minecraft: str | None = None, limit: int = 20, sort: str = "-downloads") -> list[dict]:
        params = {"q": query, "limit": limit, "offset": 0, "platform": PLATFORM, "sort": sort}
        if minecraft:
            params["version"] = minecraft
        data = self.http.get_json(f"{API}/projects", params=params)
        out = []
        for p in data.get("result", []):
            slug = str((p.get("namespace") or {}).get("slug") or p.get("name", ""))
            out.append({"source": "hangar", "id": slug, "slug": slug, "name": p.get("name", slug),
                        "description": p.get("description", ""), "icon": p.get("avatarUrl") or "",
                        "downloads": (p.get("stats") or {}).get("downloads", 0),
                        "url": f"{WEBSITE}/{(p.get('namespace') or {}).get('owner', '')}/{slug}"})
        return out
