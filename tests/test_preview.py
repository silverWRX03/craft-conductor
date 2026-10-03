"""World previews: reading a world's region files into a map, and the preview job."""

import gzip
import struct
import zlib

import pytest

from craft_conductor import nbt as craft_conductor_nbt, preview

from test_hub import login
from test_web import wait_for


# ------------------------------------------------------------- writing test worlds
def nbt(root: dict) -> bytes:
    """Uncompressed NBT for plain Python values; ("L", [...]) is a long array."""
    def conv(v):
        if isinstance(v, tuple) and v and v[0] == "I":
            return craft_conductor_nbt.Tagged(craft_conductor_nbt.INT_ARRAY, list(v[1]))
        if isinstance(v, tuple) and v and v[0] == "L":
            return craft_conductor_nbt.Tagged(craft_conductor_nbt.LONG_ARRAY, [x - (1 << 64) if x >= 1 << 63 else x for x in v[1]])
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        if isinstance(v, list):
            items = [conv(x) for x in v]
            return craft_conductor_nbt.ListTag(craft_conductor_nbt._kind(items[0]) if items else craft_conductor_nbt.END, items)
        return v
    return craft_conductor_nbt.dumps(conv(root))


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
    Minecraft versions keep the spawn where craft-conductor can't read it: the map goes where the land is."""
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


def test_map_tiles(tmp_path):
    world = tmp_path / "world"
    write_world(world, {(cx, cz): chunk(cx, cz) for cx in range(0, 4) for cz in range(0, 4)})
    s = preview.Surfaces(world)
    w, h, rows = read_png(preview.tile(s, 1, 0, 0))
    assert (w, h) == (256, 256) and rows[10][10][:3] == preview.COLORS["grass_block"] and rows[200][200][3] == 0
    w, h, rows = read_png(preview.tile(s, 4, 0, 0))  # zoomed out: 64 blocks of land in 16 pixels
    assert rows[5][5][3] == 255 and rows[20][20][3] == 0
    assert read_png(preview.tile(s, 1, 50, 50))[0] == 1  # nowhere near: an empty picture
    with pytest.raises(preview.PreviewError):
        preview.tile(s, 3, 0, 0)
    first = s.region(0, 0)
    assert s.region(0, 0) is first  # read once, until the file changes


def test_worlds_from_minecraft_26_keep_their_land_under_dimensions(tmp_path):
    """Minecraft 26.x saves the Overworld in world/dimensions/minecraft/overworld/region: a map
    of such a world said "the server didn't save any land" although it had."""
    from craft_conductor import areas, lagfinder
    world = tmp_path / "world"
    write_world(world, {(cx, cz): chunk(cx, cz) for cx in range(-2, 2) for cz in range(-2, 2)})
    overworld = world / "dimensions" / "minecraft" / "overworld"
    overworld.mkdir(parents=True)
    (world / "region").rename(overworld / "region")
    (world / "dimensions" / "minecraft" / "the_nether" / "region").mkdir(parents=True)
    assert preview.region_folder(world) == overworld / "region"
    assert preview.map_center(world, 32) == ((0, 0), (0, 0))
    image, meta = preview.render(world, (0, 0), 32, (0, 0))
    assert read_png(image)[2][10][10][:3] == preview.COLORS["grass_block"]
    assert read_png(preview.tile(preview.Surfaces(world), 1, 0, 0))[0] == 256
    assert areas.dimension_folder(world, "nether") == world / "dimensions" / "minecraft" / "the_nether"
    assert areas.dimension_dir("world", "end", tmp_path) == "world/dimensions/minecraft/the_end"
    assert [name for name, _ in lagfinder._dimensions(world)] == ["the Overworld", "the Nether"]
    # Older worlds are where they always were.
    old = tmp_path / "old"
    write_world(old, {(0, 0): chunk(0, 0)})
    (old / "DIM-1").mkdir()
    assert preview.region_folder(old) == old / "region"
    assert areas.dimension_folder(old, "nether") == old / "DIM-1"
    assert areas.dimension_dir("old", "overworld", tmp_path) == "old"


