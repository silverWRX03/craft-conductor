"""A new server is made on the Minecraft version and server type chosen for it (B6).

Mods are resolved around those choices: a required dependency is looked for on the site that
names it, then on the other one (CurseForge and Modrinth), for the same Minecraft version and
loader. When it can't be found on either, the conflict says what needs what and where it
looked, and other Minecraft versions are only suggested. An installed server's upgrades still
weigh newer versions against the mods.
"""

import hashlib

import pytest

from craft_conductor.config import ModSpec
from craft_conductor.daemon import Daemon, decision_to_dict
from craft_conductor.lock import Lock
from craft_conductor.mods import curseforge as cf
from craft_conductor.mods import providers_for
from craft_conductor.mods.modrinth import API as MODRINTH, ModrinthProvider
from craft_conductor.planner import CREATE, UPGRADE, Planner
from craft_conductor.web import mod_requirements

from conftest import FakeLoader, FakeMojang

OLD, NEW = "1.21.1", "1.21.2"
RELEASES = [OLD, NEW]
KEY = "fake-curseforge-key"  # (not a real key)


class FakeNeoForge(FakeLoader):
    name = "neoforge"
    mod_loaders = ("neoforge",)


class CurseForgeFixture:
    """Build CurseForge API answers for made-up mods."""

    def __init__(self, http):
        self.http = http
        self.mods: dict[int, dict] = {}
        self.files: dict[int, list[dict]] = {}
        http.json[f"{cf.API}/mods/search"] = self._search

    def project(self, mod_id: int, slug: str, name: str):
        self.mods[mod_id] = {"id": mod_id, "slug": slug, "name": name}
        self.files[mod_id] = []
        self.http.json[f"{cf.API}/mods/{mod_id}"] = {"data": self.mods[mod_id]}
        self.http.json[f"{cf.API}/mods/{mod_id}/files"] = lambda params, mod_id=mod_id: self._files(mod_id, params)

    def file(self, mod_id: int, game_versions: list[str], deps: list[int] = (), loaders=("neoforge",)):
        n = len(self.files[mod_id]) + 1
        content = f"cf {mod_id} {n}".encode()
        url = f"https://edge.forgecdn.net/files/{mod_id}/{n}/mod-{mod_id}-{n}.jar"
        self.http.files[url] = content
        self.files[mod_id].append({
            "id": mod_id * 100 + n, "displayName": f"{self.mods[mod_id]['name']} {n}", "fileName": f"mod-{mod_id}-{n}.jar",
            "downloadUrl": url, "gameVersions": list(game_versions), "loaders": list(loaders), "releaseType": 1,
            "fileDate": f"2025-03-{n:02d}T00:00:00Z", "hashes": [{"algo": 1, "value": hashlib.sha1(content).hexdigest()}],
            "dependencies": [{"modId": d, "relationType": cf.REQUIRED_DEPENDENCY} for d in deps]})

    def _files(self, mod_id, params):
        loader = next(name for name, n in cf.LOADER_TYPES.items() if n == int(params["modLoaderType"]))
        found = [f for f in self.files[mod_id] if loader in f["loaders"]
                 and ("gameVersion" not in params or params["gameVersion"] in f["gameVersions"])]
        start = int(params.get("index", 0))
        return {"data": found[start:start + int(params.get("pageSize", 50))]}

    def _search(self, params):
        if "slug" in params:
            return {"data": [m for m in self.mods.values() if m["slug"] == params["slug"]]}
        return {"data": [m for m in self.mods.values() if params.get("searchFilter", "").lower() in m["name"].lower()]}


@pytest.fixture
def curseforge(http):
    http.json[f"{MODRINTH}/search"] = {"hits": []}  # (Modrinth's search, when it has no project with that slug)
    return CurseForgeFixture(http)


