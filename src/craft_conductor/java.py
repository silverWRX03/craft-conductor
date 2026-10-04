"""Choosing, downloading and managing the Java a server runs on.

One store of downloaded runtimes serves every server on this computer: Eclipse Temurin builds from the
Adoptium API, in ``<home>/.craft-conductor/java/<major>/<release>/`` (home is CRAFT_CONDUCTOR_HOME, else
``~/craft-conductor``; ``/data`` in Docker). Two servers that need Java 21 use one copy, downloaded once.

- A new patch release goes in next to the old one, and servers move to it at their next start. An older
  release is deleted only once no server process runs from it: each start leaves the process id in
  ``<release>/.in-use/``, and on Windows a folder with a file still open can't be renamed away either.
- Before anything is downloaded, Java that's already on the computer is looked for: [java.versions],
  ``java`` on PATH, JAVA_HOME and the usual install folders. Each one is run with ``-version`` only (plus
  the flag that prints its architecture), once: the answer is remembered by the file's size and date.
  One that is exactly the version needed is written into the server's [java.versions], so the choice
  stays explicit. A newer major version is used only when asked to ([java] version).
- ``servers/`` in the store notes which server last started on which Java (one small file each), so a
  runtime another server uses is never removed.
"""

from __future__ import annotations

import glob
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import tarfile
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable

from .config import Config
from .http import HttpClient

log = logging.getLogger(__name__)

ADOPTIUM = "https://api.adoptium.net/v3"
META = "craft-conductor-java.json"
LEASES = ".in-use"          # in a release's folder: one file per process running from it
USERS = "servers"           # in the store: which server uses which Java
CHECKED = "checked.json"    # in the store: what each Java found on this computer turned out to be
SCAN_TTL = 3600             # how long the list of Java install folders is trusted
GRACE = 300                 # an old release replaced less than this long ago stays (a server may be starting on it)


class JavaError(Exception):
    pass


def default_store() -> Path:
    """The shared Java folder: in Craft Conductor's own folder, next to the servers (``/data`` in Docker)."""
    home = Path(os.environ.get("CRAFT_CONDUCTOR_HOME") or Path.home() / "craft-conductor")
    return home.resolve() / ".craft-conductor" / "java"


# ------------------------------------------------------------------ what a Java is
_VERSION = re.compile(r'version "([^"]+)"')
_PROPERTY = re.compile(r"^\s*([\w.]+) = (.*?)\s*$", re.M)
_ARCHES = {"x86_64": "x64", "amd64": "x64", "x64": "x64", "aarch64": "aarch64", "arm64": "aarch64",
           "armv7l": "arm", "arm": "arm", "x86": "x32", "i386": "x32", "i486": "x32", "i586": "x32",
           "i686": "x32", "ppc64le": "ppc64le", "s390x": "s390x"}


_ARCH_WORDS = {"x64": "x64 (64-bit Intel/AMD)", "aarch64": "ARM64", "x32": "32-bit x86", "arm": "32-bit ARM"}


def arch_name(machine: str) -> str:
    """An architecture in Adoptium's words (x64, aarch64, x32, ...)."""
    m = machine.strip().lower()
    return _ARCHES.get(m, m)


def parse_major(version_output: str) -> int | None:
    m = _VERSION.search(version_output)
    if not m:
        return None
    parts = m.group(1).split(".")
    if parts[0] == "1" and len(parts) > 1:  # "1.8.0_392" style
        parts = parts[1:]
    digits = re.match(r"\d+", parts[0])
    return int(digits.group(0)) if digits else None


@dataclass(frozen=True)
class JavaInfo:
    major: int
    arch: str | None = None   # Adoptium's words; None when it didn't say
    version: str = ""
    vendor: str = ""
    home: str = ""            # its java.home (where it's installed)


def parse_info(output: str) -> JavaInfo | None:
    """``java -XshowSettings:properties -version``'s output, read."""
    props = dict(_PROPERTY.findall(output))
    major = parse_major(output)
    if major is None and props.get("java.version"):
        major = parse_major(f'version "{props["java.version"]}"')
    if major is None:
        return None
    arch = props.get("os.arch")
    return JavaInfo(major, arch_name(arch) if arch else None,
                    props.get("java.runtime.version") or props.get("java.version", ""), props.get("java.vendor", ""),
                    props.get("java.home", ""))


