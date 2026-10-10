
from pathlib import Path
import pytest

from craft_conductor import backup, config as configmod
from craft_conductor.config import ConfigError, ModSpec, parse_duration
from craft_conductor.java import JavaError
from craft_conductor.java import JavaManager, parse_major
from craft_conductor.loaders.base import version_key
from craft_conductor.loaders.forge import NEOFORGE_VERSIONS, NeoForgeLoader, neoforge_prefix
from craft_conductor.loaders.fabric import FABRIC_META, QUILT_META, FabricLoader, QuiltLoader
from craft_conductor.process import PLAYERS, READY
from craft_conductor.rcon import decode, encode

from conftest import FakeMojang


def test_durations():
    assert parse_duration("6h") == 21600
    assert parse_duration("30m") == 1800
    assert parse_duration(90) == 90
    with pytest.raises(ConfigError):
        parse_duration("soon")


def test_template_loads_and_mod_blocks_round_trip(tmp_path):
    (tmp_path / "craft-conductor.toml").write_text(configmod.render_template("neoforge", "1.21.1"))
    path = tmp_path / "craft-conductor.toml"
    configmod.append_mod(path, ModSpec("modrinth", "create"))
    configmod.append_mod(path, ModSpec("curseforge", "238222", required=False))
    cfg = configmod.load(tmp_path)
    assert cfg.server.loader == "neoforge"
    assert [(m.source, m.id, m.required) for m in cfg.mods] == [
        ("modrinth", "create", True), ("curseforge", "238222", False)]

    assert configmod.remove_mod(path, "modrinth", "create")
    assert not configmod.remove_mod(path, "modrinth", "create")
    cfg = configmod.load(tmp_path)
    assert [m.id for m in cfg.mods] == ["238222"]
    assert "# Craft Conductor configuration" in path.read_text()  # comments survive edits


def test_setting_required_changes_only_that(tmp_path):
    path = tmp_path / "craft-conductor.toml"
    path.write_text(configmod.render_template("fabric", "1.21.1"))
    configmod.append_mod(path, ModSpec("modrinth", "betamod", channel="beta"))
    path.write_text(path.read_text() + '\n[[mods]]\nid = "byhand"  # added by hand\ndatapack = true')
    configmod.append_mod(path, ModSpec("curseforge", "238222", required=False))
    assert configmod.set_mod_required(path, "modrinth", "betamod", False)
    assert configmod.set_mod_required(path, "modrinth", "byhand", False)  # (no `required` line yet)
    assert configmod.set_mod_required(path, "curseforge", "238222", True)
    assert not configmod.set_mod_required(path, "modrinth", "238222", True)  # (another site's)
    mods = configmod.load(tmp_path).mods
    assert [(m.id, m.required, m.channel, m.datapack) for m in mods] == [
        ("betamod", False, "beta", False), ("byhand", False, None, True), ("238222", True, None, False)]
    assert "# added by hand" in path.read_text()


def test_invalid_config(tmp_path):
    (tmp_path / "craft-conductor.toml").write_text('[server]\nloader = "bukkit"\n')
    with pytest.raises(ConfigError, match="server.loader"):
        configmod.load(tmp_path)


def test_java_version_parsing():
    assert parse_major('openjdk version "21.0.4" 2024-07-16') == 21
    assert parse_major('java version "1.8.0_392"') == 8
    assert parse_major('openjdk version "17" 2021-09-14') == 17


def test_java_selection(tmp_path):
    (tmp_path / "craft-conductor.toml").write_text(configmod.render_template("fabric", "1.21.1"))
    cfg = configmod.load(tmp_path)
    cfg.java_versions = {17: "/j17", 21: "/j21"}
    cfg.java_auto_install = False
    majors = {"/j17": 17, "/j21": 21, "java": 25}
    jm = JavaManager(cfg, probe_fn=majors.get)
    assert jm.select(21) == "/j21"
    assert jm.select(17) == "/j17"
    assert jm.select(25) == "java"
    with pytest.raises(JavaError, match="Java 17 is on this computer"):  # a newer one only when asked for
        jm.select(16)
    cfg.java_version = 17
    assert jm.select(16) == "/j17"
    cfg.java_version = 21
    assert jm.select(17) == "/j21"  # forced
    with pytest.raises(JavaError, match="needs Java 25"):
        jm.select(25)


