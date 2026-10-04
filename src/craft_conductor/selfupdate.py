"""Updating craft-conductor itself from its GitHub releases.

A release is a GitHub release tagged ``vX.Y.Z`` (a beta: ``vX.Y.ZbN``, published as a GitHub
pre-release). Stable is the default channel; beta is chosen by the owner. How it is installed
depends on how craft-conductor was installed:

* the standalone download (a PyInstaller executable): the matching executable is
  downloaded from the release, checked against the release's ``SHA256SUMS.txt``,
  and swapped in place of the running one;
* pip / pipx: the release's wheel, checked against the same ``SHA256SUMS.txt``, is installed
  with ``pip install --no-index --no-deps`` by the same Python that runs craft-conductor;
* a source checkout (editable install): left to ``git pull``.

Whatever the way, an update is only ever to a newer version (never a downgrade), and the
running copy stays untouched until the new one has been downloaded completely and matched
its published checksum. Anything that can't be verified is refused, never installed anyway.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from importlib import metadata
from pathlib import Path

from . import __version__
from .http import HashMismatch, HttpClient, HttpError, sha256_file

log = logging.getLogger(__name__)

REPO = "silverWRX03/craft-conductor"
DIST = "craft-conductor"
RELEASES = f"https://api.github.com/repos/{REPO}/releases"
SUMS = "SHA256SUMS.txt"
CHANNELS = ("stable", "beta")   # stable: releases only (the default); beta: pre-releases too
DEFAULT_CHANNEL = "stable"
MAX_DOWNLOAD = 512 * 1024 * 1024  # far bigger than any real download: a bad one can't fill the disk
MAX_SUMS = 64 * 1024
WHEEL = re.compile(r"craft_conductor-([0-9A-Za-z.+!-]+)-py3-none-any\.whl")


class SelfUpdateError(Exception):
    pass


class VerificationError(SelfUpdateError):
    """The download isn't exactly what the release published (damaged, cut short or tampered with)."""


@dataclass
class Release:
    version: str
    tag: str
    url: str
    notes: str
    assets: dict[str, str] = field(default_factory=dict)   # file name -> download URL
    sizes: dict[str, int] = field(default_factory=dict)    # file name -> size GitHub says it has
    prerelease: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Release:
        return cls(str(d["version"]), str(d["tag"]), str(d.get("url", "")), str(d.get("notes", "")),
                   dict(d.get("assets") or {}), {k: int(v) for k, v in (d.get("sizes") or {}).items()},
                   bool(d.get("prerelease")))


_VERSION = re.compile(r"[vV]?(\d+)\.(\d+)(?:\.(\d+))?"
                      r"(?:[-.]?(a|alpha|b|beta|c|rc|pre|preview)[-.]?(\d*))?", re.IGNORECASE)
_PRE_RANK = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "c": 2, "rc": 2, "pre": 2, "preview": 2}
FINAL = 9  # a release sorts after its own alphas, betas and release candidates


def version_key(v: str) -> tuple[int, int, int, int, int] | None:
    """A version as something to compare: 0.23.0b1 < 0.23.0b2 < 0.23.0rc1 < 0.23.0 < 0.23.1.
    None for anything that isn't a version like that (never installed: it can't be compared)."""
    m = _VERSION.fullmatch(str(v).strip().split("+")[0])
    if not m:
        return None
    major, minor, patch = int(m[1]), int(m[2]), int(m[3] or 0)
    if not m[4]:
        return (major, minor, patch, FINAL, 0)
    return (major, minor, patch, _PRE_RANK[m[4].lower()], int(m[5] or 0))


def is_prerelease(v: str) -> bool:
    key = version_key(v)
    return key is not None and key[3] != FINAL


def newer(candidate: str, current: str = __version__) -> bool:
    """Whether ``candidate`` is a newer version than ``current`` (False when either can't be read)."""
    a, b = version_key(candidate), version_key(current)
    return a is not None and b is not None and a > b


def channel_or_default(channel: str | None) -> str:
    return channel if channel in CHANNELS else DEFAULT_CHANNEL


def latest_release(http: HttpClient, channel: str = DEFAULT_CHANNEL) -> Release | None:
    """The newest release on ``channel``: stable never offers a beta, even one GitHub calls latest."""
    try:
        data = http.get_json(RELEASES, params={"per_page": 30}, headers={"Accept": "application/vnd.github+json"})
    except HttpError as e:
        if e.status == 404:  # no releases published yet
            return None
        raise
    found = [r for r in (_release(x, channel) for x in (data if isinstance(data, list) else [])
                         if isinstance(x, dict)) if r is not None]
    return max(found, key=lambda r: version_key(r.version), default=None)


