"""See a world before you make it: a map of a seed, with the server's world-generation mods.

Only Minecraft itself knows what a seed makes (and world-generation mods change it), so a
preview is made the honest way: a throwaway server with the new server's Minecraft, loader
and mods, plus the Chunky mod, generates the area around spawn; then craft-conductor reads the world's
region files and draws the ground seen from above, like a Minecraft map (with the biome of
each chunk for the page to show on hover). The throwaway server listens only on this
computer, and is kept between previews with the same mods (a new seed only needs a new
world), then deleted.

Maps need Minecraft 1.18 or newer (the region format craft-conductor reads).
"""

from __future__ import annotations

import gzip
import hashlib
import logging
import re
import secrets
import shutil
import struct
import threading
import time
import zlib
from collections import Counter
from pathlib import Path

from . import config as configmod, setup as setupmod
from .config import ModSpec

log = logging.getLogger(__name__)

SIZES = (128, 256, 512)  # radius in blocks: the map is twice that across
LEVEL_TYPES = ("minecraft:normal", "minecraft:large_biomes", "minecraft:amplified", "minecraft:flat",
               "minecraft:single_biome_surface")
SEED = re.compile(r"[^\x00-\x1f\x7f]{0,64}")
GENERATE_TIMEOUT = 20 * 60
KEEP = 14  # maps kept for the page's "earlier previews" (a seed gallery's 10 and a few more)
CHUNKY = ModSpec("modrinth", "chunky")


class PreviewError(ValueError):
    pass


def random_seed() -> str:
    return str(secrets.randbits(63) * (1 if secrets.randbits(1) else -1))


def _version_key(v: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", v)[:3])


def supports(minecraft: str) -> bool:
    """Whether craft-conductor can draw maps of this Minecraft's worlds (1.18+; snapshots count as new)."""
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?(?:-(?:pre|rc)\d+)?", minecraft or ""):
        return True  # a snapshot (24w14a) or "latest": new enough
    return _version_key(minecraft) >= (1, 18)


# ------------------------------------------------------------------------- NBT
# A reader for region files: plain values and long arrays left as bytes until needed, which is
# much faster over thousands of chunks than nbt.py's (made for small files it also writes).
_TAG_STRUCT = {1: ">b", 2: ">h", 3: ">i", 4: ">q", 5: ">f", 6: ">d"}


class _Reader:
    def __init__(self, data: bytes):
        self.data, self.pos = data, 0

    def take(self, n: int) -> bytes:
        if n < 0 or self.pos + n > len(self.data):
            raise PreviewError("a damaged chunk")
        b = self.data[self.pos:self.pos + n]
        self.pos += n
        return b

    def num(self, fmt: str):
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.take(size))[0]

    def string(self) -> str:
        return self.take(self.num(">H")).decode("utf-8", "replace")

    def payload(self, tag: int, depth: int = 0):
        if depth > 64:
            raise PreviewError("a damaged chunk")
        if tag in _TAG_STRUCT:
            return self.num(_TAG_STRUCT[tag])
        if tag == 7:  # byte array
            return self.take(self.num(">i"))
        if tag == 8:
            return self.string()
        if tag == 9:
            item, n = self.num(">b"), self.num(">i")
            if n < 0 or n > 1 << 20:
                raise PreviewError("a damaged chunk")
            return [self.payload(item, depth + 1) for _ in range(n)]
        if tag == 10:
            out = {}
            while True:
                t = self.num(">b")
                if t == 0:
                    return out
                name = self.string()
                out[name] = self.payload(t, depth + 1)
        if tag == 11:
            n = self.num(">i")
            return struct.unpack(f">{n}i", self.take(4 * n))
        if tag == 12:  # long arrays stay bytes: most are never needed
            return LongArray(self.take(8 * self.num(">i")))
        raise PreviewError("a damaged chunk")


class LongArray(bytes):
    def longs(self) -> tuple[int, ...]:
        return struct.unpack(f">{len(self) // 8}Q", self)


def read_nbt(data: bytes) -> dict:
    """The root compound of uncompressed NBT."""
    r = _Reader(data)
    if r.num(">b") != 10:
        raise PreviewError("not NBT")
    r.string()
    return r.payload(10)


def unpack(longs: tuple[int, ...], bits: int, count: int) -> list[int]:
    """Values packed ``bits`` wide into longs, not spanning longs (Minecraft 1.16+)."""
    per = 64 // bits
    mask = (1 << bits) - 1
    out = []
    for word in longs:
        for i in range(per):
            out.append((word >> (i * bits)) & mask)
            if len(out) == count:
                return out
    return out + [0] * (count - len(out))


# -------------------------------------------------------------------- regions
def region_chunks(path: Path, problems: list | None = None):
    """(chunk x, chunk z, root compound) for each chunk in an .mca region file. Chunks that can't
    be read are skipped (and described in ``problems``, if given)."""
    m = re.fullmatch(r"r\.(-?\d+)\.(-?\d+)\.mca", path.name)
    if not m:
        return
    rx, rz = int(m.group(1)), int(m.group(2))
    data = path.read_bytes()
    if len(data) < 8192:
        return
    for i in range(1024):
        entry = struct.unpack(">I", data[i * 4:i * 4 + 4])[0]
        offset, sectors = entry >> 8, entry & 0xFF
        if not offset or not sectors:
            continue
        start = offset * 4096
        if start + 5 > len(data):
            continue
        length, kind = struct.unpack(">IB", data[start:start + 5])
        raw = data[start + 5:start + 4 + length]
        try:
            if kind == 2:
                raw = zlib.decompress(raw)
            elif kind == 1:
                raw = gzip.decompress(raw)
            elif kind != 3:
                if problems is not None:
                    problems.append(f"a chunk stored with compression {kind}")
                continue  # LZ4 or kept in a separate file: not drawn
            yield rx * 32 + i % 32, rz * 32 + i // 32, read_nbt(raw)
        except (zlib.error, OSError, EOFError, PreviewError, struct.error) as e:
            if problems is not None:
                problems.append(f"{path.name}: {e}")
            log.debug("skipping a damaged chunk in %s", path.name)


