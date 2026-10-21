"""Folders on the computer Craft Conductor runs on: where its browser saves downloads, and a
folder browser for the control panel.

A web page can't give the server a real path, so the panel shows this computer's folders through
the server, to the owner only (the routes aren't in access.py's tables). It lists folders, never
files, and never a link (a symlink or a Windows junction): a folder chosen with it is a real folder,
and a path typed by hand is resolved to one before it's used.
"""

from __future__ import annotations

import os
import re
import stat
import sys
from pathlib import Path

MAX_LISTED = 1000  # folders shown in one folder (a folder with more says so)

# Windows' own names for the folders people know (KNOWNFOLDERID), so a moved one (Downloads on D:) is found
DOWNLOADS = "{374DE290-123F-4565-9164-39C4925E467B}"
DOCUMENTS = "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}"
DESKTOP = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"
_HIDDEN = 0x2 | 0x4          # FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM
_REPARSE = 0x400             # FILE_ATTRIBUTE_REPARSE_POINT: a link, or a OneDrive folder that's partly in the cloud
_LINK_TAGS = (0xA000000C, 0xA0000003)  # IO_REPARSE_TAG_SYMLINK, IO_REPARSE_TAG_MOUNT_POINT (a junction)
_NOT_HERE = 0x1000 | 0x40000 | 0x400000  # FILE_ATTRIBUTE_OFFLINE, _RECALL_ON_OPEN, _RECALL_ON_DATA_ACCESS


class FolderError(Exception):
    """A folder that can't be used, said in plain words for the page."""


def _system() -> str:
    return "windows" if os.name == "nt" else "darwin" if sys.platform == "darwin" else "linux"


def known_folder(guid: str) -> Path | None:
    """A Windows known folder (``DOWNLOADS``...), where it is now, even if it was moved."""
    if os.name != "nt":
        return None
    import ctypes
    import uuid
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]
    u = uuid.UUID(guid)
    g = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))
    out = ctypes.c_wchar_p()
    try:
        failed = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out))
        return None if failed or not out.value else Path(out.value)
    except OSError:
        return None
    finally:
        if out:
            ctypes.windll.ole32.CoTaskMemFree(out)


def _xdg_downloads(home: Path, env: dict) -> Path | None:
    """Linux: the Downloads folder in ~/.config/user-dirs.dirs (XDG_DOWNLOAD_DIR="$HOME/Downloads"),
    read as text (no program is run). None when it's set to the home folder itself (switched off)."""
    config = Path(env.get("XDG_CONFIG_HOME") or home / ".config") / "user-dirs.dirs"
    try:
        lines = config.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return home / "Downloads"
    for line in lines:
        key, sep, value = line.strip().partition("=")
        if key != "XDG_DOWNLOAD_DIR" or not sep:
            continue
        value = value.strip().strip('"')
        if value.startswith("$HOME"):
            path = home / value[len("$HOME"):].lstrip("/")
        elif value.startswith("/"):
            path = Path(value)
        else:
            return None  # (the format allows only these two)
        return None if path == home else path
    return home / "Downloads"


def downloads_dir(system: str | None = None, home: Path | None = None, env: dict | None = None) -> Path | None:
    """Where the browser on this computer saves downloads: Windows' Downloads known folder, macOS'
    ~/Downloads, Linux's XDG download folder; None when there's none Craft Conductor can read (a
    service running as another account, Docker)."""
    system = system or _system()
    home = home or Path.home()
    env = os.environ if env is None else env
    if system == "windows":
        found = known_folder(DOWNLOADS) or home / "Downloads"
    elif system == "darwin":
        found = home / "Downloads"
    else:
        found = _xdg_downloads(home, env)
    return found if found is not None and readable(found) else None


def readable(path: Path) -> bool:
    try:
        return path.is_dir() and os.access(path, os.R_OK | os.X_OK)
    except OSError:
        return False


def link_stat(st: os.stat_result) -> bool:
    """From an lstat: a symlink, or on Windows a junction (or a reparse point of an unknown kind).
    What OneDrive syncs is a reparse point too, but a real file or folder: it isn't one."""
    if stat.S_ISLNK(st.st_mode):
        return True
    if not getattr(st, "st_file_attributes", 0) & _REPARSE:
        return False
    tag = getattr(st, "st_reparse_tag", 0)
    return not tag or tag in _LINK_TAGS


def in_the_cloud(st: os.stat_result) -> bool:
    """A file that's only in the cloud (OneDrive and the like): reading it would download it."""
    return bool(getattr(st, "st_file_attributes", 0) & _NOT_HERE)


def is_link(entry: os.DirEntry) -> bool:
    try:
        return entry.is_symlink() or link_stat(entry.stat(follow_symlinks=False))
    except OSError:
        return True


def _hidden(entry: os.DirEntry) -> bool:
    if entry.name.startswith("."):
        return True
    try:
        return bool(getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0) & _HIDDEN)
    except OSError:
        return True


NETWORK_FS = {"nfs", "nfs4", "cifs", "smb3", "smbfs", "fuse.sshfs", "sshfs", "9p", "davfs", "fuse.davfs2", "afs", "glusterfs",
              "ceph", "fuse.rclone"}


def is_network(path: Path | str) -> bool:
    r"""A folder on another computer: a Windows network path (\\server\share) or network drive, or
    a Linux network file system (NFS, SMB, SSHFS...). Said without connecting to it."""
    text = str(path)
    if os.name == "nt":
        if text.startswith(("\\\\", "//")):
            return True
        drive = os.path.splitdrive(text)[0]
        if len(drive) != 2:
            return False
        import ctypes
        return ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") == 4  # (DRIVE_REMOTE)
    if sys.platform == "darwin":
        return False  # (macOS: network shares and other drives both appear under /Volumes: locations.py)
    return mount_type(Path(text)) in NETWORK_FS