def _release(data: dict, channel: str = DEFAULT_CHANNEL) -> Release | None:
    tag = str(data.get("tag_name") or "")
    version = tag.lstrip("vV")
    if not tag or data.get("draft") or version_key(version) is None:
        return None
    pre = bool(data.get("prerelease")) or is_prerelease(version)  # (either says so: it's a beta)
    if pre and channel_or_default(channel) != "beta":
        return None
    assets, sizes = {}, {}
    for a in data.get("assets") or []:
        if isinstance(a, dict) and a.get("name") and a.get("browser_download_url"):
            assets[a["name"]] = a["browser_download_url"]
            if isinstance(a.get("size"), int):
                sizes[a["name"]] = a["size"]
    return Release(version=version, tag=tag, url=data.get("html_url", ""),
                   notes=(data.get("body") or "")[:4000], assets=assets, sizes=sizes, prerelease=pre)


def check(http: HttpClient, current: str = __version__, channel: str = DEFAULT_CHANNEL) -> Release | None:
    """The newest release on ``channel``, if it is newer than ``current``."""
    release = latest_release(http, channel)
    if release and newer(release.version, current):
        return release
    return None


def frozen() -> bool:
    """True when running as the standalone executable."""
    return bool(getattr(sys, "frozen", False))


PREFIX = "craft-conductor"               # the downloads: craft-conductor-windows-x64.exe ...
FRIEND_PREFIX = "craft-conductor-join"   # the friends' download: the same program, opening straight into joining


def friend_build() -> bool:
    """True for a friends' download, including a browser's numbered duplicate filename."""
    return frozen() and Path(sys.executable).name.lower().startswith(FRIEND_PREFIX)



def asset_name(friend: bool | None = None) -> str:
    """The release file for this computer, e.g. ``craft-conductor-windows-x64.exe``
    (``craft-conductor-join-...`` for the friends' download, which updates to the same)."""
    system = {"Windows": "windows", "Darwin": "macos"}.get(platform.system(), "linux")
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    prefix = FRIEND_PREFIX if (friend_build() if friend is None else friend) else PREFIX
    return f"{prefix}-{system}-{arch}{'.exe' if system == 'windows' else ''}"


def install_method(release: Release | None = None) -> tuple[bool, str]:
    """(can craft-conductor update itself, why not)."""
    if os.environ.get("CRAFT_CONDUCTOR_CONTAINER"):
        return False, "Craft Conductor runs in a container here; update it by pulling the new image (docker pull ...)"
    if frozen():
        if release is not None and asset_name() not in release.assets:
            return False, f"this release has no download for your system ({asset_name()}); get it from the release page"
        return True, ""
    try:
        dist = metadata.distribution(DIST)
    except metadata.PackageNotFoundError:
        return False, "Craft Conductor is running from a source checkout; update it with `git pull`"
    direct = dist.read_text("direct_url.json")
    if direct:
        try:
            if json.loads(direct).get("dir_info", {}).get("editable"):
                return False, "Craft Conductor is installed in editable (development) mode; update it with `git pull`"
        except ValueError:
            pass
    if release is not None:
        try:
            wheel_name(release)
        except SelfUpdateError as e:
            return False, str(e)
    return True, ""


def _refuse_downgrade(release: Release, current: str) -> None:
    if not newer(release.version, current):
        raise SelfUpdateError(f"Craft Conductor {release.version} isn't newer than the {current} you have, so it "
                              "wasn't installed (updates never go back to an older version)")


def install(release: Release, runner=subprocess.run, http: HttpClient | None = None,
            current: str = __version__) -> str:
    _refuse_downgrade(release, current)
    ok, why = install_method(release)
    if not ok:
        raise SelfUpdateError(why)
    http = http or HttpClient()
    if frozen():
        return install_binary(release, Path(sys.executable), http, current)
    return install_wheel(release, runner, http, current)


def wheel_name(release: Release) -> str:
    """The release's Python package (for pip/pipx installs): exactly one, of this very version."""
    found = [n for n in release.assets if (m := WHEEL.fullmatch(n)) and version_key(m[1]) == version_key(release.version)]
    if len(found) != 1:
        raise SelfUpdateError(f"release {release.version} has no Python package to install; "
                              f"update by hand from {release.url or 'its release page'}")
    return found[0]


def install_wheel(release: Release, runner, http: HttpClient, current: str = __version__) -> str:
    """pip/pipx: install the release's wheel, verified, without pip fetching anything else."""
    _refuse_downgrade(release, current)
    name = wheel_name(release)
    log.info("installing Craft Conductor %s", release.version)
    with tempfile.TemporaryDirectory(prefix="craft-conductor-update-") as tmp:
        wheel = _download_verified(release, name, http, Path(tmp))
        proc = runner([sys.executable, "-m", "pip", "install", "--upgrade", "--no-deps", "--no-index",
                       "--disable-pip-version-check", str(wheel)], capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-15:])
        raise SelfUpdateError(f"pip could not install Craft Conductor {release.version}:\n{tail}")
    return f"installed Craft Conductor {release.version}"


