"use strict";
// The website's side of the demo (used by the homepage, website.js, and the phone demo, demo/index.html).
// It puts the real control panel (demo/app/) in a frame sandboxed WITHOUT allow-same-origin: the
// frame gets an origin of its own, so the panel's scripts can't reach this page, the invite page,
// the testing dashboard or their storage. The frame and this page only exchange messages:
//   frame -> page: "hello" (ready), "save" (the demo's state), "browser" (the panel's own settings),
//                  "note", "notification", "explained", "unhandled", "blocked" (shown or counted)
//   page -> frame: "init" (which demo, its saved state), "command" (the website's demo buttons)
// Only messages from that frame's window, from an opaque origin ("null"), are listened to.
(function () {
  const PREFIX = "craft-conductor-demo:v1:";
  const SCENARIOS = ["new", "existing"];
  const memory = {};  // (when this browser keeps nothing: a private window, or storage switched off)
  const read = (key) => {
    try { const v = localStorage.getItem(PREFIX + key); return v === null ? null : JSON.parse(v); } catch (_) { return memory[key] ?? null; }
  };
  const write = (key, value) => {
    memory[key] = value;
    try { localStorage.setItem(PREFIX + key, JSON.stringify(value)); } catch (_) { /* kept in memory for this page */ }
  };
  const forget = (key) => { delete memory[key]; try { localStorage.removeItem(PREFIX + key); } catch (_) { /* nothing kept */ } };

  // The demo's frame: the attributes that keep it apart (see the top of this file).
  function frame(title) {
    const f = document.createElement("iframe");
    f.title = title || "Craft Conductor demo (the real control panel, with made-up data)";
    f.setAttribute("sandbox", "allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox");
    f.setAttribute("allow", "clipboard-write");
    f.setAttribute("referrerpolicy", "no-referrer");
    f.setAttribute("loading", "eager");
    return f;
  }

  function attach(iframe, options = {}) {
    const appUrl = new URL(options.app || "app/", document.baseURI).href;
    let scenario = SCENARIOS.includes(options.scenario) ? options.scenario : "existing";
    let mobile = !!options.mobile, hash = options.hash || "";
    let ready = false, saveTimer = null, pending = null;
    // Each load of the frame is a session: what an earlier one sends as it goes (its last save,
    // after a reset) is ignored, so a reset really starts again.
    let session = 0;
    const listeners = [];
    const emit = (type, data) => { for (const fn of listeners) { try { fn(type, data); } catch (_) { /* a listener's problem */ } } };
    const stats = { unhandled: [], blocked: [], explained: [], notes: [] };

    const onMessage = (e) => {
      if (e.source !== iframe.contentWindow || e.origin !== "null" || !e.data || typeof e.data !== "object") return;
      const msg = e.data;
      if (msg.type !== "cc-demo-hello" && msg.session !== session) return;  // (a frame since replaced)
      switch (msg.type) {
        case "cc-demo-hello":
          ready = false;
          flush();  // (the frame reloaded itself: it gets the newest state)
          session += 1;
          iframe.contentWindow.postMessage({ type: "cc-demo-init", session, scenario, mobile, hash, state: read("state:" + scenario),
            browser: read("browser") || {}, theme: options.theme ? options.theme() : null }, "*");
          break;
        case "cc-demo-started": ready = true; emit("started", { scenario }); break;
        case "cc-demo-save":
          if (msg.state && typeof msg.state === "object" && msg.state.scenario === scenario) {
            pending = msg.state;
            if (!saveTimer) saveTimer = setTimeout(() => { saveTimer = null; if (pending) write("state:" + scenario, pending); pending = null; }, 250);
          }
          break;
        case "cc-demo-browser":
          if (msg.data && typeof msg.data === "object") {
            const clean = {};
            for (const [k, v] of Object.entries(msg.data)) if (typeof k === "string" && typeof v === "string" && k.length < 100 && v.length < 200000) clean[k] = v;
            write("browser", clean);
          }
          break;
        default: {
          const kind = String(msg.type || "").replace(/^cc-demo-/, "");
          if (["unhandled", "blocked", "explained"].includes(kind)) stats[kind].push(msg.data);
          if (["note", "notification", "explained", "unhandled", "blocked", "escape", "event"].includes(kind)) emit(kind, msg.data);
        }
      }
    };
    window.addEventListener("message", onMessage);
    const flush = () => { if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; } if (pending) write("state:" + scenario, pending); pending = null; };
    window.addEventListener("pagehide", flush);

    const load = () => { ready = false; session += 1; iframe.src = appUrl; };
    return {
      get scenario() { return scenario; },
      get ready() { return ready; },
      stats,
      on(fn) { listeners.push(fn); },
      // Open a demo: "new" (no servers yet) or "existing" (a server with friends on it).
      start(which, opts = {}) {
        flush();
        scenario = SCENARIOS.includes(which) ? which : "existing";
        if ("mobile" in opts) mobile = !!opts.mobile;
        hash = opts.hash || "";
        load();
      },
      hasSaved: (which) => !!read("state:" + which),
      // Start again: forgets both demos and the panel's settings kept for them.
      reset() {
        flush();
        for (const s of SCENARIOS) forget("state:" + s);
        forget("browser");
        load();
      },
      command(name, args = {}) {
        if (iframe.contentWindow) iframe.contentWindow.postMessage({ type: "cc-demo-command", command: name, args }, "*");
      },
      stop() { flush(); iframe.removeAttribute("src"); ready = false; },
      destroy() { flush(); window.removeEventListener("message", onMessage); window.removeEventListener("pagehide", flush); },
    };
  }

  window.CraftDemoHost = { frame, attach };
})();