def planner(make_config, http, mods, minecraft=NEW, lock=None, releases=RELEASES, **updates):
    config = make_config(mods, minecraft=minecraft, **updates)
    config.server.loader = "neoforge"
    config.curseforge_api_key = KEY
    mojang = FakeMojang(http, releases)
    return Planner(config, lock or Lock(), mojang, FakeNeoForge(http, mojang), providers_for(config, http))


def biomes(curseforge, glitchcore_versions):
    """Biomes O' Plenty on CurseForge, which needs GlitchCore (also on CurseForge)."""
    curseforge.project(220318, "biomes-o-plenty", "Biomes O' Plenty")
    curseforge.file(220318, [OLD, NEW, "NeoForge"], deps=[955399])
    curseforge.project(955399, "glitchcore", "GlitchCore")
    if glitchcore_versions:
        curseforge.file(955399, [*glitchcore_versions, "NeoForge"])


def modrinth_glitchcore(modrinth, versions):
    modrinth.project("GLC", "glitchcore", "GlitchCore")
    modrinth.version("GLC", "1.0", versions, loaders=("neoforge",))


BOP = [ModSpec("curseforge", "220318")]


def test_a_dependency_on_curseforge_resolves_and_minecraft_stays(make_config, http, curseforge):
    """Test A."""
    biomes(curseforge, [NEW])
    decision = planner(make_config, http, BOP).decide()
    assert decision.policy == CREATE
    assert decision.plan.minecraft == NEW
    mods = {m.name: m for m in decision.plan.mods}
    assert mods["GlitchCore"].source == "curseforge" and mods["GlitchCore"].dependency_of == "curseforge:220318"


def test_a_dependency_only_on_modrinth_comes_from_modrinth(make_config, http, curseforge, modrinth):
    """Test B: CurseForge has no GlitchCore for this Minecraft; Modrinth does."""
    biomes(curseforge, [OLD])
    modrinth_glitchcore(modrinth, [NEW])
    decision = planner(make_config, http, BOP).decide()
    assert decision.plan is not None and decision.plan.minecraft == NEW
    assert not decision.blocked and not decision.plan.blockers and not decision.plan.dropped
    mods = {m.name: m for m in decision.plan.mods}
    assert set(mods) == {"Biomes O' Plenty", "GlitchCore"}  # one GlitchCore
    assert mods["GlitchCore"].source == "modrinth" and mods["GlitchCore"].dependency_of == "curseforge:220318"


def test_a_modrinth_mods_dependency_can_come_from_curseforge(make_config, http, curseforge, modrinth):
    modrinth.project("TOP", "topmod", "Top Mod")
    modrinth.version("TOP", "1.0", [NEW], deps=["LIB"], loaders=("neoforge",))
    modrinth.project("LIB", "somelib", "Some Lib")
    modrinth.version("LIB", "1.0", [OLD], loaders=("neoforge",))
    curseforge.project(42, "somelib", "Some Lib")
    curseforge.file(42, [NEW, "NeoForge"])
    plan = planner(make_config, http, [ModSpec("modrinth", "topmod")]).decide().plan
    assert plan.minecraft == NEW
    assert {(m.name, m.source) for m in plan.mods} == {("Top Mod", "modrinth"), ("Some Lib", "curseforge")}


def test_a_dependency_on_neither_site_is_a_clear_conflict(make_config, http, curseforge, modrinth):
    """Test C."""
    biomes(curseforge, [OLD])
    modrinth_glitchcore(modrinth, [OLD])
    p = planner(make_config, http, BOP)
    decision = p.decide()
    assert decision.plan is None
    blocked = decision.blocked[0]
    assert [b.minecraft for b in decision.blocked] == [NEW]  # the version chosen, and no other
    top = next(b for b in blocked.blockers if b.name == "Biomes O' Plenty")
    assert top.chain == ["Biomes O' Plenty", "GlitchCore"] and top.checked == ["CurseForge", "Modrinth"]
    text = top.explain(blocked.minecraft, blocked.loader)
    assert text.startswith("Biomes O' Plenty requires GlitchCore, but no compatible GlitchCore release was found "
                           f"for Minecraft {NEW} using NeoForge. Craft Conductor checked CurseForge and Modrinth")
    # ...and the page gets it all
    class M:
        lock = p.lock

        def missing_manual(self, plan):
            return []

        def unmanaged_jars(self):
            return []
    shown = decision_to_dict(M(), decision, None)["blocked"][0]
    assert shown["minecraft"] == NEW
    entry = next(b for b in shown["blockers"] if b["name"] == "Biomes O' Plenty")
    assert entry["chain"] == ["Biomes O' Plenty", "GlitchCore"] and entry["checked"] == ["CurseForge", "Modrinth"]
    assert entry["explain"] == text


