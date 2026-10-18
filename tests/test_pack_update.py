"""Updating a server made from a modpack to the pack's next version (packupdate.py, #95)."""

import hashlib
import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from craft_conductor import config as configmod, modpack, packupdate
from craft_conductor.config import ModSpec, Pin
from craft_conductor.mods.modrinth import API as MODRINTH

from test_manager import manager, update

PROJECT = "PACKPROJ"


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def build(http, modrinth, pid: str, vid: str, name: str) -> dict:
    """A mod's build on Modrinth (ids as a pack names them), and its line in a pack's index."""
    if f"{MODRINTH}/project/{pid}" not in http.json:
        modrinth.project(pid, name.lower().replace(" ", ""), name)
    content = f"{name} {vid}".encode()
    url = f"https://cdn.modrinth.com/data/{pid}/versions/{vid}/{name.replace(' ', '')}-{vid}.jar"
    http.files[url] = content
    http.json[f"{MODRINTH}/version/{vid}"] = {
        "id": vid, "project_id": pid, "version_number": vid, "version_type": "release", "game_versions": ["1.21.1"],
        "loaders": ["fabric"], "dependencies": [],
        "files": [{"url": url, "filename": url.rsplit("/", 1)[1], "primary": True, "hashes": {"sha1": sha1(content)}}]}
    return {"path": f"mods/{url.rsplit('/', 1)[1]}", "downloads": [url], "hashes": {"sha1": sha1(content)},
            "env": {"server": "required", "client": "required"}}