def mount_type(path: Path) -> str:
    """Linux: the file system type of the mount ``path`` is on (from /proc/mounts)."""
    try:
        lines = Path("/proc/mounts").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    real, best, kind = os.path.realpath(path), "", ""
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        point = parts[1].replace("\\040", " ")
        if (real == point or real.startswith(point.rstrip("/") + "/")) and len(point) > len(best):
            best, kind = point, parts[2]
    return kind


def check(text: str) -> Path:
    """A folder typed or picked on the page: a full path to a folder that's there and can be read,
    as the real folder it is (links followed to where they lead, ``..`` gone)."""
    text = str(text or "").strip()
    if not text or len(text) > 1000 or "\0" in text:
        raise FolderError("type the full path of a folder")
    path = Path(os.path.expanduser(text))
    if not path.is_absolute():
        raise FolderError(f"{text} isn't a full path (it starts with a drive like C:\\ or with /)")
    if is_network(path):
        raise FolderError(f"{text} is on another computer (the network): Craft Conductor only uses this computer's own folders")
    real = Path(os.path.realpath(path))
    if is_network(real):  # (a link that leads to the network)
        raise FolderError(f"{text} leads to another computer (the network): Craft Conductor only uses this computer's own folders")
    if not real.is_dir():
        raise FolderError(f"there's no folder at {text}")
    if not readable(real):
        raise FolderError(f"Craft Conductor can't read {real} (it isn't allowed to)")
    return real


def nearest(text: str) -> str:
    """``text``, or the nearest folder above it that's there: the folder browser opens on a place
    that isn't made yet (the exports folder, made when first used: #145) without an error. "" when
    none is; a path check() refuses (a network folder, a part path) as it is, for check() to say why."""
    text = str(text or "").strip()
    if not text or len(text) > 1000 or "\0" in text:
        return text
    path = Path(os.path.expanduser(text))
    if not path.is_absolute() or is_network(path):
        return text
    for p in (path, *path.parents):
        if p.is_dir():
            return str(p)
    return ""


_BAD_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_RESERVED = re.compile(r"(?i)^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$")  # (Windows' own names)


def make(parent: str, name: str) -> Path:
    """A new folder ``name`` in ``parent`` (the folder browser's New folder…); one already there is opened."""
    folder = check(parent)
    name = str(name or "").strip()
    if not name or len(name) > 100 or name in (".", "..") or name.endswith(".") or _BAD_NAME.search(name) or _RESERVED.match(name):
        raise FolderError("a folder's name can't be empty, end with a dot, or have \\ / : * ? \" < > | in it")
    path = folder / name
    try:
        path.mkdir(exist_ok=True)
    except OSError as e:
        raise FolderError(f"couldn't make the folder {path}: {e.strerror or e}") from None
    if not path.is_dir():
        raise FolderError(f"{path} is a file, not a folder")
    return path


def _drives() -> list[Path]:
    """Windows: the drive letters there are (not CD/DVD drives)."""
    if os.name != "nt":
        return []
    import ctypes
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    out = []
    for i in range(26):
        if mask & (1 << i):
            root = f"{chr(65 + i)}:\\"
            if ctypes.windll.kernel32.GetDriveTypeW(root) not in (0, 1, 4, 5):  # unknown, no root, network, CD/DVD
                out.append(Path(root))
    return out


def places(system: str | None = None, home: Path | None = None) -> list[dict]:
    """Where the folder browser starts: the home folder, Desktop, Documents, Downloads, then the
    drives (Windows) or the computer's top folder and where other drives appear (macOS, Linux)."""
    system = system or _system()
    home = home or Path.home()
    named = [("Home", home)]
    if system == "windows":
        named += [("Desktop", known_folder(DESKTOP) or home / "Desktop"),
                  ("Documents", known_folder(DOCUMENTS) or home / "Documents")]
    else:
        named += [("Desktop", home / "Desktop"), ("Documents", home / "Documents")]
    named.append(("Downloads", downloads_dir(system, home)))
    if system == "windows":
        named += [(str(d), d) for d in _drives()]
    else:
        named.append(("This computer (/)", Path("/")))
        user = home.name
        named += [(str(p), p) for p in (Path("/Volumes"),) if system == "darwin"]
        named += [(str(p), p) for p in (Path("/media") / user, Path("/mnt"), Path("/run/media") / user) if system == "linux"]
    out, seen = [], set()
    for name, path in named:
        if path is None or not readable(path):
            continue
        real = os.path.realpath(path)
        if real not in seen:
            seen.add(real)
            out.append({"name": name, "path": real})
    return out


def listing(text: str) -> dict:
    """The folders in a folder (by name; hidden ones and links left out), and the folder above it."""
    folder = check(text)
    out, more = [], False
    try:
        with os.scandir(folder) as entries:
            for e in entries:
                try:
                    if _hidden(e) or is_link(e) or not e.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                if len(out) >= MAX_LISTED:
                    more = True
                    break
                out.append({"name": e.name, "path": str(folder / e.name)})
    except PermissionError:
        raise FolderError(f"Craft Conductor isn't allowed to open {folder}") from None
    except OSError as e:
        raise FolderError(f"couldn't open {folder}: {e.strerror or e}") from None
    out.sort(key=lambda x: x["name"].casefold())
    parent = folder.parent if folder.parent != folder else None
    return {"path": str(folder), "parent": str(parent) if parent else None, "folders": out, "more": more}
