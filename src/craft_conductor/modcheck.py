"""Will these mods start together? The mod loader's own check, done before anyone launches.

Mod sites say which mods a mod needs, but not which versions, and they can be wrong about
which side (server or players' computers) a mod runs on. The files themselves say exactly,
and the loader refuses to start when they disagree ("Incompatible mods found!"). This reads
the same descriptions the loaders read and runs the same checks:

* Fabric: ``fabric.mod.json`` (``depends``, ``breaks``, ``provides``, ``environment``), with the
  mods bundled inside it (``jars``); versions are Fabric's (semantic versions, ``>=1.2``,
  ``~1.2``, ``^1.2``, ``1.2.x``, several of them in one string all apply).
* Forge and NeoForge: ``META-INF/mods.toml`` / ``META-INF/neoforge.mods.toml``
  (``[[dependencies.<mod>]]`` with ``mandatory`` or ``type``, ``versionRange``, ``side``), with the
  mods bundled in ``META-INF/jarjar``; versions and ranges are Maven's (``[1.2,2)``).

When something can't be told (a version that isn't a version, a file that couldn't be read),
it is taken to be fine: a warning that's wrong would be worse than the loader saying so later.
Quilt reads its own descriptions as well as Fabric's and is not checked.
"""

from __future__ import annotations

import io
import json
import logging
import re
import threading
import tomllib
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

LOADERS = ("fabric", "forge", "neoforge")
MAX_ENTRY = 1 << 20          # a description bigger than this isn't read
MAX_NESTED = 64 << 20        # nor a bundled mod bigger than this
MAX_DEPTH = 3                # mods bundled in mods bundled in mods
MAX_FILES = 400              # bundled mods in one file, all levels together
#: Mod ids the loader itself provides (no file says so), with the version they have when it's known.
BUILTIN = {
    "fabric": ("minecraft", "java", "fabricloader", "mixinextras"),
    "forge": ("minecraft", "forge", "fml", "javafml", "lowcodefml", "mcp"),
    "neoforge": ("minecraft", "neoforge", "fml", "javafml", "lowcodefml", "mixinextras"),
}


@dataclass
class Dep:
    id: str
    ranges: list[str]            # Fabric: any one of them; Maven: one range spec
    kind: str = "requires"       # requires | breaks
    side: str = "both"           # both | client | server: where it applies


@dataclass
class ModInfo:
    id: str
    version: str | None
    name: str
    side: str = "both"           # where the loader loads it (Fabric's environment)
    depends: list[Dep] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    file: str = ""

    @staticmethod
    def from_dict(d: dict) -> "ModInfo":
        return ModInfo(**{**d, "depends": [Dep(**x) for x in d.get("depends", [])]})


@dataclass
class Problem:
    kind: str                    # missing | version | breaks | minecraft | loader | java
    mod: str                     # who says so
    mod_id: str
    needs: str                   # the mod id it's about
    text: str
    file: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ reading files
_seen: dict[tuple, list[ModInfo]] = {}   # (path, size, modified, loader) -> what's in it
_seen_lock = threading.Lock()


def read_file(path: Path, loader: str) -> list[ModInfo]:
    """The mods in one file (it and what it bundles). Not a mod file: none. Raises OSError when
    it can't be read at all. A file that hasn't changed isn't read again."""
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns, loader)
    with _seen_lock:
        if key in _seen:
            return _seen[key]
    with open(path, "rb") as f:  # (only the parts that describe mods are read, not the whole file)
        out: list[ModInfo] = []
        _read(f, loader, path.name, out, 0, [MAX_FILES])
    with _seen_lock:
        if len(_seen) >= 4000:
            _seen.clear()
        _seen[key] = out
    return out


def read_bytes(data: bytes, loader: str, name: str) -> list[ModInfo]:
    out: list[ModInfo] = []
    _read(io.BytesIO(data), loader, name, out, 0, [MAX_FILES])
    return out


def _entry(z: zipfile.ZipFile, name: str, limit: int = MAX_ENTRY) -> bytes | None:
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    if info.file_size > limit:
        return None
    return z.read(info)