def test_block_palettes_from_minecraft_26(tmp_path):
    """26.x writes a palette as plain names, as {id, properties}, or (mixed) with names wrapped
    as {"": name}: all read as the block, not air (the map came out full of holes)."""
    assert preview._block_name({"Name": "minecraft:stone", "Properties": {}}) == "minecraft:stone"
    assert preview._block_name("minecraft:sand") == "minecraft:sand"
    assert preview._block_name({"id": "minecraft:cave_vines", "properties": {"age": "1"}}) == "minecraft:cave_vines"
    assert preview._block_name({"": "minecraft:clay"}) == "minecraft:clay"
    assert preview._block_name({}) == preview._block_name(5) == "minecraft:air"
    for palette in (["minecraft:air", "minecraft:sand"], [{"": "minecraft:air"}, {"id": "minecraft:sand", "properties": {}}]):
        root = chunk(0, 0, block="minecraft:sand")
        root["sections"][0]["block_states"]["palette"] = palette
        surface = preview.chunk_surface(preview.read_nbt(nbt(root)))
        assert all(h is not None for h in surface.heights)
        assert bytes(surface.colors[:3]) == bytes(preview.COLORS["sand"])


def test_the_preview_installs_what_the_picked_mods_need(hub_env, modrinth, monkeypatch):
    """The page sends the mods that were picked; the ones they need come along (Towns and Towers
    needs Cristel Lib), and one that can't be installed is named."""
    hub, c = hub_env
    login(c)
    for pid, slug, title in (("FAPI", "fabric-api", "Fabric API"), ("CHK", "chunky", "Chunky"),
                             ("TNT", "towns-and-towers", "Towns and Towers"), ("CRL", "cristel-lib", "Cristel Lib")):
        modrinth.project(pid, slug, title)
    modrinth.version("FAPI", "1.0", ["1.21.1"])
    modrinth.version("CHK", "1.0", ["1.21.1"])
    modrinth.version("TNT", "1.0", ["1.21.1"], deps=["CRL"])
    modrinth.version("CRL", "1.0", ["1.21.1"])
    installed, steps = [], []
    real_check = preview.Preview._server

    def server(self):
        m = real_check(self)
        steps.append(self.step)
        return m

    def generate(self, m):
        installed.append(sorted(p.name.split("-")[0] for p in (m.server_dir / "mods").iterdir()))
        write_world(m.server_dir / "world", {(cx, cz): chunk(cx, cz) for cx in range(-8, 8) for cz in range(-8, 8)})
        return m.server_dir / "world"

    monkeypatch.setattr(preview.Preview, "_server", server)
    monkeypatch.setattr(preview.Preview, "_generate", generate)
    body = {"loader": "fabric", "minecraft": "1.21.1", "mods": ["towns-and-towers"], "seed": "1",
            "level_type": "minecraft:normal", "structures": True, "radius": 128}
    r = c.post("/api/hub/preview", body)[1]
    wait_for(lambda: c.get(f"/api/hub/preview?id={r['id']}")[1]["state"] != "running", timeout=60)
    assert c.get(f"/api/hub/preview?id={r['id']}")[1]["state"] == "done"
    assert installed == [["CHK", "CRL", "FAPI", "TNT"]]
    assert "needed by them: Cristel Lib" in steps[0] and "Towns and Towers" in steps[0]
    # A needed mod without a build for this Minecraft: the error says which.
    modrinth.project("OLD", "old-lib", "Old Lib")
    modrinth.version("OLD", "1.0", ["1.20.1"])
    modrinth.version("TNT", "1.1", ["1.21.1"], deps=["CRL", "OLD"])
    r = c.post("/api/hub/preview", {**body, "mods": ["towns-and-towers", "chunky"]})[1]
    wait_for(lambda: c.get(f"/api/hub/preview?id={r['id']}")[1]["state"] != "running", timeout=60)
    job = c.get(f"/api/hub/preview?id={r['id']}")[1]
    assert job["state"] == "failed" and "Old Lib" in job["error"], job


