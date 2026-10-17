"""Passwords are kept only as hashes; files that hold a secret are this account's only (the
owner's rule: a password Craft Conductor only checks is hashed; a secret it has to use can't be,
so the file holding it is readable by this account alone)."""

import json
import logging
import os
import re
import stat
import tomllib

from craft_conductor import config as configmod, private, snapshots, webauth
from craft_conductor.properties import write_properties


def _sddl(descriptor, ctypes, wintypes) -> str:
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR), ctypes.c_void_p]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    text = wintypes.LPWSTR()
    assert advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, 1, 0x4, ctypes.byref(text), None)
    try:
        return text.value
    finally:
        kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))


def windows_access(path) -> str:
    """The file's access list, in Windows' own notation (SDDL)."""
    import ctypes
    from ctypes import wintypes
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.GetFileSecurityW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                          ctypes.POINTER(wintypes.DWORD)]
    need = wintypes.DWORD()
    advapi32.GetFileSecurityW(str(path), 0x4, None, 0, ctypes.byref(need))
    buf = ctypes.create_string_buffer(need.value)
    assert advapi32.GetFileSecurityW(str(path), 0x4, buf, need, ctypes.byref(need))
    return _sddl(buf, ctypes, wintypes)


def windows_spelling(sddl: str) -> str:
    """An access list as Windows writes it back: well-known accounts by their alias (an account
    that's the computer's built-in Administrator, as on GitHub's runners, is "LA")."""
    import ctypes
    from ctypes import wintypes
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    sd = ctypes.c_void_p()
    assert advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(sd), None)
    try:
        return _sddl(sd, ctypes, wintypes)
    finally:
        ctypes.WinDLL("kernel32").LocalFree(sd)


def only_mine(path) -> bool:
    """Readable by this account only: 0600, or on Windows full control for this account, SYSTEM and
    the Administrators, nothing inherited from the folder."""
    if os.name != "nt":
        return stat.S_IMODE(path.stat().st_mode) == 0o600
    actual = windows_access(path)
    expected = windows_spelling(f"D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;{private._sid})")
    return actual.startswith("D:P") and sorted(re.findall(r"\([^)]*\)", actual)) == sorted(re.findall(r"\([^)]*\)", expected))


def access(path) -> str:
    """What the file's permissions are, for a failed assertion."""
    if os.name != "nt":
        return oct(stat.S_IMODE(path.stat().st_mode))
    return f"{windows_access(path)} (expected this account {private._sid}, SYSTEM, Administrators)"


def test_a_file_that_holds_a_secret_is_this_accounts_only(tmp_path):
    path = tmp_path / "secret.json"
    private.write_text(path, '{"key": "fake-key-for-tests"}')
    assert path.read_text(encoding="utf-8") == '{"key": "fake-key-for-tests"}'
    assert only_mine(path), access(path)
    assert not (tmp_path / "secret.json.tmp").exists()
    other = tmp_path / "made-elsewhere.txt"
    other.write_text("x")
    assert private.protect(other)
    assert only_mine(other), access(other)


def test_secret_bytes_are_written_to_a_file_that_is_this_accounts_only(tmp_path):
    path = tmp_path / "secret.key"
    private.write_bytes(path, b"fake-key-bytes-for-tests")
    assert path.read_bytes() == b"fake-key-bytes-for-tests"
    assert only_mine(path), access(path)
    private.write_bytes(path, b"fake-replacement-for-tests")  # (a file put in place again stays private)
    assert path.read_bytes() == b"fake-replacement-for-tests"
    assert only_mine(path), access(path)
    assert not (tmp_path / "secret.key.tmp").exists()