def _read(source, loader: str, name: str, out: list[ModInfo], depth: int, budget: list[int]) -> None:
    try:
        z = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, EOFError, ValueError):
        return  # not a mod file (the loader skips it too)
    with z:
        try:
            if loader == "fabric":
                nested = _fabric(z, name, out)
            else:
                nested = _forge(z, name, loader, out)
        except (ValueError, TypeError, AttributeError, zipfile.BadZipFile, RuntimeError, OSError) as e:
            log.debug("couldn't read the mod description in %s: %s", name, e)
            return
        if depth >= MAX_DEPTH:
            return
        for inner in nested:
            if budget[0] <= 0:
                return
            budget[0] -= 1
            try:
                blob = _entry(z, inner, MAX_NESTED)
            except (zipfile.BadZipFile, RuntimeError, OSError):
                blob = None
            if blob is not None:
                _read(io.BytesIO(blob), loader, f"{name}/{inner.rsplit('/', 1)[-1]}", out, depth + 1, budget)


def _text(raw: bytes) -> str:
    return raw.decode("utf-8-sig", errors="replace")


def _fabric(z: zipfile.ZipFile, name: str, out: list[ModInfo]) -> list[str]:
    raw = _entry(z, "fabric.mod.json")
    if raw is None:
        return []
    d = json.loads(_text(raw), strict=False)  # (loader-tolerated control characters in strings)
    if not isinstance(d, dict) or not isinstance(d.get("id"), str):
        return []
    env = d.get("environment", "*")
    side = env if env in ("client", "server") else "both"

    def deps(key, kind):
        found = d.get(key) or {}
        result = []
        for dep_id, spec in (found.items() if isinstance(found, dict) else ()):
            ranges = [spec] if isinstance(spec, str) else [s for s in spec if isinstance(s, str)] if isinstance(spec, list) else []
            result.append(Dep(str(dep_id), ranges or ["*"], kind))
        return result

    provides = [p for p in d.get("provides", []) if isinstance(p, str)] if isinstance(d.get("provides"), list) else []
    version = d.get("version")
    out.append(ModInfo(d["id"], version if isinstance(version, str) else None, str(d.get("name") or d["id"]), side,
                       deps("depends", "requires") + deps("breaks", "breaks"), provides, name))
    jars = d.get("jars") if isinstance(d.get("jars"), list) else []
    return [j["file"] for j in jars if isinstance(j, dict) and isinstance(j.get("file"), str)]


_PLACEHOLDER = re.compile(r"\$\{[^}]*\}")


def _manifest_version(z: zipfile.ZipFile) -> str | None:
    raw = _entry(z, "META-INF/MANIFEST.MF")
    for line in _text(raw).splitlines() if raw else ():
        key, _, value = line.partition(":")
        if key.strip() == "Implementation-Version" and value.strip():
            return value.strip()
    return None


def _forge(z: zipfile.ZipFile, name: str, loader: str, out: list[ModInfo]) -> list[str]:
    raw = None
    if loader == "neoforge":
        raw = _entry(z, "META-INF/neoforge.mods.toml")
    if raw is None:
        raw = _entry(z, "META-INF/mods.toml")
    nested: list[str] = []
    jarjar = _entry(z, "META-INF/jarjar/metadata.json")
    if jarjar is not None:
        meta = json.loads(_text(jarjar))
        nested = [j["path"] for j in (meta.get("jars") or []) if isinstance(j, dict) and isinstance(j.get("path"), str)]
    if raw is None:
        return nested
    d = tomllib.loads(_text(raw))
    all_deps = d.get("dependencies") if isinstance(d.get("dependencies"), dict) else {}
    for mod in d.get("mods") or []:
        if not isinstance(mod, dict) or not isinstance(mod.get("modId"), str):
            continue
        version = mod.get("version")
        if isinstance(version, str) and "${file.jarVersion}" in version:
            version = version.replace("${file.jarVersion}", _manifest_version(z) or "${file.jarVersion}")
        if not isinstance(version, str) or _PLACEHOLDER.search(version):
            version = None  # (filled in when the mod is built; nothing to compare with)
        depends = []
        for x in all_deps.get(mod["modId"]) or []:
            if not isinstance(x, dict) or not isinstance(x.get("modId"), str):
                continue
            kind = str(x.get("type", "")).lower()
            if kind == "incompatible":
                kind = "breaks"
            elif kind == "required" or (not kind and x.get("mandatory") is True):
                kind = "requires"
            else:
                continue  # optional, discouraged: the loader starts anyway
            side = str(x.get("side", "BOTH")).lower()
            depends.append(Dep(x["modId"], [str(x.get("versionRange") or "*")], kind,
                               side if side in ("client", "server") else "both"))
        out.append(ModInfo(mod["modId"], version, str(mod.get("displayName") or mod["modId"]), "both", depends, [], name))
    return nested


