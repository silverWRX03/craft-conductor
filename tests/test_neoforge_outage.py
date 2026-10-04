"""NeoForge's download site having an incomplete list of builds (as on 2026-09-28, when both of its
lists held only 26.3.0.33-beta for hours and no NeoForge 1.21.1 server could be created)."""

from craft_conductor.config import ModSpec
from craft_conductor.lock import Lock
from craft_conductor.loaders.forge import NEOFORGE_MAVEN, NEOFORGE_VERSIONS, NeoForgeLoader
from craft_conductor.mods import providers_for
from craft_conductor.planner import Planner

from conftest import FakeMojang

METADATA = f"{NEOFORGE_MAVEN}/maven-metadata.xml"
# What NeoForge's servers answered that day (from the e2e log).
OUTAGE_API = {"isSnapshot": False, "versions": ["26.3.0.33-beta"]}
OUTAGE_XML = ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<metadata>\n  <groupId>net.neoforged</groupId>\n"
              "  <artifactId>neoforge</artifactId>\n  <versioning>\n    <latest>26.3.0.33-beta</latest>\n"
              "    <release>26.3.0.33-beta</release>\n    <versions>\n      <version>26.3.0.33-beta</version>\n"
              "    </versions>\n  </versioning>\n</metadata>\n")
# A healthy list: many builds for many Minecraft versions, none for 1.21.4 (NeoForge skipped it).
HEALTHY = [f"20.4.{n}" for n in range(30)] + [f"21.1.{n}" for n in range(1, 78)] + ["21.3.1-beta"]


def outage(http):
    http.json[NEOFORGE_VERSIONS] = OUTAGE_API
    http.texts = {METADATA: OUTAGE_XML}


def loader(http):
    return NeoForgeLoader(http, FakeMojang(http, ["1.21.1", "26.3"]))


def test_an_incomplete_list_is_called_that_not_no_build_yet(http):
    outage(http)
    neoforge = loader(http)
    assert neoforge.latest_version("1.21.1") is None
    reason = neoforge.missing_reason("1.21.1")
    assert "lists only 1 build right now" in reason and "Minecraft 1.21.1" in reason and "try again later" in reason


def test_a_full_list_without_the_version_is_just_no_build_yet(http):
    http.json[NEOFORGE_VERSIONS] = {"versions": HEALTHY}
    neoforge = loader(http)
    assert neoforge.latest_version("1.21.1") == "21.1.77"
    assert neoforge.latest_version("1.21.4") is None
    assert neoforge.missing_reason("1.21.4") is None


def test_no_list_at_all_says_so(http):
    from craft_conductor.http import HttpError
    http.json[NEOFORGE_VERSIONS] = HttpError(NEOFORGE_VERSIONS, 403, "HTTP 403")
    http.texts = {}  # (maven-metadata.xml: 404)
    neoforge = loader(http)
    assert neoforge.latest_version("1.21.1") is None
    assert "didn't give its list of builds" in neoforge.missing_reason("1.21.1")


def test_entries_that_arent_versions_are_ignored(http):
    """Versions go into the installer's address and the launch file's path."""
    # (each would sort above the real build if it were taken as a version)
    http.json[NEOFORGE_VERSIONS] = {"versions": ["21.1.77", "21.1.999.1/../../../evil", "21.1.999 x"]}
    assert loader(http).latest_version("1.21.1") == "21.1.77"
    http.json[NEOFORGE_VERSIONS] = {"versions": []}
    http.texts = {METADATA: "<versions><version>21.1.5</version><version>21.1.8.1/../x</version></versions>"}
    assert loader(http).latest_version("1.21.1") == "21.1.5"


def test_the_full_list_is_read_once_per_check(http):
    """An update check asks about every newer Minecraft; maven-metadata.xml is large."""
    http.json[NEOFORGE_VERSIONS] = {"versions": ["26.1.1"]}  # (the API leaving older builds out)
    reads = []
    http.texts = {METADATA: "<versions><version>21.1.5</version></versions>"}
    real = http.get_text

    def counting(url, headers=None, limit=0):
        reads.append(url)
        return real(url, headers, limit)
    http.get_text = counting
    neoforge = loader(http)
    for minecraft in ("1.21.1", "1.21.2", "1.21.3", "1.21.4"):
        neoforge.latest_version(minecraft)
    neoforge.missing_reason("1.21.4")
    assert reads == [METADATA]


def neoforge_planner(make_config, http, modrinth, lock):
    modrinth.project("FERR", "ferrite-core", "FerriteCore")
    modrinth.version("FERR", "7.0", ["1.21.1"], loaders=("neoforge",))
    config = make_config([ModSpec("modrinth", "ferrite-core")])
    config.server.loader = "neoforge"
    config.updates.strategy = "mods-only"
    mojang = FakeMojang(http, ["1.21.1"])
    return Planner(config, lock, mojang, NeoForgeLoader(http, mojang), providers_for(config, http))


def test_a_new_server_during_the_outage_says_why(make_config, http, modrinth):
    outage(http)
    decision = neoforge_planner(make_config, http, modrinth, Lock()).decide()
    assert decision.plan is None
    blocked = decision.blocked[0]
    assert blocked.loader_version is None and "lists only 1 build" in blocked.loader_problem
    # (and when the loader has simply nothing yet, the usual words)
    blocked.loader_reason = None
    assert blocked.loader_problem == "neoforge has no build for Minecraft 1.21.1 yet"


def test_an_installed_server_keeps_its_neoforge_during_the_outage(make_config, http, modrinth):
    """Mod updates carry on with the build the server already runs; the loader isn't touched."""
    outage(http)
    lock = Lock(minecraft="1.21.1", loader="neoforge", loader_version="21.1.77", launch=["@args", "nogui"])
    decision = neoforge_planner(make_config, http, modrinth, lock).decide()
    assert decision.plan is not None and decision.plan.loader_version == "21.1.77"
    assert decision.plan.loader_reason is None
    changes = decision.plan.changes(lock)
    assert changes.loader is None and [m.name for m in changes.added] == ["FerriteCore"]


def test_the_cli_and_the_page_get_the_reason(make_config, http, modrinth, capsys):
    from craft_conductor.cli import _print_decision
    from craft_conductor.daemon import decision_to_dict
    outage(http)
    planner = neoforge_planner(make_config, http, modrinth, Lock())
    decision = planner.decide()

    class M:
        lock = planner.lock

        def missing_manual(self, plan):
            return []

        def unmanaged_jars(self):
            return []
    _print_decision(M(), decision, None)
    assert "x NeoForge's download site lists only 1 build" in capsys.readouterr().out
    blocked = decision_to_dict(M(), decision, None)["blocked"][0]
    assert blocked["loader_missing"] and "lists only 1 build" in blocked["loader_reason"]