def test_without_a_curseforge_key_it_says_curseforge_wasnt_checked(make_config, http, curseforge, modrinth):
    modrinth.project("TOP", "topmod", "Top Mod")
    modrinth.version("TOP", "1.0", [NEW], deps=["LIB"], loaders=("neoforge",))
    modrinth.project("LIB", "somelib", "Some Lib")
    modrinth.version("LIB", "1.0", [OLD], loaders=("neoforge",))
    p = planner(make_config, http, [ModSpec("modrinth", "topmod")])
    p.providers["curseforge"].api_key = ""
    top = next(b for b in p.decide().blocked[0].blockers if b.name == "Top Mod")
    assert top.checked == ["Modrinth"] and "CurseForge couldn't be checked: no CurseForge API key" in top.unchecked[0]


@pytest.mark.parametrize("chosen", [NEW, "latest"])
def test_an_older_minecraft_that_would_work_is_only_suggested(make_config, http, curseforge, modrinth, chosen):
    """Test D: GlitchCore has builds for the older Minecraft only. Choosing the newest one
    (by its number, or as "Newest release") makes nothing on the older one."""
    biomes(curseforge, [OLD])
    modrinth_glitchcore(modrinth, [OLD])
    p = planner(make_config, http, BOP, minecraft=chosen)
    decision = p.decide()
    assert decision.plan is None and [b.minecraft for b in decision.blocked] == [NEW]
    assert p.alternatives(NEW) == [OLD]  # offered, not applied
    assert p.decide().plan is None  # (asking again changes nothing)


def test_a_failed_setup_says_so_and_keeps_the_version(make_config, http, curseforge, modrinth, fake_template):
    """Test D, as the setup page sees it: the server isn't made on the older Minecraft."""
    from craft_conductor import config as configmod, setup as setupmod
    from craft_conductor.manager import Manager
    biomes(curseforge, [OLD])
    modrinth_glitchcore(modrinth, [OLD])
    cfg = make_config([])
    mojang = FakeMojang(http, RELEASES)
    m = Manager(cfg, http=http, mojang=mojang, loader=FakeNeoForge(http, mojang), providers=providers_for(cfg, http),
                echo=False, sleep=lambda s: None)
    m.providers["curseforge"].api_key = KEY

    def reload_config():  # (keeping the made-up NeoForge)
        m.config = configmod.load(cfg.root)
    m.reload_config = reload_config
    spec = setupmod.SetupSpec.from_dict({"loader": "neoforge", "minecraft": "latest", "mods": ["curseforge:220318"],
                                         "accept_eula": True})
    with pytest.raises(RuntimeError) as failure:
        Daemon(m, autostart=False).run_setup(spec)
    message = str(failure.value)
    assert message.startswith(f"Minecraft {NEW} with NeoForge doesn't work with these choices. "
                              "Biomes O' Plenty requires GlitchCore, but no compatible GlitchCore release was found "
                              f"for Minecraft {NEW} using NeoForge. Craft Conductor checked CurseForge and Modrinth.")
    assert "Your Minecraft version has not been changed." in message
    assert f"These choices appear to work on Minecraft {OLD}: to use one, pick it under Minecraft version" in message
    assert not m.lock.installed and m.lock.minecraft is None
    assert configmod.load(cfg.root).server.minecraft == "latest"  # (as chosen)


