"use strict";
// The demo's worlds: map previews of a seed and the explorable map, drawn here from a made-up
// world (smooth noise from the seed, not Minecraft's generator: the real app has a throwaway
// server make the world and reads it). Landmarks are placed from the seed too, and are only
// shown when the visitor asks (the page warns that they give away what players would explore).
// Also the modded single-player games' checks.
(function () {
  const sim = window.CCSim;
  const { ApiError } = sim;
  const cat = () => sim.catalog;

  // ------------------------------------------------------------- the made-up world
  const seedNumber = (seed) => { let h = 2166136261; for (const ch of String(seed)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619) >>> 0; return h || 1; };
  const hash2 = (x, z, s) => { let h = Math.imul(x, 374761393) + Math.imul(z, 668265263) + Math.imul(s, 2147483647); h = Math.imul(h ^ (h >>> 13), 1274126177); return ((h ^ (h >>> 16)) >>> 0) / 4294967296; };
  const smooth = (t) => t * t * (3 - 2 * t);
  const noise = (x, z, s) => {
    const xi = Math.floor(x), zi = Math.floor(z), xf = x - xi, zf = z - zi;
    const a = hash2(xi, zi, s), b = hash2(xi + 1, zi, s), c = hash2(xi, zi + 1, s), d = hash2(xi + 1, zi + 1, s);
    const u = smooth(xf), v = smooth(zf);
    return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
  };
  const fbm = (x, z, s, octaves = 4) => { let sum = 0, amp = 1, f = 1, norm = 0; for (let i = 0; i < octaves; i++) { sum += noise(x * f, z * f, s + i * 977) * amp; norm += amp; amp *= 0.5; f *= 2; } return sum / norm; };
  const flat = (p) => p.level_type === "minecraft:flat";
  // The ground at (x, z): height 0..1, and the biome.
  const BIOMES = { ocean: [44, 80, 160], deep_ocean: [30, 58, 128], beach: [222, 210, 150], plains: [120, 172, 72], forest: [64, 128, 52], birch_forest: [96, 150, 70],
    desert: [216, 196, 128], snowy_plains: [236, 240, 244], taiga: [70, 110, 80], jagged_peaks: [150, 150, 156], swamp: [80, 104, 60], river: [56, 96, 176], savanna: [170, 168, 90],
    cherry_grove: [232, 170, 200], badlands: [196, 112, 60] };
  sim.BIOMES = BIOMES;
  const ground = (p, x, z) => {
    const s = seedNumber(p.seed);
    if (flat(p)) return { h: 0.5, biome: "plains" };
    const big = p.level_type === "minecraft:large_biomes" ? 4 : 1;
    const h = fbm(x / (420 * big), z / (420 * big), s);
    const temp = fbm(x / (900 * big) + 50, z / (900 * big) - 40, s + 31, 2);
    const wet = fbm(x / (700 * big) - 80, z / (700 * big) + 20, s + 77, 2);
    const river = Math.abs(fbm(x / 300, z / 300, s + 191, 3) - 0.5) < 0.012 && h > 0.43 && h < 0.7;
    if (p.level_type === "minecraft:single_biome_surface") return { h: Math.max(0.46, h), biome: "plains" };
    const amp = p.level_type === "minecraft:amplified" ? 1.25 : 1;
    const hh = 0.5 + (h - 0.5) * amp;
    if (hh < 0.36) return { h: hh, biome: "deep_ocean" };
    if (hh < 0.44) return { h: hh, biome: "ocean" };
    if (hh < 0.455) return { h: hh, biome: "beach" };
    if (river) return { h: hh, biome: "river" };
    if (hh > 0.7) return { h: hh, biome: temp < 0.45 ? "jagged_peaks" : "taiga" };
    if (temp > 0.62) return { h: hh, biome: wet < 0.42 ? (temp > 0.68 ? "badlands" : "desert") : "savanna" };
    if (temp < 0.38) return { h: hh, biome: wet > 0.5 ? "taiga" : "snowy_plains" };
    if (wet > 0.62) return { h: hh, biome: "swamp" };
    if (wet > 0.52) return { h: hh, biome: hash2(Math.floor(x / 64), Math.floor(z / 64), s) > 0.85 ? "cherry_grove" : "forest" };
    if (wet > 0.46) return { h: hh, biome: "birch_forest" };
    return { h: hh, biome: "plains" };
  };
  // A block's colour seen from above, like a Minecraft map: the biome's, shaded by the slope (light from
  // the north-west), with trees in forests and a little grain.
  const TREES = { forest: 0.55, birch_forest: 0.62, taiga: 0.6, cherry_grove: 0.6, swamp: 0.7, savanna: 0.88, jagged_peaks: 2, plains: 0.97 };
  const colour = (p, x, z) => {
    const g = ground(p, x, z);
    let [r, gr, b] = BIOMES[g.biome];
    const water = ["ocean", "deep_ocean", "river"].includes(g.biome);
    if (water) {
      const shade = 0.82 + Math.max(0, g.h - 0.3) * 0.9 + (hash2(x >> 1, z >> 1, 11) - 0.5) * 0.04;
      return [Math.min(255, r * shade), Math.min(255, gr * shade), Math.min(255, b * shade)];
    }
    const s = seedNumber(p.seed);
    const slope = (ground(p, x - 3, z - 3).h - g.h) * 9;  // (higher to the north-west: in shadow)
    let shade = 0.9 + Math.min(0.2, (g.h - 0.45) * 0.8) - slope + (hash2(x, z, 9) - 0.5) * 0.07;
    const tree = TREES[g.biome];
    if (tree && hash2(x >> 1, z >> 1, s + 17) > tree) { shade *= 0.72; if (g.biome !== "cherry_grove") { r *= 0.8; b *= 0.85; } }
    shade = Math.max(0.55, Math.min(1.25, shade));
    return [Math.min(255, r * shade), Math.min(255, gr * shade), Math.min(255, b * shade)];
  };
  const biomeLabel = (b) => "minecraft:" + b;
  sim.biomeAt = (p, x, z) => sim.made(p, x, z) ? biomeLabel(ground(p, x, z).biome) : "";
  // What's been made: the first map's square and each "make more" since.
  const areas = (p) => [[0, 0, p.radius], ...(p.areas || [])];
  sim.made = (p, x, z) => areas(p).some(([ax, az, r]) => Math.abs(x - ax) <= r && Math.abs(z - az) <= r);
  sim.mapRegions = (p) => {
    const out = new Set();
    for (const [ax, az, r] of areas(p)) for (let rx = Math.floor((ax - r) / 512); rx <= Math.floor((ax + r) / 512); rx++) for (let rz = Math.floor((az - r) / 512); rz <= Math.floor((az + r) / 512); rz++) out.add(`${rx},${rz}`);
    return [...out].map((x) => x.split(",").map(Number)).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  };
  sim.mapMeta = (p) => {
    const size = p.radius * 2, x0 = -p.radius, z0 = -p.radius;
    const cx0 = x0 >> 4, cz0 = z0 >> 4, n = ((x0 + size - 1) >> 4) - cx0 + 1;
    const names = [];
    const grid = [];
    for (let cz = 0; cz < n; cz++) {
      const row = [];
      for (let cx = 0; cx < n; cx++) {
        const b = biomeLabel(ground(p, (cx0 + cx) * 16 + 8, (cz0 + cz) * 16 + 8).biome);
        if (!names.includes(b)) names.push(b);
        row.push(names.indexOf(b));
      }
      grid.push(row);
    }
    return { x: x0, z: z0, size, spawn: { x: 0, z: 0 }, biomes: { names, chunk_x: cx0, chunk_z: cz0, grid } };
  };
  // Landmarks: a village every so often on plains and deserts, temples, ruined portals, shipwrecks...
  sim.landmarks = (p) => {
    const s = seedNumber(p.seed);
    const out = [];
    const L = { village: ["Village", "🏠"], pillager_outpost: ["Pillager outpost", "⚔"], desert_pyramid: ["Desert temple", "🔺"], igloo: ["Igloo", "❄"],
      swamp_hut: ["Witch hut", "🧹"], shipwreck: ["Shipwreck", "⚓"], ocean_ruin: ["Ocean ruins", "🏛"], ruined_portal: ["Ruined portal", "🌀"], monument: ["Ocean monument", "🔱"],
      trail_ruins: ["Trail ruins", "🏺"], trial_chambers: ["Trial chambers", "🗝"] };
    const reach = Math.max(...areas(p).map(([ax, az, r]) => Math.max(Math.abs(ax), Math.abs(az)) + r));
    const step = 96;
    for (let gx = -Math.ceil(reach / step); gx <= Math.ceil(reach / step); gx++) {
      for (let gz = -Math.ceil(reach / step); gz <= Math.ceil(reach / step); gz++) {
        const roll = hash2(gx, gz, s + 5);
        if (roll > 0.45) continue;
        const x = Math.round(gx * step + hash2(gx, gz, s + 6) * step * 0.8), z = Math.round(gz * step + hash2(gx, gz, s + 7) * step * 0.8);
        if (!sim.made(p, x, z)) continue;
        const b = ground(p, x, z).biome;
        const kind = ["ocean", "deep_ocean"].includes(b) ? (roll < 0.06 ? "monument" : roll < 0.25 ? "shipwreck" : "ocean_ruin")
          : b === "desert" ? (roll < 0.2 ? "desert_pyramid" : "village") : b === "snowy_plains" ? (roll < 0.2 ? "igloo" : "village")
          : b === "swamp" ? "swamp_hut" : ["plains", "savanna"].includes(b) ? (roll < 0.07 ? "pillager_outpost" : "village")
          : b === "jagged_peaks" ? "ruined_portal" : roll < 0.05 ? "trial_chambers" : roll < 0.12 ? "trail_ruins" : "ruined_portal";
        out.push({ kind, name: L[kind][0], symbol: L[kind][1], x, z });
      }
    }
    return out.slice(0, 500);
  };
  // Pictures: drawn once per map (and per tile), kept for this page.
  const pictures = new Map();
  const canvasUrl = (w, h, draw) => {
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    const ctx = c.getContext("2d");
    const img = ctx.createImageData(w, h);
    draw(img.data);
    ctx.putImageData(img, 0, 0);
    return c.toDataURL("image/png");
  };
  sim.mapImage = (p) => {
    const key = `map:${p.id}`;
    if (pictures.has(key)) return pictures.get(key);
    const size = p.radius * 2, step = size > 512 ? 2 : 1, w = size / step;
    const url = canvasUrl(w, w, (data) => {
      for (let j = 0; j < w; j++) for (let i = 0; i < w; i++) {
        const [r, g, b] = colour(p, -p.radius + i * step, -p.radius + j * step);
        const o = (j * w + i) * 4;
        data[o] = r; data[o + 1] = g; data[o + 2] = b; data[o + 3] = 255;
      }
    });
    pictures.set(key, url);
    return url;
  };
  sim.mapTile = (p, scale, tx, tz) => {
    const s = [1, 2, 4, 8, 16].includes(scale) ? scale : 1;
    const key = `tile:${p.id}:${p.version}:${s}:${tx}:${tz}`;
    if (pictures.has(key)) return pictures.get(key);
    const T = 128;  // (drawn at half the real tile's pixels: it's scaled up, and quicker)
    const url = canvasUrl(T, T, (data) => {
      for (let j = 0; j < T; j++) for (let i = 0; i < T; i++) {
        const x = (tx * 256 + i * 2) * s, z = (tz * 256 + j * 2) * s;
        const o = (j * T + i) * 4;
        if (!sim.made(p, x, z)) { data[o + 3] = 0; continue; }
        const [r, g, b] = colour(p, x, z);
        data[o] = r; data[o + 1] = g; data[o + 2] = b; data[o + 3] = 255;
      }
    });
    pictures.set(key, url);
    if (pictures.size > 400) pictures.delete(pictures.keys().next().value);
    return url;
  };

  // ------------------------------------------------------------- single-player games
  sim.game = (id) => {
    const g = sim.state.games.find((x) => x.id === id);
    if (!g) throw new ApiError(404, "there's no game with that id");
    return g;
  };
  sim.gameRecipe = (b) => {
    const name = String(b.name || "").trim();
    if (!name || name.length > 60 || /[\\/:*?"<>|]/.test(name)) throw new ApiError(400, 'give the game a name (up to 60 letters, no \\ / : * ? " < > |)');
    const loader = String(b.loader || "");
    if (!["fabric", "quilt", "neoforge", "forge"].includes(loader)) throw new ApiError(400, "pick Fabric, Quilt, NeoForge or Forge");
    const minecraft = String(b.minecraft || "latest");
    if (minecraft !== "latest" && !cat().RELEASES.includes(minecraft)) throw new ApiError(400, "pick a Minecraft version from the list");
    const mods = (b.mods || []).map(String).filter((x) => /^[A-Za-z0-9_.:-]{1,100}$/.test(x)).slice(0, 200);
    const memory = Number(b.memory_gb || 4);
    if (!Number.isInteger(memory) || memory < 1 || memory > 32) throw new ApiError(400, "give Minecraft 1 to 32 GB");
    return { name, loader, minecraft, mods, memory_gb: memory, pins: b.pins && typeof b.pins === "object" ? b.pins : {} };
  };
  sim.gameCheck = (g) => {
    const mc = g.minecraft === "latest" ? cat().RELEASES.find((v) => g.mods.every((slug) => !cat().mod(slug) || cat().build(slug, v, g.loader))) || cat().RELEASES[0] : g.minecraft;
    const mods = [], skipped = [];
    for (const slug of g.mods) {
      const m = cat().mod(slug);
      const b = m && cat().build(slug, mc, g.loader);
      if (!b) { skipped.push({ name: m ? m.name : slug, reason: `no ${g.loader} build for Minecraft ${mc}` }); continue; }
      mods.push({ name: m.name, project: `modrinth:${m.id}`, source: "modrinth", version: b.version, version_id: `${m.id}-${b.version}`, channel: b.channel,
        needed_by: null, selected: true, requested: slug, manual: false });
      for (const d of m.deps) {
        const dm = cat().mod(d), db = cat().build(d, mc, g.loader);
        if (dm && db && !mods.some((x) => x.requested === d)) mods.push({ name: dm.name, project: `modrinth:${dm.id}`, source: "modrinth", version: db.version, version_id: `${dm.id}-${db.version}`, channel: db.channel, needed_by: m.name, selected: false, requested: null, manual: false });
      }
    }
    const lv = cat().loaderVersion(g.loader, mc);
    const problems = sim.fileCheck(g.loader, mc, g.mods, []).problems;
    return { id: g.id, minecraft: mc, loader: g.loader, problems, loader_version: lv,
      changes: g.installed ? [] : [`Minecraft ${mc} with ${g.loader} ${lv} and ${mods.length} mod(s)`], skipped, manual: [], mods };
  };
})();
