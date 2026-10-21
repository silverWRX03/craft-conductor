"""Mods only players run stay off the server when the mod sites don't say so (sides.py: a mod's own
file, #93; Modrinth's word for a CurseForge mod, #94), and a mod that stops the server by reaching for
players' parts of Minecraft can be moved to players' mods (explain.py)."""

from types import SimpleNamespace

import pytest

from craft_conductor import config as configmod, explain, sides
from craft_conductor.clientpack import PackBuilder
from craft_conductor.config import ModSpec
from craft_conductor.manager import Manager
from craft_conductor.mods import providers_for
from craft_conductor.mods.base import ModFile, Project
from craft_conductor.mods.modrinth import API as MODRINTH
from craft_conductor.planner import Plan

from conftest import FakeLoader, FakeMojang
from test_hub import login
from test_manager import manager, update
from test_modcheck import dep, forge_jar


@pytest.fixture(autouse=True)
def fresh_cache():
    sides._known.clear()
    yield
    sides._known.clear()


class NeoLoader(FakeLoader):
    name = "neoforge"
    mod_loaders = ("neoforge",)


def neo_manager(cfg, http):
    mojang = FakeMojang(http, ["1.21.1"])
    return Manager(cfg, http=http, mojang=mojang, loader=NeoLoader(http, mojang), providers=providers_for(cfg, http),
                   echo=False, sleep=lambda s: None)


def neo(mod_id, deps=""):
    return forge_jar(mod_id, "1.0", deps, path="META-INF/neoforge.mods.toml")


def test_a_dependency_only_players_need_stays_off_the_server(make_config, http, modrinth):
    """Iris Search needs Iris on players' computers only (its file says side = "CLIENT"), and Iris needs
    Sodium; Modrinth only says "required". Neither goes on the server: players get both (#93)."""
    for pid, slug, name, deps, content in (
            ("SRCH", "irissearch", "Iris Search", ["IRIS"], neo("irissearch", dep("irissearch", "iris", "*", True, side="CLIENT"))),
            ("IRIS", "iris", "Iris", ["SODI"], neo("iris", dep("iris", "sodium", "*", True))),
            ("SODI", "sodium", "Sodium", [], neo("sodium"))):
        modrinth.project(pid, slug, name)
        modrinth.version(pid, "1.0", ["1.21.1"], deps=deps, loaders=("neoforge",), content=content)
    cfg = make_config([ModSpec("modrinth", "SRCH")])
    m = neo_manager(cfg, http)
    assert update(m).ok
    assert [x.name for x in m.lock.mods] == ["Iris Search"]
    assert {x.name for x in m.lock.players} == {"Iris", "Sodium"}
    assert set(m.lock.client_only) == {"modrinth:IRIS", "modrinth:SODI"}
    assert "Iris Search only needs Iris on players' computers" in m.lock.skipped["modrinth:IRIS"]
    assert sorted(p.name for p in m.mods_dir.glob("*.jar")) == ["SRCH-1.0.jar"]
    pack = PackBuilder(m).build("mc.example.com")
    assert {x["name"]: x["side"] for x in pack["mods"]} == {"Iris Search": "both", "Iris": "client", "Sodium": "client"}
    assert next(x for x in pack["mods"] if x["name"] == "Iris")["needed_by"] == "Iris Search"

    # A mod whose own file needs Iris on the server (its site doesn't say) keeps it, and Sodium, there.
    modrinth.project("SHAD", "shaderlib", "Shader Lib")
    modrinth.version("SHAD", "1.0", ["1.21.1"], loaders=("neoforge",), content=neo("shaderlib", dep("shaderlib", "iris", "*", True)))
    configmod.append_mod(cfg.path, ModSpec("modrinth", "SHAD"))
    m.reload_config()
    assert update(m).ok
    assert {x.name for x in m.lock.mods} == {"Iris Search", "Shader Lib", "Iris", "Sodium"}
    assert m.lock.players == [] and m.lock.client_only == {}