def test_a_missing_dependency_of_a_dependency_names_the_chain(make_config, http, curseforge, modrinth):
    """Test E: A needs B, B needs C, and C has no build for this Minecraft anywhere."""
    curseforge.project(1, "mod-a", "Mod A")
    curseforge.file(1, [NEW, "NeoForge"], deps=[2])
    curseforge.project(2, "mod-b", "Mod B")
    curseforge.file(2, [NEW, "NeoForge"], deps=[3])
    curseforge.project(3, "mod-c", "Mod C")
    curseforge.file(3, [OLD, "NeoForge"])
    modrinth.project("MC", "mod-c", "Mod C")
    modrinth.version("MC", "1.0", [OLD], loaders=("neoforge",))
    decision = planner(make_config, http, [ModSpec("curseforge", "1")]).decide()
    assert decision.plan is None and [b.minecraft for b in decision.blocked] == [NEW]
    blocked = decision.blocked[0]
    top = next(b for b in blocked.blockers if b.name == "Mod A")
    assert top.chain == ["Mod A", "Mod B", "Mod C"] and top.checked == ["CurseForge", "Modrinth"]
    assert top.explain(NEW, "neoforge").startswith(
        f"Mod A requires Mod B, which requires Mod C, but no compatible Mod C release was found for Minecraft {NEW} "
        "using NeoForge. Craft Conductor checked CurseForge and Modrinth")


def test_the_same_mod_from_both_sites_is_installed_once(make_config, http, curseforge, modrinth):
    """GlitchCore picked from Modrinth, and needed by a CurseForge mod: one copy, yours."""
    biomes(curseforge, [NEW])
    modrinth_glitchcore(modrinth, [NEW])
    plan = planner(make_config, http, [ModSpec("modrinth", "glitchcore"), *BOP]).decide().plan
    assert sorted((m.name, m.source) for m in plan.mods) == [("Biomes O' Plenty", "curseforge"), ("GlitchCore", "modrinth")]
    # Two mods from different sites that need the same library: one copy, from where it was found first.
    modrinth.project("TOP", "topmod", "Top Mod")
    modrinth.version("TOP", "1.0", [NEW], deps=["GLC"], loaders=("neoforge",))
    plan = planner(make_config, http, [*BOP, ModSpec("modrinth", "topmod")]).decide().plan
    assert sorted((m.name, m.source) for m in plan.mods) == [
        ("Biomes O' Plenty", "curseforge"), ("GlitchCore", "curseforge"), ("Top Mod", "modrinth")]


def test_newest_release_follows_the_loader_never_the_mods(make_config, http, curseforge, modrinth):
    """"Newest release" is the newest Minecraft the server type runs; a mod that isn't ready
    for it doesn't move the server to an older one."""
    biomes(curseforge, [OLD])
    modrinth_glitchcore(modrinth, [OLD])
    p = planner(make_config, http, BOP, minecraft="latest", releases=[OLD, NEW, "1.21.3"])
    p.loader.supported = {OLD, NEW}  # the loader has nothing for 1.21.3 yet
    assert p.current_version() == NEW
    decision = p.decide()
    assert decision.plan is None and [b.minecraft for b in decision.blocked] == [NEW]


def test_upgrades_still_weigh_newer_minecraft_against_the_mods(make_config, http, curseforge, modrinth):
    """Test F: an installed server's upgrade compatibility analysis is unchanged."""
    biomes(curseforge, [OLD])
    modrinth_glitchcore(modrinth, [OLD])
    installed = Lock(minecraft=OLD, loader="neoforge", loader_version=f"loader-{OLD}", launch=["x"])
    p = planner(make_config, http, BOP, minecraft="latest", lock=installed)
    decision = p.decide()
    assert decision.policy == UPGRADE
    # GlitchCore isn't ready for 1.21.2 on either site: the server stays where it is, and says why.
    assert decision.plan.minecraft == OLD and [b.minecraft for b in decision.blocked] == [NEW]
    # Once it is (here: on Modrinth only), the upgrade goes ahead.
    modrinth.version("GLC", "1.1", [NEW], loaders=("neoforge",))
    decision = planner(make_config, http, BOP, minecraft="latest", lock=installed).decide()
    assert decision.plan.minecraft == NEW
    assert {(m.name, m.source) for m in decision.plan.mods} == {("Biomes O' Plenty", "curseforge"), ("GlitchCore", "modrinth")}
    # An explicit update to a version still checks that version only.
    assert planner(make_config, http, BOP, lock=installed).decide(OLD).plan.minecraft == OLD


