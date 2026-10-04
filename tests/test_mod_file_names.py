"""A mod file's name comes from its author (through Modrinth or CurseForge) and becomes a path on
this computer: one that would land outside the mods folder is never saved."""

import hashlib

from craft_conductor.config import ModSpec
from craft_conductor.mods.curseforge import API as CURSEFORGE

from test_manager import manager, update


def test_a_modrinth_file_named_like_a_path_isnt_saved(make_config, http, modrinth, tmp_path):
    modrinth.project("GOOD", "goodmod", "Good Mod")
    modrinth.version("GOOD", "1.0", ["1.21.1"])
    modrinth.project("EVIL", "evilmod", "Evil Mod")
    modrinth.version("EVIL", "1.0", ["1.21.1"], filename="../../../escaped.jar")
    cfg = make_config([ModSpec("modrinth", "goodmod"), ModSpec("modrinth", "evilmod", required=False)])
    m = manager(cfg, http, ["1.21.1"])
    decision, _ = m.check()
    assert [x.name for x in decision.plan.mods] == ["Good Mod"]
    [left_out] = decision.plan.dropped
    assert left_out.name == "Evil Mod" and "isn't safe to save" in left_out.reason
    assert update(m).ok
    assert not list(tmp_path.rglob("escaped.jar"))


def test_a_blocked_curseforge_file_named_like_a_path_isnt_waited_for(make_config, http, modrinth):
    """Its name would also be where the manual download is looked for."""
    jar = b"jar"
    http.json[f"{CURSEFORGE}/mods/123"] = {"data": {"id": 123, "slug": "blocked-mod", "name": "Blocked Mod"}}
    http.json[f"{CURSEFORGE}/mods/123/files"] = {"data": [{
        "id": 5550001, "displayName": "Blocked Mod 1.0", "fileName": "..\\..\\escaped.jar", "releaseType": 1,
        "downloadUrl": None, "gameVersions": ["1.21.1", "Fabric"], "fileDate": "2025-01-01T00:00:00Z",
        "hashes": [{"value": hashlib.sha1(jar).hexdigest(), "algo": 1}], "dependencies": []}]}
    cfg = make_config([ModSpec("curseforge", "123")])
    cfg.curseforge_api_key = "test-key"
    m = manager(cfg, http, ["1.21.1"])
    decision, _ = m.check()
    assert decision.plan is None
    [blocker] = decision.blocked[0].blockers
    assert blocker.name == "Blocked Mod" and "isn't safe to save" in blocker.reason