def test_a_web_password_typed_into_craft_conductor_toml_is_kept_as_its_hash(tmp_path):
    root = tmp_path / "server"
    root.mkdir()
    password = "Open#Sesame-42"  # (a # inside the quotes: STRONG_RULES suggest one)
    toml = root / configmod.CONFIG_NAME
    toml.write_text(f'[server]\nloader = "fabric"\n\n[web]\npassword = "{password}"   # mine\nhost = "127.0.0.1"\n',
                    encoding="utf-8")
    # A backup note from before: it kept craft-conductor.toml's text, password and all.
    backups = configmod.parse(root, {"server": {"loader": "fabric"}}).backups.dir
    backups.mkdir(parents=True)
    note = backups / "before-update.tar.gz.json"
    note.write_text(json.dumps({"toml": toml.read_text(encoding="utf-8"), "properties": {"motd": "x"}}))

    cfg = configmod.load(root)
    text = toml.read_text(encoding="utf-8")
    assert password not in text and webauth.is_hashed(cfg.web.password)
    assert f'password = "{cfg.web.password}"   # mine' in text and 'host = "127.0.0.1"' in text  # (the rest as it was)
    assert only_mine(toml), access(toml)
    auth = webauth.AuthStore(cfg).get()
    assert auth.managed and auth.check(password) and not auth.check("open#sesame-42")
    assert auth.strong  # (it met STRONG_RULES, so other devices may still sign in with it)
    assert configmod.load(root).web.password == cfg.web.password  # (hashed once)
    kept = json.loads(note.read_text())
    assert password not in note.read_text() and tomllib.loads(kept["toml"])["web"]["password"] == ""
    assert webauth.is_hashed(snapshots._opened(kept["secrets"])["toml"]["web.password"])  # (locked here, and hashed)
    assert kept["properties"] == {"motd": "x"}
    assert only_mine(note), access(note)
    # An editor that saves by writing a new file: the next read makes it this account's again.
    replaced = root / "saved-by-an-editor.toml"
    replaced.write_text(toml.read_text(encoding="utf-8"), encoding="utf-8")
    os.replace(replaced, toml)
    configmod.load(root)
    assert only_mine(toml), access(toml)
    # Changing it is typing a new one there: it's hashed in turn (a weak one isn't enough for other devices).
    configmod.set_value(toml, "web", "password", '"letmein"')
    weak = webauth.AuthStore(configmod.load(root)).get()
    assert weak.check("letmein") and not weak.strong and "letmein" not in toml.read_text(encoding="utf-8")
    # A backup made before Craft Conductor reads the file again doesn't keep it either.
    found = snapshots._secrets('[web]\npassword = "Typed-Now-2!"\n', {})
    assert webauth.is_hashed(found["toml"]["web.password"])
    assert snapshots._without('[web]\npassword = "Typed-Now-2!"\n', {}, found)[0] == '[web]\npassword = ""\n'


def test_a_password_in_a_read_only_toml_still_works(tmp_path, monkeypatch, caplog):
    """In Docker the file can be mounted read-only: the password works, and the log says once that
    it's still there as typed."""
    root = tmp_path / "server"
    root.mkdir()
    (root / configmod.CONFIG_NAME).write_text('[server]\nloader = "fabric"\n[web]\npassword = "Typed-In-Docker!1"\n',
                                              encoding="utf-8")

    def read_only(*args, **kwargs):
        raise PermissionError(30, "Read-only file system")
    monkeypatch.setattr(configmod, "set_value", read_only)
    with caplog.at_level(logging.WARNING):
        cfg = configmod.load(root)
        configmod.load(root)
    assert webauth.AuthStore(cfg).get().check("Typed-In-Docker!1")
    assert caplog.text.count("still there as typed") == 1


def test_a_password_typed_into_hub_json_is_kept_as_its_hash(tmp_path):
    from craft_conductor.hub import Hub
    state = tmp_path / "home" / configmod.STATE_DIR
    state.mkdir(parents=True)
    (state / "hub.json").write_text(json.dumps({"web": {"password": "Hub-Password-9!"}}))
    hub = Hub(tmp_path / "home")
    saved = json.loads((state / "hub.json").read_text())["web"]["password"]
    assert webauth.is_hashed(saved) and hub.web.password == saved
    assert webauth.AuthStore(hub).get().check("Hub-Password-9!")
    assert only_mine(state / "hub.json"), access(state / "hub.json")
def test_a_secret_minecraft_writes_into_server_properties_is_kept_private(hub_env):
    """Minecraft 1.21.9 and newer write a generated secret (their management server's) into
    server.properties themselves: once the server has started, the file is this account's only."""
    hub, _ = hub_env
    d = hub.get("alpha")
    props = d.m.server_dir / "server.properties"
    with open(props, "a", encoding="utf-8") as f:  # (as Minecraft writes it: with the folder's permissions)
        f.write("management-server-secret=fake-secret-for-tests\n")
    assert d.start_server() == "started"
    try:
        assert only_mine(props), access(props)
    finally:
        d.stop_server()


def test_files_that_hold_a_secret_are_made_this_accounts_only(tmp_path):
    toml = tmp_path / configmod.CONFIG_NAME
    configmod.write_text(toml, '[server]\nloader = "fabric"\n')
    configmod.set_value(toml, "notify", "discord_webhook", '"https://discord.com/api/webhooks/0/fake-webhook-for-tests"')
    assert only_mine(toml), access(toml)
    props = tmp_path / "server.properties"
    write_properties(props, {"motd": "A server"})
    write_properties(props, {"enable-rcon": "true", "rcon.password": "fake-rcon-password-for-tests"})
    assert only_mine(props), access(props)