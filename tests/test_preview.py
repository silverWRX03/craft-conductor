"""World previews: reading a world's region files into a map, and the preview job."""

import gzip
import struct
import zlib

import pytest

from mcsm import nbt as mcsm_nbt, preview

from test_hub import login
from test_web import wait_for


# ------------------------------------------------------------- writing test worlds
def nbt(root: dict) -> bytes:
    """Uncompressed NBT for plain Python values; ("L", [...]) is a long array."""
    def conv(v):
        if isinstance(v, tuple) and v and v[0] == "I":
            return mcsm_nbt.Tagged(mcsm_nbt.INT_ARRAY, list(v[1]))
        if isinstance(v, tuple) and v and v[0] == "L":
            return mcsm_nbt.Tagged(mcsm_nbt.LONG_ARRAY, [x - (1 << 64) if x >= 1 << 63 else x for x in v[1]])
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        if isinstance(v, list):
            items = [conv(x) for x in v]
            return mcsm_nbt.ListTag(mcsm_nbt._kind(items[0]) if items else mcsm_nbt.END, items)
        return v
    return mcsm_nbt.dumps(conv(root))


def pack(values, bits):
    per = 64 // bits
    longs = []
    for i in range(0, len(values), per):
        word = 0
        for j, v in enumerate(values[i:i + per]):
            word |= v << (j * bits)
        longs.append(word)
    return longs


def chunk(cx, cz, ground_y=64, block="minecraft:grass_block", biome="minecraft:plains", status="minecraft:full"):
    """A chunk whose ground is ``block`` at ``ground_y`` (one section, -4 is the bottom)."""
    min_y = -64
    sy = ground_y >> 4
    palette = [{"Name": "minecraft:air"}, {"Name": block}]
    blocks = [0] * 4096
    for z in range(16):
        for x in range(16):
            blocks[((ground_y & 15) * 16 + z) * 16 + x] = 1
    height = [ground_y + 1 - min_y] * 256
    return {"Status": status, "yPos": -4, "xPos": cx, "zPos": cz,
            "Heightmaps": {"WORLD_SURFACE": ("L", pack(height, 9)), "OCEAN_FLOOR": ("L", pack([h - 4 for h in height], 9))},
            "sections": [{"Y": sy, "block_states": {"palette": palette, "data": ("L", pack(blocks, 4))},
                          "biomes": {"palette": [biome]}}]}


