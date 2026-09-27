"""See a world before you make it: a map of a seed, with the server's world-generation mods.

Only Minecraft itself knows what a seed makes (and world-generation mods change it), so a
preview is made the honest way: a throwaway server with the new server's Minecraft, loader
and mods, plus the Chunky mod, generates the area around spawn; then mcsm reads the world's
region files and draws the ground seen from above, like a Minecraft map (with the biome of
each chunk for the page to show on hover). The throwaway server listens only on this
computer, and is kept between previews with the same mods (a new seed only needs a new
world), then deleted.

Maps need Minecraft 1.18 or newer (the region format mcsm reads).
"""

from __future__ import annotations

import gzip
import hashlib
import logging
import os
import re
import secrets
import shutil
import struct
import threading
import time
import zlib
from pathlib import Path

from . import config as configmod, setup as setupmod
from .config import ModSpec

log = logging.getLogger(__name__)

SIZES = (128, 256, 512)  # radius in blocks: the map is twice that across
LEVEL_TYPES = ("minecraft:normal", "minecraft:large_biomes", "minecraft:amplified", "minecraft:flat",
               "minecraft:single_biome_surface")
SEED = re.compile(r"[^\x00-\x1f\x7f]{0,64}")
GENERATE_TIMEOUT = 20 * 60
KEEP = 12  # maps kept for the page's "earlier previews"
CHUNKY = ModSpec("modrinth", "chunky")


class PreviewError(ValueError):
    pass


def random_seed() -> str:
    return str(secrets.randbits(63) * (1 if secrets.randbits(1) else -1))


