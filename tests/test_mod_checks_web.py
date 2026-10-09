"""Change version and the file check on the pages: a server's mods, its friends' download (paused
while players' Minecraft wouldn't start), the setup page (Create my server waits) and single-player
games (Install waits)."""

import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from craft_conductor import config as configmod, join, setup as setupmod
from craft_conductor.http import HttpClient
from craft_conductor.hub import Hub

from test_friends import free_port
from test_hub import login
from test_manager import manager, update
from test_mod_versions import shaders
from test_web import Client, wait_for


def finished(c, started: dict) -> dict:
    """A background check's result (GET /api/hub/mods/check?id=...)."""
    assert "id" in started, started
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        j = c.get(f"/api/hub/mods/check?id={started['id']}")[1]
        if j["state"] != "running":
            assert j["state"] == "done", j
            return j["result"]
        time.sleep(0.05)
    raise AssertionError("the check didn't finish")


def test_change_version_on_a_servers_mods(hub_env, modrinth):
    hub, c = hub_env
    login(c)
    shaders(modrinth)
    code, r, _ = c.get("/api/servers/alpha/mods/versions?key=modrinth:IRIS")
    assert code == 200 and r["key"] == "modrinth:IRIS" and r["held"] is None
    assert [(v["number"], v["here"]) for v in r["versions"]] == [("1.11.4", True), ("1.11.3", True), ("1.10.9", True)]
    assert c.get("/api/servers/alpha/mods/versions?key=iris")[1]["key"] == "modrinth:IRIS"   # (a slug works too)
    assert c.post("/api/servers/alpha/mods/pin", {"key": "modrinth:IRIS", "version": "IRIS-1.10.9"})[0] == 200
    m = hub.get("alpha").m
    assert m.config.pins["modrinth:IRIS"] == configmod.Pin("IRIS-1.10.9", "1.21.1")
    assert c.get("/api/servers/alpha/mods/versions?key=modrinth:IRIS")[1]["held"] == "IRIS-1.10.9"
    for bad in ({"key": "modrinth:../x", "version": "a"}, {"key": "modrinth:IRIS", "version": "../../x"}, {"key": "x", "version": "a"}):
        assert c.post("/api/servers/alpha/mods/pin", bad)[0] == 400
    assert c.get("/api/servers/alpha/mods/versions?key=modrinth:..%2F..")[0] == 400
    assert c.post("/api/servers/alpha/mods/pin", {"key": "modrinth:IRIS", "version": None})[0] == 200
    assert "modrinth:IRIS" not in hub.get("alpha").m.config.pins


def test_the_servers_check_runs_in_the_background(hub_env, modrinth):
    hub, c = hub_env
    login(c)
    shaders(modrinth)
    c.post("/api/servers/alpha/client", {"enabled": True, "mods": ["iris"]})
    result = finished(c, c.post("/api/servers/alpha/mods/filecheck", {})[1])
    [problem] = result["problems"]
    assert problem["side"] == "client" and problem["key"] == "modrinth:IRIS" and problem["needs_key"] == "modrinth:SOD"
    assert [f["text"] for f in problem["fixes"]] == ["Use Iris 1.10.9"]
    # No invite goes out while it wouldn't start ...
    assert c.get("/api/servers/alpha/client")[1]["pack"]["problems"]
    code, r, _ = c.post("/api/servers/alpha/client/new-link", {})
    assert code == 409 and "Manage Friends Mods" in r["error"]
    # ... and after the fix, it does.
    c.post("/api/servers/alpha/mods/pin", {"key": "modrinth:IRIS", "version": "IRIS-1.10.9"})
    assert finished(c, c.post("/api/servers/alpha/mods/filecheck", {})[1])["problems"] == []
    d = c.get("/api/servers/alpha/client")[1]
    assert d["pack"]["problems"] == [] and d["held"]["modrinth:IRIS"] == {"version": "IRIS-1.10.9", "number": "1.10.9"}
    assert c.post("/api/servers/alpha/client/new-link", {})[0] == 200


def test_invites_already_sent_are_paused_until_the_mods_are_fixed(tmp_path, http, modrinth, fake_template):
    modrinth.project("FAPI", "fabric-api", "Fabric API")
    modrinth.version("FAPI", "0.1", ["1.21.1"])
    shaders(modrinth)
    home = tmp_path / "home"
    root = home / "servers" / "survival"
    setupmod.configure(root, setupmod.SetupSpec.from_dict({"loader": "fabric", "minecraft": "1.21.1", "client_mods": ["iris"],
                                                           "motd": "Weekend", "accept_eula": True, "port": 25571}))
    assert update(manager(configmod.load(root), http, ["1.21.1"])).ok
    hub = Hub(home, make_manager=lambda cfg: manager(cfg, http, ["1.21.1"]), http=http, tick=0.1)
    hub.web.port = 0
    share_port = free_port()
    hub._save_hub_file({"share": {"port": share_port, "address": ""}})
    t = threading.Thread(target=hub.run, daemon=True)
    t.start()
    try:
        wait_for(lambda: hub.ui is not None and hub.share is not None and hub.share.httpd is not None)
        c = Client(hub.ui.url.rstrip("/"))
        login(c)
        inv = join.Invite("127.0.0.1", share_port, configmod.load(root).client.token, hub.share.fingerprint)
        pinned = HttpClient(cache_ttl=0, retries=1)
        pinned.pin(inv.netloc, inv.fp)
        joiner = join.Joiner(inv, mc_dir=tmp_path / ".minecraft", http=pinned)
        with pytest.raises(join.JoinError, match="fixing its mods"):
            joiner.fetch_pack()
        c.post("/api/servers/survival/mods/pin", {"key": "modrinth:IRIS", "version": "IRIS-1.10.9"})
        assert {m["name"]: m["version"] for m in joiner.fetch_pack()["mods"]}["Iris"] == "1.10.9"   # (the same invite works again)
    finally:
        hub.stop_requested.set()
        t.join(30)