def _expected_sha256(release: Release, name: str, http: HttpClient, workdir: Path) -> str:
    """The checksum ``SHA256SUMS.txt`` publishes for ``name``. A missing, unreadable or
    contradictory entry is refused: without it the download can't be checked."""
    sums_url = release.assets.get(SUMS)
    if not sums_url:
        raise VerificationError("the release has no SHA256SUMS.txt, so the download can't be verified")
    try:
        text = http.download(sums_url, workdir / SUMS, max_bytes=MAX_SUMS).read_text("utf-8")
    except (HashMismatch, UnicodeDecodeError) as e:
        raise VerificationError("the release's SHA256SUMS.txt isn't readable, so the download can't be verified") from e
    found = set()
    for line in text.splitlines():
        m = re.fullmatch(r"(\S+)\s+\*?(.+)", line.strip())  # (sha256sum's "<hash>  <name>")
        if not m or m[2] != name:
            continue
        if not re.fullmatch(r"[0-9a-fA-F]{64}", m[1]):
            raise VerificationError(f"SHA256SUMS.txt has a broken entry for {name}")
        found.add(m[1].lower())
    if not found:
        raise VerificationError(f"SHA256SUMS.txt has no entry for {name}")
    if len(found) > 1:
        raise VerificationError(f"SHA256SUMS.txt has two different entries for {name}")
    return found.pop()


def _download_verified(release: Release, name: str, http: HttpClient, workdir: Path) -> Path:
    """Download ``name`` into the private ``workdir`` and check it: its published checksum,
    the size GitHub gives for it, and (just before it's used) the checksum of the file on disk."""
    sha256 = _expected_sha256(release, name, http, workdir)
    size = release.sizes.get(name)
    if size is not None and not 0 < size <= MAX_DOWNLOAD:
        raise VerificationError(f"{name} in release {release.version} has an impossible size ({size} bytes)")
    try:
        new = http.download(release.assets[name], workdir / name, sha256=sha256,
                            max_bytes=size if size is not None else MAX_DOWNLOAD)
    except HashMismatch as e:
        raise VerificationError(f"the download of {name} doesn't match the release's published checksum "
                                "(it may be incomplete or tampered with), so nothing was changed") from e
    if (size is not None and new.stat().st_size != size) or sha256_file(new) != sha256:
        raise VerificationError(f"the download of {name} changed after it was checked, so nothing was changed")
    return new


def install_binary(release: Release, exe: Path, http: HttpClient, current: str = __version__) -> str:
    """Download this platform's executable, verify it, and put it in place of ``exe``."""
    _refuse_downgrade(release, current)
    name = asset_name()
    if name not in release.assets:
        raise SelfUpdateError(f"this release has no download for your system ({name})")
    log.info("downloading Craft Conductor %s (%s)", release.version, name)
    try:
        with tempfile.TemporaryDirectory(dir=exe.parent, prefix=".craft-conductor-update-") as tmp:
            new = _download_verified(release, name, http, Path(tmp))
            new.chmod(0o755)
            if os.name == "nt":
                # A running .exe can't be overwritten, but it can be renamed out of the way.
                old = old_binary(exe)
                old.unlink(missing_ok=True)
                exe.rename(old)
                try:
                    os.replace(new, exe)
                except OSError:
                    old.rename(exe)
                    raise
            else:
                os.replace(new, exe)
    except PermissionError as e:
        raise SelfUpdateError(f"no permission to replace {exe}; move Craft Conductor somewhere you can write to, "
                              f"or download the new version from {release.url}") from e
    return f"installed Craft Conductor {release.version}"


def old_binary(exe: Path) -> Path:
    return exe.with_name(exe.stem + ".old" + exe.suffix)


def cleanup_after_update() -> None:
    """Delete the previous executable that a Windows self-update left behind."""
    if frozen():
        try:
            old_binary(Path(sys.executable)).unlink(missing_ok=True)
        except OSError:
            pass


def restart_argv() -> list[str]:
    """The command line to re-run this same craft-conductor command on the new version."""
    if frozen():
        return [sys.executable, *sys.argv[1:]]
    return [sys.executable, "-m", "craft_conductor", *sys.argv[1:]]


WINDOWS = os.name == "nt"


def restart_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """The environment for the restarted copy. The standalone download unpacks itself into a
    temporary folder (PyInstaller) that's deleted when this copy exits; without this, the new
    copy would think it's a helper of this one, reuse that folder and break as soon as it's gone
    ("No such file or directory: ...\\_MEI...\\base_library.zip")."""
    env = dict(os.environ if env is None else env)
    if frozen():
        env = {k: v for k, v in env.items() if not k.startswith("_PYI_") and k != "_MEIPASS2"}
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def restart() -> None:
    """Replace this process with the same craft-conductor command on the new version (never returns)."""
    argv, env = restart_argv(), restart_env()
    print("restarting Craft Conductor on the new version...", flush=True)
    if WINDOWS:
        # (Windows has no real exec: os.execv starts another process without quoting paths
        # with spaces. Start it properly, sharing this console, and end this one.)
        subprocess.Popen(argv, env=env)
        os._exit(0)
        return  # (only reached in tests)
    os.execve(argv[0], argv, env)