def test_a_curseforge_mod_modrinth_says_players_run_stays_off_the_server(make_config, http, modrinth):
    """CurseForge doesn't say where a mod runs: the same mod on Modrinth does, found by its file's checksum or by
    its slug and name (#94). One Modrinth doesn't have stays on the server."""
    modrinth.project("SODM", "sodium", "Sodium", server_side="unsupported")
    modrinth.project("IRSM", "iris", "Iris", server_side="unsupported")
    modrinth.project("JEIM", "jei", "JEI")
    asked = []

    def identify(body):
        asked.append(sorted(body["hashes"]))
        return {"5" * 40: {"project_id": "SODM"}, "6" * 40: {"project_id": "JEIM"}}
    http.posts[f"{MODRINTH}/version_files"] = identify
    m = manager(make_config(), http, ["1.21.1"])

    def cf(pid, name, sha1, dependency_of=None):
        return ModFile(key=f"curseforge:{pid}", source="curseforge", project_id=pid, name=name, version_id="1",
                       version_number="1", filename=f"{pid}.jar", url="", sha1=sha1, dependency_of=dependency_of)
    plan = Plan("1.21.1", "fabric", "loader-1.21.1",
                mods=[cf("1", "Sodium", "5" * 40), cf("2", "JEI", "6" * 40), cf("3", "Iris", "7" * 40, "curseforge:9"),
                      cf("4", "Lonely Mod", "8" * 40), cf("9", "Shader Pack Helper", "9" * 40)])
    plan.projects = {"curseforge:3": Project("curseforge", "3", "iris", "Iris"),
                     "curseforge:4": Project("curseforge", "4", "lonely", "Lonely Mod")}
    plan.needs = {"curseforge:9": ["curseforge:3"]}
    m.trim(plan)
    assert [x.name for x in plan.mods] == ["JEI", "Lonely Mod", "Shader Pack Helper"]
    assert {b.name: (b.reason, b.client_only) for b in plan.dropped} == {
        "Sodium": ("Sodium only runs on players' computers (Modrinth says so)", True),
        "Iris": ("Iris only runs on players' computers (Modrinth says so)", True)}
    # Players get them: Sodium, added by itself, too (#144), and Iris, which a mod on the server needs.
    assert [x.name for x in plan.players] == ["Sodium", "Iris"]

    again = Plan("1.21.1", "fabric", "loader-1.21.1", mods=[cf("1", "Sodium", "5" * 40)])
    m.trim(again)
    assert again.mods == [] and len(asked) == 1  # (what Modrinth said is remembered for a while)


def test_a_players_mod_left_off_the_server_is_in_the_friends_download_with_what_it_needs(make_config, http, modrinth):
    """Iris & Oculus Search (CurseForge), which Modrinth says only players run, left off the server with
    Iris: friends get both, and Iris says it's needed by Iris & Oculus Search, not by an id (#144)."""
    m = manager(make_config(), http, ["1.21.1"])
    assert update(m).ok

    def cf(pid, name, dependency_of=None):
        return ModFile(key=f"curseforge:{pid}", source="curseforge", project_id=pid, name=name, version_id="1",
                       version_number="1", filename=f"{pid}.jar", url=f"https://edge.forgecdn.net/files/1/{pid}.jar",
                       sha1=pid * 40, dependency_of=dependency_of)
    m.lock.players = [cf("9", "Iris & Oculus Search"), cf("3", "Iris", "curseforge:9")]
    pack = PackBuilder(m).build("mc.example.com")
    by_name = {x["name"]: x for x in pack["mods"]}
    assert by_name["Iris & Oculus Search"]["side"] == "client" and "needed_by" not in by_name["Iris & Oculus Search"]
    assert by_name["Iris"]["needed_by"] == "Iris & Oculus Search"


def test_a_mod_that_reaches_for_players_parts_of_minecraft_can_go_to_players_mods():
    mods = [SimpleNamespace(name="Iris", filename="iris-1.8.jar")]
    lines = ["java.lang.RuntimeException: Attempted to load class net/minecraft/client/gui/screens/Screen for invalid dist DEDICATED_SERVER",
             "\tat TRANSFORMER/iris@1.8.0/net.irisshaders.iris.Iris.<clinit>(Iris.java:40)"]
    e = explain.explain(lines, None, mods)
    assert e["cause"] == "players-only" and e["title"] == "Iris only runs on players' computers"
    assert [a["kind"] for a in e["actions"]] == ["players-only", "remove-mod"]
    assert e["actions"][0]["label"] == "Move Iris to players' mods"
    # an ordinary crash in the same mod is still "remove it"
    assert explain.explain(["java.lang.NullPointerException", "\tat x.Y(Y.java:1) [iris-1.8.jar:?]"], None, mods)["cause"] == "mod"


def test_moving_a_mod_to_players_mods_takes_it_off_the_server(hub_env):
    hub, c = hub_env
    login(c)
    d = hub.get("alpha")
    configmod.append_mod(d.m.config.path, ModSpec("modrinth", "goodmod"))
    d.m.reload_config()
    assert update(d.m).ok
    good = next(x for x in d.m.lock.mods if x.name == "Good Mod")
    d.problem = explain.explain(["java.lang.NoClassDefFoundError: net/minecraft/client/Minecraft",
                                 f"\tat x.Y(Y.java:1) [{good.filename}:?]"], None, d.m.lock.mods)
    assert d.problem["cause"] == "players-only"
    status, r, _ = c.post("/api/servers/alpha/problem/fix", {"kind": "players-only", "filename": good.filename})
    assert status == 200 and "Moved Good Mod to players' mods" in r["message"], r
    cfg = d.m.config
    assert cfg.client.only == [good.key] and "AAA" in cfg.client.mods
    plan = d.m.check()[0].plan
    assert good.key not in {x.key for x in plan.mods}
    assert any(b.key == good.key and b.client_only for b in plan.dropped)
    assert c.get("/api/servers/alpha/mods")[1]["players_only"] == [good.key]

    status, r, _ = c.post("/api/servers/alpha/mods/players", {"key": good.key, "on": False})
    assert status == 200 and "goes back on the server" in r["message"]
    assert d.m.config.client.only == [] and good.key in {x.key for x in d.m.check()[0].plan.mods}
    assert c.post("/api/servers/alpha/mods/players", {"key": "../x"})[0] == 400


