"""Modded single-player games: a recipe, the newest versions that work together, the launchers."""

import json

import pytest

from craft_conductor import join, launchers, singleplayer
from craft_conductor.minecraft import MANIFEST_URL

from test_hub import login


def mojang(http, releases):
    http.json[MANIFEST_URL] = {"latest": {"release": releases[-1]}, "versions": [
        {"id": v, "type": "release", "releaseTime": f"2024-0{i + 1}-01T00:00:00+00:00", "url": f"https://x/{v}.json"}
        for i, v in enumerate(releases)]}
    for v in releases:
        http.json[f"https://x/{v}.json"] = {"javaVersion": {"majorVersion": 21}}


def test_recipes_are_checked():
    with pytest.raises(singleplayer.SingleplayerError):
        singleplayer.check_recipe("", "fabric", "latest", [], 4)
    with pytest.raises(singleplayer.SingleplayerError):
        singleplayer.check_recipe("x", "paper", "latest", [], 4)
    with pytest.raises(singleplayer.SingleplayerError):
        singleplayer.check_recipe("x", "fabric", "latest", ["../evil"], 4)
    r = singleplayer.check_recipe(" Cozy ", "fabric", "1.21.1", ["modrinth:sodium", "sodium", "iris"], "6")
    assert r == {"name": "Cozy", "loader": "fabric", "minecraft": "1.21.1", "mods": ["sodium", "iris"], "memory_gb": 6}


def test_the_newest_minecraft_every_mod_supports(hub_env, http, modrinth):
    hub, c = hub_env
    login(c)
    mojang(http, ["1.21.1", "1.21.4"])
    http.json["https://meta.fabricmc.net/v2/versions/loader/1.21.4"] = [{"loader": {"version": "0.16.9", "stable": True}}]
    http.json["https://meta.fabricmc.net/v2/versions/loader/1.21.1"] = [{"loader": {"version": "0.16.5", "stable": True}}]
    modrinth.project("SOD", "sodium", "Sodium", server_side="unsupported")
    modrinth.version("SOD", "0.6", ["1.21.1", "1.21.4"])
    modrinth.project("MAP", "minimap", "Minimap", server_side="unsupported")
    modrinth.version("MAP", "1.0", ["1.21.1"], deps=["SOD"])
    status, g, _ = c.post("/api/hub/singleplayer", {"name": "Cozy", "loader": "fabric", "minecraft": "latest",
                                                     "mods": ["sodium", "minimap"], "memory_gb": 6})
    assert status == 200, g
    assert c.post("/api/hub/singleplayer", {"name": "cozy", "loader": "fabric", "mods": []})[0] == 400  # same name
    assert c.post("/api/hub/singleplayer", {"name": "X", "loader": "fabric", "mods": ["a b"]})[0] == 400
    # The minimap has no 1.21.4 build: the game stays on 1.21.1, with both mods.
    r = c.post("/api/hub/singleplayer/check", {"id": g["id"]})[1]
    assert r["minecraft"] == "1.21.1" and r["loader_version"] == "0.16.5", r
    assert r["changes"] == ["Minecraft 1.21.1 with fabric 0.16.5 and 2 mod(s)"] and not r["skipped"]
    pack = singleplayer.resolve(hub, singleplayer.load(hub, g["id"]))
    assert pack["address"] == "" and join.validate_pack(pack) is pack  # a pack the launchers accept
    # Installed; then the minimap catches up: Minecraft moves up too.
    singleplayer.save(hub, {**singleplayer.load(hub, g["id"]), "installed": singleplayer.summary(pack), "launchers": ["prism"]})
    modrinth.version("MAP", "1.1", ["1.21.4"], deps=["SOD"])
    r = c.post("/api/hub/singleplayer/check", {"id": g["id"]})[1]
    assert r["minecraft"] == "1.21.4"
    assert r["changes"][0] == "Minecraft 1.21.1 → 1.21.4" and any(x.startswith("~ Minimap") for x in r["changes"])
    # A fixed version stays put.
    assert c.post("/api/hub/singleplayer/edit", {"id": g["id"], "minecraft": "1.21.1"})[0] == 200
    assert c.post("/api/hub/singleplayer/check", {"id": g["id"]})[1]["changes"] == []
    assert c.post("/api/hub/singleplayer/edit", {"id": g["id"], "loader": "forge"})[0] == 400  # (installed)
    games = c.get("/api/hub/singleplayer")[1]["games"]
    assert [x["name"] for x in games] == ["Cozy"] and games[0]["launchers"] == ["prism"]
    assert c.post("/api/hub/singleplayer/delete", {"id": g["id"]})[0] == 200
    assert c.get("/api/hub/singleplayer")[1]["games"] == []
    assert c.post("/api/hub/singleplayer/delete", {"id": "../../x"})[0] == 404


def test_launchers_set_up_a_game_without_a_server(tmp_path, http):
    http.files["https://cdn.modrinth.com/data/SOD/sodium.jar"] = b"jar"
    import hashlib
    pack = {"format": 1, "name": "Cozy", "minecraft": "1.21.1", "loader": "fabric", "loader_version": "0.16.5",
            "address": "", "singleplayer": True, "memory_gb": 6, "manual": [],
            "mods": [{"name": "Sodium", "filename": "sodium.jar", "url": "https://cdn.modrinth.com/data/SOD/sodium.jar",
                      "sha1": hashlib.sha1(b"jar").hexdigest(), "sha512": None, "project": "modrinth:SOD", "side": "client"}]}
    join.validate_pack(pack)
    j = join.Joiner(join.Invite("localhost", 1, "local-" + "0" * 16), mc_dir=tmp_path / "mc", http=http, say=lambda s: None)
    r = launchers.install_prism(j, pack, "cozy", tmp_path / "prism")
    inst = tmp_path / "prism" / "instances" / "craft-conductor-cozy"
    cfg = (inst / "instance.cfg").read_text()
    assert "JoinServerOnLaunch=false" in cfg and (inst / ".minecraft" / "mods" / "sodium.jar").read_bytes() == b"jar"
    assert not (inst / ".minecraft" / "servers.dat").exists() and "joins the server" not in r["message"]
    assert all("--server" not in cmd for cmd in launchers.prism_command("craft-conductor-cozy", ""))
    import zipfile
    mr = launchers.build_mrpack(j, pack, tmp_path)
    with zipfile.ZipFile(mr) as z:
        assert "overrides/servers.dat" not in z.namelist()
        assert json.loads(z.read("modrinth.index.json"))["summary"] == "Made by Craft Conductor"
    # A server pack still needs its address.
    with pytest.raises(join.JoinError):
        join.validate_pack({**pack, "singleplayer": False})