def test_config_set_value_keeps_comments(tmp_path):
    path = tmp_path / "craft-conductor.toml"
    path.write_text(configmod.render_template("fabric", "1.21.1"))
    configmod.set_value(path, "java", "version", "21")
    configmod.set_value(path, "server", "memory", '"8G"')
    configmod.set_value(path, "brand_new", "key", "true")
    cfg = configmod.load(tmp_path)
    assert cfg.java_version == 21
    assert cfg.server.memory == "8G"
    assert "# download Eclipse Temurin" in path.read_text()


def test_server_properties_editing(tmp_path):
    from craft_conductor.properties import read_properties, write_properties
    path = tmp_path / "server.properties"
    path.write_text("#Minecraft server properties\nmotd=old\nview-distance=10\n")
    write_properties(path, {"motd": "new", "server-port": "25570"})
    assert read_properties(path) == {"motd": "new", "view-distance": "10", "server-port": "25570"}
    assert path.read_text().startswith("#Minecraft")


@pytest.mark.parametrize("name", ["我的服务器", "Máy chủ của tôi", "Café ☕", "Ángel's world 🎮", r"Me\You"])
def test_a_server_name_in_any_language(tmp_path, name):
    """A Java properties file: names are written as \\u escapes (plain ASCII, so every Minecraft reads
    them the same, whatever this computer's own text encoding), and read back as they were typed."""
    from craft_conductor.properties import read_properties, write_properties
    path = tmp_path / "server.properties"
    write_properties(path, {"motd": name})
    assert read_properties(path)["motd"] == name
    path.read_bytes().decode("ascii")  # (Windows' own encoding can't hold most of these)
    if "\\" in name:  # (Java reads a lone backslash as an escape)
        assert "motd=Me\\\\You" in path.read_text()


def test_server_properties_as_minecraft_writes_them(tmp_path):
    """Minecraft keeps server.properties in UTF-8 (older ones: ISO-8859-1, with \\u escapes); a value it
    escaped (https\\://) means what it says. Lines craft-conductor doesn't change stay byte for byte."""
    from craft_conductor.properties import read_properties, write_properties
    path = tmp_path / "server.properties"
    utf8 = "#Minecraft server properties\r\nmotd=Ángel's Café\r\nresource-pack=https\\://example.com/a.zip\r\nserver-port=25565\r\n"
    path.write_bytes(utf8.encode("utf-8"))
    assert read_properties(path) == {"motd": "Ángel's Café", "resource-pack": "https://example.com/a.zip",
                                     "server-port": "25565"}
    write_properties(path, {"server-port": "25566"})
    assert path.read_bytes().split(b"\n")[:3] == utf8.encode("utf-8").split(b"\n")[:3]
    assert read_properties(path)["server-port"] == "25566"
    old = b"motd=Caf\xe9 \\u00e0 la plage \\uD83C\\uDFAE\nlevel-name=world\n"  # (ISO-8859-1)
    path.write_bytes(old)
    assert read_properties(path)["motd"] == "Café à la plage 🎮"
    write_properties(path, {"level-name": "world2"})
    assert path.read_bytes().startswith(b"motd=Caf\xe9 ") and read_properties(path)["level-name"] == "world2"


def test_a_new_server_named_in_any_language(tmp_path):
    from craft_conductor import setup as setupmod
    from craft_conductor.properties import read_properties
    cfg = setupmod.configure(tmp_path, setupmod.SetupSpec(motd="我的服务器", accept_eula=True))
    assert read_properties(cfg.server.dir / "server.properties")["motd"] == "我的服务器"


