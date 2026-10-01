"""Backups that are checked, and putting back one area of the world from a backup."""

import gzip
import tarfile

from craft_conductor import areas, backup

from test_hub import login
from test_preview import chunk, write_world
from test_web import wait_for


def blocks(world, cx, cz):
    """The name of the ground block of a chunk (as test_preview's chunk() writes it)."""
    from craft_conductor.preview import region_chunks
    for x, z, root in region_chunks(world / "region" / f"r.{cx >> 5}.{cz >> 5}.mca"):
        if (x, z) == (cx, cz):
            return root["sections"][0]["block_states"]["palette"][1]["Name"]
    return None


def make_server(tmp_path, block="minecraft:grass_block"):
    sd = tmp_path / "server"
    world = sd / "world"
    world.mkdir(parents=True)
    write_world(world, {(cx, cz): chunk(cx, cz, block=block) for cx in range(-3, 3) for cz in range(-3, 3)})
    return sd


def test_backups_are_read_through(tmp_path):
    sd = make_server(tmp_path)
    b = backup.create(sd, tmp_path / "backups", "x", [])
    r = areas.check(b.parent, b.name)
    assert r["ok"] and r["regions"] == 4 and areas.load_checks(b.parent)[b.name]["ok"]
    cut = tmp_path / "backups" / "20000101-000000-cut.tar.gz"
    cut.write_bytes(b.read_bytes()[: b.stat().st_size // 2])  # a copy cut short
    assert not areas.verify(cut)["ok"]
    empty = tmp_path / "e"
    (empty / "x").mkdir(parents=True)
    assert areas.verify(backup.create(empty, tmp_path / "b2", "y", []))["detail"].startswith("no world")
    # a world whose level.dat is garbage
    (sd / "world" / "level.dat").write_bytes(gzip.compress(b"not nbt"))
    assert not areas.verify(backup.create(sd, tmp_path / "b3", "z", []))["ok"]


def test_one_area_is_put_back(tmp_path):
    sd = make_server(tmp_path)
    b = backup.create(sd, tmp_path / "backups", "before", [])
    # griefing: the whole world is now dirt, and a new chunk appeared inside the area
    import shutil
    shutil.rmtree(sd / "world")
    (sd / "world").mkdir()
    chunks = {(cx, cz): chunk(cx, cz, block="minecraft:dirt") for cx in range(-3, 3) for cz in range(-3, 3)}
    write_world(sd / "world", chunks)
    r = areas.restore_area(b, sd, "world", "overworld", -20, -20, 15, 15)  # chunks -2..0 each way
    assert r["chunks"] == 9
    assert blocks(sd / "world", -2, -2) == blocks(sd / "world", 0, 0) == "minecraft:grass_block"
    assert blocks(sd / "world", 1, 1) == blocks(sd / "world", -3, -3) == "minecraft:dirt"  # outside: as it is now
    # the nether folder doesn't exist in either: nothing to do
    import pytest
    with pytest.raises(areas.AreaError):
        areas.restore_area(b, sd, "world", "nether", 0, 0, 1, 1)
    with pytest.raises(areas.AreaError):
        areas.restore_area(b, sd, "world", "overworld", 0, 0, 10_000, 0)
    assert areas.dimension_dir("world", "end") == "world/DIM1"
    for bad in ("../x", "..", "a/b", "C:x"):
        with pytest.raises(areas.AreaError):
            areas.dimension_dir(bad, "overworld")
    (sd / "world_nether").mkdir()
    assert areas.dimension_dir("world", "nether", sd) == "world_nether/DIM-1"  # Paper


def test_region_files_round_trip():
    chunks = {5: (b"\x00\x00\x00\x03\x02ab", 7), 1023: (b"\x00\x00\x10\x01" + b"\x02" + b"x" * 4096, 9)}
    again = areas.read_region(areas.write_region(chunks))
    assert again[5] == chunks[5] and again[1023][0] == chunks[1023][0][:4 + 4097] and again[1023][1] == 9


def test_from_the_backups_page(hub_env):
    hub, c = hub_env
    login(c)
    d = hub.get("alpha")
    world = d.m.server_dir / "world"
    world.mkdir(exist_ok=True)
    write_world(world, {(cx, cz): chunk(cx, cz) for cx in range(-2, 2) for cz in range(-2, 2)})
    status, r, _ = c.post("/api/servers/alpha/backups/create", {"label": "t"})
    assert status == 200
    wait_for(lambda: c.get("/api/servers/alpha/status")[1]["job"] is None, timeout=30)
    listed = c.get("/api/servers/alpha/backups")[1]["backups"][0]
    assert listed["check"]["ok"], listed  # checked right after it was made
    assert "checked" in c.get("/api/servers/alpha/status")[1]["last_job"]["message"]
    name = listed["name"]
    assert c.post("/api/servers/alpha/backups/check", {"name": "../../etc/passwd"})[0] == 404
    assert c.post("/api/servers/alpha/backups/check", {"name": name})[0] == 200
    wait_for(lambda: c.get("/api/servers/alpha/status")[1]["job"] is None, timeout=30)
    body = {"name": name, "dimension": "overworld", "x1": 0, "z1": 0, "x2": 5, "z2": 5}
    assert c.post("/api/servers/alpha/backups/area", {**body, "dimension": "moon"})[0] == 400
    assert c.post("/api/servers/alpha/backups/area", {**body, "x2": "a"})[0] == 400
    if d.state != "stopped":
        assert c.post("/api/servers/alpha/backups/area", body)[0] == 409
        c.post("/api/servers/alpha/server/stop", {})
        wait_for(lambda: d.state == "stopped", timeout=30)
    assert c.post("/api/servers/alpha/backups/area", body)[0] == 200
    wait_for(lambda: c.get("/api/servers/alpha/status")[1]["job"] is None, timeout=30)
    last = c.get("/api/servers/alpha/status")[1]["last_job"]
    assert last["ok"] and "put back 1 chunk" in last["message"], last
    assert any("before-putting-an-area-back" in b["name"] for b in c.get("/api/servers/alpha/backups")[1]["backups"])
    with tarfile.open(d.m.config.backups.dir / name) as tar:
        assert any(m.name.endswith("level.dat") for m in tar)
