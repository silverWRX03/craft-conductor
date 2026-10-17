"use strict";
// The demo's answers for Craft Conductor itself: signing in (always the owner, never a password),
// the server list, making a server, the setup page's checks, people and phones, sharing with friends,
// single-player games, map previews and Craft Conductor's own settings. Shapes as web.py answers them.
(function () {
  const sim = window.CCSim;
  const { ApiError } = sim;
  const now = sim.now;
  const cat = () => sim.catalog;
  const rel = () => sim.catalog.release;
  const st = () => sim.state;
  const hub = () => sim.state.hub;
  const HOME = "C:\\Users\\you\\craft-conductor";
  sim.HOME = HOME;
  const LAN = "192.168.1.50", PUBLIC = "203.0.113.25";  // (a home address and a documentation-only one)
  const version = () => rel().version || "demo";
  // Links the demo makes are clearly made up: .invalid addresses never lead anywhere.
  const DEMO_HOST = "craft-conductor.demo.invalid";
  sim.DEMO_HOST = DEMO_HOST;

  const auth = () => ({ mode: hub().auth.mode, default: false, managed: false, strong: hub().auth.strong, temporary: false });
  sim.serverSummary = (s) => ({
    id: s.id, name: s.name, state: s.state, setup_pending: !!s.setup_pending, job: s.job ? { name: s.job.name, started: s.job.started } : null,
    minecraft: s.minecraft, loader: s.loader, players: s.state === "running" ? s.players.online.length : 0, max_players: s.max_players,
    port: String(s.port), folder: `${HOME}\\servers\\${s.id}`, update: sim.updateReady(s), crashed_at: s.crashed_at,
    last_job: s.last_job, join_requests: s.players.requests.length,
  });
  const shareStatus = () => ({ port: hub().share.port, address: hub().share.address, running: st().servers.some((s) => s.client.enabled),
    error: null, lan_ip: LAN });
  const guideSteps = () => {
    const servers = st().servers;
    const ticked = new Set(hub().guide.ticked);
    const done = {
      make: servers.length > 0, start: servers.some((s) => s.state === "running" || s.everStarted),
      join: servers.some((s) => s.players.history.length > 0), open: ticked.has("open") || hub().upnp || !!hub().share.address,
      invite: ticked.has("invite") || servers.some((s) => s.client.enabled), friend: servers.some((s) => s.players.history.length > 0),
    };
    const manual = new Set(rel().guide_manual || ["open", "invite"]);
    const steps = (rel().guide || []).map((g) => ({ id: g.id, title: g.title, how: g.how, done: !!done[g.id], manual: manual.has(g.id) }));
    const next = steps.find((x) => !x.done);
    return { asked: hub().guide.asked, active: hub().guide.active, ticked: [...ticked], started: servers.length > 0,
      steps, server: servers[0] ? servers[0].id : null, next: next ? next.id : null };
  };
  const totalGb = 16;
  const memoryPlan = (adding) => {
    const running = st().servers.filter((s) => (s.state === "running" || s.state === "starting") && s.id !== adding);
    const extra = st().servers.find((s) => s.id === adding);
    const used = running.reduce((n, s) => n + s.memory_gb, 0);
    const after = used + (extra ? extra.memory_gb : 0);
    return { fits: after <= totalGb - 3, running_gb: used, total_gb: totalGb, after_gb: after, free_gb: sim.round(totalGb - 1.5 - used),
      running: running.map((s) => ({ id: s.id, gb: s.memory_gb })), adding_gb: extra ? extra.memory_gb : 0 };
  };
  const freePort = (from = 25565) => { const used = new Set(st().servers.map((s) => Number(s.port))); let p = from; while (used.has(p)) p++; return p; };
  const slugify = (name) => (String(name).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 32) || "server");
  sim.freePort = freePort;

  // ------------------------------------------------------------- the setup page's choices
  sim.setupOptions = () => ({
    loaders: cat().setupLoaders(), versions: cat().RELEASES.slice(), betas: cat().BETAS.slice(), versions_error: null,
    total_ram_gb: totalGb, memory_gb: 4, difficulties: rel().difficulties || ["peaceful", "easy", "normal", "hard"],
    gamemodes: rel().gamemodes || ["survival", "creative", "adventure", "spectator"], properties_schema: cat().propertiesSchema(),
  });

  // ------------------------------------------------------------- checks of a set of mods
  // What Craft Conductor's quick check (trial.check) and file check (filecheck.py) would find, from
  // the sample catalog: builds missing for this Minecraft, required mods, mods that need another.
  sim.checkMods = (loader, minecraft, slugs, { client = [], channels = {} } = {}) => {
    const mods = [], problems = [], conflicts = [];
    const mc = minecraft === "latest" || !minecraft ? cat().newestFor(loader) : minecraft;
    for (const slug of slugs) {
      const m = cat().mod(slug);
      if (!m) { problems.push({ mod: slug, reason: "not in the demo's sample catalog" }); continue; }
      const b = cat().build(m.slug, mc, loader);
      if (!b) { problems.push({ mod: m.name, reason: `no ${loader} build for Minecraft ${mc}` }); continue; }
      if (b.channel !== "release" && !channels[m.slug] && !channels[`modrinth:${m.slug}`]) {
        problems.push({ mod: m.name, reason: `only ${b.channel} builds for Minecraft ${mc}: tick "Also show mods with only alpha/beta builds" to use one` });
        continue;
      }
      mods.push({ id: m.id, slug: m.slug, name: m.name, version: b.version, channel: b.channel });
    }
    void client;
    return { ok: !problems.length && !conflicts.length, mods, conflicts, problems, minecraft: mc };
  };
  // A background check (poll GET /api/hub/mods/check?id=): done a moment later.
  sim.startCheck = (work, total = 3) => {
    const id = sim.id(6);
    hub().checks[id] = { id, state: "running", done: 0, total, current: "", result: null, error: "", started: now(), work };
    return { ok: true, id };
  };
  const checkStatus = (id) => {
    const job = hub().checks[id];
    if (!job) throw new ApiError(404, "that check isn't running any more");
    const elapsed = now() - job.started;
    if (job.state === "running") {
      job.done = Math.min(job.total, Math.floor(elapsed * 3));
      if (elapsed > 1.2) {
        try { job.result = sim.checkWork(job.work); job.state = "done"; job.done = job.total; } catch (e) { job.state = "failed"; job.error = e.message; }
      }
    }
    return { id: job.id, state: job.state, done: job.done, total: job.total, current: job.current, result: job.result, error: job.error, elapsed: Math.floor(elapsed) };
  };
  // (the work is kept as data, so a saved demo can still finish it)
  sim.checkWork = (w) => {
    if (w.kind === "quick") return sim.checkMods(w.loader, w.minecraft, w.mods, { channels: w.channels || {} });
    if (w.kind === "files") return { ok: true, ...sim.fileCheck(w.loader, w.minecraft, w.mods, w.client || []) };
    if (w.kind === "server-files") { const s = sim.server(w.server); return { ok: true, ...sim.fileCheck(s.loader, s.minecraft, s.mods.map((m) => m.slug), s.client.mods) }; }
    if (w.kind === "game") { const g = st().games.find((x) => x.id === w.game) || w.recipe; return { minecraft: g.minecraft === "latest" ? cat().RELEASES[0] : g.minecraft, problems: sim.fileCheck(g.loader, g.minecraft, g.mods, []).problems }; }
    return { ok: true, problems: [], unreadable: [], minecraft: w.minecraft || "" };
  };
  // Will these mods start together (the jars' own needs, on the server and players' computers)?
  sim.fileCheck = (loader, minecraft, slugs, client) => {
    const mc = minecraft === "latest" || !minecraft ? cat().newestFor(loader) : minecraft;
    const have = new Set([...slugs, ...client]);
    const problems = [];
    for (const slug of have) {
      const m = cat().mod(slug);
      if (!m) continue;
      if (m.missing && !have.has(m.missing)) {
        const dep = cat().mod(m.missing);
        const b = cat().build(slug, mc, loader);
        problems.push({ side: m.environment === "client" ? "client" : "server", kind: "missing", mod: m.name, needs: m.missing,
          text: `${m.name} ${b ? b.version : ""} needs ${dep.name} ${m.needs}, and it isn't in the list.`.replace("  ", " "),
          key: `modrinth:${m.id}`, needs_key: `modrinth:${dep.id}`,
          fixes: [{ key: `modrinth:${dep.id}`, name: dep.name, version_id: `${dep.id}-${(cat().build(dep.slug, mc, loader) || { version: "" }).version}`,
            version: (cat().build(dep.slug, mc, loader) || { version: "" }).version, channel: "release", text: `Add ${dep.name}` }] });
      }
    }
    return { problems, unreadable: [], minecraft: mc };
  };
  // What a mod needs (GET /api/hub/mods/requires, and the server's /api/mods/requires): its required
  // mods, recursively, each with a build for this Minecraft and server type, or why not.
  // Craft Conductor never changes the Minecraft version picked to make a mod fit: it says which would.
  sim.requires = (q) => {
    const id = String(q.id || "");
    if (!/^[A-Za-z0-9_.-]{1,100}$|^curseforge:\d{1,10}$/.test(id)) throw new ApiError(400, "bad mod id");
    const loader = q.loader || "fabric";
    if (loader === "vanilla") throw new ApiError(400, "that server type doesn't run mods");
    const minecraft = q.version === undefined ? null : q.version || null;
    const loaderLabel = (cat().setupLoaders().find((l) => l.name === loader) || { label: loader }).label;
    const m = cat().mod(id);
    if (!m) throw new ApiError(400, `${id} isn't in the demo's sample catalog`);
    const mc = minecraft === "latest" || !minecraft ? cat().newestFor(loader) : minecraft;
    const project = { id: m.id, slug: m.slug, name: m.name, source: m.source, environment: m.environment };
    const base = { project, minecraft: mc, loader: loaderLabel, chain: [], checked: [], suggestions: [], builds: [], datapack: false,
      channel: "release" };
    const own = cat().build(m.slug, mc, loader);
    const where = (slug) => cat().RELEASES.filter((v) => cat().build(slug, v, loader));
    if (!own) {
      const versions = where(m.slug);
      return { ...base, compatible: false, deps: [], companions: [], checked: ["Modrinth", "CurseForge"],
        reason: `${m.name} has no ${loaderLabel} build for Minecraft ${mc}. Craft Conductor checked Modrinth and CurseForge.`,
        suggestions: versions.slice(0, 3), builds: m.loaders.filter((l) => cat().build(m.slug, mc, l)) };
    }
    base.channel = own.channel;
    const deps = [], companions = [];
    const seen = new Set([m.slug]);
    const queue = m.deps.map((d) => [d, [m]]);
    let failure = null;
    while (queue.length) {
      const [slug, chain] = queue.shift();
      if (seen.has(slug)) continue;
      seen.add(slug);
      const dep = cat().mod(slug);
      const needed_by = chain[chain.length - 1].name;
      if (dep.environment === "client") { companions.push({ id: dep.id, slug: dep.slug, name: dep.name, needed_by, channel: "release" }); continue; }
      const b = cat().build(slug, mc, loader);
      deps.push({ id: dep.id, slug: dep.slug, name: dep.name, needed_by, source: "modrinth", compatible: !!b, channel: b ? b.channel : null,
        checked: ["Modrinth", "CurseForge"], environment: dep.environment });
      if (!b) { if (!failure) failure = [...chain, dep]; continue; }
      for (const d of dep.deps) queue.push([d, [...chain, dep]]);
    }
    if (!failure) return { ...base, compatible: true, deps, companions, reason: "" };
    const names = failure.map((x) => x.name);
    const needs = names.slice(2).map((n) => `, which requires ${n}`).join("");
    const last = failure[failure.length - 1];
    const fits = cat().RELEASES.filter((v) => failure.every((x) => cat().build(x.slug, v, loader)));
    return { ...base, compatible: false, deps, companions, chain: names, checked: ["Modrinth", "CurseForge"],
      reason: `${names[0]} requires ${names[1]}${needs}, but no compatible ${last.name} release was found for Minecraft ${mc} using ${loaderLabel}. Craft Conductor checked Modrinth and CurseForge.`,
      suggestions: fits.slice(0, 3) };
  };
  // Every build of a mod for a server type (Change version).
  sim.versions = (key, loader, minecraft) => {
    const m = cat().mod(key);
    if (!m) throw new ApiError(400, "that isn't a mod");
    const versions = [];
    let day = 0;
    for (const mc of cat().RELEASES) {
      const b = m.builds[mc];
      if (!b) continue;
      const loaders = m.loaders.filter((l) => l === loader || (loader === "quilt" && l === "fabric"));
      if (!loaders.length) continue;
      versions.push({ id: `${m.id}-${b[0]}`, number: b[0], channel: b[1] || "release", date: new Date((now() - (day += 20) * 86400) * 1000).toISOString().slice(0, 10) + "T00:00:00Z",
        minecraft: [mc], loaders, here: !minecraft || mc === minecraft });
    }
    return { key: `modrinth:${m.id}`, name: m.name, minecraft: minecraft || null, loaders: [loader], versions };
  };

  // ------------------------------------------------------------- browsing mods
  const hit = (m, loader, minecraft) => {
    const b = minecraft ? cat().build(m.slug, minecraft, loader) : null;
    return { source: m.source, id: m.id, slug: m.slug, name: m.name, summary: m.summary, icon: "", author: m.author,
      downloads: m.downloads, follows: m.follows, updated: "", created: "", categories: m.categories,
      versions: m.kind === "modpack" ? [m.minecraft] : Object.keys(m.builds || {}), kind: m.kind,
      environment: m.environment || "both", url: `https://modrinth.com/${m.kind === "modpack" ? "modpack" : m.kind === "plugin" ? "plugin" : "mod"}/${m.slug}`,
      ...(b ? { channel: b.channel } : {}) };
  };
  sim.browseSearch = (q, s) => {
    const kind = q.type || "mod";
    let loader = q.loader || (s ? s.loader : null);
    if (loader === "vanilla") loader = null;
    const version = q.version !== undefined ? q.version || null : s ? s.minecraft : null;
    const term = String(q.q || "").trim().toLowerCase();
    const category = q.category || "";
    let pool;
    if (kind === "modpack") pool = Object.values(cat().PACKS).filter((p) => !loader || p.loader === loader || !q.loader);
    else pool = Object.values(cat().MODS).filter((m) => (kind === "plugin" ? m.kind === "plugin" || (loader && cat().plugins(loader) && m.loaders.some((l) => cat().plugins(l))) : m.kind === "mod"));
    if (q.side === "client") pool = pool.filter((m) => m.environment !== "server");
    let hidden = 0, early = 0;
    const found = [];
    for (const m of pool) {
      if (term && !`${m.name} ${m.summary} ${m.author}`.toLowerCase().includes(term)) continue;
      if (category && !(m.categories || []).includes(category)) continue;
      if (kind !== "modpack" && loader && version) {
        const b = cat().build(m.slug, version, loader);
        if (!b) { hidden++; continue; }
        if (b.channel !== "release" && q.early !== "1") { early++; continue; }
      }
      found.push(hit(m, loader, version));
    }
    const sorts = { downloads: (a, b) => b.downloads - a.downloads, follows: (a, b) => b.follows - a.follows, newest: () => 0, updated: () => 0 };
    if (sorts[q.sort]) found.sort(sorts[q.sort]);
    return { results: found, hidden, early_hidden: early, total: found.length, offset: 0, page: 20, next: null, sample: true };
  };
  sim.browseProject = (q) => {
    const id = String(q.id || "");
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(id)) throw new ApiError(400, "bad project id");
    const m = cat().mod(id) || cat().pack(id) || cat().pack(id.toLowerCase());
    if (!m) throw new ApiError(400, "that project isn't in the demo's sample catalog");
    const pack = m.kind === "modpack";
    const versions = pack ? [{ id: `${m.id}-1.0.0`, name: `${m.name.replace(" (demo pack)", "")} 1.0.0`, number: "1.0.0", channel: "release",
      minecraft: [m.minecraft], loaders: [m.loader], date: "2026-09-01T00:00:00Z" }] : [];
    const body = m.body || `${m.summary}\n\n*This is the Craft Conductor website demo's sample catalog: the text, numbers and builds are saved for the demo, not live from ${m.source === "curseforge" ? "CurseForge" : "Modrinth"}.*`;
    return { source: m.source, id: m.id, slug: m.slug, name: m.name, summary: m.summary, icon: "", body, body_format: "markdown",
      downloads: m.downloads, follows: m.follows, updated: "2026-09-12T10:00:00Z", license: pack ? "All rights reserved (demo)" : "See the mod's page",
      categories: m.categories || [], gallery: [], links: {}, url: hit(m).url,
      loaders: pack ? [m.loader] : m.loaders, game_versions: pack ? [m.minecraft] : Object.keys(m.builds), kind: m.kind,
      client_side: m.environment === "server" ? "unsupported" : "optional", server_side: m.environment === "client" ? "unsupported" : "required", versions };
  };
  sim.browseCategories = (q) => {
    const kind = q.type || "mod";
    const pool = kind === "modpack" ? Object.values(cat().PACKS) : Object.values(cat().MODS);
    const names = [...new Set(pool.flatMap((m) => m.categories || ["adventure"]))].sort();
    return { categories: names.map((n) => ({ id: n, name: n[0].toUpperCase() + n.slice(1) })), sources: ["modrinth", "curseforge"] };
  };
  sim.packPreview = (version) => {
    const slug = String(version || "").replace(/^curseforge:/, "").replace(/-1\.0\.0$/, "").toLowerCase();
    const p = cat().pack(slug) || Object.values(cat().PACKS).find((x) => version && String(version).startsWith(x.id));
    if (!p) throw new ApiError(400, "that modpack isn't in the demo's sample catalog");
    const one = (slug) => { const m = cat().mod(slug); const b = cat().build(slug, p.minecraft, p.loader); return { name: m.name, slug, id: m.id, version: b ? b.version : "", source: "modrinth", environment: m.environment }; };
    return { name: p.name, minecraft: p.minecraft, loader: p.loader, loader_version: cat().loaderVersion(p.loader, p.minecraft),
      mods: p.mods.map(one), client_mods: p.client.map(one), overrides: 3, manual: [] };
  };

  // ------------------------------------------------------------- people
  const people = () => hub().people;
  const peopleAnswer = () => ({ people: people(), devices: hub().devices, servers: st().servers.map((s) => ({ id: s.id, name: s.name })),
    catalog: rel().access || { groups: [], presets: [] }, invite_hours: rel().invite_hours || 24, addresses: addresses(), available: true });
  const addresses = () => [{ label: `Home network (${LAN})`, host: LAN, kind: "lan" },
    ...(hub().share.address ? [{ label: `Your address (${hub().share.address})`, host: hub().share.address, kind: "custom" }] : [])];
  const inviteLink = () => {
    const url = `https://${DEMO_HOST}/#invite=DEMO-NOT-A-REAL-INVITE`;
    return { url, qr: (rel().qr || {}).invite || "", secure: true, expires_in: (rel().invite_hours || 24) * 3600 };
  };
  const grants = (raw) => {
    const known = new Set(st().servers.map((s) => s.id));
    const out = {};
    for (const [sid, caps] of Object.entries(raw || {})) if (known.has(sid) && Array.isArray(caps) && caps.length) out[sid] = [...new Set(caps.map(String))].sort();
    return out;
  };
  const person = (id) => { const p = people().find((x) => x.id === id); if (!p) throw new ApiError(404, "no such person"); return p; };

  // ------------------------------------------------------------- the phone app
  const phoneInfo = (q) => ({ public_key: "BDemoOnlyNotARealKey0000000000000000000000000000000000000000000000000000000000000000000",
    devices: hub().phones, tailscale: q.tailscale === "1" ? tailscale() : null,
    secure_url: hub().tailscale ? `https://family-pc.tail-demo.ts.net/` : null, strong: true, funnel_allowed: hub().risks.includes("tailscale-funnel") });
  const tailscale = () => ({ installed: true, running: true, name: "family-pc.tail-demo.ts.net", serving: hub().tailscale, funnel: false, ip: "100.64.0.7" });
  const KINDS = () => rel().push_kinds || { join: "A friend asks to join, or was let in", crash: "A server crashed", updates: "Updates", other: "Everything else" };
  const phone = (endpoint) => { const d = hub().phones.find((x) => x.endpoint === endpoint); if (!d) throw new ApiError(404, "notifications aren't on for this device"); return d; };

  // ------------------------------------------------------------- map previews
  sim.previewDict = (p) => ({ id: p.id, state: p.state, step: p.step, progress: p.progress, error: p.error || "", seed: p.seed,
    level_type: p.level_type, structures: p.structures, radius: p.radius, loader: p.loader, minecraft: p.minecraft, mods: p.mods,
    map: p.state === "done" ? sim.mapMeta(p) : null, elapsed: Math.floor(now() - p.started) });
  const advancePreview = (p) => {
    if (p.state !== "running") return;
    const t = now() - p.started;
    const steps = [[0, "Getting ready…", null], [1.5, "Installing Minecraft and the mods…", null], [3, "Making the world…", 0.2], [4, "Making the world…", 0.6], [5, "Drawing the map…", null]];
    for (const [at, step, progress] of steps) if (t >= at) { p.step = step; p.progress = progress; }
    if (t >= 6) { p.state = "done"; p.step = "Done"; p.progress = null; }
  };
  const preview = (id) => {
    const p = hub().previews.find((x) => x.id === String(id || ""));
    if (!p) throw new ApiError(404, "that map isn't here any more");
    advancePreview(p);
    return p;
  };
  const newPreview = (b, seed) => {
    const loader = String(b.loader || "");
    if (!loader) throw new ApiError(400, "pick a server type");
    const radius = Number(b.radius || 256);
    if (![128, 256, 512].includes(radius)) throw new ApiError(400, "pick one of the map sizes");
    const mc = String(b.minecraft || "latest");
    if (mc !== "latest" && /^1\.(1[0-7]|[0-9])(\.|$)/.test(mc)) throw new ApiError(400, "map previews need Minecraft 1.18 or newer");
    const s = String(seed ?? b.seed ?? "").trim() || String(Math.floor(Math.random() * 9e15) * (Math.random() < 0.5 ? -1 : 1));
    if (s.length > 64) throw new ApiError(400, "the seed can be up to 64 letters, numbers or symbols");
    return { id: sim.id(6), state: "running", step: "Getting ready…", progress: null, error: "", seed: s, level_type: String(b.level_type || "minecraft:normal"),
      structures: b.structures !== false, radius, loader: loader === "vanilla" ? "fabric" : loader, minecraft: mc,
      mods: (b.mods || []).map(String), started: now(), version: 0, areas: [] };
  };
  const mapSession = (id) => {
    const p = hub().previews.find((x) => x.id === String(id || "") && x.state === "done");
    if (!p || hub().map !== p.id) throw new ApiError(404, "this map's world is gone (a newer preview replaced it); preview it again to explore it");
    return p;
  };
  const mapDict = (p) => {
    if (p.job && p.job.state === "running" && now() - p.job.started > 4) {
      p.areas.push([p.job.x, p.job.z, p.job.radius]); p.version += 1;
      p.job = { ...p.job, state: "done", step: "Done", progress: null };
    } else if (p.job && p.job.state === "running") p.job.progress = Math.min(0.95, (now() - p.job.started) / 4);
    return { id: p.id, version: p.version, areas: [[0, 0, p.radius], ...p.areas], spawn: { x: 0, z: 0 }, rate: 48.0,
      running: !!(p.job && p.job.state === "running"), job: p.job || null, regions: sim.mapRegions(p) };
  };
  const ints = (q, ...names) => names.map((n) => { const v = Number(q[n]); if (!Number.isInteger(v)) throw new ApiError(400, "whole numbers, please"); return v; });

  // ------------------------------------------------------------- the routes
  sim.hubRoutes({
    // Signing in: the demo is always signed in as the owner; it never asks for a password.
    "GET /api/auth": () => ({ ...auth(), passkeys: hub().passkeys.length > 0, local: true, version: version(), reset_code: true,
      matches: false, last_update: null, strong_required: false }),
    "POST /api/login": (r) => { void r.b; return { ok: true }; },  // (whatever was typed is dropped: nothing is kept)
    "POST /api/logout": () => ({ ok: true }),
    "POST /api/auth/change": (r) => {
      const mode = r.b.mode === "pin" ? "pin" : "password";
      hub().auth = { mode, strong: mode === "password" };
      sim.emit("note", { text: "Demo: nothing was saved. The demo never keeps what you type in password boxes." });
      return { ok: true, strong: mode === "password" };
    },
    "POST /api/auth/reset-code": () => { throw sim.explain("the reset code is written to a file on the server's computer. There's no such computer in the demo."); },
    "POST /api/auth/reset-local": () => { throw sim.explain("resetting the password works only on the server's own computer."); },
    "POST /api/passkey/options": () => { throw sim.explain("signing in with a passkey isn't needed: the demo is always signed in."); },
    "POST /api/passkey/login": () => { throw sim.explain("signing in with a passkey isn't needed: the demo is always signed in."); },
    "POST /api/pair": () => { throw sim.explain("pairing a phone happens on the phone, with the code from Craft Conductor settings → Connections."); },
    "POST /api/invite": () => { throw sim.explain("invite links are opened by the people you invite, on their own device."); },
    "POST /api/invite/accept": () => { throw sim.explain("invite links are opened by the people you invite, on their own device."); },
    "GET /api/account": () => ({ owner: true }),
    "POST /api/account/password": () => { throw sim.explain("only people you invite have an account password; you're the owner here."); },
    "POST /api/account/passkeys/options": () => { throw sim.explain("only people you invite add passkeys here; you're the owner."); },
    "POST /api/account/passkeys/add": () => { throw sim.explain("only people you invite add passkeys here; you're the owner."); },
    "POST /api/account/passkeys/remove": () => { throw sim.explain("only people you invite add passkeys here; you're the owner."); },

    "GET /api/notice": () => ({ accepted: true, version: (rel().notice || {}).version || 1, title: (rel().notice || {}).title || "", points: (rel().notice || {}).points || [] }),
    "POST /api/notice/accept": () => ({ ok: true }),
    "GET /api/licenses": () => rel().licenses || { project: {}, runtime: [], bundled: [], development: [] },

    "GET /api/hub": () => ({
      version: version(), single: false, notice_accepted: true, self_update: hub().self_update, update_result: null,
      update_channel: hub().update_channel, auth: auth(), home: HOME, network_access: hub().network_access,
      servers: st().servers.map(sim.serverSummary), share: shareStatus(), guide: { asked: hub().guide.asked || st().servers.length > 0, active: hub().guide.active },
      health: hub().risks.map((name) => { const r = (rel().risks || []).find((x) => x.name === name) || { text: name };
        return { id: `risk-${name}`, level: "warn", title: "A safety rule is switched off:", risk: r.text, detail: `${r.text}. Craft Conductor settings → Advanced` }; }),
      risks: hub().risks.slice(), local: true, device: null, role: "owner",
    }),
    "GET /api/hub/guide": () => guideSteps(),
    "POST /api/hub/guide": (r) => {
      const action = String(r.b.action || ""), step = String(r.b.step || "");
      const g = hub().guide;
      if (action === "start") Object.assign(g, { asked: true, active: true });
      else if (action === "skip" || action === "stop") Object.assign(g, { asked: true, active: false });
      else if ((action === "tick" || action === "untick") && ["open", "invite"].includes(step)) {
        g.ticked = action === "tick" ? [...new Set([...g.ticked, step])] : g.ticked.filter((x) => x !== step);
      } else throw new ApiError(400, "start, skip, stop, or tick a step");
      return guideSteps();
    },
    "GET /api/hub/memory": (r) => memoryPlan(r.q.adding || null),
    "GET /api/hub/setup": () => ({ ...sim.setupOptions(), pending: true, network_option: false, port: freePort(), open_port: 36537,
      server_dir: `${HOME}\\servers\\<name>`, current: null }),
    "GET /api/hub/setup/newest": (r) => {
      const loader = r.q.loader || "";
      if (!cat().setupLoaders().some((l) => l.name === loader)) throw new ApiError(400, "unknown server type");
      return { loader, minecraft: cat().newestFor(loader) };
    },
    "GET /api/hub/port": (r) => {
      const port = Number(r.q.port);
      if (!Number.isInteger(port)) throw new ApiError(400, "the port must be a number");
      if (port < 1024 || port > 65535) throw new ApiError(400, "pick a port between 1024 and 65535");
      const owner = st().servers.find((s) => Number(s.port) === port && s.id !== r.q.exclude);
      return { port, used_by: owner ? owner.name : null, "craft-conductor": !!owner, busy: !!owner, suggestion: owner ? freePort(port) : port };
    },
    "GET /api/hub/mods/requires": (r) => sim.requires(r.q),
    "GET /api/hub/mods/search": () => ({ results: [] }),
    "GET /api/hub/mods/versions": (r) => {
      if (!r.q.loader || r.q.loader === "vanilla") throw new ApiError(400, "that server type doesn't run mods");
      return sim.versions(r.q.key || "", r.q.loader, r.q.minecraft || null);
    },
    "POST /api/hub/mods/check": (r) => {
      const b = r.b;
      if (!b.loader || b.loader === "vanilla") throw new ApiError(400, "that server type doesn't run mods");
      const work = { kind: "quick", loader: b.loader, minecraft: b.minecraft || null, mods: (b.mods || []).map(String), channels: b.mod_channels || {} };
      if (!b.background) return sim.checkWork(work);
      return sim.startCheck(work, Math.max(1, work.mods.length));
    },
    "GET /api/hub/mods/check": (r) => checkStatus(r.q.id),
    "POST /api/hub/mods/filecheck": (r) => {
      const b = r.b;
      return sim.startCheck({ kind: "files", loader: b.loader || "fabric", minecraft: b.minecraft || "latest",
        mods: [...(b.mods || []), ...(b.optional_mods || [])].map(String), client: (b.client_mods || []).map(String) }, 2);
    },
    "GET /api/hub/modpack/preview": (r) => sim.packPreview(r.q.version),
    "GET /api/hub/browse/search": (r) => sim.browseSearch(r.q, null),
    "GET /api/hub/browse/project": (r) => sim.browseProject(r.q),
    "GET /api/hub/browse/categories": (r) => sim.browseCategories(r.q),

    // Making a server: the setup page's choices become a server that "sets itself up" for a few seconds.
    "POST /api/hub/create": (r) => {
      const b = r.b;
      const loader = String(b.loader || "");
      if (!cat().setupLoaders().some((l) => l.name === loader)) throw new ApiError(400, "pick a server type");
      if (b.accept_eula !== true) throw new ApiError(400, "accept Minecraft's EULA first");
      const name = String(b.motd || b.name || "My server").trim().slice(0, 59) || "My server";
      let id = slugify(name);
      for (let n = 2; st().servers.some((s) => s.id === id); n++) id = `${slugify(name)}-${n}`;
      const minecraft = !b.minecraft || b.minecraft === "latest" ? cat().newestFor(loader) : String(b.minecraft);
      const mods = (b.mods || []).map(String);
      const check = sim.checkMods(loader, minecraft, mods.filter((x) => !String(x).includes(":") || x.startsWith("modrinth:")).map((x) => x.replace(/^modrinth:/, "")), { channels: b.mod_channels || {} });
      if (check.problems.length) throw new ApiError(409, `these mods wouldn't start together (${check.problems[0].mod}: ${check.problems[0].reason}). Fix it in Manage Mods first.`);
      const port = Number(b.port) || freePort();
      if (st().servers.some((s) => Number(s.port) === port)) throw new ApiError(409, `port ${port} is already used by another server here`);
      const s = sim.newServer({ id, name, loader, minecraft, port, memory_gb: Number(b.memory_gb) || 4, gamemode: b.gamemode, difficulty: b.difficulty,
        seed: b.properties && b.properties["level-seed"] });
      for (const [k, v] of Object.entries(b.properties || {})) if (k in s.properties) s.properties[k] = String(v);
      s.madeInDemo = true;
      s.setup_pending = true;
      s.pendingMods = mods;
      s.client.mods = (b.client_mods || []).map(String);
      s.client.enabled = !!b.friends;
      if (b.modpack_version) {  // (a modpack's mods, all but the ones taken out of it)
        const pack = cat().pack(String(b.modpack_version).replace(/^curseforge:/, "").replace(/-1\.0\.0$/, "").toLowerCase());
        if (!pack) throw new ApiError(400, "that modpack isn't in the demo's sample catalog");
        s.modpack = pack.slug;
        s.modpackExclude = (b.modpack_exclude || []).map(String);
      }
      if (["playit", "forward", "home"].includes(b.reach)) s.reach = b.reach;
      if (b.owner_name && /^[A-Za-z0-9_]{1,16}$/.test(b.owner_name)) {  // (the owner's own Minecraft name: let in, and an operator)
        s.players.whitelist.push(b.owner_name);
        s.players.ops.push({ name: b.owner_name, level: 4 });
        sim.known(s, b.owner_name);
      }
      st().servers.push(s);
      sim.submit(s, "set up server", "setup", {});
      if (hub().guide.active) hub().guide.ticked = [...new Set(hub().guide.ticked)];
      return { ok: true, id };
    },
    "POST /api/hub/delete": (r) => {
      const s = sim.server(String(r.b.id || ""));
      if (s.state === "running" || s.state === "starting") throw new ApiError(409, "stop the server first");
      st().servers = st().servers.filter((x) => x !== s);
      return { ok: true, message: r.b.delete_files ? `Deleted ${s.name} and its folder (in the demo: nothing on your computer was touched)` : `Removed ${s.name} from Craft Conductor (its folder stays)` };
    },
    "GET /api/hub/firewall-rules": () => ({ rules: [] }),  // (rules Craft Conductor made in Windows Firewall: none in the demo)
    "POST /api/hub/firewall/remove": () => { throw sim.explain("Craft Conductor would remove the Windows Firewall rules it made. The demo never changes your computer's firewall."); },
    "POST /api/hub/stage": (r) => {
      const f = r.b.__file || { name: "server.zip", size: 0 };
      return { ok: true, id: sim.id(6), name: f.name, size: f.size, kind: /\.zip$/i.test(f.name) ? "zip" : "unknown",
        servers: [], locked: false, note: "In the demo the file isn't read: only its name is shown." };
    },
    "POST /api/hub/import": () => { throw sim.explain("Craft Conductor would unpack the server you picked and add it here. The demo doesn't read your files."); },
    "GET /api/hub/saves": () => ({ worlds: [
      { id: "demo-world-1", folder: "Island Survival", name: "Island Survival", version: "1.21.1", hardcore: false, launcher: "Minecraft Launcher",
        played: now() - 2 * 86400, path: "C:\\Users\\you\\AppData\\Roaming\\.minecraft\\saves\\Island Survival", icon: "" },
      { id: "demo-world-2", folder: "Castle Build", name: "Castle Build", version: "1.20.1", hardcore: false, launcher: "Minecraft Launcher",
        played: now() - 40 * 86400, path: "C:\\Users\\you\\AppData\\Roaming\\.minecraft\\saves\\Castle Build", icon: "" }] }),
    "POST /api/hub/manual/needed": () => ({ items: [] }),
    "POST /api/hub/manual/stage": (r) => ({ ok: true, name: (r.b.__file || {}).name || "mod.jar", note: "In the demo the file isn't read." }),
    "POST /api/hub/open": () => { throw sim.explain("Craft Conductor would open the folder in your file manager, on the server's computer."); },
    "POST /api/hub/quit": () => { throw sim.explain("Quit stops every server and closes Craft Conductor. The demo stays open."); },
    "POST /api/hub/remote-install": () => { throw sim.explain("Craft Conductor would set itself up on another computer over SSH. The demo can't reach other computers."); },
    "POST /api/hub/remote-install/open": () => { throw sim.explain("Craft Conductor would open a terminal window for SSH. The demo can't open programs."); },

    // Sharing with friends and reaching the control panel from other devices.
    "POST /api/hub/share": (r) => {
      const port = Number(r.b.port || 8766);
      if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new ApiError(400, "pick a port between 1024 and 65535 that the control panel isn't using");
      hub().share = { port, address: String(r.b.address || "").trim().slice(0, 253) };
      return { ok: true, share: shareStatus() };
    },
    "POST /api/hub/share/public-ip": () => { hub().share.address = PUBLIC; return { ok: true, ip: PUBLIC, share: shareStatus() }; },
    "POST /api/hub/network": (r) => {
      if (r.b.enabled === true && !hub().auth.strong) throw new ApiError(400, `first set a strong password (${rel().strong_rules || "a strong password"}); PINs can't be used for access from other devices`);
      const before = hub().network_access;
      hub().network_access = r.b.enabled === true;
      return { ok: true, restart_needed: before !== hub().network_access };
    },
    "POST /api/hub/network/apply": () => ({ ok: true }),
    "GET /api/hub/remote": () => ({ available: true, network_access: hub().network_access, configured: hub().network_access, running_on_network: hub().network_access,
      strong: hub().auth.strong, mode: hub().auth.mode, rules: rel().strong_rules || "", port: 58908, tls: false, tls_cert: "", tls_key: "",
      addresses: addresses(), devices: hub().devices, people: people() }),
    "POST /api/hub/remote/tls": () => { throw sim.explain("Craft Conductor would use your own HTTPS certificate files. The demo has no files to read."); },
    "GET /api/hub/upnp": () => ({ enabled: hub().upnp, mapped: hub().upnp ? st().servers.filter((s) => s.state === "running").map((s) => ({ port: Number(s.port), protocol: "TCP" })) : [],
      ports: [], checked: hub().upnp ? now() - 60 : null, error: "", warning: "", exposure: hub().upnp ? rel().upnp_warning || "" : "" }),
    "POST /api/hub/upnp": (r) => {
      if (r.b.enabled === true && !hub().upnp && r.b.accept !== true) throw new ApiError(400, `confirm first: ${rel().upnp_warning || ""}`);
      if (typeof r.b.enabled === "boolean") hub().upnp = r.b.enabled;
      sim.emit("note", { text: "Demo: no router was asked. In the real app, Craft Conductor asks your router to open the server's port (UPnP)." });
      return { enabled: hub().upnp, mapped: [], ports: [], checked: now(), error: "", warning: "", exposure: hub().upnp ? rel().upnp_warning || "" : "" };
    },
    "GET /api/hub/playit": () => ({ platform: "windows", agent: false, install: { state: "idle" }, apt: (rel().playit || {}).apt || [],
      download_page: "https://playit.gg/download", guide: "https://playit.gg/support/", signer: "Developed Methods LLC" }),
    "POST /api/hub/playit/install": () => { throw sim.explain("Craft Conductor would download and check playit.gg's program, then install it. The demo can't install programs."); },
    "GET /api/hub/cloudflare": () => ({ installed: false, version: "", download: { state: "idle" }, hours: (rel().cloudflare || {}).hours || 4,
      downsides: (rel().cloudflare || {}).downsides || [], terms: "https://www.cloudflare.com/website-terms/", about: (rel().cloudflare || {}).about || "",
      error: "", running: false, address: "", ends: null, mac: false, strong: hub().auth.strong }),
    "POST /api/hub/cloudflare/download": () => { throw sim.explain("Craft Conductor would download Cloudflare's program. The demo can't download programs."); },
    "POST /api/hub/cloudflare/start": () => { throw sim.explain("Craft Conductor would put the control panel on the internet for a few hours through Cloudflare. The demo stays in your browser."); },
    "POST /api/hub/cloudflare/stop": () => ({ installed: false, running: false, address: "", download: { state: "idle" }, downsides: [], strong: true }),
    "GET /api/hub/risks": () => ({ risks: (rel().risks || []).map((x) => ({ name: x.name, text: x.text, on: hub().risks.includes(x.name), in_file: false })) }),
    "POST /api/hub/risks": (r) => {
      const name = String(r.b.name || "");
      if (!(rel().risks || []).some((x) => x.name === name)) throw new ApiError(400, "unknown setting");
      hub().risks = r.b.on === true ? [...new Set([...hub().risks, name])] : hub().risks.filter((x) => x !== name);
      return { risks: (rel().risks || []).map((x) => ({ name: x.name, text: x.text, on: hub().risks.includes(x.name), in_file: false })) };
    },
    "GET /api/hub/conflicts": () => ({ enabled: hub().conflicts, available: true, relay: "" }),
    "POST /api/hub/conflicts": (r) => { hub().conflicts = r.b.enabled === true; return { ok: true, enabled: hub().conflicts, available: true, relay: "" }; },
    "GET /api/hub/curseforge": () => ({ set: hub().curseforge, own: hub().curseforge, builtin: true }),
    "POST /api/hub/curseforge": (r) => { hub().curseforge = !!String(r.b.key || "").trim(); sim.emit("note", { text: "Demo: the key wasn't kept. The demo never stores keys or passwords." }); return { ok: true, set: true }; },

    // Discord: explained (it needs a real bot and server), with the settings page's answers.
    "GET /api/hub/discord": () => ({ set: false, bot: null, guild: "", channel: "", status_channel: "", portal: "https://discord.com/developers/applications",
      invite_url: null, whitelist: { enabled: false, mode: "ask", role: "", status: null } }),
    "POST /api/hub/discord": (r) => { if (!String(r.b.token || "").trim()) return { ok: true, set: false }; throw sim.explain("connecting a Discord bot needs a real bot token and Discord. The demo never sends or keeps tokens."); },
    "GET /api/hub/discord/guilds": () => { throw new ApiError(400, "Demo: no Discord bot is connected."); },
    "GET /api/hub/discord/channels": () => { throw new ApiError(400, "Demo: no Discord bot is connected."); },
    "GET /api/hub/discord/roles": () => { throw new ApiError(400, "Demo: no Discord bot is connected."); },
    "POST /api/hub/discord/status": () => { throw sim.explain("the status message goes to a Discord channel; no bot is connected in the demo."); },
    "POST /api/hub/discord/whitelist": () => { throw sim.explain("Discord /whitelist needs a connected bot; none is connected in the demo."); },

    // Passkeys and phones (made up: the browser and devices are never asked).
    "GET /api/hub/passkeys": () => ({ passkeys: hub().passkeys, allowed: true }),
    "POST /api/hub/passkeys/options": () => ({ challenge: "ZGVtbw", rp: { name: "Craft Conductor (demo)", id: location.hostname || "demo.invalid" },
      user: { id: "ZGVtbw", name: "owner", displayName: "Owner" }, pubKeyCredParams: [{ type: "public-key", alg: -7 }], timeout: 60000,
      authenticatorSelection: { residentKey: "preferred", userVerification: "preferred" }, attestation: "none", excludeCredentials: [] }),
    "POST /api/hub/passkeys/add": (r) => {
      const added = { id: sim.id(8), name: String(r.b.name || "This device").slice(0, 60), created: now(), last_used: null };
      hub().passkeys.push(added);
      return { ok: true, passkey: added, passkeys: hub().passkeys };
    },
    "POST /api/hub/passkeys/remove": (r) => { hub().passkeys = hub().passkeys.filter((k) => k.id !== r.b.id); return { ok: true, passkeys: hub().passkeys }; },
    "POST /api/hub/devices/pair": (r) => {
      if (!hub().network_access) throw new ApiError(400, "switch on access from other devices first (Craft Conductor settings → Connections)");
      const code = "DEMO-" + Math.floor(1000 + Math.random() * 9000);
      hub().pairing = { code, until: now() + 300, user: String(r.b.user || "owner") };
      return { url: `https://${DEMO_HOST}/#pair=DEMO-ONLY`, qr: (rel().qr || {}).pair || "", code, secure: true, expires_in: 300 };
    },
    "POST /api/hub/devices/cancel-pairing": () => { const n = hub().pairing ? 1 : 0; hub().pairing = null; return { ok: true, cancelled: n }; },
    "POST /api/hub/devices/remove": (r) => { hub().devices = r.b.id === "all" ? [] : hub().devices.filter((d) => d.id !== r.b.id); return { ok: true, devices: hub().devices }; },
    "GET /api/hub/phone": (r) => phoneInfo(r.q),
    "POST /api/hub/phone/subscribe": (r) => {
      const endpoint = String(r.b.endpoint || "");
      if (!/^https:\/\/push\.demo\.invalid\//.test(endpoint)) throw new ApiError(400, "that isn't a push address the demo made");
      const device = { id: sim.id(6), name: String(r.b.name || "This browser").slice(0, 60), endpoint, created: now(), last_ok: null, kinds: Object.keys(KINDS()).filter((k) => k !== "status"), who: "owner" };
      hub().phones = hub().phones.filter((d) => d.endpoint !== endpoint).concat(device);
      return { ok: true, device };
    },
    "POST /api/hub/phone/unsubscribe": (r) => { const n = hub().phones.length; hub().phones = hub().phones.filter((d) => d.endpoint !== r.b.endpoint); return { ok: true, removed: n - hub().phones.length }; },
    "POST /api/hub/phone/test": (r) => {
      const d = phone(String(r.b.endpoint || ""));
      d.last_ok = now();
      sim.emit("notification", { title: "Craft Conductor", body: "Notifications work on this device.", phone: true });
      return { ok: true, results: [{ id: d.id, ok: true, status: 201 }] };
    },
    "POST /api/hub/phone/prefs": (r) => {
      const d = phone(String(r.b.endpoint || ""));
      if ("kinds" in r.b) {
        if (!Array.isArray(r.b.kinds)) throw new ApiError(400, "kinds must be a list");
        d.kinds = r.b.kinds.map(String).filter((k) => k in KINDS());
      }
      return { kinds: d.kinds, all: KINDS() };
    },
    "POST /api/hub/phone/remove": (r) => { const n = hub().phones.length; hub().phones = hub().phones.filter((d) => d.id !== r.b.id); if (n === hub().phones.length) throw new ApiError(404, "no such device"); return { ok: true, devices: hub().phones }; },
    "POST /api/hub/phone/tailscale": (r) => {
      if (r.b.on === false) { hub().tailscale = false; return { ok: true, tailscale: tailscale() }; }
      if (r.b.funnel === true && !hub().risks.includes("tailscale-funnel")) throw new ApiError(403, "putting the control panel on the internet with Funnel is switched off: Craft Conductor settings → Advanced");
      hub().tailscale = true;
      sim.emit("note", { text: "Demo: Tailscale wasn't touched. In the real app the control panel gets a private HTTPS address on your Tailscale network." });
      return { ok: true, url: "https://family-pc.tail-demo.ts.net/", tailscale: tailscale() };
    },

    // People and what they may do.
    "GET /api/hub/users": () => peopleAnswer(),
    "POST /api/hub/users/invite": (r) => {
      const name = String(r.b.name || "").trim();
      if (!name || name.length > 40) throw new ApiError(400, "give them a name (up to 40 letters)");
      if (people().some((p) => p.name.toLowerCase() === name.toLowerCase())) throw new ApiError(409, "someone here already has that name");
      const g = grants(r.b.grants);
      if (!Object.keys(g).length) throw new ApiError(400, "pick at least one server and what they may do there");
      const p = { id: sim.id(6), name, username: null, created: now(), signed_up: false, invite_expires: now() + (rel().invite_hours || 24) * 3600, grants: g };
      people().push(p);
      return { ok: true, person: p.id, ...inviteLink(), people: people() };
    },
    "POST /api/hub/users/update": (r) => {
      const p = person(String(r.b.id || ""));
      if (r.b.name) p.name = String(r.b.name).trim().slice(0, 40) || p.name;
      if (r.b.grants) p.grants = grants(r.b.grants);
      return { ok: true, people: people() };
    },
    "POST /api/hub/users/remove": (r) => { person(String(r.b.id || "")); hub().people = people().filter((p) => p.id !== r.b.id); return { ok: true, people: people(), devices: hub().devices }; },
    "POST /api/hub/users/new-link": (r) => {
      const p = person(String(r.b.id || ""));
      if (p.signed_up) throw new ApiError(409, "they've already chosen how to sign in");
      p.invite_expires = now() + (rel().invite_hours || 24) * 3600;
      return { ok: true, ...inviteLink(), people: people() };
    },
    "POST /api/hub/users/cancel-link": (r) => { const p = person(String(r.b.id || "")); p.invite_expires = null; return { ok: true, people: people() }; },

    // Testing a set of mods by starting it (a throwaway server in the real app).
    "POST /api/hub/trial": (r) => {
      if (Object.values(hub().trials).some((t) => t.state === "running")) throw new ApiError(409, "a test is already running; wait for it or stop it");
      const b = r.b;
      let loader = b.loader, minecraft = b.minecraft || "latest", mods = (b.mods || []).map((x) => String(x).replace(/^modrinth:/, ""));
      if (b.server) { const s = sim.server(String(b.server)); loader = s.loader; minecraft = s.minecraft; mods = s.mods.map((m) => m.slug); }
      if (!loader || loader === "vanilla" && mods.length) throw new ApiError(400, "pick a server type that runs mods");
      const id = sim.id(6);
      hub().trials = { [id]: { id, state: "running", started: now(), loader, minecraft, mods, bisect: !!b.bisect } };
      return { ok: true, id };
    },
    "GET /api/hub/trial": (r) => {
      const t = hub().trials[r.q.id];
      if (!t) throw new ApiError(404, "that test isn't running any more");
      return sim.trialDict(t, Number(r.q.since || 0));
    },
    "POST /api/hub/trial/cancel": (r) => { const t = hub().trials[r.b.id]; if (!t) throw new ApiError(404, "that test isn't running any more"); t.state = "cancelled"; return { ok: true }; },

    // Map previews of a seed, the seed gallery and the explorable map.
    "POST /api/hub/preview": (r) => {
      if (hub().previews.some((p) => (advancePreview(p), p.state === "running"))) throw new ApiError(409, "a map is already being made; wait for it or stop it");
      const p = newPreview(r.b);
      hub().previews = [...hub().previews.filter((x) => x.state === "done").slice(-13), p];
      hub().map = p.id;
      return { ok: true, id: p.id, seed: p.seed };
    },
    "GET /api/hub/preview": (r) => sim.previewDict(preview(r.q.id)),
    "POST /api/hub/preview/cancel": (r) => { const p = preview(r.b.id); if (p.state === "running") { p.state = "cancelled"; p.step = "Stopped"; } return { ok: true }; },
    "POST /api/hub/preview/gallery": (r) => {
      const count = r.b.count ?? 6;
      if (!Number.isInteger(count) || count < 2 || count > 10) throw new ApiError(400, "compare 2 to 10 seeds");
      newPreview(r.b, "0");  // (checks the settings now)
      hub().gallery = { id: sim.id(6), state: "running", error: "", count, started: now(), params: { ...r.b, seed: "" }, made: [] };
      return { ok: true, id: hub().gallery.id };
    },
    "GET /api/hub/preview/gallery": (r) => {
      const g = hub().gallery;
      if (!g || g.id !== String(r.q.id || "")) throw new ApiError(404, "that seed gallery isn't here any more");
      const due = Math.min(g.count, Math.floor((now() - g.started) / 3));
      while (g.state === "running" && g.made.length < due) {
        const p = newPreview(g.params);
        p.state = "done"; p.step = "Done"; p.started = now() - 6;
        hub().previews.push(p);
        g.made.push(p.id);
      }
      if (g.made.length >= g.count && g.state === "running") { g.state = "done"; hub().map = g.made[g.made.length - 1]; }
      const maps = g.made.map((id) => sim.previewDict(hub().previews.find((p) => p.id === id)));
      const cur = g.state === "running" ? { ...sim.previewDict(newPreview(g.params, "…")), step: "Making the world…", progress: ((now() - g.started) % 3) / 3 } : null;
      return { id: g.id, state: g.state, error: g.error, count: g.count, index: g.made.length + (cur ? 1 : 0), current: cur, maps, failed: 0, elapsed: Math.floor(now() - g.started) };
    },
    "POST /api/hub/preview/gallery/cancel": (r) => { const g = hub().gallery; if (!g || g.id !== r.b.id) throw new ApiError(404, "that seed gallery isn't here any more"); g.state = "cancelled"; return { ok: true }; },
    "GET /api/hub/preview/map": () => { throw new ApiError(400, "the map is a picture"); },
    "GET /api/hub/map": (r) => mapDict(mapSession(r.q.id)),
    "GET /api/hub/map/tile": () => { throw new ApiError(400, "a map tile is a picture"); },
    "GET /api/hub/map/biome": (r) => { const p = mapSession(r.q.id); const [x, z] = ints(r.q, "x", "z"); return { biome: sim.biomeAt(p, x, z), made: sim.made(p, x, z) }; },
    "GET /api/hub/map/poi": (r) => {
      const p = hub().previews.find((x) => x.id === String(r.q.id || ""));
      if (!p || p.state !== "done") throw new ApiError(404, "this map's points of interest couldn't be read");
      return { landmarks: p.structures ? sim.landmarks(p) : [], version: p.version };
    },
    "POST /api/hub/map/explore": (r) => {
      const p = mapSession(r.b.id);
      const [x, z, radius] = ints(r.b, "x", "z", "radius");
      if (radius < 16 || radius > 1024) throw new ApiError(400, "make at most 1024 blocks each way from the middle at a time");
      if (p.job && p.job.state === "running") throw new ApiError(409, "the map is already being made bigger; wait for it or stop it");
      p.job = { state: "running", step: "Making the world…", progress: 0, x, z, radius, started: now(), error: "" };
      return p.job;
    },
    "POST /api/hub/map/stop": (r) => { const p = mapSession(r.b.id); if (p.job && p.job.state === "running") p.job = { ...p.job, state: "cancelled", step: "Stopped" }; return { ok: true }; },

    // Modded single-player games.
    "GET /api/hub/singleplayer": () => ({ games: st().games, loaders: ["fabric", "quilt", "neoforge", "forge"] }),
    "POST /api/hub/singleplayer": (r) => {
      const g = sim.gameRecipe(r.b);
      g.id = sim.id(6); g.created = now(); g.installed = null;
      st().games.push(g);
      return g;
    },
    "POST /api/hub/singleplayer/edit": (r) => {
      const g = sim.game(String(r.b.id || ""));
      const recipe = sim.gameRecipe({ ...g, ...r.b });
      if (recipe.loader !== g.loader && g.installed) throw new ApiError(400, "a game's mod loader can't change once it's installed: make a new game instead");
      Object.assign(g, recipe);
      return g;
    },
    "POST /api/hub/singleplayer/delete": (r) => { sim.game(String(r.b.id || "")); st().games = st().games.filter((g) => g.id !== r.b.id); return { ok: true }; },
    "POST /api/hub/singleplayer/check": (r) => { const g = sim.game(String(r.b.id || "")); return sim.gameCheck(g); },
    "POST /api/hub/singleplayer/preview": (r) => { const g = sim.gameRecipe({ name: "Preview", ...r.b }); const c = sim.gameCheck(g); return { minecraft: c.minecraft, loader: c.loader, loader_version: c.loader_version, skipped: [], mods: c.mods }; },
    "POST /api/hub/singleplayer/filecheck": (r) => { const recipe = sim.gameRecipe({ name: "Preview", ...r.b }); return sim.startCheck({ kind: "game", recipe }, 2); },
    "GET /api/hub/singleplayer/versions": (r) => {
      if (!["fabric", "quilt", "neoforge", "forge"].includes(r.q.loader)) throw new ApiError(400, "pick Fabric, Quilt, NeoForge or Forge");
      return sim.versions(r.q.key || "", r.q.loader, r.q.minecraft || null);
    },
    "POST /api/hub/singleplayer/install": () => { throw sim.explain("Craft Conductor would put this game into your Minecraft Launcher (or Prism, the Modrinth App or CurseForge) on this computer. The demo can't reach your launchers."); },

    // Craft Conductor's own updates.
    "GET /api/self-update": () => ({ version: version(), matches: false, self_update: hub().self_update, update_result: null }),
    "POST /api/self-update/check": () => {
      hub().self_update = null;
      sim.emit("note", { text: `Demo: you're looking at Craft Conductor ${version()}${rel().channel ? ` (${rel().channel})` : ""}. The real app checks GitHub for a newer release and asks before updating.` });
      return { ok: true, self_update: null, version: version() };
    },
    "POST /api/self-update/apply": () => { throw sim.explain("Craft Conductor would download its new version, check it, and restart itself."); },
    "POST /api/self-update/later": () => ({ ok: true }),
    "POST /api/self-update/channel": (r) => {
      const channel = r.b.channel === "beta" ? "beta" : "stable";
      hub().update_channel = channel;
      return { ok: true, channel };
    },
  });
})();
