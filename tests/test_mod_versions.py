"""Holding a mod at one version (Change version), and the fixes the file check suggests."""

import pytest

from craft_conductor import config as configmod, filecheck
from craft_conductor.config import ConfigError, ModSpec, Pin
from craft_conductor.modfiles import Store
from craft_conductor.mods.modrinth import ModrinthProvider

from test_manager import manager, update
from test_modcheck import fabric


# ------------------------------------------------------------------ the config
def test_held_versions_are_kept_in_the_config(make_config):
    cfg = make_config([])
    configmod.set_pin(cfg.path, "modrinth:SOD", Pin("SOD-0.8.9", "1.21.1"))
    configmod.set_pin(cfg.path, "curseforge:123", Pin("4567", "1.21.1"))
    assert configmod.load(cfg.root).pins == {"modrinth:SOD": Pin("SOD-0.8.9", "1.21.1"), "curseforge:123": Pin("4567", "1.21.1")}
    configmod.set_pin(cfg.path, "modrinth:SOD", Pin("SOD-0.9.2", "1.21.1"))   # (changed in place)
    configmod.set_pin(cfg.path, "curseforge:123", None)
    assert configmod.load(cfg.root).pins == {"modrinth:SOD": Pin("SOD-0.9.2", "1.21.1")}
    for key, version in (("modrinth:../x", "a"), ("other:1", "a"), ("modrinth:SOD", "../../x"), ("modrinth:SOD", "a..b")):
        with pytest.raises(ConfigError):
            configmod.set_pin(cfg.path, key, Pin(version, "1.21.1"))


# ------------------------------------------------------------------ installing
def two_builds(modrinth):
    modrinth.project("AAA", "goodmod", "Good Mod")
    modrinth.version("AAA", "1.0", ["1.21.1"])
    modrinth.version("AAA", "1.1", ["1.21.1"])


def test_a_held_mod_stays_on_its_version_through_updates(make_config, http, modrinth):
    two_builds(modrinth)
    cfg = make_config([ModSpec("modrinth", "goodmod")])
    configmod.set_pin(cfg.path, "modrinth:AAA", Pin("AAA-1.0", "1.21.1"))
    m = manager(configmod.load(cfg.root), http, ["1.21.1"])
    assert update(m).ok
    assert [x.version_number for x in m.lock.mods] == ["1.0"]
    modrinth.version("AAA", "1.2", ["1.21.1"])
    decision, changes = m.check()
    assert changes is None or changes.empty
    configmod.set_pin(cfg.path, "modrinth:AAA", None)   # back to the newest by itself
    m.reload_config()
    assert update(m).ok and [x.version_number for x in m.lock.mods] == ["1.2"]


def test_a_build_made_for_another_minecraft_can_be_held_on_this_one_only(make_config, http, modrinth):
    modrinth.project("AAA", "goodmod", "Good Mod")
    modrinth.version("AAA", "1.0", ["1.21.1"])
    modrinth.version("AAA", "2.0", ["1.21.2"])
    cfg = make_config([ModSpec("modrinth", "goodmod")])
    configmod.set_pin(cfg.path, "modrinth:AAA", Pin("AAA-2.0", "1.21.1"))   # (picked from every build)
    m = manager(configmod.load(cfg.root), http, ["1.21.1", "1.21.3"])
    assert update(m).ok and [x.version_number for x in m.lock.mods] == ["2.0"]
    plan = m.planner().plan_for("1.21.3")                                  # an upgrade waits for another pick
    assert not plan.complete and "held at 2.0, which isn't made for Minecraft 1.21.3" in plan.blockers[0].reason


def test_every_build_is_listed_newest_first(http, modrinth):
    two_builds(modrinth)
    modrinth.version("AAA", "2.0-beta", ["1.21.2"], version_type="beta")
    p = ModrinthProvider(http)
    found = p.versions(p.project("goodmod"), ("fabric",))
    assert [(v["number"], v["channel"], v["minecraft"]) for v in found] == [
        ("2.0-beta", "beta", ["1.21.2"]), ("1.1", "release", ["1.21.1"]), ("1.0", "release", ["1.21.1"])]


# ------------------------------------------------------------------ fixes
def shaders(modrinth):
    modrinth.project("IRIS", "iris", "Iris", server_side="unsupported")
    modrinth.version("IRIS", "1.10.9", ["1.21.1"], deps=["SOD"], content=fabric("iris", "1.10.9", {"sodium": ">=0.8.0 <0.9"}, "Iris"))
    modrinth.version("IRIS", "1.11.3", ["1.21.1"], deps=["SOD"], content=fabric("iris", "1.11.3", {"sodium": "0.9.x"}, "Iris"))
    modrinth.version("IRIS", "1.11.4", ["1.21.1"], deps=["SOD"], content=fabric("iris", "1.11.4", {"sodium": "0.9.x"}, "Iris"))
    modrinth.project("SOD", "sodium", "Sodium", server_side="unsupported")
    modrinth.version("SOD", "0.8.9", ["1.21.1"], content=fabric("sodium", "0.8.9", name="Sodium"))


def test_the_check_suggests_a_build_that_works(tmp_path, http, modrinth):
    shaders(modrinth)
    p = ModrinthProvider(http)
    entries = []
    for slug in ("iris", "sodium"):
        f = p.resolve(ModSpec("modrinth", slug), "1.21.1", ("fabric",), "release", side="client")
        entries.append({"name": f.name, "project": f.key, "url": f.url, "sha1": f.sha1, "filename": f.filename,
                        "version": f.version_number, "version_id": f.version_id, "channel": f.channel, "side": "client"})
    r = filecheck.check(entries, loader="fabric", minecraft="1.21.1", loader_version="0.19.5", java_major=21,
                        store=Store(tmp_path / "files", http), providers={"modrinth": p}, mod_loaders=("fabric",))
    assert not r["ok"]
    problem = r["problems"][0]
    assert (problem["key"], problem["needs_key"], problem["side"]) == ("modrinth:IRIS", "modrinth:SOD", "client")
    assert [x["text"] for x in problem["fixes"]] == ["Use Iris 1.10.9"]   # (1.11.3 needs 0.9 too)
    assert problem["fixes"][0]["version_id"] == "IRIS-1.10.9"
    entries[0].update(url=None, sha1=None)  # nothing new is downloaded when it's run again: the files are kept
    downloads = len(http.downloads)
    filecheck.check(entries[1:], loader="fabric", minecraft="1.21.1", loader_version="0.19.5", java_major=21,
                    store=Store(tmp_path / "files", http))
    assert len(http.downloads) == downloads


def test_players_get_the_held_build(make_config, http, modrinth):
    from craft_conductor.clientpack import PackBuilder
    shaders(modrinth)
    cfg = make_config([])
    configmod.set_value(cfg.path, "client", "mods", '["iris"]')
    configmod.set_pin(cfg.path, "modrinth:IRIS", Pin("IRIS-1.10.9", "1.21.1"))
    m = manager(configmod.load(cfg.root), http, ["1.21.1"])
    assert update(m).ok
    p = PackBuilder(m).build("mc.example.com")
    assert {x["name"]: x["version"] for x in p["mods"]} == {"Iris": "1.10.9", "Sodium": "0.8.9"}
    assert p["problems"] == []
