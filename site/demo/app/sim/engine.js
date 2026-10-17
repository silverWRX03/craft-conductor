"use strict";
// The demo's world: the two ways to start (no servers yet, or an existing one with friends on it),
// a server's life (setting up, starting, running, stopping), players coming and going, friends
// asking to join, and the background jobs (updates, backups, checks) that take a while in the real app.
(function () {
  const sim = window.CCSim;
  const SCHEMA = 3;  // (bumped when the state's shape changes: an older saved demo starts afresh)
  const now = sim.now;

  // ------------------------------------------------------------- servers
  // A server as the demo keeps it. Its pages' answers (routes-server.js) are made from this.
  sim.newServer = (spec) => {
    const loader = spec.loader || "fabric";
    const s = {
      id: spec.id, name: spec.name, loader, minecraft: spec.minecraft || sim.catalog.newestFor(loader),
      loader_version: sim.catalog.loaderVersion(loader, spec.minecraft), java_major: sim.catalog.javaFor(spec.minecraft),
      port: spec.port || 25565, memory_gb: spec.memory_gb || 4, gamemode: spec.gamemode || "survival",
      difficulty: spec.difficulty || "normal", max_players: 20,
      state: "stopped", want_running: false, started_at: null, job: null, last_job: null, problem: null,
      crashed_at: null, setup_pending: false, created: now(),
      mods: [], world: { rules: sim.catalog.defaultRules(), border: 29999984, progress: null, seed: spec.seed || String(Math.floor(Math.random() * 1e12)) },
      players: { online: [], known: [], whitelist: [], whitelist_enabled: true, ops: [], bans: [], ip_bans: [], requests: [], history: [] },
      console: { seq: 0, lines: [] }, events: { seq: 0, list: [] },
      backups: [], modsets: [], exports: [],
      updates: { checked_at: null, target: null, rehearsal: null, report: null, failNext: false, lastResult: null },
      settings: sim.catalog.defaultSettings(), properties: sim.catalog.defaultProperties(spec),
      client: { enabled: false, mods: [], memory_gb: 4, link_days: sim.catalog.linkDays(), expires: null, secret: null, local: [] },
      java: { forced: null },
      perf: { samples: [] },
      webmap: null, bedrock: false, lag: null,
    };
    s.properties.gamemode = s.gamemode;
    s.properties.difficulty = s.difficulty;
    s.properties.motd = s.name;
    s.properties["server-port"] = String(s.port);
    return s;
  };
  // A mod as the server has it (installed, or added as another mod's dependency).
  sim.installMod = (s, slug, { dependency_of = null, channel, version, manual = false, filename } = {}) => {
    const mod = sim.catalog.mod(slug);
    const build = mod ? sim.catalog.build(slug, s.minecraft, s.loader) : null;
    const entry = {
      key: `modrinth:${mod ? mod.id : slug}`, source: mod ? mod.source || "modrinth" : "modrinth", slug: mod ? mod.slug : slug,
      name: mod ? mod.name : slug, version: version || (build ? build.version : "1.0.0"), channel: channel || (build ? build.channel : "release"),
      filename: filename || (mod && version ? mod.file(version) : build ? build.file : `${slug}.jar`), dependency_of, manual, datapack: false, required: true,
      environment: mod ? mod.environment : "both", pinned: null, added: now(),
    };
    s.mods = s.mods.filter((m) => m.slug !== entry.slug);
    s.mods.push(entry);
    return entry;
  };
  sim.hasMod = (s, slug) => s.mods.some((m) => m.slug === slug);

  // ------------------------------------------------------------- the two ways to start
  const FRIENDS = ["Alex", "Mia", "KaiCrafts", "Sam_Builds", "JordanMC", "Riley", "Noor", "LenaPlays", "Bruno_77"];
  sim.FRIENDS = FRIENDS;
  function hubState(scenario) {
    return {
      scenario, schema: SCHEMA, created: now(), clock: 0,
      servers: [], games: [],
      hub: {
        guide: { asked: scenario === "existing", active: false, ticked: scenario === "existing" ? ["invite"] : [] },
        auth: { mode: "password", strong: true }, network_access: false, update_channel: "stable",
        share: { port: 8766, address: scenario === "existing" ? "203.0.113.25" : "" },
        people: [], devices: [], phones: [], passkeys: [], pairing: null,
        risks: [], upnp: false, discord: null, curseforge: false, conflicts: false,
        tailscale: false, cloudflare: { installed: false, running: false, address: "" },
        self_update: null, javas: [{ major: 21, release: "jdk-21.0.4+7", bytes: 141300000, installed_at: now() - 9 * 86400 }],
        previews: [], gallery: null, map: null, trials: {}, checks: {},
      },
      next: { request: now() + 75, chat: now() + 20, join: now() + 40 },
      scripted: [],
    };
  }
  function existingScenario() {
    const st = hubState("existing");
    const s = sim.newServer({ id: "family-survival", name: "Family Survival", loader: "fabric", minecraft: "1.21.1", memory_gb: 6, seed: "8675309" });
    for (const slug of ["fabric-api", "lithium", "ferrite-core", "krypton", "terralith", "chunky", "spark", "simple-voice-chat"]) sim.installMod(s, slug);
    // Two mods have newer builds than the ones installed: Updates shows them ready to install.
    sim.installMod(s, "lithium", { version: "mc1.21.1-0.14.2" });
    sim.installMod(s, "spark", { version: "1.10.105" });
    s.reach = "playit";
    s.world.rules.keepInventory = "true";
    s.world.rules.mobGriefing = "false";
    s.client = { enabled: true, mods: ["xaeros-minimap"], memory_gb: 4, link_days: sim.catalog.linkDays(), expires: now() + 6 * 86400, secret: sim.id(10), local: [] };
    const p = s.players;
    p.known = [...FRIENDS, "Griefer42"].map((name) => ({ name, uuid: sim.uuid(name) }));
    p.whitelist = FRIENDS.slice();
    p.ops = [{ name: "Alex", level: 4 }, { name: "Riley", level: 2 }];
    p.bans = [{ name: "Griefer42", reason: "Burned down the village", created: "2026-09-21 20:14:03 +0000", source: "Alex" }];
    p.history = sim.playHistory(FRIENDS);
    sim.catalog.seedBackups(s);
    s.perf.samples = sim.catalog.perfHistory();
    sim.boot(s, { instant: true });
    for (const name of ["Alex", "Mia", "KaiCrafts"]) sim.join(s, name, { quiet: true });
    sim.say(s, "<Alex> anyone up for the nether fortress?");
    sim.say(s, "<Mia> omw, bringing fire res");
    sim.say(s, "<KaiCrafts> the new bridge is done :)");
    st.servers.push(s);
    // A creative world for building, stopped.
    const c = sim.newServer({ id: "creative-builds", name: "Creative builds", loader: "fabric", minecraft: "1.21.1", port: 25566, gamemode: "creative" });
    for (const slug of ["fabric-api", "lithium"]) sim.installMod(c, slug);
    c.players.known = ["Alex", "Mia"].map((name) => ({ name, uuid: sim.uuid(name) }));
    c.players.whitelist = ["Alex", "Mia"];
    c.settings.strategy = "latest";  // (it follows new Minecraft versions: an update to the newest is ready)
    sim.say(c, "Stopping the server");
    st.servers.push(c);
    // A modded server whose newest mod needs another one: it won't start, and the Dashboard says why.
    const a = sim.newServer({ id: "modded-adventure", name: "Modded adventure", loader: "fabric", minecraft: "1.21.1", port: 25567, memory_gb: 6 });
    sim.installMod(a, "fabric-api");
    sim.installMod(a, "better-end");
    sim.failStart(a, "better-end");
    st.servers.push(a);
    // People invited to help, and a modded single-player game.
    st.hub.people = sim.catalog.samplePeople(st.servers);
    st.games.push({ id: "cozy-modded", created: now() - 5 * 86400, installed: null, name: "Cozy modded survival", loader: "fabric",
      minecraft: "latest", mods: ["lithium", "xaeros-minimap"], memory_gb: 4, pins: {} });
    st.next.request = now() + 45;
    // Each server was checked for updates a while ago (as Craft Conductor does every few hours).
    for (const x of st.servers) { sim.check(x); x.updates.check.checked_at = now() - 2 * 3600; }
    return st;
  }
  sim.fresh = (scenario) => scenario === "existing" ? existingScenario() : hubState("new");

  sim.start = ({ scenario, state, mobile, release }) => {
    scenario = scenario === "new" ? "new" : "existing";
    const usable = state && typeof state === "object" && state.schema === SCHEMA && state.scenario === scenario && Array.isArray(state.servers);
    sim.state = usable ? state : sim.fresh(scenario);
    sim.mobile = mobile;
    sim.release = release;
    for (const s of sim.state.servers) {  // (a demo saved mid-job: the job finishes now)
      if (s.job) sim.finishJob(s, true);
      if (s.state === "starting") sim.boot(s, { instant: true });
      if (s.state === "stopping") s.state = "stopped";
    }
    setInterval(sim.tick, 1000);
    sim.changed();
  };
  sim.firstPage = () => {
    const st = sim.state;
    if (st.scenario === "new" && !st.servers.length) return "#new";
    return st.servers.length ? `#s/${st.servers[0].id}/dashboard` : "#servers";
  };

  // ------------------------------------------------------------- jobs
  // A job runs a while (the Dashboard shows its name with a spinner); its steps say what's happening
  // in the console and events, and its end sets last_job, as the real daemon does.
  const JOBS = {};
  sim.job = (name, def) => { JOBS[name] = def; };
  sim.submit = (s, name, kind, params = {}) => {
    if (s.job) throw new sim.ApiError(409, `busy: ${s.job.name} is running`);
    const def = JOBS[kind];
    s.job = { name, started: now(), kind, params, step: 0 };
    if (def.begin) def.begin(s, params);
    return { ok: true, job: name };
  };
  sim.finishJob = (s, quick = false) => {
    const job = s.job;
    if (!job) return;
    const def = JOBS[job.kind];
    for (; job.step < def.steps.length; job.step++) def.steps[job.step][1](s, job.params, quick);
    let ok = true, message = "done";
    try { message = (def.end ? def.end(s, job.params) : "") || "done"; } catch (e) { ok = false; message = e.message; }
    s.job = null;
    s.last_job = { name: job.name, ok, message, finished: now() };
    if (!ok) sim.event(s, `${job.name} failed: ${message}`, "error");
  };
  function runJobs(s) {
    const job = s.job;
    if (!job) return;
    const def = JOBS[job.kind];
    const elapsed = now() - job.started;
    while (job.step < def.steps.length && elapsed >= def.steps[job.step][0]) {
      def.steps[job.step][1](s, job.params, false);
      job.step++;
    }
    if (job.step >= def.steps.length && elapsed >= (def.duration || 0)) sim.finishJob(s);
  }

  // ------------------------------------------------------------- a server's life
  const START_LINES = (s) => [
    ["main", `Loading Minecraft ${s.minecraft} with ${sim.catalog.loaderName(s.loader)} ${s.loader_version}`.replace(/ $/, "")],
    ["main", `Loading ${s.mods.length + 3} mods:`],
    ...s.mods.map((m) => ["main", `  - ${m.filename.replace(/\.jar$/, "")}`]),
    ["Server thread", `Starting minecraft server version ${s.minecraft}`],
    ["Server thread", "Loading properties"],
    ["Server thread", `Default game type: ${s.gamemode.toUpperCase()}`],
    ["Server thread", "Generating keypair"],
    ["Server thread", `Starting Minecraft server on *:${s.port}`],
    ["Server thread", "Preparing level \"world\""],
    ["Server thread", "Preparing start region for dimension minecraft:overworld"],
    ["Worker-Main-2", "Preparing spawn area: 100%"],
  ];
  sim.boot = (s, { instant = false } = {}) => {
    if (!instant) return;
    for (const [thread, text] of START_LINES(s)) sim.say(s, text, { thread });
    sim.say(s, 'Done (6.482s)! For help, type "help"');
    s.state = "running";
    s.want_running = true;
    s.started_at = now() - (s.id === "family-survival" ? 3 * 3600 + 17 * 60 : 0);
  };
  sim.failStart = (s, slug) => {
    const mod = sim.catalog.mod(slug);
    const dep = sim.catalog.mod(mod.missing);
    const version = sim.catalog.build(slug, s.minecraft, s.loader).version;
    const evidence = `- Mod '${mod.name}' (${mod.modid || slug}) ${version} requires ${mod.needs} of mod '${dep.name}' (${dep.modid || mod.missing}), which is missing!`;
    s.problem = { kind: "start", time: now(), cause: "missing", title: `A mod needs ${dep.name}, which isn't installed`,
      words: `Add ${dep.name} (Craft Conductor looks for it on Modrinth), or remove the mod that needs it.`, evidence,
      actions: [{ kind: "add-mod", id: mod.missing, name: dep.name, label: `Add ${dep.name}` }] };
    s.state = "stopped";
    s.want_running = false;
    sim.say(s, `Loading Minecraft ${s.minecraft} with ${sim.catalog.loaderName(s.loader)} ${s.loader_version}`, { thread: "main" });
    sim.say(s, "Incompatible mods found!", { thread: "main", level: "ERROR" });
    s.console.seq += 1;
    s.console.lines.push({ seq: s.console.seq, text: evidence.slice(1), user: false });
    s.last_job = { name: "start", ok: false, finished: now(),
      message: `server did not finish starting:\n[${sim.clock()}] [main/ERROR]: Incompatible mods found!\n${evidence.slice(1)}` };
    sim.event(s, `start failed: a mod needs ${dep.name}`, "error");
  };
  // Why a server can't start now (the real one finds out by starting it: a missing mod, a port in use).
  sim.startProblem = (s) => {
    const broken = s.mods.find((m) => { const mod = sim.catalog.mod(m.slug); return mod && mod.missing && !sim.hasMod(s, mod.missing); });
    return broken ? broken.slug : null;
  };
  sim.job("start", {
    duration: 7,
    begin: (s) => { s.state = "starting"; s.want_running = true; s.problem = null; sim.event(s, "Starting the server"); },
    steps: [
      [0.5, (s) => { const lines = START_LINES(s); for (const [thread, text] of lines.slice(0, 2 + s.mods.length)) sim.say(s, text, { thread }); }],
      [2, (s) => {
        const broken = sim.startProblem(s);
        if (broken) { s.state = "stopped"; s.want_running = false; s.crashBroken = broken; return; }
        for (const [thread, text] of START_LINES(s).slice(2 + s.mods.length, -2)) sim.say(s, text, { thread });
      }],
      [4.5, (s) => { if (s.crashBroken) return; for (const [thread, text] of START_LINES(s).slice(-2)) sim.say(s, text, { thread }); }],
      [6, (s) => {
        if (s.crashBroken) return;
        sim.say(s, `Done (${(5 + Math.random() * 3).toFixed(3)}s)! For help, type "help"`);
        s.state = "running"; s.started_at = now();
        sim.event(s, `Server is up (Minecraft ${s.minecraft})`);
        sim.state.next.join = Math.min(sim.state.next.join, now() + 8);
      }],
    ],
    end: (s) => {
      if (s.crashBroken) {
        const slug = s.crashBroken;
        delete s.crashBroken;
        sim.failStart(s, slug);
        throw new Error(s.last_job.message);
      }
      if (s.madeInDemo && !s.firstFriends) s.firstFriends = 1;  // (a server made in the demo: friends come by)
      return "started";
    },
  });
  sim.disconnectAll = (s, why) => {
    for (const name of s.players.online.slice()) sim.leave(s, name, why);
  };
  sim.job("stop", {
    duration: 3,
    begin: (s) => { s.state = "stopping"; s.want_running = false; sim.say(s, "Stopping the server"); },
    steps: [
      [1, (s) => { sim.disconnectAll(s, "Server closed"); sim.say(s, "Saving players"); }],
      [2, (s) => { sim.say(s, "Saving worlds"); sim.say(s, "Saving chunks for level 'ServerLevel[world]'/minecraft:overworld"); }],
    ],
    end: (s) => { s.state = "stopped"; s.started_at = null; sim.event(s, "Server stopped"); return "stopped"; },
  });
  sim.job("restart", {
    duration: 9,
    begin: (s) => { s.state = "stopping"; sim.say(s, "Stopping the server"); sim.event(s, "Restarting the server"); },
    steps: [
      [1, (s) => { sim.disconnectAll(s, "Server restarting"); sim.say(s, "Saving worlds"); }],
      [2.5, (s) => { s.state = "starting"; for (const [thread, text] of START_LINES(s).slice(0, 4)) sim.say(s, text, { thread }); }],
      [7.5, (s) => {
        for (const [thread, text] of START_LINES(s).slice(4)) sim.say(s, text, { thread });
        sim.say(s, `Done (${(5 + Math.random() * 3).toFixed(3)}s)! For help, type "help"`);
        s.state = "running"; s.started_at = now(); s.restartNeeded = false;
        sim.event(s, `Server is up (Minecraft ${s.minecraft})`);
        sim.state.next.join = Math.min(sim.state.next.join, now() + 6);
      }],
    ],
    end: () => "restarted",
  });

  // ------------------------------------------------------------- players
  sim.known = (s, name) => {
    if (!s.players.known.some((k) => k.name === name)) s.players.known.push({ name, uuid: sim.uuid(name) });
  };
  sim.join = (s, name, { quiet = false } = {}) => {
    const p = s.players;
    if (s.state !== "running" || p.online.includes(name)) return false;
    if (p.bans.some((b) => b.name === name)) { if (!quiet) sim.say(s, `Disconnecting ${name}: You are banned from this server.`); return false; }
    if (p.whitelist_enabled && !p.whitelist.includes(name)) {
      if (!quiet) sim.say(s, `Disconnecting ${name} (/203.0.113.${40 + name.length}:52144): You are not white-listed on this server!`);
      return false;
    }
    if (p.online.length >= s.max_players) return false;
    p.online.push(name);
    p.online.sort((a, b) => a.localeCompare(b, "en", { sensitivity: "base" }));
    sim.known(s, name);
    p.history.push({ name, start: now(), end: null });
    sim.say(s, `${name} joined the game`);
    if (!quiet) sim.event(s, `${name} joined`);
    return true;
  };
  sim.leave = (s, name, why = "") => {
    const p = s.players;
    if (!p.online.includes(name)) return;
    p.online = p.online.filter((x) => x !== name);
    const visit = [...p.history].reverse().find((h) => h.name === name && !h.end);
    if (visit) visit.end = now();
    if (why) sim.say(s, `${name} lost connection: ${why}`);
    sim.say(s, `${name} left the game`);
  };
  // A friend who used the invite asks to be let in (the whitelist is on and they're not on it).
  sim.requestJoin = (s, name) => {
    const p = s.players;
    if (p.requests.some((r) => r.name === name) || p.whitelist.includes(name)) return false;
    p.requests.push({ id: sim.id(8), name, time: now(), via: "invite" });
    sim.known(s, name);
    sim.say(s, `Disconnecting ${name} (/203.0.113.77:51820): You are not white-listed on this server!`);
    sim.event(s, `${name} asks to join (from the friends' invite)`);
    sim.emit("notification", { title: `A friend asks to join ${s.name}`, body: `${name} used your invite. Allow them on the Players page.`, phone: true });
    return true;
  };
  sim.playHistory = (names) => {
    // A month of evenings and weekend afternoons (the Players page's activity chart).
    const out = [];
    let seed = 7;
    const rand = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
    const t = now();
    for (let day = 30; day > 0; day--) {
      const midnight = t - (t % 86400) - day * 86400;
      const weekend = [0, 6].includes(new Date(midnight * 1000).getUTCDay());
      for (const name of names) {
        if (rand() < (weekend ? 0.75 : 0.45)) {
          const hour = weekend && rand() < 0.5 ? 14 + Math.floor(rand() * 3) : 18 + Math.floor(rand() * 3);
          const start = midnight + hour * 3600 + Math.floor(rand() * 3600);
          out.push({ name, start, end: start + (40 + Math.floor(rand() * 160)) * 60 });
        }
      }
    }
    return out;
  };

  // ------------------------------------------------------------- the clock
  const CHAT = ["anyone seen my horse?", "found diamonds!!", "who wants to go to the end", "brb dinner", "the farm is done",
    "nice build", "omw", "can someone help with the wither", "gg", "lol", "the village is growing"];
  sim.tick = () => {
    const st = sim.state;
    const t = now();
    st.clock += 1;
    for (const s of st.servers) {
      runJobs(s);
      if (s.state === "running" && st.clock % 30 === 0) {
        const mspt = Math.random() < 0.12 ? 50 + Math.random() * 10 : 15 + Math.random() * 15;
        s.perf.samples.push({ tps: sim.round(Math.min(20, 1000 / mspt)), mspt: sim.round(mspt), time: t });
        if (s.perf.samples.length > 60) s.perf.samples.shift();
      }
      if (s.world.progress && s.world.progress.done < s.world.progress.total) {
        s.world.progress.done = Math.min(s.world.progress.total, s.world.progress.done + s.world.progress.total / 40);
        if (s.world.progress.done >= s.world.progress.total) { sim.say(s, "[Chunky] Task finished for world. Processed: 100.00%"); s.world.progress = null; }
      }
    }
    // The existing server's friends: someone joins or says something now and then, and a new
    // friend asks to join a little after the demo opens (once).
    const main = st.servers.find((s) => s.state === "running" && s.players.whitelist.length);
    if (main && st.scenario === "existing") {
      if (t >= st.next.chat && main.players.online.length) {
        sim.say(main, `<${sim.pick(main.players.online)}> ${sim.pick(CHAT)}`);
        st.next.chat = t + 25 + Math.random() * 40;
      }
      if (t >= st.next.join) {
        const away = main.players.whitelist.filter((n) => !main.players.online.includes(n));
        if (away.length && main.players.online.length < 6 && Math.random() < 0.6) sim.join(main, sim.pick(away));
        else if (main.players.online.length > 3) sim.leave(main, sim.pick(main.players.online.filter((n) => n !== "Alex")));
        st.next.join = t + 50 + Math.random() * 60;
      }
      if (st.next.request && t >= st.next.request) {
        st.next.request = null;
        sim.requestJoin(main, "Steve_the_Brave");
      }
    }
    // A server just made in the demo: once it runs, a friend joins and another asks to (as if invited).
    for (const s of st.servers) {
      if (s.state !== "running" || !s.firstFriends) continue;
      const since = t - s.started_at;
      if (since > 6 && s.firstFriends === 1) {
        s.firstFriends = 2;
        if (!s.players.whitelist.includes("Alex")) s.players.whitelist.push("Alex");
        sim.join(s, "Alex");
      } else if (since > 14 && s.firstFriends === 2) {
        s.firstFriends = 3;
        sim.requestJoin(s, "Sam_Builds");
      }
    }
    if (st.clock % 10 === 0) sim.changed();
  };

  // ------------------------------------------------------------- the website's buttons
  sim.command = (command, args) => {
    const st = sim.state;
    const s = st.servers.find((x) => x.id === args.server) || st.servers.find((x) => x.state === "running") || st.servers[0];
    if (command === "join-request") {
      if (!s) { sim.emit("note", { text: "Make a server first: a friend asks to join a server." }); return; }
      if (s.state !== "running") { sim.emit("note", { text: `Start ${s.name} first: friends ask to join a running server.` }); return; }
      const names = ["Steve_the_Brave", "PixelPia", "CreeperKid", "Ender_Ella", "RedstoneRay", "MossyMoe"];
      const name = names.find((n) => !s.players.requests.some((r) => r.name === n) && !s.players.whitelist.includes(n));
      if (name) sim.requestJoin(s, name);
    } else if (command === "fail-next-update") {
      for (const x of st.servers) x.updates.failNext = !!args.on;
      sim.failNext = !!args.on;  // (servers made later too)
    } else if (command === "player-join") {
      if (s && s.state === "running") {
        const away = s.players.whitelist.filter((n) => !s.players.online.includes(n));
        if (away.length) sim.join(s, sim.pick(away));
      }
    }
    sim.changed();
  };
})();