# ------------------------------------------------------------------ Fabric versions
# ("1.2-": a bare "-" is the lowest pre-release, so that "~26.1-" takes 26.1's pre-releases too)
_SEMVER = re.compile(r"^(\d+(?:\.(?:\d+|[xX*]))*)(?:-([0-9A-Za-z.-]*))?(?:\+[0-9A-Za-z.+-]*)?$")


def fabric_version(text: str):
    """(components, prerelease) of a Fabric semantic version; components may be "x" (any), or
    None when it isn't one (Fabric then only compares it for equality)."""
    m = _SEMVER.match(text.strip())
    if not m:
        return None
    parts = ["x" if p in ("x", "X", "*") else int(p) for p in m.group(1).split(".")]
    if "x" in parts and any(p != "x" for p in parts[parts.index("x"):]):
        return None
    return parts, (m.group(2).split(".") if m.group(2) is not None else [])


def _cmp_pre(a: list[str], b: list[str]) -> int:
    if not a or not b:
        return (not a) - (not b)  # a release is newer than its pre-releases
    for x, y in zip(a, b):
        if x == y:
            continue
        if x.isdigit() and y.isdigit():
            return -1 if int(x) < int(y) else 1
        if x.isdigit() != y.isdigit():
            return -1 if x.isdigit() else 1
        return -1 if x < y else 1
    return (len(a) > len(b)) - (len(a) < len(b))


def _cmp_fabric(a, b) -> int:
    pa, pb = a[0], b[0]
    for i in range(max(len(pa), len(pb))):
        x = pa[i] if i < len(pa) else 0
        y = pb[i] if i < len(pb) else 0
        if x == "x" or y == "x":
            return 0
        if x != y:
            return -1 if x < y else 1
    return _cmp_pre(a[1], b[1])


def _fabric_term(have, term: str) -> bool | None:
    op = next((o for o in (">=", "<=", ">", "<", "=", "~", "^") if term.startswith(o)), "")
    want = fabric_version(term[len(op):])
    if want is None:
        return None
    c = _cmp_fabric(have, want)
    if op in ("", "="):
        return c == 0
    if op == ">=":
        return c >= 0
    if op == "<=":
        return c <= 0
    if op == ">":
        return c > 0
    if op == "<":
        return c < 0
    same = 2 if op == "~" else 1  # ~ keeps major.minor, ^ keeps major
    head = lambda v: [v[0][i] if i < len(v[0]) else 0 for i in range(same)]
    return c >= 0 and head(have) == head(want)


def fabric_matches(version: str, ranges: list[str]) -> bool | None:
    """Whether ``version`` is in any of ``ranges`` (each: terms that all apply). None: can't tell."""
    have = fabric_version(version)
    unknown = False
    for r in ranges:
        terms = r.split()
        if not terms or terms == ["*"]:
            return True
        if have is None:
            if all(t == version for t in terms):
                return True
            unknown = True
            continue
        results = [_fabric_term(have, t) for t in terms]
        if all(x is True for x in results):
            return True
        if None in results and False not in results:
            unknown = True
    return None if unknown else False


# ------------------------------------------------------------------ Maven versions (Forge, NeoForge)
_QUALIFIERS = {"alpha": 1, "a": 1, "beta": 2, "b": 2, "milestone": 3, "m": 3, "rc": 4, "cr": 4,
               "snapshot": 5, "": 6, "ga": 6, "final": 6, "release": 6, "sp": 7}
_ITEM = re.compile(r"\d+|[a-z]+")


def maven_version(text: str) -> list:
    return [int(x) if x.isdigit() else x for x in _ITEM.findall(text.lower())]


