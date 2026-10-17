"use strict";
// The website demo's simulated Craft Conductor: the real control panel (assets/app.js, unchanged)
// talks to this instead of a computer. Everything here is made up and stays in this browser tab:
// nothing is sent anywhere, no server runs, nothing on the visitor's computer changes.
//
// core.js: the shared pieces. A request is answered by the route registered for it
// (routes-*.js), from the state kept here (engine.js keeps it moving: jobs, players, the clock).
// boot.js puts it between the page and the network, and loads the real page's scripts.
(function () {
  const CCSim = window.CCSim = {
    state: null,        // the whole made-up world (saved by the website through boot.js)
    routes: new Map(),  // "GET /api/hub" -> handler; server routes are under "server:"
    unhandled: [],      // requests no route answers (the tests fail on any)
    explained: [],      // actions the demo only explains (shown to the visitor, counted by tests)
    files: new Map(),   // static files of the real app delivered as scripts (see boot.js)
    listeners: [],
  };

  // ------------------------------------------------------------- helpers
  CCSim.now = () => Date.now() / 1000;
  CCSim.clone = (x) => JSON.parse(JSON.stringify(x));
  CCSim.round = (x, n = 1) => Math.round(x * 10 ** n) / 10 ** n;
  CCSim.id = (n = 12) => Array.from(crypto.getRandomValues(new Uint8Array(n)), (b) => (b % 16).toString(16)).join("");
  CCSim.pick = (list) => list[Math.floor(Math.random() * list.length)];
  // A Minecraft player name: what the game allows (3 to 16 letters, digits and _).
  CCSim.playerName = (name) => {
    const n = String(name || "").trim();
    if (!/^[A-Za-z0-9_]{3,16}$/.test(n)) throw new CCSim.ApiError(400, "a player name is 3 to 16 letters, digits or _");
    return n;
  };
  // A stable made-up UUID for a player name (the same name always gets the same one).
  CCSim.uuid = (name) => {
    let h1 = 0x811c9dc5, h2 = 0x01000193;
    for (const ch of String(name).toLowerCase()) {
      h1 = Math.imul(h1 ^ ch.charCodeAt(0), 16777619) >>> 0;
      h2 = Math.imul(h2 + ch.charCodeAt(0), 2246822519) >>> 0;
    }
    const hex = (h1.toString(16).padStart(8, "0") + h2.toString(16).padStart(8, "0")).repeat(2);
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-5${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20, 32)}`;
  };
  CCSim.clock = (t = CCSim.now()) => new Date(t * 1000).toLocaleTimeString("en-GB", { hour12: false });

  class ApiError extends Error {
    // `confirm`: what the page asks before sending it again (web.py's ApiError(..., confirm=...)).
    constructor(status, message, confirm = "") { super(message); this.status = status; this.confirm = confirm; }
  }
  CCSim.ApiError = ApiError;
  // What the real Craft Conductor would do, for actions the demo can't do on the visitor's computer.
  CCSim.explain = (what) => {
    CCSim.explained.push(what);
    CCSim.emit("explained", { what });
    return new ApiError(400, "Demo: " + what);
  };

  CCSim.on = (fn) => CCSim.listeners.push(fn);
  CCSim.emit = (type, data) => { for (const fn of CCSim.listeners) { try { fn(type, data); } catch (_) { /* a listener's problem */ } } };

  // ------------------------------------------------------------- routes
  // route("GET /api/hub", fn) or route("POST /api/server/start", fn, { server: true }).
  // A handler gets { q (query), b (JSON body), s (the server, for server routes), path } and
  // returns the answer, or throws ApiError.
  CCSim.route = (key, fn, opts = {}) => CCSim.routes.set((opts.server ? "server:" : "") + key, fn);
  CCSim.serverRoutes = (table) => { for (const [k, fn] of Object.entries(table)) CCSim.route(k, fn, { server: true }); };
  CCSim.hubRoutes = (table) => { for (const [k, fn] of Object.entries(table)) CCSim.route(k, fn); };

  CCSim.server = (id) => {
    const s = CCSim.state.servers.find((x) => x.id === id);
    if (!s) throw new ApiError(404, "there's no server with that id");
    return s;
  };

  // A request from the page: GET /api/..., or /api/servers/<id>/... for one server's.
  CCSim.request = (method, url, body) => {
    const u = new URL(url, "https://demo.invalid/");
    const q = Object.fromEntries(u.searchParams);
    let path = u.pathname, s = null, key;
    const m = path.match(/^\/api\/servers\/([a-z0-9][a-z0-9-]*)\/(.+)$/);
    if (m) {
      path = "/api/" + m[2];
      key = `server:${method} ${path}`;
      try { s = CCSim.server(m[1]); } catch (e) { return { status: e.status, body: { error: e.message } }; }
    } else {
      key = `${method} ${path}`;
      if (!CCSim.routes.has(key) && CCSim.routes.has("server:" + key)) {  // (one server: /api/status)
        key = "server:" + key;
        s = CCSim.state.servers[0] || null;
        if (!s) return { status: 404, body: { error: "make a server first" } };
      }
    }
    const fn = CCSim.routes.get(key);
    if (!fn) {
      CCSim.unhandled.push(`${method} ${u.pathname}`);
      CCSim.emit("unhandled", { method, path: u.pathname });
      return { status: 501, body: { error: `Demo: this part of Craft Conductor (${method} ${path}) isn't simulated. Nothing was sent anywhere.` } };
    }
    try {
      const answer = fn({ q, b: body || {}, s, path, method });
      CCSim.changed();
      return { status: 200, body: answer === undefined ? { ok: true } : answer };
    } catch (e) {
      if (e instanceof ApiError) { CCSim.changed(); return { status: e.status, body: { error: e.message, ...(e.confirm ? { confirm: e.confirm } : {}) } }; }
      console.error("demo route failed", key, e);
      return { status: 500, body: { error: "Demo: something went wrong in the simulation (" + e.message + ")." } };
    }
  };

  // ------------------------------------------------------------- saving
  // The website keeps the state (boot.js passes it on): saved shortly after a change.
  let saveTimer = null;
  CCSim.changed = () => {
    if (saveTimer) return;
    saveTimer = setTimeout(() => { saveTimer = null; CCSim.emit("save", CCSim.state); }, 400);
  };

  // ------------------------------------------------------------- logs
  // The console as Minecraft writes it, and the server's event list (the Dashboard's "Events").
  CCSim.say = (s, text, { thread = "Server thread", level = "INFO", user = false } = {}) => {
    const line = user ? text : `[${CCSim.clock()}] [${thread}/${level}]: ${text}`;
    s.console.seq += 1;
    s.console.lines.push({ seq: s.console.seq, text: line, user });
    if (s.console.lines.length > 400) s.console.lines.splice(0, s.console.lines.length - 400);
  };
  CCSim.event = (s, message, level = "info") => {
    s.events.seq += 1;
    s.events.list.push({ seq: s.events.seq, time: CCSim.now(), level, message });
    if (s.events.list.length > 200) s.events.list.splice(0, s.events.list.length - 200);
  };
})();