def _version_key(v: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", v)[:3])


def supports(minecraft: str) -> bool:
    """Whether mcsm can draw maps of this Minecraft's worlds (1.18+; snapshots count as new)."""
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
def _section_block(section: dict, x: int, y: int, z: int) -> str:
    states = section.get("block_states") or {}
    palette = states.get("palette") or []
    if not palette:
        return "minecraft:air"
    if len(palette) == 1 or "data" not in states:
        return str(palette[0].get("Name", "minecraft:air"))
    cached = section.get("_blocks")
    if cached is None:
        bits = max(4, (len(palette) - 1).bit_length())
        cached = section["_blocks"] = unpack(states["data"].longs(), bits, 4096)
    i = cached[(y * 16 + z) * 16 + x]
    return str(palette[i].get("Name", "minecraft:air")) if i < len(palette) else "minecraft:air"


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
    present = chunks_present(world / "region")
    if not present:
        raise PreviewError("the world has no region files to draw: the server didn't save any land")
    if spawn and (spawn[0] >> 4, spawn[1] >> 4) in present:
        return spawn, spawn
    xs, zs = sorted(c[0] for c in present), sorted(c[1] for c in present)
    middle = (xs[len(xs) // 2] * 16 + 8, zs[len(zs) // 2] * 16 + 8)  # (the median: stray chunks don't pull it)
    log.info("map preview: spawn %s isn't in the generated land; centring on %s", spawn, middle)
    return middle, spawn


def render(world: Path, center: tuple[int, int], radius: int, spawn: tuple[int, int] | None = None) -> tuple[bytes, dict]:
    """A PNG of the ground within ``radius`` blocks of ``center`` (one pixel a block, north up),
    and what the page needs: where it is, the spawn and each chunk's biome. Raises PreviewError
    (saying what was found) when there's nothing to draw."""
    from collections import Counter
    problems: list[str] = []
    statuses: Counter = Counter()
    drawn = painted = 0
    sample = ""  # (what the first chunk looked like, for the error when nothing shows)
    x0, z0 = center[0] - radius, center[1] - radius
    size = radius * 2
    pixels = [[BACKGROUND] * size for _ in range(size)]
    heights = [[None] * size for _ in range(size)]
    water = [[False] * size for _ in range(size)]
    cx0, cz0, n = x0 >> 4, z0 >> 4, ((x0 + size - 1) >> 4) - (x0 >> 4) + 1
    biome_names: list[str] = []
    biome_grid = [[-1] * n for _ in range(n)]
    region = world / "region"
    wanted = {(rx, rz) for rx in range(x0 >> 9, (x0 + size - 1 >> 9) + 1) for rz in range(z0 >> 9, (z0 + size - 1 >> 9) + 1)}
    for rx, rz in sorted(wanted):
        path = region / f"r.{rx}.{rz}.mca"
        if not path.is_file():
            continue
        for cx, cz, root in region_chunks(path, problems):
            if not (cx0 <= cx < cx0 + n and cz0 <= cz < cz0 + n):
                continue
            if "Level" in root and isinstance(root["Level"], dict):  # (the pre-1.18 layout)
                statuses["old format"] += 1
                continue
            status = str(root.get("Status", "")).removeprefix("minecraft:")
            statuses[status or "no status"] += 1
            if status != "full":
                continue
            maps = root.get("Heightmaps") or {}
            if "WORLD_SURFACE" not in maps or not isinstance(maps["WORLD_SURFACE"], LongArray):
                statuses["full, without a height map"] += 1
                continue
            drawn += 1
            surface = _heightmap(maps["WORLD_SURFACE"].longs())
            if not sample:
                sample = (f"height map of {len(maps['WORLD_SURFACE']) // 8} longs, yPos {root.get('yPos')}, sections "
                          f"{sorted(int(x.get('Y', 0)) for x in root.get('sections') or [] if isinstance(x, dict))}")
            floor = _heightmap(maps["OCEAN_FLOOR"].longs()) if "OCEAN_FLOOR" in maps else surface
            min_y = int(root.get("yPos", -4)) * 16
            sections = {int(s.get("Y", 0)): s for s in root.get("sections") or [] if isinstance(s, dict)}
            middle = sections.get((min_y + surface[8 * 16 + 8] - 1) >> 4)
            if middle is not None:
                name = _section_biome(middle)
                if name:
                    if name not in biome_names:
                        biome_names.append(name)
                    biome_grid[cz - cz0][cx - cx0] = biome_names.index(name)
            for lz in range(16):
                pz = cz * 16 + lz - z0
                if not 0 <= pz < size:
                    continue
                for lx in range(16):
                    px = cx * 16 + lx - x0
                    if not 0 <= px < size:
                        continue
                    y = min_y + surface[lz * 16 + lx] - 1
                    section = sections.get(y >> 4)
                    block = _section_block(section, lx, y & 15, lz) if section else "minecraft:air"
                    if block.split(":", 1)[-1] in AIR:
                        continue
                    rgb = color(block)
                    if "water" in block:  # deeper water is darker
                        depth = y - (min_y + floor[lz * 16 + lx] - 1)
                        rgb = _shade(rgb, max(0.45, 1.0 - depth * 0.035))
                        water[pz][px] = True
                    heights[pz][px] = y
                    pixels[pz][px] = rgb
                    painted += 1
    # Relief, as on a Minecraft map: lighter where the ground rises going south, darker where it falls.
    for pz in range(size):
        for px in range(size):
            here = heights[pz][px]
            if here is None:
                continue
            north = heights[pz - 1][px] if pz else None
            rgb = pixels[pz][px]
            if north is not None and not water[pz][px]:
                factor = 1.12 if here > north else 0.84 if here < north else 1.0
                rgb = _shade(rgb, factor)
            pixels[pz][px] = (*rgb, 255)
    if not drawn:
        found = ", ".join(f"{k}: {v}" for k, v in statuses.most_common(5)) or "no chunks in that area"
        raise PreviewError(f"nothing could be drawn around {center[0]}, {center[1]} ({found}"
                           + (f"; {problems[0]}" if problems else "") + ")")
    if not painted:
        raise PreviewError(f"the world's {drawn} chunk(s) around {center[0]}, {center[1]} came out empty ({sample})")
    log.info("map preview: drew %d chunk(s) around %s (spawn %s)", drawn, center, spawn)
    meta = {"x": x0, "z": z0, "size": size, "spawn": {"x": spawn[0], "z": spawn[1]} if spawn else None,
            "biomes": {"names": biome_names, "chunk_x": cx0, "chunk_z": cz0, "grid": biome_grid}}
    return png(pixels), meta


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


# --------------------------------------------------------------------- the job
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

    def _server(self):
        """The throwaway server with these mods (and Chunky), made or reused; its world removed."""
        base = self.folder(self.hub) / "server"
        mark = base / ".mcsm-preview"
        if mark.is_file() and mark.read_text() == self.fingerprint():
            m = self.hub.make_manager(configmod.load(base))
            shutil.rmtree(m.server_dir / "world", ignore_errors=True)
        else:
            shutil.rmtree(base, ignore_errors=True)
            spec = setupmod.SetupSpec.from_dict({
                "loader": self.loader, "minecraft": self.minecraft, "motd": "mcsm map preview", "accept_eula": True,
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
            if self.java_from and self.java_from.is_dir():  # reuse Java that's already downloaded
                target = base / configmod.STATE_DIR / "java"
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.symlink(self.java_from, target, target_is_directory=True)
                except OSError:
                    pass
            m = self.hub.make_manager(configmod.load(base))
            self.step = "Downloading Minecraft and the mods…"
            decision, _ = m.check(retry_failed=True)
            if decision.plan is None:
                blocked = decision.blocked[0] if decision.blocked else None
                why = "; ".join(f"{b.name}: {b.reason}" for b in blocked.blockers) if blocked else "nothing to install"
                raise PreviewError(f"these mods can't be installed together: {why}")
            if not supports(decision.plan.minecraft):
                raise PreviewError(f"map previews need Minecraft 1.18 or newer (this is {decision.plan.minecraft})")
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
        """Start the server, have Chunky generate the map's area, save and stop. The world folder."""
        from . import worldtools
        self.step = "Starting a private server to make the world…"
        proc = m.start_server()
        try:
            self._check()
            self.step, self.progress = "Making the world…", 0.0
            for command in ("chunky spawn", f"chunky radius {self.radius}", "chunky start", "chunky confirm"):
                proc.send(command)
            deadline = time.monotonic() + GENERATE_TIMEOUT
            while time.monotonic() < deadline:
                self._check()
                if not proc.running:
                    raise PreviewError("the server stopped while making the world: " + " / ".join(proc.tail(3)))
                lines = proc.tail(80)
                if any(worldtools._CHUNKY_DONE.search(line) for line in lines):
                    break
                p = worldtools.chunky_progress(lines)
                if p and p.get("percent") is not None:
                    self.progress = min(1.0, float(p["percent"]) / 100)
                time.sleep(1)
            else:
                raise PreviewError("making the world took too long; try a smaller map")
            self.step, self.progress = "Saving the world…", None
            proc.ask("save-all flush", lambda ls: True if any("Saved the game" in x for x in ls) else None, timeout=60)
        finally:
            proc.stop(m.config.server.stop_timeout)
        return m.server_dir / "world"

    def _run(self) -> None:
        try:
            m = self._server()
            self._check()
            world = self._generate(m)
            self.step = "Drawing the map…"
            center, spawn = map_center(world, self.radius)
            image, meta = render(world, center, self.radius, spawn)
            self.folder(self.hub).mkdir(parents=True, exist_ok=True)
            self.map_path.write_bytes(image)
            self.meta = meta
            self.step, self.state = "Done", "done"
            self._forget_old_maps()
        except InterruptedError:
            self.step, self.state = "Stopped", "cancelled"
        except Exception as e:
            if not isinstance(e, (PreviewError, OSError, RuntimeError)):
                log.exception("map preview failed")
            self.error = str(e).splitlines()[0][:400] if str(e) else repr(e)
            self.step, self.state = "Failed", "failed"
            shutil.rmtree(self.folder(self.hub) / "server", ignore_errors=True)  # start clean next time

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

