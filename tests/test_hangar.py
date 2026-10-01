"""Paper plugins from Hangar (PaperMC's plugin site), and plugins added by hand."""

import pytest

from craft_conductor.config import ModSpec
from craft_conductor.mods import hangar
from craft_conductor.mods.base import Unavailable

from test_hub import login

API = hangar.API


def fake_hangar(http):
    http.json[f"{API}/projects/ViaVersion"] = {"name": "ViaVersion", "namespace": {"owner": "ViaVersion", "slug": "ViaVersion"}}
    http.json[f"{API}/projects/ViaVersion/versions"] = {"result": [
        {"id": 3, "name": "6.0-SNAPSHOT", "channel": {"name": "Snapshot"},
         "downloads": {"PAPER": {"fileInfo": {"name": "ViaVersion-6.0.jar", "sha256Hash": "c" * 64}, "downloadUrl": "https://hangarcdn.papermc.io/v6.jar"}},
         "platformDependencies": {"PAPER": ["1.21-1.21.4"]}},
        {"id": 2, "name": "5.2.1", "channel": {"name": "Release"},
         "downloads": {"PAPER": {"fileInfo": {"name": "ViaVersion-5.2.1.jar", "sha256Hash": "b" * 64}, "downloadUrl": "https://hangarcdn.papermc.io/v5.jar"}},
         "pluginDependencies": {"PAPER": [{"name": "ViaBackwards", "required": False}, {"name": "ProtocolLib", "required": True}]},
         "platformDependencies": {"PAPER": ["1.8-1.21.4"]}},
        {"id": 1, "name": "4.0", "channel": {"name": "Release"},
         "downloads": {"PAPER": {"fileInfo": {"name": "ViaVersion-4.0.jar"}, "externalUrl": "https://elsewhere.example/v4.jar"}},
         "platformDependencies": {"PAPER": ["1.7"]}},
    ]}


def test_versions_and_ranges():
    assert hangar.supports("1.21.1", "1.21-1.21.4") and hangar.supports("1.21.4", "1.20-1.21")
    assert not hangar.supports("1.21.5", "1.21-1.21.4") and not hangar.supports("1.19.4", "1.20-1.21")
    assert hangar.supports("1.21.1", "1.21") and not hangar.supports("1.20.1", "1.21")
    assert "1.21.1" in hangar.VersionSet({"1.8-1.21.4"}) and "1.22" not in hangar.VersionSet({"1.8-1.21.4"})


def test_resolve(http):
    fake_hangar(http)
    p = hangar.HangarProvider(http)
    f = p.resolve(ModSpec("hangar", "ViaVersion"), "1.21.1", ("paper",), "release")
    assert (f.version_number, f.sha256, f.url) == ("5.2.1", "b" * 64, "https://hangarcdn.papermc.io/v5.jar")
    assert f.dependencies == ["ProtocolLib"] and not f.manual  # only required ones, from Hangar
    assert p.resolve(ModSpec("hangar", "ViaVersion"), "1.21.1", ("paper",), "alpha").version_number == "6.0-SNAPSHOT"
    old = p.resolve(ModSpec("hangar", "ViaVersion"), "1.7", ("paper",), "release")
    assert old.manual  # hosted elsewhere: you download it yourself
    with pytest.raises(Unavailable):
        p.resolve(ModSpec("hangar", "ViaVersion"), "26.1", ("paper",), "release")
    assert "1.21.4" in p.supported_versions(ModSpec("hangar", "ViaVersion"), ("paper",), "release")


def test_search_and_the_browser(http):
    from craft_conductor.browse import Browser, BrowseError
    http.json[f"{API}/projects"] = {"pagination": {"count": 1}, "result": [
        {"name": "ViaVersion", "namespace": {"owner": "ViaVersion", "slug": "ViaVersion"}, "description": "Newer clients on older servers",
         "stats": {"downloads": 1000, "stars": 50}, "avatarUrl": "https://hangarcdn.papermc.io/avatar.png", "category": "admin_tools"}]}
    r = Browser(http).search(source="hangar", query="via", loader="paper", version="1.21.1")
    assert r["results"][0]["id"] == "ViaVersion" and r["results"][0]["url"].endswith("/ViaVersion/ViaVersion")
    with pytest.raises(BrowseError):
        Browser(http).search(source="hangar", loader="fabric")  # mods don't come from Hangar
    assert {c["id"] for c in Browser(http).categories("hangar")} >= {"chat", "economy"}


def test_plugins_added_by_hand(hub_env):
    hub, c = hub_env
    login(c)
    d = hub.get("alpha")
    folder = d.m.mods_dir
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "MyPlugin.jar").write_bytes(b"x")
    r = c.get("/api/servers/alpha/mods")[1]
    assert "MyPlugin.jar" in r["unmanaged"] and r["disabled"] == []
    assert c.post("/api/servers/alpha/mods/jar", {"name": "MyPlugin.jar", "action": "disable"})[0] == 200
    assert (folder / "MyPlugin.jar.disabled").exists() and c.get("/api/servers/alpha/mods")[1]["disabled"] == ["MyPlugin.jar"]
    assert c.post("/api/servers/alpha/mods/jar", {"name": "MyPlugin.jar", "action": "enable"})[0] == 200
    for bad in ("../../etc/passwd", "nothere.jar", ""):
        assert c.post("/api/servers/alpha/mods/jar", {"name": bad, "action": "remove"})[0] == 400
    assert c.post("/api/servers/alpha/mods/jar", {"name": "MyPlugin.jar", "action": "remove"})[0] == 200
    assert not (folder / "MyPlugin.jar").exists()