def test_neoforge_versions(http):
    assert neoforge_prefix("1.21.1") == "21.1."
    assert neoforge_prefix("1.21") == "21.0."
    assert neoforge_prefix("26.1") == "26.1."
    http.json[NEOFORGE_VERSIONS] = {"versions": ["21.1.9", "21.1.77", "21.1.100-beta", "21.2.1", "21.1.10"]}
    loader = NeoForgeLoader(http, FakeMojang(http, ["1.21.1"]))
    assert loader.latest_version("1.21.1") == "21.1.77"
    assert loader.latest_version("1.21.4") is None


def test_neoforge_falls_back_to_maven_metadata(http):
    from craft_conductor.http import HttpError
    from craft_conductor.loaders.forge import NEOFORGE_MAVEN
    http.json[NEOFORGE_VERSIONS] = HttpError(NEOFORGE_VERSIONS, 403, "Forbidden")
    texts = {f"{NEOFORGE_MAVEN}/maven-metadata.xml":
             "<metadata><versioning><versions><version>21.1.9</version><version>21.1.77</version>"
             "<version>21.1.100-beta</version></versions></versioning></metadata>"}
    http.texts = texts
    assert NeoForgeLoader(http, FakeMojang(http, ["1.21.1"])).latest_version("1.21.1") == "21.1.77"
    http.json[NEOFORGE_VERSIONS] = {"versions": ["26.1.1", "26.1.2"]}  # (the API leaving older builds out)
    assert NeoForgeLoader(http, FakeMojang(http, ["1.21.1"])).latest_version("1.21.1") == "21.1.77"


def test_fabric_latest_version(http):
    http.json[f"{FABRIC_META}/versions/loader/1.21.1"] = [
        {"loader": {"version": "0.17.0-beta", "stable": False}},
        {"loader": {"version": "0.16.10", "stable": True}},
    ]
    http.json[f"{FABRIC_META}/versions/loader/26.1"] = []
    loader = FabricLoader(http, FakeMojang(http, ["1.21.1"]))
    assert loader.latest_version("1.21.1") == "0.16.10"
    assert loader.latest_version("26.1") is None
    assert loader.latest_version("9.9") is None  # 404 means unsupported


def test_quilt_latest_version_is_the_highest_stable_one(http):
    # Quilt's list isn't sorted: taking the first stable entry picked 0.24.0, which can't
    # start Minecraft 26.1.
    http.json[f"{QUILT_META}/versions/loader/26.1"] = [
        {"loader": {"version": "0.20.0-beta.9"}},
        {"loader": {"version": "0.24.0"}},
        {"loader": {"version": "0.31.0-beta.4"}},
        {"loader": {"version": "0.30.1"}},
        {"loader": {"version": "0.18.4-pre.1"}},
        {"loader": {"version": "0.9.0"}},
    ]
    http.json[f"{QUILT_META}/versions/loader/1.21.1"] = [{"loader": {"version": "0.26.0-beta.1"}}]
    loader = QuiltLoader(http, FakeMojang(http, ["26.1"]))
    assert loader.latest_version("26.1") == "0.30.1"
    assert loader.latest_version("1.21.1") is None
    assert loader.latest_version("9.9") is None  # 404 means unsupported


def test_version_key_orders_prereleases_first():
    assert sorted(["1.2.0", "1.10.0", "1.2.0-beta", "1.9"], key=version_key) == \
        ["1.2.0-beta", "1.2.0", "1.9", "1.10.0"]


def test_mojang_ordering_handles_new_version_scheme(http):
    mojang = FakeMojang(http, ["1.21.9", "1.21.10", "26.1"])
    assert mojang.newer_than("1.21.9") == ["26.1", "1.21.10"]
    assert mojang.latest_release() == "26.1"


