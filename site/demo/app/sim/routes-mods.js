"use strict";
// The demo's mods, updates and friends' downloads: the Mods page and the mod browser, adding a mod
// with what it needs (never moving the server to another Minecraft to make one fit), Change version,
// update checks, rehearsals on a copy, updates that work and updates that fail and roll back, and the
// Friends page's invite (made-up links that lead nowhere).
(function () {
  const sim = window.CCSim;
  const { ApiError } = sim;
  const now = sim.now;
  const cat = () => sim.catalog;
  const rel = () => sim.catalog.release;
  const running = (s) => s.state === "running";
  const keyOf = (m) => `${m.source || "modrinth"}:${(cat().mod(m.slug) || { id: m.slug }).id}`;
  const installed = (s) => s.mods.filter((m) => m.installed !== false);

  // ------------------------------------------------------------- the Mods page
  const modsAnswer = (s) => ({
    loader: s.loader, minecraft: s.minecraft,
    installed: installed(s).map((m) => ({ key: keyOf(m), name: m.name, version: m.version, filename: m.filename, source: m.source,
      dependency_of: m.dependency_of ? keyOf({ slug: m.dependency_of }) : null, channel: m.channel, manual: !!m.manual, datapack: false })),
    configured: s.mods.filter((m) => !m.dependency_of && !m.manual).map((m) => ({
      source: m.source, id: m.slug, required: m.required !== false, key: keyOf(m), channel: m.channel, version: m.installed === false ? "" : m.version,
      name: m.name, for_players: s.client.mods.includes(m.slug) ? m.slug : null,
      deps: s.mods.filter((d) => d.dependency_of === m.slug).map((d) => ({ key: keyOf(d), name: d.name, source: d.source, version: d.version, channel: d.channel,
        dependency_of: keyOf(m), for_players: s.client.mods.includes(d.slug) ? d.slug : null })) })),
    players_mods: s.client.mods.slice(),
    held: Object.fromEntries(s.mods.filter((m) => m.pinned).map((m) => [keyOf(m), { version: m.pinned, number: m.version }])),
    skipped: [], unmanaged: s.mods.filter((m) => m.manual).map((m) => m.filename), disabled: s.disabledJars || [], known_conflicts: [],
  });
  // Adding a mod: it needs a build for this server's Minecraft and server type, and the mods it
  // needs come along. A mod that doesn't fit is refused with the reason (never a quiet version change).
  sim.addMod = (s, source, id, { required = true, channel = null } = {}) => {
    if (!["modrinth", "curseforge"].includes(source)) throw new ApiError(400, "unknown source");
    if (!/^[A-Za-z0-9_.-]{1,100}$/.test(String(id))) throw new ApiError(400, "invalid mod id");
    if (!cat().runsMods(s.loader)) throw new ApiError(400, "this server runs plain Minecraft: pick Fabric, NeoForge or another server type for mods");
    const m = cat().mod(id);
    if (!m) throw new ApiError(400, `${id} isn't in the demo's sample catalog`);
    if (cat().plugins(s.loader) !== (m.kind === "plugin" || m.loaders.some((l) => cat().plugins(l)) && cat().plugins(s.loader))) {
      if (cat().plugins(s.loader) && m.kind !== "plugin" && !m.loaders.some((l) => cat().plugins(l))) throw new ApiError(400, `${m.name} is a mod: ${s.loader === "paper" ? "Paper" : "Purpur"} runs plugins`);
    }
    if (m.environment === "client") throw new ApiError(400, `${m.name} is client-side only`);
    if (sim.hasMod(s, m.slug) && !s.mods.find((x) => x.slug === m.slug).dependency_of) throw new ApiError(409, `${m.name} is already listed`);
    const req = sim.requires({ id: m.slug, loader: s.loader, version: s.minecraft, channel });
    if (!req.compatible) throw new ApiError(400, `can't add ${m.name}: ${req.reason || "no compatible build"}`);
    const b = cat().build(m.slug, s.minecraft, s.loader);
    if (b.channel !== "release" && !channel && s.settings.mod_channel === "release") {
      throw new ApiError(400, `can't add ${m.name}: it has only ${b.channel} builds for Minecraft ${s.minecraft} (tick "Also show mods with only alpha/beta builds" to use one)`);
    }
    const entry = sim.installMod(s, m.slug, { channel: b.channel });
    entry.installed = false; entry.required = required !== false; entry.early = channel;
    const deps = [];
    for (const d of req.deps) {
      if (sim.hasMod(s, d.slug)) continue;
      const dep = sim.installMod(s, d.slug, { dependency_of: m.slug });
      dep.installed = false;
      deps.push(d);
    }
    sim.event(s, `Added ${m.name}${deps.length ? ` (with ${deps.map((d) => d.name).join(", ")})` : ""}: it's installed with the next update`);
    const out = { ok: true, name: m.name, deps: deps.map((d) => d.name) };
    if (m.environment === "both") out.for_players = [{ id: m.slug, name: m.name, ids: [m.id, m.slug] }, ...deps.filter((d) => d.environment === "both").map((d) => ({ id: d.slug, name: d.name, ids: [d.id, d.slug] }))];
    return out;
  };
  sim.removeMod = (s, id) => {
    const m = s.mods.find((x) => (x.slug === id || keyOf(x).endsWith(":" + id)) && !x.dependency_of);
    if (!m) throw new ApiError(404, "not listed in craft-conductor.toml");
    const needed = new Set(s.mods.filter((x) => x !== m && !x.dependency_of).flatMap((x) => (cat().mod(x.slug) || { deps: [] }).deps));
    s.mods = s.mods.filter((x) => x !== m && !(x.dependency_of === m.slug && !needed.has(x.slug)));
    for (const x of s.mods) if (x.dependency_of === m.slug) x.dependency_of = [...s.mods].find((o) => (cat().mod(o.slug) || { deps: [] }).deps.includes(x.slug) && !o.dependency_of)?.slug || null;
    if (m.installed !== false && running(s)) s.restartNeeded = true;
    sim.event(s, `Removed ${m.name}: it's gone at the next update check or start`);
  };

  // ------------------------------------------------------------- updates
  const rank = { release: 0, beta: 1, alpha: 2 };
  const allows = (s, channel, early) => rank[channel] <= Math.max(rank[s.settings.mod_channel] || 0, rank[early] || 0);
  // What an update to `target` would do: each mod's newest build there (release unless allowed).
  sim.plan = (s, target) => {
    const mc = target;
    const blockers = [], mods = [];
    for (const m of s.mods.filter((x) => !x.manual)) {
      const def = cat().mod(m.slug);
      const b = def ? cat().build(m.slug, mc, s.loader) : null;
      if (!b || !allows(s, b.channel, m.early)) {
        blockers.push({ name: m.name, slug: m.slug, reason: b ? `only ${b.channel} builds for Minecraft ${mc}` : `no build for Minecraft ${mc} yet`, required: m.required !== false,
          dependency: !!m.dependency_of, config: m.dependency_of ? null : m.slug, waiting: !b });
        continue;
      }
      const version = m.pinned && mc === s.minecraft ? m.version : b.version;
      mods.push({ slug: m.slug, name: m.name, from: m.installed === false ? null : m.version, to: version, channel: b.channel, file: def.file(version) });
    }
    return { minecraft: mc, blockers: blockers.filter((x) => x.required), dropped: blockers.filter((x) => !x.required), mods };
  };
  const changesOf = (s, plan) => {
    const lines = [];
    if (plan.minecraft !== s.minecraft) lines.push(`Minecraft ${s.minecraft} -> ${plan.minecraft}`);
    if (plan.minecraft !== s.minecraft) lines.push(`loader ${s.loader_version} -> ${cat().loaderVersion(s.loader, plan.minecraft)}`);
    for (const m of plan.mods) {
      if (!m.from) lines.push(`+ ${m.name} ${m.to}`);
      else if (m.from !== m.to) lines.push(`~ ${m.name} ${m.from} -> ${m.to}`);
    }
    return lines;
  };
  const newestFor = (s) => cat().newestFor(s.loader);
  // The update check (Check now): what's new, the target the server's strategy picks, and why newer
  // Minecraft versions are held back (the mods waiting on them).
  sim.check = (s, target) => {
    const latest = newestFor(s);
    const candidates = cat().RELEASES.filter((v) => cat().RELEASES.indexOf(v) <= cat().RELEASES.indexOf(s.minecraft));
    let chosen = null;
    const blocked = [];
    if (target) chosen = sim.plan(s, target);
    else if (s.settings.strategy === "latest") {
      for (const v of candidates) {
        const p = sim.plan(s, v);
        if (!p.blockers.length) { chosen = p; break; }
        blocked.push(p);
      }
    } else chosen = sim.plan(s, s.minecraft);
    if (!target && s.settings.strategy !== "latest" && latest !== s.minecraft) blocked.push(sim.plan(s, latest));
    if (chosen && chosen.blockers.length) { blocked.unshift(chosen); chosen = null; }
    const changes = chosen ? changesOf(s, chosen) : [];
    const lagPlan = blocked.find((p) => p.minecraft === latest) || (latest !== s.minecraft ? sim.plan(s, latest) : null);
    const lagging = lagPlan && lagPlan.blockers.length && (!chosen || chosen.minecraft !== latest)
      ? { version: latest, released: now() - 12 * 86400, days: 12, remind_days: 30, due: false,
        mods: lagPlan.blockers.filter((b) => !b.dependency).map((b) => ({ name: b.name, reason: b.reason, required: b.required, config: b.config })) } : null;
    const c = {
      checked_at: now(), installed: s.minecraft, latest, target: chosen ? chosen.minecraft : null, fingerprint: chosen ? sim.id(8) : null,
      loader_version: chosen ? cat().loaderVersion(s.loader, chosen.minecraft) : null, up_to_date: !!chosen && !changes.length, changes,
      dropped: chosen ? chosen.dropped.map((b) => ({ name: b.name, reason: b.reason })) : [], manual: [],
      blocked: blocked.map((p) => ({ minecraft: p.minecraft, loader_missing: false, loader_reason: null,
        blockers: p.blockers.map((b) => ({ name: b.name, reason: b.reason, waiting: b.waiting, chain: [b.name], checked: ["Modrinth", "CurseForge"],
          explain: `${b.name}: ${b.reason}. Craft Conductor checked Modrinth and CurseForge, and keeps the server on Minecraft ${s.minecraft} until it has one.`, dependency: b.dependency })) })),
      lagging,
    };
    s.updates.check = c;
    s.updates.checked_at = c.checked_at;
    return c;
  };
  sim.updateSummary = (s) => {
    const c = s.updates.check;
    return c ? { checked_at: c.checked_at, up_to_date: c.up_to_date, target: c.target, latest: c.latest, manual: 0, lagging: c.lagging } : null;
  };
  sim.updateReady = (s) => !!(s.updates.check && !s.updates.check.up_to_date && s.updates.check.target);
  // An update fails to start when a new Minecraft gets an early (alpha/beta) build, or when the demo's
  // "the next update fails" switch is on (the website's demo controls): then it's rolled back.
  const willFail = (s, plan) => {
    if (s.updates.failNext || sim.failNext) return { mod: plan.mods.find((m) => m.from !== m.to) || plan.mods[0] || { name: "a mod", to: "" }, why: "a Mixin couldn't be applied while starting" };
    const early = plan.minecraft !== s.minecraft && plan.mods.find((m) => m.channel !== "release");
    return early ? { mod: early, why: `the ${early.channel} build crashed while starting (a Mixin couldn't be applied)` } : null;
  };
  sim.job("update", {
    duration: 9,
    begin: (s, p) => {
      p.wasRunning = running(s);
      sim.event(s, `Updating: ${p.changes.slice(0, 3).join(", ")}${p.changes.length > 3 ? "…" : ""}`);
      if (p.wasRunning) sim.say(s, `[Server] The server restarts in a moment to install an update (Craft Conductor).`);
    },
    steps: [
      [1, (s, p) => { const b = sim.makeBackup(s, `before-mod-updates-${s.minecraft}`, { quiet: true }); p.backup = b.name; sim.event(s, `Backed up to ${b.name} first`); }],
      [2.5, (s, p) => { if (p.wasRunning) { s.state = "stopping"; sim.disconnectAll(s, "Server closed"); sim.say(s, "Stopping the server"); } }],
      [4, (s, p) => { s.state = p.wasRunning ? "starting" : s.state === "stopping" ? "stopped" : s.state; sim.event(s, `Downloading ${p.plan.mods.filter((m) => m.from !== m.to).length || 1} file(s) (simulated: nothing is downloaded)`); }],
      [6, (s, p) => {
        const fail = willFail(s, p.plan);
        if (fail) {
          p.failed = fail;
          s.state = "starting";
          sim.say(s, `Loading Minecraft ${p.plan.minecraft} with ${cat().loaderName(s.loader)} ${cat().loaderVersion(s.loader, p.plan.minecraft)}`, { thread: "main" });
          sim.say(s, `Mixin apply for mod ${fail.mod.slug || "mod"} failed: ${fail.mod.name} ${fail.mod.to}`, { thread: "main", level: "ERROR" });
          sim.say(s, "Encountered an unexpected exception", { level: "ERROR" });
          return;
        }
        for (const m of p.plan.mods) { const mod = s.mods.find((x) => x.slug === m.slug); if (mod) Object.assign(mod, { version: m.to, filename: m.file, channel: m.channel, installed: true }); }
        s.minecraft = p.plan.minecraft;
        s.loader_version = cat().loaderVersion(s.loader, s.minecraft);
        s.java_major = cat().javaFor(s.minecraft);
        if (p.wasRunning) { sim.say(s, `Starting minecraft server version ${s.minecraft}`); sim.say(s, `Done (${(5 + Math.random() * 2).toFixed(3)}s)! For help, type "help"`); s.state = "running"; s.started_at = now(); s.restartNeeded = false; sim.state.next.join = Math.min(sim.state.next.join, now() + 8); }
      }],
    ],
    end: (s, p) => {
      if (p.failed) {
        const b = s.backups.find((x) => x.name === p.backup);
        if (b) sim.restoreBackup(s, b);
        s.updates.failNext = false;
        sim.failNext = false;
        for (const x of sim.state.servers) x.updates.failNext = false;
        sim.emit("event", { kind: "update-failed", server: s.id });
        s.state = p.wasRunning ? "running" : "stopped";
        if (p.wasRunning) { s.started_at = now(); sim.say(s, `Done (${(5 + Math.random() * 2).toFixed(3)}s)! For help, type "help"`); }
        sim.event(s, `The update didn't start, so Craft Conductor put everything back as it was (from ${p.backup})`, "error");
        sim.check(s);
        throw new Error(`the update didn't start: ${p.failed.mod.name} ${p.failed.mod.to}: ${p.failed.why}. Craft Conductor rolled back to the backup it made first (${p.backup}): the server is as it was${p.wasRunning ? " and running again" : ""}.`);
      }
      sim.event(s, `Updated: ${p.changes.join("; ")}`);
      sim.check(s);
      return p.plan.minecraft !== p.from ? `updated to Minecraft ${p.plan.minecraft}` : `installed ${p.changes.length} change(s)`;
    },
  });
  const startUpdate = (s, target) => {
    if (s.setup_pending) throw new ApiError(409, "the server isn't set up yet");
    const c = target ? sim.check(s, target) : s.updates.check || sim.check(s);
    if (!c.target) throw new ApiError(409, `nothing can be installed yet: ${(c.blocked[0] || { blockers: [{ name: "a mod", reason: "it isn't ready" }] }).blockers.map((b) => `${b.name} (${b.reason})`).join(", ")}`);
    const plan = sim.plan(s, c.target);
    const changes = changesOf(s, plan);
    if (!changes.length) throw new ApiError(409, "already up to date");
    return sim.submit(s, "update", "update", { plan, changes, from: s.minecraft });
  };
  // A server just made on the setup page: it "downloads" Minecraft, the loader and the mods.
  sim.job("setup", {
    duration: 8,
    steps: [
      [0.3, (s) => sim.event(s, `Downloading Minecraft ${s.minecraft} (simulated: nothing is downloaded)`)],
      [2, (s) => s.loader !== "vanilla" && sim.event(s, `Installing ${cat().loaderName(s.loader)} ${s.loader_version}`)],
      [3.5, (s) => {
        const pack = s.modpack ? cat().pack(s.modpack) : null;
        const wanted = pack ? pack.mods.filter((x) => !(s.modpackExclude || []).some((e) => e === x || e === (cat().mod(x) || {}).id))
          : (s.pendingMods || []).map((x) => String(x).replace(/^modrinth:/, ""));
        for (const slug of wanted) {
          if (!cat().mod(slug) || sim.hasMod(s, slug)) continue;
          sim.installMod(s, slug);
          for (const d of sim.requires({ id: slug, loader: s.loader, version: s.minecraft }).deps) if (!sim.hasMod(s, d.slug)) sim.installMod(s, d.slug, { dependency_of: slug });
        }
        if (pack) s.client.mods = pack.client.slice();
        if (s.mods.length) sim.event(s, `Downloading ${s.mods.length} mod(s): ${s.mods.map((m) => m.name).join(", ")}`);
      }],
      [5.5, (s) => sim.event(s, `Java ${s.java_major} is ready (shared Java ${s.java_major})`)],
      [7, (s) => sim.event(s, "Accepted Minecraft's EULA (you agreed on the setup page)")],
    ],
    end: (s) => {
      s.setup_pending = false;
      delete s.pendingMods;
      s.updates.check = null;
      sim.check(s);
      if (s.client.enabled) Object.assign(s.client, { expires: until(s.client.link_days), secret: sim.id(10) });
      sim.event(s, `${s.name} is set up: press Start to play`);
      return "set up";
    },
  });
  // A copy of the server on a beta Minecraft (Updates → Try a beta): the server itself isn't touched.
  sim.job("beta test copy", { duration: 4, steps: [], end: (s, p) => {
    const id = `${s.id}-beta`;
    if (!sim.state.servers.some((x) => x.id === id)) {
      const copy = sim.newServer({ id, name: `${s.name} (beta ${p.version})`, loader: s.loader, minecraft: p.version, port: sim.freePort(s.port + 10), memory_gb: s.memory_gb });
      copy.players = sim.clone(s.players); copy.players.online = []; copy.players.requests = [];
      sim.state.servers.push(copy);
    }
    return `made a copy, "${s.name} (beta ${p.version})", and is installing Minecraft ${p.version} on it`;
  } });
  sim.job("export", { duration: 3, steps: [], end: (s) => `exported to ${s.exports[s.exports.length - 1].name}` });

  // The update rehearsal: the update tried on a copy for a few minutes (faster in the demo).
  const rehearsalDict = (s) => {
    const r = s.updates.rehearsal;
    if (!r) return null;
    const t = now() - r.started;
    if (r.state === "running") {
      const steps = [[0, "Copying the server (world included)…"], [2, "Installing the update on the copy…"], [4, "Starting the copy…"], [6, `Watching it for ${r.minutes} minute(s)…`]];
      for (const [at, step] of steps) if (t >= at && r.step !== step) { r.step = step; r.log.push(step.replace("…", "")); }
      r.progress = t >= 6 ? Math.min(1, (t - 6) / 6) : null;
      if (t >= 12) {
        const fail = willFail(s, r.plan);
        const result = { to: r.plan.minecraft, fingerprint: (s.updates.check || {}).fingerprint, changes: r.changes, target: r.target, started: !fail, start_seconds: 41.2,
          complaints: { mods: [], other: { warnings: 3, errors: 0, examples: [] }, lag: { count: 0, worst_ms: 0 } }, note: "",
          tps_avg: fail ? null : 19.9, tps_min: fail ? null : 19.2, mspt_avg: fail ? null : 21.4, mspt_max: fail ? null : 38.0, finished: now(), minutes: r.minutes };
        if (fail) Object.assign(result, { error: `${fail.mod.name} ${fail.mod.to}: ${fail.why}`, last_lines: [`[main/ERROR]: Mixin apply for mod ${fail.mod.slug} failed`] });
        result.verdict = fail ? "bad" : "good";
        result.summary = fail ? `The update didn't start on the copy: ${result.error}` : "It worked: the copy started and ran without problems.";
        r.log.push(fail ? "✗ The update didn't start on the copy." : `✓ It started (41.2 s including the install). Watched it for ${r.minutes} minute(s).`);
        r.log.push(result.summary);
        Object.assign(r, { state: "done", step: "", progress: null, result });
        s.updates.report = result;
      }
    }
    return { id: r.id, state: r.state, step: r.step, progress: r.progress, log: r.log.slice(-50), result: r.result, minutes: r.minutes, elapsed: Math.floor(t) };
  };

  // ------------------------------------------------------------- friends' downloads
  // When a link made now stops working: link_days days from now, or never for 0 ("until I make new ones",
  // which releases before 0.29 had).
  const until = (days) => (Number(days) > 0 ? now() + Number(days) * 86400 : null);
  sim.inviteLink = (s, kind = "internet") => `https://${sim.DEMO_HOST}/join/#demo-not-a-real-invite-${kind}/${encodeURIComponent(s.name)}`;
  const linkWorks = (c) => c.enabled && c.secret && (!c.expires || c.expires > now());
  const pack = (s) => {
    const both = installed(s).filter((m) => m.environment === "both");
    const forPlayers = s.client.mods.map((slug) => cat().mod(slug)).filter(Boolean);
    const one = (m, side) => { const b = cat().build(m.slug, s.minecraft, s.loader) || { version: m.version || "", channel: "release", file: `${m.slug}.jar` };
      return { name: m.name, filename: b.file, url: `https://cdn.modrinth.com/data/${m.id || m.slug.toUpperCase()}/demo/${b.file}`, sha1: "0".repeat(40), sha512: null,
        project: `modrinth:${m.id || m.slug.toUpperCase()}`, source: "modrinth", version: b.version, version_id: `${m.id || m.slug}-${b.version}`, channel: b.channel, side }; };
    return { format: 1, name: s.name, minecraft: s.minecraft, loader: s.loader, loader_version: s.loader_version, java_major: s.java_major,
      address: sim.state.hub.share.address || "<your address>", memory_gb: s.client.memory_gb,
      mods: [...both.map((m) => one({ ...m, ...(cat().mod(m.slug) || {}) }, "both")), ...forPlayers.map((m) => one(m, "client"))],
      manual: [], skipped: [], problems: [], icon: "", updated: new Date().toISOString() };
  };
  sim.clientAnswer = (s) => {
    const c = s.client;
    const works = linkWorks(c);
    const links = works ? { local: sim.inviteLink(s, "home"), ...(sim.state.hub.share.address ? { internet: sim.inviteLink(s, "internet") } : {}) } : {};
    return {
      available: true, enabled: c.enabled, mods: c.mods.slice(), mod_details: c.mods.map((slug) => { const m = cat().mod(slug); return { slug, id: m ? m.id : "", name: m ? m.name : slug, source: "modrinth" }; }),
      memory_gb: c.memory_gb, mods_on_server: c.mods.filter((x) => sim.hasMod(s, x)),
      link: c.enabled ? links.internet || links.local || null : null, links: c.enabled ? links : {},
      expires: c.expires || null, expired: !!(c.enabled && c.secret && !works), link_days: c.link_days, link_day_choices: rel().link_days || [1, 3, 7],
      share: { port: sim.state.hub.share.port, address: sim.state.hub.share.address, running: sim.state.servers.some((x) => x.client.enabled), error: null, lan_ip: "192.168.1.50" },
      pack: c.enabled && !s.setup_pending ? pack(s) : null, pack_error: null, held: {}, loader: s.loader, minecraft: s.minecraft || "", local_mods: c.local.slice(),
      demo: true,
    };
  };
  const saveClient = (s, b) => {
    const c = s.client;
    const out = {};
    if ("enabled" in b) {
      c.enabled = b.enabled === true;
      if (c.enabled && (!c.secret || (c.expires && c.expires <= now()))) Object.assign(c, { secret: sim.id(10), expires: until(c.link_days) });
      sim.event(s, c.enabled ? "Friends' downloads are on: the invite works" : "Friends' downloads are off");
    }
    if ("link_days" in b) {
      const days = Number(b.link_days);
      if (!(rel().link_days || [1, 3, 7]).includes(days)) throw new ApiError(400, `invite links last ${(rel().link_days || [1, 3, 7]).join(", ")} days`);
      c.link_days = days;
      if (linkWorks(c)) c.expires = until(days);
    }
    if ("mods" in b) {
      if (!Array.isArray(b.mods) || !b.mods.every((x) => typeof x === "string" && /^[A-Za-z0-9_.:-]{1,100}$/.test(x))) throw new ApiError(400, "mods must be a list of Modrinth project names (or curseforge:<project id>)");
      const before = c.mods.slice();
      c.mods = [...new Set(b.mods)];
      const added = c.mods.filter((x) => !before.includes(x));
      const also = [], skipped = [];
      for (const slug of added) {
        const m = cat().mod(slug);
        if (!m || m.environment !== "both" || sim.hasMod(s, slug)) continue;
        try { sim.addMod(s, "modrinth", slug); also.push({ id: slug, name: m.name }); } catch (e) { skipped.push({ id: slug, name: m.name, reason: e.message }); }
      }
      out.also_on_server = also; out.server_skipped = skipped;
      if (Array.isArray(b.remove_from_server)) { for (const x of b.remove_from_server) if (!c.mods.includes(x) && sim.hasMod(s, x)) { try { sim.removeMod(s, x); } catch (_) { /* not listed */ } } out.players_deps = []; }
    }
    if ("memory_gb" in b) {
      const gb = Number(b.memory_gb);
      if (!Number.isInteger(gb) || gb < 1 || gb > 32) throw new ApiError(400, "memory must be between 1 and 32 GB");
      c.memory_gb = gb;
    }
    return { ...sim.clientAnswer(s), ...out };
  };

  // ------------------------------------------------------------- the lag finder
  sim.lagFinder = (s) => {
    const l = s.lag;
    if (!l || !l.started) return null;
    const t = now() - l.started;
    if (t >= 10 && !l.report) {
      l.report = { finished: now(), seconds: 30, tps: 18.7, findings: [
        { title: "Lots of item frames and hoppers in one place", detail: "A storage room's hoppers tick every game tick.", places: ["near 120, 64, -340 (the overworld)"], mods: [], tip: "Hopper minecarts or fewer hoppers in a chain help." },
        { title: "A busy mob farm", detail: "Around 180 mobs in a few chunks.", places: ["near -800, 40, 220 (the overworld)"], mods: [], tip: "A kill chamber that runs constantly keeps mob counts low." }] };
      l.started = null;
      return null;
    }
    return { state: "running", step: t < 4 ? "Asking Minecraft's profiler…" : "Reading the world's files…", progress: Math.min(0.95, t / 10), elapsed: Math.floor(t) };
  };

  // ------------------------------------------------------------- testing mods by starting them
  sim.trialDict = (t, since) => {
    const e = now() - t.started;
    const lines = ["Making a throwaway server (it listens only on this computer)…", `Installing Minecraft ${t.minecraft} with ${t.loader}…`,
      `Downloading ${t.mods.length} mod(s)…`, "Starting it…"];
    const broken = t.mods.find((slug) => { const m = cat().mod(slug); return m && m.missing && !t.mods.includes(m.missing); });
    const log = lines.slice(0, Math.min(lines.length, 1 + Math.floor(e / 1.5)));
    if (t.state === "running" && e >= 7) {
      t.state = "done";
      t.result = broken ? { ok: false, culprits: [cat().mod(broken).name], text: `It didn't start: ${cat().mod(broken).name} needs ${cat().mod(cat().mod(broken).missing).name}, which isn't in the set.` }
        : { ok: true, culprits: [], text: "It started: these mods work together." };
    }
    if (t.state !== "running") log.push(t.result ? (t.result.ok ? "✓ " : "✗ ") + t.result.text : "Stopped.");
    return { id: t.id, state: t.state, log: log.slice(since), next: log.length, tests: 1, result: t.result || null, elapsed: Math.floor(e) };
  };

  // A mod in Modrinth's search results (Quick add, and the friends' mods search).
  sim.searchHit = (m, s) => {
    const b = cat().build(m.slug, s.minecraft, s.loader);
    return { id: m.id, slug: m.slug, name: m.name, description: m.summary, icon: "", downloads: m.downloads,
      server_side: m.environment === "client" ? "unsupported" : "required", client_side: m.environment === "server" ? "unsupported" : "optional",
      latest_version: b ? b.version : "", channel: b ? b.channel : "release", environment: m.environment };
  };

  // ------------------------------------------------------------- the routes
  sim.serverRoutes({
    "GET /api/mods": (r) => modsAnswer(r.s),
    "GET /api/mods/search": (r) => {
      const term = String(r.q.q || "").toLowerCase();
      const listed = new Set(r.s.mods.map((m) => m.slug));
      return { results: Object.values(cat().MODS).filter((m) => m.kind === "mod" && m.environment !== "client" && (!term || m.name.toLowerCase().includes(term)) && cat().build(m.slug, r.s.minecraft, r.s.loader))
        .slice(0, 20).map((m) => ({ ...sim.searchHit(m, r.s), listed: listed.has(m.slug) })), hidden: 0, early_hidden: 0 };
    },
    "POST /api/mods/add": (r) => sim.addMod(r.s, r.b.source || "modrinth", String(r.b.id || "").trim(), { required: r.b.required !== false, channel: ["beta", "alpha"].includes(r.b.channel) ? r.b.channel : null }),
    "POST /api/mods/remove": (r) => { sim.removeMod(r.s, String(r.b.id || "")); return { ok: true }; },
    "POST /api/mods/required": (r) => { const m = r.s.mods.find((x) => x.slug === r.b.id && !x.dependency_of); if (!m) throw new ApiError(404, "not listed in craft-conductor.toml"); m.required = !!r.b.required; return { ok: true }; },
    "GET /api/mods/versions": (r) => {
      const found = sim.versions(r.q.key || "", r.s.loader, r.s.minecraft);
      const m = r.s.mods.find((x) => keyOf(x) === found.key);
      return { ...found, held: m && m.pinned ? m.pinned : null, installed: m ? `${(cat().mod(m.slug) || { id: m.slug }).id}-${m.version}` : null };
    },
    "POST /api/mods/pin": (r) => {
      const key = String(r.b.key || "");
      const m = r.s.mods.find((x) => keyOf(x) === key);
      if (!m) throw new ApiError(400, "that isn't a mod on this server");
      if (r.b.version) {
        const number = String(r.b.version).replace(/^[A-Z0-9-]+?-(?=[a-z0-9])/i, "").replace(`${(cat().mod(m.slug) || { id: "" }).id}-`, "");
        m.pinned = String(r.b.version);
        if (number && number !== m.version) { m.version = number; m.installed = false; }
      } else m.pinned = null;
      return { ok: true };
    },
    "POST /api/mods/jar": (r) => {
      const action = String(r.b.action || ""), name = String(r.b.name || "");
      if (!["enable", "disable", "remove"].includes(action)) throw new ApiError(400, "unknown action");
      const s = r.s;
      s.disabledJars = s.disabledJars || [];
      if (action === "disable") { s.disabledJars.push(name); s.mods = s.mods.filter((m) => m.filename !== name); }
      else if (action === "enable") s.disabledJars = s.disabledJars.filter((x) => x !== name);
      else { s.mods = s.mods.filter((m) => m.filename !== name); s.disabledJars = s.disabledJars.filter((x) => x !== name); }
      return { ok: true, message: `${action === "remove" ? "removed" : action + "d"} ${name}` };
    },
    "POST /api/mods/filecheck": (r) => sim.startCheck({ kind: "server-files", server: r.s.id }, Math.max(1, r.s.mods.length)),
    "POST /api/mods/check": (r) => { const work = { kind: "quick", loader: r.s.loader, minecraft: r.s.minecraft, mods: r.s.mods.filter((m) => !m.dependency_of).map((m) => m.slug) }; return r.b.background ? sim.startCheck(work, work.mods.length || 1) : sim.checkWork(work); },
    "POST /api/client/check": (r) => { const work = { kind: "quick", loader: r.s.loader, minecraft: r.s.minecraft, mods: [...r.s.mods.filter((m) => !m.dependency_of).map((m) => m.slug), ...r.s.client.mods] }; return r.b.background ? sim.startCheck(work, work.mods.length || 1) : sim.checkWork(work); },
    "POST /api/mods/local": (r) => {
      const f = r.b.__file || {};
      const name = String(f.name || "").replace(/[^\w.+-]/g, "_").slice(0, 120);
      if (!/\.jar$/i.test(name)) throw new ApiError(400, "pick a .jar file");
      r.s.mods.push({ key: `local:${name}`, source: "local", slug: name, name: name.replace(/\.jar$/i, ""), version: "local file", channel: "release", filename: name,
        dependency_of: null, manual: true, datapack: false, required: true, environment: "both", installed: true });
      if (running(r.s)) r.s.restartNeeded = true;
      return { ok: true, name, managed: false, note: "In the demo the file stays on your device: only its name was used." };
    },
    "GET /api/browse/search": (r) => sim.browseSearch(r.q, r.s),
    "GET /api/browse/project": (r) => sim.browseProject(r.q),
    "GET /api/browse/categories": (r) => sim.browseCategories(r.q),
    "GET /api/browse/added": (r) => ({ keys: [...new Set([...r.s.mods.flatMap((m) => [keyOf(m), `modrinth:${m.slug}`]), ...r.s.client.mods.map((x) => `modrinth:${x}`),
      ...r.s.client.mods.map((x) => `modrinth:${(cat().mod(x) || { id: x }).id}`)])].sort() }),
    "POST /api/mods/add-many": (r) => {
      const items = r.b.mods;
      if (!Array.isArray(items) || !items.length || items.length > 100) throw new ApiError(400, "pick between 1 and 100 mods");
      const added = [], skipped = [], both = [];
      for (const item of items) {
        try { const res = sim.addMod(r.s, item.source || "modrinth", item.id || item.slug, { required: r.b.required !== false, channel: item.channel }); added.push(res.name); if (res.for_players) both.push(...res.for_players); }
        catch (e) { skipped.push({ name: item.name || item.id, reason: e.message }); }
      }
      const out = { ok: true, added, skipped };
      if (both.length && r.s.client.enabled) {
        const fresh = both.filter((x) => !r.s.client.mods.includes(x.id)).map((x) => x.id);
        r.s.client.mods.push(...fresh);
        out.for_players = fresh; out.friends_on = true;
      }
      return out;
    },
    "GET /api/mods/requires": (r) => sim.requires({ ...r.q, loader: r.q.loader || r.s.loader, version: r.q.version === undefined ? r.s.minecraft : r.q.version }),

    "GET /api/updates": (r) => ({ check: r.s.updates.check }),
    "POST /api/updates/check": (r) => {
      const s = r.s;
      const target = r.b.target ? String(r.b.target) : null;
      if (target && !cat().RELEASES.includes(target) && !cat().BETAS.includes(target)) throw new ApiError(400, "that isn't a Minecraft version");
      return sim.submit(s, "update check", "update check", { target });
    },
    "POST /api/updates/apply": (r) => startUpdate(r.s, r.b.target || null),
    "POST /api/updates/remove-and-upgrade": (r) => {
      const s = r.s;
      const lag = (s.updates.check || {}).lagging;
      if (!lag || lag.version !== String(r.b.version || "")) throw new ApiError(409, "that's out of date; check for updates and try again");
      const allowed = new Set(lag.mods.map((m) => m.config).filter(Boolean));
      const mods = r.b.mods;
      if (!Array.isArray(mods) || !mods.length || !mods.every((x) => allowed.has(String(x)))) throw new ApiError(400, "pick mods from the list of mods holding the update back");
      for (const slug of mods) sim.removeMod(s, String(slug));
      return startUpdate(s, lag.version);
    },
    "GET /api/updates/readiness": (r) => {
      const s = r.s;
      const version = r.q.version || newestFor(s);
      if (!/^\d+(\.\d+){1,3}(-[A-Za-z0-9.]+)?$|^\d{2}w\d{2}[a-z]$/.test(version)) throw new ApiError(400, "that isn't a Minecraft version");
      const order = { red: 0, yellow: 1, unknown: 2, green: 3 };
      const mods = s.mods.map((m) => {
        if (m.manual) return { name: m.name, key: `local:${m.filename}`, version: "local file", state: "unknown", channel: null, required: true, needed_by: null };
        const b = cat().build(m.slug, version, s.loader);
        const state = !b ? "red" : b.channel === "release" ? "green" : "yellow";
        return { name: m.name, key: keyOf(m), version: m.version, state, channel: b ? b.channel : null, required: m.required !== false,
          needed_by: m.dependency_of ? (cat().mod(m.dependency_of) || { name: m.dependency_of }).name : null, ...(m.installed === false ? { installed: false } : {}) };
      }).sort((a, b) => order[a.state] - order[b.state] || a.name.localeCompare(b.name));
      const loaderOk = !!cat().loaderVersion(s.loader, version) || s.loader === "vanilla";
      return { minecraft: version, installed: s.minecraft, strategy: s.settings.strategy,
        loader: { name: s.loader, state: loaderOk ? "green" : "red", version: cat().loaderVersion(s.loader, version) || null }, mods,
        counts: Object.fromEntries(Object.keys(order).map((k) => [k, mods.filter((m) => m.state === k).length])) };
    },
    "GET /api/updates/rehearsal": (r) => ({ rehearsal: rehearsalDict(r.s), report: r.s.updates.report }),
    "POST /api/updates/rehearsal": (r) => {
      const s = r.s;
      if (s.setup_pending) throw new ApiError(400, "the server isn't installed yet");
      const minutes = r.b.minutes ?? 3;
      if (!Number.isInteger(minutes) || minutes < 1 || minutes > 10) throw new ApiError(400, "watch the copy for 1 to 10 minutes");
      if (sim.state.servers.some((x) => x.updates.rehearsal && x.updates.rehearsal.state === "running")) throw new ApiError(409, "an update rehearsal is already running; wait for it or stop it");
      if (s.job) throw new ApiError(409, `busy: ${s.job.name} is running`);
      const c = r.b.target ? sim.check(s, String(r.b.target)) : s.updates.check || sim.check(s);
      if (!c.target) throw new ApiError(409, "there's no update to try: check for updates first");
      const plan = sim.plan(s, c.target);
      s.updates.rehearsal = { id: sim.id(6), state: "running", step: "", progress: null, log: [], result: null, minutes, started: now(), plan, changes: changesOf(s, plan), target: r.b.target || null };
      return { ok: true, id: s.updates.rehearsal.id };
    },
    "POST /api/updates/rehearsal/stop": (r) => {
      const rr = r.s.updates.rehearsal;
      if (!rr || rr.state !== "running") throw new ApiError(404, "no rehearsal is running");
      rr.state = "cancelled"; rr.log.push("Stopped.");
      return { ok: true };
    },
    "GET /api/beta": (r) => ({ betas: cat().BETAS.slice(), current: r.s.minecraft, copies: true }),
    "POST /api/beta/test": (r) => {
      const version = String(r.b.version || "");
      if (!cat().BETAS.includes(version)) throw new ApiError(400, "pick one of the beta versions in the list");
      return sim.submit(r.s, "beta test copy", "beta test copy", { version });
    },

    "GET /api/client": (r) => sim.clientAnswer(r.s),
    "POST /api/client": (r) => saveClient(r.s, r.b),
    "POST /api/client/new-link": (r) => {
      const c = r.s.client;
      if (r.s.setup_pending) throw new ApiError(409, "the server isn't set up yet");
      Object.assign(c, { secret: sim.id(10), expires: until(r.b.days ?? c.link_days) });
      sim.event(r.s, "Made a new invite link; the old one no longer works");
      return sim.clientAnswer(r.s);
    },
    "POST /api/client/stop-link": (r) => {
      const c = r.s.client;
      if (!c.secret) throw new ApiError(404, "there's no invite link to stop");
      c.expires = now() - 1;
      sim.event(r.s, "Stopped the invite link; it no longer works");
      return sim.clientAnswer(r.s);
    },
    "POST /api/client/discord": () => { throw sim.explain("the invite would be posted to a Discord channel by your bot; no bot is connected in the demo."); },
    "POST /api/client/local": (r) => {
      const name = String((r.b.__file || {}).name || "").replace(/[^\w.+-]/g, "_").slice(0, 120);
      if (!/\.jar$/i.test(name)) throw new ApiError(400, "pick a .jar file");
      if (!r.s.client.local.includes(name)) r.s.client.local.push(name);
      return { ok: true, name };
    },
    "POST /api/client/local/remove": (r) => { r.s.client.local = r.s.client.local.filter((x) => x !== r.b.name); return { ok: true }; },
    "GET /api/client/search": (r) => {
      const s = r.s;
      if (!cat().runsMods(s.loader) || cat().plugins(s.loader)) return { results: [] };
      const term = String(r.q.q || "").trim().toLowerCase();
      if (!term && r.q.top !== "1") return { results: [] };
      return { results: Object.values(cat().MODS).filter((m) => m.kind === "mod" && m.environment !== "server" && cat().build(m.slug, s.minecraft, s.loader)
        && (!term || m.name.toLowerCase().includes(term) || m.summary.toLowerCase().includes(term))).slice(0, 20)
        .map((m) => ({ ...sim.searchHit(m, s), listed: s.client.mods.includes(m.slug) })), hidden: 0, early_hidden: 0 };
    },
  });
  sim.job("update check", { duration: 2, steps: [], end: (s, p) => {
    const c = sim.check(s, p.target);
    if (!c.target) return `update check: Minecraft ${p.target || c.latest} isn't ready: ${c.blocked[0].blockers.map((b) => b.name).join(", ")} ${c.blocked[0].blockers.length === 1 ? "isn't" : "aren't"} ready`;
    return c.up_to_date ? "update check: up to date" : `update check: an update is ready (${c.changes.length} change${c.changes.length === 1 ? "" : "s"})`;
  } });
})();