def region_folder(world: Path) -> Path:
    """The Overworld's region files (world/region, or world/dimensions/minecraft/overworld/region
    from Minecraft 26.x on)."""
    from .areas import dimension_folder
    return dimension_folder(world) / "region"


def chunks_present(region: Path) -> set[tuple[int, int]]:
    """The chunks a world's region files hold (from their headers: quick, nothing unpacked)."""
    out: set[tuple[int, int]] = set()
    for path in region.glob("r.*.mca") if region.is_dir() else []:
        m = re.fullmatch(r"r\.(-?\d+)\.(-?\d+)\.mca", path.name)
        if not m:
            continue
        with path.open("rb") as f:
            head = f.read(4096)
        rx, rz = int(m.group(1)), int(m.group(2))
        for i in range(len(head) // 4):
            if struct.unpack(">I", head[i * 4:i * 4 + 4])[0]:
                out.add((rx * 32 + i % 32, rz * 32 + i // 32))
    return out


def _heightmap(longs: tuple[int, ...]) -> list[int]:
    for bits in range(1, 17):  # the width follows from the world's height; find it from the length
        if -(-256 // (64 // bits)) == len(longs):
            return unpack(longs, bits, 256)
    return [0] * 256


# ---------------------------------------------------------------------- colours
COLORS = {
    "grass_block": (127, 178, 56), "short_grass": (106, 160, 48), "grass": (106, 160, 48), "tall_grass": (106, 160, 48),
    "fern": (96, 148, 46), "sand": (219, 207, 163), "red_sand": (190, 102, 33), "sandstone": (216, 203, 155),
    "gravel": (136, 126, 122), "stone": (112, 112, 112), "deepslate": (80, 80, 84), "andesite": (130, 130, 130),
    "diorite": (190, 190, 190), "granite": (149, 103, 85), "tuff": (108, 109, 102), "calcite": (223, 224, 220),
    "dirt": (134, 96, 67), "coarse_dirt": (119, 85, 59), "rooted_dirt": (144, 103, 76), "podzol": (91, 63, 24),
    "mycelium": (111, 99, 105), "mud": (60, 57, 61), "clay": (160, 166, 179), "snow": (240, 251, 251),
    "snow_block": (240, 251, 251), "powder_snow": (240, 251, 251), "ice": (145, 183, 253), "packed_ice": (141, 180, 250),
    "blue_ice": (116, 167, 253), "water": (64, 64, 255), "lava": (255, 90, 0), "terracotta": (152, 94, 67),
    "moss_block": (89, 109, 45), "moss_carpet": (89, 109, 45), "mangrove_roots": (74, 59, 38),
    "netherrack": (111, 54, 52), "end_stone": (219, 222, 158), "obsidian": (21, 18, 30), "bedrock": (60, 60, 60),
    "cactus": (85, 127, 43), "pumpkin": (198, 118, 24), "melon": (111, 145, 30), "sugar_cane": (148, 192, 101),
    "lily_pad": (32, 128, 48), "seagrass": (40, 90, 200), "kelp": (40, 90, 200), "kelp_plant": (40, 90, 200),
    "dripstone_block": (134, 107, 92), "pointed_dripstone": (134, 107, 92), "sculk": (13, 18, 23),
    "cobblestone": (122, 122, 122), "mossy_cobblestone": (110, 118, 94), "bamboo": (93, 144, 19),
    "dead_bush": (148, 116, 64), "sweet_berry_bush": (70, 110, 40), "farmland": (114, 76, 50), "dirt_path": (148, 122, 65),
}
KEYWORDS = (  # for blocks not listed (mods' blocks too), by name
    ("water", (64, 64, 255)), ("lava", (255, 90, 0)), ("leaves", (48, 110, 36)), ("snow", (240, 251, 251)),
    ("ice", (145, 183, 253)), ("sand", (219, 207, 163)), ("grass", (127, 178, 56)), ("moss", (89, 109, 45)),
    ("log", (102, 81, 51)), ("wood", (102, 81, 51)), ("stem", (102, 81, 51)), ("planks", (162, 130, 78)),
    ("terracotta", (152, 94, 67)), ("dirt", (134, 96, 67)), ("mud", (60, 57, 61)), ("gravel", (136, 126, 122)),
    ("clay", (160, 166, 179)), ("flower", (180, 120, 170)), ("tulip", (200, 90, 90)), ("mushroom", (160, 60, 50)),
    ("coral", (220, 120, 150)), ("stone", (112, 112, 112)), ("slate", (80, 80, 84)), ("basalt", (80, 80, 90)),
    ("ore", (112, 112, 112)), ("glass", (200, 220, 240)), ("wool", (220, 220, 220)), ("brick", (150, 90, 70)),
)
AIR = {"air", "cave_air", "void_air"}
BACKGROUND = (0, 0, 0, 0)


def color(block: str) -> tuple[int, int, int]:
    name = block.split(":", 1)[-1]
    if name in COLORS:
        return COLORS[name]
    for word, rgb in KEYWORDS:
        if word in name:
            return rgb
    h = hashlib.sha1(name.encode()).digest()  # something unknown: a steady, muted colour
    return (90 + h[0] % 80, 90 + h[1] % 80, 90 + h[2] % 80)


def _shade(rgb, factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * factor))) for c in rgb)


# --------------------------------------------------------------------- the map
def _block_name(entry) -> str:
    """A block palette entry's name. Up to 1.21: {Name, Properties}. Minecraft 26.x: just the
    name, {id, properties}, or, in a list mixing the two, the name wrapped as {"": name}."""
    if isinstance(entry, dict):
        entry = entry.get("Name", entry.get("id", entry.get("")))
    return entry if isinstance(entry, str) and entry else "minecraft:air"


def _section_block(section: dict, x: int, y: int, z: int) -> str:
    states = section.get("block_states") or {}
    palette = states.get("palette") or []
    if not palette:
        return "minecraft:air"
    if len(palette) == 1 or "data" not in states:
        return _block_name(palette[0])
    cached = section.get("_blocks")
    if cached is None:
        bits = max(4, (len(palette) - 1).bit_length())
        cached = section["_blocks"] = unpack(states["data"].longs(), bits, 4096)
    i = cached[(y * 16 + z) * 16 + x]
    return _block_name(palette[i]) if i < len(palette) else "minecraft:air"


def _section_biome(section: dict) -> str:
    biomes = section.get("biomes") or {}
    palette = biomes.get("palette") or []
    if not palette:
        return ""
    if len(palette) == 1 or "data" not in biomes:
        return str(palette[0])
    bits = max(1, (len(palette) - 1).bit_length())
    i = unpack(biomes["data"].longs(), bits, 64)[(2 * 4 + 2) * 4 + 2]  # the chunk's middle
    return str(palette[i]) if i < len(palette) else ""


def spawn_point(world: Path) -> tuple[int, int] | None:
    """The world's spawn (x, z) from level.dat; None if it can't be read."""
    try:
        data = read_nbt(gzip.decompress((world / "level.dat").read_bytes())).get("Data", {})
    except (OSError, PreviewError, EOFError, zlib.error, struct.error):
        return None
    spawn = data.get("spawn")
    if isinstance(spawn, dict):  # Minecraft 1.21.9+: {pos: [x, y, z], dimension, ...}
        pos = spawn.get("pos")
        if isinstance(pos, (list, tuple)) and len(pos) >= 3:
            return int(pos[0]), int(pos[2])
        if all(k in spawn for k in ("x", "z")):
            return int(spawn["x"]), int(spawn["z"])
    if "SpawnX" in data and "SpawnZ" in data:
        return int(data["SpawnX"]), int(data["SpawnZ"])
    return None


def map_center(world: Path, radius: int) -> tuple[tuple[int, int], tuple[int, int] | None]:
    """Where to draw: the spawn when the world has land around it, otherwise the middle of the
    land that was generated (Chunky makes a square around the spawn, wherever that is)."""
    spawn = spawn_point(world)
    present = chunks_present(region_folder(world))
    if not present:
        raise PreviewError("the world has no region files to draw: the server didn't save any land")
    if spawn and (spawn[0] >> 4, spawn[1] >> 4) in present:
        return spawn, spawn
    xs, zs = sorted(c[0] for c in present), sorted(c[1] for c in present)
    middle = (xs[len(xs) // 2] * 16 + 8, zs[len(zs) // 2] * 16 + 8)  # (the median: stray chunks don't pull it)
    log.info("map preview: spawn %s isn't in the generated land; centring on %s", spawn, middle)
    return middle, spawn


class Surface:
    """The ground of one chunk seen from above: per column, its colour, height and whether it's
    water (256 columns, z * 16 + x), and the chunk's biome."""
    __slots__ = ("colors", "heights", "water", "biome")

    def __init__(self):
        self.colors = bytearray(256 * 3)
        self.heights = [None] * 256
        self.water = bytearray(256)
        self.biome = ""


def chunk_surface(root: dict, stats=None) -> Surface | None:
    """A finished chunk's ground (None for one that isn't finished or can't be read). ``stats``
    (a Counter) collects why chunks were left out."""
    def note(why):
        if stats is not None:
            stats[why] += 1
    if "Level" in root and isinstance(root["Level"], dict):  # (the pre-1.18 layout)
        note("old format")
        return None
    status = str(root.get("Status", "")).removeprefix("minecraft:")
    if status != "full":
        note(status or "no status")
        return None
    maps = root.get("Heightmaps") or {}
    if "WORLD_SURFACE" not in maps or not isinstance(maps["WORLD_SURFACE"], LongArray):
        note("full, without a height map")
        return None
    note("full")
    surface = _heightmap(maps["WORLD_SURFACE"].longs())
    floor = _heightmap(maps["OCEAN_FLOOR"].longs()) if isinstance(maps.get("OCEAN_FLOOR"), LongArray) else surface
    min_y = int(root.get("yPos", -4)) * 16
    sections = {int(x.get("Y", 0)): x for x in root.get("sections") or [] if isinstance(x, dict)}
    out = Surface()
    middle = sections.get((min_y + surface[8 * 16 + 8] - 1) >> 4)
    if middle is not None:
        out.biome = _section_biome(middle)
    for i in range(256):
        y = min_y + surface[i] - 1
        section = sections.get(y >> 4)
        block = _section_block(section, i & 15, y & 15, i >> 4) if section else "minecraft:air"
        if block.split(":", 1)[-1] in AIR:
            continue
        rgb = color(block)
        if "water" in block:  # deeper water is darker
            rgb = _shade(rgb, max(0.45, 1.0 - (y - (min_y + floor[i] - 1)) * 0.035))
            out.water[i] = 1
        out.colors[i * 3:i * 3 + 3] = bytes(rgb)
        out.heights[i] = y
    return out


# Landmarks: the structures Minecraft placed (from each chunk's "structures" → "starts"), with a
# name and a symbol for the map. Underground or countless ones (mineshafts, buried treasure) are
# left out; a mod's own structures show with their name.
LANDMARKS = {
    "village": ("Village", "🏠"), "pillager_outpost": ("Pillager outpost", "⚔"), "mansion": ("Woodland mansion", "🏰"),
    "monument": ("Ocean monument", "🔱"), "desert_pyramid": ("Desert temple", "🔺"), "jungle_pyramid": ("Jungle temple", "🌿"),
    "igloo": ("Igloo", "❄"), "swamp_hut": ("Witch hut", "🧹"), "shipwreck": ("Shipwreck", "⚓"), "ocean_ruin": ("Ocean ruins", "🏛"),
    "ruined_portal": ("Ruined portal", "🌀"), "stronghold": ("Stronghold", "👁"), "ancient_city": ("Ancient city", "🕯"),
    "trail_ruins": ("Trail ruins", "🏺"), "trial_chambers": ("Trial chambers", "🗝"),
}
HIDDEN_LANDMARKS = ("mineshaft", "buried_treasure", "nether_fossil", "fortress", "bastion", "end_city")
MAX_LANDMARKS = 500


def landmark_kind(structure: str) -> tuple[str, str, str] | None:
    """(kind, name, symbol) for a structure id like minecraft:village_plains; None to leave out."""
    namespace, _, path = structure.partition(":") if ":" in structure else ("minecraft", "", structure)
    if any(path.startswith(x) for x in HIDDEN_LANDMARKS):
        return None
    for kind, (name, symbol) in LANDMARKS.items():
        if path == kind or path.startswith(kind + "_"):
            return kind, name, symbol
    if namespace == "minecraft":
        return None  # (something new or unusual: not guessed at)
    return path, path.replace("_", " ").replace("/", " ").strip().capitalize()[:40], "📍"


def chunk_landmarks(root: dict) -> list[dict]:
    """The structures that start in this chunk: [{kind, name, symbol, x, z}]."""
    starts = (root.get("structures") or {}).get("starts") if isinstance(root.get("structures"), dict) else None
    out = []
    for key, start in (starts or {}).items() if isinstance(starts, dict) else []:
        if not isinstance(start, dict) or str(start.get("id", "INVALID")) == "INVALID":
            continue
        what = landmark_kind(str(start.get("id") or key))
        if what is None:
            continue
        x = z = None
        for child in start.get("Children") or []:
            bb = child.get("BB") if isinstance(child, dict) else None
            if isinstance(bb, (tuple, list)) and len(bb) == 6:
                x, z = (bb[0] + bb[3]) // 2, (bb[2] + bb[5]) // 2
                break
        if x is None:
            try:
                x, z = int(start["ChunkX"]) * 16 + 8, int(start["ChunkZ"]) * 16 + 8
            except (KeyError, TypeError, ValueError):
                continue
        out.append({"kind": what[0], "name": what[1], "symbol": what[2], "x": int(x), "z": int(z)})
    return out


class Surfaces:
    """The ground of a world's chunks, read from its region files once and kept until a file
    changes (the server can add land while the map is open). Safe to use from several threads."""

    def __init__(self, world: Path):
        self.world = world
        self.regions: dict[tuple[int, int], tuple[tuple[int, int], dict]] = {}
        self.marks: dict[tuple[int, int], list[dict]] = {}  # each region's landmarks (read with its ground)
        self.stats = Counter()
        self.problems: list[str] = []
        self.lock = threading.Lock()

    def region(self, rx: int, rz: int) -> dict:
        path = region_folder(self.world) / f"r.{rx}.{rz}.mca"
        try:
            st = path.stat()
        except OSError:
            return {}
        stamp = (st.st_mtime_ns, st.st_size)
        with self.lock:
            cached = self.regions.get((rx, rz))
            if cached and cached[0] == stamp:
                return cached[1]
            chunks, marks = {}, []
            for cx, cz, root in region_chunks(path, self.problems):
                surface = chunk_surface(root, self.stats)
                if surface is not None:
                    chunks[(cx, cz)] = surface
                try:
                    marks += chunk_landmarks(root)
                except (AttributeError, TypeError, ValueError):
                    pass  # (an odd chunk: no landmarks from it)
            del self.problems[20:]
            self.regions[(rx, rz)] = (stamp, chunks)
            self.marks[(rx, rz)] = marks
            return chunks

    def chunk(self, cx: int, cz: int) -> Surface | None:
        return self.region(cx >> 5, cz >> 5).get((cx, cz))

    def landmarks(self, x0: int | None = None, z0: int | None = None, x1: int | None = None, z1: int | None = None) -> list[dict]:
        """The landmarks in [x0, x1) × [z0, z1) (all the world's without bounds), nearest the middle first."""
        folder = region_folder(self.world)
        keys = [(int(m.group(1)), int(m.group(2))) for p in (folder.glob("r.*.mca") if folder.is_dir() else [])
                if (m := re.fullmatch(r"r\.(-?\d+)\.(-?\d+)\.mca", p.name))]
        if x0 is not None:
            keys = [(rx, rz) for rx, rz in keys if rx * 512 < x1 and (rx + 1) * 512 > x0 and rz * 512 < z1 and (rz + 1) * 512 > z0]
        out = []
        for rx, rz in keys:
            self.region(rx, rz)
            out += [m for m in self.marks.get((rx, rz), [])
                    if x0 is None or (x0 <= m["x"] < x1 and z0 <= m["z"] < z1)]
        mx, mz = ((x0 + x1) / 2, (z0 + z1) / 2) if x0 is not None else (0, 0)
        out.sort(key=lambda m: (m["x"] - mx) ** 2 + (m["z"] - mz) ** 2)
        return out[:MAX_LANDMARKS]


def draw(surfaces: Surfaces, x0: int, z0: int, size: int, scale: int = 1) -> tuple[list, int]:
    """Pixels (rows of RGBA) for ``size`` × ``size`` pixels from block (x0, z0), ``scale`` blocks a
    pixel, north up, with relief as on a Minecraft map; and how many pixels have ground."""
    pixels, painted = [], 0
    above = [None] * size  # the heights of the row to the north
    last_key, last = None, None
    regions: dict[tuple[int, int], dict] = {}  # (read once a drawing: zoomed out, every pixel is another chunk)
    for pz in range(size):
        bz = z0 + pz * scale
        row, heights = [], [None] * size
        for px in range(size):
            bx = x0 + px * scale
            key = (bx >> 4, bz >> 4)
            if key != last_key:
                rkey = (key[0] >> 5, key[1] >> 5)
                if rkey not in regions:
                    regions[rkey] = surfaces.region(*rkey)
                last_key, last = key, regions[rkey].get(key)
            i = (bz & 15) * 16 + (bx & 15)
            if last is None or last.heights[i] is None:
                row.append(BACKGROUND)
                continue
            here = last.heights[i]
            heights[px] = here
            rgb = tuple(last.colors[i * 3:i * 3 + 3])
            north = above[px]
            if north is not None and not last.water[i]:  # lighter going up, darker going down
                rgb = _shade(rgb, 1.12 if here > north else 0.84 if here < north else 1.0)
            row.append((*rgb, 255))
            painted += 1
        pixels.append(row)
        above = heights
    return pixels, painted


def render(world: Path, center: tuple[int, int], radius: int, spawn: tuple[int, int] | None = None,
           surfaces: Surfaces | None = None) -> tuple[bytes, dict]:
    """A PNG of the ground within ``radius`` blocks of ``center`` (one pixel a block, north up),
    and what the page needs: where it is, the spawn and each chunk's biome. Raises PreviewError
    (saying what was found) when there's nothing to draw."""
    surfaces = surfaces or Surfaces(world)
    x0, z0 = center[0] - radius, center[1] - radius
    size = radius * 2
    pixels, painted = draw(surfaces, x0, z0, size)
    cx0, cz0, n = x0 >> 4, z0 >> 4, ((x0 + size - 1) >> 4) - (x0 >> 4) + 1
    biome_names: list[str] = []
    biome_grid = [[-1] * n for _ in range(n)]
    for cz in range(cz0, cz0 + n):
        for cx in range(cx0, cx0 + n):
            c = surfaces.chunk(cx, cz)
            if c is not None and c.biome:
                if c.biome not in biome_names:
                    biome_names.append(c.biome)
                biome_grid[cz - cz0][cx - cx0] = biome_names.index(c.biome)
    if not painted:
        found = ", ".join(f"{k}: {v}" for k, v in surfaces.stats.most_common(5)) or "no chunks in that area"
        what = "came out empty" if surfaces.stats.get("full") else "had nothing that could be drawn"
        raise PreviewError(f"nothing could be drawn around {center[0]}, {center[1]}: the world {what} ({found}"
                           + (f"; {surfaces.problems[0]}" if surfaces.problems else "") + ")")
    log.info("map preview: drew %d pixel(s) around %s (spawn %s)", painted, center, spawn)
    meta = {"x": x0, "z": z0, "size": size, "spawn": {"x": spawn[0], "z": spawn[1]} if spawn else None,
            "biomes": {"names": biome_names, "chunk_x": cx0, "chunk_z": cz0, "grid": biome_grid},
            "landmarks": surfaces.landmarks(x0, z0, x0 + size, z0 + size)}
    return png(pixels), meta


TILE = 256  # a map tile's pixels each way
TILE_SCALES = (1, 2, 4, 8, 16)  # blocks a pixel
EMPTY_PNG = None  # (made on first use)


def tile(surfaces: Surfaces, scale: int, tx: int, tz: int) -> bytes:
    """One square of the explorable map: TILE × TILE pixels at ``scale`` blocks a pixel."""
    global EMPTY_PNG
    if scale not in TILE_SCALES:
        raise PreviewError("that zoom isn't one of the map's")
    span = TILE * scale
    x0, z0 = tx * span, tz * span
    regions = [(rx, rz) for rx in range(x0 >> 9, ((x0 + span - 1) >> 9) + 1)
               for rz in range(z0 >> 9, ((z0 + span - 1) >> 9) + 1)]
    folder = region_folder(surfaces.world)
    if not any((folder / f"r.{rx}.{rz}.mca").is_file() for rx, rz in regions):
        if EMPTY_PNG is None:
            EMPTY_PNG = png([[BACKGROUND]])
        return EMPTY_PNG
    return png(draw(surfaces, x0, z0, TILE, scale)[0])


def png(pixels: list[list[tuple[int, int, int, int]]]) -> bytes:
    """An RGBA PNG (standard library only)."""
    height, width = len(pixels), len(pixels[0]) if pixels else 0
    raw = bytearray()
    for row in pixels:
        raw.append(0)
        for px in row:
            raw.extend(px)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))


# ----------------------------------------------------------- the live map
EXPLORE_MAX = 1024     # the widest square made at once (blocks from the middle)
IDLE_STOP = 5 * 60     # the private server stops after this long without being asked for land


def _new_lines(proc, mark: int) -> list[str]:
    """The server's output since ``mark`` (its line count then)."""
    lines = list(proc.lines)
    return lines[len(lines) - min(len(lines), proc.line_count - mark):]


class MapSession:
    """The last previewed world, kept so its map can be explored: moved around, zoomed out, and
    grown by asking the private server (started again if it stopped) to make more land. The
    server stops by itself after a few minutes of not being asked; the land made stays."""

    def __init__(self, hub, preview_id: str, m, spawn: tuple[int, int] | None):
        self.hub, self.id, self.m = hub, preview_id, m
        self.world = m.server_dir / "world"
        self.surfaces = Surfaces(self.world)
        self.spawn = spawn
        self.proc = None
        self.version = 0          # goes up whenever land is added (the page reloads its tiles)
        self.areas: list[list[int]] = []  # squares made: [x, z, radius]
        self.rate: float | None = None     # chunks a second, measured
        self.job: dict | None = None       # the land being made: {state, step, progress, ...}
        self.last_used = time.monotonic()
        self.cancel = threading.Event()
        self.lock = threading.Lock()
        self.closed = False
        threading.Thread(target=self._watch, daemon=True, name=f"map:{preview_id}").start()

    def to_dict(self) -> dict:
        folder = region_folder(self.world)
        return {"id": self.id, "version": self.version, "areas": self.areas, "spawn": self.spawn,
                "landmarks": self.landmarks(),
                "rate": self.rate, "running": bool(self.proc and self.proc.running), "job": self.job,
                "regions": sorted([int(m.group(1)), int(m.group(2))] for p in folder.glob("r.*.mca")
                                  if (m := re.fullmatch(r"r\.(-?\d+)\.(-?\d+)\.mca", p.name)))
                if folder.is_dir() else []}

    def landmarks(self) -> list[dict]:
        """The world's landmarks, read again only when land was added (not while it's being made:
        the page asks every couple of seconds then, and the region files keep changing)."""
        cached = getattr(self, "_marks", None)
        if cached is None or cached[0] != self.version:
            self._marks = (self.version, self.surfaces.landmarks())
        return self._marks[1]

    def generate(self, center: tuple[int, int] | None, radius: int, report=None) -> None:
        """Make the land in a square (``center`` None: around the spawn), waiting until it's saved.
        ``report(step, progress)`` hears how it's going."""
        from . import worldtools
        report = report or (lambda step, progress: None)
        self.last_used = time.monotonic()
        if not (self.proc and self.proc.running):
            report("Starting a private server to make the world…", None)
            self.proc = self.m.start_server()
        proc = self.proc
        report("Making the world…", 0.0)
        mark = proc.line_count
        started = time.monotonic()
        where = "chunky spawn" if center is None else f"chunky center {center[0]} {center[1]}"
        for command in (where, f"chunky radius {radius}", "chunky start", "chunky confirm"):
            proc.send(command)
        deadline = started + GENERATE_TIMEOUT
        while time.monotonic() < deadline:
            if self.cancel.is_set():
                proc.send("chunky cancel")
                raise InterruptedError
            if not proc.running:
                from .diagnose import diagnose
                blame = diagnose(proc.tail(400), self.m.server_dir, self.m.lock.mods, since=started).summary
                raise PreviewError("the server stopped while making the world" +
                                   (f". {blame}" if blame else ": " + " / ".join(proc.tail(3))))
            lines = _new_lines(proc, mark)
            if any(worldtools._CHUNKY_DONE.search(line) for line in lines):
                break
            p = worldtools.chunky_progress(lines)
            if p and p.get("percent") is not None:
                report("Making the world…", min(1.0, float(p["percent"]) / 100))
            time.sleep(1)
        else:
            raise PreviewError("making the world took too long; try a smaller area")
        report("Saving the world…", None)
        proc.ask("save-all flush", lambda ls: True if any("Saved the game" in x for x in ls) else None, timeout=60)
        chunks = (2 * radius // 16 + 1) ** 2
        took = max(1.0, time.monotonic() - started)
        self.rate = round(chunks / took, 1)
        self.last_used = time.monotonic()

    def explore(self, x: int, z: int, radius: int) -> dict:
        """Make more land around (x, z), in the background; the page polls :meth:`to_dict`."""
        if not (16 <= radius <= EXPLORE_MAX):
            raise PreviewError(f"make at most {EXPLORE_MAX} blocks each way from the middle at a time")
        if max(abs(x), abs(z)) > 29_000_000:
            raise PreviewError("that's outside the world")
        with self.lock:
            if self.closed:
                raise PreviewError("this map's world is gone; preview it again")
            if self.job and self.job["state"] == "running":
                raise PreviewError("the map is already being made bigger; wait for it or stop it")
            self.cancel.clear()
            self.job = {"state": "running", "step": "Getting ready…", "progress": None, "x": x, "z": z,
                        "radius": radius, "started": time.time(), "error": ""}

        def run():
            def report(step, progress):
                self.job.update(step=step, progress=progress)
            try:
                self.generate((x, z), radius, report)
                self.areas.append([x, z, radius])
                self.version += 1
                self.job.update(state="done", step="Done", progress=None)
            except InterruptedError:
                self.job.update(state="cancelled", step="Stopped", progress=None)
            except Exception as e:
                if not isinstance(e, (PreviewError, OSError, RuntimeError)):
                    log.exception("making more of the map failed")
                self.job.update(state="failed", step="Failed", error=str(e).splitlines()[0][:300] if str(e) else repr(e))
        threading.Thread(target=run, daemon=True, name=f"map-explore:{self.id}").start()
        return self.job

    def stop_server(self) -> None:
        proc, self.proc = self.proc, None
        if proc and proc.running:
            try:
                proc.stop(self.m.config.server.stop_timeout)
            except Exception:
                log.exception("couldn't stop the map's server")

    def close(self) -> None:
        """Stop for good (a new preview replaces this world, or craft-conductor quits)."""
        with self.lock:
            self.closed = True
        self.cancel.set()
        self.stop_server()

    def _watch(self) -> None:
        while not self.closed:
            time.sleep(15)
            busy = self.job and self.job["state"] == "running"
            if self.proc and not busy and time.monotonic() - self.last_used > IDLE_STOP:
                log.info("the map's private server wasn't needed for a while: stopping it")
                self.stop_server()


# --------------------------------------------------------------------- the job
def downloading_step(plan) -> str:
    """What the preview is downloading, the mods the picked ones need included."""
    def names(mods):
        shown = [m.name for m in mods[:6]]
        return ", ".join(shown) + (f" and {len(mods) - 6} more" if len(mods) > 6 else "")
    own = [m for m in plan.mods if not m.dependency_of]
    needed = [m for m in plan.mods if m.dependency_of]
    return (f"Downloading Minecraft {plan.minecraft} and {len(plan.mods)} mod(s): {names(own)}"
            + (f"; needed by them: {names(needed)}" if needed else "") + "…")


class Preview:
    """One map preview, run in the background; the page polls :meth:`to_dict`."""

    def __init__(self, hub, loader: str, minecraft: str, mods: list[ModSpec], seed: str, level_type: str,
                 structures: bool, radius: int, java_from: Path | None = None):
        if not SEED.fullmatch(seed):
            raise PreviewError("the seed can be up to 64 letters, numbers or symbols")
        if level_type not in LEVEL_TYPES:
            raise PreviewError("pick one of the world types")
        if radius not in SIZES:
            raise PreviewError("pick one of the map sizes")
        if minecraft != "latest" and not supports(minecraft):
            raise PreviewError("map previews need Minecraft 1.18 or newer")
        self.id = secrets.token_hex(6)
        self.hub = hub
        # Vanilla has nowhere to put Chunky; Fabric generates exactly the same worlds.
        self.loader = "fabric" if loader == "vanilla" else loader
        self.minecraft, self.mods = minecraft, mods
        self.seed = seed.strip() or random_seed()
        self.level_type, self.structures, self.radius = level_type, structures, radius
        self.java_from = java_from
        self.state, self.step, self.progress = "running", "Getting ready…", None
        self.error = ""
        self.meta: dict | None = None
        self.cancel = threading.Event()
        self.started = time.time()
        self.thread = threading.Thread(target=self._run, daemon=True, name=f"preview:{self.id}")

    # (where the maps and the reusable throwaway server live)
    @staticmethod
    def folder(hub) -> Path:
        return hub.state_dir / "previews"

    @property
    def map_path(self) -> Path:
        return self.folder(self.hub) / f"{self.id}.png"

    def start(self) -> "Preview":
        self.thread.start()
        return self

    def to_dict(self) -> dict:
        return {"id": self.id, "state": self.state, "step": self.step, "progress": self.progress, "error": self.error,
                "seed": self.seed, "level_type": self.level_type, "structures": self.structures, "radius": self.radius,
                "loader": self.loader, "minecraft": self.minecraft, "mods": [m.id for m in self.mods],
                "map": self.meta, "elapsed": int(time.time() - self.started)}

    def _check(self) -> None:
        if self.cancel.is_set():
            raise InterruptedError

    def fingerprint(self) -> str:
        mods = sorted(f"{m.source}:{m.id}:{m.channel or ''}" for m in self.mods)
        return hashlib.sha256(repr((self.loader, self.minecraft, mods)).encode()).hexdigest()[:16]

    def _share_java(self, m) -> None:
        """Java that a server already downloaded, used as it is (not fetched again)."""
        if self.java_from and self.java_from.is_dir():
            m.java.shared = self.java_from

    def _server(self):
        """The throwaway server with these mods (and Chunky), made or reused; its world removed."""
        base = self.folder(self.hub) / "server"
        mark = base / ".craft-conductor-preview"
        if mark.is_file() and mark.read_text() == self.fingerprint():
            m = self.hub.make_manager(configmod.load(base))
            self._share_java(m)
            shutil.rmtree(m.server_dir / "world", ignore_errors=True)
        else:
            shutil.rmtree(base, ignore_errors=True)
            spec = setupmod.SetupSpec.from_dict({
                "loader": self.loader, "minecraft": self.minecraft, "motd": "Craft Conductor map preview", "accept_eula": True,
                "memory_gb": 2, "port": self.hub.free_port(25590)})
            spec.mods = []
            setupmod.configure(base, spec)
            path = base / configmod.CONFIG_NAME
            configmod.set_value(path, "backups", "keep", "0")
            extra = [CHUNKY]
            if self.loader in ("fabric", "quilt") and not any(x.id == "fabric-api" for x in self.mods):
                extra.insert(0, ModSpec("modrinth", "fabric-api"))  # Chunky (and most Fabric mods) need it
            for s in [*self.mods, *extra]:
                configmod.append_mod(path, ModSpec(s.source, s.id, required=True, channel=s.channel))
            m = self.hub.make_manager(configmod.load(base))
            self._share_java(m)
            self.step = "Downloading Minecraft and the mods…"
            decision, _ = m.check(retry_failed=True)
            if decision.plan is None:
                blocked = decision.blocked[0] if decision.blocked else None
                why = "; ".join(f"{b.name}: {b.reason}" for b in blocked.blockers) if blocked else "nothing to install"
                raise PreviewError(f"these mods can't be installed together: {why}")
            if not supports(decision.plan.minecraft):
                raise PreviewError(f"map previews need Minecraft 1.18 or newer (this is {decision.plan.minecraft})")
            self.step = downloading_step(decision.plan)
            self._check()
            result = m.apply(decision.plan, verify=False)
            if not result.ok:
                raise PreviewError(result.message.splitlines()[0])
            mark.write_text(self.fingerprint())
        from .properties import write_properties
        write_properties(m.server_dir / "server.properties", {
            "level-seed": self.seed, "level-type": self.level_type, "generate-structures": str(self.structures).lower(),
            "server-ip": "127.0.0.1",  # nobody else can join it
            "server-port": str(self.hub.free_port(25590)),
            "view-distance": "3", "simulation-distance": "3", "spawn-protection": "0", "online-mode": "false",
            "max-players": "1", "enable-query": "false", "enable-rcon": "false"})
        return m

    def _generate(self, m) -> Path:
        """Make the land around the spawn (the map session keeps the server running). The world folder."""
        def report(step, progress):
            self._check()
            self.step, self.progress = step, progress
        self.session = MapSession(self.hub, self.id, m, None)
        self.session.generate(None, self.radius, report)
        return m.server_dir / "world"

    def _run(self) -> None:
        old = getattr(self.hub, "map_session", None)
        if old is not None:  # its world is about to be replaced
            old.close()
            self.hub.map_session = None
        try:
            m = self._server()
            self._check()
            world = self._generate(m)
            self.step = "Drawing the map…"
            center, spawn = map_center(world, self.radius)
            session = getattr(self, "session", None) or MapSession(self.hub, self.id, m, spawn)
            session.spawn, session.areas = spawn, [[center[0], center[1], self.radius]]
            image, meta = render(world, center, self.radius, spawn, session.surfaces)
            self.folder(self.hub).mkdir(parents=True, exist_ok=True)
            self.map_path.write_bytes(image)
            self.meta = meta
            self.hub.map_session = session
            self.step, self.state = "Done", "done"
            self._forget_old_maps()
        except InterruptedError:
            self._drop_session()
            self.step, self.state = "Stopped", "cancelled"
        except Exception as e:
            self._drop_session()
            if not isinstance(e, (PreviewError, OSError, RuntimeError)):
                log.exception("map preview failed")
            from .diagnose import headline
            self.error = headline(str(e)) or repr(e)
            self.step, self.state = "Failed", "failed"
            self._keep_log()
            shutil.rmtree(self.folder(self.hub) / "server", ignore_errors=True)  # start clean next time

    def _keep_log(self) -> None:
        """The failed server's log, kept (as previews/last-failed.log) when its server is removed."""
        server = self.folder(self.hub) / "server"
        for log_file in server.glob("*/logs/latest.log"):
            try:
                shutil.copyfile(log_file, self.folder(self.hub) / "last-failed.log")
                log.info("map preview failed: its server's log is kept in %s", self.folder(self.hub) / "last-failed.log")
            except OSError:
                pass
            break

    def _drop_session(self) -> None:
        session = getattr(self, "session", None)
        if session is not None:
            session.close()

    def _forget_old_maps(self) -> None:
        maps = sorted(self.folder(self.hub).glob("*.png"), key=lambda p: p.stat().st_mtime)
        for p in maps[:-KEEP]:
            p.unlink(missing_ok=True)


def image(hub, preview_id: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{12}", preview_id or ""):
        raise PreviewError("no such map")
    path = Preview.folder(hub) / f"{preview_id}.png"
    if not path.is_file():
        raise PreviewError("no such map")
    return path.read_bytes()


def clean(hub) -> None:
    """At start: nothing from last time is needed (maps and the throwaway server)."""
    shutil.rmtree(Preview.folder(hub), ignore_errors=True)



# --------------------------------------------------------------- seed gallery
GALLERY_MAX = 10


class Gallery:
    """Maps of several random seeds, one after another, to pick the one with the features you're
    after. Each is an ordinary :class:`Preview` (kept in ``hub.previews``, so its map is fetched and
    explored like any other); the private server with the mods is installed once and reused."""

    def __init__(self, hub, count: int, **params):
        if not 2 <= count <= GALLERY_MAX:
            raise PreviewError(f"compare 2 to {GALLERY_MAX} seeds")
        Preview(hub, seed="", **params)  # (checks the settings now, rather than in the background)
        self.id = secrets.token_hex(6)
        self.hub, self.count, self.params = hub, count, params
        self.state, self.error = "running", ""
        self.done: list[dict] = []
        self.failed = 0
        self.current: Preview | None = None
        self.cancel = threading.Event()
        self.started = time.time()

    def start(self) -> "Gallery":
        threading.Thread(target=self.run, daemon=True, name=f"gallery:{self.id}").start()
        return self

    def to_dict(self) -> dict:
        cur = self.current.to_dict() if self.current is not None and self.current.state == "running" else None
        return {"id": self.id, "state": self.state, "error": self.error, "count": self.count,
                "index": len(self.done) + self.failed + (1 if cur else 0), "current": cur, "maps": self.done,
                "failed": self.failed, "elapsed": int(time.time() - self.started)}

    def run(self) -> None:
        try:
            for _ in range(self.count):
                if self.cancel.is_set():
                    break
                p = Preview(self.hub, seed="", **self.params)
                self.current = p
                self.hub.previews[p.id] = p
                watcher = threading.Thread(target=lambda: (self.cancel.wait(), p.cancel.set()), daemon=True)
                watcher.start()
                p._run()
                if p.state == "done":
                    self.done.append(p.to_dict())
                elif p.state == "failed":
                    self.failed += 1
                    if not self.done:  # the first one failing means they all would (the mods, Java...)
                        raise PreviewError(p.error or "the map couldn't be made")
            self.state = "cancelled" if self.cancel.is_set() else "done"
        except Exception as e:
            self.error = str(e).splitlines()[0][:400] if str(e) else repr(e)
            self.state = "failed"
        finally:
            self.cancel.set()  # (lets the watcher threads end)
            self.current = None
