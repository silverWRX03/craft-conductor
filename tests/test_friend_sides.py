"""Friends' mods land on the right side: client-only mods stay with players, mods that run on both
sides are also the server's own (with what they need), and a friend's own search shows only mods
that run on their computer alone."""

import json

from craft_conductor import friendextras, join, joinui
from craft_conductor.browse import Browser, side_facets
from craft_conductor.mods.modrinth import API

from test_friends import pack
from test_hub import login
from test_manager import update
from test_web import Client


def record_searches(http):
    seen = []
    http.json[f"{API}/search"] = lambda params: seen.append(json.loads(params["facets"])) or {"total_hits": 0, "hits": []}
    return seen


# ------------------------------------------------------------ the friend's own search
def test_a_friends_mod_search_shows_only_client_side_only_mods(http):
    seen = record_searches(http)
    friendextras.search(http, "mod", "map", pack())
    facets = seen[-1]
    assert ["project_type:mod"] in facets and ["versions:1.21.1"] in facets
    assert ["client_side:required", "client_side:optional"] in facets   # side=client ...
    assert ["server_side:unsupported"] in facets                        # ... env=only: nothing the server runs too
    # The very same filter as the owner's mod browser for players.
    assert side_facets("client", "only") == [["client_side:required", "client_side:optional"], ["server_side:unsupported"]]
    Browser(http).search("modrinth", "mod", "map", loader="fabric", side="client", env="only")
    assert all(f in seen[-1] for f in side_facets("client", "only"))


def test_a_friends_search_says_where_the_next_page_starts(http):
    """The friend's More mods keeps scrolling to the real end, like the owner's mod browser."""
    from test_browse import fake_search
    seen = []
    http.json[f"{API}/search"] = fake_search(30, seen)
    first = friendextras.search(http, "resourcepack", "", pack())
    assert len(first["results"]) == 20 and first["next"] == 20 and first["total"] == 30
    last = friendextras.search(http, "resourcepack", "", pack(), offset=20)
    assert len(last["results"]) == 10 and last["next"] is None
    friendextras.search(http, "resourcepack", "", pack(), offset=50_000)
    assert seen == [0, 20, 9_980]  # (no deeper than Modrinth's search goes)


def test_modpacks_resource_packs_and_shaders_keep_their_own_filters(http):
    seen = record_searches(http)
    for kind, project_type in (("resourcepack", "resourcepack"), ("shader", "shader")):
        friendextras.search(http, kind, "x", pack())
        facets = seen[-1]
        assert [f"project_type:{project_type}"] in facets
        assert not any(f.startswith(("client_side", "server_side")) for group in facets for f in group), (kind, facets)
    # The owner's browser: modpacks have no environment narrowing; mods do.
    Browser(http).search("modrinth", "modpack", "x", loader="fabric", side="client", env="only")
    assert ["server_side:unsupported"] not in seen[-1]
    Browser(http).search("modrinth", "mod", "x", loader="fabric", side="client", env="both")
    assert ["server_side:required", "server_side:optional"] in seen[-1]
    Browser(http).search("modrinth", "mod", "x", loader="fabric", side="server", env="only")
    assert ["client_side:unsupported"] in seen[-1]


def test_the_friends_page_asks_for_client_side_only_mods(tmp_path, http):
    seen = record_searches(http)
    http.json["https://mc.example.com:8766/join/" + "C" * 24 + "/pack.json"] = pack(name="Weekend Server")
    ui = joinui.JoinUI(join.Invite("mc.example.com", 8766, "C" * 24, "F" * 43), mc_dir=tmp_path / ".minecraft", http=http,
                       prism_dir=tmp_path / "prism", out_dir=tmp_path)
    url = ui.start()
    try:
        c = Client(url.rstrip("/"))
        c.get("/api/info")
        assert c.get("/api/extras/search?kind=mod&q=map")[0] == 200
        assert ["server_side:unsupported"] in seen[-1]
        assert c.get("/api/extras/search?kind=shader&q=bsl")[0] == 200
        assert ["server_side:unsupported"] not in seen[-1]
    finally:
        ui.stop()