def publish(http, vid: str, name: str, date: str, files: list[dict], overrides: dict[str, str], loader: str = "0.16.0") -> None:
    """A version of the pack on Modrinth."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("modrinth.index.json", json.dumps({
            "formatVersion": 1, "game": "minecraft", "name": "Test Pack", "versionId": name,
            "dependencies": {"minecraft": "1.21.1", "fabric-loader": loader}, "files": files}))
        for path, text in overrides.items():
            z.writestr(path, text)
    data = buf.getvalue()
    url = f"https://cdn.modrinth.com/data/{PROJECT}/versions/{vid}/pack.mrpack"
    http.files[url] = data
    version = {"id": vid, "project_id": PROJECT, "name": name, "version_number": name, "version_type": "release",
               "date_published": date, "game_versions": ["1.21.1"], "loaders": ["fabric"],
               "files": [{"filename": "pack.mrpack", "url": url, "primary": True, "hashes": {"sha1": sha1(data)}}]}
    http.json[f"{MODRINTH}/version/{vid}"] = version
    listed = [v for v in http.json.get(f"{MODRINTH}/project/{PROJECT}/version", []) if v["id"] != vid]
    http.json[f"{MODRINTH}/project/{PROJECT}/version"] = [version] + listed


def test_a_modrinth_pack_moves_to_its_next_version(make_config, http, modrinth):
    good1, old = build(http, modrinth, "GOODMODA", "GOODV001", "Good Mod"), build(http, modrinth, "OLDMODAA", "OLDV0001", "Old Mod")
    cut = build(http, modrinth, "CUTMODAA", "CUTV0001", "Cut Mod")
    publish(http, "PACKV001", "Test Pack 1.0", "2026-01-01T00:00:00Z", [good1, old, cut],
            {"overrides/config/a.txt": "one", "overrides/config/mine.txt": "pack"})
    cfg = make_config()
    modpack.apply(cfg.root, "PACKV001", http, exclude=[cut["path"]])
    cfg = configmod.load(cfg.root)
    assert cfg.modpack == configmod.Modpack("modrinth", PROJECT, "PACKV001", "Test Pack 1.0")
    state = packupdate.load_state(cfg.root)
    assert state["mods"] == {"modrinth:GOODMODA": "GOODV001", "modrinth:OLDMODAA": "OLDV0001"}
    assert state["removed"] == ["modrinth:CUTMODAA"] and set(state["files"]) == {"config/a.txt", "config/mine.txt"}
    assert cfg.server.loader_version == "0.16.0"
    m = manager(cfg, http, ["1.21.1"])
    assert update(m).ok
    assert {x.name for x in m.lock.mods} == {"Good Mod", "Old Mod"}
    # The pack's loader build, not the newest ("loader-1.21.1" here): players on the pack have that one (#95).
    assert m.lock.loader_version == "0.16.0" and m.check()[1].empty
    (m.server_dir / "config" / "mine.txt").write_text("mine")  # (changed by hand since)

    good2, new = build(http, modrinth, "GOODMODA", "GOODV002", "Good Mod"), build(http, modrinth, "NEWMODAA", "NEWV0001", "New Mod")
    publish(http, "PACKV002", "Test Pack 1.1", "2026-02-01T00:00:00Z", [good2, new, cut],
            {"overrides/config/a.txt": "two", "overrides/config/mine.txt": "pack 2", "overrides/config/new.txt": "new"}, loader="0.16.5")
    found = packupdate.versions(m)
    assert found["current"]["id"] == "PACKV001" and [v["id"] for v in found["newer"]] == ["PACKV002"]
    what = packupdate.preview(m, "PACKV002")
    assert (what["added"], what["removed"], what["updated"], what["kept_removed"]) == (["New Mod"], ["Old Mod"], 1, ["Cut Mod"])
    assert (what["loader"], what["loader_version"]) == ("fabric", "0.16.5")

    d = SimpleNamespace(m=m, proc=None, want_running=False, last_check=None)
    message = packupdate.run(d, "PACKV002")
    assert message.startswith("Updated the pack to Test Pack 1.1") and "config/mine.txt" in message
    assert {(x.name, x.version_id) for x in m.lock.mods} == {("Good Mod", "GOODV002"), ("New Mod", "NEWV0001")}
    server = m.server_dir
    assert (server / "config" / "a.txt").read_text() == "two" and (server / "config" / "new.txt").read_text() == "new"
    assert (server / "config" / "mine.txt").read_text() == "mine"  # (yours, kept)
    cfg = m.config
    assert cfg.modpack.version == "PACKV002" and cfg.modpack.name == "Test Pack 1.1"
    assert cfg.server.loader_version == m.lock.loader_version == "0.16.5"
    assert ("modrinth", "CUTMODAA") not in {(s.source, s.id) for s in cfg.mods}  # (still left out)
    assert packupdate.load_state(cfg.root)["mods"] == {"modrinth:GOODMODA": "GOODV002", "modrinth:NEWMODAA": "NEWV0001"}
    assert packupdate.versions(m)["newer"] == []

    # A version that can't be installed changes nothing: the settings and files stay as they were.
    broken = build(http, modrinth, "BADMODAA", "BADV0001", "Bad Mod")
    http.json[f"{MODRINTH}/version/BADV0001"]["loaders"] = ["forge"]  # (not for this server's loader)
    publish(http, "PACKV003", "Test Pack 1.2", "2026-03-01T00:00:00Z", [good2, new, broken], {"overrides/config/a.txt": "three"})
    before = configmod.read_text(cfg.path)
    with pytest.raises(modpack.ModpackError, match="can't be installed"):
        packupdate.run(d, "PACKV003")
    assert configmod.read_text(m.config.path) == before and (server / "config" / "a.txt").read_text() == "two"
    assert m.config.modpack.version == "PACKV002"

    # One that installs but doesn't start is put back too: its files with the rest (they went in after the backup).
    crash = build(http, modrinth, "CRASHMOD", "CRASHV01", "crash")
    publish(http, "PACKV004", "Test Pack 1.3", "2026-04-01T00:00:00Z", [good2, new, crash],
            {"overrides/config/a.txt": "four", "overrides/config/extra.txt": "extra"})
    with pytest.raises(modpack.ModpackError, match="rolled back"):
        packupdate.run(d, "PACKV004")
    assert configmod.read_text(m.config.path) == before and m.config.modpack.version == "PACKV002"
    assert (server / "config" / "a.txt").read_text() == "two" and not (server / "config" / "extra.txt").exists()
    assert {x.name for x in m.lock.mods} == {"Good Mod", "New Mod"}

    # A version that only moves the loader to another build: the server is updated for it all the same.
    publish(http, "PACKV005", "Test Pack 1.4", "2026-05-01T00:00:00Z", [good2, new], {"overrides/config/a.txt": "two"}, loader="0.16.9")
    assert packupdate.preview(m, "PACKV005")["loader_version"] == "0.16.9"
    assert packupdate.run(d, "PACKV005").startswith("Updated the pack to Test Pack 1.4")
    assert m.config.server.loader_version == m.lock.loader_version == "0.16.9"
    assert (server / "runtime-1.21.1.txt").read_text() == "0.16.9"


def test_a_packs_loader_build_is_read_as_the_loader_takes_it(tmp_path):
    assert configmod.loader_build("1.20.1-47.2.0", "1.20.1") == "47.2.0"  # (Forge, as some packs write it)
    assert configmod.loader_build("26.1.2.109", "26.1.2") == "26.1.2.109"
    assert configmod.loader_build("21.1.0-beta", "1.21.1") == "21.1.0-beta"
    for odd in ("", "latest", "../21.1", "21.1.109/../../x", "21.1.109;x", "1" * 50):
        assert configmod.loader_build(odd, "1.21.1") == ""
    with pytest.raises(configmod.ConfigError, match="loader_version"):
        configmod.parse(tmp_path, {"server": {"loader": "neoforge", "loader_version": "21.1/../x"}})


def test_the_loader_is_held_only_on_the_minecraft_its_build_is_for(make_config, http):
    cfg = make_config()
    configmod.set_value(cfg.path, "server", "minecraft", '"1.21.1"')
    configmod.hold_loader(cfg.path, "0.16.0")
    planner = manager(configmod.load(cfg.root), http, ["1.21.1", "1.21.4"]).planner()
    assert planner.plan_for("1.21.1").loader_version == "0.16.0"
    assert planner.plan_for("1.21.4").loader_version == "loader-1.21.4"  # (another Minecraft: the newest build)
    configmod.hold_loader(cfg.path, "")
    assert configmod.load(cfg.root).server.loader_version == ""


def test_what_updating_a_curseforge_pack_keeps_as_you_chose(make_config, http):
    """Mods you removed stay removed, a mod you held at another build stays there, mods you added stay
    yours, and the players' mods follow the pack (unless you took one out of their download)."""
    cfg = make_config()
    path = cfg.path
    for pid in ("1", "2", "3", "4"):
        configmod.append_mod(path, ModSpec("curseforge", pid, pack=True))
    configmod.append_mod(path, ModSpec("curseforge", "7"))  # (added by you)
    for key, version in (("curseforge:1", "11"), ("curseforge:2", "21"), ("curseforge:3", "99"), ("curseforge:4", "41"),
                         ("curseforge:20", "201"), ("curseforge:21", "211")):
        configmod.set_pin(path, key, Pin(version, "1.21.1"))
    configmod.set_value(path, "client", "mods", json.dumps(["curseforge:20", "curseforge:21"]))
    packupdate.record(cfg.root, "curseforge", "500", "9001", "Big Pack 1.0",
                      {"curseforge:1": "11", "curseforge:2": "21", "curseforge:3": "31", "curseforge:4": "41", "curseforge:5": "51"},
                      [], {"curseforge:20": "201", "curseforge:21": "211", "curseforge:22": "221"}, {})
    m = manager(configmod.load(cfg.root), http, ["1.21.1"])
    Mod = packupdate.Mod
    new = packupdate.Pack("curseforge", "500", "9002", "Big Pack 1.1", "1.21.1", "fabric",
                          server={k: Mod(k, v, n) for k, v, n in (
                              ("curseforge:1", "12", "One"), ("curseforge:3", "32", "Three"), ("curseforge:4", "41", "Four"),
                              ("curseforge:5", "52", "Five"), ("curseforge:6", "61", "Six"), ("curseforge:7", "71", "Seven"))},
                          friends={k: Mod(k, v, n) for k, v, n in (
                              ("curseforge:20", "202", "Twenty"), ("curseforge:22", "222", "Twenty-two"), ("curseforge:23", "231", "Twenty-three"))})
    p = packupdate.plan(m, new)
    assert [x.key for x in p.move] == ["curseforge:1"]           # held at the pack's file: moves on
    assert p.remove == ["curseforge:2"]                           # the pack dropped it
    assert [x.key for x in p.kept_held] == ["curseforge:3"]      # you held it at another build
    assert [x.key for x in p.kept_removed] == ["curseforge:5"]   # you removed it
    assert [x.key for x in p.add] == ["curseforge:6"]            # new (Seven is already yours)
    assert [x.key for x in p.friends_move] == ["curseforge:20"]
    assert [x.key for x in p.friends_add] == ["curseforge:23"]   # (22 was taken out of the download: it stays out)
    assert p.friends_remove == ["curseforge:21"] and p.minecraft is None

    packupdate.Change(m, p).settings()
    cfg = m.config
    assert [(s.id, s.pack) for s in cfg.mods] == [("1", True), ("3", True), ("4", True), ("7", False), ("6", True)]
    assert {k: v.version for k, v in cfg.pins.items()} == {"curseforge:1": "12", "curseforge:3": "99", "curseforge:4": "41",
                                                          "curseforge:20": "202", "curseforge:6": "61", "curseforge:23": "231"}
    assert cfg.client.mods == ["curseforge:20", "curseforge:23"] and cfg.modpack.version == "9002"

    with pytest.raises(modpack.ModpackError, match="make a new server"):
        packupdate.plan(m, packupdate.Pack("curseforge", "500", "9003", "Big Pack 2.0", "1.21.1", "neoforge"))


