"""The web map: which one is installed, its port, and BlueMap's download OK."""

from types import SimpleNamespace

import pytest

from craft_conductor import webmap
from craft_conductor.http import HttpError
from craft_conductor.mods.modrinth import API, ModrinthProvider

from test_manager import update


def mod(name, filename=""):
    return SimpleNamespace(name=name, key=name.lower(), filename=filename)


def test_which_map_is_installed():
    assert webmap.installed([mod("Lithium"), mod("BlueMap", "bluemap-5.4-fabric.jar")]) == "bluemap"
    assert webmap.installed([mod("dynmap®")]) == "dynmap"
    assert webmap.installed([mod("Chunky")]) is None


def test_port_and_download(tmp_path):
    folder = tmp_path / "config" / "bluemap"
    assert webmap.port(tmp_path, "bluemap", "fabric") == 8100  # not set up yet: the default
    with pytest.raises(webmap.WebMapError):
        webmap.set_port(tmp_path, "bluemap", "fabric", 8200)
    assert webmap.download_accepted(tmp_path, "fabric") is None
    folder.mkdir(parents=True)
    (folder / "webserver.conf").write_text('enabled: true\n# the port\nport: 8100\nlog: {\n  file: "x"\n}\n')
    (folder / "core.conf").write_text("# read Mojang's terms\naccept-download: false\nrender-thread-count: 1\n")
    assert webmap.download_accepted(tmp_path, "fabric") is False
    webmap.accept_download(tmp_path, "fabric")
    assert webmap.download_accepted(tmp_path, "fabric") is True
    assert "render-thread-count: 1" in (folder / "core.conf").read_text()
    webmap.set_port(tmp_path, "bluemap", "fabric", 8200)
    assert webmap.port(tmp_path, "bluemap", "fabric") == 8200
    with pytest.raises(webmap.WebMapError):
        webmap.set_port(tmp_path, "bluemap", "fabric", 25565, taken={25565})
    with pytest.raises(webmap.WebMapError):
        webmap.set_port(tmp_path, "bluemap", "fabric", 80)


def test_dynmap_as_a_plugin(tmp_path):
    folder = tmp_path / "plugins" / "dynmap"
    folder.mkdir(parents=True)
    (folder / "configuration.txt").write_text("deftemplatesuffix: hires\nwebserver-bindaddress: 0.0.0.0\nwebserver-port: 8123\n")
    assert webmap.port(tmp_path, "dynmap", "paper") == 8123
    webmap.set_port(tmp_path, "dynmap", "paper", 8124)
    assert "webserver-port: 8124" in (folder / "configuration.txt").read_text()


def test_the_page(hub_env):
    from test_hub import login
    hub, c = hub_env
    login(c)
    status, r, _ = c.get("/api/servers/alpha/webmap")
    assert status == 200 and r["kind"] is None and r["maps"] == {"bluemap": "BlueMap", "dynmap": "Dynmap"}
    assert c.post("/api/servers/alpha/webmap/add", {"kind": "squaremap"})[0] == 400
    assert c.post("/api/servers/alpha/webmap/port", {"port": 8200})[0] == 400


def publish_maps(modrinth, bluemap=("1.21.1",), dynmap=("1.20.1",)):
    """BlueMap and Dynmap on a fake Modrinth, each with builds for just these Minecraft versions."""
    for pid, slug, name, versions in (("BLM", "bluemap", "BlueMap", bluemap), ("DYN", "dynmap", "Dynmap", dynmap)):
        modrinth.project(pid, slug, name)
        if versions:
            modrinth.version(pid, "1.0", list(versions))


def version_lookups(http):
    """Count the requests made for a project's builds (what the map check costs)."""
    calls = []
    original = http.get_json

    def counting(url, params=None, headers=None, cache=True):
        if url.endswith("/version"):
            calls.append(url)
        return original(url, params, headers, cache)
    http.get_json = counting
    return calls


def test_only_the_map_with_a_build_is_offered(hub_env, http, modrinth):
    from test_hub import login
    hub, c = hub_env
    login(c)
    publish_maps(modrinth)  # BlueMap has a build for 1.21.1 (the server's), Dynmap only for 1.20.1
    status, r, _ = c.get("/api/servers/alpha/webmap")
    assert status == 200 and r["minecraft"] == "1.21.1" and r["runs_mods"] is True
    assert r["available"] == {"bluemap": True, "dynmap": False}
    # The page isn't the only check: adding the other one is refused, and says why.
    status, r, _ = c.post("/api/servers/alpha/webmap/add", {"kind": "dynmap"})
    assert status == 400 and "Dynmap has no fabric build for Minecraft 1.21.1 yet" in r["error"]
    hub.get("alpha").m.reload_config()
    assert webmap.installed(hub.get("alpha").m.config.mods) is None  # (nothing was added)
    assert c.post("/api/servers/alpha/webmap/add", {"kind": "bluemap"})[0] == 200
    assert webmap.installed(hub.get("alpha").m.config.mods) == "bluemap"
    # With one added, there's nothing to offer (and nothing to ask Modrinth).
    r = c.get("/api/servers/alpha/webmap")[1]
    assert r["listed"] == "bluemap" and "available" not in r