# --------------------------------------------------------------- the owner's side
def publish(modrinth):
    modrinth.project("MAPM", "minimap", "Mini Map", server_side="unsupported")          # players only
    modrinth.version("MAPM", "2.0", ["1.21.1"])
    modrinth.project("LIB", "recipe-lib", "Recipe Library", client_side="required", server_side="required")
    modrinth.version("LIB", "1.0", ["1.21.1"])
    modrinth.project("REC", "recipes", "Recipe Viewer", client_side="required", server_side="optional")  # both sides
    modrinth.version("REC", "3.0", ["1.21.1"], deps=["LIB"])
    modrinth.project("OLD", "oldmod", "Old Mod", client_side="required", server_side="required")        # no build for 1.21.1
    modrinth.version("OLD", "1.0", ["1.20.1"])


def listed(hub):
    m = hub.get("alpha").m
    m.reload_config()
    return {(s.id, s.required) for s in m.config.mods}


def test_a_mod_for_players_that_runs_on_both_sides_is_added_to_the_server_too(hub_env, modrinth):
    hub, c = hub_env
    login(c)
    publish(modrinth)
    base = "/api/servers/alpha/client"
    # A client-only mod stays with the players.
    r = c.post(base, {"mods": ["minimap"]})[1]
    assert r["also_on_server"] == [] and r["server_skipped"] == [] and r["mods_on_server"] == []
    assert "minimap" not in {i for i, _ in listed(hub)}
    # A mod that runs on both is also one of the server's mods, with its required library.
    r = c.post(base, {"mods": ["minimap", "recipes"]})[1]
    assert r["also_on_server"] == [{"name": "Recipe Viewer", "deps": ["Recipe Library"]}]
    assert r["mods"] == ["minimap", "recipes"] and r["mods_on_server"] == ["recipes"]
    assert listed(hub) == {("recipes", False)}  # (the server only optionally supports it: it never holds an update)
    # The library is resolved the way any server mod's needs are: it's installed with it, as its dependency.
    m = hub.get("alpha").m
    assert update(m).ok
    assert {(x.name, x.dependency_of) for x in m.lock.mods if x.name != "Fabric API"} == {
        ("Recipe Viewer", None), ("Recipe Library", "modrinth:REC")}
    # Players still get all of it: the server's mods, and the client-only one.
    from craft_conductor.clientpack import PackBuilder
    sides = {x["name"]: x["side"] for x in PackBuilder(m).build("mc.example.com")["mods"]}
    assert sides["Recipe Viewer"] == "both" and sides["Recipe Library"] == "both" and sides["Mini Map"] == "client"
    # Saving the same list again adds nothing more.
    r = c.post(base, {"mods": ["minimap", "recipes"]})[1]
    assert r["also_on_server"] == [] and listed(hub) == {("recipes", False)}
    # Other settings don't mention it.
    assert "also_on_server" not in c.post(base, {"memory_gb": 5})[1]


def test_a_mod_the_server_requires_is_added_as_required(hub_env, modrinth):
    hub, c = hub_env
    login(c)
    publish(modrinth)
    modrinth.project("MST", "must-have", "Must Have", client_side="required", server_side="required")
    modrinth.version("MST", "1.0", ["1.21.1"])
    assert c.post("/api/servers/alpha/client", {"mods": ["must-have"]})[1]["also_on_server"] == [{"name": "Must Have", "deps": []}]
    assert listed(hub) == {("must-have", True)}


def test_a_mod_the_server_already_has_is_not_added_twice(hub_env, modrinth):
    hub, c = hub_env
    login(c)
    publish(modrinth)
    assert c.post("/api/servers/alpha/mods/add", {"id": "recipes"})[0] == 200
    r = c.post("/api/servers/alpha/client", {"mods": ["recipes"]})[1]
    assert r["also_on_server"] == [] and r["mods_on_server"] == ["recipes"]
    assert [i for i, _ in listed(hub)] == ["recipes"]