# ----------------------------------------------------- the setup page's check

def test_the_setup_check_looks_on_both_sites(http, curseforge, modrinth):
    modrinth.project("TOP", "topmod", "Top Mod")
    modrinth.version("TOP", "1.0", [OLD, NEW], deps=["LIB"], loaders=("neoforge",))
    modrinth.project("LIB", "somelib", "Some Lib")
    modrinth.version("LIB", "1.0", [OLD], loaders=("neoforge",))
    provider, cfp = ModrinthProvider(http), cf.CurseForgeProvider(http, KEY)
    r = mod_requirements(provider, "topmod", ("neoforge",), NEW, curseforge=cfp)
    assert not r["compatible"] and r["minecraft"] == NEW
    assert r["reason"] == (f"Top Mod requires Some Lib, but no compatible Some Lib release was found for Minecraft {NEW} "
                           "using NeoForge. Craft Conductor checked Modrinth and CurseForge.")
    assert r["chain"] == ["Top Mod", "Some Lib"] and r["suggestions"] == [OLD]
    # CurseForge has it: compatible, from there
    curseforge.project(42, "somelib", "Some Lib")
    curseforge.file(42, [NEW, "NeoForge"])
    r = mod_requirements(provider, "topmod", ("neoforge",), NEW, curseforge=cfp)
    assert r["compatible"] and [(d["name"], d["source"]) for d in r["deps"]] == [("Some Lib", "curseforge")]


def test_the_setup_check_covers_curseforge_mods_and_chains(http, curseforge, modrinth):
    curseforge.project(1, "mod-a", "Mod A")
    curseforge.file(1, [OLD, NEW, "NeoForge"], deps=[2])
    curseforge.project(2, "mod-b", "Mod B")
    curseforge.file(2, [OLD, NEW, "NeoForge"], deps=[3])
    curseforge.project(3, "mod-c", "Mod C")
    curseforge.file(3, [OLD, "NeoForge"])
    r = mod_requirements(ModrinthProvider(http), "curseforge:1", ("neoforge",), NEW,
                         curseforge=cf.CurseForgeProvider(http, KEY))
    assert not r["compatible"] and r["chain"] == ["Mod A", "Mod B", "Mod C"]
    assert r["checked"] == ["CurseForge", "Modrinth"] and r["suggestions"] == [OLD]
    assert r["reason"].startswith("Mod A requires Mod B, which requires Mod C, but no compatible Mod C release")
    assert r["project"]["source"] == "curseforge"


def test_the_setup_page_endpoints(hub_env, curseforge, modrinth, monkeypatch):
    from test_hub import login
    hub, c = hub_env
    login(c)
    monkeypatch.setenv("CRAFT_CONDUCTOR_CURSEFORGE_API_KEY", KEY)
    biomes(curseforge, [OLD])
    modrinth_glitchcore(modrinth, [OLD])
    r = c.get(f"/api/hub/mods/requires?id=curseforge:220318&loader=neoforge&version={NEW}")[1]
    assert not r["compatible"] and r["checked"] == ["CurseForge", "Modrinth"] and r["minecraft"] == NEW
    assert c.get("/api/hub/mods/requires?id=curseforge:abc&loader=neoforge")[0] == 400
    assert c.get("/api/hub/setup/newest?loader=nope")[0] == 400
    assert c.get("/api/hub/setup/newest?loader=vanilla")[1] == {"loader": "vanilla", "minecraft": "1.21.1"}


