"""Make a modpack from a server's mods (roadmap 53): a Modrinth .mrpack or a CurseForge .zip, with
only links to the mod sites' own downloads, and every mod that can't go in named with why."""

import hashlib
import io
import json
import re
import zipfile

import pytest

from craft_conductor import config as configmod, makepack
from craft_conductor.config import ModSpec
from craft_conductor.mods.base import ModFile
from craft_conductor.mods.modrinth import API as MODRINTH

from test_manager import manager, update

CF_URL = "https://edge.forgecdn.net/files/5555/123/cfmod-1.0.jar"


def versions_answer(http):
    """Modrinth's GET /versions?ids=[...]: each build with both hashes and its size."""
    def answer(params):
        out = []
        for vid in json.loads(params["ids"]):
            v = http.json.get(f"{MODRINTH}/version/{vid}")
            if v is None:
                continue
            v = json.loads(json.dumps(v))
            for f in v["files"]:
                data = http.files[f["url"]]
                f["hashes"] = {"sha1": hashlib.sha1(data).hexdigest(), "sha512": hashlib.sha512(data).hexdigest()}
                f["size"] = len(data)
            out.append(v)
        return out
    http.json[f"{MODRINTH}/versions"] = answer


@pytest.fixture
def server(make_config, http, modrinth):
    modrinth.project("BOTHMODA", "bothmod", "Both Mod")
    modrinth.version("BOTHMODA", "1.0", ["1.21.1"])
    modrinth.project("SRVMODAA", "srvmod", "Server Tool", client_side="unsupported")
    modrinth.version("SRVMODAA", "1.0", ["1.21.1"])
    modrinth.project("OPTMODAA", "optmod", "Optional Mod")
    modrinth.version("OPTMODAA", "1.0", ["1.21.1"])
    modrinth.project("CLIMODAA", "climod", "Minimap", server_side="unsupported")
    modrinth.version("CLIMODAA", "1.0", ["1.21.1"])
    versions_answer(http)
    cfg = make_config([ModSpec("modrinth", "bothmod"), ModSpec("modrinth", "srvmod"),
                       ModSpec("modrinth", "optmod", required=False)])
    configmod.set_value(cfg.path, "client", "mods", '["climod"]')
    m = manager(configmod.load(cfg.root), http, ["1.21.1"])
    assert update(m).ok
    http.files[CF_URL] = b"cf mod"
    m.lock.mods.append(ModFile(key="curseforge:5555", source="curseforge", project_id="5555", name="<b>CF Mod</b>",
                               version_id="123", version_number="1.0", filename="cfmod-1.0.jar", url=CF_URL,
                               sha1=hashlib.sha1(b"cf mod").hexdigest()))
    m.lock.mods.append(ModFile(key="modrinth:DPACKAAA", source="modrinth", project_id="DPACKAAA", name="Terrain Pack",
                               version_id="DP1", version_number="1", filename="terrain.zip", url="https://cdn.modrinth.com/x",
                               datapack=True))
    (m.mods_dir / "mine.jar").write_bytes(b"my own")
    return m


def unzip(data: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(data))


def test_an_mrpack_links_modrinth_files_only(server):
    m = server
    filename, data = makepack.build(m, "mrpack")
    z = unzip(data)
    assert z.namelist() == ["modrinth.index.json"]
    index = json.loads(z.read("modrinth.index.json"))
    assert index["formatVersion"] == 1 and index["game"] == "minecraft"
    assert index["dependencies"] == {"minecraft": "1.21.1", "fabric-loader": m.lock.loader_version}
    env = {f["path"].split("/")[1].split("-")[0]: f["env"] for f in index["files"]}
    assert env["BOTHMODA"] == {"client": "required", "server": "required"}
    assert env["SRVMODAA"] == {"client": "unsupported", "server": "required"}
    assert env["OPTMODAA"]["server"] == "optional"
    assert env["CLIMODAA"] == {"client": "required", "server": "unsupported"}
    for f in index["files"]:
        assert f["downloads"][0].startswith("https://cdn.modrinth.com/")
        assert f["fileSize"] > 0 and len(f["hashes"]["sha1"]) == 40 and len(f["hashes"]["sha512"]) == 128
    left = {x["name"]: x["why"] for x in makepack.contents(m, "mrpack")["left_out"]}
    assert left == {"<b>CF Mod</b>": "only on CurseForge: a Modrinth pack can't link to it",
                    "mine.jar": "added by hand: not on a mod site",
                    "Terrain Pack": "a datapack for the world, not a mod"}
    assert all(name in index["summary"] for name in left)


def test_a_curseforge_pack_lists_project_and_file_ids(server):
    m = server
    filename, data = makepack.build(m, "curseforge")
    z = unzip(data)
    assert set(z.namelist()) == {"manifest.json", "modlist.html"}
    manifest = json.loads(z.read("manifest.json"))
    assert manifest["minecraft"] == {"version": "1.21.1", "modLoaders": [{"id": f"fabric-{m.lock.loader_version}", "primary": True}]}
    assert manifest["manifestType"] == "minecraftModpack" and manifest["manifestVersion"] == 1
    assert manifest["files"] == [{"projectID": 5555, "fileID": 123, "required": True}]
    assert manifest["overrides"] == "overrides"
    left = {x["name"]: x["why"] for x in makepack.contents(m, "curseforge")["left_out"]}
    assert left["Both Mod"] == left["Minimap"] == "only on Modrinth: a CurseForge pack can't link to it"
    html = z.read("modlist.html").decode()
    assert "Not included" in html and "Minimap" in html and "&lt;b&gt;CF Mod&lt;/b&gt;" in html and "<b>CF" not in html


def test_a_build_modrinth_no_longer_has_is_named(server, http):
    del http.json[f"{MODRINTH}/version/OPTMODAA-1.0"]
    left = {x["name"]: x["why"] for x in makepack.contents(server, "mrpack")["left_out"]}
    assert left["Optional Mod"] == "Modrinth no longer has this file"


def test_the_file_name_is_safe(server):
    (server.server_dir / "server.properties").write_text('motd=Bob\'s "Pack"/../x\n')
    filename, _ = makepack.build(server, "mrpack")
    assert re.fullmatch(r"[A-Za-z0-9._ -]+-\d{4}-\d{2}-\d{2}\.mrpack", filename), filename
    assert ".." not in filename.split("-")[0] or "/" not in filename


def test_unknown_formats_and_servers_without_mods(server):
    with pytest.raises(ValueError):
        makepack.contents(server, "zip")
    server.lock.loader = "paper"   # (plugins: players join with plain Minecraft)
    with pytest.raises(ValueError):
        makepack.contents(server, "mrpack")


def test_the_routes_and_permission(hub_env, http):
    from test_hub import login
    hub, c = hub_env
    login(c)
    versions_answer(http)
    code, r, _ = c.get("/api/servers/alpha/modpack/make?format=mrpack")
    assert code == 200 and r["filename"].endswith(".mrpack") and isinstance(r["left_out"], list)
    assert c.get("/api/servers/alpha/modpack/make?format=zip")[0] == 400
    code, body, headers = c.get("/api/servers/alpha/modpack/make/download?format=curseforge")
    assert code == 200 and "attachment" in headers.get("Content-Disposition", "")
    from craft_conductor import access
    assert access.SERVER_ROUTES[("GET", "/api/modpack/make")] == "mods.view"
    assert access.SERVER_ROUTES[("GET", "/api/modpack/make/download")] == "mods.view"