def test_a_both_sides_mod_the_server_cant_run_is_said_so_and_players_still_get_it(hub_env, modrinth):
    hub, c = hub_env
    login(c)
    publish(modrinth)
    r = c.post("/api/servers/alpha/client", {"mods": ["oldmod"]})[1]
    assert r["mods"] == ["oldmod"] and r["also_on_server"] == []
    assert [x["name"] for x in r["server_skipped"]] == ["Old Mod"]
    assert "no build for Minecraft 1.21.1" in r["server_skipped"][0]["reason"]
    assert listed(hub) == set()


def test_removing_a_mod_from_the_players_asks_about_the_server_too(hub_env, modrinth):
    hub, c = hub_env
    login(c)
    publish(modrinth)
    base = "/api/servers/alpha/client"
    c.post(base, {"mods": ["minimap", "recipes"]})
    # Taken off the players' list alone: it stays one of the server's mods.
    r = c.post(base, {"mods": ["minimap"]})[1]
    assert r["mods"] == ["minimap"] and r["mods_on_server"] == []
    assert listed(hub) == {("recipes", False)}
    # "Remove it from the server too": gone from craft-conductor.toml.
    c.post(base, {"mods": ["minimap", "recipes"]})
    r = c.post(base, {"mods": ["minimap"], "remove_from_server": ["recipes"]})[1]
    assert listed(hub) == set() and r["mods"] == ["minimap"]
    # A mod still on the players' list isn't removed from the server by it, and nothing else is touched.
    c.post("/api/servers/alpha/mods/add", {"id": "recipes"})
    c.post(base, {"mods": ["recipes"]})
    c.post(base, {"mods": ["recipes"], "remove_from_server": ["recipes", "minimap", "never-heard-of-it"]})
    assert [i for i, _ in listed(hub)] == ["recipes"]
    for bad in ("recipes", ["../x"], [3]):
        assert c.post(base, {"mods": [], "remove_from_server": bad})[0] == 400
    assert [i for i, _ in listed(hub)] == ["recipes"]


def test_plain_minecraft_and_plugin_servers_add_nothing(hub_env, modrinth):
    hub, c = hub_env
    login(c)
    publish(modrinth)
    m = hub.get("alpha").m
    m.loader.mod_loaders = ()  # (a server type that runs no mods)
    assert c.post("/api/servers/alpha/client", {"mods": ["recipes"]})[1]["also_on_server"] == []
    assert listed(hub) == set()


def test_a_name_from_modrinth_is_never_written_to_the_config_unchecked(hub_env, http, modrinth):
    """A slug is the site's answer (and can hold quote marks): only a plain name goes into craft-conductor.toml."""
    hub, c = hub_env
    login(c)
    modrinth.project("QUO", 'odd"slug\nid = "x', "Odd Mod", client_side="required", server_side="required")
    modrinth.version("QUO", "1.0", ["1.21.1"])
    base = "/api/servers/alpha"
    # (found by its id, as a slug can't be asked for) it's written under its id, which is plain
    http.json[f"https://api.modrinth.com/v2/project/oddmod"] = http.json["https://api.modrinth.com/v2/project/QUO"]
    assert c.post(f"{base}/mods/add", {"id": "oddmod"})[0] == 200
    text = hub.get("alpha").m.config.path.read_text()
    assert 'id = "QUO"' in text and "odd\"slug" not in text
    # With no plain name at all, it's refused.
    modrinth.project("w!rd", 'odd"slug', "Weird Mod", client_side="required", server_side="required")
    modrinth.version("w!rd", "1.0", ["1.21.1"])
    http.json["https://api.modrinth.com/v2/project/weirdmod"] = http.json["https://api.modrinth.com/v2/project/w!rd"]
    status, r, _ = c.post(f"{base}/mods/add", {"id": "weirdmod"})
    assert status == 400 and "isn't safe to save" in r["error"]
    assert "w!rd" not in hub.get("alpha").m.config.path.read_text()