def test_log_patterns():
    assert READY.search('[12:00:00] [Server thread/INFO]: Done (4.512s)! For help, type "help"')
    assert READY.search('[12:00:00] [Server thread/INFO] [minecraft/DedicatedServer]: Done (31.2s)! For help')
    assert not READY.search("<steve> Done (1s)! lol")
    assert PLAYERS.search("[Server thread/INFO]: There are 3 of a max of 20 players online: a, b, c").group(1) == "3"


def test_rcon_packets():
    packet = encode(7, 2, "list")
    assert int.from_bytes(packet[:4], "little") == len(packet) - 4
    assert decode(packet[4:]) == (7, 2, "list")


def test_backup_restore_prune(tmp_path):
    server = tmp_path / "server"
    (server / "world").mkdir(parents=True)
    (server / "world" / "level.dat").write_text("v1")
    (server / "logs").mkdir()
    (server / "logs" / "latest.log").write_text("noise")
    backups = tmp_path / "backups"

    archive = backup.create(server, backups, "test", ["logs"])
    (server / "world" / "level.dat").write_text("v2")
    (server / "new.txt").write_text("x")
    backup.restore(archive, server)
    assert (server / "world" / "level.dat").read_text() == "v1"
    assert not (server / "new.txt").exists()
    assert not (server / "logs").exists()

    for i in range(3):
        backup.create(server, backups, f"extra{i}", [])
    backup.prune(backups, 2)
    assert len(backup.list_backups(backups)) == 2


def test_memory_setting(tmp_path, monkeypatch):
    def memory(value):
        return configmod.parse(tmp_path, {"server": {"loader": "fabric", "memory": value}}).server.memory
    assert memory("4g") == "4G" and memory("4096M") == "4096M" and memory("AUTO") == "auto"
    for bad in ("4", "4 GB", "-1G", "0G", "lots"):
        with pytest.raises(ConfigError, match="server.memory"):
            memory(bad)

    # "auto" becomes a real size on the java command line, never -Xmxauto.
    from craft_conductor import setup as setupmod
    from craft_conductor.lock import Lock
    from craft_conductor.manager import Manager
    monkeypatch.setattr(setupmod, "suggested_memory_gb", lambda total=None: 6)
    m = Manager.__new__(Manager)
    m.config = configmod.parse(tmp_path, {"server": {"loader": "fabric", "memory": "auto"}})
    argv = m.launch_argv(Lock(minecraft="1.21.1", launch=["-jar", "server.jar"]), java="java")
    assert argv[:3] == ["java", "-Xms6G", "-Xmx6G"]


def test_web_auth_store(tmp_path):
    from craft_conductor import webauth
    cfg = configmod.parse(tmp_path, {"server": {"loader": "fabric"}})
    store = webauth.AuthStore(cfg)
    auth = store.get()
    assert auth.default and auth.check("PASSWORD") and auth.check("Password") and not auth.check("passwort")
    store.set("pin", "0042")
    assert webauth.AuthStore(cfg).get().check("0042")  # saved
    for mode, secret in (("pin", "123"), ("pin", "123456789"), ("password", "abc"), ("password", "PASSWORD"),
                         ("magic", "x")):
        with pytest.raises(ConfigError):
            store.set(mode, secret)
    assert store.get().check("0042")  # failed changes keep the old one
    with pytest.raises(ConfigError):
        store.set("none")  # there's always a password or PIN
    # A sign-in file from before "no password" was removed: back to the default PASSWORD.
    store.path.write_text('{"format": 2, "mode": "none"}')
    fresh = webauth.AuthStore(cfg).get()
    assert fresh.mode == "password" and fresh.default and fresh.check("PASSWORD")
    store.set("pin", "0042")

    # craft-conductor 0.1's generated plain-text password is replaced by the default PASSWORD.
    legacy = tmp_path / "old"
    (legacy / ".craft-conductor").mkdir(parents=True)
    (legacy / ".craft-conductor" / "web-password").write_text("s3cret-from-0.1\n")
    old = webauth.AuthStore(configmod.parse(legacy, {"server": {"loader": "fabric"}})).get()
    assert old.check("PASSWORD") and old.default and not old.check("s3cret-from-0.1")
    assert not (legacy / ".craft-conductor" / "web-password").exists()

    # [web] password in craft-conductor.toml wins and can't be changed from the UI.
    cfg.web.password = "from-config"
    assert store.get().managed and store.get().check("from-config")
    with pytest.raises(ConfigError, match="craft-conductor.toml"):
        store.set("pin", "1234")
    cfg.web.password = ""
    assert store.get().check("0042") and not store.get().managed


