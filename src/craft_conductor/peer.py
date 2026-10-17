"""Which program on this computer opened a connection to the control panel.

A connection from this computer's own address (127.0.0.1) is usually a browser here, but it can
also be a tunnel's program passing on requests from the internet: playit.gg's agent,
cloudflared, Tailscale, ngrok, SSH… Some of them say so in a header and some don't (playit.gg's
tunnels add nothing), so "on this computer" (the password reset, a PIN, the local-only actions)
also needs the connection's program to be found, to run as this account, and not to be one of
those. Anything that can't be told counts as not on this computer.

Windows: GetExtendedTcpTable (iphlpapi) gives the program's process; Linux: /proc/net/tcp gives
the account, then /proc/<pid>/fd the process; macOS: lsof.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Programs that pass on connections from elsewhere (by their file name, without .exe).
TUNNEL_PROGRAMS = frozenset({
    "cloudflared", "tailscale", "tailscaled", "tailscale-ipn", "ngrok", "frpc", "bore", "zrok", "localtonet",
    "ssh", "sshd", "plink", "putty", "kitty", "autossh", "socat", "ncat", "nc", "netcat", "stunnel", "rathole",
    "chisel", "inlets", "pinggy", "expose", "devtunnel", "code-tunnel", "tunnelto",
})
TUNNEL_PREFIXES = ("playit",)  # playit.gg's agent: playit, playitd, playitd-service…


@dataclass(frozen=True)
class Program:
    pid: int | None
    path: str = ""          # its file, when it could be read
    other_account: bool = False  # it runs as another account on this computer (a service, say)

    @property
    def name(self) -> str:
        base = re.split(r"[\\/]", self.path)[-1].lower()
        return base[:-4] if base.endswith(".exe") else base


def is_tunnel(name: str) -> bool:
    name = name.lower().removesuffix(".exe")
    return name in TUNNEL_PROGRAMS or name.startswith(TUNNEL_PREFIXES)


def a_person_here(peer: tuple, server_port: int) -> bool:
    """Whether the connection from ``peer`` (its address and port, as the listener saw them) to
    ``server_port`` was opened by a program of this account that isn't a tunnel. False when it
    can't be told."""
    try:
        prog = program(peer, server_port)
    except Exception:  # (any surprise from the operating system: not here)
        return False
    return prog is not None and not prog.other_account and bool(prog.path) and not is_tunnel(prog.name)


def program(peer: tuple, server_port: int) -> Program | None:
    host, port = str(peer[0]), int(peer[1])
    try:
        ip = ipaddress.ip_address(host.split("%")[0])
    except ValueError:
        return None
    if not ip.is_loopback and not (ip.version == 6 and ip.ipv4_mapped and ip.ipv4_mapped.is_loopback):
        return None
    if os.name == "nt":
        return _windows(ip, port, server_port)
    if sys.platform.startswith("linux"):
        return _linux(ip, port, server_port)
    if sys.platform == "darwin":
        return _mac(port, server_port)
    return None


# ------------------------------------------------------------------- Windows
def _windows(ip, port: int, server_port: int) -> Program | None:
    import ctypes
    from ctypes import wintypes
    iphlpapi = ctypes.WinDLL("iphlpapi")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    TCP_TABLE_OWNER_PID_ALL = 5
    rows = []
    for family, row_size in ((socket.AF_INET, 24), (23, 56)):  # (AF_INET6 is 23 on Windows)
        size = wintypes.DWORD(0)
        iphlpapi.GetExtendedTcpTable(None, ctypes.byref(size), False, family, TCP_TABLE_OWNER_PID_ALL, 0)
        for _ in range(4):  # (the table can grow between the two calls)
            buf = ctypes.create_string_buffer(size.value + 4096)
            size = wintypes.DWORD(len(buf))
            if iphlpapi.GetExtendedTcpTable(buf, ctypes.byref(size), False, family, TCP_TABLE_OWNER_PID_ALL, 0) == 0:
                break
        else:
            continue
        raw = buf.raw
        count = struct.unpack_from("<I", raw, 0)[0]
        for i in range(count):
            off = 4 + i * row_size
            if family == socket.AF_INET:
                _state, laddr, lport, _raddr, rport, pid = struct.unpack_from("<IIIIII", raw, off)
                local = socket.inet_ntoa(struct.pack("<I", laddr))
            else:
                local = socket.inet_ntop(socket.AF_INET6, raw[off:off + 16])
                lport, = struct.unpack_from("<I", raw, off + 20)
                rport, = struct.unpack_from("<I", raw, off + 44)
                pid, = struct.unpack_from("<I", raw, off + 52)
            rows.append((local, socket.ntohs(lport & 0xFFFF), socket.ntohs(rport & 0xFFFF), pid))
    pids = {pid for local, lport, rport, pid in rows if lport == port and rport == server_port and _same(local, ip)}
    if len(pids) != 1:
        return None
    pid = pids.pop()
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                    ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return Program(pid, other_account=True)  # (a service, or a program run as administrator: not readable)
    try:
        name = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(name))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(length)):
            return Program(pid)
        return Program(pid, name.value, other_account=not _same_windows_account(handle))
    finally:
        kernel32.CloseHandle(handle)


