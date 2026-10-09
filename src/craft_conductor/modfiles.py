"""Mod files kept by their hash, shared by every server here.

The file check (filecheck.py) looks inside mods before they're installed: on the setup page,
before the server exists, and for players' mods the server never runs. Those files are kept
here, so installing the server afterwards takes them from here instead of downloading them
again. Only checked files go in (Modrinth's or CurseForge's hash), and only from their
download servers. The oldest are removed when the folder grows past its limit.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path

from .http import sha1_file

log = logging.getLogger(__name__)

LIMIT_BYTES = 2 << 30   # the oldest files go past this
MAX_FILE = 256 << 20    # a mod bigger than this isn't kept
_HASH = re.compile(r"[0-9a-f]{40}|[0-9a-f]{128}")


class Store:
    def __init__(self, folder: Path, http, limit: int = LIMIT_BYTES):
        self.folder = folder
        self.http = http
        self.limit = limit
        self._lock = threading.Lock()

    @staticmethod
    def _name(sha1: str | None, sha512: str | None) -> str | None:
        for h in (sha1, sha512):
            if h and _HASH.fullmatch(h.lower()):
                return h.lower()[:64] + ".jar"
        return None

    def find(self, sha1: str | None, sha512: str | None = None) -> Path | None:
        """The kept file with this hash, if it's here (marked as just used)."""
        name = self._name(sha1, sha512)
        path = self.folder / name if name else None
        if path is None or not path.is_file():
            return None
        try:
            os.utime(path)
        except OSError:
            pass
        return path

    def get(self, url: str, sha1: str | None, sha512: str | None = None) -> Path:
        """The file, downloaded (and checked against its hash) unless it's here already. Raises
        ValueError for a file without a hash or from somewhere else than the mod sites."""
        from .clientpack import allowed_url
        name = self._name(sha1, sha512)
        if name is None or not allowed_url(url):
            raise ValueError("only checked files from Modrinth or CurseForge are kept")
        found = self.find(sha1, sha512)
        if found is not None:
            return found
        self.folder.mkdir(parents=True, exist_ok=True)
        dest = self.folder / name
        self.http.download(url, dest, sha1=sha1, sha512=sha512, max_bytes=MAX_FILE)
        self.prune()
        return dest

    def copy_to(self, sha1: str | None, dest: Path) -> bool:
        """Copy the kept file with this sha1 to ``dest`` (checked again first). False if it isn't here."""
        import shutil
        found = self.find(sha1)
        if found is None or not sha1 or sha1_file(found) != sha1.lower():
            return False
        shutil.copy2(found, dest)
        return True

    def prune(self) -> None:
        with self._lock:
            try:
                files = [(p.stat().st_mtime, p.stat().st_size, p) for p in self.folder.glob("*.jar")]
            except OSError:
                return
            total = sum(size for _, size, _ in files)
            for _, size, path in sorted(files):
                if total <= self.limit:
                    break
                try:
                    path.unlink()
                    total -= size
                except OSError as e:
                    log.debug("couldn't remove %s: %s", path.name, e)
