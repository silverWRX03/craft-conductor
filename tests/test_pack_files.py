"""A modpack's own files (configs, scripts) for friends: All the Mods 11's friends got its mods but not
its KubeGroovy scripts, and the server refused them ("registries with unknown keys", #288)."""

import hashlib
import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from craft_conductor import config as configmod, join, launchers, packfiles
from craft_conductor.mods import curseforge as cf
from craft_conductor.mods.modrinth import API as MODRINTH

from test_friends import pack

CF_URL = "https://edge.forgecdn.net/files/9001/big-pack-1.0.zip"
MR_URL = "https://cdn.modrinth.com/data/PACK/versions/V1/big-pack-1.0.mrpack"


def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def cf_pack(version="1", extra=None) -> bytes:
    files = {"manifest.json": json.dumps({"manifestType": "minecraftModpack", "manifestVersion": 1, "overrides": "Over",
                                          "minecraft": {"version": "1.21.1", "modLoaders": [{"id": "neoforge-21.1.1"}]},
                                          "files": []}),
             "Over/kubegroovy/startup_scripts/items.groovy": f"items v{version}",
             "Over/config/pack.toml": f"v = {version}",
             "Over/options.txt": "guiScale:2",
             "Over/servers.dat": "the pack's own list",
             "Over/../escape.txt": "no",
             "outside.txt": "not an override"}
    files.update(extra or {})
    return _zip(files)


def info_for(http, data: bytes, url: str = CF_URL, kind: str = "curseforge") -> dict:
    http.files[url] = data
    return {"kind": kind, "name": "Big Pack 1.0", "url": url, "sha1": hashlib.sha1(data).hexdigest(), "size": len(data)}


def joiner(http, tmp_path):
    return join.Joiner(join.Invite("mc.example.com", 1, "A" * 24, "F" * 43), mc_dir=tmp_path / "mc", http=http,
                       say=lambda s: None)


def test_the_server_names_its_modpack_file(http):
    """CurseForge: the pack's file by CurseForge's API (its download and checksum); Modrinth: the version's
    primary file. Nothing is named for an author who keeps the pack to CurseForge's own app."""
    data = cf_pack()
    http.posts[f"{cf.API}/mods/files"] = lambda body: {"data": [{"id": 9001, "downloadUrl": CF_URL, "fileLength": len(data),
                                                                  "hashes": [{"value": hashlib.sha1(data).hexdigest(), "algo": 1}]}]}
    packfiles._known.clear()
    m = SimpleNamespace(config=SimpleNamespace(modpack=configmod.Modpack("curseforge", "500", "9001", "Big Pack 1.0")),
                        loader=SimpleNamespace(mods_folder="mods"), http=http,
                        providers={"curseforge": SimpleNamespace(api_key="test-key-not-real")})
    assert packfiles.describe(m) == {"kind": "curseforge", "name": "Big Pack 1.0", "url": CF_URL,
                                     "sha1": hashlib.sha1(data).hexdigest(), "size": len(data)}
    http.json[f"{MODRINTH}/version/V1"] = {"files": [{"primary": True, "url": MR_URL, "size": 5, "hashes": {"sha1": "b" * 40}}]}
    m.config.modpack = configmod.Modpack("modrinth", "PACK", "V1", "Big Pack 1.0")
    assert packfiles.describe(m)["url"] == MR_URL
    m.config.modpack = configmod.Modpack("curseforge", "500", "9002", "Blocked")  # (no downloadUrl)
    http.posts[f"{cf.API}/mods/files"] = lambda body: {"data": [{"id": 9002, "downloadUrl": None, "hashes": []}]}
    assert packfiles.describe(m) is None
    m.config.modpack = None
    assert packfiles.describe(m) is None


