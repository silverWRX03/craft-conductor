"""Regression tests for the compact mod-management UI's backend data.

The UI must reuse Craft Conductor's existing dependency/modpack resolution. These tests keep
the display APIs and the modpack per-file exclusion behavior tied to those existing sources
of truth.
"""

import json
import zipfile

import pytest

from craft_conductor import config as configmod, modpack, setup as setupmod
from craft_conductor.config import ConfigError
from craft_conductor.mods.modrinth import API as MODRINTH


def _pack(path):
    index = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": "test",
        "name": "Test Pack",
        "summary": "A test pack",
        "files": [
            {
                "path": "mods/one.jar",
                "hashes": {"sha1": "1" * 40},
                "downloads": ["https://cdn.modrinth.com/data/PROJ0001/versions/VERS0001/one.jar"],
                "env": {"server": "required", "client": "required"},
            },
            {
                "path": "mods/two.jar",
                "hashes": {"sha1": "2" * 40},
                "downloads": ["https://cdn.modrinth.com/data/PROJ0002/versions/VERS0002/two.jar"],
                "env": {"server": "required", "client": "required"},
            },
            {
                "path": "mods/client.jar",
                "hashes": {"sha1": "3" * 40},
                "downloads": ["https://cdn.modrinth.com/data/CLNT0001/versions/VERS0003/client.jar"],
                "env": {"server": "unsupported", "client": "required"},
            },
        ],
        "dependencies": {"minecraft": "1.21.1", "fabric-loader": "0.16.5"},
    }
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("modrinth.index.json", json.dumps(index))


def _metadata(http):
    http.json[f"{MODRINTH}/projects"] = [
        {"id": "PROJ0001", "slug": "one", "title": "One Mod"},
        {"id": "PROJ0002", "slug": "two", "title": "Two Mod"},
        {"id": "CLNT0001", "slug": "client", "title": "Client Mod"},
    ]
    http.json[f"{MODRINTH}/versions"] = [
        {"id": "VERS0001", "version_number": "1.0", "version_type": "release",
         "game_versions": ["1.21.1"], "loaders": ["fabric"]},
        {"id": "VERS0002", "version_number": "2.0-beta", "version_type": "beta",
         "game_versions": ["1.21.1"], "loaders": ["fabric"]},
        {"id": "VERS0003", "version_number": "3.0", "version_type": "release",
         "game_versions": ["1.21.1"], "loaders": ["fabric"]},
    ]


def test_modpack_preview_lists_every_mod_but_counts_server_mods(tmp_path, http):
    pack = tmp_path / "test.mrpack"
    _pack(pack)
    _metadata(http)

    preview = modpack.preview_file(pack, http, name="Test Pack")

    assert preview["name"] == "Test Pack"
    assert preview["minecraft"] == "1.21.1"
    assert preview["loader"] == "fabric"
    assert preview["count"] == 2
    assert preview["client_only"] == 1
    assert [m["name"] for m in preview["mods"]] == ["One Mod", "Two Mod", "Client Mod"]
    assert preview["mods"][1]["channel"] == "beta"
    assert preview["mods"][2]["included_on_server"] is False


def test_modpack_can_exclude_one_mod_without_removing_the_pack(tmp_path, http):
    pack = tmp_path / "test.mrpack"
    _pack(pack)
    root = tmp_path / "server-root"
    root.mkdir()
    (root / configmod.CONFIG_NAME).write_text(configmod.render_template("fabric", "1.21.1"))

    result = modpack.apply_file(root, pack, http, name="Test Pack", exclude=["mods/two.jar"])
    cfg = configmod.load(root)

    assert result["name"] == "Test Pack"
    assert result["removed"] == 1
    assert result["client_only"] == 1
    assert [m.id for m in cfg.mods] == ["PROJ0001"]
    assert cfg.server.minecraft == "1.21.1"
    assert cfg.server.loader == "fabric"


def test_setup_only_accepts_mod_file_paths_as_modpack_exclusions():
    good = setupmod.SetupSpec.from_dict({
        "loader": "fabric",
        "minecraft": "1.21.1",
        "modpack_version": "PACK0001",
        "modpack_exclude": ["mods/one.jar", "mods/nested/two.jar", "mods/one.jar"],
        "accept_eula": True,
    })
    assert good.modpack_exclude == ["mods/one.jar", "mods/nested/two.jar"]

    for bad in ("../one.jar", "mods/../one.jar", "config/a.json", "mods\\one.jar", "mods/no-extension"):
        with pytest.raises(ConfigError):
            setupmod.SetupSpec.from_dict({
                "loader": "fabric",
                "minecraft": "1.21.1",
                "modpack_version": "PACK0001",
                "modpack_exclude": [bad],
                "accept_eula": True,
            })