def test_a_packs_name_never_breaks_the_settings_file(make_config):
    cfg = make_config()
    name = 'Cozy \U0001F338 "Pack"\\ 2.0\x7f'
    packupdate.record(cfg.root, "modrinth", PROJECT, "PACKV001", name, {}, [], {}, {})
    assert configmod.load(cfg.root).modpack.name == name


def test_the_modpack_record_is_checked():
    with pytest.raises(configmod.ConfigError):
        configmod._modpack({"source": "modrinth", "project": "../x", "version": "AAAAAAAA"})
    with pytest.raises(configmod.ConfigError):
        configmod._modpack({"source": "github", "project": "1", "version": "2"})
    assert configmod._modpack({"source": "curseforge", "project": "925200", "version": "6543210", "name": "ATM"}).name == "ATM"
    assert configmod._modpack(None) is None


def test_the_modpack_page_answers(hub_env):
    from test_hub import login
    hub, c = hub_env
    login(c)
    assert c.get("/api/servers/alpha/modpack")[1] == {"pack": None}
    assert c.post("/api/servers/alpha/modpack/update", {"version": "PACKV002"})[0] == 400  # (not made from a pack)
    assert c.post("/api/servers/alpha/modpack/check", {})[1] == {"pack": None, "current": None, "newer": []}