def test_exploring_the_map_from_the_page(hub_env, modrinth, monkeypatch):
    hub, c = hub_env
    login(c)
    for pid, slug in (("FAPI", "fabric-api"), ("CHK", "chunky")):
        modrinth.project(pid, slug, slug)
        modrinth.version(pid, "1.0", ["1.21.1"])
    made = []

    def generate(self, center, radius, report=None):  # the fake server can't make land: write it
        cx0 = (center[0] if center else 0) >> 4
        cz0 = (center[1] if center else 0) >> 4
        made.append((center, radius))
        r = radius >> 4
        chunks = {(cx, cz): chunk(cx, cz) for cx in range(cx0 - r, cx0 + r) for cz in range(cz0 - r, cz0 + r)}
        write_world(self.world, chunks) if not (self.world / "region").exists() else _add(self.world, chunks)

    def _add(world, chunks):
        import shutil
        other = world.parent / "more"
        shutil.rmtree(other, ignore_errors=True)
        write_world(other, chunks)
        for f in (other / "region").iterdir():
            (world / "region" / f.name).write_bytes(f.read_bytes())

    monkeypatch.setattr(preview.MapSession, "generate", generate)
    body = {"loader": "fabric", "minecraft": "1.21.1", "mods": [], "seed": "1", "level_type": "minecraft:normal",
            "structures": True, "radius": 128}
    r = c.post("/api/hub/preview", body)[1]
    wait_for(lambda: c.get(f"/api/hub/preview?id={r['id']}")[1]["state"] != "running", timeout=60)
    assert c.get(f"/api/hub/preview?id={r['id']}")[1]["state"] == "done"
    info = c.get(f"/api/hub/map?id={r['id']}")[1]
    assert info["version"] == 0 and info["regions"] and info["areas"][0][2] == 128
    assert info["spawn"] == {"x": 0, "z": 0}  # browser tile coordinates use named axes
    status, png, headers = c.get(f"/api/hub/map/tile?id={r['id']}&s=1&x=0&z=0")
    assert status == 200 and headers["Content-Type"] == "image/png"
    assert c.get(f"/api/hub/map/biome?id={r['id']}&x=5&z=5")[1] == {"biome": "minecraft:plains", "made": True}
    assert c.get(f"/api/hub/map/tile?id={r['id']}&s=3&x=0&z=0")[0] == 400
    assert c.get(f"/api/hub/map/tile?id={r['id']}&s=1&x=a&z=0")[0] == 400
    # more land, elsewhere
    status, job, _ = c.post("/api/hub/map/explore", {"id": r["id"], "x": 2000, "z": -1000, "radius": 256})
    assert status == 200 and job["state"] == "running"
    wait_for(lambda: c.get(f"/api/hub/map?id={r['id']}")[1]["job"]["state"] != "running", timeout=30)
    info = c.get(f"/api/hub/map?id={r['id']}")[1]
    assert info["job"]["state"] == "done" and info["version"] == 1 and made[-1] == ((2000, -1000), 256)
    assert c.get(f"/api/hub/map/biome?id={r['id']}&x=2000&z=-1000")[1]["made"]
    assert c.post("/api/hub/map/explore", {"id": r["id"], "x": 0, "z": 0, "radius": 5000})[0] == 400
    assert c.get("/api/hub/map?id=000000000000")[0] == 404
    # a new preview replaces the explorable world
    old = hub.map_session
    r2 = c.post("/api/hub/preview", body)[1]
    wait_for(lambda: c.get(f"/api/hub/preview?id={r2['id']}")[1]["state"] != "running", timeout=60)
    assert old.closed and c.get(f"/api/hub/map?id={r['id']}")[0] == 404
    from craft_conductor.web import device_allowed
    assert not device_allowed("POST", "/api/hub/map/explore")