def test_the_cli_keeps_the_version_and_suggests(make_config, http, curseforge, modrinth, capsys):
    from craft_conductor.cli import _print_decision
    biomes(curseforge, [OLD])
    modrinth_glitchcore(modrinth, [OLD])
    p = planner(make_config, http, BOP)

    class M:
        lock = p.lock

        def planner(self):
            return p

        def missing_manual(self, plan):
            return []

        def unmanaged_jars(self):
            return []
    _print_decision(M(), p.decide(), None)
    out = capsys.readouterr().out
    assert f"Minecraft {NEW} is blocked by:" in out and "Biomes O' Plenty requires GlitchCore" in out
    assert "kept as they are" in out and f"appear to work on Minecraft {OLD}" in out


def top_mod_on_both_sites(curseforge, modrinth):
    """Top Mod, picked on Modrinth: no NeoForge build for NEW there; CurseForge has one."""
    modrinth.project("TOP", "topmod", "Top Mod")
    modrinth.version("TOP", "1.0", [NEW], loaders=("fabric",))
    curseforge.project(42, "topmod", "Top Mod")
    curseforge.file(42, [NEW, "NeoForge"])


def test_a_picked_mod_with_no_build_where_it_was_picked_comes_from_the_other_site(make_config, http, curseforge, modrinth):
    top_mod_on_both_sites(curseforge, modrinth)
    plan = planner(make_config, http, [ModSpec("modrinth", "topmod")]).decide().plan
    assert plan is not None and plan.minecraft == NEW
    [mod] = plan.mods
    assert (mod.name, mod.source, mod.listed_as) == ("Top Mod", "curseforge", "modrinth:topmod")
    # (and the setup page's check says where it comes from)
    r = mod_requirements(ModrinthProvider(http), "topmod", ("neoforge",), NEW, curseforge=cf.CurseForgeProvider(http, KEY))
    assert r["compatible"] and r["from"]["site"] == "CurseForge" and r["from"]["picked"] == "Modrinth"


def terralith(modrinth):
    """Like Terralith on Minecraft 26.x: Fabric and NeoForge builds need a library; a datapack doesn't."""
    modrinth.project("LITH", "lithostitched", "Lithostitched")
    modrinth.version("LITH", "1.0", [NEW], loaders=("fabric", "neoforge"))
    modrinth.project("TERRA", "terralith", "Terralith")
    modrinth.version("TERRA", "2.6", [NEW], deps=["LITH"], loaders=("fabric",))
    modrinth.version("TERRA", "2.6n", [NEW], deps=["LITH"], loaders=("neoforge",))
    modrinth.version("TERRA", "2.6d", [NEW], loaders=("datapack",), filename="Terralith_2.6.zip")
    modrinth.version("TERRA", "2.5", [OLD], loaders=("forge",))


def test_the_setup_check_says_which_server_types_and_a_datapack_have_it(http, curseforge, modrinth):
    terralith(modrinth)
    provider, cfp = ModrinthProvider(http), cf.CurseForgeProvider(http, KEY)
    r = mod_requirements(provider, "terralith", ("forge",), NEW, curseforge=cfp)
    assert not r["compatible"] and r["checked"] == ["Modrinth", "CurseForge"]
    assert r["builds"] == ["neoforge", "fabric"] and r["datapack"] is True and r["suggestions"] == [OLD]
    # Its datapack build: nothing else needed
    r = mod_requirements(provider, "terralith", ("forge",), NEW, curseforge=cfp, datapack=True)
    assert r["compatible"] and r["deps"] == [] and r["loader"] == "Forge"
    r = mod_requirements(provider, "terralith", ("forge",), OLD, curseforge=cfp, datapack=True)
    assert not r["compatible"] and r["reason"] == f"Terralith's datapack has no build for Minecraft {OLD}"