def _cmp_item(x, y) -> int:
    if isinstance(x, int) and isinstance(y, int):
        return (x > y) - (x < y)
    if isinstance(x, int) or isinstance(y, int):  # a number is newer than a qualifier ...
        if x is None or y is None:                # ... and a missing number is 0
            n = x if y is None else y
            return ((n > 0) - (n < 0)) * (1 if y is None else -1)
        return 1 if isinstance(x, int) else -1
    rx, ry = _QUALIFIERS.get(x or "", 8), _QUALIFIERS.get(y or "", 8)
    if rx != ry:
        return (rx > ry) - (rx < ry)
    return ((x or "") > (y or "")) - ((x or "") < (y or ""))


def _cmp_maven(a: list, b: list) -> int:
    for i in range(max(len(a), len(b))):
        c = _cmp_item(a[i] if i < len(a) else None, b[i] if i < len(b) else None)
        if c:
            return c
    return 0


def maven_ranges(spec: str) -> list[tuple] | None:
    """[(low, low inclusive, high, high inclusive)], low/high None when open; [] for any version;
    None when it isn't a range."""
    spec = spec.replace(" ", "")
    if spec in ("", "*"):
        return []
    if spec[0] not in "[(":
        return []  # a bare version is only a recommendation: any version will do
    out, i = [], 0
    while i < len(spec):
        if spec[i] == ",":
            i += 1
            continue
        if spec[i] not in "[(":
            return None
        end = min((j for j in (spec.find("]", i), spec.find(")", i)) if j != -1), default=-1)
        if end == -1:
            return None
        body, lo_inc, hi_inc = spec[i + 1:end], spec[i] == "[", spec[end] == "]"
        if "," in body:
            lo, _, hi = body.partition(",")
            out.append((maven_version(lo) if lo else None, lo_inc, maven_version(hi) if hi else None, hi_inc))
        else:
            v = maven_version(body)
            out.append((v, True, v, True))
        i = end + 1
    return out


def maven_matches(version: str, ranges: list[str]) -> bool | None:
    have = maven_version(version)
    if not have:
        return None
    parsed = maven_ranges(ranges[0] if ranges else "*")
    if parsed is None:
        return None
    if not parsed:
        return True
    for lo, lo_inc, hi, hi_inc in parsed:
        if lo is not None and (_cmp_maven(have, lo) < 0 or (_cmp_maven(have, lo) == 0 and not lo_inc)):
            continue
        if hi is not None and (_cmp_maven(have, hi) > 0 or (_cmp_maven(have, hi) == 0 and not hi_inc)):
            continue
        return True
    return False


# ------------------------------------------------------------------ in words
def wanted(loader: str, ranges: list[str]) -> str:
    """A version requirement the way people say it."""
    if loader == "fabric":
        def one(r):
            terms = r.split()
            if not terms or terms == ["*"]:
                return "any version"
            if len(terms) == 1:
                t = terms[0].rstrip("-")  # ("26.1-": with its pre-releases; people say 26.1)
                if t.startswith(">="):
                    return f"{t[2:]} or later"
                if t.startswith(">"):
                    return f"newer than {t[1:]}"
                if t[0] in "~^" and fabric_version(t[1:]):
                    keep = ".".join(str(p) for p in (fabric_version(t[1:])[0] + [0])[:2 if t[0] == "~" else 1])
                    return f"{t[1:]} or a later {keep}.x version"
                if t.startswith("<"):
                    return f"older than {t[1:].lstrip('=')}" if not t.startswith("<=") else f"{t[2:]} or older"
                if "x" in t.lower() or "*" in t:
                    return f"any {t.lstrip('=')} version"
                if t[0].isdigit() or t.startswith("="):
                    return f"exactly {t.lstrip('=')}"
            return " ".join(terms)
        return " or ".join(one(r) for r in ranges) or "any version"
    parsed = maven_ranges(ranges[0] if ranges else "*")
    spec = (ranges[0] if ranges else "*").replace(" ", "")
    if parsed and len(parsed) == 1:
        m = re.fullmatch(r"\[([^,\]]+),\)", spec)
        if m:
            return f"{m.group(1)} or later"
        m = re.fullmatch(r"\[([^,\]]+)\]", spec)
        if m:
            return f"exactly {m.group(1)}"
        m = re.fullmatch(r"\[([^,\]]+),([^,\)]+)\)", spec)
        if m:
            return f"{m.group(1)} or later, older than {m.group(2)}"
    return "any version" if parsed == [] else spec