def test_host_allowlist():
    import socket
    from craft_conductor.web import host_allowed
    for ok in ("localhost:8765", "127.0.0.1:8765", "[::1]:8765", "10.0.0.5", "pc.local", "a.localhost",
               socket.gethostname(), None, "proxy.example.com"):
        assert host_allowed(ok, ["proxy.example.com"]), ok
    for bad in ("evil.example", "evil.example:8765", "localhost.evil.example", "127.0.0.1.nip.io"):
        assert not host_allowed(bad, []), bad


def test_http_waits_out_rate_limits(monkeypatch):
    import io
    import urllib.error
    from email.message import Message
    from craft_conductor import http as httpmod

    def limited(retry_after=None):
        headers = Message()
        if retry_after:
            headers["Retry-After"] = retry_after
        return urllib.error.HTTPError("https://api.mojang.com/x", 429, "Too Many Requests", headers, io.BytesIO())

    replies = [limited("12"), limited(), limited(), limited(), io.BytesIO(b'{"id": "abc"}')]
    slept = []
    monkeypatch.setattr(httpmod.time, "sleep", slept.append)

    def urlopen(req, timeout):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        reply.headers = {}
        return reply
    monkeypatch.setattr(httpmod._OPENER, "open", urlopen)
    assert httpmod.HttpClient(cache_ttl=0).get_json("https://api.mojang.com/x") == {"id": "abc"}
    assert slept == [12, 10, 20, 30]  # Retry-After first, then growing waits

    # Other client errors still fail at once, and plain failures stop after the normal retries.
    replies[:] = [urllib.error.HTTPError("u", 404, "nope", Message(), io.BytesIO())]
    with pytest.raises(httpmod.HttpError):
        httpmod.HttpClient(cache_ttl=0).get_json("https://api.mojang.com/y")


def test_process_stats():
    import os
    import time as _time
    from craft_conductor import stats
    rss, cpu = stats.sample(os.getpid())
    assert rss > 1024 * 1024 and cpu > 0
    s = stats.Sampler()
    first = s.read(os.getpid())
    assert first["memory_bytes"] > 0 and first["cpu_percent"] is None  # needs two readings
    end = _time.monotonic() + 0.6
    while _time.monotonic() < end:
        sum(range(1000))  # keep a core busy
    second = s.read(os.getpid())
    assert 0 < second["cpu_percent"] <= 100
    assert s.read(None) is None
    assert stats.heap_bytes("6G", 4) == 6 * 1024 ** 3 and stats.heap_bytes("512m", 4) == 512 * 1024 ** 2
    assert stats.heap_bytes("auto", 3) == 3 * 1024 ** 3