def write_world(world, chunks, spawn=(0, 0)):
    """``chunks``: {(cx, cz): root compound}, written into region files."""
    regions = {}
    for (cx, cz), root in chunks.items():
        regions.setdefault((cx >> 5, cz >> 5), {})[(cx & 31) + (cz & 31) * 32] = zlib.compress(nbt(root))
    (world / "region").mkdir(parents=True)
    for (rx, rz), entries in regions.items():
        header, body = bytearray(8192), bytearray()
        for index, data in sorted(entries.items()):
            blob = struct.pack(">IB", len(data) + 1, 2) + data
            blob += b"\x00" * (-len(blob) % 4096)
            offset = 2 + len(body) // 4096
            header[index * 4:index * 4 + 4] = struct.pack(">I", (offset << 8) | (len(blob) // 4096))
            body += blob
        (world / "region" / f"r.{rx}.{rz}.mca").write_bytes(bytes(header) + bytes(body))
    (world / "level.dat").write_bytes(gzip.compress(nbt({"Data": {"SpawnX": spawn[0], "SpawnZ": spawn[1]}})))


def read_png(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", data[16:24])
    pos, idat = 8, b""
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        if kind == b"IDAT":
            idat += data[pos + 8:pos + 8 + n]
        pos += 12 + n
    raw = zlib.decompress(idat)
    rows = []
    for y in range(h):
        row = raw[y * (w * 4 + 1):(y + 1) * (w * 4 + 1)]
        assert row[0] == 0
        rows.append([tuple(row[1 + x * 4:5 + x * 4]) for x in range(w)])
    return w, h, rows


# ------------------------------------------------------------------------ tests
def test_nbt_and_packing_round_trip():
    root = preview.read_nbt(nbt({"a": 5, "b": "text", "c": [1, 2], "d": {"e": ("L", [1, 2**63 + 5])}}))
    assert root["a"] == 5 and root["b"] == "text" and root["c"] == [1, 2]
    assert root["d"]["e"].longs() == (1, 2**63 + 5)
    values = [i % 300 for i in range(256)]
    assert preview.unpack(tuple(pack(values, 9)), 9, 256) == values
    with pytest.raises(preview.PreviewError):
        preview.read_nbt(b"\x0a\x00\x00\x09\x00")  # cut short


def test_a_world_becomes_a_map(tmp_path):
    world = tmp_path / "world"
    chunks = {(cx, cz): chunk(cx, cz) for cx in range(-2, 2) for cz in range(-2, 2)}
    chunks[(0, 0)] = chunk(0, 0, ground_y=62, block="minecraft:water", biome="minecraft:river")
    chunks[(1, 1)] = chunk(1, 1, ground_y=90, block="terralith:strange_moss", biome="terralith:moonlight_grove")  # a mod's
    chunks[(-1, 1)] = chunk(-1, 1, status="minecraft:noise")  # not finished: left out
    write_world(world, chunks, spawn=(8, 8))
    assert preview.spawn_point(world) == (8, 8)
    assert preview.map_center(world, 32) == ((8, 8), (8, 8))
    image, meta = preview.render(world, (0, 0), 32, (8, 8))
    w, h, rows = read_png(image)
    assert (w, h) == (64, 64) and meta["size"] == 64 and (meta["x"], meta["z"]) == (-32, -32)
    assert meta["spawn"] == {"x": 8, "z": 8}
    at = lambda x, z: rows[z + 32][x + 32]  # noqa: E731
    assert at(-20, -20)[:3] == preview.COLORS["grass_block"]
    water = at(5, 5)
    assert water[3] == 255 and water[2] > water[0] and water[2] < 255  # blue, darker for its depth
    assert at(20, 20)[:3] == preview.KEYWORDS[7][1]  # "moss" from the block's name
    assert at(-10, 20) == preview.BACKGROUND  # the unfinished chunk
    b = meta["biomes"]
    assert (b["chunk_x"], b["chunk_z"]) == (-2, -2)
    name = lambda cx, cz: b["names"][b["grid"][cz + 2][cx + 2]]  # noqa: E731
    assert name(0, 0) == "minecraft:river" and name(1, 1) == "terralith:moonlight_grove" and name(-2, -2) == "minecraft:plains"
    assert b["grid"][1 + 2][-1 + 2] == -1
    # A cliff shows as relief: the edge going up is lighter than the flat ground behind it.
    assert at(20, 16)[:3] > at(20, 20)[:3]


def test_the_map_follows_the_land_when_the_spawn_cant_be_read(tmp_path):
    """The land Chunky made can be far from 0,0 (Terralith often moves the spawn), and some
    Minecraft versions keep the spawn where mcsm can't read it: the map goes where the land is."""
    import gzip as _gzip
    world = tmp_path / "world"
    write_world(world, {(cx, cz): chunk(cx, cz) for cx in range(60, 70) for cz in range(-40, -30)})
    (world / "level.dat").write_bytes(_gzip.compress(nbt({"Data": {"somethingNew": 1}})))
    assert preview.spawn_point(world) is None
    center, spawn = preview.map_center(world, 64)
    assert spawn is None and 60 * 16 <= center[0] < 70 * 16 and -40 * 16 <= center[1] < -30 * 16
    image, meta = preview.render(world, center, 64, spawn)
    assert meta["spawn"] is None and read_png(image)[2][64][64][3] == 255  # land in the middle
    # 1.21.9+: the spawn is {pos: [x, y, z]}
    (world / "level.dat").write_bytes(_gzip.compress(nbt({"Data": {"spawn": {"pos": ("I", [1000, 64, -600])}}})))
    assert preview.spawn_point(world) == (1000, -600)
    # Nothing to draw: said plainly, rather than a blank map
    with pytest.raises(preview.PreviewError, match="nothing could be drawn"):
        preview.render(world, (0, 0), 64)
    with pytest.raises(preview.PreviewError, match="no region files"):
        preview.map_center(tmp_path / "empty", 64)


def test_colours_for_unknown_blocks_are_steady():
    assert preview.color("minecraft:snow") == preview.COLORS["snow"]
    assert preview.color("biomesoplenty:jacaranda_leaves") == (48, 110, 36)
    assert preview.color("somemod:thing") == preview.color("somemod:thing")


def test_what_can_be_previewed():
    assert preview.supports("1.21.1") and preview.supports("1.18") and preview.supports("24w14a")
    assert not preview.supports("1.16.5")
    with pytest.raises(preview.PreviewError, match="1.18"):
        preview.Preview(None, "fabric", "1.12.2", [], "", "minecraft:normal", True, 128)
    for bad in ({"seed": "a\nb"}, {"level_type": "minecraft:debug"}, {"radius": 5000}):
        args = {"seed": "", "level_type": "minecraft:normal", "radius": 128, **bad}
        with pytest.raises(preview.PreviewError):
            preview.Preview(None, "fabric", "1.21.1", [], args["seed"], args["level_type"], True, args["radius"])
    p = preview.Preview(None, "vanilla", "1.21.1", [], "", "minecraft:normal", True, 128)
    assert p.loader == "fabric" and p.seed.lstrip("-").isdigit()  # a random seed, shown so it can be kept


def test_the_preview_job_from_the_page(hub_env, modrinth, monkeypatch):
    hub, c = hub_env
    login(c)
    modrinth.project("FAPI", "fabric-api", "Fabric API")
    modrinth.version("FAPI", "1.0", ["1.21.1"])
    modrinth.project("CHK", "chunky", "Chunky")
    modrinth.version("CHK", "1.0", ["1.21.1"])
    modrinth.project("TER", "terralith", "Terralith")
    modrinth.version("TER", "1.0", ["1.21.1"])
    made = []
    import threading
    hold = threading.Event()  # (keeps the first map "being made" until the one-at-a-time check)

    def generate(self, m):  # the fake server can't make worlds: write one where it would be
        hold.wait(30)
        world = m.server_dir / "world"
        assert "level-seed=12345" in (m.server_dir / "server.properties").read_text()
        assert "server-ip=127.0.0.1" in (m.server_dir / "server.properties").read_text()
        assert sorted(p.name.split("-")[0] for p in (m.server_dir / "mods").iterdir()) == ["CHK", "FAPI", "TER"]
        made.append(m.server_dir)
        write_world(world, {(cx, cz): chunk(cx, cz) for cx in range(-8, 8) for cz in range(-8, 8)})
        return world

    monkeypatch.setattr(preview.Preview, "_generate", generate)
    body = {"loader": "fabric", "minecraft": "1.21.1", "mods": ["terralith"], "seed": "12345",
            "level_type": "minecraft:normal", "structures": True, "radius": 128}
    status, r, _ = c.post("/api/hub/preview", body)
    assert status == 200, r
    assert c.post("/api/hub/preview", body)[0] == 409  # one at a time
    hold.set()
    wait_for(lambda: c.get(f"/api/hub/preview?id={r['id']}")[1]["state"] != "running", timeout=60)
    job = c.get(f"/api/hub/preview?id={r['id']}")[1]
    assert job["state"] == "done", job
    assert job["seed"] == "12345" and job["map"]["size"] == 256
    status, png, headers = c.get(f"/api/hub/preview/map?id={r['id']}")
    assert status == 200 and headers["Content-Type"] == "image/png"
    # Another seed reuses the server that's set up (only the world is new).
    body["seed"] = "12345"
    r2 = c.post("/api/hub/preview", body)[1]
    wait_for(lambda: c.get(f"/api/hub/preview?id={r2['id']}")[1]["state"] != "running", timeout=60)
    assert c.get(f"/api/hub/preview?id={r2['id']}")[1]["state"] == "done"
    assert made[0] == made[1]
    assert c.get("/api/hub/preview/map?id=../../etc")[0] == 404
    assert c.post("/api/hub/preview", {**body, "seed": "x" * 65})[0] == 400
    assert c.post("/api/hub/preview", {**body, "mods": ["../x"]})[0] == 400
