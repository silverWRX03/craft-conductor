"use strict";
// The demo's sample catalog: Minecraft versions, server types, and a small fixed set of mods,
// plugins and modpacks saved for the demo (real mod names, made-up numbers). It is NOT what
// Modrinth or CurseForge have today: the demo says so wherever mods are browsed (ui.js).
// Craft Conductor's own texts (setup choices, server settings, permissions, notices, licenses)
// come from the release the demo shows, made by tools/build_website.py into catalog-release.js.
(function () {
  const sim = window.CCSim;
  const release = window.CC_DEMO_RELEASE || {};
  const now = sim.now;

  const RELEASES = ["1.21.4", "1.21.3", "1.21.1", "1.21", "1.20.6", "1.20.4", "1.20.1", "1.19.4", "1.19.2", "1.18.2"];
  const BETAS = ["25w02a"];
  const LOADER_NAMES = { fabric: "Fabric Loader", quilt: "Quilt Loader", neoforge: "NeoForge", forge: "Forge", paper: "Paper", purpur: "Purpur", vanilla: "" };
  const LOADER_VERSIONS = {
    fabric: () => "0.16.9", quilt: () => "0.27.1",
    neoforge: (mc) => ({ "1.21.4": "21.4.75", "1.21.3": "21.3.58", "1.21.1": "21.1.77", "1.21": "21.0.167", "1.20.6": "20.6.119", "1.20.4": "20.4.237" })[mc] || "",
    forge: (mc) => ({ "1.21.4": "54.0.16", "1.21.1": "52.0.40", "1.20.1": "47.3.22", "1.19.2": "43.4.4", "1.18.2": "40.2.21" })[mc] || "",
    paper: (mc) => `${mc}-133`, purpur: (mc) => `${mc}-2340`, vanilla: () => "",
  };
  // The newest Minecraft each server type has a build for (NeoForge and Forge start later).
  const NEWEST = { neoforge: "1.21.4", forge: "1.21.4" };
  const PLUGIN_SERVERS = new Set(["paper", "purpur"]);

  // ------------------------------------------------------------- mods
  // builds: Minecraft version -> [version, channel, file]; loaders the mod runs on; deps: required mods.
  // missing/needs: a dependency its jar asks for that the mod site doesn't list (a start that fails).
  const M = (o) => ({ source: "modrinth", kind: "mod", environment: "both", deps: [], categories: [], ...o });
  const MODS = {
    "fabric-api": M({ name: "Fabric API", author: "modmuss50", downloads: 132_400_000, summary: "Lightweight and modular API providing common hooks and intercompatibility measures utilized by mods using the Fabric toolchain.",
      categories: ["library"], loaders: ["fabric", "quilt"], builds: { "1.21.4": ["0.114.0+1.21.4"], "1.21.1": ["0.107.0+1.21.1"], "1.20.1": ["0.92.2+1.20.1"] },
      file: (v) => `fabric-api-${v}.jar` }),
    lithium: M({ name: "Lithium", author: "jellysquid3", downloads: 42_800_000, summary: "No-compromises game logic optimization mod. Well suited for clients and servers of all kinds.",
      categories: ["optimization"], loaders: ["fabric", "quilt", "neoforge"], builds: { "1.21.4": ["mc1.21.4-0.14.7"], "1.21.1": ["mc1.21.1-0.14.3"], "1.20.1": ["mc1.20.1-0.11.2"] },
      file: (v) => `lithium-fabric-${v}.jar`,
      body: "Lithium makes the game's own logic faster: mob AI, block ticking, collisions, chunk loading and more, while keeping how the game plays exactly the same.\n\n## What it helps\n\n- Mobs and their pathfinding\n- Hoppers, redstone and other block updates\n- Entity collisions and physics\n\nIt runs on servers and in single-player, and goes well with FerriteCore and Krypton." }),
    "ferrite-core": M({ name: "FerriteCore", author: "malte0811", downloads: 38_100_000, summary: "Memory usage optimizations",
      categories: ["optimization"], loaders: ["fabric", "quilt", "neoforge", "forge"], builds: { "1.21.4": ["7.1.1"], "1.21.1": ["7.0.2"], "1.20.1": ["6.0.1"] },
      file: (v) => `ferritecore-${v}-fabric.jar` }),
    krypton: M({ name: "Krypton", author: "astei", downloads: 12_400_000, environment: "server", summary: "A mod to optimize the Minecraft networking stack",
      categories: ["optimization"], loaders: ["fabric", "quilt"], builds: { "1.21.4": ["0.2.9-beta.1", "beta"], "1.21.1": ["0.2.8"], "1.20.1": ["0.2.3"] },
      file: (v) => `krypton-${v}.jar` }),
    terralith: M({ name: "Terralith", author: "Stardust Labs", downloads: 21_900_000, summary: "Explore almost 100 new biomes consisting of both realism and light fantasy, using just Vanilla blocks.",
      categories: ["worldgen", "adventure"], loaders: ["fabric", "quilt", "neoforge", "forge"], builds: { "1.21.1": ["2.5.5"], "1.20.1": ["2.4.11"] },
      file: (v) => `Terralith_1.21.1_v${v}.jar`, worldgen: true }),
    chunky: M({ name: "Chunky", author: "pop4959", downloads: 9_800_000, environment: "server", summary: "Pre-generates chunks, quickly and efficiently",
      categories: ["utility"], loaders: ["fabric", "quilt", "neoforge", "forge", "paper", "purpur"], builds: { "1.21.4": ["1.4.27"], "1.21.1": ["1.4.23"], "1.20.1": ["1.3.146"] },
      file: (v) => `Chunky-Fabric-${v}.jar` }),
    spark: M({ name: "spark", author: "lucko", downloads: 17_500_000, summary: "spark is a performance profiler for Minecraft clients, servers, and proxies.",
      categories: ["utility"], loaders: ["fabric", "quilt", "neoforge", "forge", "paper", "purpur"], builds: { "1.21.4": ["1.10.121"], "1.21.1": ["1.10.109"], "1.20.1": ["1.10.53"] },
      file: (v) => `spark-${v}-fabric.jar` }),
    "simple-voice-chat": M({ name: "Simple Voice Chat", author: "henkelmax", downloads: 31_200_000, summary: "A working voice chat in Minecraft!",
      categories: ["social", "utility"], loaders: ["fabric", "quilt", "neoforge", "forge", "paper", "purpur"], players: true,
      builds: { "1.21.4": ["fabric-1.21.4-2.5.26"], "1.21.1": ["fabric-1.21.1-2.5.24"], "1.20.1": ["fabric-1.20.1-2.5.12"] },
      file: (v) => `voicechat-${v}.jar` }),
    "xaeros-minimap": M({ name: "Xaero's Minimap", author: "thexaero", downloads: 48_600_000, environment: "client", summary: "Displays a minimap of the area around you. Only players need it.",
      categories: ["utility", "adventure"], loaders: ["fabric", "quilt", "neoforge", "forge"], builds: { "1.21.4": ["24.6.1"], "1.21.1": ["24.6.1"], "1.20.1": ["24.5.0"] },
      file: (v) => `Xaeros_Minimap_${v}_Fabric_1.21.jar` }),
    bluemap: M({ name: "BlueMap", author: "Blue", downloads: 2_100_000, environment: "server", summary: "A Minecraft mapping tool that creates 3D models of your Minecraft worlds and displays them in a web viewer.",
      categories: ["utility"], loaders: ["fabric", "neoforge", "forge", "paper", "purpur"], builds: { "1.21.4": ["5.5"], "1.21.1": ["5.4"], "1.20.1": ["5.3"] },
      file: (v) => `bluemap-${v}-fabric.jar` }),
    sodium: M({ name: "Sodium", author: "jellysquid3", downloads: 98_000_000, environment: "client", summary: "The fastest and most compatible rendering optimization mod for Minecraft. Only players need it.",
      categories: ["optimization"], loaders: ["fabric", "quilt", "neoforge"], builds: { "1.21.4": ["mc1.21.4-0.6.5"], "1.21.1": ["mc1.21.1-0.5.11"], "1.20.1": ["mc1.20.1-0.5.11"] },
      file: (v) => `sodium-fabric-${v}.jar` }),
    iris: M({ name: "Iris Shaders", author: "coderbot", downloads: 61_000_000, environment: "client", summary: "A modern shader pack loader for Minecraft. Only players need it.",
      categories: ["decoration"], loaders: ["fabric", "quilt", "neoforge"], deps: ["sodium"], builds: { "1.21.4": ["1.8.8+1.21.4"], "1.21.1": ["1.8.1+1.21.1"] },
      file: (v) => `iris-fabric-${v}.jar` }),
    "better-end": M({ name: "Better End", author: "quiqueck", modid: "betterend", downloads: 6_300_000, summary: "Better End Update, with new biomes, structures, mobs and items for the End.",
      categories: ["worldgen", "adventure"], loaders: ["fabric"], builds: { "1.21.1": ["21.0.11"], "1.20.1": ["4.0.11"] },
      file: (v) => `betterend-${v}.jar`, missing: "bclib", needs: "version 21.0.0 or later" }),
    bclib: M({ name: "BCLib", author: "quiqueck", downloads: 9_000_000, summary: "A library for quiqueck's mods (Better End, Better Nether).",
      categories: ["library"], loaders: ["fabric"], builds: { "1.21.1": ["21.0.13"], "1.20.1": ["3.0.14"] }, file: (v) => `bclib-${v}.jar` }),
    "biomes-o-plenty": M({ name: "Biomes O' Plenty", author: "Forstride", downloads: 67_000_000, summary: "Adds over 50 new biomes, blocks and plants to the Overworld, the Nether and the End.",
      categories: ["worldgen", "adventure"], loaders: ["neoforge", "forge", "fabric"], deps: ["glitchcore", "terrablender"],
      builds: { "1.21.4": ["21.4.0.3"], "1.21.1": ["21.1.0.13"], "1.20.1": ["19.0.0.94"] }, file: (v) => `BiomesOPlenty-neoforge-${v}.jar`, worldgen: true }),
    glitchcore: M({ name: "GlitchCore", author: "Adubbz", downloads: 22_000_000, summary: "A library mod used by Glitchfiend's mods (Biomes O' Plenty, Serene Seasons).",
      categories: ["library"], loaders: ["neoforge", "forge", "fabric"], builds: { "1.21.1": ["2.1.0.0"], "1.20.1": ["0.0.1.1"] }, file: (v) => `GlitchCore-neoforge-${v}.jar` }),
    terrablender: M({ name: "TerraBlender", author: "Adubbz", downloads: 70_000_000, summary: "A library mod for adding biomes in a simple and compatible manner.",
      categories: ["library", "worldgen"], loaders: ["neoforge", "forge", "fabric"], builds: { "1.21.4": ["4.2.0.1"], "1.21.1": ["4.1.0.8"], "1.20.1": ["3.0.1.10"] },
      file: (v) => `TerraBlender-neoforge-${v}.jar` }),
    create: M({ name: "Create", author: "simibubi", downloads: 75_000_000, summary: "Aesthetic technology that empowers the player: build contraptions, factories and trains.",
      categories: ["technology", "decoration"], loaders: ["neoforge", "forge"], builds: { "1.21.1": ["6.0.4"], "1.20.1": ["0.5.1.j"] }, file: (v) => `create-${v}.jar` }),
    jei: M({ name: "Just Enough Items", author: "mezz", downloads: 210_000_000, summary: "Shows items and recipes, so everyone can see how to make anything.",
      categories: ["utility"], loaders: ["neoforge", "forge", "fabric"], builds: { "1.21.4": ["24.1.0.18"], "1.21.1": ["19.21.0.247"], "1.20.1": ["15.20.0.105"] },
      file: (v) => `jei-${v}.jar` }),
    "distant-horizons": M({ name: "Distant Horizons", author: "jeseibel", downloads: 15_000_000, summary: "See much further: a level-of-detail renderer that draws far-away land cheaply.",
      categories: ["optimization"], loaders: ["fabric", "neoforge", "forge"], builds: { "1.21.4": ["2.3.1-a-1.21.4", "alpha"], "1.21.1": ["2.3.0-b-1.21.1", "beta"] },
      file: (v) => `DistantHorizons-${v}.jar` }),
    geyser: M({ name: "Geyser", author: "GeyserMC", downloads: 4_200_000, environment: "server", summary: "Lets Bedrock players (phones, tablets, consoles) join this Java server.",
      categories: ["utility"], loaders: ["fabric", "neoforge", "paper", "purpur"], builds: { "1.21.4": ["2.6.0"], "1.21.1": ["2.4.4"] }, file: (v) => `Geyser-Fabric-${v}.jar` }),
    floodgate: M({ name: "Floodgate", author: "GeyserMC", downloads: 2_900_000, environment: "server", summary: "Lets Bedrock players join without a Java account (works with Geyser).",
      categories: ["utility"], loaders: ["fabric", "neoforge", "paper", "purpur"], builds: { "1.21.4": ["2.2.4"], "1.21.1": ["2.2.4"] }, file: (v) => `Floodgate-Fabric-${v}.jar` }),
    luckperms: M({ name: "LuckPerms", author: "Luck", downloads: 1_900_000, environment: "server", kind: "plugin", summary: "A permissions plugin: who may use which commands.",
      categories: ["utility"], loaders: ["paper", "purpur"], builds: { "1.21.4": ["5.4.145"], "1.21.1": ["5.4.141"], "1.20.1": ["5.4.102"] }, file: (v) => `LuckPerms-Bukkit-${v}.jar` }),
    essentialsx: M({ name: "EssentialsX", author: "EssentialsX Team", downloads: 1_200_000, environment: "server", kind: "plugin", summary: "Homes, warps, kits and the everyday commands players expect.",
      categories: ["utility"], loaders: ["paper", "purpur"], builds: { "1.21.4": ["2.20.1"], "1.21.1": ["2.20.1"], "1.20.1": ["2.20.1"] }, file: (v) => `EssentialsX-${v}.jar` }),
    coreprotect: M({ name: "CoreProtect", author: "Intelli", downloads: 900_000, environment: "server", kind: "plugin", summary: "Logs who broke and placed what, so griefing can be rolled back.",
      categories: ["utility"], loaders: ["paper", "purpur"], builds: { "1.21.4": ["22.4"], "1.21.1": ["22.4"], "1.20.1": ["22.2"] }, file: (v) => `CoreProtect-${v}.jar` }),
  };
  for (const [slug, m] of Object.entries(MODS)) { m.slug = slug; m.id = slug.toUpperCase(); m.follows = Math.round(m.downloads / 40); }
  // Modpacks: made up for the demo (clearly named so), with mods from the list above.
  const PACKS = {
    "cozy-valley": { name: "Cozy Valley (demo pack)", author: "Craft Conductor demo", downloads: 18_400, loader: "fabric", minecraft: "1.21.1",
      summary: "A made-up example pack: gentle survival with new biomes, voice chat and a minimap.",
      mods: ["fabric-api", "lithium", "ferrite-core", "terralith", "simple-voice-chat"], client: ["xaeros-minimap", "sodium"] },
    "tinkerers-workshop": { name: "Tinkerers' Workshop (demo pack)", author: "Craft Conductor demo", downloads: 9_700, loader: "neoforge", minecraft: "1.21.1",
      summary: "A made-up example pack: Create contraptions and recipes for everyone.",
      mods: ["create", "jei", "ferrite-core"], client: [] },
    "wild-biomes": { name: "Wild Biomes (demo pack)", author: "Craft Conductor demo", downloads: 5_200, loader: "neoforge", minecraft: "1.21.1",
      summary: "A made-up example pack built on Biomes O' Plenty: it needs GlitchCore and TerraBlender too.",
      mods: ["biomes-o-plenty", "glitchcore", "terrablender", "jei"], client: [] },
  };
  for (const [slug, p] of Object.entries(PACKS)) { p.slug = slug; p.id = slug.toUpperCase(); p.kind = "modpack"; p.source = "modrinth"; p.follows = Math.round(p.downloads / 30); }

  const c = sim.catalog = {
    release, RELEASES, BETAS, MODS, PACKS, PLUGIN_SERVERS,
    mod: (slug) => {
      if (!slug) return null;
      const key = String(slug).replace(/^(modrinth|curseforge):/, "");
      return MODS[key] || MODS[key.toLowerCase()] || Object.values(MODS).find((m) => m.id === key || m.name === key) || null;
    },
    pack: (slug) => PACKS[slug] || Object.values(PACKS).find((p) => p.id === slug) || null,
    loaderName: (loader) => LOADER_NAMES[loader] ?? loader,
    loaderVersion: (loader, mc) => (LOADER_VERSIONS[loader] || (() => ""))(mc || "1.21.4"),
    newestFor: (loader) => NEWEST[loader] || RELEASES[0],
    javaFor: (mc) => { const v = String(mc || RELEASES[0]); return /^1\.(2\d|20\.[5-9])/.test(v) || /^\d\dw/.test(v) || v === "latest" ? 21 : /^1\.(1[89]|20)/.test(v) ? 17 : 8; },
    runsMods: (loader) => loader !== "vanilla",
    plugins: (loader) => PLUGIN_SERVERS.has(loader),
    // The build of a mod for this Minecraft and server type (null when there's none).
    build: (slug, mc, loader) => {
      const m = c.mod(slug);
      if (!m || (loader && !m.loaders.includes(loader) && !(loader === "quilt" && m.loaders.includes("fabric")))) return null;
      const b = m.builds[mc] || (mc === "latest" ? m.builds[RELEASES[0]] : null);
      if (!b) return null;
      return { version: b[0], channel: b[1] || "release", file: m.file(b[0]), minecraft: mc };
    },
    environment: (m) => m.environment,
  };

  // ------------------------------------------------------------- Craft Conductor's own texts
  // From the release (catalog-release.js); a fallback only where an older release has no such part.
  c.setupLoaders = () => release.loaders || [];
  // How long a new invite link works by default: 7 days where the release has it (it does in all so far).
  c.linkDays = () => { const days = release.link_days || [1, 3, 7]; return days.includes(7) ? 7 : days[0]; };
  // Releases since 0.29 have "Friends outside your home" (reach.py): their warnings come with it.
  c.hasReach = () => !!release.whitelist_warning;
  c.propertiesSchema = () => release.properties_schema || [];
  c.defaultProperties = (spec = {}) => {
    const props = Object.fromEntries(c.propertiesSchema().map((p) => [p.key, p.default]));
    if (spec.seed) props["level-seed"] = spec.seed;
    props["white-list"] = "true";
    props["enforce-whitelist"] = "true";
    return props;
  };
  c.defaultRules = () => Object.fromEntries((release.gamerules || []).map((r) => [r.id, r.default]));
  c.defaultSettings = () => ({
    memory: "4G", aikar_flags: false, find_lag: true, cpu_cores: 0, priority: "normal", restart_on_crash: true,
    strategy: "mods-only", mod_channel: "release", auto_upgrade: true, check_interval: "6h", warn_minutes: [10, 5, 1],
    wait_for_empty: false, verify_boot: true, rehearse: false, backups_keep: 10, discord_webhook: "", schedule_restart: "",
    schedule_backup: "", restart_when_empty: false, backup_copy_to: "", backup_copy_keep: 10,
    backup_include: ["world", "mods", "configs", "players", "maps"], tunnel_address: "",
  });

  // ------------------------------------------------------------- the existing server's past
  c.seedBackups = (s) => {
    const day = (ago, hour) => { const t = now(); return t - (t % 86400) - ago * 86400 + hour * 3600 + 17 * 60; };
    const stamp = (t) => new Date(t * 1000).toISOString().replace(/[-:]/g, "").replace("T", "-").slice(0, 15);
    const one = (label, time, size, mods, changes) => ({
      name: `${stamp(time)}-${label}.tar.gz`, label, size, time, snapshot: true, minecraft: s.minecraft, mods, changes,
      holds: ["configs", "maps", "mods", "players", "world"], locked: [],
      check: { ok: true, files: 18 + Math.round(size / 2e6), regions: 4 + Math.round(size / 4e6), detail: "", checked: time + 60 },
      contents: s.mods.map((m) => m.slug),
    });
    s.backups = [
      one("scheduled", day(6, 4), 9_459_418, 7, null),
      one("before-mod-updates-1.21.1", day(3, 19), 13_655_266, 7, ["craft-conductor's settings for the server changed"]),
      one("scheduled", day(1, 4), 16_802_317, 8, ["+ Simple Voice Chat fabric-1.21.1-2.5.24"]),
      one("before-the-castle", now() - 2 * 3600, 18_900_378, 8, []),
    ];
    for (const b of s.backups) b.check.detail = `${b.check.files} files, a world with ${b.check.regions} region file(s)`;
  };
  c.perfHistory = () => {
    const out = [];
    let seed = 3;
    const rand = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
    for (let i = 60; i > 0; i--) {
      const mspt = rand() < 0.15 ? 52 + rand() * 9 : 15 + rand() * 16;
      out.push({ tps: sim.round(Math.min(20, 1000 / mspt)), mspt: sim.round(mspt), time: now() - i * 60 });
    }
    return out;
  };
  // People the owner invited to help (Craft Conductor settings -> People), with what they may do.
  c.samplePeople = (servers) => {
    const preset = (name) => ((release.access && release.access.presets) || []).find((p) => p.id === name);
    const caps = (name) => (preset(name) || { caps: ["status.view"] }).caps.slice();
    const [main, second, third] = servers.map((s) => s.id);
    return [
      { id: "p-alex", name: "Alex", username: "alex", created: now() - 20 * 86400, signed_up: true, invite_expires: null,
        grants: { [main]: caps("moderator"), [second]: caps("manager") } },
      { id: "p-jordan", name: "Jordan", username: "jordan", created: now() - 12 * 86400, signed_up: true, invite_expires: null,
        grants: { [main]: [...new Set([...caps("manager"), "console.execute"])].sort(), [third]: caps("operator") } },
      { id: "p-sam", name: "Sam", username: null, created: now() - 3600, signed_up: false, invite_expires: now() + 23 * 3600,
        grants: { [main]: caps("viewer") } },
    ];
  };
})();