def test_players_only_mods_in_the_config_are_checked():
    with pytest.raises(configmod.ConfigError):
        configmod._client({"only": ["sodium"]})
    assert configmod._client({"only": ["modrinth:AANobbMI", "curseforge:394468", "modrinth:AANobbMI"]}).only == \
        ["modrinth:AANobbMI", "curseforge:394468"]


def serve_curseforge(http, mods: dict):
    """CurseForge mods for the tests, by slug: {slug: (id, name)}, each with a Fabric 1.21.1 file."""
    import hashlib
    from craft_conductor.mods.curseforge import API as CURSEFORGE
    by_slug = {}
    for slug, (pid, name) in mods.items():
        body = {"id": pid, "slug": slug, "name": name, "classId": 6}
        by_slug[slug] = body
        http.json[f"{CURSEFORGE}/mods/{pid}"] = {"data": body}
        jar = f"{slug} jar".encode()
        url = f"https://edge.forgecdn.net/files/{pid}/{slug}.jar"
        http.files[url] = jar
        http.json[f"{CURSEFORGE}/mods/{pid}/files"] = {"data": [{
            "id": pid * 10, "modId": pid, "displayName": f"{name} 1.0", "fileName": f"{slug}.jar", "releaseType": 1,
            "downloadUrl": url, "gameVersions": ["1.21.1", "Fabric"], "fileDate": "2025-01-01T00:00:00Z",
            "hashes": [{"value": hashlib.sha1(jar).hexdigest(), "algo": 1}], "dependencies": []}]}
    http.json[f"{CURSEFORGE}/mods/search"] = lambda p: {"data": [by_slug[p["slug"]]] if p.get("slug") in by_slug else []}


def test_a_players_only_mod_added_by_its_slug_is_noted_at_the_check(make_config, http, modrinth):
    """Sodium from CurseForge, added by its slug to a server that's up to date: the check said
    "Left out: Sodium only runs on players' computers", but nothing was installed, so nothing noted it:
    Manage Mods kept "sodium · Added; installed with the next update" without the reason or Move to
    players' mods, and friends didn't get it (#134, #144). The check notes it, under the name it's
    listed by. A CurseForge mod installed under its slug is known by that name too (no second row)."""
    from craft_conductor import lock as lockmod
    serve_curseforge(http, {"sodium": (394468, "Sodium"), "appleskin": (248787, "AppleSkin")})
    modrinth.project("SODM", "sodium", "Sodium", server_side="unsupported")
    cfg = make_config([ModSpec("curseforge", "appleskin")])
    cfg.curseforge_api_key = "test-key"
    m = manager(cfg, http, ["1.21.1"])
    assert update(m).ok
    [skin] = m.lock.mods
    assert skin.name == "AppleSkin" and skin.listed_as == "curseforge:appleskin"
    skin.listed_as = None  # (as servers installed before this have it)
    lockmod.save(cfg.root, m.lock, touch=False)
    configmod.append_mod(cfg.path, ModSpec("curseforge", "sodium"))
    m.reload_config()
    m.config.curseforge_api_key = "test-key"
    m.providers = providers_for(m.config, http)
    decision, changes = m.check()
    assert changes.empty
    saved = lockmod.load(cfg.root)
    assert saved.client_only == {"curseforge:394468": "Sodium"} and "Modrinth says so" in saved.skipped["curseforge:394468"]
    assert saved.left_out_as == {"curseforge:394468": "curseforge:sodium"}
    assert [x.name for x in saved.players] == ["Sodium"]  # (the friends' download has it now)
    assert m.lock.left_out_as == saved.left_out_as
    assert saved.mods[0].listed_as == "curseforge:appleskin"


def test_manage_mods_shows_a_mod_left_off_by_its_slug_once(hub_env):
    """What the check noted (above): Manage Mods' row for "curseforge:sodium" is Sodium's, with
    its reason, not a second "sodium · Added; installed with the next update" row (#134)."""
    from craft_conductor import lock as lockmod
    hub, c = hub_env
    login(c)
    m = hub.get("alpha").m
    configmod.append_mod(m.config.path, ModSpec("curseforge", "sodium"))
    m.reload_config()
    m.lock.skipped = {"curseforge:394468": "Sodium only runs on players' computers (Modrinth says so)"}
    m.lock.client_only = {"curseforge:394468": "Sodium"}
    m.lock.left_out_as = {"curseforge:394468": "curseforge:sodium"}
    lockmod.save(m.config.root, m.lock, touch=False)
    r = c.get("/api/servers/alpha/mods")[1]
    [row] = [x for x in r["configured"] if x["source"] == "curseforge"]
    assert (row["key"], row["name"], row["version"]) == ("curseforge:394468", "Sodium", "")
    assert [x["key"] for x in r["skipped"]] == ["curseforge:394468"] and r["skipped"][0]["client_only"]
