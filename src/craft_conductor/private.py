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


def keep_access(src: Path, dst: Path) -> bool:
    """Give a copy (``dst``, made but still empty) the original's permissions when they're its own,
    not its folder's: a file made this account's only stays so in its new place (on another drive
    it would otherwise take that folder's, readable by every account). Other files keep the
    permissions of the folder they're copied to. False (said once per folder in the log) where it
    can't be done, as protect()."""
    try:
        if os.name == "nt":
            _keep_access_windows(str(src), str(dst))
        else:
            os.chmod(dst, os.stat(src).st_mode & 0o7777)
        return True
    except OSError as e:
        folder = str(Path(dst).parent)
        if folder not in _warned:
            _warned.add(folder)
            log.warning("couldn't give %s the permissions of %s (%s)", dst, src, e)
        return False


def own_folder(path: Path) -> bool:
    """Make ``path`` a folder only this account can use (with SYSTEM and the Administrators), made if it
    isn't there, for a folder in a place every account can write to (Windows' ProgramData). Its files
    take its permissions. False where it can't be: when the folder is there but another account made
    it, or it's a link (it could hold anything), or the permissions can't be set."""
    try:
        made = False
        try:
            os.mkdir(path, 0o700)
            made = True
        except FileExistsError:
            pass
        if os.name == "nt":
            st = os.lstat(path)
            if st.st_file_attributes & 0x400 or not os.path.isdir(path):  # (FILE_ATTRIBUTE_REPARSE_POINT)
                raise OSError("it's a link, not a folder")
            mine = {account_sid(), "S-1-5-32-544", "S-1-5-18"}  # (made by this account, elevated, or SYSTEM)
            if _owner_sid(str(path)) not in mine:
                raise OSError("another account made it")
            if made or not _dacl_protected(str(path)):  # (once: it goes down to every file in it)
                _owner_only_windows(str(path), inherit=True)
        else:
            st = os.lstat(path)
            if not os.path.isdir(path) or os.path.islink(path) or st.st_uid != os.getuid():
                raise OSError("another account made it")
            os.chmod(path, 0o700)
        return True
    except OSError as e:
        log.warning("couldn't make %s a folder of this account's own (%s)", path, e)
        return False


def account_sid() -> str:
    """This account's Windows SID (S-1-5-21-...)."""
    import ctypes
    return _account_sid(ctypes.WinDLL("advapi32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True))


def _owner_sid(path: str) -> str:
    """The account that owns ``path``, as an SID string."""
    import ctypes
    from ctypes import wintypes
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    SE_FILE_OBJECT, OWNER_SECURITY_INFORMATION = 1, 0x1
    owner, sd = ctypes.c_void_p(), ctypes.c_void_p()
    err = advapi32.GetNamedSecurityInfoW(path, SE_FILE_OBJECT, OWNER_SECURITY_INFORMATION, ctypes.byref(owner),
                                         None, None, None, ctypes.byref(sd))
    if err:
        raise ctypes.WinError(err)
    try:
        text = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(owner, ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return text.value or ""
        finally:
            kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))
    finally:
        kernel32.LocalFree(sd)


def _keep_access_windows(src: str, dst: str) -> None:
    _with_dacl(src, lambda protected, dacl: protected and _set_dacl(dst, dacl))  # (else the copy takes its new folder's)


def _dacl_protected(path: str) -> bool:
    """Whether ``path`` has permissions of its own (nothing inherited from its folder)."""
    return _with_dacl(path, lambda protected, dacl: protected)


def _with_dacl(path: str, use):
    """``use(protected, dacl)`` with ``path``'s access list, and whether it's its own (not its folder's)."""
    import ctypes
    from ctypes import wintypes
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetSecurityDescriptorControl.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD)]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, SE_DACL_PROTECTED = 1, 0x4, 0x1000
    dacl, sd = ctypes.c_void_p(), ctypes.c_void_p()
    err = advapi32.GetNamedSecurityInfoW(path, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, None, None,
                                         ctypes.byref(dacl), None, ctypes.byref(sd))
    if err:
        raise ctypes.WinError(err)
    try:
        control, revision = wintypes.WORD(), wintypes.DWORD()
        if not advapi32.GetSecurityDescriptorControl(sd, ctypes.byref(control), ctypes.byref(revision)):
            raise ctypes.WinError(ctypes.get_last_error())
        return use(bool(control.value & SE_DACL_PROTECTED), dacl)
    finally:
        kernel32.LocalFree(sd)


def _set_dacl(path: str, dacl) -> None:
    """Give ``path`` the access list ``dacl``, as its own (nothing inherited from its folder)."""
    import ctypes
    from ctypes import wintypes
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, PROTECTED_DACL_SECURITY_INFORMATION = 1, 0x4, 0x80000000
    err = advapi32.SetNamedSecurityInfoW(path, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
                                         None, None, dacl, None)
    if err:
        raise ctypes.WinError(err)


def _owner_only_windows(path: str, inherit: bool = False) -> None:
    import ctypes
    from ctypes import wintypes
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    advapi32.GetSecurityDescriptorDacl.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    # Full control for SYSTEM, the Administrators and this account; "P": nothing inherited; "OICI": a
    # folder's files and folders take it.
    flags = "OICI" if inherit else ""
    sddl = f"D:P(A;{flags};FA;;;SY)(A;{flags};FA;;;BA)(A;{flags};FA;;;{_account_sid(advapi32, kernel32)})"
    sd = ctypes.c_void_p()
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(sd), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
        if not advapi32.GetSecurityDescriptorDacl(sd, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
            raise ctypes.WinError(ctypes.get_last_error())
        _set_dacl(path, dacl)
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
