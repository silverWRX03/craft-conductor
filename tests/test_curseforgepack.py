"""CurseForge modpacks (curseforgepack.py), and mods downloaded by hand on the manual downloads panel."""

import hashlib
import io
import json
import threading
import zipfile

import pytest

from craft_conductor import config as configmod, curseforgepack, setup as setupmod
from craft_conductor.modpack import ModpackError
from craft_conductor.mods import curseforge as cf

from test_web import login, running, wait_for  # noqa: F401  (running: the fixture)

PACK_URL = "https://edge.forgecdn.net/files/9000/1/big-pack-1.0.zip"
SERVER_URL = "https://edge.forgecdn.net/files/9000/2/big-pack-server-1.0.zip"


def _zip(files: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def _sha1(data: bytes) -> list[dict]:
    return [{"value": hashlib.sha1(data).hexdigest(), "algo": 1}]


@pytest.fixture(autouse=True)
def fresh_cache():
    from craft_conductor import handdownload
    for cache in (curseforgepack._previews, handdownload._resolved, handdownload._wanted):
        cache.clear()
    yield
    for cache in (curseforgepack._previews, handdownload._resolved, handdownload._wanted):
        cache.clear()


def serve_pack(http, *, server_pack=True, pack_download=True, overrides="overrides", manifest=None):
    """A CurseForge pack (project 500, file 9001): Sodium-like "Fancy Client" (players only), "Core
    Mod" (server too), a resource pack, and configs; with its server pack (file 9002) holding only Core Mod."""
    manifest = manifest or {
        "manifestType": "minecraftModpack", "manifestVersion": 1, "name": "Big Pack", "overrides": overrides,
        "minecraft": {"version": "1.20.1", "modLoaders": [{"id": "forge-47.2.0", "primary": True}]},
        "files": [{"projectID": 11, "fileID": 111, "required": True}, {"projectID": 22, "fileID": 222, "required": True},
                  {"projectID": 33, "fileID": 333, "required": True}]}
    pack = _zip({"manifest.json": json.dumps(manifest), f"{overrides}/config/core.toml": "speed = 2",
                 f"{overrides}/../../escape.txt": "no"})
    server = _zip({"Big Pack Server/mods/core-1.0.jar": b"core", "Big Pack Server/start.sh": "java -jar"})
    http.files[PACK_URL] = pack
    http.files[SERVER_URL] = server
    files = {
        9001: {"id": 9001, "modId": 500, "displayName": "Big Pack 1.0", "fileName": "big-pack-1.0.zip",
               "downloadUrl": PACK_URL if pack_download else None, "hashes": _sha1(pack),
               "serverPackFileId": 9002 if server_pack else None},
        111: {"id": 111, "modId": 11, "fileName": "core-1.0.jar", "displayName": "Core 1.0", "releaseType": 1,
              "downloadUrl": "https://edge.forgecdn.net/files/111/core-1.0.jar"},
        222: {"id": 222, "modId": 22, "fileName": "fancy-client-2.0.jar", "displayName": "Fancy 2.0", "releaseType": 2,
              "downloadUrl": None},
        333: {"id": 333, "modId": 33, "fileName": "shiny-textures.zip", "displayName": "Shiny", "releaseType": 1},
    }
    mods = {11: {"id": 11, "name": "Core Mod", "slug": "core-mod", "classId": 6},
            22: {"id": 22, "name": "Fancy Client", "slug": "fancy-client", "classId": 6, "allowModDistribution": False},
            33: {"id": 33, "name": "Shiny Textures", "slug": "shiny", "classId": 12}}
    http.posts[f"{cf.API}/mods/files"] = lambda body: {"data": [files[i] for i in body["fileIds"] if i in files]}
    http.posts[f"{cf.API}/mods"] = lambda body: {"data": [mods[i] for i in body["modIds"] if i in mods]}
    http.json[f"{cf.API}/mods/500"] = {"data": {"id": 500, "name": "Big Pack", "slug": "big-pack", "classId": 4471}}
    http.json[f"{cf.API}/mods/500/files/9002"] = {"data": {
        "id": 9002, "modId": 500, "fileName": "big-pack-server-1.0.zip", "isServerPack": True,
        "downloadUrl": SERVER_URL, "hashes": _sha1(server)}}


def test_a_curseforge_pack_sends_what_its_server_pack_leaves_out_to_friends(http):
    serve_pack(http)
    p = curseforgepack.preview(http, "key", "curseforge:9001")
    assert (p["minecraft"], p["loader"], p["server_pack"], p["other"]) == ("1.20.1", "forge", True, 1)
    by_name = {m["name"]: m for m in p["mods"]}
    assert set(by_name) == {"Core Mod", "Fancy Client"}  # (the resource pack isn't a mod)
    assert by_name["Core Mod"]["included_on_server"] and not by_name["Core Mod"]["for_friends"]
    assert by_name["Fancy Client"]["for_friends"] and not by_name["Fancy Client"]["included_on_server"]
    assert by_name["Fancy Client"]["manual"] and by_name["Fancy Client"]["url"] == f"{cf.WEBSITE}/fancy-client"
    assert (p["count"], p["client_only"]) == (1, 1)
    downloads = len(http.downloads)
    assert curseforgepack.preview(http, "key", "curseforge:9001") is p and len(http.downloads) == downloads  # (cached)


def test_without_a_server_pack_every_mod_goes_on_the_server(http):
    serve_pack(http, server_pack=False)
    p = curseforgepack.preview(http, "key", "curseforge:9001")
    assert not p["server_pack"] and all(m["included_on_server"] for m in p["mods"]) and p["count"] == 2


def test_a_curseforge_pack_is_applied(tmp_path, http):
    serve_pack(http, overrides="Overrides Here")
    root = tmp_path / "srv"
    setupmod.configure(root, setupmod.SetupSpec.from_dict({"loader": "fabric", "accept_eula": True}))
    r = curseforgepack.apply(root, "curseforge:9001", http, "key")
    assert r["friends"] == ["curseforge:22"] and r["mods"] == 1 and r["overrides"] == 1
    cfg = configmod.load(root)
    assert (cfg.server.loader, cfg.server.minecraft, cfg.updates.strategy) == ("forge", "1.20.1", "mods-only")
    assert [(m.source, m.id) for m in cfg.mods] == [("curseforge", "11")]
    assert (cfg.server.dir / "config" / "core.toml").read_text() == "speed = 2"
    assert not (tmp_path / "escape.txt").exists()

    again = tmp_path / "srv2"
    setupmod.configure(again, setupmod.SetupSpec.from_dict({"loader": "fabric", "accept_eula": True}))
    r = curseforgepack.apply(again, "curseforge:9001", http, "key", exclude=["mods/core-1.0.jar"])
    assert r["removed"] == 1 and configmod.load(again).mods == []


def test_a_pack_mod_with_only_early_builds_accepts_them(tmp_path, http):
    """RLCraft: many of its mods only have beta or alpha builds for 1.12.2. Each pack mod accepts
    the channel of its file in the pack, or setup says there's "no forge build" for it."""
    serve_pack(http, server_pack=False)
    root = tmp_path / "srv"
    setupmod.configure(root, setupmod.SetupSpec.from_dict({"loader": "fabric", "accept_eula": True}))
    curseforgepack.apply(root, "curseforge:9001", http, "key")
    assert {m.id: m.channel for m in configmod.load(root).mods} == {"11": None, "22": "beta"}


def serve_blocked_mod(http, data: bytes = b"fancy jar"):
    """Fancy Client (project 22) on CurseForge: one beta build, whose author keeps it to CurseForge."""
    http.json[f"{cf.API}/mods/22"] = {"data": {"id": 22, "name": "Fancy Client", "slug": "fancy-client"}}
    http.json[f"{cf.API}/mods/22/files"] = {"data": [{
        "id": 2222, "fileName": "fancy-client-2.1.jar", "displayName": "Fancy 2.1", "gameVersions": ["Forge", "1.20.1"],
        "releaseType": 2, "fileDate": "2026-01-01", "downloadUrl": None, "hashes": _sha1(data), "dependencies": []}]}


def test_mods_to_download_by_hand_are_found_before_the_server_is_made(http):
    from craft_conductor import handdownload
    serve_pack(http, server_pack=False)
    serve_blocked_mod(http)
    found = handdownload.needed(http, "key", "", "", [], "curseforge:9001")
    assert [(x["name"], x["filename"], x["url"]) for x in found] == [
        ("Fancy Client", "fancy-client-2.1.jar", f"{cf.WEBSITE}/fancy-client/files/2222")]  # (the exact file)
    assert handdownload.needed(http, "key", "", "", [], "curseforge:9001", ["mods/fancy-client-2.0.jar"]) == []  # (removed)
    # A mod picked by itself: found for its own channel (a release-only server wouldn't take it at all).
    assert handdownload.needed(http, "key", "forge", "1.20.1", [("22", None)]) == []
    assert [x["filename"] for x in handdownload.needed(http, "key", "forge", "1.20.1", [("22", "beta")])] == ["fancy-client-2.1.jar"]


def test_a_mod_downloaded_by_hand_is_loaded_before_the_server_is_made(hub_env, monkeypatch):
    """Choose a mod its author keeps to CurseForge: the page learns which file to download, takes
    only that file back, and creating the server puts it where the server looks for it."""
    from test_hub import login as hub_login
    hub, c = hub_env
    hub_login(c)
    monkeypatch.setenv("CRAFT_CONDUCTOR_CURSEFORGE_API_KEY", "test-key-not-real")
    serve_blocked_mod(hub.http, b"fancy jar")
    status, body, _ = c.post("/api/hub/manual/needed", {"loader": "forge", "minecraft": "1.20.1",
                                                         "mods": [{"id": "22", "channel": "beta"}]})
    assert status == 200 and [x["filename"] for x in body["mods"]] == ["fancy-client-2.1.jar"], body
    assert c.post("/api/hub/manual/needed", {"loader": "forge", "minecraft": "../x", "mods": [{"id": "22"}]})[0] == 400
    # Another file (or another version of it) isn't kept.
    status, body, _ = c.call("POST", "/api/hub/manual/stage?filename=fancy.jar", raw=b"something else")
    assert status == 400 and "isn't one of the mods" in body["error"]
    status, staged, _ = c.call("POST", "/api/hub/manual/stage?filename=Fancy%20(1).jar", raw=b"fancy jar")
    assert status == 200 and staged["filename"] == "fancy-client-2.1.jar", staged
    status, body, _ = c.post("/api/hub/create", {"loader": "fabric", "minecraft": "1.21.1", "motd": "Handmade",
                                                  "manual_files": [staged["id"]], "accept_eula": True})
    assert status == 200, body
    cfg = configmod.load(hub.home / "servers" / body["id"])
    assert (cfg.manual_dir / "fancy-client-2.1.jar").read_bytes() == b"fancy jar"
    assert not (hub.staging_dir / staged["id"]).exists()
    assert c.post("/api/hub/create", {"loader": "fabric", "manual_files": ["../x"], "accept_eula": True})[0] == 400


def test_a_pack_its_author_keeps_to_curseforge_isnt_downloaded(http):
    serve_pack(http, pack_download=False)
    with pytest.raises(ModpackError, match="doesn't allow other apps") as e:
        curseforgepack.preview(http, "key", "curseforge:9001")
    assert f"{cf.WEBSITE}/big-pack/files/9001" in str(e.value)
    assert PACK_URL not in http.downloads


def test_odd_curseforge_packs_are_refused(http):
    with pytest.raises(ModpackError, match="API key"):
        curseforgepack.preview(http, "", "curseforge:9001")
    with pytest.raises(ModpackError):
        curseforgepack.preview(http, "key", "curseforge:../1")
    serve_pack(http, manifest={"minecraft": {"version": "1.20.1", "modLoaders": []}, "files": [], "overrides": "../up"})
    with pytest.raises(ModpackError, match="overrides folder"):
        curseforgepack.preview(http, "key", "curseforge:9001")
    curseforgepack._previews.clear()
    serve_pack(http, manifest={"minecraft": {"version": "1.20.1", "modLoaders": [{"id": "rift-1"}]}, "files": []})
    with pytest.raises(ModpackError, match="mod loader"):
        curseforgepack.preview(http, "key", "curseforge:9001")
    http.json[f"{cf.API}/mods/500"] = {"data": {"id": 500, "name": "A Mod", "classId": 6}}
    with pytest.raises(ModpackError, match="isn't a modpack"):
        curseforgepack.preview(http, "key", "curseforge:9001")


def test_setup_and_friends_take_curseforge_entries():
    spec = setupmod.SetupSpec.from_dict({"loader": "forge", "minecraft": "1.20.1", "accept_eula": True,
                                         "modpack_version": "curseforge:9001", "client_mods": ["curseforge:22", "sodium"]})
    assert spec.modpack_version == "curseforge:9001" and spec.friends
    for bad in ("curseforge:x", "curseforge:1/2"):
        with pytest.raises(configmod.ConfigError):
            setupmod.SetupSpec.from_dict({"accept_eula": True, "modpack_version": bad})
    with pytest.raises(configmod.ConfigError):
        setupmod.SetupSpec.from_dict({"accept_eula": True, "client_mods": ["modrinth:../x"]})
    assert configmod._client({"mods": ["curseforge:22"]}).mods == ["curseforge:22"]


def _check(*manual: dict) -> dict:
    return {"manual": list(manual), "target": None, "checked_at": 0, "up_to_date": False, "latest": "1.21.1"}


def test_setup_waits_for_mods_downloaded_by_hand(running):
    """Create my server with a mod only downloadable by hand: setup waits (the page's panel shows
    what), carries on once the file is dropped, and stops when asked."""
    d, c, cfg = running
    login(c)
    jar = b"blocked jar"
    d.last_check = _check({"name": "Blocked", "filename": "blocked-1.0.jar", "url": "https://www.curseforge.com/x",
                           "sha1": hashlib.sha1(jar).hexdigest()})
    done = []
    t = threading.Thread(target=lambda: done.append(d.wait_for_manual_downloads()), daemon=True)
    t.start()
    wait_for(lambda: c.get("/api/status")[1]["manual_wait"])
    assert c.get("/api/status")[1]["manual_wait"][0]["filename"] == "blocked-1.0.jar"
    status, body, _ = c.call("POST", "/api/manual/upload?filename=whatever.jar", raw=jar,
                             headers={"Content-Type": "application/octet-stream"})
    assert status == 200 and body["left"] == 0
    t.join(5)
    assert done == [None] and c.get("/api/status")[1]["manual_wait"] is None

    d.last_check = _check({"name": "Other", "filename": "other.jar", "url": "u", "sha1": "0" * 40})
    errors = []
    def wait():
        try:
            d.wait_for_manual_downloads()
        except RuntimeError as e:
            errors.append(str(e))
    t = threading.Thread(target=wait, daemon=True)
    t.start()
    wait_for(lambda: d.waiting_for_manual)
    assert c.post("/api/manual/stop", {})[0] == 200
    t.join(5)
    assert errors and "setup stopped" in errors[0]
    assert c.post("/api/manual/stop", {})[0] == 400  # (nothing waiting)

    # Copied into the manual-downloads folder by hand works too.
    d.last_check = _check({"name": "Copied", "filename": "copied.jar", "url": "u", "sha1": hashlib.sha1(b"c").hexdigest()})
    cfg.manual_dir.mkdir(parents=True, exist_ok=True)
    (cfg.manual_dir / "copied.jar").write_bytes(b"c")
    d.wait_for_manual_downloads()