def test_skins(tmp_path, http):
    import base64
    import json as _json
    from craft_conductor.skins import SESSION_PROFILE, SkinError, Skins
    server = tmp_path / "server"
    server.mkdir()
    (server / "usercache.json").write_text(_json.dumps([{"name": "Notch", "uuid": "069a79f4-44e9-4726-a5be-fca90e38aaf5"}]))
    png = b"\x89PNG\r\n\x1a\n" + b"skin" * 10
    textures = base64.b64encode(_json.dumps(
        {"textures": {"SKIN": {"url": "http://textures.minecraft.net/texture/abc123"}}}).encode()).decode()
    http.json[f"{SESSION_PROFILE}/069a79f444e94726a5befca90e38aaf5"] = {"properties": [{"name": "textures", "value": textures}]}
    http.files["https://textures.minecraft.net/texture/abc123"] = png
    skins = Skins(tmp_path / "skins", server, http)
    assert skins.png("Notch") == png
    http.files.clear()
    assert skins.png("notch") == png  # cached on disk
    with pytest.raises(SkinError):
        skins.png("../etc")
    with pytest.raises(SkinError):
        skins.png("Nobody")  # not in the cache and Mojang doesn't know them
    # A texture address that isn't Mojang's is refused.
    (server / "usercache.json").write_text(_json.dumps([{"name": "Evil", "uuid": "0" * 32}]))
    bad = base64.b64encode(_json.dumps({"textures": {"SKIN": {"url": "http://evil.example/x"}}}).encode()).decode()
    http.json[f"{SESSION_PROFILE}/{'0' * 32}"] = {"properties": [{"name": "textures", "value": bad}]}
    with pytest.raises(SkinError):
        skins.png("Evil")


def test_advanced_server_settings():
    from craft_conductor import serverprops
    ok = serverprops.validate({"pvp": False, "view-distance": "16", "level-type": "minecraft:flat",
                               "level-seed": " 12345 ", "resource-pack": "", "hardcore": "true"})
    assert ok == {"pvp": "false", "view-distance": "16", "level-type": "minecraft:flat", "level-seed": "12345",
                  "resource-pack": "", "hardcore": "true"}
    assert serverprops.validate(None) == {}
    for bad in ({"enable-rcon": True}, {"server-port": 1}, {"view-distance": 2}, {"view-distance": "x"},
                {"pvp": "maybe"}, {"level-type": "minecraft:mars"}, {"level-seed": "a\nb"},
                {"level-name": "../../etc"}, {"resource-pack": "ftp://x"}, "pvp=false"):
        with pytest.raises(ConfigError):
            serverprops.validate(bad)
    current = serverprops.current({"pvp": "false"})
    assert current["pvp"] == "false" and current["view-distance"] == "10"
    assert {p["key"] for p in serverprops.schema()} >= {"level-seed", "online-mode", "spawn-protection"}


def test_download_cleans_up_on_windows(tmp_path, monkeypatch):
    """Windows can't delete or rename a file that's open, or that antivirus is scanning."""
    import os
    from craft_conductor import http as httpmod
    client = httpmod.HttpClient()

    # The request fails before any data: the .part file is closed first, and the real error shows.
    closed = []
    real_unlink = Path.unlink
    def unlink(self, missing_ok=False):
        closed.append(self.name)
        return real_unlink(self, missing_ok=missing_ok)
    monkeypatch.setattr(Path, "unlink", unlink)
    def fail(req):
        raise httpmod.HttpError("https://example.com/a.jar", 403, "HTTP 403")
    monkeypatch.setattr(client, "_open", fail)
    with pytest.raises(httpmod.HttpError, match="403"):
        client.download("https://example.com/a.jar", tmp_path / "mods" / "a.jar")
    assert closed and not list((tmp_path / "mods").iterdir())

    # Antivirus holds the finished file for a moment: moving it into place waits and retries.
    src = tmp_path / "src.part"
    src.write_bytes(b"jar")
    tries = []
    real_replace = os.replace
    def replace(a, b):
        tries.append(1)
        if len(tries) < 3:
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")
        return real_replace(a, b)
    monkeypatch.setattr(httpmod.os, "replace", replace)
    monkeypatch.setattr(httpmod.time, "sleep", lambda s: None)
    httpmod._replace(str(src), tmp_path / "dest.jar")
    assert len(tries) == 3 and (tmp_path / "dest.jar").read_bytes() == b"jar"