def test_neither_map_for_a_version_nobody_supports_yet(hub_env, http, modrinth):
    from test_hub import login
    hub, c = hub_env
    login(c)
    publish_maps(modrinth, bluemap=("1.20.1",), dynmap=())  # (a Dynmap that has no build at all)
    r = c.get("/api/servers/alpha/webmap")[1]
    assert r["available"] == {"bluemap": False, "dynmap": False} and r["minecraft"] == "1.21.1"
    for kind in ("bluemap", "dynmap"):
        assert c.post("/api/servers/alpha/webmap/add", {"kind": kind})[0] == 400


def test_a_beta_only_map_is_not_offered_to_a_releases_only_server(hub_env, http, modrinth):
    from test_hub import login
    hub, c = hub_env
    login(c)
    modrinth.project("BLM", "bluemap", "BlueMap")
    modrinth.version("BLM", "1.0-beta", ["1.21.1"], version_type="beta")
    publish = lambda: c.get("/api/servers/alpha/webmap")[1]["available"]  # noqa: E731
    assert publish()["bluemap"] is False  # the server takes releases only
    from craft_conductor import config as configmod
    m = hub.get("alpha").m
    configmod.set_value(m.config.path, "updates", "mod_channel", '"beta"')
    m.reload_config()
    assert publish()["bluemap"] is True


def test_the_lookup_is_asked_once_per_map_and_remembered(hub_env, http, modrinth):
    from test_hub import login
    hub, c = hub_env
    login(c)
    publish_maps(modrinth)
    calls = version_lookups(http)
    for _ in range(4):  # the World page opened again and again
        assert c.get("/api/servers/alpha/webmap")[1]["available"]["bluemap"] is True
    assert c.post("/api/servers/alpha/webmap/add", {"kind": "dynmap"})[0] == 400  # (the refusal uses the same answer)
    assert sorted(calls) == [f"{API}/project/bluemap/version", f"{API}/project/dynmap/version"]


def test_the_map_check_expires_and_retries_failures_soon(http, modrinth, monkeypatch):
    publish_maps(modrinth)
    provider = ModrinthProvider(http)
    now = [1000.0]
    monkeypatch.setattr(webmap.time, "monotonic", lambda: now[0])
    calls = version_lookups(http)
    cache = webmap.Availability(ttl=900, retry=60)
    assert cache.check(provider, ("fabric",), "1.21.1") == {"bluemap": True, "dynmap": False}
    now[0] += 899
    cache.check(provider, ("fabric",), "1.21.1")
    assert len(calls) == 2  # still remembered
    assert cache.check(provider, ("fabric",), "1.20.1") == {"bluemap": False, "dynmap": True}  # another version: its own answer
    assert len(calls) == 4
    now[0] += 2
    cache.check(provider, ("fabric",), "1.21.1")
    assert len(calls) == 6  # expired: asked again
    # A lookup that failed is "can't tell" (not "no"), and tried again after a minute rather than on every view.
    http.json[f"{API}/project/bluemap/version"] = HttpError(f"{API}/project/bluemap/version", 503, "unavailable")
    assert cache.check(provider, ("fabric",), "1.19.4") == {"bluemap": None, "dynmap": False}
    asked = len(calls)
    now[0] += 30
    cache.check(provider, ("fabric",), "1.19.4")
    assert len(calls) == asked
    now[0] += 31
    cache.check(provider, ("fabric",), "1.19.4")
    assert len(calls) > asked
    # Vanilla runs nothing; no version is "can't tell"; neither asks Modrinth.
    asked = len(calls)
    assert cache.check(provider, (), "1.21.1") == {"bluemap": False, "dynmap": False}
    assert cache.check(provider, ("fabric",), "") == {"bluemap": None, "dynmap": None}
    assert len(calls) == asked


def test_a_map_that_could_not_be_checked_may_still_be_tried(hub_env, http, modrinth):
    """Modrinth being down isn't "no build": the buttons stay, and adding does its own check."""
    from test_hub import login
    hub, c = hub_env
    login(c)
    publish_maps(modrinth)
    http.json[f"{API}/project/bluemap/version"] = HttpError(f"{API}/project/bluemap/version", 503, "unavailable")
    r = c.get("/api/servers/alpha/webmap")[1]
    assert r["available"] == {"bluemap": None, "dynmap": False}


def test_a_map_without_a_build_for_the_next_minecraft_holds_that_update_back(hub_env, http, modrinth):
    """Show why: an added map counts like any other mod, installed or not yet."""
    from test_hub import login
    hub, c = hub_env
    login(c)
    publish_maps(modrinth, bluemap=("1.21.1",), dynmap=("1.21.1", "1.21.2"))
    alpha = hub.get("alpha")
    assert c.post("/api/servers/alpha/webmap/add", {"kind": "bluemap"})[0] == 200
    # Added but not installed yet: it's already on the list.
    r = c.get("/api/servers/alpha/updates/readiness?version=1.21.2")[1]
    assert [(m["name"], m["state"], m["installed"] if "installed" in m else True) for m in r["mods"]] == [("BlueMap", "red", False)]
    assert r["counts"]["red"] == 1
    # Installed: the same, the normal way.
    assert update(alpha.m).ok
    r = c.get("/api/servers/alpha/updates/readiness?version=1.21.2")[1]
    assert [(m["name"], m["state"]) for m in r["mods"] if m["name"] == "BlueMap"] == [("BlueMap", "red")]
    assert not any("installed" in m for m in r["mods"] if m["name"] == "BlueMap")
