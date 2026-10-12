"""Files that hold a secret are readable by this computer's account only.

A secret Craft Conductor has to use (the CurseForge key, the Discord token and webhook, the push
and HTTPS keys, the friends' invite secrets, the RCON password) can't be kept as a hash, so the
files holding one are this account's alone: 0600 on Linux and macOS; on Windows, an access list of
this account, SYSTEM and the Administrators (who can open any file anyway), with nothing inherited
from the folder. Without it, a file on another drive (``E:\\...``) or in a shared folder is
readable by every account on the computer. Passwords Craft Conductor only checks are kept as
hashes besides (webauth).
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

log = logging.getLogger(__name__)

_protected: set[tuple] = set()  # (protect_once: path and file identity)
_warned: set[str] = set()      # folders where it couldn't be done, said once
_sid: str | None = None        # this account's Windows SID


def protect(path: Path) -> bool:
    """Make ``path`` readable and writable by this account only. False (said once per folder in
    the log) where it can't be done: a drive without access lists, a read-only mount, a file
    owned by another account."""
    try:
        if os.name == "nt":
            _owner_only_windows(str(path))
        else:
            os.chmod(path, 0o600)
        return True
    except OSError as e:
        folder = str(Path(path).parent)
        if folder not in _warned:
            _warned.add(folder)
            log.warning("couldn't make %s readable by this account only (%s)", path, e)
        return False


def write_text(path: Path, text: str) -> None:
    """Write a file that holds a secret, whole or not at all: the new file is made this account's
    before the secret goes in, then put in place."""
    tmp = path.with_name(path.name + ".tmp")
    os.close(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600))
    protect(tmp)
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_bytes(path: Path, data: bytes) -> None:
    """write_text() for bytes."""
    tmp = path.with_name(path.name + ".tmp")
    os.close(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600))
    protect(tmp)
    tmp.write_bytes(data)
    os.replace(tmp, path)


def protect_once(path: Path) -> None:
    """protect(), for a file checked each time it's read: once, and again after it's been replaced
    (an editor that saves by writing a new file gives it the folder's permissions)."""
    try:
        st = os.stat(path)
    except OSError:
        return
    key = (str(path), st.st_dev, st.st_ino)
    if key not in _protected:
        _protected.add(key)
        protect(path)


def _owner_only_windows(path: str) -> None:
    import ctypes
    from ctypes import wintypes
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    advapi32.GetSecurityDescriptorDacl.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    advapi32.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    # Full control for SYSTEM, the Administrators and this account; "P": nothing inherited.
    sddl = f"D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;{_account_sid(advapi32, kernel32)})"
    sd = ctypes.c_void_p()
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(sd), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
        if not advapi32.GetSecurityDescriptorDacl(sd, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
            raise ctypes.WinError(ctypes.get_last_error())
        SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, PROTECTED_DACL_SECURITY_INFORMATION = 1, 0x4, 0x80000000
        err = advapi32.SetNamedSecurityInfoW(path, SE_FILE_OBJECT,
                                             DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
                                             None, None, dacl, None)
        if err:
            raise ctypes.WinError(err)
    finally:
        kernel32.LocalFree(sd)


def _account_sid(advapi32, kernel32) -> str:
    """This process's account, as an SID string (S-1-5-21-...)."""
    global _sid
    if _sid:
        return _sid
    import ctypes
    from ctypes import wintypes
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                             ctypes.POINTER(wintypes.DWORD)]
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    TOKEN_QUERY, TOKEN_USER = 0x0008, 1
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(token, TOKEN_USER, None, 0, ctypes.byref(size))
        buf = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(token, TOKEN_USER, buf, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        psid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]  # TOKEN_USER.User.Sid
        text = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(psid, ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            sid = text.value or ""
        finally:
            kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))
    finally:
        kernel32.CloseHandle(token)
    if not re.fullmatch(r"S-1(-\d+)+", sid):
        raise OSError(f"unexpected account id {sid!r}")
    _sid = sid
    return sid