def _same_windows_account(handle) -> bool:
    """Whether the process runs as the account Craft Conductor runs as (its token's user SID)."""
    import ctypes
    from ctypes import wintypes
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                             ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetLengthSid.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    TOKEN_QUERY, TokenUser = 0x0008, 1

    def sid_of(process) -> bytes | None:
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
            return None
        try:
            size = wintypes.DWORD(0)
            advapi32.GetTokenInformation(token, TokenUser, None, 0, ctypes.byref(size))
            buf = ctypes.create_string_buffer(size.value or 256)
            if not advapi32.GetTokenInformation(token, TokenUser, buf, len(buf), ctypes.byref(size)):
                return None
            sid = ctypes.c_void_p.from_buffer(buf).value  # (TOKEN_USER starts with the SID's address)
            length = advapi32.GetLengthSid(ctypes.c_void_p(sid))
            return ctypes.string_at(sid, length)
        finally:
            kernel32.CloseHandle(token)
    theirs, ours = sid_of(handle), sid_of(kernel32.GetCurrentProcess())
    return theirs is not None and theirs == ours


# --------------------------------------------------------------------- Linux
def _same(address: str, ip) -> bool:
    """The same address, 127.0.0.1 and ::ffff:127.0.0.1 alike."""
    a = ipaddress.ip_address(address.split("%")[0])
    return (getattr(a, "ipv4_mapped", None) or a) == (getattr(ip, "ipv4_mapped", None) or ip)


def _proc_addr(text: str) -> tuple[str, int]:
    addr, port = text.split(":")
    raw = bytes.fromhex(addr)
    # (each 32-bit word is written in this computer's byte order)
    words = b"".join(struct.pack("=I", struct.unpack(">I", raw[i:i + 4])[0]) for i in range(0, len(raw), 4))
    family = socket.AF_INET if len(raw) == 4 else socket.AF_INET6
    return str(ipaddress.ip_address(socket.inet_ntop(family, words))), int(port, 16)


def _linux(ip, port: int, server_port: int, proc: Path = Path("/proc")) -> Program | None:
    found = []
    for table in ("tcp", "tcp6"):
        try:
            lines = (proc / "net" / table).read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            f = line.split()
            if len(f) < 10:
                continue
            local, remote = _proc_addr(f[1]), _proc_addr(f[2])
            if local[1] == port and remote[1] == server_port and _same(local[0], ip):
                found.append((int(f[7]), f[9]))  # (the account, and the socket's inode)
    if len(found) != 1:
        return None
    uid, inode = found[0]
    if uid != os.geteuid():
        return Program(None, other_account=True)
    target = f"socket:[{inode}]"
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if any(os.readlink(fd) == target for fd in (entry / "fd").iterdir()):
                try:
                    return Program(int(entry.name), os.readlink(entry / "exe"))
                except OSError:
                    return Program(int(entry.name), (entry / "comm").read_text().strip())
        except OSError:
            continue
    return None


# --------------------------------------------------------------------- macOS
def _mac(port: int, server_port: int) -> Program | None:
    lsof = "/usr/sbin/lsof"
    if not os.path.exists(lsof):
        return None
    try:
        out = subprocess.run([lsof, "-nP", f"-iTCP:{port}", "-sTCP:ESTABLISHED", "-Fpcun"],
                             capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    pid = cmd = uid = None
    matches = []
    for line in out.splitlines():
        kind, value = line[:1], line[1:]
        if kind == "p":
            pid, cmd, uid = int(value), None, None
        elif kind == "c":
            cmd = value
        elif kind == "u":
            uid = int(value)
        elif kind == "n" and re.search(rf":{port}->[^ ]*:{server_port}$", value):
            matches.append((pid, cmd or "", uid))
    if len({m[0] for m in matches}) != 1:
        return None
    pid, cmd, uid = matches[0]
    return Program(pid, cmd, other_account=uid is not None and uid != os.geteuid())


def program_file(pid: int) -> str:
    """The file a running process was started from ("" if it isn't running or can't be read)."""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                            ctypes.POINTER(wintypes.DWORD)]
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel32.OpenProcess(0x1000, False, int(pid))
            if not handle:
                return ""
            try:
                name = ctypes.create_unicode_buffer(32768)
                length = wintypes.DWORD(len(name))
                return name.value if kernel32.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(length)) else ""
            finally:
                kernel32.CloseHandle(handle)
        return os.readlink(f"/proc/{int(pid)}/exe")
    except (OSError, ValueError, AttributeError):
        return ""