def test_the_seed_gallery(hub_env, modrinth, monkeypatch):
    hub, c = hub_env
    login(c)
    modrinth.project("FAPI", "fabric-api", "Fabric API")
    modrinth.version("FAPI", "1.0", ["1.21.1"])
    modrinth.project("CHK", "chunky", "Chunky")
    modrinth.version("CHK", "1.0", ["1.21.1"])
    seeds, servers = [], set()

    def generate(self, m):
        seeds.append(self.seed)
        servers.add(m.server_dir)
        world = m.server_dir / "world"
        write_world(world, {(cx, cz): chunk(cx, cz) for cx in range(-4, 4) for cz in range(-4, 4)})
        return world

    monkeypatch.setattr(preview.Preview, "_generate", generate)
    body = {"loader": "fabric", "minecraft": "1.21.1", "mods": [], "level_type": "minecraft:normal", "structures": True,
            "radius": 128}
    assert c.post("/api/hub/preview/gallery", {**body, "count": 11})[0] == 400
    assert c.post("/api/hub/preview/gallery", {**body, "count": 3, "radius": 7})[0] == 400
    status, r, _ = c.post("/api/hub/preview/gallery", {**body, "count": 3})
    assert status == 200, r
    wait_for(lambda: c.get(f"/api/hub/preview/gallery?id={r['id']}")[1]["state"] != "running", timeout=60)
    g = c.get(f"/api/hub/preview/gallery?id={r['id']}")[1]
    assert g["state"] == "done" and len(g["maps"]) == 3, g
    assert len(set(seeds)) == 3 and len(servers) == 1  # three random seeds, one server set up once
    assert [m["seed"] for m in g["maps"]] == seeds
    assert c.get(f"/api/hub/preview/map?id={g['maps'][0]['id']}")[0] == 200
    assert c.get(f"/api/hub/map?id={g['maps'][-1]['id']}")[0] == 200  # the last one can be explored
    # Stopped part-way: the maps made so far stay.
    hold = __import__("threading").Event()
    monkeypatch.setattr(preview.Preview, "_generate", lambda self, m: (hold.wait(30), generate(self, m))[1])
    r = c.post("/api/hub/preview/gallery", {**body, "count": 5})[1]
    assert c.post("/api/hub/preview", {**body, "seed": "1"})[0] == 409  # one thing at a time
    assert c.post("/api/hub/preview/gallery/cancel", {"id": r["id"]})[0] == 200
    hold.set()
    wait_for(lambda: c.get(f"/api/hub/preview/gallery?id={r['id']}")[1]["state"] != "running", timeout=60)
    g = c.get(f"/api/hub/preview/gallery?id={r['id']}")[1]
    assert g["state"] == "cancelled" and len(g["maps"]) <= 1


def test_landmarks_are_found_in_the_world(tmp_path):
    world = tmp_path / "world"
    chunks = {(cx, cz): chunk(cx, cz) for cx in range(-2, 2) for cz in range(-2, 2)}
    chunks[(1, 1)]["structures"] = {"starts": {
        "minecraft:village_plains": {"id": "minecraft:village_plains", "ChunkX": 1, "ChunkZ": 1,
                                     "Children": [{"id": "minecraft:jigsaw", "BB": ("I", [20, 60, 22, 30, 70, 28])}]},
        "minecraft:mineshaft": {"id": "minecraft:mineshaft", "ChunkX": 1, "ChunkZ": 1, "Children": []},  # (underground: left out)
        "minecraft:igloo": {"id": "INVALID"}}}
    chunks[(-2, -2)]["structures"] = {"starts": {
        "towns:castle": {"id": "towns:big_castle", "ChunkX": -2, "ChunkZ": -2}}}  # a mod's: no box, the chunk's middle
    write_world(world, chunks, spawn=(8, 8))
    image, meta = preview.render(world, (0, 0), 32, (8, 8))
    marks = {(m["kind"], m["name"], m["x"], m["z"]) for m in meta["landmarks"]}
    assert marks == {("village", "Village", 25, 25), ("big_castle", "Big castle", -24, -24)}
    assert preview.Surfaces(world).landmarks(0, 0, 32, 32)[0]["symbol"] == "🏠"
    assert preview.landmark_kind("minecraft:ocean_ruin_cold")[1] == "Ocean ruins"
    assert preview.landmark_kind("minecraft:something_new") is None
