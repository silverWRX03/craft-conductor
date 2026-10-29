"""Reading the file list of a zip on a web server without downloading it.

A zip keeps its list of files at the end, so a few small range requests are enough to say what a
600 MB server pack holds (curseforgepack.py asks that of a pack's official server pack).
"""

from __future__ import annotations

import io
import urllib.parse
import zipfile

from .http import HttpClient, HttpError

BLOCK = 256 << 10          # asked for at a time (the end of the file first, where the list is)
MAX_READ = 32 << 20        # a zip whose list needs more than this isn't a modpack's


class RemoteFile(io.RawIOBase):
    """A read-only, seekable view of a file on a server that answers range requests."""

    def __init__(self, http: HttpClient, url: str):
        self.http, self.url = http, url
        self.pos = self.fetched = 0
        self._block: tuple[int, bytes] = (0, b"")
        data, self.size = http.get_range(url, -BLOCK, BLOCK)
        self._block, self.fetched = (self.size - len(data), data), len(data)

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self.pos, io.SEEK_END: self.size}[whence]
        self.pos = max(0, base + offset)
        return self.pos

    def read(self, n: int = -1) -> bytes:
        end = self.size if n is None or n < 0 else min(self.size, self.pos + n)
        out = bytearray()
        while self.pos < end:
            start, data = self._block
            if not start <= self.pos < start + len(data):
                if self.fetched >= MAX_READ:
                    raise OSError("that zip's list of files is too big to read from a server")
                data, _ = self.http.get_range(self.url, self.pos, min(BLOCK, self.size - self.pos))
                if not data:
                    break
                self._block, self.fetched = (self.pos, data), self.fetched + len(data)
                start = self.pos
            chunk = self._block[1][self.pos - start:end - start]
            out += chunk
            self.pos += len(chunk)
        return bytes(out)

    def readinto(self, buffer) -> int:
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)


def names(http: HttpClient, url: str) -> list[str]:
    """The names of the files in the zip at ``url``. A server that answers a range request with an
    error but redirects a plain one (CurseForge's edge.forgecdn.net, #191) is asked where the file
    really is, and that place is read instead."""
    try:
        remote = RemoteFile(http, url)
    except HttpError:
        real = http.final_url(url)
        if real == url or urllib.parse.urlsplit(real).scheme != "https":
            raise
        remote = RemoteFile(http, real)
    with zipfile.ZipFile(remote) as z:
        return z.namelist()