# ------------------------------------------------------------------ the check
def check(mods: list[ModInfo], *, loader: str, minecraft: str | None, loader_version: str | None,
          java_major: int | None = None, side: str = "client", complete: bool = True) -> list[Problem]:
    """What the loader would refuse, for the mods that load on ``side`` (client or server).
    ``complete`` is False when some files couldn't be read: a mod missing may be in one of
    those, so only the problems with mods that are there are told."""
    if loader not in LOADERS:
        return []
    matches = fabric_matches if loader == "fabric" else maven_matches
    loaded = [m for m in mods if m.side in ("both", side)]
    have: dict[str, list[tuple[str | None, str]]] = {}   # mod id -> [(version, name)]
    for m in loaded:
        for mid in (m.id, *m.provides):
            have.setdefault(mid, []).append((m.version, m.name))
    for mid in BUILTIN[loader]:
        if mid not in have:
            known = {"minecraft": minecraft, "java": str(java_major) if java_major else None}.get(mid)
            if mid in ("fabricloader", "forge", "neoforge"):
                known = loader_version
            have[mid] = [(known, {"minecraft": "Minecraft", "java": "Java"}.get(mid, mid))]

    problems: list[Problem] = []
    seen = set()
    for m in loaded:
        who = f"{m.name} {m.version}" if m.version else m.name
        for dep in m.depends:
            if dep.side not in ("both", side) or dep.id == m.id:
                continue
            present = have.get(dep.id)
            if dep.kind == "breaks":
                if present and any(v is not None and matches(v, dep.ranges) is True for v, _ in present):
                    v, name = next((v, n) for v, n in present if v is not None and matches(v, dep.ranges) is True)
                    p = Problem("breaks", m.name, m.id, dep.id, f"{who} doesn't work with {name} {v}.", m.file)
                    if (p.kind, p.mod_id, p.needs) not in seen:
                        seen.add((p.kind, p.mod_id, p.needs))
                        problems.append(p)
                continue
            want = wanted(loader, dep.ranges)
            if not present:
                if not complete:
                    continue
                p = Problem("missing", m.name, m.id, dep.id, f"{who} needs {dep.id} ({want}), which is missing.", m.file)
            else:
                results = [matches(v, dep.ranges) if v is not None else None for v, _ in present]
                if any(r is not False for r in results):
                    continue
                v, name = present[0]
                if dep.id == "minecraft":
                    p = Problem("minecraft", m.name, m.id, dep.id, f"{who} is made for Minecraft {want}, not {v}.", m.file)
                elif dep.id == "java":
                    p = Problem("java", m.name, m.id, dep.id, f"{who} needs Java {want}; this Minecraft uses Java {v}.", m.file)
                elif dep.id in ("fabricloader", "forge", "neoforge"):
                    p = Problem("loader", m.name, m.id, dep.id, f"{who} needs {name} {want}, not {v}.", m.file)
                else:
                    p = Problem("version", m.name, m.id, dep.id, f"{who} needs {name} {want}, but {name} {v} is the one there.", m.file)
            if (p.kind, p.mod_id, p.needs) not in seen:
                seen.add((p.kind, p.mod_id, p.needs))
                problems.append(p)
    return problems


def check_folder(folder: Path, *, loader: str, minecraft: str | None, loader_version: str | None,
                 java_major: int | None = None, side: str = "server") -> list[Problem]:
    """The check for a mods folder on this computer (every .jar in it)."""
    if loader not in LOADERS or not folder.is_dir():
        return []
    mods, complete = [], True
    for path in sorted(folder.glob("*.jar")):
        try:
            mods += read_file(path, loader)
        except OSError as e:
            log.info("couldn't read %s to check it: %s", path.name, e)
            complete = False
    return check(mods, loader=loader, minecraft=minecraft, loader_version=loader_version,
                 java_major=java_major, side=side, complete=complete)