def test_create_my_server_waits_until_the_mods_check_out(hub_env, modrinth):
    hub, c = hub_env
    login(c)
    shaders(modrinth)
    body = {"loader": "fabric", "minecraft": "1.21.1", "motd": "Shaders", "accept_eula": True, "client_mods": ["iris"],
            "mods": ["goodmod"]}
    result = finished(c, c.post("/api/hub/mods/filecheck", body)[1])
    [problem] = result["problems"]
    assert problem["side"] == "client" and problem["fixes"][0]["version_id"] == "IRIS-1.10.9"
    code, r, _ = c.post("/api/hub/create", body)
    assert code == 409 and "Manage Mods" in r["error"]
    assert c.get("/api/hub/mods/versions?key=iris&loader=fabric&minecraft=1.21.1")[1]["key"] == "modrinth:IRIS"
    body["pins"] = {"modrinth:IRIS": {"version": "IRIS-1.10.9", "minecraft": "1.21.1"}}
    assert finished(c, c.post("/api/hub/mods/filecheck", body)[1])["problems"] == []
    code, r, _ = c.post("/api/hub/create", body)
    assert code == 200

    def held():  # (the new server's setup rewrites its settings in the background: read them once they're whole)
        try:
            return configmod.load(hub.home / "servers" / r["id"]).pins
        except configmod.ConfigError:
            return None
    wait_for(lambda: held() == {"modrinth:IRIS": configmod.Pin("IRIS-1.10.9", "1.21.1")})
    assert c.post("/api/hub/mods/filecheck", {**body, "pins": {"modrinth:IRIS": "../x"}})[0] == 400


def test_a_single_player_game_isnt_installed_while_it_wouldnt_start(hub_env, http, modrinth):
    from test_singleplayer import mojang
    hub, c = hub_env
    login(c)
    mojang(http, ["1.21.1"])
    http.json["https://meta.fabricmc.net/v2/versions/loader/1.21.1"] = [{"loader": {"version": "0.16.5", "stable": True}}]
    shaders(modrinth)
    game = c.post("/api/hub/singleplayer", {"name": "Shaders", "loader": "fabric", "minecraft": "1.21.1", "mods": ["iris"]})[1]
    r = c.post("/api/hub/singleplayer/check", {"id": game["id"]})[1]
    assert [p["needs"] for p in r["problems"]] == ["sodium"]
    code, r, _ = c.post("/api/hub/singleplayer/install", {"id": game["id"]})
    assert code == 409 and "Manage Mods" in r["error"]
    recipe = {"name": "Shaders", "loader": "fabric", "minecraft": "1.21.1", "mods": ["iris"]}
    [problem] = finished(c, c.post("/api/hub/singleplayer/filecheck", recipe)[1])["problems"]
    assert problem["fixes"][0]["text"] == "Use Iris 1.10.9"
    assert c.get("/api/hub/singleplayer/versions?key=modrinth:IRIS&loader=fabric&minecraft=1.21.1")[1]["versions"]
    pins = {"modrinth:IRIS": {"version": "IRIS-1.10.9", "minecraft": "1.21.1"}}
    assert finished(c, c.post("/api/hub/singleplayer/filecheck", {**recipe, "pins": pins})[1])["problems"] == []
    saved = c.post("/api/hub/singleplayer/edit", {"id": game["id"], "pins": pins})[1]
    assert saved["pins"] == pins
    assert c.post("/api/hub/singleplayer/check", {"id": game["id"]})[1]["problems"] == []


@pytest.mark.skipif(not os.environ.get("CRAFT_UI_NODE"), reason="optional browser verification")
def test_change_version_and_the_check_in_a_real_browser(hub_env, modrinth):
    hub, c = hub_env
    login(c)
    shaders(modrinth)
    modrinth.version("SOD", "0.9.0-beta", ["1.21.2"], version_type="beta")   # (made for another Minecraft)
    assert c.post("/api/servers/alpha/client", {"enabled": True, "mods": ["iris"]})[0] == 200
    from craft_conductor.config import ModSpec
    from test_modcheck import TERRALITH
    from test_singleplayer import mojang
    modrinth.project("TER", "terralith", "Terralith")
    modrinth.version("TER", "2.6.2", ["1.21.1"], content=TERRALITH)   # (its file needs Lithostitched; its site doesn't say)
    m = hub.get("alpha").m
    configmod.append_mod(m.config.path, ModSpec("modrinth", "terralith"))
    m.reload_config()
    mojang(hub.http, ["1.21.1"])   # (for single-player games)
    hub.http.json["https://meta.fabricmc.net/v2/versions/loader/1.21.1"] = [{"loader": {"version": "0.16.5", "stable": True}}]
    result = subprocess.run([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_mod_versions.cjs")), c.base],
                            capture_output=True, text=True, timeout=240)
    assert result.returncode == 0, result.stdout + result.stderr
