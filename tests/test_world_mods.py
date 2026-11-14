"""A world played with mods, imported into a server without them (#234): which mods' data it has is
read from its level.dat (DataPacks → Enabled), so the setup page can say so before Create."""

import gzip
import io
import zipfile

from craft_conductor import nbt, world

from test_hub import login


def level_dat(enabled: list[str]) -> bytes:
    return gzip.compress(nbt.dumps({"Data": {"LevelName": "Modded", "Version": {"Name": "1.21.4"},
                                             "DataPacks": {"Enabled": nbt.ListTag(nbt.STRING, enabled), "Disabled": nbt.ListTag(nbt.STRING)}}}))


ENABLED = ["vanilla", "fabric", "fabric-convention-tags-v2", "axiom", "collective", "easyshulkerboxes", "file/MyPack.zip",
           "bundle", "mod:jade", "mod_resources", "../odd", "trade_rebalance"]


def test_the_mods_a_world_was_played_with():
    assert world.level_info(level_dat(ENABLED))["mods"] == [
        "axiom", "collective", "easyshulkerboxes", "fabric", "fabric-convention-tags-v2", "jade"]
    assert world.level_info(level_dat(["vanilla", "bundle"]))["mods"] == []  # (a plain world)
    assert world.mod_packs("not a list") == [] and world.mod_packs([5, None, "Bad Name"]) == []


def test_saves_and_uploads_say_which_mods(hub_env, tmp_path):
    saves = tmp_path / "saves"
    (saves / "Modded").mkdir(parents=True)
    (saves / "Modded" / "level.dat").write_bytes(level_dat(ENABLED))
    [w] = world.list_saves([("Minecraft Launcher", saves)])
    assert "axiom" in w["mods"] and "vanilla" not in w["mods"]

    hub, c = hub_env
    login(c)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Modded/level.dat", level_dat(["vanilla", "mod:create"]))
    status, r, _ = c.call("POST", "/api/hub/stage?filename=Modded.zip", raw=buf.getvalue(), headers={"X-CRAFT-CONDUCTOR": "1"})
    assert status == 200 and r["world"] == {"version": "1.21.4", "mods": ["create"]}, r
    status, r, _ = c.call("POST", "/api/hub/stage?filename=notaworld.zip", raw=b"not a zip", headers={"X-CRAFT-CONDUCTOR": "1"})
    assert status == 200 and "world" not in r  # (said when it's used)