# Variables that would make even `java -version` load extra code (an agent, a class path).
_JAVA_ENV = ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "JAVA_OPTIONS", "CLASSPATH")


def run_version(binary: str) -> JavaInfo | None:
    """What a Java is: its version and architecture, from running it with ``-version`` (nothing else runs)."""
    if shutil.which(binary) is None:
        return None
    from .desktop import NO_WINDOW, child_env
    env = {k: v for k, v in child_env().items() if k.upper() not in _JAVA_ENV}
    try:
        out = subprocess.run([binary, "-XshowSettings:properties", "-version"], capture_output=True, text=True,
                             errors="replace", timeout=20, env=env, stdin=subprocess.DEVNULL, **NO_WINDOW)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return parse_info(out.stderr + out.stdout)


def probe(binary: str) -> int | None:
    info = run_version(binary)
    return info.major if info else None


@lru_cache(maxsize=1)
def _rosetta() -> bool:
    """Python itself running translated (x86) on an Apple silicon Mac."""
    try:
        out = subprocess.run(["sysctl", "-in", "sysctl.proc_translated"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return out.stdout.strip() == "1"


def host_platform() -> tuple[str, str]:
    """(os, architecture) in Adoptium's vocabulary."""
    system = platform.system().lower()
    if system == "darwin":
        os_name = "mac"
    elif system == "windows":
        os_name = "windows"
    elif Path("/etc/alpine-release").exists():
        os_name = "alpine-linux"
    else:
        os_name = "linux"
    arch = arch_name(platform.machine())
    if os_name == "mac" and arch == "x64" and _rosetta():
        arch = "aarch64"
    return os_name, arch


def install_folders() -> list[str]:
    """Where Java is usually installed on this kind of computer (glob patterns for its java)."""
    system = platform.system()
    if system == "Windows":
        bases = dict.fromkeys(filter(None, [os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"),
                                            os.environ.get("ProgramFiles(x86)"),
                                            os.environ.get("LOCALAPPDATA") and os.path.join(os.environ["LOCALAPPDATA"], "Programs")]))
        vendors = ("Eclipse Adoptium", "AdoptOpenJDK", "Microsoft", "Java", "Zulu", "Amazon Corretto", "BellSoft",
                   "Semeru", "OpenJDK", "RedHat")
        return [os.path.join(b, v, "*", "bin", "java.exe") for b in bases for v in vendors]
    if system == "Darwin":
        return ["/Library/Java/JavaVirtualMachines/*/Contents/Home/bin/java",
                os.path.expanduser("~/Library/Java/JavaVirtualMachines/*/Contents/Home/bin/java"),
                "/opt/homebrew/opt/openjdk*/bin/java", "/usr/local/opt/openjdk*/bin/java"]
    return ["/usr/lib/jvm/*/bin/java", "/usr/lib64/jvm/*/bin/java", "/usr/java/*/bin/java", "/opt/java/*/bin/java",
            "/opt/jdk*/bin/java"]


class _Checked:
    """What each Java turned out to be, remembered by its file's size and date: ``-version`` runs once per
    Java, not on every look. Kept in the store (``checked.json``) so a restart doesn't run them again."""

    def __init__(self, file: Path | None):
        self.file = file
        self.lock = threading.Lock()
        self.data: dict | None = None

    def _load(self) -> dict:
        if self.data is None:
            try:
                data = json.loads(self.file.read_text()) if self.file else {}
            except (OSError, ValueError):
                data = {}
            self.data = data if isinstance(data, dict) else {}
        return self.data

    def get(self, binary: str, run: Callable[[str], JavaInfo | None]) -> JavaInfo | None:
        try:
            path = shutil.which(binary)
            real = os.path.realpath(path) if path else None
            st = os.stat(real) if real else None
        except OSError:
            real = st = None
        if st is None:  # (nothing there: nothing to remember it by)
            return run(binary)
        stamp = [st.st_mtime_ns, st.st_size]
        with self.lock:
            hit = self._load().get(real)
            if isinstance(hit, dict) and hit.get("stamp") == stamp:
                try:
                    return JavaInfo(**hit["info"]) if hit.get("info") else None
                except TypeError:
                    pass
        info = run(binary)
        with self.lock:
            data = self._load()
            data[real] = {"stamp": stamp, "info": info.__dict__ if info else None}
            if self.file:
                try:
                    self.file.parent.mkdir(parents=True, exist_ok=True)
                    tmp = self.file.with_name(f"{CHECKED}.{os.getpid()}.tmp")
                    tmp.write_text(json.dumps(data, indent=1))
                    os.replace(tmp, self.file)
                except OSError as e:
                    log.debug("couldn't remember what %s is: %s", real, e)
        return info


_checked: dict[Path, _Checked] = {}
_found_paths: dict[tuple, tuple[float, list[tuple[str, str]]]] = {}  # the install folders' java, by pattern
_shared_lock = threading.Lock()
_install_locks: dict[tuple[Path, int], threading.Lock] = {}


def _checked_for(store: Path) -> _Checked:
    with _shared_lock:
        return _checked.setdefault(store, _Checked(store / CHECKED))


def folder_size(folder: Path) -> int:
    """Bytes in a folder (links not followed)."""
    total = 0
    for dirpath, _, files in os.walk(folder):
        for name in files:
            try:
                st = os.lstat(os.path.join(dirpath, name))
            except OSError:
                continue
            total += st.st_size if not os.path.islink(os.path.join(dirpath, name)) else 0
    return total


def _others_can_change(path: str) -> bool:
    """A file (or its folder) that another user could replace: never run, even with -version."""
    if os.name == "nt":
        return False  # (the install folders are Program Files and the user's own)
    try:
        real = os.path.realpath(path)
        for p in (real, os.path.dirname(real)):
            st = os.stat(p)
            if st.st_mode & 0o002 or st.st_uid not in (0, os.getuid()):
                return True
    except OSError:
        return False
    return False


def _version_key(info: JavaInfo) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", info.version)[:4])


@dataclass
class Found:
    """A Java on this computer (or in a server's settings), and what it is."""
    path: str
    source: str               # "[java.versions]", "default", "JAVA_HOME" or "installed"
    info: JavaInfo | None
    problem: str = ""         # why it can't run a server here ("" when it can)


# ------------------------------------------------------------------ the shared store
@dataclass
class ManagedJava:
    major: int
    release: str
    semver: str
    binary: Path
    folder: Path | None = None
    installed_at: float = 0.0
    size: int = 0

    @property
    def dir(self) -> Path:
        return self.folder or self.binary.parents[1]


_RELEASE_NAME = re.compile(r"[^A-Za-z0-9._+-]")


def _alive(pid: int) -> bool:
    from .daemon import pid_alive
    try:
        return pid_alive(pid)
    except (OSError, ValueError, OverflowError):
        return True  # (can't tell: count it as running)


class Store:
    """The folder of downloaded runtimes every server on this computer shares."""

    def __init__(self, root: Path, grace: float | None = None):
        self.root = root
        self.grace = GRACE if grace is None else grace

    # ------------------------------------------------------------ releases
    def _read(self, folder: Path) -> ManagedJava | None:
        try:
            d = json.loads((folder / META).read_text())
            binary = folder / d["java"]
            major = int(d["major"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
        try:
            inside = Path(os.path.realpath(binary)).is_relative_to(os.path.realpath(folder))
        except (OSError, ValueError):
            inside = False
        if not inside or not binary.is_file() or str(major) != folder.parent.name:
            return None
        return ManagedJava(major, str(d.get("release", "")), str(d.get("semver", "")), binary, folder,
                           float(d.get("installed_at", 0) or 0), int(d.get("bytes", 0) or 0))

    def releases(self) -> dict[int, list[ManagedJava]]:
        """Each Java version's releases here, newest first."""
        out: dict[int, list[ManagedJava]] = {}
        if not self.root.is_dir():
            return out
        for major_dir in self.root.iterdir():
            if not major_dir.name.isdigit() or not major_dir.is_dir() or major_dir.is_symlink():
                continue
            for folder in major_dir.iterdir():
                if folder.name.startswith(".") or folder.is_symlink() or not folder.is_dir():
                    continue
                j = self._read(folder)
                if j:
                    out.setdefault(j.major, []).append(j)
        return {k: sorted(v, key=lambda j: (j.installed_at, j.release), reverse=True) for k, v in sorted(out.items())}

    def newest(self) -> dict[int, ManagedJava]:
        return {major: rels[0] for major, rels in self.releases().items()}

    def owner(self, binary: str | Path) -> ManagedJava | None:
        """The release a java binary belongs to, if it's one of the store's."""
        try:
            rel = Path(os.path.realpath(binary)).relative_to(os.path.realpath(self.root))
        except (ValueError, OSError):
            return None
        if len(rel.parts) < 3 or not rel.parts[0].isdigit():
            return None
        return self._read(self.root / rel.parts[0] / rel.parts[1])

    # ------------------------------------------------- processes running it
    def lease(self, binary: str | Path, pid: int) -> None:
        """Note that process ``pid`` runs from this binary's release (so it isn't deleted under it)."""
        j = self.owner(binary)
        if j is None:
            return
        try:
            (j.dir / LEASES).mkdir(exist_ok=True)
            (j.dir / LEASES / str(int(pid))).write_text(str(int(time.time())))
        except OSError as e:
            log.warning("couldn't note that the server runs on %s: %s", j.release, e)

    def running(self, j: ManagedJava) -> list[int]:
        """Processes running from release ``j`` right now (notes left by ones that ended are removed)."""
        pids = []
        try:
            notes = list((j.dir / LEASES).iterdir())
        except OSError:
            return pids
        for note in notes:
            if not note.name.isdigit():
                continue
            if _alive(int(note.name)):
                pids.append(int(note.name))
            else:
                note.unlink(missing_ok=True)
        return pids

    # ------------------------------------------------------- servers using it
    def _user_file(self, root: Path) -> Path:
        return self.root / USERS / (hashlib.sha256(str(root).encode()).hexdigest()[:16] + ".json")

    def note_user(self, root: Path, name: str, major: int, binary: str, shared: bool) -> None:
        entry = {"root": str(root), "name": name, "major": major, "java": binary, "shared": shared}
        file = self._user_file(root)
        try:
            if json.loads(file.read_text()) == entry:
                return
        except (OSError, ValueError):
            pass
        try:
            file.parent.mkdir(parents=True, exist_ok=True)
            tmp = file.with_name(f"{file.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(entry))
            os.replace(tmp, file)
        except OSError as e:
            log.warning("couldn't note which Java %s uses: %s", name, e)

    def forget(self, root: Path) -> dict | None:
        file = self._user_file(root)
        try:
            entry = json.loads(file.read_text())
        except (OSError, ValueError):
            entry = None
        file.unlink(missing_ok=True)
        return entry if isinstance(entry, dict) else None

    def users(self) -> list[dict]:
        """Servers that still exist, and the Java each last started on."""
        from .config import CONFIG_NAME
        out = []
        folder = self.root / USERS
        if not folder.is_dir():
            return out
        for file in sorted(folder.glob("*.json")):
            try:
                entry = json.loads(file.read_text())
                if isinstance(entry, dict) and (Path(entry["root"]) / CONFIG_NAME).is_file():
                    out.append(entry)
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return out

    # ------------------------------------------------------------- removing
    def _delete(self, folder: Path) -> bool:
        """Delete a release's folder, only ever one inside the store. False when something still uses it."""
        try:
            if folder.is_symlink() or not folder.parent.name.isdigit() \
                    or folder.resolve().parent.parent != self.root.resolve():
                return False
        except OSError:
            return False
        trash = self.root / f".trash-{uuid.uuid4().hex[:12]}"
        try:
            folder.rename(trash)  # (Windows refuses while a program has a file in it open)
        except OSError:
            return False
        shutil.rmtree(trash, ignore_errors=True)
        return True

    def tidy(self) -> list[str]:
        """Delete older patch releases that no server process runs from any more. The newest release
        of each Java version stays (until it's removed)."""
        removed = []
        now = time.time()
        for major, rels in self.releases().items():
            newest = rels[0]
            if now - newest.installed_at < self.grace:
                continue
            for old in rels[1:]:
                if not self.running(old) and self._delete(old.dir):
                    log.info("removed Java %s %s: no server runs on it any more", major, old.release)
                    removed.append(old.release)
        if self.root.is_dir():
            for trash in self.root.glob(".trash-*"):  # (what an earlier removal couldn't finish)
                if trash.is_dir() and not trash.is_symlink():
                    shutil.rmtree(trash, ignore_errors=True)
        return removed

    def remove(self, major: int, ignore: Path | None = None) -> bool:
        """Delete every release of a Java version: refused while a server uses it or runs on it."""
        rels = self.releases().get(major, [])
        if not rels:
            return False
        users = [u for u in self.users() if u.get("shared") and u.get("major") == major
                 and (ignore is None or u["root"] != str(ignore))]
        if users:
            raise JavaError(f"Java {major} is used by {', '.join(u.get('name') or u['root'] for u in users)}")
        if any(self.running(j) for j in rels):
            raise JavaError(f"a server is running on Java {major}: stop it first")
        for j in rels:
            if not self._delete(j.dir):
                raise JavaError(f"a program still has Java {major}'s files open ({j.dir})")
        try:
            (self.root / str(major)).rmdir()
        except OSError:
            pass
        return True


# ------------------------------------------------------------------ choosing
@dataclass
class Choice:
    """The Java a server runs on, and why."""
    wanted: int
    source: str               # configured | shared | default | found | download | missing
    binary: str | None = None
    major: int | None = None
    release: str = ""
    note: str = ""
    newer: list[Found] = field(default_factory=list)   # newer Java that's here: used only if asked to


class JavaManager:
    def __init__(self, config: Config, http: HttpClient | None = None,
                 probe_fn: Callable[[str], int | JavaInfo | None] | None = None,
                 platform_fn: Callable[[], tuple[str, str]] | None = None,
                 store: Path | None = None, scan: bool = True,
                 folders_fn: Callable[[], list[str]] | None = None):
        self.config = config
        self.http = http or HttpClient()
        self.platform = platform_fn or host_platform
        self.store = Store(store or default_store())
        self.scan = scan                        # look for Java installed on the computer
        self.folders = folders_fn or install_folders
        self.temporary = False                  # a throwaway copy (test boot, preview, rehearsal): not noted
        if probe_fn is None:
            self._run, self._checked = run_version, _checked_for(self.store.root)
        else:
            self._run, self._checked = _as_info(probe_fn), _Checked(None)

    @property
    def dir(self) -> Path:
        return self.store.root

    def inspect(self, binary: str) -> JavaInfo | None:
        return self._checked.get(binary, self._run)

    def probe(self, binary: str) -> int | None:
        info = self.inspect(binary)
        return info.major if info else None

    # ------------------------------------------------------------ managed
    def installed(self) -> dict[int, ManagedJava]:
        """The newest downloaded release of each Java version."""
        return self.store.newest()

    def latest_release(self, major: int) -> dict:
        os_name, arch = self.platform()
        for image in dict.fromkeys([self.config.java_image, "jre", "jdk"]):
            assets = self.http.get_json(
                f"{ADOPTIUM}/assets/latest/{major}/hotspot",
                params={"architecture": arch, "image_type": image, "os": os_name, "vendor": "eclipse"})
            if assets:
                return assets[0]
        raise JavaError(f"Temurin has no Java {major} build for {os_name}/{arch}; "
                        f"install one yourself and set it under [java.versions]")

    def install(self, major: int, newest: bool = False) -> ManagedJava:
        """Java ``major`` in the shared store: downloaded unless it's there already (with ``newest``,
        unless its newest release is). A new release goes in next to the old one."""
        root = self.store.root
        with _shared_lock:
            lock = _install_locks.setdefault((root, major), threading.Lock())
        with lock:  # (two servers wanting it at once: one download)
            have = self.store.newest().get(major)
            if have and not newest:
                return have
            release = self.latest_release(major)
            name = _RELEASE_NAME.sub("_", str(release["release_name"]))[:80].strip(".") or "release"
            if have and have.release == release["release_name"]:
                return have
            target = root / str(major) / name
            if target.exists():
                j = self.store._read(target)
                if j:
                    return j
            package = release["binary"]["package"]
            if not package.get("checksum"):
                raise JavaError(f"Adoptium gave no checksum for Java {major} ({release['release_name']}): not downloaded")
            pkg_name = Path(str(package["name"])).name
            work = uuid.uuid4().hex[:12]
            download = root / f".download-{work}"
            extract = root / f".extract-{work}"
            archive = download / pkg_name
            log.info("downloading Java %s (%s)", major, release["release_name"])
            try:
                self.http.download(package["link"], archive, sha256=package.get("checksum"))
                extract.mkdir(parents=True)
                if pkg_name.endswith(".zip"):
                    with zipfile.ZipFile(archive) as z:
                        z.extractall(extract)
                else:
                    with tarfile.open(archive) as t:
                        t.extractall(extract, filter="data")
                binary = _find_java(extract)
                if binary is None:
                    raise JavaError(f"no bin/java in {pkg_name}")
                binary.chmod(binary.stat().st_mode | 0o111)
                size = folder_size(extract)
                (extract / META).write_text(json.dumps({
                    "major": major, "release": release["release_name"],
                    "semver": release.get("version", {}).get("semver", ""),
                    "java": binary.relative_to(extract).as_posix(),
                    "installed_at": time.time(), "bytes": size,
                }, indent=2))
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    extract.rename(target)
                except OSError:
                    if self.store._read(target) is None:  # (else another Craft Conductor put it there first)
                        raise
            finally:
                shutil.rmtree(extract, ignore_errors=True)
                shutil.rmtree(download, ignore_errors=True)
        self.store.tidy()
        j = self.store._read(target)
        if j is None:
            raise JavaError(f"Java {major} didn't install into {target}")
        return j

    def update(self) -> list[tuple[int, str, str]]:
        """Bring every downloaded Java version to its newest patch release. Servers move to it at their
        next start; a running one keeps its release until then."""
        changed = []
        for major, current in self.installed().items():
            latest = self.install(major, newest=True)
            if latest.release != current.release:
                changed.append((major, current.release, latest.release))
        return changed

    def remove(self, major: int) -> bool:
        """Delete a downloaded Java version (refused while a server uses it)."""
        return self.store.remove(major)

    def lease(self, binary: str, pid: int) -> None:
        self.store.lease(binary, pid)
        self.store.tidy()

    def forget(self, prune: bool = False, keep: set[int] = frozenset()) -> list[int]:
        """This server is gone: it no longer counts as using its Java. With ``prune``, a shared runtime only
        it used is deleted too (never one another server uses or a process runs from, nor any in ``keep``)."""
        entry = self.store.forget(self.config.root)
        if not (prune and entry and entry.get("shared")) or entry.get("major") in keep:
            return []
        try:
            return [entry["major"]] if self.store.remove(int(entry["major"])) else []
        except (JavaError, ValueError, TypeError):
            return []

    # ------------------------------------------------- Java on the computer
    def _computer(self, refresh: bool) -> list[tuple[str, str]]:
        """java on PATH, JAVA_HOME and the install folders' java: paths only (cheap), kept for SCAN_TTL."""
        patterns = tuple(self.folders())
        java_home = os.environ.get("JAVA_HOME", "")
        key = (patterns, java_home)
        with _shared_lock:
            hit = _found_paths.get(key)
            if hit and not refresh and time.monotonic() - hit[0] < SCAN_TTL:
                return hit[1]
        out = []
        if java_home:
            out.append((os.path.join(java_home, "bin", "java.exe" if os.name == "nt" else "java"), "JAVA_HOME"))
        for pattern in patterns:
            out += [(p, "installed") for p in sorted(glob.glob(pattern))[:20]]
        with _shared_lock:
            _found_paths[key] = (time.monotonic(), out)
        return out

    def problem(self, f: Found) -> str:
        """Why a Java can't run a server here ("" when it can)."""
        if f.info is None:
            return "not found, or didn't say its version"
        host = self.platform()[1]
        if f.info.arch is None:
            return "" if f.source in ("[java.versions]", "default") else "didn't say what kind of computer it's built for"
        if f.info.arch != host:
            words = lambda a: _ARCH_WORDS.get(a, a)  # noqa: E731
            return f"built for {words(f.info.arch)}, and this computer is {words(host)}"
        return ""

    def found(self, refresh: bool = False) -> list[Found]:
        """Every Java on this computer and in this server's settings, and what each is."""
        entries = [(p, "[java.versions]") for _, p in sorted(self.config.java_versions.items())]
        entries.append((self.config.java_default, "default"))
        if self.scan:
            entries += self._computer(refresh)
        out, seen = [], set()
        store = os.path.realpath(self.store.root)
        for path, source in entries:
            try:
                where = shutil.which(path)
                real = os.path.realpath(where) if where else path
            except (OSError, ValueError):
                real = path
            if real in seen or (source in ("JAVA_HOME", "installed") and real.startswith(store + os.sep)):
                continue
            seen.add(real)
            if source in ("JAVA_HOME", "installed") and _others_can_change(path):
                out.append(Found(path, source, None, "not run: other users on this computer can change it"))
                continue
            f = Found(path, source, self.inspect(path))
            if f.info is None and source == "default" and path == "java":
                continue  # (no java on the PATH: nothing found)
            f.problem = self.problem(f)
            out.append(f)
        return out

    def _remember(self, major: int, path: str) -> None:
        """Write a Java found on this computer into the server's [java.versions] (its explicit choice)."""
        cfg_path = getattr(self.config, "path", None)
        if cfg_path is not None:
            from . import config as configmod
            configmod.set_value(cfg_path, "java.versions", str(major), json.dumps(path))
        self.config.java_versions[major] = path

    # ---------------------------------------------------------- selection
    def choose(self, required: int, offers: bool = False) -> Choice:
        """Which Java a server that needs Java ``required`` runs on, and why, without changing anything.

        Preference: the exact major version: [java.versions], the shared store, [java] default, then
        one found on this computer (written into [java.versions] when the server starts); else a
        download when ``auto_install`` is on. A newer major version is never picked by itself: with
        ``offers``, the ones here are listed in :attr:`Choice.newer`. ``[java] version`` forces one.
        """
        forced = self.config.java_version
        if forced is not None and forced < required:
            raise JavaError(f"[java] version = {forced}, but this Minecraft version needs Java {required}+")
        wanted = forced or required
        c = self._pick(wanted)
        if offers and forced is None:
            c.newer = self._newer(wanted)
        return c

    def _pick(self, wanted: int) -> Choice:
        configured = self.config.java_versions.get(wanted)
        broken = ""
        if configured:
            info = self.inspect(configured)
            if info and info.major == wanted:
                return Choice(wanted, "configured", configured, wanted, note=f"your own Java at {configured}")
            broken = (f"[java.versions] {wanted} = {configured} is "
                      f"{f'Java {info.major}' if info else 'not there, or not Java'}")
        shared = self.store.newest().get(wanted)
        if shared:
            return Choice(wanted, "shared", str(shared.binary), wanted, shared.release,
                          f"shared Java {wanted} ({shared.release}), in {self.store.root}")
        default = self.config.java_default
        info = self.inspect(default)
        if info and info.major == wanted and not self.problem(Found(default, "default", info)):
            return Choice(wanted, "default", default, wanted, note=f"this computer's {default} (Java {wanted})")
        if self.scan and not configured:
            fits = [f for f in self.found() if f.info and f.info.major == wanted and not f.problem
                    and f.source in ("JAVA_HOME", "installed")]
            if fits:
                best = max(fits, key=lambda f: _version_key(f.info))
                return Choice(wanted, "found", best.path, wanted, note=f"your own Java at {best.path}")
        why = f" ({broken})" if broken else ""
        if self.config.java_auto_install:
            return Choice(wanted, "download", note=f"Java {wanted} isn't on this computer yet{why}: Eclipse Temurin "
                                                   f"{wanted} will be downloaded into {self.store.root}")
        return Choice(wanted, "missing", note=f"Java {wanted} isn't on this computer{why}, and downloads are off "
                                              "([java] auto_install = false)")

    def _newer(self, wanted: int) -> list[Found]:
        """Newer Java already here, one per version: the shared store's, else the newest found."""
        best: dict[int, Found] = {}
        for major, j in self.store.newest().items():
            if major > wanted:
                best[major] = Found(str(j.binary), "shared", JavaInfo(major, self.platform()[1], j.release, "Eclipse Adoptium"))
        for f in self.found() if self.scan else []:
            if f.info and f.info.major > wanted and not f.problem:
                if f.info.major not in best or (best[f.info.major].source != "shared"
                                                and _version_key(f.info) > _version_key(best[f.info.major].info)):
                    best[f.info.major] = f
        return [best[k] for k in sorted(best)]

    def select(self, required: int) -> str:
        """The Java binary to run a server that needs Java ``required``: a Java found on this computer is
        written into [java.versions], a missing one downloaded (when ``auto_install`` is on)."""
        c = self.choose(required)
        if c.source == "default" and self.scan:
            pinned = _home_java(self.inspect(c.binary))  # ([java] default = "java": the one it is today, kept)
            if pinned:
                c.source, c.binary = "found", pinned
        if c.source == "found":
            self._remember(c.wanted, c.binary)
            log.info("using the Java %s already on this computer: %s", c.wanted, c.binary)
        elif c.source == "download":
            j = self.install(c.wanted)
            c.source, c.binary, c.release = "shared", str(j.binary), j.release
        elif c.source == "missing":
            newer = self._newer(c.wanted) if self.scan else self._newer_shared(c.wanted)
            hint = ""
            if newer:
                n = newer[0].info.major
                hint = (f" Java {n} is on this computer: to use it instead, press Use Java {n} on the Java page "
                        f"(or run `craft-conductor java use {n}`). Some loaders and older mods break on a newer Java.")
            raise JavaError(f"Minecraft needs Java {c.wanted}: {c.note}.{hint} Run `craft-conductor java install "
                            f"{c.wanted}`, or set it under [java.versions] in craft-conductor.toml")
        self._note(c)
        return c.binary

    def _newer_shared(self, wanted: int) -> list[Found]:
        return [Found(str(j.binary), "shared", JavaInfo(m)) for m, j in self.store.newest().items() if m > wanted]

    def _note(self, c: Choice) -> None:
        root = getattr(self.config, "root", None)
        if self.temporary or root is None or getattr(self.config, "path", None) is None:
            return
        from .properties import read_properties
        try:
            name = read_properties(self.config.server.dir / "server.properties").get("motd") or root.name
        except (OSError, AttributeError):
            name = root.name
        self.store.note_user(root, name, c.wanted, c.binary, c.source == "shared")

    def users_of(self, c: Choice) -> list[dict]:
        """Other servers that run on the same Java as choice ``c``."""
        mine = str(getattr(self.config, "root", ""))
        same = lambda u: (u.get("shared") and u.get("major") == c.major) if c.source == "shared" \
            else (not u.get("shared") and u.get("java") == c.binary)  # noqa: E731
        return [u for u in self.store.users() if u["root"] != mine and same(u)]


def _home_java(info: JavaInfo | None) -> str | None:
    """The java in a Java's own folder (java.home), when it said where that is."""
    if not info or not info.home:
        return None
    binary = Path(info.home) / "bin" / ("java.exe" if os.name == "nt" else "java")
    return str(binary) if binary.is_file() else None


def _as_info(fn: Callable[[str], int | JavaInfo | None]) -> Callable[[str], JavaInfo | None]:
    def run(binary: str) -> JavaInfo | None:
        r = fn(binary)
        return JavaInfo(r) if isinstance(r, int) else r
    return run


def _find_java(root: Path) -> Path | None:
    hits = [p for name in ("java", "java.exe") for p in root.rglob(f"bin/{name}") if p.is_file()]
    return min(hits, key=lambda p: len(p.parts)) if hits else None
