"use strict";
// The demo's answers for one server's pages: the Dashboard and console, starting and stopping,
// players and join requests, backups, Java, settings, world tools and the check-ups. Mods, updates
// and friends' downloads are in routes-mods.js. Shapes as web.py's Api answers them.
(function () {
  const sim = window.CCSim;
  const { ApiError } = sim;
  const now = sim.now;
  const cat = () => sim.catalog;
  const rel = () => sim.catalog.release;
  const GB = 1024 ** 3;
  const dir = (s) => `${sim.HOME}\\servers\\${s.id}\\server`;
  const running = (s) => s.state === "running";
  const busy = (s) => { if (s.job) throw new ApiError(409, `busy: ${s.job.name} is running`); };
  // Turning the whitelist off on a server that can be reached from the internet asks first (since 0.29,
  // reach.py). A release from before has no such warning: there, as it did then, the whitelist just goes off.
  const whitelistGuarded = (s) => cat().hasReach() && sim.reachable(s);

  // ------------------------------------------------------------- the Dashboard
  const resources = (s) => {
    if (!running(s)) return null;
    const t = now();
    const players = s.players.online.length;
    const wave = Math.sin(t / 37) * 0.08 + Math.sin(t / 11) * 0.04;
    return { memory_bytes: Math.round(s.memory_gb * GB * Math.min(0.92, 0.45 + players * 0.03 + s.mods.length * 0.01 + wave)),
      cpu_percent: sim.round(Math.max(3, 14 + players * 3.5 + wave * 60), 1), cpus: 8, memory_max_bytes: s.memory_gb * GB, system_memory_bytes: 16 * GB };
  };
  const disk = (s) => {
    const used = 412 * GB + s.backups.reduce((n, b) => n + b.size, 0) + s.mods.length * 9e6;
    return { total_bytes: 1000 * GB, used_bytes: used, free_bytes: 1000 * GB - used };
  };
  sim.status = (s) => ({
    version: rel().version || "demo", state: s.state, job: s.job ? { name: s.job.name, started: s.job.started } : null, last_job: s.last_job,
    want_running: s.want_running, uptime: running(s) && s.started_at ? now() - s.started_at : null, minecraft: s.setup_pending ? null : s.minecraft,
    loader: s.loader, loader_version: s.loader_version, java_major: s.setup_pending ? null : s.java_major, java_forced: s.java.forced,
    mods: s.mods.filter((m) => m.installed !== false).length, players: running(s) ? s.players.online.slice() : [], max_players: s.max_players,
    motd: s.name, port: String(s.port), server_dir: dir(s), strategy: s.settings.strategy, auto_upgrade: s.settings.auto_upgrade,
    update: sim.updateSummary(s), notice_accepted: true, setup_pending: !!s.setup_pending, self_update: sim.state.hub.self_update,
    update_channel: sim.state.hub.update_channel, id: s.id, auth: { mode: sim.state.hub.auth.mode, default: false, managed: false, strong: sim.state.hub.auth.strong, temporary: false },
    resources: resources(s), disk: disk(s), problem: s.problem, manual_wait: null,
  });

  // ------------------------------------------------------------- the console
  // What the stand-in Minecraft answers. Nothing here is a real server: each command is looked at
  // and answered the way the game would.
  const RULE_NAMES = () => (rel().gamerules || []).map((r) => r.id);
  sim.runCommand = (s, raw) => {
    const say = (text) => sim.say(s, text);
    const words = raw.split(/\s+/);
    const cmd = words[0].toLowerCase();
    const p = s.players;
    const target = words[1] || "";
    const named = (n) => /^[A-Za-z0-9_]{3,16}$/.test(n);
    switch (cmd) {
      case "help": say("/advancement, /ban, /ban-ip, /banlist, /deop, /difficulty, /gamemode, /gamerule, /give, /help, /kick, /list, /me, /msg, /op, /pardon, /say, /seed, /stop, /tell, /time, /tp, /weather, /whitelist, /worldborder"); break;
      case "list": say(`There are ${p.online.length} of a max of ${s.max_players} players online: ${p.online.join(", ")}`); break;
      case "say": if (words.length < 2) say("Unknown or incomplete command, see below for error"); else say(`[Server] ${raw.slice(4)}`); break;
      case "me": say(`* Server ${raw.slice(3)}`); break;
      case "tell": case "msg": case "w":
        if (!p.online.includes(target)) say("No player was found");
        else say(`You whisper to ${target}: ${words.slice(2).join(" ")}`);
        break;
      case "seed": say(`Seed: [${s.world.seed}]`); break;
      case "time": if (words[1] === "set" && words[2]) say(`Set the time to ${({ day: 1000, noon: 6000, night: 13000, midnight: 18000 })[words[2]] ?? words[2]}`); else say("Unknown or incomplete command, see below for error"); break;
      case "weather": if (["clear", "rain", "thunder"].includes(words[1])) say(`Set the weather to ${words[1] === "clear" ? "clear" : words[1]}`); else say("Unknown or incomplete command, see below for error"); break;
      case "difficulty": if ((rel().difficulties || []).includes(words[1])) { s.properties.difficulty = words[1]; say(`The difficulty has been set to ${words[1][0].toUpperCase() + words[1].slice(1)}`); } else say(`The difficulty is ${s.properties.difficulty || "normal"}`); break;
      case "gamemode":
        if (!(rel().gamemodes || []).includes(words[1])) { say("Unknown or incomplete command, see below for error"); break; }
        if (words[2] && !p.online.includes(words[2])) { say("No player was found"); break; }
        say(words[2] ? `Set ${words[2]}'s game mode to ${words[1][0].toUpperCase() + words[1].slice(1)} Mode` : "No player was found");
        break;
      case "tp": case "teleport": if (words.length >= 3 && p.online.includes(words[1]) && p.online.includes(words[2])) say(`Teleported ${words[1]} to ${words[2]}`); else say("No entity was found"); break;
      case "give": if (p.online.includes(target) && words[2]) say(`Gave ${words[3] || 1} [${words[2].replace(/^minecraft:/, "").replace(/_/g, " ")}] to ${target}`); else say("No player was found"); break;
      case "kick":
        if (!p.online.includes(target)) { say("No player was found"); break; }
        sim.leave(s, target, words.slice(2).join(" ") || "Kicked by an operator");
        say(`Kicked ${target}: ${words.slice(2).join(" ") || "Kicked by an operator"}`);
        break;
      case "ban":
        if (!named(target)) { say("Unknown or incomplete command, see below for error"); break; }
        if (p.bans.some((b) => b.name === target)) { say("Nothing changed. The player is already banned"); break; }
        p.bans.push({ name: target, reason: words.slice(2).join(" ") || "Banned by an operator.", created: new Date().toISOString().replace("T", " ").slice(0, 19) + " +0000", source: "Server" });
        sim.known(s, target);
        if (p.online.includes(target)) sim.leave(s, target, "You are banned from this server.");
        say(`Banned ${target}: ${words.slice(2).join(" ") || "Banned by an operator."}`);
        break;
      case "pardon":
        if (!p.bans.some((b) => b.name === target)) { say("Nothing changed. The player isn't banned"); break; }
        p.bans = p.bans.filter((b) => b.name !== target);
        say(`Unbanned ${target}`);
        break;
      case "op":
        if (!named(target)) { say("That player does not exist"); break; }
        if (p.ops.some((o) => o.name === target)) { say("Nothing changed. The player already is an operator"); break; }
        p.ops.push({ name: target, level: Number(s.properties["op-permission-level"] || 4) });
        sim.known(s, target);
        say(`Made ${target} a server operator`);
        break;
      case "deop":
        if (!p.ops.some((o) => o.name === target)) { say("Nothing changed. The player is not an operator"); break; }
        p.ops = p.ops.filter((o) => o.name !== target);
        say(`Made ${target} no longer a server operator`);
        break;
      case "whitelist": {
        const sub = words[1], who = words[2] || "";
        if (sub === "add" && named(who)) {
          if (p.whitelist.includes(who)) say("Player is already whitelisted");
          else { p.whitelist.push(who); sim.known(s, who); p.requests = p.requests.filter((r) => r.name !== who); say(`Added ${who} to the whitelist`); }
        } else if (sub === "remove" && named(who)) {
          if (!p.whitelist.includes(who)) say("Player is not whitelisted");
          else { p.whitelist = p.whitelist.filter((x) => x !== who); say(`Removed ${who} from the whitelist`); }
        } else if (sub === "list") say(`There are ${p.whitelist.length} whitelisted player(s): ${p.whitelist.join(", ")}`);
        else if (sub === "on") { p.whitelist_enabled = true; s.properties["white-list"] = "true"; say("Whitelist is now turned on"); }
        else if (sub === "off") { p.whitelist_enabled = false; s.properties["white-list"] = "false"; say("Whitelist is now turned off"); }
        else if (sub === "reload") say("Reloaded the whitelist");
        else say("Unknown or incomplete command, see below for error");
        break;
      }
      case "banlist": say(p.bans.length ? `There are ${p.bans.length} ban(s): ${p.bans.map((b) => `${b.name} was banned by ${b.source}: ${b.reason}`).join("; ")}` : "There are no bans"); break;
      case "gamerule": {
        const rules = RULE_NAMES();
        if (!rules.includes(words[1])) { say("Incorrect argument for command"); break; }
        if (words[2] === undefined) say(`Gamerule ${words[1]} is currently set to: ${s.world.rules[words[1]]}`);
        else { s.world.rules[words[1]] = words[2]; say(`Gamerule ${words[1]} is now set to: ${words[2]}`); }
        break;
      }
      case "worldborder":
        if (words[1] === "get") say(`The world border is currently ${Math.round(s.world.border)} block(s) wide`);
        else if (words[1] === "set" && Number(words[2]) > 0) { s.world.border = Number(words[2]); say(`Set the world border to ${s.world.border} block(s) wide`); }
        else say("Unknown or incomplete command, see below for error");
        break;
      case "tick": if (words[1] === "query") { say("The game is running normally"); say("Target tick rate: 20.0 per second."); say("Average time per tick: 21.7ms (Target: 50.0ms)"); } else say("Unknown or incomplete command, see below for error"); break;
      case "save-all": say("Saving the game (this may take a moment!)"); say("Saved the game"); break;
      case "save-on": say("Automatic saving is now enabled"); break;
      case "save-off": say("Automatic saving is now disabled"); break;
      case "stop": sim.submit(s, "stop", "stop"); break;
      case "chunky":
        if (!sim.hasMod(s, "chunky")) { say("Unknown or incomplete command, see below for error"); break; }
        if (words[1] === "start") { s.world.progress = { done: 0, total: 1600, world: "world" }; say("[Chunky] Task started for world."); }
        else if (words[1] === "cancel") { s.world.progress = null; say("[Chunky] Task cancelled for world."); }
        else say("[Chunky] Commands: start, pause, continue, cancel, radius, center, world, shape, progress");
        break;
      case "spark": say(sim.hasMod(s, "spark") ? "[⚡] Profiler starting (the demo doesn't make a real report)" : "Unknown or incomplete command, see below for error"); break;
      default: say("Unknown or incomplete command, see below for error"); say(`${raw}<--[HERE]`);
    }
  };

  // ------------------------------------------------------------- players
  const offlineError = (action) => new ApiError(400, `${action} only works while the server is running`);
  const playerAct = (s, action, name, reason) => {
    const p = s.players;
    const n = String(name || "").trim();
    const actions = ["kick", "ban", "pardon", "ban-ip", "pardon-ip", "op", "deop", "whitelist-add", "whitelist-remove", "whitelist-on", "whitelist-off"];
    if (!actions.includes(action)) throw new ApiError(400, `unknown action '${action}'`);
    if (action === "whitelist-on" || action === "whitelist-off") {
      p.whitelist_enabled = action === "whitelist-on";
      s.properties["white-list"] = String(p.whitelist_enabled);
      if (running(s)) { sim.say(s, `Whitelist is now turned ${p.whitelist_enabled ? "on" : "off"}`); return `sent: whitelist ${p.whitelist_enabled ? "on" : "off"}`; }
      return `whitelist ${p.whitelist_enabled ? "enabled" : "disabled"}`;
    }
    if (action === "ban-ip" || action === "pardon-ip") {
      const ip = /^\d{1,3}(\.\d{1,3}){3}$/.test(n) ? n : null;
      if (!ip && !(action === "ban-ip" && /^[A-Za-z0-9_]{3,16}$/.test(n))) throw new ApiError(400, `'${n}' is not a valid IP address or player name`);
      if (action === "ban-ip") {
        const addr = ip || `203.0.113.${40 + n.length}`;
        if (!p.ip_bans.some((b) => b.ip === addr)) p.ip_bans.push({ ip: addr, created: new Date().toISOString(), source: "craft-conductor", expires: "forever", reason: reason || "Banned by an operator." });
        if (!ip && p.online.includes(n)) sim.leave(s, n, "You are banned from this server.");
        if (running(s)) sim.say(s, `Banned IP ${addr}: ${reason || "Banned by an operator."}`);
        return `banned IP ${addr}`;
      }
      p.ip_bans = p.ip_bans.filter((b) => b.ip !== n);
      return `unbanned IP ${n}`;
    }
    if (!/^[A-Za-z0-9_]{3,16}$/.test(n)) throw new ApiError(400, `'${n}' is not a valid player name`);
    if (action === "kick" && !running(s)) throw offlineError("kick");
    if (running(s)) {
      const before = s.console.seq;
      const command = { kick: `kick ${n}${reason ? " " + reason : ""}`, ban: `ban ${n}${reason ? " " + reason : ""}`, pardon: `pardon ${n}`,
        op: `op ${n}`, deop: `deop ${n}`, "whitelist-add": `whitelist add ${n}`, "whitelist-remove": `whitelist remove ${n}` }[action];
      sim.runCommand(s, command);
      const said = s.console.lines.filter((l) => l.seq > before).map((l) => l.text.split("]: ").pop()).join(" ");
      if (/No player was found|does not exist/.test(said)) throw new ApiError(400, action === "kick" ? `${n} isn't online` : `there is no Minecraft account named '${n}'`);
      return said || `sent: ${command}`;
    }
    // A stopped server: Craft Conductor edits Minecraft's files itself.
    if (action === "pardon") { if (!p.bans.some((b) => b.name === n)) throw new ApiError(400, `${n} is not banned`); p.bans = p.bans.filter((b) => b.name !== n); return `unbanned ${n}`; }
    if (action === "deop") { if (!p.ops.some((o) => o.name === n)) throw new ApiError(400, `${n} is not an operator`); p.ops = p.ops.filter((o) => o.name !== n); return `${n} is no longer an operator`; }
    if (action === "whitelist-remove") { if (!p.whitelist.includes(n)) throw new ApiError(400, `${n} is not whitelisted`); p.whitelist = p.whitelist.filter((x) => x !== n); return `removed ${n} from the whitelist`; }
    sim.known(s, n);
    if (action === "op") { const level = Number(s.properties["op-permission-level"] || 4); p.ops = p.ops.filter((o) => o.name !== n).concat({ name: n, level }); return `made ${n} an operator (level ${level})`; }
    if (action === "ban") { p.bans = p.bans.filter((b) => b.name !== n).concat({ name: n, reason: reason || "Banned by an operator.", created: new Date().toISOString().replace("T", " ").slice(0, 19) + " +0000", source: "craft-conductor" }); return `banned ${n}`; }
    if (!p.whitelist.includes(n)) p.whitelist.push(n);
    p.requests = p.requests.filter((r) => r.name !== n);
    return `added ${n} to the whitelist`;
  };
  const activity = (s, days) => {
    const since = now() - days * 86400;
    const visits = s.players.history.filter((h) => (h.end || now()) > since);
    const per = new Map();
    for (const v of visits) {
      const e = per.get(v.name) || { name: v.name, seconds: 0, visits: 0, last_seen: 0, online: false };
      e.seconds += Math.round((v.end || now()) - Math.max(v.start, since));
      e.visits += 1;
      e.last_seen = Math.max(e.last_seen, v.end || now());
      e.online = e.online || (!v.end && s.players.online.includes(v.name));
      per.set(v.name, e);
    }
    const week = Array.from({ length: 7 }, () => Array(24).fill(0));
    for (const v of visits) {
      for (let t = Math.max(v.start, since); t < (v.end || now()); t += 3600) {
        const d = new Date(t * 1000);
        week[(d.getDay() + 6) % 7][d.getHours()] += 1 / Math.max(1, Math.round(days / 7));
      }
    }
    for (const row of week) for (let h = 0; h < 24; h++) row[h] = sim.round(row[h], 2);
    const by_hour = Array.from({ length: 24 }, (_, h) => sim.round(week.reduce((n, row) => n + row[h], 0) / 7, 3));
    let busiest = null;
    week.forEach((row, d) => row.forEach((v, h) => { if (!busiest || v > busiest.average) busiest = { weekday: d, day: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][d], hour: h, average: v }; }));
    const quietHour = by_hour.indexOf(Math.min(...by_hour));
    return { days, history_days: Math.min(days, sim.round((now() - Math.min(...s.players.history.map((h) => h.start), now())) / 86400)),
      enough: s.players.history.length > 10, players: [...per.values()].sort((a, b) => b.seconds - a.seconds), week, by_hour,
      quiet: { hour: quietHour, average: by_hour[quietHour], cron: `0 ${quietHour} * * *` }, busiest: busiest && busiest.average ? busiest : null,
      recent: visits.slice(-20).reverse().map((v) => ({ name: v.name, start: v.start, end: v.end || now(), online: !v.end })) };
  };

  // ------------------------------------------------------------- backups
  sim.makeBackup = (s, label, { quiet = false } = {}) => {
    const t = now();
    const stamp = new Date(t * 1000).toISOString().replace(/[-:]/g, "").replace("T", "-").slice(0, 15);
    const clean = String(label || "").trim().toLowerCase().replace(/[^a-z0-9.]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);
    const size = 9e6 + s.mods.length * 1.4e6 + s.players.history.length * 4e3 + Math.round(Math.random() * 2e6);
    const prev = s.backups[s.backups.length - 1];
    const changes = prev ? sim.backupChanges(prev, s) : null;
    const b = { name: `${stamp}-${clean || "manual"}.tar.gz`, label: clean || "manual", size: Math.round(size), time: t, snapshot: true, minecraft: s.minecraft,
      mods: s.mods.length, changes, holds: s.settings.backup_include.slice().sort(), locked: [], check: null,
      contents: s.mods.map((m) => m.slug), versions: Object.fromEntries(s.mods.map((m) => [m.slug, m.version])), loader: s.loader };
    s.backups.push(b);
    // (the oldest go, past the number to keep: the real app keeps 10 unless told otherwise)
    while (s.backups.length > Number(s.settings.backups_keep || 10)) { const old = s.backups.shift(); if (!quiet) sim.event(s, `Removed the oldest backup, ${old.name} (keeping ${s.settings.backups_keep})`); }
    if (!quiet) sim.event(s, `Backed up to ${b.name}`);
    return b;
  };
  sim.backupChanges = (b, s) => {
    const before = new Map((b.contents || []).map((slug) => [slug, (b.versions || {})[slug] || ""]));
    const out = [];
    if (b.minecraft !== s.minecraft) out.push(`Minecraft ${b.minecraft} -> ${s.minecraft}`);
    for (const m of s.mods) {
      if (!before.has(m.slug)) out.push(`+ ${m.name} ${m.version}`);
      else if (before.get(m.slug) && before.get(m.slug) !== m.version) out.push(`~ ${m.name} ${before.get(m.slug)} -> ${m.version}`);
    }
    for (const slug of before.keys()) if (!sim.hasMod(s, slug)) { const m = cat().mod(slug); out.push(`- ${m ? m.name : slug}`); }
    return out;
  };
  // Rolling back: the world, mods and settings as they were when the backup was made.
  sim.restoreBackup = (s, b) => {
    const keep = s.mods;
    s.mods = [];
    for (const slug of b.contents || keep.map((m) => m.slug)) sim.installMod(s, slug, { version: (b.versions || {})[slug] });
    for (const m of s.mods) { const was = keep.find((k) => k.slug === m.slug); if (was) Object.assign(m, { version: (b.versions || {})[m.slug] || was.version, filename: was.filename, channel: was.channel }); }
    s.minecraft = b.minecraft;
    s.loader_version = cat().loaderVersion(s.loader, s.minecraft);
    s.java_major = cat().javaFor(s.minecraft);
  };
  sim.job("backup", {
    duration: 2.5,
    begin: (s) => { if (running(s)) { sim.say(s, "Automatic saving is now disabled"); sim.say(s, "Saving the game (this may take a moment!)"); sim.say(s, "Saved the game"); } },
    steps: [],
    end: (s, p) => { const b = sim.makeBackup(s, p.label); b.check = { ok: true, files: 22, regions: 7, detail: "22 files, a world with 7 region file(s)", checked: now() };
      if (running(s)) sim.say(s, "Automatic saving is now enabled"); return `backed up to ${b.name}`; },
  });
  sim.job("check backup", { duration: 2, steps: [], end: (s, p) => {
    const b = s.backups.find((x) => x.name === p.name);
    if (!b) throw new Error("that backup isn't there any more");
    b.check = { ok: true, files: 18 + b.mods, regions: 6, detail: `${18 + b.mods} files, a world with 6 region file(s)`, checked: now() };
    return `${b.name} is fine: ${b.check.detail}`;
  } });
  sim.job("roll back", {
    duration: 4,
    begin: (s) => sim.event(s, "Rolling back to a backup"),
    steps: [[1, (s) => { sim.makeBackup(s, "before-rollback", { quiet: true }); }]],
    end: (s, p) => {
      const b = s.backups.find((x) => x.name === p.name);
      if (!b) throw new Error("that backup isn't there any more");
      sim.restoreBackup(s, b);
      sim.event(s, `Rolled back to ${b.name}`);
      return `rolled back to ${b.name}; what was there before is in a new backup (before-rollback)`;
    },
  });
  sim.job("put back an area", { duration: 3, steps: [], end: (s, p) => {
    const b = s.backups.find((x) => x.name === p.name) || s.backups[s.backups.length - 1];
    sim.makeBackup(s, "before-area", { quiet: true });
    return `put back ${p.chunks} chunk(s) from ${b.name}; what was there is in the backup before-area`;
  } });

  // ------------------------------------------------------------- Java
  const javaAnswer = (s) => {
    const hub = sim.state.hub;
    const wanted = cat().javaFor(s.minecraft);
    const major = s.java.forced ? Number(s.java.forced) : wanted;
    const shared = hub.javas.find((j) => j.major === major);
    const store = `${sim.HOME}\\.craft-conductor\\java`;
    const bin = (j) => `${store}\\${j.major}\\${j.release}\\${j.release}-jre\\bin\\java.exe`;
    const usedBy = (m) => sim.state.servers.filter((x) => (x.java.forced ? Number(x.java.forced) : cat().javaFor(x.minecraft)) === m).map((x) => x.name);
    return {
      required: wanted, forced: s.java.forced, auto_install: true,
      choice: shared ? { source: "shared", binary: bin(shared), major, wanted, release: shared.release, note: `shared Java ${major} (${shared.release}), in ${store}`,
        also: usedBy(major).filter((n) => n !== s.name), newer: [] }
        : { source: "missing", binary: null, major, wanted, release: null, note: `Java ${major} isn't installed yet: it's downloaded at the next start`, also: [], newer: [] },
      store, shared: hub.javas.map((j) => ({ major: j.major, used_by: usedBy(j.major), releases: [{ release: j.release, path: bin(j), bytes: j.bytes, running: sim.state.servers.some((x) => running(x) && cat().javaFor(x.minecraft) === j.major), newest: true }] })),
      found: [{ path: "C:\\Program Files\\Microsoft\\jdk-17.0.12.7-hotspot\\bin\\java.exe", source: "installed", major: 17, arch: "x64", vendor: "Microsoft", version: "17.0.12+7", problem: "" },
        { path: "C:\\Program Files\\Java\\jre1.8.0_421\\bin\\java.exe", source: "installed", major: 8, arch: "x32", vendor: "Oracle Corporation", version: "1.8.0_421-b09", problem: "built for 32-bit x86, and this computer is x64 (64-bit Intel/AMD)" }],
      configured: [], default: "java", old_folder: null, old_bytes: 0,
    };
  };
  sim.job("install java", { duration: 4, steps: [[1, (s, p) => sim.event(s, `Downloading Java ${p.major} from Adoptium (simulated)`)]], end: (s, p) => {
    const hub = sim.state.hub;
    const release = { 8: "jdk8u422-b05", 11: "jdk-11.0.24+8", 17: "jdk-17.0.12+7", 21: "jdk-21.0.4+7", 25: "jdk-25+36" }[p.major] || `jdk-${p.major}`;
    if (!hub.javas.some((j) => j.major === p.major)) hub.javas.push({ major: p.major, release, bytes: 120e6 + p.major * 1e6, installed_at: now() });
    return `installed ${release}`;
  } });
  sim.job("update java", { duration: 3, steps: [], end: () => "the shared Java is up to date" });

  // ------------------------------------------------------------- settings
  const SETTINGS_KEYS = ["memory", "aikar_flags", "find_lag", "cpu_cores", "priority", "restart_on_crash", "strategy", "mod_channel", "auto_upgrade",
    "check_interval", "warn_minutes", "wait_for_empty", "verify_boot", "rehearse", "backups_keep", "discord_webhook", "schedule_restart",
    "schedule_backup", "restart_when_empty", "backup_copy_to", "backup_copy_keep", "backup_include", "tunnel_address", "minecraft", "java_version", "motd"];
  const scheduleWords = (cron) => {
    if (!cron) return "off";
    const m = String(cron).match(/^(\d{1,2}) (\d{1,2}) \* \* \*$/);
    return m ? `every day at ${m[2].padStart(2, "0")}:${m[1].padStart(2, "0")}` : cron;
  };
  const settingsAnswer = (s) => ({
    ...s.settings, memory: `${s.memory_gb}G`, cpu_count: 8, can_pin_cores: true, backup_copy_ok: true,
    schedule_restart_words: scheduleWords(s.settings.schedule_restart), schedule_restart_next: s.settings.schedule_restart ? now() + 6 * 3600 : null,
    schedule_backup_words: scheduleWords(s.settings.schedule_backup), schedule_backup_next: s.settings.schedule_backup ? now() + 9 * 3600 : null,
    port: Number(s.port), properties: { ...s.properties }, properties_schema: cat().propertiesSchema(),
    choices: { strategy: ["latest", "mods-only", "pinned"], mod_channel: ["release", "beta", "alpha"] },
  });
  const saveSettings = (s, body) => {
    const b = { ...body };
    const props = b.properties || null;
    delete b.properties;
    const whitelistOk = b.whitelist_off_ok === true;
    delete b.whitelist_off_ok;
    const schema = new Map(cat().propertiesSchema().map((p) => [p.key, p]));
    if (props) {
      for (const [k, v] of Object.entries(props)) {
        const def = schema.get(k);
        if (!def) throw new ApiError(400, `unknown server setting ${k}`);
        const val = String(v);
        if (def.kind === "int") {
          if (!/^-?\d+$/.test(val)) throw new ApiError(400, `${def.label} must be a whole number`);
          if (def.max && (Number(val) < def.min || Number(val) > def.max)) throw new ApiError(400, `${def.label} must be between ${def.min} and ${def.max}`);
        } else if (def.kind === "bool" && !["true", "false"].includes(val)) throw new ApiError(400, `${def.label} must be true or false`);
        else if (def.kind === "choice" && !def.choices.includes(val)) throw new ApiError(400, `pick one of the choices for ${def.label}`);
        else if (def.max_len && val.length > def.max_len) throw new ApiError(400, `${def.label} is too long`);
      }
      if (props["white-list"] === "false" && s.properties["white-list"] === "true" && !whitelistOk && whitelistGuarded(s)) {
        throw new ApiError(409, rel().whitelist_warning, "whitelist-off");
      }
    }
    if (b.port !== undefined) {
      const port = Number(b.port);
      if (!Number.isInteger(port)) throw new ApiError(400, "the port must be a number");
      if (port < 1024 || port > 65535) throw new ApiError(400, "the port must be between 1024 and 65535");
      const clash = sim.state.servers.find((x) => x !== s && Number(x.port) === port);
      if (clash) throw new ApiError(400, `port ${port} is already used by another server here (${clash.name})`);
      if ([8766, 58908].includes(port)) throw new ApiError(400, `Craft Conductor itself uses port ${port} (the control panel or friends' downloads); pick another`);
      s.port = port;
      s.properties["server-port"] = String(port);
      delete b.port;
    }
    for (const [k, v] of Object.entries(b)) {
      if (!SETTINGS_KEYS.includes(k)) throw new ApiError(400, `unknown setting ${k}`);
      if (k === "memory") {
        const m = String(v).trim().match(/^(\d{1,3})\s*[gG]$/);
        if (!m || Number(m[1]) < 1) throw new ApiError(400, "memory is a number of gigabytes, like 4G");
        s.memory_gb = Number(m[1]);
      } else if (k === "discord_webhook" && v) {
        s.settings.discord_webhook = "";  // (never kept: the demo doesn't store web addresses with keys in them)
        sim.emit("note", { text: "Demo: the webhook wasn't kept. In the real app, server messages go to that Discord channel." });
      } else if (k === "minecraft") {
        s.settings.pinned_minecraft = String(v);
      } else if (k === "java_version") {
        s.java.forced = v === "auto" || !v ? null : Number(v);
      } else if (k === "motd") {
        s.name = String(v).slice(0, 59) || s.name;
        s.properties.motd = s.name;
      } else s.settings[k] = v;
    }
    if (props) {
      for (const [k, v] of Object.entries(props)) s.properties[k] = String(v);
      if ("white-list" in props) s.players.whitelist_enabled = props["white-list"] === "true";
      if ("max-players" in props) s.max_players = Number(props["max-players"]);
      if ("gamemode" in props) s.gamemode = props.gamemode;
    }
    if (running(s)) s.restartNeeded = true;
    return { ok: true };
  };
  sim.reachable = (s) => sim.whyReachable(s).length > 0;
  sim.whyReachable = (s) => {
    const why = [];
    if (s.reach === "playit") why.push("playit.gg is chosen for friends outside");
    if (s.reach === "forward") why.push(`port ${s.port} is to be forwarded on the router`);
    if (sim.state.hub.upnp) why.push("Router (UPnP) opens its port");
    if (s.settings.tunnel_address) why.push("a playit.gg address is set");
    if (sim.state.hub.share.address && s.reach !== "home") why.push("a public address is set in Sharing with friends");
    return why;
  };
  sim.reach = (s) => ({
    way: s.reach || "", port: Number(s.port), bedrock: { on: sim.hasMod(s, "geyser"), port: 19132, wanted: null }, reachable: sim.whyReachable(s),
    whitelist_on: s.players.whitelist_enabled, running: running(s), lan_ip: "192.168.1.50", upnp: sim.state.hub.upnp,
    tunnel_address: s.settings.tunnel_address || "", range: [30000, 39999],
    playit: { platform: "windows", agent: false, install: { state: "idle" }, apt: (rel().playit || {}).apt || [], download_page: "https://playit.gg/download", guide: "https://playit.gg/support/", signer: "Developed Methods LLC" },
    router_risks: rel().router_risks || "", playit_downsides: rel().playit_downsides || "", whitelist_warning: rel().whitelist_warning || "",
    status_page: "https://status.playit.gg", any_port: sim.state.hub.risks.includes("any-port"),
  });

  // ------------------------------------------------------------- the check-ups
  const doctor = (s) => {
    const c = (id, title, status, detail, fix = "", action = "", action_label = "") => ({ id, title, status, detail, fix, action, action_label });
    const broken = sim.startProblem(s);
    return { checks: [
      c("installed", "Server installed", s.setup_pending ? "bad" : "ok", s.setup_pending ? "Not installed yet." : `Minecraft ${s.minecraft} with ${s.loader}.`),
      c("java", "Java", "ok", `Java ${s.java_major} is ready: shared Java ${s.java_major}, in ${sim.HOME}\\.craft-conductor\\java.`),
      broken ? c("mods", "Mods work together", "bad", `${cat().mod(broken).name} needs ${cat().mod(cat().mod(broken).missing).name}, which isn't installed.`, "Add it on the Mods page, or remove the mod that needs it.")
        : c("mods", "Mods work together", "ok", "Every mod has the mods and versions it says it needs."),
      c("memory", "Memory", "ok", `The server uses ${s.memory_gb}.0 GB of this computer's 16 GB.`),
      c("disk", "Disk space", "ok", "588 GB free."),
      running(s) ? c("port", `Port ${s.port}`, "ok", "The server is taking connections on this computer.")
        : c("port", `Port ${s.port}`, "info", "The server isn't running, so nothing is listening on its port yet."),
      sim.state.hub.upnp ? c("router", "Router port forwarding", "ok", `Your router forwards port ${s.port} to this computer (UPnP).`)
        : c("router", "Router port forwarding", "info", "Friends outside your home need the port forwarded on your router.", "Turn on Open ports on my router by itself (Craft Conductor settings → Sharing with friends), or forward it by hand (Help → Router setup).", "upnp", "Ask my router (UPnP)"),
      c("share", "Friends' downloads", s.client.enabled ? "ok" : "info", s.client.enabled ? `Running on port 8766${sim.state.hub.share.address ? `, for ${sim.state.hub.share.address}` : ""}.` : "Off: switch it on on the Friends page to send friends an invite."),
      c("firewall", "Windows Firewall", "info", "Windows asks the first time the server starts whether Java may accept connections.", "Choose Allow, with both private and public networks ticked."),
    ] };
  };

  // ------------------------------------------------------------- pictures
  // A player's face (the real app shows their Minecraft skin's face): a made-up 8×8 face per name.
  const FACE_COLOURS = ["#8B5A2B", "#C68642", "#E0AC69", "#F1C27D", "#5C3A21", "#3B2219"];
  const HAIR = ["#2B1B0F", "#6B4423", "#D9A441", "#111111", "#A0522D", "#E6C27A", "#B22222"];
  const hash = (text) => { let h = 2166136261; for (const ch of String(text)) h = Math.imul(h ^ ch.charCodeAt(0), 16777619) >>> 0; return h; };
  sim.face = (name) => {
    const h = hash(name);
    const skin = FACE_COLOURS[h % FACE_COLOURS.length], hair = HAIR[(h >> 4) % HAIR.length], eyes = ["#3A6EA5", "#2E8B57", "#5B3A29", "#222"][(h >> 8) % 4];
    const px = (x, y, c) => `<rect x="${x}" y="${y}" width="1" height="1" fill="${c}"/>`;
    let out = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8" shape-rendering="crispEdges"><rect width="8" height="8" fill="${skin}"/><rect width="8" height="2" fill="${hair}"/>`;
    if ((h >> 12) % 2) out += px(0, 2, hair) + px(7, 2, hair);
    out += px(1, 4, "#fff") + px(2, 4, eyes) + px(5, 4, eyes) + px(6, 4, "#fff") + `<rect x="3" y="6" width="2" height="1" fill="#6b3b2a"/></svg>`;
    return "data:image/svg+xml;base64," + btoa(out);
  };

  // ------------------------------------------------------------- the routes
  sim.serverRoutes({
    "GET /api/status": (r) => sim.status(r.s),
    "GET /api/console": (r) => {
      const since = Number(r.q.since || 0);
      const lines = r.s.console.lines.filter((l) => l.seq > since);
      return { lines: lines.map((l) => ({ seq: l.seq, text: l.text, user: l.user })), last: r.s.console.seq };
    },
    "GET /api/events": (r) => {
      const since = Number(r.q.since || 0);
      return { events: r.s.events.list.filter((e) => e.seq > since), last: r.s.events.seq };
    },
    "POST /api/command": (r) => {
      const s = r.s;
      const command = String(r.b.command || "").trim().replace(/^\//, "");
      if (!command) throw new ApiError(400, "enter a command");
      if (/[\r\n]/.test(command)) throw new ApiError(400, "enter a single command (it can't have line breaks)");
      if (/[\x00-\x1f\x7f]/.test(command)) throw new ApiError(400, "a console command can't contain control characters");
      if (command.length > 1000) throw new ApiError(400, "that command is too long (at most 1000 characters)");
      if (!running(s)) throw new ApiError(409, "the server isn't running");
      sim.say(s, `> ${command}`, { user: true });
      sim.runCommand(s, command);
      return { ok: true };
    },
    "POST /api/server/start": (r) => {
      const s = r.s;
      if (running(s)) { s.want_running = true; return { ok: true, job: "start" }; }
      if (s.setup_pending) throw new ApiError(409, "the server isn't set up yet");
      const plan = sim.state.servers.filter((x) => x !== s && (running(x) || x.state === "starting")).reduce((n, x) => n + x.memory_gb, s.memory_gb);
      if (plan > 13) sim.event(s, `The running servers are given ${plan} GB of memory with this one, and this computer has 16 GB: it may slow down`, "warning");
      s.everStarted = true;
      return sim.submit(s, "start", "start");
    },
    "POST /api/server/stop": (r) => { if (r.s.state === "stopped") return { ok: true, job: "stop" }; return sim.submit(r.s, "stop", "stop"); },
    "POST /api/server/restart": (r) => { if (!running(r.s)) return sim.submit(r.s, "start", "start"); return sim.submit(r.s, "restart", "restart"); },
    "GET /api/setup": (r) => ({ ...sim.setupOptions(), pending: !!r.s.setup_pending, network_option: false, network_access: sim.state.hub.network_access,
      server_dir: dir(r.s), current: { loader: r.s.loader, minecraft: r.s.minecraft, memory_gb: r.s.memory_gb,
        mods: r.s.mods.filter((m) => !m.dependency_of && !m.manual && m.slug !== "fabric-api").map((m) => ({ slug: m.slug, required: m.required !== false })) } }),
    "POST /api/setup": (r) => {
      const s = r.s;
      busy(s);
      if (running(s)) throw new ApiError(409, "stop the server first");
      const b = r.b;
      if (b.loader) s.loader = String(b.loader);
      if (b.minecraft) s.minecraft = b.minecraft === "latest" ? cat().newestFor(s.loader) : String(b.minecraft);
      if (b.motd) s.name = String(b.motd).slice(0, 59);
      s.pendingMods = (b.mods || []).map(String);
      s.setup_pending = true;
      return sim.submit(s, "set up server", "setup", {});
    },
    "POST /api/problem/fix": (r) => {
      const s = r.s, kind = String(r.b.kind || "");
      if (kind === "dismiss") { s.problem = null; return { ok: true, message: "Dismissed" }; }
      const offered = ((s.problem || {}).actions || []).find((a) => a.kind === kind);
      if (!offered) throw new ApiError(409, "that's not on offer any more");
      let message = "";
      if (kind === "add-mod") {
        const m = sim.installMod(s, offered.id);
        m.installed = false;
        message = `Added ${offered.name}: it's installed with the next update check or start`;
      } else message = "Done";
      s.problem = { ...s.problem, fixed: message };
      return { ok: true, message };
    },

    // Players.
    "GET /api/players": (r) => {
      const p = r.s.players;
      const uuid = (name) => (p.known.find((k) => k.name === name) || { uuid: sim.uuid(name) }).uuid;
      return { running: running(r.s), online: running(r.s) ? p.online.slice() : [], ops: p.ops.map((o) => ({ name: o.name, uuid: uuid(o.name), level: o.level })),
        whitelist_enabled: p.whitelist_enabled, whitelist: p.whitelist.map((name) => ({ name, uuid: uuid(name) })),
        bans: p.bans.map((b) => ({ name: b.name, uuid: uuid(b.name), reason: b.reason, created: b.created, source: b.source })), ip_bans: p.ip_bans.slice(),
        known: p.known.map((k) => ({ name: k.name, uuid: k.uuid })), online_mode: r.s.properties["online-mode"] !== "false" };
    },
    "GET /api/players/online": (r) => {
      const s = r.s, p = s.players;
      const out = { running: running(s), players: (running(s) ? p.online : []).map((name) => {
        const op = p.ops.find((o) => o.name === name);
        return { name, op: !!op, op_level: op ? op.level : null, ping_ms: null, ping_state: null };
      }), max: s.max_players, whitelist_enabled: p.whitelist_enabled,
      ping: { available: false, reason: "Minecraft doesn't share each player's ping with the server console, so Craft Conductor can't show it. (It never adds a mod or plugin only to measure it.)" } };
      if (r.q.whitelist === "1") out.whitelist = p.whitelist.slice().sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()));
      return out;
    },
    "GET /api/players/activity": (r) => ({ ...activity(r.s, Math.min(90, Number(r.q.days) || 30)), schedule_restart: r.s.settings.schedule_restart,
      schedule_restart_words: scheduleWords(r.s.settings.schedule_restart) }),
    "POST /api/players/action": (r) => {
      const s = r.s;
      if (s.state === "starting" || (s.state === "stopped" && s.job)) throw new ApiError(409, "the server is starting; try again in a moment");
      const action = String(r.b.action || "");
      if (action === "whitelist-off" && s.players.whitelist_enabled && whitelistGuarded(s) && r.b.whitelist_off_ok !== true) {
        throw new ApiError(409, rel().whitelist_warning, "whitelist-off");
      }
      if (action === "ban-ip" && cat().hasReach() && (s.reach === "playit" || s.settings.tunnel_address) && !/^[0-9A-Fa-f:.]{2,45}$/.test(String(r.b.name || "").trim())) {
        throw new ApiError(400, "players who join through playit.gg all come from this computer's address, so banning a player's IP would shut out everyone who joins through it, and you too. Ban the name instead");
      }
      const message = playerAct(s, action, r.b.name, r.b.reason ? String(r.b.reason).slice(0, 200) : "");
      return { ok: true, message };
    },
    "GET /api/players/skin": () => { throw new ApiError(400, "a player's face is a picture"); },
    "POST /api/broadcast": (r) => {
      const message = String(r.b.message || "").trim();
      if (!message) throw new ApiError(400, "write something to say");
      if (message.length > 256) throw new ApiError(400, "that's too long for Minecraft's chat (256 characters at most)");
      if (!running(r.s)) throw new ApiError(409, "the server isn't running");
      sim.say(r.s, `[Server] ${message}`);
      return { ok: true, message: "sent to everyone online" };
    },
    "GET /api/join-requests": (r) => ({ requests: r.s.players.requests.map((x) => ({ name: x.name, time: x.time, via: x.via || "invite" })), whitelist_on: r.s.players.whitelist_enabled }),
    "POST /api/join-requests/answer": (r) => {
      const s = r.s;
      const name = String(r.b.name || "").trim();
      if (!/^[A-Za-z0-9_]{3,16}$/.test(name)) throw new ApiError(400, "that isn't a Minecraft name");
      let message = `ignored ${name}`;
      if (r.b.allow === true) {
        message = playerAct(s, "whitelist-add", name);
        sim.event(s, `Let ${name} in (whitelist)`);
        // (they were waiting: in the real game they'd join again now; here they do a moment later)
        if (running(s)) setTimeout(() => { if (sim.join(s, name)) sim.changed(); }, 2500);
      } else sim.event(s, `Ignored ${name}'s request to join`);
      s.players.requests = s.players.requests.filter((x) => x.name !== name);
      return { ok: true, message };
    },

    // Backups.
    "GET /api/backups": (r) => ({ backups: r.s.backups.slice().reverse().map((b) => ({ name: b.name, size: b.size, time: b.time, check: b.check, snapshot: b.snapshot,
      minecraft: b.minecraft, mods: b.mods, changes: b.changes, holds: b.holds, locked: b.locked })) }),
    "POST /api/backups/create": (r) => sim.submit(r.s, "backup", "backup", { label: String(r.b.label || "").slice(0, 60) }),
    "POST /api/backups/check": (r) => { if (!r.s.backups.some((b) => b.name === r.b.name)) throw new ApiError(404, "no such backup"); return sim.submit(r.s, "check backup", "check backup", { name: r.b.name }); },
    "POST /api/backups/restore": (r) => {
      const s = r.s;
      if (!s.backups.some((b) => b.name === r.b.name)) throw new ApiError(404, "no such backup");
      if (running(s)) throw new ApiError(409, "stop the server first: restoring replaces the world it's using");
      return sim.submit(s, "roll back", "roll back", { name: r.b.name });
    },
    "GET /api/backups/changes": (r) => {
      const b = r.s.backups.find((x) => x.name === r.q.name);
      if (!b) throw new ApiError(404, "no such backup");
      return { snapshot: true, undo: sim.backupChanges(b, r.s) };
    },
    "POST /api/backups/area": (r) => {
      const s = r.s;
      if (running(s)) throw new ApiError(409, "stop the server first");
      if (!s.backups.some((b) => b.name === r.b.name)) throw new ApiError(404, "no such backup");
      const size = Math.max(1, Math.abs(Number(r.b.x2 || 0) - Number(r.b.x1 || 0)) + 1);
      return sim.submit(s, "put back an area", "put back an area", { name: r.b.name, chunks: Math.max(1, Math.round(size / 16) ** 2) });
    },
    "GET /api/export": (r) => ({ folder: `${sim.HOME}\\exports\\${r.s.id}`, exports: r.s.exports, parts: ["world", "mods", "players"], sensitive: ["invite_secret"], has_backups: r.s.backups.length > 0 }),
    "POST /api/export": (r) => {
      const s = r.s;
      const name = `${s.id}-${new Date().toISOString().slice(0, 10)}.zip`;
      s.exports = s.exports.filter((x) => x.name !== name).concat({ name, size: 24e6, time: now(), encrypted: !!r.b.encrypt });
      const started = { ok: true, job: "export" };
      return r.b.encrypt ? { ...started, password: "demo-not-a-real-password" } : started;
    },
    "POST /api/export/delete": (r) => { r.s.exports = r.s.exports.filter((x) => x.name !== r.b.name); return { ok: true }; },
    "GET /api/export/download": () => { throw new ApiError(400, "a download"); },
    "POST /api/world/replace": () => { throw sim.explain("Craft Conductor would swap this server's world for one of your single-player worlds (backing up the old one first). The demo can't read your Minecraft saves."); },

    // Java.
    "GET /api/java": (r) => javaAnswer(r.s),
    "POST /api/java/install": (r) => {
      const major = Number(r.b.major);
      if (![8, 11, 16, 17, 21, 25].includes(major)) throw new ApiError(400, "pick a Java version Minecraft uses (8, 11, 16, 17, 21 or 25)");
      return sim.submit(r.s, `install Java ${major}`, "install java", { major });
    },
    "POST /api/java/use": (r) => {
      const b = r.b;
      if (b.source === "auto" || b.major === "auto" || b.version === "auto") r.s.java.forced = null;
      else if (b.major) r.s.java.forced = Number(b.major);
      else if (b.path) r.s.java.forced = /jdk-17/.test(b.path) ? 17 : /1\.8|jre1\.8/.test(b.path) ? 8 : r.s.java.forced;
      return { ok: true, note: "applies the next time the server starts" };
    },
    "POST /api/java/scan": () => ({ ok: true, count: 2 }),
    "POST /api/java/update": (r) => sim.submit(r.s, "update the shared Java", "update java", {}),
    "POST /api/java/remove": (r) => {
      const major = Number(r.b.major);
      const users = sim.state.servers.filter((x) => cat().javaFor(x.minecraft) === major && !x.java.forced);
      if (users.length) throw new ApiError(409, `Java ${major} is used by ${users.map((x) => x.name).join(", ")}`);
      sim.state.hub.javas = sim.state.hub.javas.filter((j) => j.major !== major);
      return { ok: true };
    },

    // Settings.
    "GET /api/settings": (r) => settingsAnswer(r.s),
    "POST /api/settings": (r) => saveSettings(r.s, r.b),

    // World tools (game rules, the border, pre-generating with Chunky).
    "GET /api/world/tools": (r) => {
      const s = r.s;
      const chunky = sim.hasMod(s, "chunky");
      if (!running(s)) return { running: false, chunky };
      return { running: true, rules: (rel().gamerules || []).map((x) => ({ id: x.id, kind: x.kind, value: String(s.world.rules[x.id] ?? x.default), words: x.words })),
        border: s.world.border, chunky, progress: s.world.progress ? { ...s.world.progress, percent: sim.round(100 * s.world.progress.done / s.world.progress.total) } : null };
    },
    "POST /api/world/rule": (r) => {
      const s = r.s;
      if (!running(s)) throw new ApiError(409, "start the server first: game rules are changed in the running game");
      const rule = String(r.b.rule || ""), value = String(r.b.value || "");
      if (!/^[A-Za-z_]{2,40}$/.test(rule)) throw new ApiError(400, "that isn't a game rule");
      if (!/^(true|false|-?\d{1,9})$/.test(value)) throw new ApiError(400, "a game rule is true, false or a number");
      if (!RULE_NAMES().includes(rule)) { sim.say(s, `> gamerule ${rule} ${value}`, { user: true }); sim.say(s, "Incorrect argument for command"); throw new ApiError(400, `the server doesn't know a game rule called ${rule}`); }
      s.world.rules[rule] = value;
      sim.say(s, `> gamerule ${rule} ${value}`, { user: true });
      sim.say(s, `Gamerule ${rule} is now set to: ${value}`);
      return { ok: true, message: `Gamerule ${rule} is now set to: ${value}` };
    },
    "POST /api/world/border": (r) => {
      const s = r.s;
      if (!running(s)) throw new ApiError(409, "start the server first");
      const d = Number(r.b.diameter);
      if (!(d >= 16 && d <= 59999968)) throw new ApiError(400, "the border is 16 to 59,999,968 blocks wide");
      s.world.border = d;
      sim.say(s, `Set the world border to ${d} block(s) wide`);
      return { ok: true, message: `Set the world border to ${d} block(s) wide, centred on ${r.b.x || 0}, ${r.b.z || 0}` };
    },
    "POST /api/world/chunky": (r) => {
      const s = r.s;
      if (!sim.hasMod(s, "chunky")) throw new ApiError(400, "add Chunky first (it pre-generates the world)");
      if (!running(s)) throw new ApiError(409, "start the server first");
      const action = String(r.b.action || "");
      if (action === "start") { const radius = Number(r.b.radius || 1000); s.world.progress = { done: 0, total: Math.round((radius / 16) ** 2 * 4), world: "world", radius }; sim.say(s, `[Chunky] Task started for world. Radius ${radius}.`); return { ok: true, message: `Pre-generating ${radius} blocks around the spawn` }; }
      if (action === "cancel" || action === "stop") { s.world.progress = null; sim.say(s, "[Chunky] Task cancelled for world."); return { ok: true, message: "Stopped pre-generating" }; }
      if (action === "pause") return { ok: true, message: "Paused" };
      return { ok: true, message: "Done" };
    },
    "GET /api/webmap": (r) => ({ kind: r.s.webmap, listed: r.s.webmap, maps: { bluemap: "BlueMap", dynmap: "Dynmap" }, running: running(r.s), minecraft: r.s.minecraft,
      available: { bluemap: !!cat().build("bluemap", r.s.minecraft, r.s.loader), dynmap: null }, runs_mods: cat().runsMods(r.s.loader),
      ...(r.s.webmap ? { url: `http://192.168.1.50:8100/`, port: 8100, accepted: !!r.s.webmapAccepted, needs_accept: !r.s.webmapAccepted } : {}) }),
    "POST /api/webmap/add": (r) => {
      const kind = String(r.b.kind || "");
      if (kind !== "bluemap") throw new ApiError(400, "the demo has BlueMap");
      if (!cat().build("bluemap", r.s.minecraft, r.s.loader)) throw new ApiError(400, `BlueMap has no build for Minecraft ${r.s.minecraft} on ${r.s.loader}`);
      const m = sim.installMod(r.s, "bluemap");
      m.installed = false;
      r.s.webmap = "bluemap";
      return { ok: true, name: "BlueMap", deps: [] };
    },
    "POST /api/webmap/accept": (r) => { r.s.webmapAccepted = true; return { ok: true }; },
    "POST /api/webmap/port": (r) => { const port = Number(r.b.port); if (!(port >= 1024 && port <= 65535)) throw new ApiError(400, "pick a port between 1024 and 65535"); return { ok: true, message: `BlueMap uses port ${port} from the next start` }; },
    "GET /api/bedrock": (r) => ({ supported: ["fabric", "neoforge", "paper", "purpur"].includes(r.s.loader), geyser: sim.hasMod(r.s, "geyser"), floodgate: sim.hasMod(r.s, "floodgate"),
      installed: sim.hasMod(r.s, "geyser") && r.s.mods.find((m) => m.slug === "geyser").installed !== false, port: 19132, minecraft: r.s.minecraft }),
    "GET /api/bedrock/check": (r) => {
      const mods = ["geyser", "floodgate"].map((slug) => { const b = cat().build(slug, r.s.minecraft, r.s.loader); const m = cat().mod(slug); return { source: "modrinth", id: slug, name: m.name, ok: !!b, reason: b ? "" : `no build for Minecraft ${r.s.minecraft}` }; });
      return { mods, minecraft: r.s.minecraft };
    },
    "GET /api/tunnel": (r) => ({ address: r.s.settings.tunnel_address || "", status: r.s.settings.tunnel_address ? { status: "ok", words: "playit.gg is running (in the demo: made up)" } : null,
      agent: null, status_page: "https://status.playit.gg", download: "https://playit.gg/download" }),

    // Performance and the lag finder.
    "GET /api/performance": (r) => {
      const s = r.s;
      const cur = running(s) && s.perf.samples.length ? s.perf.samples[s.perf.samples.length - 1] : null;
      const bad = cur && cur.tps < 18;
      return { supported: true, running: running(s), current: cur, status: !running(s) ? "stopped" : bad ? "behind" : "ok",
        words: !running(s) ? "stopped" : bad ? "falling behind now and then" : "running smoothly", samples: s.perf.samples.slice(), spark: sim.hasMod(s, "spark"), spark_url: null };
    },
    "GET /api/performance/lag": (r) => ({ finder: sim.lagFinder(r.s), report: r.s.lag && r.s.lag.report || null }),
    "POST /api/performance/lag": (r) => { if (!running(r.s)) throw new ApiError(409, "start the server first"); r.s.lag = { started: now(), report: null }; return { ok: true }; },
    "POST /api/performance/lag/stop": (r) => { if (r.s.lag) r.s.lag.started = null; return { ok: true }; },
    "POST /api/performance/spark": (r) => {
      if (!sim.hasMod(r.s, "spark")) throw new ApiError(400, "add the spark mod first");
      if (!running(r.s)) throw new ApiError(409, "start the server first");
      sim.say(r.s, "[⚡] Profiler running for 30 seconds (in the demo, no report is made or uploaded).");
      return { ok: true, message: "profiling for 30 seconds; the report's link appears here and in the console" };
    },
    "GET /api/doctor": (r) => doctor(r.s),
    "POST /api/doctor/fix": (r) => {
      const action = String(r.b.action || "");
      if (action === "upnp") { sim.state.hub.upnp = true; return { ok: true, message: "Demo: no router was asked. In the real app, Craft Conductor asks your router to forward the port." }; }
      throw sim.explain("this fix changes things on the server's computer (Java, the firewall or the server's files), which the demo doesn't have.");
    },
    "POST /api/doctor/internet": (r) => ({ id: "internet", title: "Reachable from the internet", status: sim.reachable(r.s) && running(r.s) ? "ok" : "info",
      detail: sim.reachable(r.s) && running(r.s) ? `In the demo, ${sim.state.hub.share.address || "your address"}:${r.s.port} would be tested from outside. Nothing was sent anywhere.` : "Start the server and set up a way in (Help → Router setup, or a playit.gg tunnel) first.",
      fix: "", action: "", action_label: "" }),
    "GET /api/doctor/report": () => { throw new ApiError(400, "a download"); },
    "GET /api/play-here": (r) => ({ installed: !r.s.setup_pending, system_gb: 16, cpus: 8, server_gb: r.s.memory_gb, game_gb: 4, mods: r.s.mods.length, max_players: r.s.max_players }),
    "POST /api/play-here": () => { throw sim.explain("Craft Conductor would set up Minecraft on this computer, with this server's mods, to play on it here. The demo can't reach your launchers."); },
    "POST /api/open": () => { throw sim.explain("Craft Conductor would open this server's folder in your file manager, on the server's computer."); },
    "POST /api/manual/upload": (r) => ({ ok: true, name: (r.b.__file || {}).name || "mod.jar", filename: (r.b.__file || {}).name || "mod.jar", note: "In the demo the file isn't read." }),
    "POST /api/manual/stop": () => ({ ok: true }),

    // Configuration files: a few made-up ones per mod.
    "GET /api/configs": (r) => {
      const withFiles = r.s.mods.filter((m) => !m.manual && !["fabric-api", "krypton", "ferrite-core"].includes(m.slug)).slice(0, 6);
      return { mods: withFiles.map((m) => ({ mod_id: m.slug.replace(/-/g, "_"), name: m.name, jar: m.filename, files: [`config/${m.slug}.toml`] })),
        other: ["config/craft-conductor-demo.json"] };
    },
    "GET /api/configs/file": (r) => {
      const path = String(r.q.path || "");
      if (!/^config\/[\w.-]{1,100}\.(toml|json|properties|cfg|yml|yaml|txt)$/.test(path)) throw new ApiError(400, "that isn't a config file");
      if (!r.s.configFiles) r.s.configFiles = {};
      const text = r.s.configFiles[path] ?? (path.endsWith(".json") ? JSON.stringify({ note: "made up for the Craft Conductor demo", enabled: true }, null, 2) + "\n"
        : `# ${path} (made up for the Craft Conductor demo)\n[general]\n# How much the mod logs\nlogLevel = "info"\nenabled = true\n`);
      return { path, text, format: path.split(".").pop(), size: text.length, modified: r.s.configStamp || now() - 3600 };
    },
    "POST /api/configs/file": (r) => {
      const path = String(r.b.path || "");
      if (!/^config\/[\w.-]{1,100}\.(toml|json|properties|cfg|yml|yaml|txt)$/.test(path)) throw new ApiError(400, "that isn't a config file");
      const text = String(r.b.text ?? "");
      if (text.length > 512 * 1024) throw new ApiError(400, "that's too big");
      if (path.endsWith(".json")) { try { JSON.parse(text); } catch (e) { throw new ApiError(400, `that isn't valid JSON: ${e.message}`); } }
      if (r.b.modified && r.s.configStamp && Math.abs(r.b.modified - r.s.configStamp) > 0.001) throw new ApiError(409, "the file changed on disk since you opened it (maybe the mod rewrote it); reload it and make your change again");
      r.s.configFiles = { ...(r.s.configFiles || {}), [path]: text };
      r.s.configStamp = now();
      if (running(r.s)) r.s.restartNeeded = true;
      return { path, saved: true, modified: r.s.configStamp, size: text.length, running: running(r.s) };
    },
    // How friends outside your home join: playit.gg, a port on the router, or only at home.
    "GET /api/reach": (r) => sim.reach(r.s),
    "POST /api/reach": (r) => {
      const s = r.s, way = String(r.b.way || "");
      if (!["playit", "forward", "home"].includes(way)) throw new ApiError(400, "choose playit.gg, port forwarding, or only friends at home");
      let message = { playit: "Friends outside join through playit.gg", home: "Only friends on your network can join", forward: "" }[way];
      if (way === "forward") {
        const chosen = r.b.port;
        if (chosen !== undefined && chosen !== null && chosen !== "") {
          if (!sim.state.hub.risks.includes("any-port")) throw new ApiError(403, "choosing the port yourself is switched off (Craft Conductor settings → Advanced)");
          const port = Number(chosen);
          if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new ApiError(400, "the port is a number from 1024 to 65535");
          if (port !== Number(s.port) && (s.state !== "stopped" || s.job)) throw new ApiError(409, "stop the server first: it gets a new port");
          s.port = port;
        } else if (!(Number(s.port) >= 30000 && Number(s.port) <= 39999)) {
          if (s.state !== "stopped" || s.job) throw new ApiError(409, "stop the server first: it gets a new port");
          s.port = 30000 + Math.floor(Math.random() * 9999);
        }
        s.properties["server-port"] = String(s.port);
        message = `Forward TCP port ${s.port} on your router to this computer`;
      }
      s.reach = way;
      if (way !== "home" && !s.players.whitelist_enabled) { s.players.whitelist_enabled = true; s.properties["white-list"] = "true"; }
      return { ...sim.reach(s), ok: true, message };
    },
    "GET /api/modsets": (r) => ({ sets: r.s.modsets.map((x) => ({ name: x.name, saved: x.saved, mods: x.mods.length, minecraft: x.minecraft })) }),
    "POST /api/modsets/save": (r) => {
      const name = String(r.b.name || "").trim();
      if (!name) throw new ApiError(400, "give the list a name");
      const entry = { name, saved: now(), minecraft: r.s.minecraft, mods: r.s.mods.filter((m) => !m.dependency_of).map((m) => m.slug) };
      r.s.modsets = r.s.modsets.filter((x) => x.name !== name).concat(entry);
      return { ok: true, message: `saved '${name}' (${entry.mods.length} mods)` };
    },
    "POST /api/modsets/restore": (r) => {
      const entry = r.s.modsets.find((x) => x.name === r.b.name);
      if (!entry) throw new ApiError(404, "no such list");
      for (const m of r.s.mods.slice()) if (!entry.mods.includes(m.slug) && !m.dependency_of) r.s.mods = r.s.mods.filter((x) => x !== m);
      for (const slug of entry.mods) if (!sim.hasMod(r.s, slug)) { const m = sim.installMod(r.s, slug); m.installed = false; }
      return { ok: true, message: `switched to '${entry.name}': installed with the next update` };
    },
    "POST /api/modsets/delete": (r) => { r.s.modsets = r.s.modsets.filter((x) => x.name !== r.b.name); return { ok: true }; },
    "POST /api/modsets/import": () => { throw sim.explain("Craft Conductor would load a mod list from a file. The demo doesn't read your files."); },
    "GET /api/modsets/export": () => { throw new ApiError(400, "a download"); },
  });

  // ------------------------------------------------------------- pictures and downloads
  sim.picture = (url) => {
    const u = new URL(url, "https://demo.invalid/");
    const q = Object.fromEntries(u.searchParams);
    const path = u.pathname.replace(/^\/api\/servers\/[^/]+\//, "/api/");
    if (path === "/api/players/skin") return sim.face(q.name || "Steve");
    if (path === "/api/hub/preview/map") { const p = sim.state.hub.previews.find((x) => x.id === q.id); return p ? sim.mapImage(p) : sim.EMPTY_IMAGE; }
    if (path === "/api/hub/map/tile") { const p = sim.state.hub.previews.find((x) => x.id === q.id); return p ? sim.mapTile(p, Number(q.s), Number(q.x), Number(q.z)) : sim.EMPTY_IMAGE; }
    sim.unhandled.push(`GET ${u.pathname} (picture)`);
    sim.emit("unhandled", { method: "GET", path: u.pathname });
    return sim.EMPTY_IMAGE;
  };
  sim.EMPTY_IMAGE = "data:image/gif;base64,R0lGODlhAQABAAAAACw=";
  sim.downloadNote = (path) => {
    const p = path.replace(/^\/api\/servers\/[^/]+\//, "/api/");
    const what = { "/api/doctor/report": "a zip of the check-up and the logs, for a bug report", "/api/modsets/export": "the mod list as a file, to load on another server",
      "/api/export/download": "the exported server (a .zip to move it to another computer)" }[p] || "a file";
    return `Demo: in the real app this downloads ${what}. The demo has no files to download.`;
  };
})();
