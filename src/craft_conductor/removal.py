"""Deleting folders, including read-only ones.

Windows won't delete a file or folder marked read-only, and some are: files a program set that way,
and every folder OneDrive syncs (#216). ``shutil.rmtree`` then fails (or, told to ignore errors,
silently leaves the folder behind). This clears the mark and tries again.
"""

from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path


def rmtree(path: str | os.PathLike, ignore_errors: bool = False) -> None:
    """``shutil.rmtree``, for read-only files and folders too."""
    top = os.path.abspath(path)

    def again(func, p, exc):
        exc = exc[1] if isinstance(exc, tuple) else exc  # (onerror gets sys.exc_info())
        if isinstance(exc, PermissionError):
            try:
                os.chmod(p, stat.S_IWRITE | stat.S_IREAD | (stat.S_IEXEC if os.path.isdir(p) else 0))
                parent = os.path.dirname(os.path.abspath(p))
                # (elsewhere a folder's own mark says no; here its parent's, and only one inside what's deleted is changed)
                if os.name != "nt" and (parent == top or parent.startswith(top + os.sep)) and not os.access(parent, os.W_OK):
                    os.chmod(parent, stat.S_IRWXU)
                func(p)
                return
            except OSError as e:
                exc = e
        if isinstance(exc, FileNotFoundError):
            return  # (gone already: what was wanted)
        if not ignore_errors:
            raise exc
    if ignore_errors and not os.path.lexists(path):
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=again)
    else:
        shutil.rmtree(path, onerror=again)


def gone(path: Path) -> bool:
    """Delete a folder if it can be; whether it's gone."""
    rmtree(path, ignore_errors=True)
    return not os.path.lexists(path)