def test_a_friend_gets_the_packs_configs_and_scripts(tmp_path, http):
    game = tmp_path / "game"
    j = joiner(http, tmp_path)
    info = info_for(http, cf_pack("1"))
    j.sync_mods(join.validate_pack(pack(pack_files=info)), game)
    assert (game / "kubegroovy" / "startup_scripts" / "items.groovy").read_text() == "items v1"
    assert (game / "config" / "pack.toml").read_text() == "v = 1"
    assert (game / "options.txt").read_text() == "guiScale:2"  # (none yet: the pack's)
    assert not (tmp_path / "escape.txt").exists() and not (game / "outside.txt").exists()
    # Up to date: not downloaded again
    (game / "options.txt").write_text("guiScale:4")  # (the friend's own from now on)
    downloads = len(http.downloads)
    j.sync_mods(join.validate_pack(pack(pack_files=info)), game)
    assert len(http.downloads) == downloads
    # The pack's next version: its files replace these, one it dropped is removed, the friend's settings stay
    data2 = _zip({"manifest.json": json.dumps({"overrides": "Over", "minecraft": {"version": "1.21.1"}, "files": []}),
                  "Over/config/pack.toml": "v = 2", "Over/options.txt": "guiScale:2"})
    newer = info_for(http, data2, "https://edge.forgecdn.net/files/9003/big-pack-2.0.zip")
    j.sync_mods(join.validate_pack(pack(pack_files=newer)), game)
    assert (game / "config" / "pack.toml").read_text() == "v = 2"
    assert not (game / "kubegroovy" / "startup_scripts" / "items.groovy").exists()
    assert (game / "options.txt").read_text() == "guiScale:4"
    # The server isn't on a pack any more: the pack's files go
    j.sync_mods(join.validate_pack(pack()), game)
    assert not (game / "config" / "pack.toml").exists() and (game / "options.txt").read_text() == "guiScale:4"
    assert "pack_files" not in json.loads((game / join.MANIFEST).read_text())


def test_a_modrinth_packs_players_files_win(tmp_path, http):
    game = tmp_path / "game"
    data = _zip({"modrinth.index.json": "{}", "overrides/config/a.toml": "server and players",
                 "client-overrides/config/a.toml": "players", "server-overrides/config/s.toml": "server only"})
    j = joiner(http, tmp_path)
    j.sync_mods(join.validate_pack(pack(pack_files=info_for(http, data, MR_URL, "modrinth"))), game)
    assert (game / "config" / "a.toml").read_text() == "players" and not (game / "config" / "s.toml").exists()


def test_a_damaged_or_odd_pack_file_is_refused(tmp_path, http):
    j = joiner(http, tmp_path)
    info = info_for(http, cf_pack())
    for bad in ({**info, "url": "https://example.com/pack.zip"}, {**info, "url": CF_URL.replace("https", "http")},
                {**info, "sha1": "x"}, {**info, "kind": "ftb"}, "a pack"):
        with pytest.raises(join.JoinError):
            join.validate_pack(pack(pack_files=bad))
    http.files[CF_URL] = b"something else"  # (not the file CurseForge's checksum is for)
    with pytest.raises(join.JoinError, match="checksum"):
        j.sync_mods(join.validate_pack(pack(pack_files=info)), tmp_path / "game")
    assert not (tmp_path / "game" / "config").exists()


def test_launcher_imports_carry_the_packs_files(tmp_path, http):
    """Modrinth App and CurseForge app: in the modpack zip made for them (servers.dat stays the server's)."""
    j = joiner(http, tmp_path)
    p = join.validate_pack(pack(pack_files=info_for(http, cf_pack())))
    for build in (launchers.build_mrpack, launchers.build_curseforge):
        with zipfile.ZipFile(build(j, p, tmp_path)) as z:
            names = z.namelist()
            assert "overrides/kubegroovy/startup_scripts/items.groovy" in names and "overrides/config/pack.toml" in names
            assert names.count("overrides/servers.dat") == 1 and z.read("overrides/servers.dat") != b"the pack's own list"
