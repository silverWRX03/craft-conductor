"use strict";
// Starts the website demo inside its sandboxed frame, then loads the real control panel's scripts.
//
// The frame (demo/app/) is opened by the website (website.js) or the phone demo (demo/index.html)
// through host.js, with sandbox="allow-scripts allow-forms allow-popups ..." and *without*
// allow-same-origin: it runs in an origin of its own, apart from the website, the invite page
// and the testing dashboard, so nothing it does can reach their pages or storage. Its
// Content-Security-Policy (index.html) allows no network connections at all (connect-src 'none').
//
// Before the real page's scripts run, this replaces what in the real app reaches a computer or the
// browser's powers with the simulation (core.js):
//   fetch and XMLHttpRequest  -> /api/... answered by the simulation; the app's own files (the
//                                manual, translations) from scripts next to it; anything else refused
//   WebSocket, EventSource, sendBeacon, file pickers  -> not available
//   <img src="/api/...">      -> pictures drawn here (players' faces, map previews)
//   links and downloads       -> explained; outside https links open in a new tab
//   localStorage              -> kept by the website for this demo only (no real storage here)
//   service worker, push, notifications, passkeys -> pretend versions that never ask the browser
(function () {
  const script = document.currentScript;
  const APP_SCRIPTS = (script && script.dataset.app || "").split(/\s+/).filter(Boolean);
  const APP_STATIC = /^\/(?:screenshots\/[\w.-]+\.png|[\w-]+\.(?:png|svg)|manual\.md|i18n\/[a-z]{2}\.json)$/;
  const sim = window.CCSim;

  // Only ever inside the website's sandboxed frame. Opened any other way (its own tab, or framed
  // without the sandbox), it doesn't start: the real app's scripts never run with the site's origin.
  if (self.origin !== "null" || window.parent === window) {
    document.addEventListener("DOMContentLoaded", refuse);
    if (document.readyState !== "loading") refuse();
    return;
  }
  function refuse() {
    const p = document.createElement("p");
    p.className = "cc-demo-refused";
    p.append("This is part of the Craft Conductor website's demo. ");
    const a = document.createElement("a");
    a.href = "../";
    a.target = "_top";
    a.textContent = "Open the demo";
    p.append(a, ".");
    document.body.replaceChildren(p);
  }

  const origin = location.origin;  // (the website's: messages go only there)
  let demoSession = null;  // (given by the website with "init"; its messages carry it)
  const tell = (type, data) => parent.postMessage({ type, session: demoSession, ...data }, origin);

  // ------------------------------------------------------------ storage
  // A Storage-like object in memory; localStorage's is saved with the demo by the website.
  function memoryStorage(data, onChange) {
    const store = {
      getItem: (k) => Object.prototype.hasOwnProperty.call(data, k) ? data[k] : null,
      setItem: (k, v) => { data[String(k)] = String(v); onChange(); },
      removeItem: (k) => { delete data[String(k)]; onChange(); },
      clear: () => { for (const k of Object.keys(data)) delete data[k]; onChange(); },
      key: (i) => Object.keys(data)[i] ?? null,
      get length() { return Object.keys(data).length; },
    };
    return store;
  }
  let browserData = {};
  let browserTimer = null;
  const saveBrowser = () => {
    if (browserTimer) return;
    browserTimer = setTimeout(() => { browserTimer = null; tell("cc-demo-browser", { data: browserData }); }, 300);
  };
  const local = memoryStorage(browserData, saveBrowser);
  const session = memoryStorage({}, () => {});
  const define = (target, name, value) => Object.defineProperty(target, name, { configurable: true, enumerable: true, get: () => value });
  define(window, "localStorage", local);
  define(window, "sessionStorage", session);

  // ------------------------------------------------------------ the network
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const realFetch = window.fetch ? window.fetch.bind(window) : null;
  const refused = (what) => new TypeError(`Demo: ${what} isn't available in the demo (it has no network connections).`);
  async function readBody(body) {
    if (body === undefined || body === null) return {};
    if (typeof body === "string") { try { return JSON.parse(body); } catch (_) { return {}; } }
    if (body instanceof Blob) return { __file: { name: body.name || "file", size: body.size, type: body.type } };
    return {};
  }
  sim.loadFile = (path) => new Promise((resolve, reject) => {
    if (sim.files.has(path)) { resolve(sim.files.get(path)); return; }
    const el = document.createElement("script");
    el.src = "files" + path + ".js";  // (made by tools/build_website.py from the real app's file)
    el.onload = () => sim.files.has(path) ? resolve(sim.files.get(path)) : reject(refused(path));
    el.onerror = () => reject(refused(path));
    document.head.append(el);
  });
  sim.file = (path, text) => sim.files.set(path, text);
  window.fetch = async function (input, init = {}) {
    const req = input instanceof Request ? input : null;
    const url = new URL(req ? req.url : String(input), location.href);
    const method = String(init.method || (req && req.method) || "GET").toUpperCase();
    if (url.origin === origin && (url.pathname === "/api" || url.pathname.startsWith("/api/"))) {
      const body = await readBody(init.body);
      await sleep(20 + Math.random() * 60);  // (a little like a real computer answering)
      const r = sim.request(method, url.pathname + url.search, body);
      return new Response(JSON.stringify(r.body), { status: r.status, headers: { "Content-Type": "application/json" } });
    }
    if (url.origin === origin && APP_STATIC.test(url.pathname) && !url.pathname.endsWith(".png")) {
      const text = await sim.loadFile(url.pathname);
      const type = url.pathname.endsWith(".json") ? "application/json" : "text/markdown; charset=utf-8";
      return new Response(text, { status: 200, headers: { "Content-Type": type } });
    }
    sim.emit("blocked", { what: "fetch", url: url.href });
    throw refused("a connection to " + url.host);
  };
  void realFetch;  // (never used: kept only so nothing restores it by accident)

  // Uploads (a mod's .jar, a world .zip): the file never leaves the browser; only its name and size
  // reach the simulation.
  class DemoXHR extends EventTarget {
    constructor() {
      super();
      this.readyState = 0; this.status = 0; this.responseText = ""; this.response = "";
      this.upload = new EventTarget();
      this.onload = this.onerror = this.onloadend = this.onreadystatechange = null;
    }
    open(method, url) { this._method = String(method).toUpperCase(); this._url = new URL(url, location.href); this.readyState = 1; }
    setRequestHeader() {}
    getResponseHeader(name) { return /content-type/i.test(name) ? "application/json" : null; }
    abort() { this._aborted = true; }
    async send(body) {
      const fire = (target, type, init) => {
        const e = new ProgressEvent(type, init);
        const handler = target["on" + type];
        if (typeof handler === "function") handler.call(target, e);
        target.dispatchEvent(e);
      };
      const url = this._url;
      if (!url || url.origin !== origin || !url.pathname.startsWith("/api/")) {
        sim.emit("blocked", { what: "XMLHttpRequest", url: url ? url.href : "" });
        this.readyState = 4; fire(this, "error"); fire(this, "loadend"); return;
      }
      const total = body && body.size ? body.size : 1;
      for (let i = 1; i <= 5 && !this._aborted; i++) {
        await sleep(160);
        fire(this.upload, "progress", { lengthComputable: true, loaded: total * i / 5, total });
      }
      if (this._aborted) { fire(this, "abort"); fire(this, "loadend"); return; }
      const r = sim.request(this._method, url.pathname + url.search, await readBody(body));
      this.status = r.status; this.responseText = this.response = JSON.stringify(r.body); this.readyState = 4;
      if (typeof this.onreadystatechange === "function") this.onreadystatechange();
      fire(this, "load"); fire(this, "loadend");
    }
  }
  window.XMLHttpRequest = DemoXHR;
  const noConnections = function (name) {
    return function () { sim.emit("blocked", { what: name, url: String(arguments[0] || "") }); throw new DOMException(`Demo: ${name} isn't available in the demo.`, "SecurityError"); };
  };
  window.WebSocket = noConnections("WebSocket");
  window.EventSource = noConnections("EventSource");
  if (navigator.sendBeacon) define(navigator, "sendBeacon", () => false);
  define(window, "showOpenFilePicker", undefined);  // (the page falls back to a file input)

  // ------------------------------------------------------------ pictures
  // The real app's own files are next to the page (assets/); /api/ pictures are drawn by the simulation.
  sim.imageUrl = (value) => {
    let url;
    try { url = new URL(String(value), location.href); } catch (_) { return value; }
    if (url.origin !== origin) return value;
    if (url.pathname.startsWith("/api/")) return sim.picture(url.pathname + url.search);
    if (APP_STATIC.test(url.pathname)) return "assets" + url.pathname;
    return value;
  };
  const imgSrc = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, "src");
  Object.defineProperty(HTMLImageElement.prototype, "src", {
    configurable: true, enumerable: true,
    get() { return imgSrc.get.call(this); },
    set(v) { imgSrc.set.call(this, sim.imageUrl(v)); },
  });
  const setAttribute = Element.prototype.setAttribute;
  Element.prototype.setAttribute = function (name, value) {
    if (this instanceof HTMLImageElement && String(name).toLowerCase() === "src") value = sim.imageUrl(value);
    return setAttribute.call(this, name, value);
  };

  // ------------------------------------------------------------ links, downloads, forms
  const madeUp = (url) => /\.invalid$/i.test(url.hostname) || /(^|\.)example\.(com|net|org)$/i.test(url.hostname);
  const showNote = (text) => sim.emit("note", { text });
  document.addEventListener("click", (e) => {
    const a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
    if (!a || e.defaultPrevented) return;
    const href = a.getAttribute("href") || "";
    if (href.startsWith("#")) return;  // (the control panel's own pages)
    let url;
    try { url = new URL(href, location.href); } catch (_) { e.preventDefault(); return; }
    if (url.origin === origin) {
      e.preventDefault();
      if (url.pathname.startsWith("/api/")) showNote(sim.downloadNote(url.pathname, a.hasAttribute("download")));
      else showNote("That link leads out of the demo.");
      return;
    }
    if (url.protocol !== "https:" || madeUp(url)) {
      e.preventDefault();
      showNote(madeUp(url) ? "That address is made up for the demo: it doesn't lead anywhere." : "Demo: that link can't be opened from the demo.");
      return;
    }
    if (a.target !== "_blank") { e.preventDefault(); window.open(url.href, "_blank", "noopener"); }
  }, true);
  document.addEventListener("submit", (e) => {
    if (!e.defaultPrevented) { e.preventDefault(); showNote("Demo: nothing is sent anywhere."); }
  });
  const realOpen = window.open.bind(window);
  window.open = (url, target, features) => {
    let u = null;
    try { u = new URL(String(url), location.href); } catch (_) { /* not an address */ }
    if (!u || u.protocol !== "https:" || u.origin === origin || madeUp(u)) { showNote("That address is made up for the demo: it doesn't lead anywhere."); return null; }
    return realOpen(u.href, "_blank", "noopener,noreferrer" + (features ? "," + features : ""));
  };

  // ------------------------------------------------------------ the browser's powers, pretended
  // Notifications: the demo shows what would appear on screen, without asking the browser.
  let permission = local.getItem("craft-conductor-demo-notifications") === "granted" ? "granted" : "default";
  class DemoNotification {
    constructor(title, opts = {}) { sim.emit("notification", { title: String(title), body: String(opts.body || "") }); this.title = title; }
    close() {}
    static get permission() { return permission; }
    static requestPermission() {
      permission = "granted";
      local.setItem("craft-conductor-demo-notifications", "granted");
      showNote("Demo: your browser wasn't asked. Notifications here are shown inside the demo.");
      return Promise.resolve("granted");
    }
  }
  define(window, "Notification", DemoNotification);
  // The phone app's service worker and push subscription.
  let subscription = null;
  const makeSub = () => {
    const endpoint = "https://push.demo.invalid/" + sim.id(16);
    const keys = { p256dh: "demo-" + sim.id(20), auth: "demo-" + sim.id(8) };
    return { endpoint, expirationTime: null, toJSON: () => ({ endpoint, keys }), getKey: () => null,
      unsubscribe: () => { subscription = null; return Promise.resolve(true); } };
  };
  const registration = {
    scope: location.href, active: { state: "activated" }, installing: null, waiting: null,
    pushManager: {
      getSubscription: () => Promise.resolve(subscription),
      subscribe: () => { subscription = subscription || makeSub(); return Promise.resolve(subscription); },
      permissionState: () => Promise.resolve(permission === "granted" ? "granted" : "prompt"),
    },
    showNotification: (title, opts = {}) => { sim.emit("notification", { title: String(title), body: String(opts.body || "") }); return Promise.resolve(); },
    getNotifications: () => Promise.resolve([]),
    update: () => Promise.resolve(), unregister: () => Promise.resolve(true),
    addEventListener() {}, removeEventListener() {},
  };
  let registered = false;
  define(navigator, "serviceWorker", {
    controller: null,
    ready: Promise.resolve(registration),
    register: () => { registered = true; return Promise.resolve(registration); },
    getRegistration: () => Promise.resolve(registered ? registration : undefined),
    getRegistrations: () => Promise.resolve(registered ? [registration] : []),
    addEventListener() {}, removeEventListener() {},
  });
  // Passkeys: a made-up key, without the browser's fingerprint or face prompt (nothing real is made).
  const bytes = (text) => new TextEncoder().encode(text).buffer;
  const fakeCredential = () => {
    const id = "demo-passkey-" + sim.id(8);
    return { id, rawId: bytes(id), type: "public-key", authenticatorAttachment: "platform",
      response: { clientDataJSON: bytes("{}"), attestationObject: bytes("demo"), authenticatorData: bytes("demo"),
        signature: bytes("demo"), userHandle: null, getTransports: () => ["internal"], getPublicKey: () => null,
        getPublicKeyAlgorithm: () => -7, getAuthenticatorData: () => bytes("demo") },
      getClientExtensionResults: () => ({}) };
  };
  define(navigator, "credentials", {
    create: () => { showNote("Demo: no passkey was made. Your browser and device weren't asked."); return Promise.resolve(fakeCredential()); },
    get: () => Promise.resolve(fakeCredential()),
    store: () => Promise.resolve(), preventSilentAccess: () => Promise.resolve(),
  });

  // ------------------------------------------------------------ talking to the website
  sim.on((type, data) => {
    if (type === "save") tell("cc-demo-save", { state: data });
    else if (["unhandled", "explained", "blocked", "note", "notification", "event"].includes(type)) tell("cc-demo-" + type, { data });
  });
  addEventListener("pagehide", () => { if (sim.state) tell("cc-demo-save", { state: sim.state }); tell("cc-demo-browser", { data: browserData }); });

  let started = false;
  addEventListener("message", (e) => {
    if (e.source !== parent || !e.data || typeof e.data !== "object") return;
    const msg = e.data;
    if (msg.type === "cc-demo-init" && !started) {
      started = true;
      demoSession = msg.session;
      if (msg.browser && typeof msg.browser === "object") for (const [k, v] of Object.entries(msg.browser)) if (typeof v === "string") browserData[k] = v;
      if (!local.getItem("craft-conductor-theme") && (msg.theme === "day" || msg.theme === "night")) browserData["craft-conductor-theme"] = msg.theme;
      if (!local.getItem("craft-conductor-sounds")) browserData["craft-conductor-sounds"] = "off";  // (quiet until asked for)
      const hash = typeof msg.hash === "string" && /^#(servers|new|help|manual|craft-conductor|s\/[a-z0-9-]+(\/\w+)?)$/.test(msg.hash) ? msg.hash : "";
      sim.start({ scenario: msg.scenario, state: msg.state, mobile: !!msg.mobile, release: msg.release || {} });
      history.replaceState(null, "", location.pathname + location.search + (hash || sim.firstPage()));
      loadApp();
    } else if (msg.type === "cc-demo-command" && started) {
      sim.command(String(msg.command || ""), msg.args || {});
    }
  });
  function loadApp() {
    for (const src of APP_SCRIPTS) {
      const el = document.createElement("script");
      el.src = src;
      el.async = false;  // (in order, as the real page has them)
      document.body.append(el);
    }
    tell("cc-demo-started", { scenario: sim.state.scenario });
  }
  // Escape when nothing in the panel is open (a dialog, Help, the bell, a side pane, the menu) leaves
  // the demo, as it does with the focus on the website; otherwise it's the panel's, as in the real app.
  let busyEscape = false;
  const panelOpen = () => !!document.querySelector('[aria-modal="true"], .modal-backdrop, #bell-list:not([hidden]), #stage.browsing, .sidebar.open')
    || document.body.classList.contains("browse-mode");
  addEventListener("keydown", (e) => {
    if (e.key === "Escape") busyEscape = panelOpen() || /^(INPUT|TEXTAREA|SELECT)$/.test((e.target && e.target.tagName) || "");
  }, true);
  addEventListener("keydown", (e) => { if (e.key === "Escape" && !busyEscape && !e.defaultPrevented) tell("cc-demo-escape", {}); });

  // (an address with an invite or pairing code would show the real sign-up pages: never in the demo)
  if (/^#(pair|invite)=/.test(location.hash)) history.replaceState(null, "", location.pathname + location.search);
  tell("cc-demo-hello", { version: 1 });
})();
