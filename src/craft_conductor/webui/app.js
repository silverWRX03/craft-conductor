"use strict";

// ------------------------------------------------------------------ helpers
const $ = (sel) => document.querySelector(sel);

// Build DOM nodes. Text is always inserted as text, never HTML: mod names,
// descriptions, player names and console output all come from outside.
// A link or picture address is a web address, one on this page, or (pictures) a data: image;
// never javascript: or the like, whatever a mod site's details say.
function safeUrl(u, image = false) {
  return /^(https?:|mailto:|[/#?.])/i.test(u.trim()) || (image && /^data:image\//i.test(u.trim()));
}

// Paper and Purpur run server plugins (in plugins/) rather than mods (loaders.PLUGIN_SERVERS).
const runsPlugins = (loader) => loader === "paper" || loader === "purpur";

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if ((k === "href" || k === "src") && !safeUrl(String(v), tag === "img")) continue;  // (links from mod sites: web addresses only)
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") {
      el.className = v;
      if (el.classList.contains("btn")) {
        el.classList.add("cc-btn", el.classList.contains("primary") ? "cc-btn-primary" : el.classList.contains("danger") ? "cc-btn-danger" : "cc-btn-secondary");
      }
      if (el.classList.contains("card")) el.classList.add("cc-panel");
    }
    else if (k === "value") el.value = v;
    else if (k === "checked") el.checked = !!v;
    else el.setAttribute(k, v === true ? "" : k === "placeholder" || k === "title" || k === "aria-label" ? t(String(v)) : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(typeof c === "string" ? t(c) : String(c)));  // (i18n.js)
  }
  // A button showing only a symbol ("✕", "📂") is named by its tooltip for screen readers.
  if (tag === "button" && el.title && !el.hasAttribute("aria-label") && !/\p{L}/u.test(el.textContent)) el.setAttribute("aria-label", el.title);
  return el;
}

class Unauthorized extends Error {}

// ------------------------------------------------------------------ day / night
// Remembered per browser; the first time, it follows the computer's own light/dark setting.
const THEME_KEY = "craft-conductor-theme";
function currentTheme() {
  try { const t = localStorage.getItem(THEME_KEY); if (t === "day" || t === "night") return t; } catch (_) { /* private mode */ }
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "day" : "night";
}
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const bar = document.querySelector('meta[name="theme-color"]');  // (the phone's status bar and the app's title bar)
  if (bar) bar.setAttribute("content", theme === "day" ? "#F4F4F4" : "#0A0A0A");
  for (const b of document.querySelectorAll("[data-theme-toggle]")) {
    if (b.getAttribute("role") === "switch") b.setAttribute("aria-checked", String(theme === "night"));
    else b.setAttribute("aria-pressed", String(theme === "day"));
    b.title = t(theme === "day" ? "Switch to night" : "Switch to day");
  }
}
applyTheme(currentTheme());
// Until day or night is picked with the button, follow the computer's (or phone's) own setting,
// also when it changes while Craft Conductor is open (a phone switching to dark at sunset).
if (window.matchMedia) window.matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => applyTheme(currentTheme()));
document.addEventListener("click", (e) => {
  const b = e.target.closest && e.target.closest("[data-theme-toggle]");
  if (!b) return;
  const next = document.documentElement.dataset.theme === "day" ? "night" : "day";
  try { localStorage.setItem(THEME_KEY, next); } catch (_) { /* private mode */ }
  document.documentElement.classList.add("theme-switching");
  applyTheme(next);
  setTimeout(() => document.documentElement.classList.remove("theme-switching"), 700);
});

// ------------------------------------------------------------------ accessibility
// Contrast and motion (Craft Conductor settings → Appearance → Display), kept per browser; Automatic follows the
// computer's own settings (see style.css).
const CONTRAST_KEY = "craft-conductor-contrast", MOTION_KEY = "craft-conductor-motion";
const DISPLAY = [[CONTRAST_KEY, "contrast", "high", "(prefers-contrast: more)"], [MOTION_KEY, "motion", "less", "(prefers-reduced-motion: reduce)"]];
function applyDisplay() {
  for (const [key, attr, on, query] of DISPLAY) {
    let v = "";
    try { v = localStorage.getItem(key) || ""; } catch (_) { /* private mode */ }
    if (v === on || (!v && window.matchMedia && window.matchMedia(query).matches)) document.documentElement.dataset[attr] = on;
    else if (v === "normal") document.documentElement.dataset[attr] = "normal";
    else delete document.documentElement.dataset[attr];
  }
}
applyDisplay();
if (window.matchMedia) for (const [, , , query] of DISPLAY) window.matchMedia(query).addEventListener("change", applyDisplay);

// Keyboard and screen readers: a window that opens (a dialog) takes the focus, keeps Tab inside
// it, closes with Escape (its Close or Cancel button), and gives the focus back when it closes.
const FOCUSABLE = "a[href], button:not([disabled]), input:not([disabled]):not([type=hidden]), select:not([disabled]), " +
  "textarea:not([disabled]), summary, [tabindex]:not([tabindex='-1'])";
const topDialog = () => { const all = document.querySelectorAll("body > .modal-backdrop"); return all.length ? all[all.length - 1] : null; };
const focusables = (root) => [...root.querySelectorAll(FOCUSABLE)].filter((el) => el.getClientRects().length);
let focusBeforeDialog = null;
document.addEventListener("focusin", (e) => { if (!e.target.closest(".modal-backdrop")) focusBeforeDialog = e.target; });
new MutationObserver((changes) => {
  let opened = null, closed = false;
  for (const c of changes) {
    for (const n of c.addedNodes) if (n.classList && n.classList.contains("modal-backdrop")) opened = n;
    for (const n of c.removedNodes) if (n.classList && n.classList.contains("modal-backdrop")) closed = true;
  }
  const top = topDialog();
  if (opened && opened === top && !opened.contains(document.activeElement)) {
    const first = opened.querySelector("[autofocus]") || focusables(opened)[0];
    if (first) first.focus();
  } else if (closed && !top && focusBeforeDialog && focusBeforeDialog.isConnected) focusBeforeDialog.focus();
  else if (closed && top && !top.contains(document.activeElement)) { const f = focusables(top)[0]; if (f) f.focus(); }
}).observe(document.body, { childList: true });
document.addEventListener("keydown", (e) => {
  const dialog = topDialog();
  if (!dialog || (e.target.dataset && e.target.dataset.keys === "own" && (e.key === "Escape" || !e.shiftKey))) return;  // (the code editor's Tab and Escape)
  if (e.key === "Escape") {
    const names = [t("Close"), t("Cancel"), t("Not now")];
    const close = [...dialog.querySelectorAll("button")].find((b) => names.includes(b.textContent.trim()));
    if (close) { e.preventDefault(); e.stopImmediatePropagation(); close.click(); }
  } else if (e.key === "Tab") {
    const f = focusables(dialog);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (!dialog.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
    else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
}, true);
// "Skip to main content" (the first thing Tab reaches) and, after moving to another page, the
// focus goes to the page itself so a screen reader reads it from the top.
document.getElementById("skip-link").addEventListener("click", () => document.getElementById("main").focus());

// With several servers, a server's calls go to /api/servers/<id>/...; these are about Craft Conductor itself.
const GLOBAL_API = /^\/api\/(login|logout|auth|notice|licenses|self-update|hub|servers)(\/|\?|$)/;
let server = null;            // the server being looked at (null on the server list)
const scoped = (path) => server && path.startsWith("/api/") && !GLOBAL_API.test(path)
  ? `/api/servers/${server}/${path.slice(5)}` : path;
const link = (view) => `#s/${server}/${view}`;

async function api(path, { method = "GET", body, raw } = {}) {
  const headers = { "X-CRAFT-CONDUCTOR": "1" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (raw !== undefined) uploading++;  // (a file on its way: closing the tab would cut it off)
  let res;
  try {
    res = await fetch(scoped(path), {
      method, headers, credentials: "same-origin",
      body: raw !== undefined ? raw : body !== undefined ? JSON.stringify(body) : undefined,
    });
  } finally {
    if (raw !== undefined) uploading--;
  }
  let data = {};
  try { data = await res.json(); } catch (_) { /* empty */ }
  if (res.status === 401 && path !== "/api/login" && path !== "/api/passkey/login") { showLogin(); throw new Unauthorized(); }
  if (res.status === 428) { showNotice(); throw new Unauthorized(); }
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

// Uploads a big file with progress (fetch can't report upload progress).
function upload(path, file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    uploading++;
    xhr.addEventListener("loadend", () => uploading--);
    xhr.open("POST", scoped(path));
    xhr.setRequestHeader("X-CRAFT-CONDUCTOR", "1");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch (_) { /* empty */ }
      if (xhr.status === 401) { showLogin(); reject(new Unauthorized()); return; }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data); else reject(new Error(data.error || xhr.statusText));
    };
    xhr.onerror = () => reject(new Error("the upload failed; check the connection and try again"));
    xhr.send(file);
  });
}

// "Open folder" buttons: shown only in a browser on the server's own computer, where
// Craft Conductor can open the file manager. ``sid`` picks a server other than the current one.
function folderBtn(what, label, sid, cls = "btn ghost small") {
  if (!hubInfo || !hubInfo.local) return null;
  const path = what === "home" ? "/api/hub/open" : sid ? `/api/servers/${encodeURIComponent(sid)}/open` : "/api/open";
  return h("button", { type: "button", class: cls, title: "Open in your file manager",
    onclick: () => api(path, { method: "POST", body: { what } }).catch((e) => { if (!(e instanceof Unauthorized)) toast(e.message, true); }) },
  "📂 ", label);
}

// A toast that stays until the user picks an action.
// Messages that need an answer show in the middle of the screen with the page blurred behind
// them, and stay until one of their buttons is pressed. `blocking: false` keeps one at the top
// of the screen without blocking anything (e.g. progress of a long test you can work alongside).
function stickyToast(id, children, { blocking = true } = {}) {
  if (document.getElementById(id)) return;
  if (!blocking) { $("#toasts").append(h("div", { class: "toast sticky", id, role: "status" }, children)); return; }
  const box = h("div", { class: "modal compact toast-dialog", role: "alertdialog", "aria-modal": "true" }, children);
  document.body.append(h("div", { class: "modal-backdrop blur", id }, box));
  const first = box.querySelector("button.primary, button");
  if (first) first.focus();
}
function closeToast(id) { const el = document.getElementById(id); if (el) el.remove(); }

// Questions ("Stop the server?"): in the middle of the screen like other messages that need an
// answer, and a promise of the answer. The ones people meet again and again have an `id` and a
// "Don't ask me again" box; Craft Conductor settings → Sounds & notifications → Warnings brings them all back.
const SKIP_KEY = "craft-conductor-skip-warnings";
function skippedWarnings() { try { return JSON.parse(localStorage.getItem(SKIP_KEY) || "[]"); } catch (_) { return []; } }
function skipWarning(id) { try { localStorage.setItem(SKIP_KEY, JSON.stringify([...new Set([...skippedWarnings(), id])])); } catch (_) { /* private mode */ } }
function showAllWarnings() { try { localStorage.removeItem(SKIP_KEY); } catch (_) { /* private mode */ } }
let askCount = 0;
function ask(message, { id = null, ok = "OK", danger = false } = {}) {
  if (id && skippedWarnings().includes(id)) return Promise.resolve(true);
  return new Promise((resolve) => {
    const boxId = `ask-${++askCount}`;
    const again = id ? h("input", { type: "checkbox" }) : null;
    const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); done(false); } };
    const done = (yes) => {
      if (yes && again && again.checked) skipWarning(id);
      document.removeEventListener("keydown", onKey, true);
      closeToast(boxId);
      resolve(yes);
    };
    document.addEventListener("keydown", onKey, true);
    const [title, ...more] = String(message).split("\n\n").map(t);
    stickyToast(boxId, [
      h("strong", { class: "pre-line" }, title),
      more.map((t) => h("p", { class: "small pre-line" }, t)),
      again ? h("label", { class: "row small mt-s dont-ask" }, again, "Don't ask me again") : null,
      h("div", { class: "row mt-s" },
        h("button", { class: `btn small ${danger ? "danger" : "primary"}`, onclick: () => done(true) }, ok),
        h("button", { class: "btn small ghost", onclick: () => done(false) }, "Cancel"))]);
  });
}

// Everyday messages ("Saved", errors): at the top of the screen, where they're noticed, without
// getting in the way. Click one to dismiss it; errors stay longer.
function toast(message, bad = false) {
  const el = h("div", { class: "toast" + (bad ? " bad" : ""), role: bad ? "alert" : "status", title: "Click to dismiss",
    onclick: () => el.remove() }, h("span", { class: "toast-icon", "aria-hidden": "true" }, bad ? "⚠" : "✓"), h("span", {}, t(message)));
  $("#toasts").append(el);
  setTimeout(() => el.remove(), bad ? 12000 : 5000);
  if (bad) playSound("problem");
}

// ------------------------------------------------------------------ sounds
// Short cues made here in the browser (no sound files), the same in the web page and the phone
// app. On at a quiet volume; each kind can be turned off, and each device keeps its own choice
// (Craft Conductor settings → Sounds & notifications → Sounds). Never the only sign something happened.
const SOUND_KEY = "craft-conductor-sounds";
const SOUND_KINDS = [["tap", "Button presses"], ["go", "Start, save and install"], ["stop", "Stop and delete"],
  ["problem", "Something went wrong"], ["chime", "Heads-up: a server is up, a friend asks to join"]];
const SOUND_NOTES = {  // [frequency Hz, seconds, wave]: our own sounds, a soft wooden click and note blocks
  tap: [[660, 0.035, "triangle"]],
  go: [[523, 0.07, "sine"], [784, 0.1, "sine"]],
  stop: [[494, 0.07, "sine"], [330, 0.11, "sine"]],
  problem: [[150, 0.18, "sine"]],
  chime: [[784, 0.12, "sine"], [1047, 0.22, "sine"]],
};
function soundPrefs() {
  const base = { volume: "quiet", vibrate: true, ...Object.fromEntries(SOUND_KINDS.map(([k]) => [k, true])) };
  try { return { ...base, ...(JSON.parse(localStorage.getItem(SOUND_KEY) || "null") || {}) }; } catch (_) { return base; }
}
function saveSoundPrefs(p) { try { localStorage.setItem(SOUND_KEY, JSON.stringify(p)); } catch (_) { /* private mode */ } }
let audio = null, lastSound = 0;
function playSound(kind, force = false) {
  const p = soundPrefs();
  if (!force && (p.volume === "off" || !p[kind])) return;
  const now = performance.now();
  if (now - lastSound < 70) return;  // (quick presses don't stack up)
  lastSound = now;
  if (p.vibrate && navigator.vibrate && kind !== "chime") { try { navigator.vibrate(kind === "problem" ? [30, 50, 30] : 12); } catch (_) { /* not allowed */ } }
  if (p.volume === "off") return;
  // (iPhone: "ambient" sounds follow the silent switch, like other apps' interface sounds)
  try { if (navigator.audioSession) navigator.audioSession.type = "ambient"; } catch (_) { /* older Safari */ }
  try { audio = audio || new (window.AudioContext || window.webkitAudioContext)(); } catch (_) { return; }
  if (audio.state === "suspended") audio.resume().catch(() => null);
  const peak = p.volume === "normal" ? 0.2 : 0.07;
  let at = audio.currentTime + 0.01;
  for (const [freq, secs, wave] of SOUND_NOTES[kind] || []) {
    const osc = audio.createOscillator(), gain = audio.createGain();
    osc.type = wave;
    osc.frequency.setValueAtTime(freq, at);
    gain.gain.setValueAtTime(0.0001, at);
    gain.gain.exponentialRampToValueAtTime(peak, at + 0.006);
    gain.gain.exponentialRampToValueAtTime(0.0001, at + secs);
    osc.connect(gain).connect(audio.destination);
    osc.start(at);
    osc.stop(at + secs + 0.02);
    at += secs * 0.75;
  }
}
// Pressing a button (by mouse, touch or Enter/Space; moving with Tab makes no sound).
document.addEventListener("click", (e) => {
  const b = e.target.closest && e.target.closest("button, a.btn");
  if (!b || b.disabled || b.closest("[data-silent]")) return;
  playSound(b.classList.contains("danger") ? "stop" : b.classList.contains("primary") ? "go" : "tap");
}, true);
// Heads-up chimes while the page is open: a server finished starting, a friend asks to join.
let chimeSeen = null;
function chimeFor(servers) {
  const now = new Map((servers || []).map((s) => [s.id, s]));
  if (chimeSeen) {
    for (const [id, s] of now) {
      const before = chimeSeen.get(id);
      if (before && ((s.state === "running" && before.state !== "running") || (s.join_requests || 0) > (before.join_requests || 0))) {
        playSound("chime");
        break;
      }
    }
  }
  chimeSeen = now;
}

async function act(fn, okMessage) {
  try {
    const r = await fn();
    if (okMessage) toast(okMessage);
    await refreshStatus();
    return r;
  } catch (e) {
    if (!(e instanceof Unauthorized)) toast(e.message, true);
  }
}

const fmtBytes = (n) => n > 1e9 ? (n / 1e9).toFixed(1) + " GB" : (n / 1e6).toFixed(1) + " MB";
const fmtTime = (t) => new Date(t * 1000).toLocaleString();
const fmtClock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
function fmtDuration(s) {
  s = Math.floor(s);
  const d = Math.floor(s / 86400), hr = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
  return d ? `${d}d ${hr}h` : hr ? `${hr}h ${m}m` : `${m}m ${s % 60}s`;
}
function ago(t) {
  const s = Date.now() / 1000 - t;
  return s < 60 ? "just now" : s < 3600 ? `${Math.floor(s / 60)} min ago` : s < 86400 ? `${Math.floor(s / 3600)} h ago` : fmtTime(t);
}
// Like el.replaceChildren(), but skips null/false (which would otherwise render as "null").
function fill(el, ...children) {
  el.replaceChildren(...children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false));
}
function card(title, ...children) { return h("div", { class: "card" }, title ? h("h3", {}, title) : null, ...children); }

// -------------------------------------------------------------------- state
let status = null;            // the current server's status
let hubInfo = null;           // Craft Conductor itself: servers, sign-in, notice, updates
let lastJobSeen = null;
let current = null;           // current view
let timers = [];

// Leaving the page (closing the tab, reloading): Craft Conductor and its servers keep running, and jobs
// like creating or updating a server carry on, so only what lives in this page can be lost: an
// upload on its way, unsaved changes, a form being filled in, a mod test's report. Then the
// browser asks first ("Leave site?"). Guards go with an element and end when it's gone.
let uploading = 0;
let leaveGuards = [];  // [element, () => true when leaving now would lose something]
function guardLeave(el, check) {
  leaveGuards = leaveGuards.filter(([e]) => e.isConnected);
  leaveGuards.push([el, check]);
}
function wouldLoseWork() {
  return uploading > 0 || leaveGuards.some(([el, check]) => el.isConnected && check());
}
window.addEventListener("beforeunload", (e) => { if (wouldLoseWork()) { e.preventDefault(); e.returnValue = ""; } });

// Polling pauses while the page can't be seen (another tab, a phone's screen off) and
// catches up at once when it's back: no work for the server, battery or data meanwhile.
let polls = [];
function every(ms, fn) { fn(); polls.push(fn); timers.push(setInterval(() => { if (!document.hidden) fn(); }, ms)); }
function clearTimers() { timers.forEach(clearInterval); timers = []; polls = []; }
document.addEventListener("visibilitychange", () => { if (!document.hidden) polls.forEach((fn) => fn()); });

// -------------------------------------------------------------------- login
const PROMPT_KEY = "craft-conductor-password-prompt-dismissed";
async function showLogin() {
  clearTimers();
  $("#app").classList.add("hidden");
  $("#login").classList.remove("hidden");
  let a = null;
  try { a = await (await fetch("/api/auth", { credentials: "same-origin" })).json(); } catch (_) { /* offline */ }
  const input = $("#login-password");
  const pin = a && a.mode === "pin";
  $("#login-label").textContent = t(pin ? "PIN" : "Password");
  input.setAttribute("inputmode", pin ? "numeric" : "text");
  input.setAttribute("autocomplete", pin ? "off" : "current-password");
  const reset = h("button", { type: "button", class: "link-btn", onclick: async () => {
    if (!(await ask("Go back to the default password, PASSWORD? Anyone signed in elsewhere is signed out, and you'll choose a new one after signing in.", { ok: "Reset", danger: true }))) return;
    try {
      await api("/api/auth/reset-local", { method: "POST", body: {} });
      toast("The password is PASSWORD again");
      showLogin();
    } catch (err) { $("#login-error").textContent = err.message; }
  } }, "Reset it to PASSWORD");
  $("#login-hint").replaceChildren(...(
    !a ? [] :
    a.managed ? ["The password is set in craft-conductor.toml under ", h("code", {}, "[web] password"), "."] :
    a.default ? ["First time? The password is ", h("strong", {}, "PASSWORD"), " (in capitals). You'll choose your own next."] :
    a.local ? ["Forgot it? ", reset, " (this works on the server's own computer)."] :
    ["Forgot it? On the server's own computer, open this page and choose \"Reset it to PASSWORD\", or run ",
      h("code", {}, "craft-conductor web-password --reset"), "."]));
  let box = $("#login-passkey");
  if (!box) { box = h("div", { id: "login-passkey", class: "login-fields" }); $("#login-hint").before(box); }
  fill(box, a && a.passkeys && passkeysWork() ? h("button", { type: "button", class: "btn", onclick: signInWithPasskey }, "Sign in with fingerprint or face") : null,
    a && !a.local ? h("button", { type: "button", class: "btn ghost", onclick: () => showPairing("") }, "Pair with a code") : null);
  input.focus();
}

// ------------------------------------------------------ fingerprint and face sign-in (passkeys.py)
function passkeysWork() { return window.isSecureContext && !!window.PublicKeyCredential && !!navigator.credentials; }
function b64uOf(buf) {
  let s = "";
  for (const b of new Uint8Array(buf)) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
async function signInWithPasskey() {
  $("#login-error").textContent = "";
  try {
    const o = await api("/api/passkey/options", { method: "POST", body: {} });
    const cred = await navigator.credentials.get({ publicKey: { challenge: b64uBytes(o.challenge), rpId: o.rpId, timeout: o.timeout,
      userVerification: o.userVerification, allowCredentials: o.allowCredentials.map((c) => ({ type: c.type, id: b64uBytes(c.id) })) } });
    await api("/api/passkey/login", { method: "POST", body: { id: b64uOf(cred.rawId), client_data: b64uOf(cred.response.clientDataJSON),
      auth_data: b64uOf(cred.response.authenticatorData), signature: b64uOf(cred.response.signature) } });
    start();
  } catch (err) {
    $("#login-error").textContent = err.name === "NotAllowedError" ? t("Cancelled, or this device has no passkey for Craft Conductor.") : err.message;
  }
}
function passkeyCard() {
  const box = h("div", { class: "mb" });
  const render = (r) => {
    if (!r) { fill(box); return; }
    const add = async () => {
      try {
        const o = await api("/api/hub/passkeys/options", { method: "POST", body: {} });
        const cred = await navigator.credentials.create({ publicKey: { ...o, challenge: b64uBytes(o.challenge),
          user: { ...o.user, id: b64uBytes(o.user.id) }, excludeCredentials: o.excludeCredentials.map((c) => ({ type: c.type, id: b64uBytes(c.id) })) } });
        const done = await api("/api/hub/passkeys/add", { method: "POST", body: { name: deviceName(),
          client_data: b64uOf(cred.response.clientDataJSON), attestation: b64uOf(cred.response.attestationObject) } });
        toast("Fingerprint or face sign-in added on this device");
        render({ ...r, passkeys: done.passkeys });
      } catch (err) {
        if (err.name === "InvalidStateError") toast("This device already has one for Craft Conductor.", true);
        else if (err.name !== "NotAllowedError") toast(err.message, true);
      }
    };
    fill(box, card("Fingerprint or face sign-in",
      h("p", { class: "muted small" }, "Sign in with this device's fingerprint, face or screen lock instead of typing the password. It works at the address it was added at (use the secure Tailscale address on phones). A new password removes them."),
      r.passkeys.length ? h("ul", { class: "list" }, r.passkeys.map((k) => h("li", {},
        h("span", { class: "grow" }, k.name, h("span", { class: "muted small" }, ` · ${k.rp_id} · ${k.last_used ? `last used ${fmtTime(k.last_used)}` : `added ${fmtTime(k.created)}`}`)),
        h("button", { class: "btn small ghost", onclick: async () => {
          const res = await act(() => api("/api/hub/passkeys/remove", { method: "POST", body: { id: k.id } }), "Removed");
          if (res) render({ ...r, passkeys: res.passkeys });
        } }, "Remove")))) : null,
      !r.allowed ? h("p", { class: "small" }, "Choose your own password first (Sign-in above).")
        : passkeysWork() ? h("button", { class: "btn", onclick: add }, "Add fingerprint or face sign-in on this device")
          : h("div", { class: "notice small" }, "This page isn't on a secure address, so this browser can't use fingerprint or face sign-in here. Open Craft Conductor at its secure address (Craft Conductor settings → Connections → Phone app), or at localhost on this computer.")));
  };
  api("/api/hub/passkeys").then(render).catch(() => render(null));
  return box;
}

// A show/hide "eye" for password inputs.
function eyeToggle(input, button) {
  button.addEventListener("click", () => {
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    button.setAttribute("aria-pressed", String(show));
    button.setAttribute("aria-label", show ? "Hide password" : "Show password");
    button.title = t(show ? "Hide password" : "Show password");
    button.querySelector(".eye-open").classList.toggle("hidden", show);
    button.querySelector(".eye-shut").classList.toggle("hidden", !show);
    input.focus();
  });
}
eyeToggle($("#login-password"), $("#login-eye"));
function pwField(input) {
  const svg = (cls, d) => {
    const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("aria-hidden", "true"); s.setAttribute("class", cls);
    for (const part of d) {
      const el = document.createElementNS("http://www.w3.org/2000/svg", part.circle ? "circle" : "path");
      for (const [k, v] of Object.entries(part.circle || { d: part })) el.setAttribute(k, v);
      s.append(el);
    }
    return s;
  };
  const btn = h("button", { type: "button", class: "eye", "aria-label": "Show password", "aria-pressed": "false", title: "Show password" },
    svg("eye-open", ["M1.5 12S5.5 4.5 12 4.5 22.5 12 22.5 12 18.5 19.5 12 19.5 1.5 12 1.5 12Z", { circle: { cx: 12, cy: 12, r: 3.2 } }]),
    svg("eye-shut hidden", ["M3 3l18 18M10.6 5.1A10.8 10.8 0 0 1 12 4.5C18.5 4.5 22.5 12 22.5 12a18 18 0 0 1-3.3 4.3M6.6 6.6C3.4 8.6 1.5 12 1.5 12S5.5 19.5 12 19.5a10 10 0 0 0 5.4-1.6M9.9 9.9a3.2 3.2 0 0 0 4.2 4.2"]));
  eyeToggle(input, btn);
  return h("div", { class: "pw-field" }, input, btn);
}

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#login-error").textContent = "";
  try {
    await api("/api/login", { method: "POST", body: { password: $("#login-password").value } });
    $("#login-password").value = "";
    try { sessionStorage.removeItem(PROMPT_KEY); } catch (_) {}
    start();
  } catch (err) { $("#login-error").textContent = err.message; }
});

$("#logout").addEventListener("click", async () => { await api("/api/logout", { method: "POST" }).catch(() => {}); showLogin(); });
// There's no command window to close, so Craft Conductor is quit from here.
$("#quit").addEventListener("click", async () => {
  const running = ((hubInfo && hubInfo.servers) || []).filter((s) => s.state === "running" || s.state === "starting");
  if (!(await ask(running.length ? `Quit Craft Conductor? ${running.map((s) => s.name).join(", ")} will be stopped (players get disconnected).`
    : "Quit Craft Conductor? Open it again from its icon when you want it back.", { id: running.length ? "quit-running" : "quit", ok: "Quit" }))) return;
  try { await api("/api/hub/quit", { method: "POST", body: {} }); } catch (e) { if (!(e instanceof Unauthorized)) { toast(e.message, true); return; } }
  clearTimers();
  document.body.replaceChildren(h("div", { class: "login" }, h("div", { class: "login-card" },
    h("div", { class: "brand big" }, h("span", { class: "logo" }), "craft-conductor"),
    h("p", {}, "Craft Conductor is shutting down" + (running.length ? " and stopping your servers" : "") + "."),
    h("p", { class: "muted small" }, "You can close this tab. To use Craft Conductor again, open it from its icon."))));
});

// ------------------------------------------------------------ first-run notice
let noticeOpening = false;
async function showNotice() {
  // Guard synchronously: several status polls can call this before the fetch returns.
  if (noticeOpening || $("#notice")) return;
  noticeOpening = true;
  let n;
  try { n = await (await fetch("/api/notice", { credentials: "same-origin" })).json(); } catch (_) { n = null; }
  noticeOpening = false;
  if (!n || n.accepted || $("#notice")) return;
  clearTimers();
  const accept = h("button", { class: "btn primary", onclick: async () => {
    try {
      await api("/api/notice/accept", { method: "POST", body: { version: n.version } });
      $("#notice").remove();
      route();
    } catch (e) { if (!(e instanceof Unauthorized)) toast(e.message, true); }
  } }, "I understand and accept");
  const decline = h("button", { class: "btn ghost", onclick: async () => {
    await api("/api/logout", { method: "POST" }).catch(() => {});
    $("#notice").remove();
    showLogin();
  } }, "Decline and sign out");
  document.body.append(h("div", { class: "modal-backdrop", id: "notice", role: "dialog", "aria-modal": "true", "aria-labelledby": "notice-title" },
    h("div", { class: "modal" },
      h("h2", { id: "notice-title" }, n.title),
      h("ul", { class: "notice-points" }, n.points.map((p) => h("li", {}, p))),
      h("p", { class: "muted small" }, "The Minecraft server won't start until this is accepted. You can read it again under Settings → About."),
      h("div", { class: "row" }, accept, decline))));
  accept.focus();
}

// ------------------------------------------------------------ sign-in settings
const AUTH_MODES = [
  ["password", "Password", "At least 4 characters."],
  ["pin", "PIN", "4 to 8 digits. Quick to type on a phone."],
];
// What a new password or PIN needs, ticked off as it's typed (webauth.validate and, with remote
// access on, webauth.STRONG_RULES: the server checks the same).
function requirements(pin, strongRequired, secret, again) {
  const rules = pin ? [["4 to 8 digits", (p) => /^\d{4,8}$/.test(p)]]
    : strongRequired ? [["12 or more characters", (p) => p.length >= 12], ["an uppercase letter", (p) => /[A-Z]/.test(p)],
      ["a lowercase letter", (p) => /[a-z]/.test(p)], ["a special character (like ! ? # %)", (p) => /[^A-Za-z0-9\s]/.test(p)]]
      : [["4 or more characters", (p) => p.length >= 4], ["not PASSWORD", (p) => p.length > 0 && p !== "PASSWORD"]];
  rules.push(["both boxes the same", (p) => p.length > 0 && p === again.value]);
  const list = h("ul", { class: "checklist small", "aria-live": "polite" });
  const update = () => fill(list, rules.map(([text, ok]) => {
    const met = ok(secret.value);
    return h("li", { class: met ? "ok-text" : "muted" }, h("span", { "aria-hidden": "true" }, met ? "✓ " : "• "), t(text),
      h("span", { class: "sr-only" }, met ? ` (${t("done")})` : ""));
  }));
  secret.addEventListener("input", update);
  again.addEventListener("input", update);
  update();
  return h("div", { class: "requirements" }, h("p", { class: "small" }, t(pin ? "Your PIN needs:" : "Your password needs:")), list,
    !pin && !strongRequired ? h("p", { class: "muted small" }, t("To use Craft Conductor from your phone or another computer later, it will need to be strong: 12 or more characters with an uppercase letter, a lowercase letter and a special character.")) : null);
}
async function showSecurity(firstTime = false) {
  if ($("#security")) return;
  let local = false, strongRequired = false;
  try {
    const a = await (await fetch("/api/auth", { credentials: "same-origin" })).json();
    local = !!a.local; strongRequired = !!a.strong_required;
  } catch (_) { /* offline: the server still checks */ }
  if ($("#security")) return;
  let mode = hubInfo && hubInfo.auth && !hubInfo.auth.default ? hubInfo.auth.mode : "password";
  if (mode === "pin" && (!local || strongRequired)) mode = "password";  // PINs only work on the server's own computer
  const close = () => { const m = $("#security"); if (m) m.remove(); };
  const box = h("div", { class: "modal compact" });
  const render = (error) => {
    const pin = mode === "pin";
    const kind = pin ? "PIN" : "password";
    const extra = pin ? { inputmode: "numeric", maxlength: 8, autocomplete: "off" } : { autocomplete: "new-password" };
    const secret = h("input", { type: "password", ...extra });
    const again = h("input", { type: "password", ...extra });
    const save = async (e) => {
      e.preventDefault();
      if (secret.value !== again.value) return render(`The two ${kind}s don't match.`);
      try {
        await api("/api/auth/change", { method: "POST", body: { mode, secret: secret.value } });
        close();
        toast(`Your new ${kind} is saved`);
        refreshStatus();
      } catch (err) { if (!(err instanceof Unauthorized)) render(err.message); }
    };
    fill(box,
      h("h2", { id: "security-title" }, firstTime ? "Choose your own password" : "Sign-in"),
      firstTime ? h("p", {}, "You're signed in with the default password, PASSWORD, which anyone could guess. Pick how you'd like to protect this control panel.") : null,
      h("div", { class: "choices" }, AUTH_MODES.map(([m, label, desc]) => h("button", {
        type: "button", class: "choice" + (mode === m ? " selected" : ""), disabled: m === "pin" && (!local || strongRequired),
        onclick: () => { mode = m; render(); },
      }, h("strong", {}, label), h("span", { class: "small muted" }, m === "pin" && strongRequired ? "Not with remote access on."
        : m === "pin" && !local ? "Only available on the server's own computer." : m === "password" && strongRequired ? "A strong one: see below." : desc)))),
      h("form", { class: "mt", onsubmit: save },
        h("div", { class: "grid" }, h("label", {}, `New ${kind}`, pwField(secret)), h("label", {}, `Type it again`, pwField(again))),
        requirements(pin, strongRequired, secret, again),
        h("p", { class: "error" }, error || ""),
        h("div", { class: "row" },
          h("button", { class: "btn primary", type: "submit" }, "Save"),
          h("button", { class: "btn ghost", type: "button", onclick: () => {
            if (firstTime) { try { sessionStorage.setItem(PROMPT_KEY, "1"); } catch (_) {} }
            close();
          } }, firstTime ? "Not now" : "Cancel")),
        h("p", { class: "muted small" }, "Everyone else is signed out when this changes. Forgot it later? Run ",
          h("code", {}, "craft-conductor web-password --reset"), " on the server.")));
    const first = box.querySelector("input");
    if (first) first.focus();
  };
  render();
  document.body.append(h("div", { class: "modal-backdrop", id: "security", role: "dialog", "aria-modal": "true", "aria-labelledby": "security-title" }, box));
}
function promptDismissed() { try { return !!sessionStorage.getItem(PROMPT_KEY); } catch (_) { return false; } }

// ------------------------------------------------------------ craft-conductor self-update
const DISMISS_KEY = "craft-conductor-dismissed-update";
function dismissed() { try { return localStorage.getItem(DISMISS_KEY); } catch (_) { return null; } }
function offerSelfUpdate(u, force = false) {
  if (!u || (!force && dismissed() === u.version)) return;
  const later = () => { try { localStorage.setItem(DISMISS_KEY, u.version); } catch (_) {} closeToast("self-update"); };
  const install = async () => {
    if (!(await ask(`Update Craft Conductor ${u.current} → ${u.version}?\n\ncraft-conductor installs the update, stops the Minecraft server cleanly (with a 1-minute warning if players are online), and restarts on the new version. You'll need to sign in again afterwards.`, { ok: "Update" }))) return;
    closeToast("self-update");
    act(() => api("/api/self-update/apply", { method: "POST", body: { version: u.version } }), "Updating Craft Conductor… this page reconnects when it's back.");
  };
  stickyToast("self-update", [
    h("strong", {}, `craft-conductor ${u.version} is available`),
    h("div", { class: "small muted" }, `You have ${u.current}. `, u.url ? h("a", { href: u.url, target: "_blank", rel: "noopener noreferrer" }, "What's new ↗") : null),
    u.can_install ? null : h("div", { class: "small" }, u.reason),
    h("div", { class: "row mt-s" },
      u.can_install ? h("button", { class: "btn primary small", onclick: install }, "Update now") : null,
      h("button", { class: "btn small", onclick: later }, "Later")),
  ]);
}

// ------------------------------------------------------------- guided setup
// A checklist from making the server to a friend joining it; the steps tick themselves. Offered
// once, the first time (a toast: Guide me or Skip), and started again from Help or Servers.
const GUIDE_MIN_KEY = "craft-conductor-guide-min";
let guideOffered = false, guideTimer = null;
function offerGuide(hb) {
  const g = hb.guide;
  if (!g || (hb.role && hb.role !== "owner")) return;
  if (g.active) { if (!$("#guide")) showGuide(); return; }
  if (g.asked || guideOffered) return;
  if ($("#security") || $("#notice")) { setTimeout(() => hubInfo && offerGuide(hubInfo), 1500); return; }
  guideOffered = true;
  const answer = async (action) => {
    closeToast("guide-offer");
    const r = await api("/api/hub/guide", { method: "POST", body: { action } }).catch(() => null);
    if (r && action === "start") showGuide(r);
    else if (r) toast("You can start the guided setup any time from Help or the Servers page.");
  };
  stickyToast("guide-offer", [
    h("strong", {}, "New to running a Minecraft server?"),
    h("div", { class: "small" }, "The guided setup takes you step by step, from making the server to a friend joining it."),
    h("div", { class: "row mt-s" },
      h("button", { class: "btn primary small", onclick: () => answer("start") }, "Guide me"),
      h("button", { class: "btn small", onclick: () => answer("skip") }, "Skip")),
  ], { blocking: false });
}
async function startGuide() {
  const r = await api("/api/hub/guide", { method: "POST", body: { action: "start" } }).catch((e) => { toast(e.message, true); return null; });
  if (r) { try { sessionStorage.removeItem(GUIDE_MIN_KEY); } catch (_) {} showGuide(r); }
}
function showGuide(data) {
  let box = $("#guide");
  if (!box) { box = h("aside", { id: "guide", class: "guide", "aria-label": t("Guided setup") }); document.body.append(box); }
  const minimized = () => { try { return !!sessionStorage.getItem(GUIDE_MIN_KEY); } catch (_) { return false; } };
  const setMin = (v) => { try { v ? sessionStorage.setItem(GUIDE_MIN_KEY, "1") : sessionStorage.removeItem(GUIDE_MIN_KEY); } catch (_) {} render(last); };
  let last = data || null;
  const go = (step, g) => {
    const sid = g.server;
    const where = { make: "#new", start: sid ? `#s/${sid}/dashboard` : "#new", join: sid ? `#s/${sid}/dashboard` : "#help",
      open: "#craft-conductor", invite: sid ? `#s/${sid}/friends` : "#new", friend: sid ? `#s/${sid}/players` : "#servers" }[step];
    location.hash = where;
    if (step === "open") setTimeout(() => { const el = document.getElementById("sharing"); if (el) el.scrollIntoView({ behavior: "smooth" }); }, 400);
  };
  const act2 = async (body) => { const r = await api("/api/hub/guide", { method: "POST", body }).catch(() => null); if (r) render(r); return r; };
  const stop = async () => {
    if (!(await ask("Stop the guided setup? You can start it again any time from Help or the Servers page.", { ok: "Stop the guide" }))) return;
    await act2({ action: "stop" });
    clearInterval(guideTimer); guideTimer = null;
    box.remove();
  };
  function render(g) {
    if (!g) return;
    last = g;
    if (!g.active) { box.remove(); clearInterval(guideTimer); guideTimer = null; return; }
    const n = g.steps.filter((x) => x.done).length;
    const all = n === g.steps.length;
    if (minimized()) {
      fill(box, h("button", { class: "guide-pill", onclick: () => setMin(false) }, `🧭 ${t("Guided setup")} · ${n}/${g.steps.length}`));
      box.classList.add("min");
      return;
    }
    box.classList.remove("min");
    fill(box,
      h("div", { class: "row guide-head" }, h("strong", { class: "grow" }, `🧭 ${t("Guided setup")}`), h("span", { class: "muted small" }, `${n} / ${g.steps.length}`),
        h("button", { class: "link-btn", title: t("Hide for now"), "aria-label": t("Hide for now"), onclick: () => setMin(true) }, "–"),
        h("button", { class: "link-btn", title: t("Stop the guide"), "aria-label": t("Stop the guide"), onclick: stop }, "×")),
      all ? h("div", { class: "notice ok" }, h("strong", {}, "🎉 You did it!"), h("div", { class: "small" }, "Your server is running and a friend has joined. Have fun!"),
        h("button", { class: "btn small mt-s", onclick: () => act2({ action: "stop" }) }, "Finish")) : null,
      h("ol", { class: "guide-steps" }, g.steps.map((x) => h("li", { class: (x.done ? "done" : "") + (x.id === g.next ? " next" : "") },
        h("span", { class: "guide-tick" }, x.done ? "✓" : ""), h("div", { class: "grow" }, h("div", {}, x.title),
          x.id === g.next ? h("div", {},
            h("p", { class: "small muted" }, t(x.how)),
            h("div", { class: "row" },
              h("button", { class: "btn small primary", onclick: () => go(x.id, g) }, "Show me"),
              x.manual ? h("button", { class: "btn small", onclick: () => act2({ action: "tick", step: x.id }) }, "I've done this") : null)) : null)))));
  }
  render(last);
  const poll = async () => {
    if (!document.body.contains(box)) { clearInterval(guideTimer); guideTimer = null; return; }
    const r = await api("/api/hub/guide").catch(() => null);
    if (r) render(r);
  };
  if (!last) poll();
  if (!guideTimer) guideTimer = setInterval(poll, 5000);
}

// Warnings about this computer (health.py): little disk space, the CPU busy for minutes, memory
// running out. Above every page while they last; Hide hides one until it changes.
let healthShown = "";
const healthHidden = new Set();
function renderHealth(warnings) {
  const show = warnings.filter((w) => !healthHidden.has(w.id + w.title));
  const key = JSON.stringify(show);
  if (key === healthShown) return;
  healthShown = key;
  let box = $("#health");
  if (!show.length) { if (box) box.remove(); return; }
  if (!box) { box = h("div", { id: "health", class: "health", role: "status" }); $("#stage").before(box); }
  fill(box, show.map((w) => h("div", { class: `notice small ${w.level === "bad" ? "bad" : "warn"} row` },
    h("div", { class: "grow" }, h("strong", {}, t(w.title)), " ", h("span", {}, t(w.detail))),
    h("button", { class: "btn small ghost", onclick: () => { healthHidden.add(w.id + w.title); renderHealth(warnings); } }, "Hide"))));
}

// ------------------------------------------------------------------- status
async function refreshStatus() {
  try { hubInfo = await api("/api/hub"); } catch (e) {
    if (!(e instanceof Unauthorized)) { $("#state-pill").textContent = t("reconnecting"); $("#state-pill").className = "pill"; }
    return;
  }
  const hb = hubInfo;
  chimeFor(hb.servers);
  $("#version").textContent = "v" + hb.version + " beta";
  $("#version").title = t("Craft Conductor is in beta: expect some rough edges, and keep backups.");
  $("#quit").classList.toggle("hidden", !!hb.single || (hb.role && hb.role !== "owner"));
  document.body.classList.toggle("viewer", hb.role === "viewer");  // look-only sign-in: no buttons that change things
  if (!hb.notice_accepted) { showNotice(); return; }
  offerSelfUpdate(hb.self_update);
  if (hb.auth.default && !hb.auth.managed && !promptDismissed()) showSecurity(true);
  offerGuide(hb);
  renderHealth(hb.health || []);
  if (hb.single && !server && hb.servers.length === 1) { location.hash = `#s/${hb.servers[0].id}/dashboard`; return; }
  renderNav();
  if (!server) {
    if (current && current.onHub) current.onHub(hb);
    return;
  }
  const want = server;
  let s;
  try { s = await api("/api/status"); } catch (e) {
    if (e instanceof Unauthorized) return;
    if (/no server with that id/.test(e.message)) { toast(e.message, true); location.hash = "#servers"; }
    return;
  }
  if (want !== server) return;  // switched servers meanwhile
  status = s;
  const pill = $("#state-pill");
  pill.textContent = t(s.state);
  pill.className = "pill " + s.state;
  $("#server-title").textContent = (s.motd || s.id) + (s.minecraft
    ? ` · Minecraft ${s.minecraft} · ${s.loader}` : " · not installed yet");
  const busy = !!s.job;
  $("#job").classList.toggle("hidden", !busy);
  $("#job-name").textContent = busy ? s.job.name + "…" : "";
  $("#btn-start").disabled = busy || s.state !== "stopped" || s.setup_pending;
  $("#btn-stop").disabled = busy || s.state === "stopped";
  $("#btn-restart").disabled = busy || s.state !== "running";
  const dot = $("#nav-update-dot");
  if (dot) dot.classList.toggle("hidden", !(s.update && !s.update.up_to_date && s.update.target));

  if (s.last_job && s.last_job.finished !== lastJobSeen) {
    if (lastJobSeen !== null) toast(`${s.last_job.name}: ${s.last_job.message}`, !s.last_job.ok);
    lastJobSeen = s.last_job.finished;
    if (current && current.onJobDone) current.onJobDone();
  } else if (lastJobSeen === null) {
    lastJobSeen = s.last_job ? s.last_job.finished : 0;
  }
  document.body.classList.toggle("setup-mode", !!s.setup_pending);
  if (s.setup_pending && currentName !== "setup") { location.hash = link("setup"); return; }
  if (!s.setup_pending && currentName === "setup" && !s.job) { setupFinished(); return; }
  if (current && current.onStatus) current.onStatus(s);
}

// Before starting a server: does it fit in this computer's memory next to the running ones?
// (limits.py) Asks when it doesn't; the server still starts if the person says so.
async function memoryOkToStart(sid, name) {
  const plan = await api(`/api/hub/memory?adding=${encodeURIComponent(sid)}`).catch(() => null);
  if (!plan || plan.fits || !plan.total_gb) return true;
  return ask(t("Start {name}? The servers would be given {after} GB of memory, and this computer has {total} GB.")
    .replace("{name}", name).replace("{after}", plan.after_gb).replace("{total}", plan.total_gb)
    + "\n\n" + t("It may slow right down, or a server may crash. Give servers less memory (Settings → Memory), or stop one first."),
  { ok: "Start anyway", id: "memory-start" });
}
$("#btn-start").addEventListener("click", async () => {
  if (!server || await memoryOkToStart(server, (status && (status.motd || status.id)) || server))
    act(() => api("/api/server/start", { method: "POST" }));
});
$("#btn-stop").addEventListener("click", async () => {
  if (await ask("Stop the server? Players will be disconnected.", { id: "stop-server", ok: "Stop" })) act(() => api("/api/server/stop", { method: "POST" }));
});
$("#btn-restart").addEventListener("click", () => act(() => api("/api/server/restart", { method: "POST" })));

// -------------------------------------------------------------------- views
const views = {};

// A live server console: output plus a command box. Used on the Console page and the dashboard.
function consolePanel({ compact = false } = {}) {
  const out = h("div", { class: "console cc-terminal-box" + (compact ? " compact" : ""), role: "log", "aria-label": "Server console", "aria-live": "polite" });
  const input = h("input", { placeholder: "Type a server command, e.g. say hello  (↑/↓ for history)", autocomplete: "off",
    "aria-label": "Server command" });
  const history = []; let hi = 0; let seq = 0;

  const cls = (line) => line.user ? "l-user" : /\/(ERROR|FATAL)\]|Exception/.test(line.text) ? "l-error cc-log-error" : /\/WARN\]/.test(line.text) ? "l-warn cc-log-warning" : /Done \(|joined the game|Server ready/i.test(line.text) ? "cc-log-success" : "";
  const poll = async () => {
    const r = await api(`/api/console?since=${seq}`).catch(() => null);
    if (!r || !r.lines.length) return;
    const stick = out.scrollHeight - out.scrollTop - out.clientHeight < 40;
    seq = r.last;
    const frag = document.createDocumentFragment();
    for (const l of r.lines) {
      const stamp = l.text.match(/^\[[0-9: .-]+\]/);
      frag.append(h("div", { class: "cc-log-line " + cls(l) },
        stamp ? h("span", { class: "cc-log-timestamp" }, stamp[0]) : null,
        stamp ? l.text.slice(stamp[0].length) : l.text));
    }
    out.append(frag);
    while (out.childElementCount > (compact ? 500 : 3000)) out.firstChild.remove();
    if (stick) out.scrollTop = out.scrollHeight;
  };
  const send = async () => {
    const command = input.value.trim();
    if (!command) return;
    history.push(command); hi = history.length;
    input.value = "";
    await act(() => api("/api/command", { method: "POST", body: { command } }));
    poll();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") send();
    else if (e.key === "ArrowUp" && hi > 0) { input.value = history[--hi]; e.preventDefault(); }
    else if (e.key === "ArrowDown") { hi = Math.min(history.length, hi + 1); input.value = history[hi] || ""; }
  });
  const el = h("section", { class: "card cc-panel cc-console-widget " + (compact ? "console-panel" : "console-wrap"), "aria-label": "Live console" },
    h("h3", {}, "Live console"), out, h("div", { class: "console-input" }, input, h("button", { class: "btn primary", onclick: send }, "Send")));
  return { el, input, poll };
}

// A player's face, cut from their skin (served by Craft Conductor), or a lettered tile if there's none.
const skinFails = new Set();
function playerHead(name, size = 32) {
  const c = h("canvas", { width: size, height: size, class: "head", "aria-hidden": "true" });
  const ctx = c.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  const tile = () => {
    let hash = 0;
    for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
    ctx.fillStyle = `hsl(${hash % 360} 45% 38%)`;
    ctx.fillRect(0, 0, size, size);
    ctx.fillStyle = "#fff";
    ctx.font = `bold ${Math.round(size * 0.55)}px system-ui, sans-serif`;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(name.charAt(0).toUpperCase(), size / 2, size / 2 + 1);
  };
  if (skinFails.has(name)) { tile(); return c; }
  const img = new Image();
  img.addEventListener("load", () => {
    ctx.drawImage(img, 8, 8, 8, 8, 0, 0, size, size);        // face
    if (img.height >= 64) ctx.drawImage(img, 40, 8, 8, 8, 0, 0, size, size);  // hat layer
  });
  img.addEventListener("error", () => { skinFails.add(name); tile(); });
  img.src = scoped(`/api/players/skin?name=${encodeURIComponent(name)}`);
  return c;
}

function meter(label) {
  const value = h("strong", {});
  const fillBar = h("div", { class: "bar-fill" });
  const note = h("div", { class: "muted small" });
  const el = h("div", { class: "card meter cc-metric-card" },
    h("div", { class: "meter-head" }, h("span", {}, label), value), h("div", { class: "bar", "aria-hidden": "true" }, fillBar), note);
  return {
    el,
    set(pct, text, sub) {
      value.textContent = t(text);
      note.textContent = t(sub || "");
      const p = pct === null || pct === undefined ? 0 : Math.max(0, Math.min(100, pct));
      fillBar.style.width = p + "%";  // CSSOM, allowed by the CSP (unlike style attributes)
      fillBar.className = "bar-fill" + (p >= 90 ? " bad" : p >= 75 ? " warn" : "");
    },
  };
}

// playit.gg: friends join through its tunnels instead of port forwarding. It's an outside
// service, so say so wherever it's set up, and check it's working (on the Dashboard).
function playitNote() {
  return h("div", { class: "notice warn small" }, h("strong", {}, "playit.gg is an outside service. "),
    "It's run by its own company, not by Craft Conductor: when it has problems, or its program isn't running on this computer, friends can't connect through it, and Craft Conductor can't fix that. ",
    "Craft Conductor checks the tunnel and shows on the Dashboard whether it's working. ",
    h("a", { href: "https://playit.gg/download", target: "_blank", rel: "noopener noreferrer" }, "Get playit ↗"), " · ",
    h("a", { href: "https://status.playit.gg", target: "_blank", rel: "noopener noreferrer" }, "playit.gg status ↗"));
}
const TUNNEL_ICON = { ok: "✓", wrong: "⚠", down: "✗", stopped: "•", off: "•" };
function tunnelCard() {
  const box = h("div");
  const load = async (now = false) => {
    const r = await api(`/api/tunnel${now ? "?now=1" : ""}`).catch(() => null);
    if (!r || !r.address) { fill(box); return; }
    const st = r.status || { status: "stopped", words: "" };
    fill(box, h("div", { class: "card mt" }, h("h3", {}, "playit.gg tunnel"),
      h("div", { class: `row doctor-item ${st.status === "ok" ? "ok" : st.status === "stopped" ? "info" : "bad"}` },
        h("span", { class: "doctor-icon", "aria-hidden": "true" }, TUNNEL_ICON[st.status] || "•"),
        h("div", { class: "grow" }, h("strong", {}, r.address), h("div", { class: "small" }, st.words),
          r.agent === false ? h("div", { class: "small bad-text" }, "The playit program isn't running on this computer: start it, and the tunnel comes back.") : null,
          st.checked ? h("div", { class: "muted small" }, `Checked ${ago(st.checked)}`) : null),
        h("button", { class: "btn small", onclick: () => load(true) }, "Check now")),
      st.status === "down" || st.status === "wrong" ? h("p", { class: "small mt-s" }, "Is it playit.gg? See ",
        h("a", { href: r.status_page, target: "_blank", rel: "noopener noreferrer" }, "their status page ↗"),
        ". Friends on your own network can still join with the Local link.") : null,
      h("p", { class: "muted small mt-s" }, "playit.gg is an outside service: disruptions on its side are out of Craft Conductor's control.")));
  };
  return { el: box, load };
}

// A friend asked to be let in: say so on the Dashboard, with the way to the Players page.
function askingNotice() {
  const me = hubInfo && hubInfo.servers ? hubInfo.servers.find((x) => x.id === server) : null;
  const n = me ? me.join_requests || 0 : 0;
  return n ? h("div", { class: "notice mt row" }, h("span", { class: "grow" }, `${n} friend${n === 1 ? " asks" : "s ask"} to be let in.`),
    h("a", { class: "btn small primary", href: link("players") }, "See who")) : null;
}

// Performance: ticks per second (20 = smooth), measured now and then while the Dashboard is
// open, with a small graph of the last hour, what to try when it's behind, and (with the spark
// mod) a 30-second profile for power users.
// The lag finder: 30 seconds of Minecraft's profiler plus the world's files, in plain words.
function lagBox() {
  const el = h("div", { class: "lag-box mt-s" });
  let timer = null, running = false, up = true, lastState = null;
  const findings = (r) => h("ul", { class: "list" }, r.findings.map((f) => h("li", {}, h("div", { class: "grow" },
    h("strong", {}, f.title),
    f.detail ? h("div", { class: "small" }, f.detail) : null,
    f.places.length ? h("ul", { class: "small lag-places" }, f.places.map((p) => h("li", {}, "📍 " + p))) : null,
    f.mods.length ? h("div", { class: "small" }, t("From mods:") + " " + f.mods.join(", ")) : null,
    f.tip ? h("div", { class: "muted small" }, "💡 " + t(f.tip)) : null))));
  const render = (st) => {
    lastState = st;
    const job = st.finder && st.finder.state === "running" ? st.finder : null;
    const failed = st.finder && st.finder.state === "failed" ? st.finder.result : null;
    const r = st.report;
    running = !!job;
    fill(el,
      job ? h("div", {}, h("div", { class: "row small" }, h("span", { class: "spinner" }), h("span", { class: "grow" }, t(job.step || "Getting ready…")),
        h("button", { class: "link-btn", onclick: () => api("/api/performance/lag/stop", { method: "POST" }).catch(() => null) }, "Stop")))
        : h("div", { class: "row small" },
          h("button", { class: "btn small", onclick: start, disabled: !up, title: up ? "" : "Start the server first" }, "Find what's causing lag"),
          h("span", { class: "muted" }, "Watches the server for 30 seconds, then looks through the world.")),
      failed ? h("div", { class: "notice bad mt-s small" }, failed.error) : null,
      r && !job ? h("details", { class: "mt-s", open: Date.now() / 1000 - r.finished < 3600 },
        h("summary", {}, (r.automatic ? t("Looked by itself") : t("Last look")) + ` · ${ago(r.finished)}` + (r.tps ? ` · ${r.tps} TPS` : "")),
        h("p", { class: "small" }, t(r.summary)),
        r.findings.length ? findings(r) : null,
        r.note ? h("p", { class: "muted small" }, r.note) : null) : null);
    if (job && !timer) timer = setInterval(poll, 2000);
    if (!job && timer) { clearInterval(timer); timer = null; }
  };
  const poll = async () => {
    if (timer && !el.isConnected) { clearInterval(timer); timer = null; return; }
    const st = await api("/api/performance/lag").catch(() => null);
    if (st) render(st);
  };
  async function start() {
    const r = await api("/api/performance/lag", { method: "POST", body: {} }).catch((e) => { toast(e.message, true); return null; });
    if (r) poll();
  }
  poll();
  const setUp = (v) => { if (v !== up) { up = v; if (lastState) render(lastState); } };
  return { el, poll, setUp, get running() { return running; } };
}

function perfCard() {
  const body = h("div", {}, h("p", { class: "muted small" }, "Measuring…"));
  const lag = lagBox();
  const el = card("Performance", body, lag.el);
  const spark = (samples) => {
    const pts = samples.filter((x) => x.tps !== null).slice(-60);
    if (pts.length < 2) return null;
    const NS = "http://www.w3.org/2000/svg", W = 240, H = 40;
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("class", "tps-graph"); svg.setAttribute("role", "img");
    const low = Math.min(...pts.map((x) => x.tps));
    svg.setAttribute("aria-label", t("Speed over the last hour: lowest {low} TPS").replace("{low}", low.toFixed(1)));
    const t0 = pts[0].time, span = Math.max(1, pts[pts.length - 1].time - t0);
    const d = pts.map((x, i) => `${i ? "L" : "M"}${(W * (x.time - t0) / span).toFixed(1)},${(H - 2 - (H - 4) * Math.max(0, Math.min(20, x.tps)) / 20).toFixed(1)}`).join(" ");
    const line = document.createElementNS(NS, "path");
    line.setAttribute("d", d); line.setAttribute("fill", "none"); line.setAttribute("class", "tps-line");
    const ref = document.createElementNS(NS, "line");
    for (const [k, v] of [["x1", 0], ["x2", W], ["y1", 2], ["y2", 2]]) ref.setAttribute(k, v);
    ref.setAttribute("class", "tps-ref");
    svg.append(ref, line);
    return svg;
  };
  const load = async () => {
    const r = await api("/api/performance").catch(() => null);
    if (!r) return;
    lag.setUp(!!r.running);
    if (!r.supported) { fill(body, h("p", { class: "muted small" }, "This Minecraft version can't report its speed (it needs Minecraft 1.20.3 or newer, or Paper, Purpur, Forge or NeoForge).")); return; }
    if (!r.running) { fill(body, h("p", { class: "muted small" }, "Start the server to see how well it keeps up.")); return; }
    const c = r.current;
    const tips = r.status === "bad" || r.status === "warn" ? h("details", { class: "small mt-s" }, h("summary", {}, "What slows a server down"),
      h("ul", {},
        h("li", {}, "Exploring new terrain: pre-generate the world (the Chunky mod) so it's ready before people get there."),
        h("li", {}, "Lots of mobs, item farms or redstone clocks in loaded areas."),
        h("li", {}, "Too little memory: see Check my setup; or too much, without Aikar's flags (Settings)."),
        h("li", {}, "A heavy mod: Find what's causing lag names it, and a profile with spark shows more."))) : null;
    fill(body,
      h("div", { class: "row" },
        h("strong", { class: `tps-value ${r.status}` }, c ? `${c.tps.toFixed(1)} TPS` : "…"),
        h("span", { class: "grow small" }, r.words, c && c.mspt !== null ? ` · ${c.mspt.toFixed(1)} ms per tick (under 50 keeps up)` : ""),
        spark(r.samples)),
      tips,
      r.spark ? h("div", { class: "row mt-s small" },
        h("button", { class: "btn small", onclick: () => act(() => api("/api/performance/spark", { method: "POST", body: {} })).then((x) => x && toast(x.message)) }, "Profile 30 s with spark"),
        r.spark_url ? h("a", { href: r.spark_url, target: "_blank", rel: "noopener noreferrer" }, "Latest spark report ↗") : null) : null);
  };
  return { el, load };
}

// Check my setup: what most often stops a server or friends, each with what to do. Testing from
// the internet asks an outside service, so it only runs when asked; the report (for a bug
// report) leaves secrets out.
const DOCTOR_ICON = { ok: "✓", warn: "⚠", bad: "✗", info: "ℹ" };
function openDoctor() {
  if ($("#doctor")) return;
  const list = h("ul", { class: "list doctor-list" }, h("li", { class: "muted" }, h("span", { class: "spinner" }), " Checking…"));
  const internet = h("div");
  // A fix Craft Conductor can do itself: one press, then the checks run again.
  const fix = async (c, btn) => {
    const body = { action: c.action };
    if (c.action === "eula") {
      if (!(await ask("Minecraft's End User License Agreement (EULA) is Mojang's terms for running a Minecraft server. " +
        "Read it at https://aka.ms/MinecraftEULA.\n\nDo you accept it?", { ok: "I accept the EULA" }))) return;
      body.accept = true;
    }
    btn.disabled = true;
    try {
      const r = await api("/api/doctor/fix", { method: "POST", body });
      toast(r.message);
      load();
    } catch (e) { if (!(e instanceof Unauthorized)) toast(e.message, true); btn.disabled = false; }
  };
  const row = (c) => {
    const btn = c.action ? h("button", { class: "btn small primary", onclick: () => fix(c, btn) }, c.action_label) : null;
    return h("li", { class: `doctor-item ${c.status}` },
      h("span", { class: "doctor-icon", "aria-hidden": "true" }, DOCTOR_ICON[c.status] || "•"),
      h("div", { class: "grow" }, h("strong", {}, c.title), h("div", { class: "small" }, c.detail),
        c.fix ? h("div", { class: "small muted" }, "→ ", c.fix) : null,
        btn ? h("div", { class: "mt-s" }, btn) : null));
  };
  const load = async () => {
    try {
      const r = await api("/api/doctor");
      const order = { bad: 0, warn: 1, info: 2, ok: 3 };
      fill(list, [...r.checks].sort((a, b) => order[a.status] - order[b.status]).map(row));
    } catch (e) { if (!(e instanceof Unauthorized)) fill(list, h("li", { class: "bad-text" }, e.message)); }
  };
  const testBtn = h("button", { class: "btn", onclick: async () => {
    testBtn.disabled = true;
    fill(internet, h("p", { class: "muted small" }, h("span", { class: "spinner" }), " Asking ifconfig.co to connect to your server…"));
    try { fill(internet, h("ul", { class: "list doctor-list" }, row(await api("/api/doctor/internet", { method: "POST", body: {} })))); }
    catch (e) { if (!(e instanceof Unauthorized)) fill(internet, h("p", { class: "bad-text small" }, e.message)); }
    testBtn.disabled = false;
  } }, "🌐 Test from the internet");
  const close = () => { $("#doctor").remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  const box = h("div", { class: "modal doctor" },
    h("div", { class: "row" }, h("h2", { id: "doctor-title", class: "grow" }, "Check my setup"),
      h("button", { class: "btn ghost small", onclick: close }, "Close")),
    list,
    h("h3", { class: "mt" }, "Can friends outside your home connect?"),
    h("p", { class: "muted small" }, "With the server running, this asks ifconfig.co (an outside service) to connect to your public address on the server's port. Nothing else is sent."),
    h("div", { class: "row" }, testBtn), internet,
    h("div", { class: "row mt" },
      h("button", { class: "btn small", onclick: load }, "Check again"),
      h("a", { class: "btn small ghost", href: scoped("/api/doctor/report"), download: "" }, "⬇ Report for a bug report"),
      h("span", { class: "muted small grow" }, "Logs and settings, with passwords, keys and invite secrets taken out.")));
  document.body.append(h("div", { class: "modal-backdrop", id: "doctor", role: "dialog", "aria-modal": "true", "aria-labelledby": "doctor-title" }, box));
  load();
}

// Playing on this computer too (offered in a browser on the server's own computer): Craft Conductor sets
// up this computer's Minecraft for the server, the way it does for friends, after saying what
// running both on one computer costs.
function playHereCard() {
  const btn = h("button", { class: "btn primary", onclick: () => playHere(btn) }, "🎮 Play on this computer");
  return card("Play on this computer",
    h("p", { class: "muted small" }, "Set up Minecraft on this computer with this server's version and mods, and add the server to your launcher. " +
      "Fine for a small server with a few friends: the game and the server share this computer's memory and CPU."),
    btn);
}
async function playHere(btn) {
  btn.disabled = true;
  try {
    const i = await api("/api/play-here");
    if (!i.installed) { toast("Finish setting up the server first.", true); return; }
    const need = i.server_gb + i.game_gb + 3;  // the server, the game, and the system with everything else
    const short = !!i.system_gb && need > i.system_gb;
    const heavy = i.mods >= 100;  // (20 players is Minecraft's default, so the player limit is said, not flagged)
    const text = [
      "Play on this computer too?",
      `${short ? "⚠ " : ""}Resource heavy: running both the game and the server takes a lot of memory (RAM) and CPU. ` +
        (i.system_gb ? `This computer has ${i.system_gb} GB: the server uses ${i.server_gb} GB, Minecraft about ${i.game_gb} GB, and the system and your other programs about 3 GB. ` : "") +
        (short ? "That's more than this computer has, so both the game and the server will lag, or crash. Give the server less memory (Settings), choose less for Minecraft, or play on another computer."
          : "If memory runs out, both the game and the server lag."),
      "Lag spikes: when players join or the server loads new terrain while you're in an intense moment, you may get severe frame drops in the game, or tick (TPS) lag on the server.",
      `${heavy ? "⚠ " : ""}Heavy modpacks: a heavy modpack or a large public server (15+ players) strains a personal computer heavily and is generally not recommended.` +
        ` This server has ${i.mods} mod${i.mods === 1 ? "" : "s"} and allows ${i.max_players} players at once.`,
    ].join("\n\n");
    // The general warning can be hidden; a problem with this computer or server is always said.
    if (!(await ask(text, { id: short || heavy ? null : "play-here", ok: "Set up Minecraft here" }))) return;
    await api("/api/play-here", { method: "POST", body: {} });
    toast("Minecraft setup opened in a new tab: pick your launcher and press the button.");
  } catch (e) {
    if (!(e instanceof Unauthorized)) toast(e.message, true);
  } finally {
    btn.disabled = false;
  }
}

views.dashboard = () => {
  const statusBody = h("dl", { class: "kv" });
  const update = h("div");
  const events = h("div", { class: "events" });
  const online = h("div", { class: "online" });
  const onlineCount = h("span", { class: "muted" });
  const mapLink = h("div");  // the web map, when there is one and it answers (Settings → Web map)
  const playerCard = h("div", { class: "card" }, h("h3", {}, "Connected Players ", onlineCount), online, mapLink);
  api("/api/webmap").then((r) => {
    if (r.kind && r.answers) fill(mapLink, h("a", { class: "btn small ghost mt-s", href: hubInfo && hubInfo.local ? r.local_url : r.lan_url || r.local_url,
      target: "_blank", rel: "noopener noreferrer" }, `🗺 ${t("See where everyone is on the map")} ↗`));
  }).catch(() => null);
  const cpu = meter("CPU"), mem = meter("RAM"), disk = meter("Disk"), players = meter("Players");
  const perf = perfCard();
  const tun = tunnelCard();
  const con = consolePanel({ compact: true });
  const lagBanner = h("div");
  const problemBox = h("div");
  let problemShown = "";
  let evSeq = 0;
  let selected = null;      // player whose actions are open
  let ops = new Set();
  let shown = "";           // online list last rendered, to keep head icons from flickering

  const gb = (n) => n < 1024 ** 3 ? Math.round(n / 1024 ** 2) + " MB" : (n / 1024 ** 3).toFixed(n >= 10 * 1024 ** 3 ? 0 : 1) + " GB";
  const renderMeters = (s) => {
    players.set(s.max_players ? 100 * s.players.length / s.max_players : 0, `${s.players.length} / ${s.max_players}`, "Connected players");
    disk.set(s.disk && s.disk.total_bytes ? 100 * s.disk.used_bytes / s.disk.total_bytes : null,
      s.disk ? gb(s.disk.used_bytes) : "—", s.disk ? `${gb(s.disk.free_bytes)} free on server volume` : "Disk usage unavailable");
    const r = s.resources;
    if (!r) {
      const idle = s.state === "starting" ? "starting…" : "server stopped";
      cpu.set(0, "—", idle); mem.set(0, "—", idle);
      return;
    }
    cpu.set(r.cpu_percent, r.cpu_percent === null ? "…" : `${Math.round(r.cpu_percent)}%`,
      `of ${r.cpus} CPU core${r.cpus === 1 ? "" : "s"}`);
    mem.set(100 * r.memory_bytes / r.memory_max_bytes, `${gb(r.memory_bytes)} / ${gb(r.memory_max_bytes)}`,
      "used / allowed" + (r.system_memory_bytes ? ` · this computer has ${gb(r.system_memory_bytes)}` : ""));
  };

  const run = async (action, name) => {
    const CONFIRM = { kick: `Kick ${name}?`, ban: `Ban ${name}? They won't be able to join until pardoned.`,
      op: `Make ${name} an operator? Operators can run any command, including /stop and /op.` };
    if (CONFIRM[action] && !(await ask(CONFIRM[action], { id: action === "kick" ? "kick" : null, ok: action === "op" ? "Make operator" : action === "kick" ? "Kick" : "Ban", danger: action !== "op" }))) return;
    const r = await act(() => api("/api/players/action", { method: "POST", body: { action, name } }));
    if (r) { toast(r.message); setTimeout(loadPlayers, 800); }
  };
  const message = async (name) => {
    const text = prompt(`Message to ${name}:`);
    if (!text || !text.trim()) return;
    await act(() => api("/api/command", { method: "POST", body: { command: `tell ${name} ${text.trim().replace(/\s+/g, " ")}` } }), `Sent to ${name}`);
    con.poll();
  };
  const renderOnline = (names, max, force = false) => {
    onlineCount.textContent = `${names.length} / ${max}`;
    const key = names.join(",") + "|" + selected + "|" + [...ops].join(",");
    if (key === shown && !force) return;
    shown = key;
    if (selected && !names.includes(selected)) selected = null;
    if (!names.length) { fill(online, h("p", { class: "empty" }, "Nobody online right now.")); return; }
    fill(online,
      h("div", { class: "chips" }, names.map((n) => h("button", {
        type: "button", class: "chip" + (n === selected ? " selected" : ""), title: `Manage ${n}`,
        "aria-expanded": n === selected ? "true" : "false",
        onclick: () => { selected = selected === n ? null : n; renderOnline(names, max, true); },
      }, playerHead(n, 28), h("span", {}, n), ops.has(n.toLowerCase()) ? h("span", { class: "badge" }, "op") : null))),
      selected ? h("div", { class: "row mt-s player-actions" },
        h("strong", { class: "grow" }, selected),
        h("button", { class: "btn small", onclick: () => message(selected) }, "Message"),
        ops.has(selected.toLowerCase())
          ? h("button", { class: "btn small", onclick: () => run("deop", selected) }, "Remove op")
          : h("button", { class: "btn small", onclick: () => run("op", selected) }, "Make op"),
        h("button", { class: "btn small", onclick: () => run("kick", selected) }, "Kick"),
        h("button", { class: "btn small danger", onclick: () => run("ban", selected) }, "Ban"),
        h("a", { class: "btn small ghost", href: link("players") }, "More…")) : null);
  };
  const loadPlayers = async () => {
    const r = await api("/api/players").catch(() => null);
    if (!r) return;
    ops = new Set(r.ops.map((o) => (o.name || "").toLowerCase()));
    if (status) renderOnline(status.players, status.max_players);
  };

  // What went wrong (a crash or a failed start), in plain words with the fixes Craft Conductor can do.
  const renderProblem = (p) => {
    const key = p ? JSON.stringify([p.time, p.fixed]) : "";
    if (key === problemShown) return;
    problemShown = key;
    if (!p) { fill(problemBox); return; }
    const press = async (a) => {
      if (a.kind === "backups") { location.hash = link("backups"); return; }
      const body = { kind: a.kind, filename: a.filename };
      if (a.kind === "eula") {
        if (!(await ask("Minecraft's End User License Agreement (EULA) is Mojang's terms for running a Minecraft server. " +
          "Read it at https://aka.ms/MinecraftEULA.\n\nDo you accept it?", { ok: "I accept the EULA" }))) return;
        body.accept = true;
      }
      const r = await act(() => api("/api/problem/fix", { method: "POST", body }), null);
      if (r) { toast(r.message); refreshStatus(); }
    };
    fill(problemBox, h("div", { class: "notice bad mt problem" },
      h("div", { class: "row" }, h("strong", { class: "grow" }, p.kind === "start" ? "The server didn't start: " : "The server crashed: ", p.title),
        h("span", { class: "muted small" }, ago(p.time))),
      h("p", { class: "small" }, p.words),
      p.evidence ? h("details", { class: "small" }, h("summary", {}, "What Minecraft said"), h("pre", { class: "log" }, p.evidence)) : null,
      p.fixed ? h("div", { class: "row mt-s" }, h("span", { class: "grow small ok-text" }, `✓ ${p.fixed}`),
        h("button", { class: "btn primary small", onclick: () => act(() => api("/api/server/start", { method: "POST", body: {} }), "Starting…").then(() => press({ kind: "dismiss" })) }, "Start the server"))
        : h("div", { class: "row mt-s" }, (p.actions || []).map((a) => h("button", { class: "btn small primary", onclick: () => press(a) }, a.label)),
          h("button", { class: "btn small ghost", onclick: () => press({ kind: "dismiss" }) }, "Dismiss"))));
  };

  const render = (s) => {
    renderProblem(s.problem);
    renderMeters(s);
    renderOnline(s.players, s.max_players);
    fill(statusBody,
      h("dt", {}, "State"), h("dd", {}, h("span", { class: "pill " + s.state }, s.state)),
      h("dt", {}, "Uptime"), h("dd", {}, s.uptime ? fmtDuration(s.uptime) : "—"),
      h("dt", {}, "Minecraft"), h("dd", {}, s.minecraft || "not installed"),
      h("dt", {}, "Loader"), h("dd", {}, `${s.loader} ${s.loader_version || ""}`),
      h("dt", {}, "Java"), h("dd", {}, s.java_major ? `Java ${s.java_major}${s.java_forced ? ` (forced ${s.java_forced})` : ""}` : "—"),
      h("dt", {}, "Mods"), h("dd", {}, String(s.mods)),
      h("dt", {}, "Port"), h("dd", {}, s.port),
    );
    const u = s.update;
    fill(lagBanner, u ? laggingNotice(u.lagging, s.minecraft) : null);
    fill(update,
      !u ? h("p", { class: "empty" }, "Not checked yet.")
        : u.up_to_date && u.latest !== s.minecraft
          ? h("div", { class: "notice warn" }, `On the newest version your mods support. Minecraft ${u.latest} is out; waiting on mods (see Updates).`)
        : u.up_to_date ? h("div", { class: "notice ok" }, `Up to date on the latest release (${u.latest}).`)
        : u.target ? h("div", { class: "notice warn" }, `Update ready: Minecraft ${u.target}`,
            u.manual ? h("div", { class: "small" }, `${u.manual} manual download(s) needed`) : null)
        : h("div", { class: "notice bad" }, `Minecraft ${u.latest} is out but nothing installable yet.`),
      u ? h("p", { class: "muted small" }, `Checked ${ago(u.checked_at)} · strategy ${s.strategy} · auto-upgrade ${s.auto_upgrade ? "on" : "off"}`) : null,
      h("div", { class: "row" },
        h("button", { class: "btn", onclick: () => act(() => api("/api/updates/check", { method: "POST", body: {} }), "Checking for updates…") }, "Check now"),
        h("a", { href: link("updates"), class: "btn ghost" }, "Details →")),
    );
  };

  const pollEvents = async () => {
    const r = await api(`/api/events?since=${evSeq}`).catch(() => null);
    if (!r) return;
    evSeq = r.last;
    for (const e of r.events) {
      events.prepend(h("div", { class: "ev " + e.level }, h("time", {}, fmtClock(e.time)), h("span", {}, e.message)));
    }
    while (events.childElementCount > 200) events.lastChild.remove();
  };

  fill($("#main"),
    h("h2", { class: "view-title" }, "Dashboard"),
    problemBox,
    lagBanner,
    h("section", { class: "cc-panel cc-dashboard", "aria-label": "Server dashboard" },
      h("div", { class: "cc-telemetry-grid", "aria-label": "Server telemetry" }, cpu.el, mem.el, disk.el, players.el),
      h("div", { class: "cc-dashboard-layout" }, con.el,
        h("aside", { class: "cc-dashboard-rail", "aria-label": "Server details" }, playerCard,
          card("Runtime Parameters", statusBody,
            h("div", { class: "row mt-s" }, h("button", { class: "btn small", onclick: openDoctor }, "🩺 Check my setup"),
              folderBtn("server", "Server folder"), folderBtn("world", "World folder")))))),
    h("div", { class: "mt" }, perf.el),
    tun.el,
    askingNotice(),
    hubInfo && hubInfo.local ? h("div", { class: "mt" }, playHereCard()) : null,
    card("Updates", update),
    h("div", { class: "card mt" }, h("h3", {}, "Activity"), events),
  );
  if (status) render(status);
  every(3000, pollEvents);
  every(30000, perf.load);
  every(60000, () => tun.load());
  every(1000, con.poll);
  every(5000, loadPlayers);
  return { onStatus: render };
};

views.console = () => {
  const con = consolePanel();
  const folders = hubInfo && hubInfo.local ? h("div", { class: "row mb" }, folderBtn("logs", "Logs folder"), folderBtn("crash", "Crash reports")) : null;
  fill($("#main"), folders, con.el);
  con.input.focus();
  every(1000, con.poll);
  return {};
};

// Mods holding back a newer Minecraft. After a month (and every month after) the admin is
// asked whether to remove them and update; "Keep waiting" hides it until the next reminder.
function laggingNotice(lag, installed, always = false) {
  if (!lag || !lag.mods.length) return null;
  const round = Math.floor(lag.days / lag.remind_days);
  const key = `craft-conductor-lag-${server}-${lag.version}-${round}`;
  let hidden = false;
  try { hidden = localStorage.getItem(key) === "1"; } catch (_) { /* private mode */ }
  if (!always && (!lag.due || hidden)) return null;
  const removable = lag.mods.filter((m) => m.config);
  const el = h("div", { class: "notice " + (lag.due ? "warn" : "") + " lagging" },
    h("strong", {}, lag.due ? `Minecraft ${lag.version} came out ${lag.days} days ago, and ${lag.mods.length === 1 ? "a mod hasn't" : `${lag.mods.length} mods haven't`} caught up`
      : `Minecraft ${lag.version} is out; waiting for ${lag.mods.length === 1 ? "a mod" : `${lag.mods.length} mods`} to support it`),
    h("p", { class: "small" }, `The server stays on Minecraft ${installed} until every mod supports ${lag.version}, so nothing breaks. ` +
      (lag.due ? "You can wait longer, or remove these mods and update now:" : `craft-conductor reminds you ${lag.remind_days} days after the release if they still haven't. These are:`)),
    h("ul", { class: "small" }, lag.mods.map((m) => h("li", {}, h("strong", {}, m.name), m.required ? h("span", { class: "tag" }, "required") : null,
      h("span", { class: "muted" }, ` — ${m.reason}`)))),
    h("div", { class: "row" },
      removable.length ? h("button", { class: "btn " + (lag.due ? "danger" : "small"), onclick: async () => {
        const names = removable.map((m) => m.name).join(", ");
        if (!(await ask(`Remove ${names} from this server and update to Minecraft ${lag.version}?\n\n` +
          "Their blocks and items disappear from the world. A backup is made first, and the update rolls back if the new version fails to start. " +
          "You can add the mods back later, once they support the new version.", { ok: "Remove and update", danger: true }))) return;
        act(() => api("/api/updates/remove-and-upgrade", { method: "POST", body: { version: lag.version, mods: removable.map((m) => m.config) } }),
          `Removing ${removable.length} mod(s) and updating…`);
      } }, `Remove ${removable.length === 1 ? "it" : "them"} and update to ${lag.version}`) : null,
      lag.due && !always ? h("button", { class: "btn ghost", onclick: () => { try { localStorage.setItem(key, "1"); } catch (_) {} el.remove(); } }, "Keep waiting") : null));
  return el;
}

// Why a newer Minecraft isn't installable yet: the loader and every installed mod, coloured.
function openReadiness(versions, installed) {
  const body = h("div", { class: "readiness-body" }, h("p", { class: "muted" }, "Checking each mod…"));
  const pick = h("select", { "aria-label": "Minecraft version" }, versions.map((v) => h("option", { value: v }, `Minecraft ${v}`)));
  const legend = h("div", { class: "row small legend" },
    h("span", { class: "dotc green" }), "ready (a release build)",
    h("span", { class: "dotc yellow" }), "only an alpha/beta build (may be unstable)",
    h("span", { class: "dotc red" }), "no build yet",
    h("span", { class: "dotc unknown" }), "can't tell");
  const load = async () => {
    fill(body, h("p", { class: "muted" }, `Checking each mod for Minecraft ${pick.value}…`));
    const r = await api(`/api/updates/readiness?version=${encodeURIComponent(pick.value)}`).catch((e) => { fill(body, h("div", { class: "notice bad" }, e.message)); return null; });
    if (!r || r.minecraft !== pick.value) return;
    const row = (state, name, detail, extra) => h("li", { class: "ready-row " + state }, h("span", { class: "dotc " + state, title: state }),
      h("div", { class: "grow" }, h("strong", {}, name), extra || null, h("div", { class: "muted small" }, detail)));
    const n = r.counts;
    const verdict = r.loader.state === "red" ? `${r.loader.name} doesn't support Minecraft ${r.minecraft} yet, so nothing can move until it does.`
      : n.red ? `${n.red} mod${n.red === 1 ? " has" : "s have"} no build for Minecraft ${r.minecraft} yet.`
        : n.unknown || r.loader.state === "unknown" ? "Compatibility could not be confirmed for every file. Check local files on Mods and retry any failed lookups before upgrading."
        : n.yellow ? `Every mod has a build, but ${n.yellow} only ${n.yellow === 1 ? "has" : "have"} alpha/beta builds. Craft Conductor waits for releases unless you allow early builds.`
          : `Everything is ready for Minecraft ${r.minecraft}. Run a check on the Updates tab to move.`;
    fill(body,
      h("div", { class: "notice " + (r.loader.state === "red" || n.red ? "bad" : n.yellow || n.unknown || r.loader.state === "unknown" ? "warn" : "ok") }, verdict),
      h("ul", { class: "list mt-s" },
        row(r.loader.state, `${r.loader.name[0].toUpperCase()}${r.loader.name.slice(1)} (server type)`,
          r.loader.state === "green" ? `ready (${r.loader.version})` : r.loader.state === "red" ? `no ${r.loader.name} build for Minecraft ${r.minecraft} yet` : "couldn't check it right now"),
        r.mods.map((m) => row(m.state, m.name,
          { green: "has a release build", yellow: `only ${m.channel} builds so far`, red: `no build for Minecraft ${r.minecraft} yet`, unknown: "can't tell (your own file, or the lookup failed)" }[m.state] +
            ` · installed ${m.version}`,
          [m.needed_by ? h("span", { class: "tag" }, `needed by ${m.needed_by}`) : null, m.required ? null : h("span", { class: "tag" }, "optional")]))),
      r.mods.length ? null : h("p", { class: "empty" }, "No mods installed."));
  };
  pick.addEventListener("change", load);
  openSidePane(h("div", { class: "readiness" },
    h("div", { class: "row" }, h("h2", { class: "grow" }, "Why it's waiting"), pick,
      h("button", { class: "btn ghost small", onclick: () => closeBrowser() }, "Close")),
    h("p", { class: "muted small" }, `This server is on Minecraft ${installed || "(not installed yet)"}. Each installed mod, checked for the version above:`),
    legend, body), "Update readiness");
  load();
}

// Update rehearsal: the update tried on a copy of the server (world included) that runs for a
// few minutes where nobody can join; then a report, and "Update for real".
function rehearsalCard(c, applyNow, applyBtn) {
  const el = h("div", { class: "card" });
  const minutes = h("select", { "aria-label": "How long to watch the copy" },
    [[1, "1 minute"], [3, "3 minutes"], [5, "5 minutes"], [10, "10 minutes"]].map(([n, label]) => h("option", { value: n, selected: n === 3 }, label)));
  let timer = null;
  const stat = (label, value, cls = "") => h("div", { class: "rehearsal-stat " + cls }, h("span", { class: "muted small" }, label), h("strong", {}, value));
  const report = (r) => {
    const cur = r.fingerprint === c.fingerprint;
    const cm = r.complaints || { mods: [], other: { warnings: 0, errors: 0, examples: [] }, lag: { count: 0, worst_ms: 0 } };
    const tps = r.tps_avg === null || r.tps_avg === undefined ? "not measured"
      : `${r.tps_avg} TPS` + (r.tps_min !== null && r.tps_min < r.tps_avg ? ` (lowest ${r.tps_min})` : "");
    const cls = { good: "ok", warn: "warn", bad: "bad" }[r.verdict] || "bad";
    return h("div", {},
      h("div", { class: "notice " + cls }, h("strong", {}, { good: "✓ ", warn: "⚠ ", bad: "✗ " }[r.verdict] || ""), t(r.summary || r.error || "")),
      h("p", { class: "muted small" }, `Minecraft ${r.from || "?"} → ${r.to || "?"}, tried ${ago(r.finished)}` +
        (cur ? "." : ". That was for an earlier version of this update: rehearse again to try this one.")),
      r.started ? h("div", { class: "rehearsal-stats" },
        stat("Started in", `${r.start_seconds} s`),
        stat("Kept up", tps, r.tps_avg !== null && r.tps_avg < 18 ? "bad-text" : ""),
        stat("Fell behind", cm.lag.count ? `${cm.lag.count} time(s), worst ${Math.round(cm.lag.worst_ms / 50)} ticks` : "never", cm.lag.count >= 3 ? "bad-text" : ""),
        stat("Ran for", `${r.minutes} min`)) : null,
      cm.mods.length ? h("div", { class: "mt-s" }, h("strong", {}, "Mods that complained in the log"),
        h("ul", { class: "list" }, cm.mods.map((m) => h("li", {}, h("details", { class: "grow" },
          h("summary", {}, h("strong", {}, m.name), " ",
            m.errors ? h("span", { class: "tag bad" }, `${m.errors} error(s)`) : null, " ",
            m.warnings ? h("span", { class: "tag" }, `${m.warnings} warning(s)`) : null),
          h("pre", { class: "rehearsal-lines" }, m.examples.join("\n"))))))) : null,
      cm.other.warnings + cm.other.errors ? h("details", { class: "mt-s" },
        h("summary", { class: "muted small" }, `${cm.other.warnings + cm.other.errors} other warning(s) not about a particular mod`),
        h("pre", { class: "rehearsal-lines" }, cm.other.examples.join("\n"))) : null,
      r.diagnosis && r.diagnosis.suspects && r.diagnosis.suspects.length ? h("p", { class: "small" }, t("Suspects:") + " " + r.diagnosis.suspects.map((x) => x.name).join(", ")) : null,
      r.last_lines ? h("details", { class: "mt-s" }, h("summary", { class: "muted small" }, "The copy's last lines"),
        h("pre", { class: "rehearsal-lines" }, r.last_lines.join("\n"))) : null,
      r.note ? h("p", { class: "muted small" }, r.note) : null,
      cur ? h("div", { class: "row mt-s" },
        h("button", { class: r.verdict === "bad" ? "btn danger" : "btn primary", onclick: applyNow }, r.verdict === "bad" ? "Update anyway" : "Update for real"),
        h("span", { class: "muted small" }, r.verdict !== "bad" ? "The real update still makes a backup first."
          : (r.diagnosis && r.diagnosis.suspects && r.diagnosis.suspects.length) || cm.mods.some((m) => m.errors)
            ? "Not recommended: fix the problem first (update or remove the mod named)." : "Not recommended: fix the problem first (see the copy's last lines).")) : null);
  };
  const render = (st) => {
    const job = st.rehearsal && st.rehearsal.state === "running" ? st.rehearsal : null;
    const last = st.rehearsal && st.rehearsal.state === "failed" ? st.rehearsal : null;
    if (st.report && st.report.fingerprint === c.fingerprint && ["good", "warn"].includes(st.report.verdict)) {
      applyBtn.textContent = t("Apply update") + " ✓";
      applyBtn.title = t("It worked on a copy of the server");
    }
    fill(el, h("h3", {}, "Rehearse it on a copy first"),
      h("p", { class: "muted small" }, "Try this update before it touches your server: Craft Conductor copies the server and its world, installs the update on the copy and runs it for a few minutes where nobody can join. You get a report: did it start, did it keep up, which mods complained. This server keeps running and isn't changed; the copy is deleted afterwards."),
      job ? h("div", {},
        h("div", { class: "row" }, h("span", { class: "grow" }, t(job.step || "Getting ready…")),
          h("button", { class: "link-btn", onclick: () => api("/api/updates/rehearsal/stop", { method: "POST" }).catch(() => null) }, "Stop")),
        (() => { const bar = h("div", { class: "bar" + (job.progress === null ? " indeterminate" : "") }, h("div", { class: "bar-fill" }));
          if (job.progress !== null) bar.firstChild.style.width = `${Math.round(job.progress * 100)}%`; return bar; })())
        : h("div", { class: "row" }, h("label", { class: "row small" }, "Watch it for", minutes),
          h("button", { class: "btn", onclick: start }, st.report ? "Rehearse again" : "Rehearse the update")),
      last && last.result ? h("div", { class: "notice bad mt-s" }, t("The rehearsal couldn't be done:") + " " + last.result.error) : null,
      st.report && !job ? h("div", { class: "mt-s" }, report(st.report)) : null);
    if (job && !timer) timer = setInterval(poll, 2000);
    if (!job && timer) { clearInterval(timer); timer = null; }
  };
  const poll = async () => {
    if (timer && !el.isConnected) { clearInterval(timer); timer = null; return; }  // (the page moved on)
    const st = await api("/api/updates/rehearsal").catch(() => null);
    if (st) render(st);
  };
  async function start() {
    const n = Number(minutes.value);
    if (!(await ask(`Rehearse the update to Minecraft ${c.target}? Copying the server takes a moment (longer for a big world), ` +
      `then the copy runs for ${n} minute(s). The computer works harder meanwhile, and it needs free disk space for the copy.`, { id: "rehearse-update", ok: "Rehearse" }))) return;
    const r = await api("/api/updates/rehearsal", { method: "POST", body: { target: c.target, minutes: n } }).catch((e) => { toast(e.message, true); return null; });
    if (r) poll();
  }
  poll();
  return el;
}

views.updates = () => {
  const body = h("div");
  const load = async () => {
    const r = await api("/api/updates").catch(() => null);
    if (!r) return;
    const c = r.check;
    const s = status || {};
    const checkBtn = h("button", { class: "btn", onclick: () => act(() => api("/api/updates/check", { method: "POST", body: {} }), "Checking…") }, "Check now");
    // Betas are tried on a copy, so the real world never meets one.
    const betaCard = h("div");
    api("/api/beta").then((r) => {
      if (!r.betas.length || !r.copies) return;
      const pick = h("select", { "aria-label": "Beta version" }, r.betas.map((v) => h("option", { value: v }, `Minecraft ${v}`)));
      fill(betaCard, card("Test a beta version",
        h("p", { class: "muted small" }, "Try the next Minecraft before it's released. Craft Conductor makes a separate copy of this server " +
          "(world, mods and settings) on the beta, so this server and its world aren't touched. In the copy, mods that don't support " +
          "the beta yet are left out. Delete the copy when you're done."),
        h("div", { class: "row" }, pick, h("button", { class: "btn", onclick: async () => {
          if (!(await ask(`Make a copy of this server on Minecraft ${pick.value}? It appears in your server list as a separate server.`, { ok: "Make a copy" }))) return;
          act(() => api("/api/beta/test", { method: "POST", body: { version: pick.value } }), "Copying the server…");
        } }, "Make a test copy"))));
    }).catch(() => {});
    if (!c) {
      fill(body, card(null, h("p", {}, "No update check has run yet."), checkBtn), h("div", { class: "mt" }, betaCard));
      return;
    }
    const applyNow = async () => {
      const running = s.state === "running";
      if (await ask(`Update to Minecraft ${c.target}?` + (running ? "\n\nPlayers get an in-game countdown, then the server restarts. A backup is made first and it rolls back automatically if the new version fails to start." : ""), { id: "update-minecraft", ok: "Update" }))
        act(() => api("/api/updates/apply", { method: "POST", body: { target: c.target } }), "Update started");
    };
    const applyBtn = h("button", {
      class: "btn primary", disabled: c.up_to_date || !c.target || c.manual.length > 0, onclick: applyNow,
    }, c.installed ? "Apply update" : "Install server");
    const rehearseCard = c.installed && c.target && !c.up_to_date && !c.manual.length ? rehearsalCard(c, applyNow, applyBtn) : null;

    // Newer versions to explain, newest first (the blocked ones the check found, and the latest).
    const newer = [...new Set([c.latest, ...c.blocked.map((b) => b.minecraft)].filter((v) => v && v !== c.installed))];
    const summary = c.up_to_date
      ? h("div", { class: c.latest === c.installed ? "notice ok" : "notice warn" },
          c.latest === c.installed ? `Up to date on the latest release, Minecraft ${c.installed}.`
            : [`Up to date on Minecraft ${c.installed}, the newest version your mods support. ${c.latest} is waiting. `,
              h("button", { class: "btn small", onclick: () => openReadiness(newer, c.installed) }, "Show why")])
      : c.target
        ? h("div", { class: "notice warn" }, h("strong", {}, c.installed === c.target ? `Ready: mod updates for Minecraft ${c.target}`
            : `Ready: Minecraft ${c.installed || "(new install)"} → ${c.target}`),
            c.loader_version ? h("span", { class: "muted" }, `  (loader ${c.loader_version})`) : null)
        : h("div", { class: "notice bad" }, "No installable combination of Minecraft, loader and required mods was found.");

    const manual = c.manual.length ? card("Manual downloads needed",
      h("p", { class: "muted" }, "These mod authors don't allow automatic downloads. Download each file from its link, then upload it here (or copy it into the manual-downloads folder)."),
      folderBtn("manual", "Manual-downloads folder"),
      h("ul", { class: "list" }, c.manual.map((m) => {
        const file = h("input", { type: "file", accept: ".jar", class: "hidden" });
        file.addEventListener("change", async () => {
          const f = file.files[0];
          if (!f) return;
          if (f.name !== m.filename && !(await ask(`The selected file is "${f.name}", expected "${m.filename}". Upload anyway?`, { ok: "Upload" }))) return;
          await act(() => api(`/api/manual/upload?filename=${encodeURIComponent(m.filename)}`, { method: "POST", raw: f }), `Uploaded ${m.filename}`);
          load();
        });
        return h("li", {},
          h("div", { class: "grow" }, h("div", {}, h("strong", {}, m.name)), h("code", {}, m.filename)),
          h("a", { class: "btn", href: m.url, target: "_blank", rel: "noopener noreferrer" }, "Download ↗"),
          h("button", { class: "btn primary", onclick: () => file.click() }, "Upload"), file);
      }))) : null;

    const changes = c.changes.length ? card("Changes", h("ul", { class: "list" }, c.changes.map((line) =>
      h("li", { class: line.startsWith("+") ? "change-add" : line.startsWith("-") ? "change-rm" : "" }, line)))) : null;

    const blocked = c.blocked.length ? card("Newer versions that are blocked",
      h("div", { class: "row mb" }, h("button", { class: "btn small", onclick: () => openReadiness(newer, c.installed) }, "Show why, mod by mod")),
      h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Minecraft"), h("th", {}, "Waiting on"))),
        h("tbody", {}, c.blocked.map((b) => h("tr", {},
          h("td", {}, b.minecraft),
          h("td", {}, h("ul", { class: "list" },
            b.loader_missing ? h("li", {}, "Loader has no build for this version yet") : null,
            b.blockers.map((x) => h("li", {}, h("div", {}, h("strong", {}, x.name), x.waiting ? h("span", { class: "tag" }, "optional") : null,
              h("div", { class: "muted small" }, x.reason)))))),
        ))))) : null;

    const dropped = c.dropped.length ? card("Left out (optional or client-only)",
      h("ul", { class: "list" }, c.dropped.map((x) => h("li", {}, h("div", {}, h("strong", {}, x.name), h("div", { class: "muted small" }, x.reason)))))) : null;


    fill(body, 
      summary,
      laggingNotice(c.lagging, c.installed, true),
      h("div", { class: "row mb mt-s" }, applyBtn, checkBtn, h("span", { class: "muted small" }, `Last checked ${ago(c.checked_at)}`)),
      manual, rehearseCard, changes, blocked, dropped, h("div", { class: "mt" }, betaCard));
  };
  fill($("#main"), h("h2", { class: "view-title" }, "Updates"), body);
  load();
  return { onJobDone: load };
};

views.players = () => {
  const body = h("div");
  const name = h("input", { placeholder: "Player name", autocomplete: "off", maxlength: 16 });
  const reason = h("input", { placeholder: "Reason (optional, shown when kicked/banned)", maxlength: 200 });
  let data = null;

  const CONFIRM = {
    kick: (n) => `Kick ${n}?`, ban: (n) => `Ban ${n}? They won't be able to join until pardoned.`,
    "ban-ip": (n) => `Ban the IP address of ${n}? Everyone on that connection will be blocked.`,
    op: (n) => `Make ${n} an operator? Operators can run any command, including /stop and /op.`,
  };
  const run = async (action, target, why) => {
    if (CONFIRM[action] && !(await ask(CONFIRM[action](target), { id: action === "kick" ? "kick" : null, ok: action === "op" ? "Make operator" : action === "kick" ? "Kick" : "Ban", danger: action !== "op" }))) return;
    const r = await act(() => api("/api/players/action", { method: "POST", body: { action, name: target, reason: why || reason.value } }));
    if (r) { toast(r.message); setTimeout(load, 800); }
  };
  const btn = (label, action, target, cls = "") => h("button", { class: `btn small ${cls}`, onclick: () => run(action, target) }, label);

  const load = async () => {
    const r = await api("/api/players").catch(() => null);
    if (!r) return;
    data = r;
    const lc = (list) => new Set(list.map((x) => (x.name || "").toLowerCase()));
    const ops = lc(r.ops), wl = lc(r.whitelist), banned = lc(r.bans);
    const actionsFor = (n) => {
      const k = n.toLowerCase();
      return h("div", { class: "row" },
        r.running && r.online.includes(n) ? btn("Kick", "kick", n) : null,
        ops.has(k) ? btn("De-op", "deop", n) : btn("Op", "op", n),
        r.whitelist_enabled || wl.has(k) ? (wl.has(k) ? btn("Un-whitelist", "whitelist-remove", n) : btn("Whitelist", "whitelist-add", n)) : null,
        banned.has(k) ? btn("Pardon", "pardon", n) : btn("Ban", "ban", n, "danger"),
        r.running && r.online.includes(n) ? btn("Ban IP", "ban-ip", n, "danger") : null);
    };
    const tags = (n) => {
      const k = n.toLowerCase();
      return [ops.has(k) ? h("span", { class: "tag ok" }, "op") : null, wl.has(k) ? h("span", { class: "tag" }, "whitelisted") : null,
              banned.has(k) ? h("span", { class: "tag bad" }, "banned") : null];
    };
    const playerList = (names, empty) => names.length
      ? h("ul", { class: "list" }, names.map((n) => h("li", {}, h("div", { class: "grow" }, h("strong", {}, n), tags(n)), actionsFor(n))))
      : h("p", { class: "empty" }, empty);

    const onlineSet = new Set(r.online.map((n) => n.toLowerCase()));
    const known = r.known.map((k) => k.name).filter((n) => n && !onlineSet.has(n.toLowerCase()));

    fill(body,
      r.running ? null : h("div", { class: "notice" }, "The server is stopped. Changes are written to its player files and apply when it starts. Kicking needs the server running."),
      !r.online_mode ? dismissible("offline-mode", h("div", { class: "notice warn" }, "online-mode is off: anyone can join with any name, so bans and the whitelist only match names, not accounts.")) : null,
      h("div", { class: "grid mt" },
        card(`Online now (${r.online.length})`, playerList(r.online, r.running ? "Nobody online" : "Server is stopped")),
        card(`Operators (${r.ops.length})`, r.ops.length ? h("ul", { class: "list" }, r.ops.map((o) => h("li", {},
          h("div", { class: "grow" }, h("strong", {}, o.name), h("span", { class: "tag" }, `level ${o.level}`)), btn("De-op", "deop", o.name)))) : h("p", { class: "empty" }, "No operators"))),
      h("div", { class: "grid mt" },
        card("Whitelist",
          h("div", { class: "row mb" },
            h("span", { class: "grow" }, "Whitelist is ", h("strong", {}, r.whitelist_enabled ? "on" : "off"),
              h("span", { class: "muted small" }, r.whitelist_enabled ? ": only listed players can join" : ": anyone can join")),
            h("button", { class: "btn small", onclick: () => run(r.whitelist_enabled ? "whitelist-off" : "whitelist-on", "") }, r.whitelist_enabled ? "Turn off" : "Turn on")),
          r.whitelist.length ? h("ul", { class: "list" }, r.whitelist.map((w) => h("li", {}, h("div", { class: "grow" }, w.name), btn("Remove", "whitelist-remove", w.name))))
            : h("p", { class: "empty" }, "Nobody whitelisted")),
        card("Banned",
          r.bans.length || r.ip_bans.length ? h("ul", { class: "list" },
            r.bans.map((b) => h("li", {}, h("div", { class: "grow" }, h("strong", {}, b.name),
              h("div", { class: "muted small" }, [b.reason, b.created && `since ${b.created}`].filter(Boolean).join(" · "))), btn("Pardon", "pardon", b.name))),
            r.ip_bans.map((b) => h("li", {}, h("div", { class: "grow" }, h("code", {}, b.ip),
              h("div", { class: "muted small" }, [b.reason, b.created && `since ${b.created}`].filter(Boolean).join(" · "))), btn("Pardon", "pardon-ip", b.ip))))
            : h("p", { class: "empty" }, "Nobody banned"))),
      h("div", { class: "mt" }, card("Players who have joined before", playerList(known, "Nobody else has joined yet"))),
    );
  };

  // Built once, outside the refreshed area, so typing isn't interrupted.
  const manage = card("Add or manage a player",
        h("div", { class: "row" }, name, reason),
        h("div", { class: "row mt-s" },
          ...[["Op", "op"], ["De-op", "deop"], ["Whitelist", "whitelist-add"], ["Un-whitelist", "whitelist-remove"], ["Kick", "kick"], ["Pardon", "pardon"]]
            .map(([label, action]) => h("button", { class: "btn", onclick: () => name.value.trim() && run(action, name.value.trim()) }, label)),
          h("button", { class: "btn danger", onclick: () => name.value.trim() && run("ban", name.value.trim()) }, "Ban"),
          h("button", { class: "btn danger", title: "Enter an IP address, or the name of an online player",
                        onclick: () => name.value.trim() && run("ban-ip", name.value.trim()) }, "Ban IP")));
  const requests = joinRequestsCard(() => load());
  const activity = activityCard();
  fill($("#main"), h("h2", { class: "view-title" }, "Players"), requests.el, manage, h("div", { class: "mt" }, body), h("div", { class: "mt" }, activity.el));
  load();
  every(5000, load);
  every(10000, requests.load);
  every(60000, activity.load);
  return {};
};

// Player activity (activity.py): who played and for how long, how busy each hour of the week is,
// and the quietest hour, which can become the nightly restart.
const weekdayName = (wd, style = "short") => new Date(2024, 0, 1 + wd).toLocaleDateString(LANG, { weekday: style });  // (1 January 2024 was a Monday)
const hourName = (hr) => new Date(2024, 0, 1, hr).toLocaleTimeString(LANG, { hour: "numeric", minute: "2-digit" });
function activityCard() {
  const body = h("div", {}, h("p", { class: "muted small" }, "Loading…"));
  const el = card("Player activity", body);
  let days = 30;
  const heatmap = (r) => {
    const top = Math.max(0.01, ...r.week.flat());
    const level = (v) => v <= 0 ? 0 : Math.min(4, 1 + Math.floor(3.999 * v / top));
    return h("div", { class: "heat-wrap" }, h("table", { class: "heat" },
      h("caption", { class: "sr-only" }, "Average players online, by day and hour"),
      h("thead", {}, h("tr", {}, h("td", {}), Array.from({ length: 24 }, (_, hr) =>
        h("th", { scope: "col", class: "small muted" }, hr % 3 === 0 ? String(hr) : h("span", { class: "sr-only" }, String(hr)))))),
      h("tbody", {}, r.week.map((row, wd) => h("tr", {}, h("th", { scope: "row", class: "small" }, weekdayName(wd)),
        row.map((v, hr) => {
          const words = `${weekdayName(wd, "long")} ${hourName(hr)}: ${v ? v.toFixed(1) : "0"} ${t("on average")}`;
          return h("td", { class: `heat-cell lvl${level(v)}`, title: words }, h("span", { class: "sr-only" }, words));
        }))))));
  };
  const load = async () => {
    const r = await api(`/api/players/activity?days=${days}`).catch(() => null);
    if (!r) { fill(body, h("p", { class: "muted small" }, "Couldn't load the player activity.")); return; }
    const periods = h("select", { class: "fit", "aria-label": "Period", onchange: (e) => { days = Number(e.target.value); load(); } },
      [[7, "Last 7 days"], [30, "Last 30 days"], [90, "Last 90 days"]].map(([v, l]) => h("option", { value: v }, l)));
    periods.value = String(days);
    if (!r.players.length) {
      fill(body, h("p", { class: "muted small" }, "Nobody has played since Craft Conductor started keeping track. Who plays when shows here, with the quietest time to restart the server."));
      return;
    }
    const q = r.quiet;
    const suggestion = !r.enough
      ? h("p", { class: "muted small" }, "After a few days of play, the quietest time to restart the server is suggested here.")
      : h("div", { class: "notice ok small row" },
        h("span", { class: "grow" }, t("Quietest time:") + " ", h("strong", {}, hourName(q.hour)),
          " ", q.average < 0.05 ? t("(nobody is usually on)") : `(${q.average.toFixed(1)} ${t("players on average")})`,
          r.busiest ? h("span", { class: "muted" }, " · " + t("busiest:") + ` ${weekdayName(r.busiest.weekday, "long")} ${hourName(r.busiest.hour)}`) : null,
          r.schedule_restart ? h("div", { class: "muted" }, t("Scheduled restart now:") + " " + t(r.schedule_restart_words || r.schedule_restart)) : null),
        r.schedule_restart === q.cron ? h("span", { class: "ok-text" }, "✓ The nightly restart is at this time")
          : hubInfo && hubInfo.device ? null
          : h("button", { class: "btn small", onclick: () => act(() => api("/api/settings", { method: "POST", body: { schedule_restart: q.cron } }),
            "The server restarts every day at the quietest time").then(load) }, "Restart every day at this time"));
    fill(body,
      h("div", { class: "row" }, h("p", { class: "muted small grow" }, "Who played, when, and how busy each hour of the week is (your computer's time)."), periods),
      suggestion,
      heatmap(r),
      h("div", { class: "row small muted heat-key", "aria-hidden": "true" }, t("Quiet"), [0, 1, 2, 3, 4].map((n) => h("span", { class: `heat-cell lvl${n}` })), t("Busy")),
      h("h4", { class: "mt" }, "Who played"),
      h("table", {},
        h("thead", {}, h("tr", {}, h("th", {}, "Player"), h("th", {}, "Time played"), h("th", {}, "Visits"), h("th", {}, "Last seen"))),
        h("tbody", {}, r.players.map((p) => h("tr", {},
          h("td", {}, p.name, p.online ? h("span", { class: "tag ok" }, "online") : null),
          h("td", {}, fmtDuration(p.seconds)), h("td", {}, String(p.visits)), h("td", {}, p.online ? t("now") : ago(p.last_seen)))))));
  };
  load();
  return { el, load };
}

// Friends asking to be let in (their Craft Conductor sends their Minecraft name with the invite).
function joinRequestsCard(after = () => {}) {
  const el = h("div");
  const load = async () => {
    const r = await api("/api/join-requests").catch(() => null);
    if (!r || !r.requests.length) { fill(el); return; }
    const answer = (name, allow) => act(() => api("/api/join-requests/answer", { method: "POST", body: { name, allow } }),
      allow ? `${name} can join now` : `Ignored ${name}`).then(() => { load(); after(); });
    fill(el, h("div", { class: "card mb" }, h("h3", {}, "Asking to join"),
      h("p", { class: "muted small" }, r.whitelist_on ? "These friends used your invite and asked to be let in. Allow adds them to the whitelist."
        : "These friends asked to be let in. The whitelist is off, so anyone can join anyway; Allow adds them for when it's on."),
      h("ul", { class: "list" }, r.requests.map((x) => h("li", {},
        h("strong", { class: "grow" }, x.name, h("span", { class: "muted small" }, ` · ${ago(x.time)}`)),
        h("button", { class: "btn small primary", onclick: () => answer(x.name, true) }, "Allow"),
        h("button", { class: "btn small ghost", onclick: () => answer(x.name, false) }, "Ignore"))))));
  };
  return { el, load };
}

views.mods = () => {
  const me = hubInfo && hubInfo.servers ? hubInfo.servers.find((x) => x.id === server) : null;
  const plugins = !!me && runsPlugins(me.loader);
  const results = h("div");
  const configured = h("div");
  const installed = h("div");
  const q = h("input", { placeholder: plugins ? "Search Modrinth for plugins…" : "Search Modrinth for server mods…", type: "search" });
  const sets = modSetsCard(() => load());
  let searchTimer;

  let early = false;
  const earlyBox = h("input", { type: "checkbox", onchange: (e) => { early = e.target.checked; search(); } });
  const earlyRow = h("label", { class: "row small early-opt", title: EARLY_WARNING }, earlyBox,
    h("span", {}, `Also show ${plugins ? "plugins" : "mods"} with only alpha/beta builds (less stable)`));
  const search = async () => {
    const term = q.value.trim();
    if (!term) { fill(results, ); return; }
    fill(results, h("p", { class: "empty" }, "Searching…"));
    const r = await api(`/api/mods/search?q=${encodeURIComponent(term)}` + (early ? "&early=1" : "")).catch((e) => { toast(e.message, true); return null; });
    if (!r) return;
    const note = r.hidden || r.early_hidden ? h("p", { class: "muted small" },
      r.hidden ? `${r.hidden} result(s) hidden: no build for this server's Minecraft ${info.minecraft || ""}. ` : "",
      r.early_hidden ? [`${r.early_hidden} only ${r.early_hidden === 1 ? "has" : "have"} alpha/beta builds. `,
        h("button", { class: "link-btn", onclick: () => { earlyBox.checked = early = true; search(); } }, "Show them")] : null) : null;
    fill(results, note, ...(r.results.length ? r.results.map((m) => h("div", { class: "mod" },
      m.icon ? h("img", { src: m.icon, alt: "", loading: "lazy", referrerpolicy: "no-referrer" }) : h("div", { class: "noicon" }),
      h("div", { class: "info" },
        h("div", { class: "name" }, m.name, h("span", { class: "tag" }, `${(m.downloads / 1e6).toFixed(1)}M downloads`),
          m.server_side === "optional" ? h("span", { class: "tag" }, "server optional") : null, channelTag(m.channel)),
        h("div", { class: "desc" }, m.description)),
      m.listed ? h("span", { class: "tag ok" }, "added") : h("div", { class: "row" },
        h("button", { class: "btn primary small", onclick: async () => (await confirmEarly([m])) && add(m.slug, true, "modrinth", m.channel) }, "Add"),
        h("button", { class: "btn small", title: "Won't hold back Minecraft upgrades", onclick: async () => (await confirmEarly([m])) && add(m.slug, false, "modrinth", m.channel) }, "Add optional")),
    )) : [h("p", { class: "empty" }, "No server mods found" + (info.minecraft ? ` that work on Minecraft ${info.minecraft}.` : "."))]));
  };
  const add = async (id, required, source = "modrinth", channel = null) => {
    const r = await act(() => api("/api/mods/add", { method: "POST", body: { source, id, required, channel: channel !== "release" ? channel : null } }));
    if (r) {
      toast(`Added ${r.name}` + (r.deps && r.deps.length ? `, with the mods it needs: ${r.deps.join(", ")}` : "") + ". Run an update check to install it.");
      load(); search();
    }
  };
  q.addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(search, 350); });

  const cfId = h("input", { placeholder: "CurseForge project id or slug" });
  let info = {};
  const configsCard = h("div");
  const load = async () => {
    const [r, cfg] = await Promise.all([api("/api/mods").catch(() => null), api("/api/configs").catch(() => null)]);
    if (!r) return;
    info = r;
    // Config files, matched to mods by the ids inside their jars.
    const groupByJar = new Map(((cfg && cfg.mods) || []).map((g) => [g.jar, g]));
    const groupFor = (key) => { const x = r.installed.find((m) => m.key === key); return x ? groupByJar.get(x.filename) : null; };
    const cfgBtn = (g) => g ? h("button", { class: "btn small", title: g.files.join("\n"), onclick: () => openConfigEditor(`${g.name} config`, g.files) },
      `⚙ Config${g.files.length > 1 ? ` (${g.files.length})` : ""}`) : null;
    fill(configsCard, cfg && (cfg.mods.length || cfg.other.length) ? card("Mod config files",
      h("p", { class: "muted small" }, "Change how mods behave. Most changes apply when the server restarts; the previous version of a file is kept each time you save."),
      h("ul", { class: "list" }, cfg.mods.map((g) => h("li", {},
        h("div", { class: "grow" }, h("strong", {}, g.name), h("div", { class: "small muted" }, g.files.join(", "))), cfgBtn(g))),
        cfg.other.length ? h("li", {}, h("div", { class: "grow" }, h("strong", {}, "Other config files"),
          h("div", { class: "small muted" }, `${cfg.other.length} file(s) not matched to an installed mod`)),
          h("button", { class: "btn small", onclick: () => openConfigEditor("Other config files", cfg.other) }, "⚙ Open")) : null))
      : null);
    // Each mod you added, with the mods installed because it needs them: they go together.
    const removeMods = async (specs, what) => {
      for (const x of specs) await api("/api/mods/remove", { method: "POST", body: { source: x.source, id: x.id } }).catch((e) => toast(e.message, true));
      toast(`Removed ${what}. ${specs.length === 1 ? "It's" : "They're"} uninstalled at the next update, with dependencies nothing else needs.`);
      load();
    };
    const needersOf = (depKey) => r.configured.filter((c) => c.deps.some((d) => d.key === depKey));
    fill(configured, r.configured.length ? h("ul", { class: "list" }, r.configured.flatMap((s) => [h("li", {},
      h("div", { class: "grow" }, h("strong", {}, s.name), h("span", { class: "tag" }, s.source), channelTag(s.channel)),
      h("label", { class: "row", title: "Every mod holds back Minecraft upgrades until it supports the new version. Required ones also decide the Minecraft version a new server starts on." },
        h("input", { type: "checkbox", checked: s.required, onchange: (e) => act(() => api("/api/mods/required", { method: "POST", body: { source: s.source, id: s.id, required: e.target.checked } })) }),
        "required"),
      cfgBtn(groupFor(s.key)),
      h("button", { class: "btn danger small", onclick: async () => {
        // Dependencies another mod also needs stay; say so before and after.
        const shared = s.deps.map((d) => [d, needersOf(d.key).filter((c) => c.key !== s.key)]).filter(([, others]) => others.length);
        const going = s.deps.filter((d) => !shared.some(([x]) => x.key === d.key));
        if (!(await ask(`Remove ${s.name}?` +
          (going.length ? ` The mods it needs (${going.map((d) => d.name).join(", ")}) go too.` : "") +
          (shared.length ? ` ${shared.map(([d]) => d.name).join(", ")} ${shared.length === 1 ? "stays" : "stay"}, because other mods need ${shared.length === 1 ? "it" : "them"}.` : "") +
          " It's uninstalled at the next update.", { ok: "Remove", danger: true }))) return;
        removeMods([s], s.name);
        for (const [d, others] of shared) toast(`${d.name} wasn't removed: ${others.map((c) => c.name).join(" and ")} ${others.length === 1 ? "needs" : "need"} it too.`);
      } }, "Remove")),
      ...s.deps.map((d) => h("li", { class: "dep" },
        h("div", { class: "grow" }, "↳ ", h("strong", {}, d.name), h("span", { class: "tag" }, `needed by ${needersOf(d.key).map((c) => c.name).join(", ")}`)),
        h("button", { class: "btn ghost small", onclick: async () => {
          const needers = needersOf(d.key);
          if (await ask(`${d.name} is needed by ${needers.map((c) => c.name).join(", ")}, so removing it removes ${needers.length === 1 ? "that mod" : "those mods"} too. Continue?`, { ok: "Remove", danger: true }))
            removeMods(needers, needers.map((c) => c.name).join(", "));
        } }, "Remove")))])) : h("p", { class: "empty" }, "No mods configured."));

    fill(installed, 
      r.installed.length ? h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Mod"), h("th", {}, "Version"), h("th", {}, "File"))),
        h("tbody", {}, r.installed.map((m) => h("tr", {},
          h("td", {}, m.name, m.dependency_of ? h("span", { class: "tag" }, `needed by ${(r.installed.find((x) => x.key === m.dependency_of) || {}).name || "another mod"}`) : null, m.manual ? h("span", { class: "tag warn" }, "manual") : null),
          h("td", {}, m.version), h("td", {}, h("code", {}, m.filename)))))) : h("p", { class: "empty" }, "Nothing installed yet."),
      (r.known_conflicts || []).length ? h("div", { class: "notice warn mt-s" }, h("strong", {}, "Other people found these don't work together: "),
        r.known_conflicts.map((x) => h("div", { class: "small" }, (x.with.length ? `${x.mod} + ${x.with.join(" + ")}` : `${x.mod} (on its own)`)
          + " · " + t("reported by {n} people").replace("{n}", x.reports))),
        h("div", { class: "small muted" }, "From Craft Conductor's shared list of mod conflicts. If the server starts fine, you can ignore this.")) : null,
      r.skipped.length ? h("div", { class: "notice warn mt-s" }, h("strong", {}, "Not installed: "),
        r.skipped.map((x) => h("div", { class: "small" }, `${x.key}: ${x.reason}`))) : null,
      r.unmanaged.length || (r.disabled || []).length ? h("div", { class: "mt-s" },
        h("h4", {}, runsPlugins(r.loader) ? "Plugins you added yourself" : "Jars you added yourself"),
        h("p", { class: "muted small" }, "Not updated by Craft Conductor. Switching one off keeps the file (as .jar.disabled) so you can switch it back on; changes apply at the next restart."),
        h("ul", { class: "list" },
          [...r.unmanaged.map((x) => [x, true]), ...(r.disabled || []).map((x) => [x, false])].map(([x, on]) => h("li", {},
            h("code", { class: "grow" }, x), on ? null : h("span", { class: "tag" }, "off"),
            h("button", { class: "btn small", onclick: () => act(() => api("/api/mods/jar", { method: "POST", body: { name: x, action: on ? "disable" : "enable" } })).then((res) => { if (res) { toast(res.message); load(); } }) }, on ? "Switch off" : "Switch on"),
            h("button", { class: "btn small ghost", onclick: async () => (await ask(`Remove ${x}? The file is deleted.`, { ok: "Remove", danger: true })) &&
              act(() => api("/api/mods/jar", { method: "POST", body: { name: x, action: "remove" } })).then((res) => { if (res) { toast(res.message); load(); } }) }, "Remove"))))) : null,
    );
  };

  const picker = h("input", { type: "file", multiple: true, accept: ".jar", class: "hidden" });
  picker.addEventListener("change", async () => {
    for (const f of [...picker.files]) {
      const r = await api(`/api/mods/local?filename=${encodeURIComponent(f.name)}`, { method: "POST", raw: f })
        .catch((e) => { toast(`${f.name}: ${e.message}`, true); return null; });
      if (r) toast(r.managed ? `${r.name}: found on Modrinth, so Craft Conductor will keep it up to date` : `${r.name} added as your own file (Craft Conductor won't update it)`);
    }
    picker.value = "";
    load();
  });
  const sources = h("div", { class: "source-buttons" },
    h("button", { type: "button", class: "btn", onclick: () => picker.click() }, "📁 Local files",
      h("span", { class: "small muted" }, ".jar files on this computer")),
    h("button", { type: "button", class: "btn", onclick: () => openBrowser({ type: "mod", target: server, loader: info.loader || "", version: info.minecraft || "" }) },
      plugins ? "🔎 Download plugins" : "🔎 Download mods", h("span", { class: "small muted" }, plugins ? "Browse Modrinth and Hangar" : "Browse Modrinth and CurseForge")),
    hubInfo && hubInfo.single ? null : h("button", { type: "button", class: "btn", onclick: () => openBrowser({ type: "modpack", target: "setup" }) },
      "📦 Modpacks", h("span", { class: "small muted" }, "Start a new server from a pack")),
    picker);

  fill($("#main"), 
    h("h2", { class: "view-title" }, plugins ? "Plugins" : "Mods"),
    card(plugins ? "Add plugins" : "Add mods", sources, h("h3", { class: "mt" }, "Quick add"), q, earlyRow, results,
      plugins ? h("p", { class: "muted small mt-s" }, "Paper and Purpur run Paper, Spigot and Bukkit plugins from their plugins folder. Players don't need them.")
        : h("div", { class: "row mt-s" }, cfId,
          h("button", { class: "btn", onclick: () => cfId.value.trim() && add(cfId.value.trim(), true, "curseforge") }, "Add from CurseForge"))),
    h("div", { class: "mt" }, configsCard),
    h("div", { class: "grid mt" }, card("Configured (craft-conductor.toml)", configured,
      h("div", { class: "row mt-s" }, testButton({
        check: ["/api/mods/check", {}],
        trial: { server },
        keepWorking: async (res) => {
          for (const o of res.outliers) await api("/api/mods/remove", { method: "POST", body: { source: o.source, id: o.id } }).catch((e) => toast(e.message, true));
          toast(`Removed ${res.outliers.map((o) => o.id).join(", ")}. They're uninstalled at the next update.`);
          load();
        },
      }))),
      card("Installed", hubInfo && hubInfo.local ? h("div", { class: "row mb" }, folderBtn("mods", "Mods folder"), folderBtn("config", "Config folder")) : null, installed)),
    h("div", { class: "mt" }, sets.el),
  );
  load();
  sets.load();
  return { onJobDone: () => { load(); sets.load(); }, refresh: load };
};

// Saved mod lists: keep the mods under a name, switch lists, and go back ("Before …" is saved
// by itself on every switch). Power users can download a list and load it on another server.
function modSetsCard(after) {
  const list = h("div");
  const name = h("input", { placeholder: "e.g. Survival with tech mods", maxlength: 60 });
  const file = h("input", { type: "file", accept: ".json,application/json", class: "hidden" });
  const load = async () => {
    const r = await api("/api/modsets").catch(() => null);
    if (!r) return;
    fill(list, r.sets.length ? h("ul", { class: "list" }, r.sets.map((x) => h("li", {},
      h("div", { class: "grow" }, h("strong", {}, x.name),
        h("div", { class: "muted small" }, `${x.mods.length} mod${x.mods.length === 1 ? "" : "s"}` + (x.minecraft ? ` · Minecraft ${x.minecraft}` : "") +
          (x.saved ? ` · saved ${ago(x.saved)}` : ""), x.mods.length ? h("span", { title: x.mods.join(", ") }, " ⓘ") : null)),
      h("button", { class: "btn small", onclick: async () => {
        if (!(await ask(`Switch to "${x.name}"?\n\nThe mods you have now are saved first as "Before ${x.name}", so you can switch back. The new list is installed with the next update.`, { ok: "Switch" }))) return;
        const res = await act(() => api("/api/modsets/restore", { method: "POST", body: { name: x.name } }));
        if (!res) return;
        toast(res.message);
        const mc = status && status.minecraft;
        if (mc && await ask(`Install the mods from "${x.name}" now?\n\nThe server updates its mods for Minecraft ${mc} and restarts (players get the countdown first).`, { ok: "Install now" }))
          await act(() => api("/api/updates/apply", { method: "POST", body: { target: mc } }), "Installing…");
        load(); after();
      } }, "Switch to it"),
      h("a", { class: "btn small ghost", href: scoped(`/api/modsets/export?name=${encodeURIComponent(x.name)}`), download: "", title: "Download as a file" }, "⬇"),
      h("button", { class: "btn small ghost", title: "Delete", onclick: async () => (await ask(`Delete the saved list "${x.name}"? The server's mods don't change.`, { ok: "Delete", danger: true })) &&
        act(() => api("/api/modsets/delete", { method: "POST", body: { name: x.name } }), "Deleted").then(load) }, "✕"))))
      : h("p", { class: "muted small" }, "No saved lists yet."));
  };
  file.addEventListener("change", async () => {
    const f = file.files[0];
    file.value = "";
    if (!f) return;
    let set;
    try { set = JSON.parse(await f.text()); } catch (_) { toast("That file isn't a mod list saved from Craft Conductor.", true); return; }
    const r = await act(() => api("/api/modsets/import", { method: "POST", body: { set } }));
    if (r) { toast(r.message); load(); }
  });
  const el = card("Saved mod lists",
    h("p", { class: "muted small" }, "Save the mods you have now under a name, switch to another list, and switch back. Switching saves the current mods first."),
    h("div", { class: "row" }, name, h("button", { class: "btn", onclick: async () => {
      if (!name.value.trim()) { toast("Give the list a name.", true); return; }
      const r = await act(() => api("/api/modsets/save", { method: "POST", body: { name: name.value.trim() } }));
      if (r) { toast(r.message); name.value = ""; load(); }
    } }, "Save the current mods")),
    list,
    h("div", { class: "row mt-s small" }, h("button", { class: "btn small ghost", onclick: () => file.click() }, "Load a list from a file…"), file));
  return { el, load };
}

// Put back one area of the world from a backup: griefing or a bad explosion undone, everything
// else kept as it is now. The corners are block coordinates (F3 in the game shows them).
function openAreaRestore(b) {
  if ($("#area-restore")) return;
  const num = (v) => h("input", { type: "number", value: v, class: "narrow" });
  const x1 = num(-50), z1 = num(-50), x2 = num(50), z2 = num(50);
  const dim = h("select", { "aria-label": "Dimension" }, [["overworld", "Overworld"], ["nether", "The Nether"], ["end", "The End"]]
    .map(([v, l]) => h("option", { value: v }, l)));
  const note = h("p", { class: "muted small" });
  const update = () => {
    const w = Math.abs(Math.floor(x2.value / 16) - Math.floor(x1.value / 16)) + 1, d = Math.abs(Math.floor(z2.value / 16) - Math.floor(z1.value / 16)) + 1;
    note.textContent = `${w * d} chunk(s): ${w * 16} × ${d * 16} blocks, rounded out to whole chunks.`;
  };
  [x1, z1, x2, z2].forEach((el) => el.addEventListener("input", update));
  update();
  const close = () => $("#area-restore").remove();
  const go = async () => {
    const body = { name: b.name, dimension: dim.value, x1: Number(x1.value), z1: Number(z1.value), x2: Number(x2.value), z2: Number(z2.value) };
    if (!(await ask(`Put this area back as it was in ${b.name}? Everything else in the world stays as it is now. ` +
      "Craft Conductor backs up the world first, so you can undo it.", { ok: "Put it back", danger: true }))) return;
    const r = await act(() => api("/api/backups/area", { method: "POST", body }), "Putting the area back…");
    if (r) close();
  };
  document.body.append(h("div", { class: "modal-backdrop", id: "area-restore", role: "dialog", "aria-modal": "true" },
    h("div", { class: "modal" },
      h("h2", {}, "Put back an area"),
      h("p", { class: "small" }, "From ", h("code", {}, b.name), ". Type two opposite corners (the x and z numbers F3 shows in the game)."),
      h("div", { class: "row" }, h("span", {}, "From x"), x1, h("span", {}, "z"), z1),
      h("div", { class: "row mt-s" }, h("span", {}, "To x"), x2, h("span", {}, "z"), z2),
      h("label", { class: "mt-s" }, "Dimension", dim),
      note,
      h("p", { class: "muted small" }, "Blocks, chests, animals and villagers in that area go back to how they were. Players' inventories don't change."),
      h("div", { class: "row mt" }, h("button", { class: "btn primary", onclick: go }, "Put it back"), h("button", { class: "btn ghost", onclick: close }, "Cancel")))));
}

views.backups = () => {
  const list = h("div");
  const label = h("input", { placeholder: "label (optional)" });
  const load = async () => {
    const r = await api("/api/backups").catch(() => null);
    if (!r) return;
    const stopped = status && status.state === "stopped";
    const checked = (c) => !c ? h("span", { class: "muted small" }, "not checked")
      : c.ok ? h("span", { class: "small ok-text", title: c.detail }, "✓ checked")
        : h("span", { class: "small bad-text", title: c.detail }, `✗ ${c.detail}`);
    const rollBack = async (b) => {
      const c = await api(`/api/backups/changes?name=${encodeURIComponent(b.name)}`).catch(() => null);
      const undo = c && c.undo;
      const msg = !c || !c.snapshot
        ? `Replace the server's files with ${b.name}? Anything since then is lost. (An older backup: afterwards, run an update check to put the mod list right.)`
        : undo.length ? `Roll the whole server back to ${fmtTime(b.time)}? This undoes:\n\n${undo.slice(0, 12).map((x) => "• " + x).join("\n")}${undo.length > 12 ? `\n• …and ${undo.length - 12} more` : ""}\n\nWorld changes since then are lost too.`
          : `Roll the whole server back to ${fmtTime(b.time)}? Nothing but the world has changed since then; world changes since then are lost.`;
      if (await ask(msg, { ok: c && c.snapshot ? "Roll back" : "Restore", danger: true }))
        act(() => api("/api/backups/restore", { method: "POST", body: { name: b.name } }), "Rolling back…");
    };
    const changed = (b) => b.changes === null || b.changes === undefined ? null
      : b.changes.length ? h("details", { class: "small" }, h("summary", {}, `${b.changes.length} change(s) since the one before`),
        h("ul", { class: "list snapshot-changes" }, b.changes.map((line) => h("li", { class: line.startsWith("+") ? "change-add" : line.startsWith("−") ? "change-rm" : "" }, line))))
        : h("span", { class: "muted small" }, "Only the world changed since the one before");
    fill(list, r.backups.length ? h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "Backup"), h("th", {}, "Created"), h("th", {}, "Size"), h("th", {}, "Can be restored"), h("th", {}))),
      h("tbody", {}, r.backups.map((b) => h("tr", {},
        h("td", {}, h("code", {}, b.name), b.snapshot ? h("div", { class: "small muted" }, `Minecraft ${b.minecraft || "—"} · ${b.mods} mod(s)`) : null, changed(b)),
        h("td", {}, fmtTime(b.time)), h("td", {}, fmtBytes(b.size)),
        h("td", {}, checked(b.check), " ", h("button", { class: "link-btn small", title: "Read the whole backup to make sure it can be restored",
          onclick: () => act(() => api("/api/backups/check", { method: "POST", body: { name: b.name } }), "Checking the backup…") }, b.check ? "Check again" : "Check")),
        h("td", { class: "row" }, h("button", {
          class: "btn small", disabled: !stopped, title: stopped ? "" : "Stop the server first",
          onclick: () => rollBack(b),
        }, b.snapshot ? "Roll back to this" : "Restore"),
        h("button", { class: "btn small", disabled: !stopped, title: stopped ? "Put back only part of the world" : "Stop the server first",
          onclick: () => openAreaRestore(b) }, "Put back an area…")))))) : h("p", { class: "empty" }, "No backups yet."));
  };
  fill($("#main"), 
    h("h2", { class: "view-title" }, "Backups"),
    card("Create backup", h("p", { class: "muted" }, "Each backup is a snapshot of the whole server: the world, the mods, their settings and Craft Conductor's settings for it. One is also made automatically before every update."),
      h("div", { class: "row" }, label, h("button", { class: "btn primary", onclick: () => act(() => api("/api/backups/create", { method: "POST", body: { label: label.value } }), "Backing up…") }, "Back up now"))),
    card("Backups", h("div", { class: "row" }, h("p", { class: "muted small grow" }, "Restoring needs the server to be stopped."), folderBtn("backups", "Backups folder")), list),
  );
  load();
  return { onJobDone: load, onStatus: load };
};

views.java = () => {
  const body = h("div");
  const load = async () => {
    const r = await api("/api/java").catch(() => null);
    if (!r) return;
    const use = h("select", {}, h("option", { value: "auto" }, "auto (what Minecraft needs)"),
      [8, 11, 16, 17, 21, 25].map((v) => h("option", { value: String(v) }, `Java ${v}`)));
    use.value = r.forced ? String(r.forced) : "auto";
    const major = h("input", { type: "number", min: 8, max: 99, value: r.required || 21, class: "narrow" });
    fill(body, 
      h("div", { class: "grid" },
        card("Server runtime", h("dl", { class: "kv" },
          h("dt", {}, "Needs"), h("dd", {}, r.required ? `Java ${r.required}` : "—"),
          h("dt", {}, "Using"), h("dd", {}, r.current ? h("code", {}, r.current) : "—"),
          h("dt", {}, "Auto-install"), h("dd", {}, r.auto_install ? "on" : "off")),
          h("label", { class: "mt-s" }, "Run the server on",
            h("div", { class: "row" }, use, h("button", { class: "btn primary", onclick: () => act(() => api("/api/java/use", { method: "POST", body: { version: use.value } }), "Saved. Applies at the next start.").then(load) }, "Save")))),
        card("Download Temurin", h("p", { class: "muted" }, "Downloads Eclipse Temurin into .craft-conductor/java/. ", folderBtn("java", "Open it")),
          h("div", { class: "row" }, major, h("button", { class: "btn", onclick: () => act(() => api("/api/java/install", { method: "POST", body: { major: Number(major.value) } }), "Downloading…") }, "Install"))),
      ),
      card("Available runtimes", h("table", {},
        h("thead", {}, h("tr", {}, h("th", {}, "Java"), h("th", {}, "Source"), h("th", {}, "Path"))),
        h("tbody", {},
          r.managed.map((j) => h("tr", {}, h("td", {}, String(j.major)), h("td", {}, "managed ", h("span", { class: "tag" }, j.release)), h("td", {}, h("code", {}, j.path)))),
          r.configured.map((j) => h("tr", {}, h("td", {}, String(j.major)), h("td", {}, "[java.versions]"), h("td", {}, h("code", {}, j.path)))),
          h("tr", {}, h("td", {}, "?"), h("td", {}, "default"), h("td", {}, h("code", {}, r.default)))))),
    );
  };
  fill($("#main"), h("h2", { class: "view-title" }, "Java"), body);
  load();
  return { onJobDone: load };
};

// A schedule as simple choices (off, every day at…, every week on…, every few hours), stored as a
// cron expression; "Custom" shows the expression itself, for anything else.
function schedulePicker(label, expr, kind, next) {
  expr = (expr || "").trim().replace(/\s+/g, " ");
  let mode = "off", time = kind === "restart" ? "04:00" : "03:00", day = "0", hours = "6", custom = expr;
  let m;
  const hm = (mi, hr) => `${String(hr).padStart(2, "0")}:${String(mi).padStart(2, "0")}`;
  if (!expr) mode = "off";
  else if ((m = /^(\d+) (\d+) \* \* \*$/.exec(expr))) { mode = "daily"; time = hm(m[1], m[2]); }
  else if ((m = /^(\d+) (\d+) \* \* ([0-7])$/.exec(expr))) { mode = "weekly"; time = hm(m[1], m[2]); day = String(Number(m[3]) % 7); }
  else if ((m = /^0 \*\/(\d+) \* \* \*$/.exec(expr)) && ["2", "3", "6", "12"].includes(m[1])) { mode = "hours"; hours = m[1]; }
  else if (expr === "0 * * * *") { mode = "hours"; hours = "1"; }
  else mode = "custom";
  const modeSel = h("select", {}, [["off", "Off"], ["daily", "Every day at…"], ["weekly", "Every week on…"],
    ...(kind === "backup" ? [["hours", "Every few hours"]] : []), ["custom", "Custom (cron)"]].map(([v, t]) => h("option", { value: v }, t)));
  modeSel.value = mode;
  const timeIn = h("input", { type: "time", value: time, "aria-label": `${label}: time` });
  const daySel = h("select", { "aria-label": `${label}: day` }, ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    .map((d, i) => h("option", { value: String(i) }, d)));
  daySel.value = day;
  const hoursSel = h("select", { "aria-label": `${label}: how often` }, ["1", "2", "3", "6", "12"].map((n) => h("option", { value: n }, n === "1" ? "every hour" : `every ${n} hours`)));
  hoursSel.value = hours;
  const cronIn = h("input", { value: custom, placeholder: "minute hour day month weekday, e.g. 30 5 * * 1-5", class: "mono", "aria-label": `${label}: cron expression` });
  const hint = h("span", { class: "muted small" });
  const extra = h("div", { class: "row" });
  const value = () => {
    const [hr, mi] = (timeIn.value || "04:00").split(":").map(Number);
    switch (modeSel.value) {
      case "daily": return `${mi} ${hr} * * *`;
      case "weekly": return `${mi} ${hr} * * ${daySel.value}`;
      case "hours": return hoursSel.value === "1" ? "0 * * * *" : `0 */${hoursSel.value} * * *`;
      case "custom": return cronIn.value.trim();
      default: return "";
    }
  };
  const render = () => {
    const mo = modeSel.value;
    fill(extra, mo === "weekly" ? daySel : null, mo === "daily" || mo === "weekly" ? timeIn : null, mo === "hours" ? hoursSel : null, mo === "custom" ? cronIn : null);
    hint.textContent = mo === "custom" ? "Five parts: minute, hour, day of the month, month, day of the week (0 or 7 is Sunday). * means every; */6 every 6th; 1-5 a range."
      : mo === "off" ? "" : value() === expr && next ? `Next: ${fmtTime(next)}` : "";
  };
  for (const el of [modeSel, timeIn, daySel, hoursSel, cronIn]) el.addEventListener("input", render);
  modeSel.addEventListener("change", render);
  render();
  return { el: h("label", {}, label, modeSel, extra, hint), value };
}

// World tools: game rules with what they do, the world border, and pre-generating terrain
// with Chunky. They use the running server's own commands.
function worldTools() {
  const body = h("div", {}, h("p", { class: "muted small" }, "Loading…"));
  const el = h("div", { class: "card mt" }, h("h3", {}, "World tools"), body);
  let poll = null;
  const addChunky = async () => {
    const r = await act(() => api("/api/mods/add", { method: "POST", body: { source: "modrinth", id: "chunky", required: false } }));
    if (!r) return;
    const st = status || {};
    if (st.minecraft && await ask(`Chunky is added. Install it now?\n\nThe server updates its mods for Minecraft ${st.minecraft} and restarts (players get the countdown first).`, { ok: "Install now" }))
      await act(() => api("/api/updates/apply", { method: "POST", body: { target: st.minecraft } }), "Installing Chunky…");
    else toast("Chunky is added: it's installed with the next update.");
  };
  const load = async () => {
    const r = await api("/api/world/tools").catch(() => null);
    if (!r) return;
    clearTimeout(poll);
    if (!r.running) { fill(body, h("p", { class: "muted small" }, "Start the server to change game rules, the world border or pre-generate terrain: they use the server's own commands.")); return; }
    const rule = (x) => {
      const input = x.kind === "bool" ? h("input", { type: "checkbox", checked: x.value === "true" }) : h("input", { type: "number", value: x.value, class: "narrow" });
      input.addEventListener("change", () => act(() => api("/api/world/rule", { method: "POST", body: { rule: x.id, value: x.kind === "bool" ? String(input.checked) : input.value } }), `${x.id} changed`));
      return h("label", { class: "row rule" }, input, h("span", { class: "grow" }, h("code", {}, x.id), " ", h("span", { class: "muted small" }, x.words)));
    };
    const otherName = h("input", { placeholder: "any game rule", class: "mono" }), otherValue = h("input", { placeholder: "true, false or a number", class: "mono" });
    const size = h("input", { type: "number", min: 16, placeholder: "e.g. 10000", value: r.border && r.border < 59999968 ? Math.round(r.border) : "" });
    const bx = h("input", { type: "number", value: 0, class: "narrow", "aria-label": "Centre X" }), bz = h("input", { type: "number", value: 0, class: "narrow", "aria-label": "Centre Z" });
    const radius = h("select", {}, [["1000", "1,000 blocks (quick)"], ["2500", "2,500 blocks"], ["5000", "5,000 blocks (hours)"], ["10000", "10,000 blocks (a long while)"]].map(([v, t]) => h("option", { value: v }, t)));
    const pg = r.progress;
    const chunkyAct = (action, extra = {}) => act(() => api("/api/world/chunky", { method: "POST", body: { action, ...extra } }), null).then((x) => { if (x) toast(x.message); setTimeout(load, 1500); });
    fill(body,
      h("h4", {}, "Game rules"),
      r.rules.length ? h("div", { class: "rules" }, r.rules.map(rule)) : h("p", { class: "muted small" }, "The server didn't say its game rules (it may still be starting)."),
      h("details", { class: "small mt-s" }, h("summary", {}, "Another game rule (power users)"),
        h("div", { class: "row mt-s" }, otherName, otherValue, h("button", { class: "btn small", onclick: () => otherName.value.trim() &&
          act(() => api("/api/world/rule", { method: "POST", body: { rule: otherName.value.trim(), value: otherValue.value.trim().toLowerCase() } }), "Game rule changed") }, "Set"))),
      h("h4", { class: "mt" }, "World border"),
      h("p", { class: "muted small" }, r.border && r.border < 59999968 ? `The world is ${Math.round(r.border).toLocaleString()} blocks wide.` : "No border: the world goes on (almost) for ever.",
        " A border keeps the world a size this computer can handle and players can find each other in."),
      h("div", { class: "row" }, h("label", {}, "Width (blocks)", size), h("label", {}, "Centre X", bx), h("label", {}, "Centre Z", bz),
        h("button", { class: "btn", onclick: () => size.value && act(() => api("/api/world/border", { method: "POST", body: { diameter: Number(size.value), x: Number(bx.value), z: Number(bz.value) } }), "World border set").then(load) }, "Set border")),
      h("h4", { class: "mt" }, "Pre-generate terrain"),
      h("p", { class: "muted small" }, "Making new terrain is the heaviest thing a server does. Generating it ahead of time, while nobody's playing, means no lag spikes when people explore."),
      r.chunky ? [
        pg ? h("div", { class: "mt-s" }, h("div", { class: "bar" }, h("span", { class: "bar-fill", "data-pct": String(pg.percent || 0) })),
          h("div", { class: "muted small" }, pg.running ? `${(pg.percent || 0).toFixed(1)}% done` : "Finished (or stopped).")) : null,
        h("div", { class: "row mt-s" }, radius, h("button", { class: "btn primary", onclick: () => chunkyAct("start", { radius: Number(radius.value), x: Number(bx.value), z: Number(bz.value) }) }, "Start"),
          h("button", { class: "btn small", onclick: () => chunkyAct("pause") }, "Pause"), h("button", { class: "btn small", onclick: () => chunkyAct("continue") }, "Continue"),
          h("button", { class: "btn small ghost", onclick: () => chunkyAct("cancel") }, "Cancel"))]
        : h("div", { class: "row" }, h("button", { class: "btn", onclick: addChunky }, "Add Chunky"), h("span", { class: "muted small" }, "A free mod (from Modrinth) that pre-generates the world.")));
    body.querySelectorAll(".bar-fill[data-pct]").forEach((b) => { b.style.width = `${b.dataset.pct}%`; });
    if (pg && pg.running) poll = setTimeout(load, 10000);
  };
  return { el, load };
}

// The web map (webmap.py): BlueMap (3D) or Dynmap, a live map of the world in a browser tab.
function webMapCard() {
  const body = h("div", {}, h("p", { class: "muted small" }, "Loading…"));
  const el = h("div", { class: "card mt" }, h("h3", {}, "Web map"), body);
  const add = async (kind, name) => {
    const r = await act(() => api("/api/webmap/add", { method: "POST", body: { kind } }));
    if (!r) return;
    const st = status || {};
    if (st.minecraft && await ask(`${name} is added. Install it now?\n\nThe server updates its mods for Minecraft ${st.minecraft} and restarts (players get the countdown first).`, { ok: "Install now" }))
      await act(() => api("/api/updates/apply", { method: "POST", body: { target: st.minecraft } }), `Installing ${name}…`);
    else toast(`${name} is added: it's installed with the next update.`);
    load();
  };
  const load = async () => {
    const r = await api("/api/webmap").catch(() => null);
    if (!r) return;
    if (!r.kind) {
      fill(body,
        h("p", { class: "muted small" }, "A live map of the world that you and your friends open in a browser: see the terrain, builds and who is where."),
        r.listed ? h("p", { class: "small" }, `${r.maps[r.listed]} is added and is installed with the next update.`)
          : h("div", { class: "row" },
            h("button", { class: "btn", onclick: () => add("bluemap", "BlueMap") }, "Add BlueMap"),
            h("span", { class: "muted small grow" }, "3D, looks like the game. Needs more disk space and a while to draw the first time."),
            h("button", { class: "btn", onclick: () => add("dynmap", "Dynmap") }, "Add Dynmap"),
            h("span", { class: "muted small grow" }, "Flat, like a road map. Lighter.")));
      return;
    }
    const portIn = h("input", { type: "number", min: 1024, max: 65535, value: r.port, class: "narrow", "aria-label": "Map port" });
    fill(body,
      r.accepted === false ? h("div", { class: "notice warn small" },
        h("p", {}, "BlueMap draws the map with Minecraft's own textures, which it downloads from Mojang. It waits for your OK."),
        h("button", { class: "btn small primary", onclick: () => act(() => api("/api/webmap/accept", { method: "POST", body: {} }), "BlueMap starts drawing the map").then(load) }, "OK, download them")) : null,
      !r.configured ? h("p", { class: "muted small" }, `${r.name} sets itself up the first time the server starts with it.`)
        : r.answers ? h("div", { class: "row" }, h("span", { class: "ok-text small grow" }, `✓ ${r.name} is running.`),
          h("a", { class: "btn small primary", href: hubInfo && hubInfo.local ? r.local_url : r.lan_url || r.local_url, target: "_blank", rel: "noopener noreferrer" }, "Open the map ↗"))
          : h("p", { class: "muted small" }, r.running ? `${r.name} isn't answering on port ${r.port} yet (it can take a minute after the server starts).` : "Start the server to see the map."),
      r.lan_url ? h("p", { class: "small" }, "On your network: ", h("code", {}, r.lan_url)) : null,
      h("p", { class: "muted small" }, "Friends outside your home need the map's port forwarded on the router, like the game's. Anyone with the address can see the map."),
      r.configured ? h("div", { class: "row" }, h("label", {}, "Port", portIn),
        h("button", { class: "btn small", onclick: () => act(() => api("/api/webmap/port", { method: "POST", body: { port: Number(portIn.value) } })).then((x) => { if (x) toast(x.message); load(); }) }, "Change port")) : null,
      h("p", { class: "muted small" }, `Remove ${r.name} on the Mods page to stop it.`));
  };
  return { el, load };
}

views.settings = () => {
  const form = h("form", { class: "card" });
  let edited = false;  // changes not saved yet
  form.addEventListener("input", () => { edited = true; });
  form.addEventListener("change", () => { edited = true; });
  guardLeave(form, () => edited);
  const load = async () => {
    const s = await api("/api/settings").catch(() => null);
    if (!s) return;
    const f = {};
    const sel = (k, opts, labels = {}) => (f[k] = h("select", {}, opts.map((o) => h("option", { value: o }, labels[o] || o))), f[k].value = s[k], f[k]);
    const txt = (k, extra = {}) => (f[k] = h("input", { value: s[k], ...extra }));
    const chk = (k, text) => h("label", { class: "row" }, (f[k] = h("input", { type: "checkbox", checked: s[k] })), h("span", {}, text));
    const sched = {};
    const advanced = { ...s.properties };
    const advancedEl = h("details", { class: "advanced mt-l" },
      h("summary", {}, "Advanced server settings"),
      h("p", { class: "muted small" }, "The rest of Minecraft's server.properties. These apply at the next restart."),
      propsEditor(s.properties_schema, advanced));
    fill(form,
      h("h3", {}, "Updates"),
      h("div", { class: "grid" },
        h("label", {}, "Minecraft version", sel("strategy", s.choices.strategy, {
          "latest-compatible": "Newest version your mods support (recommended)",
          "latest": "Only the newest version (waits until every mod supports it)",
          "mods-only": "Stay on this version (mods still update)" })),
        h("label", {}, "Mod builds to use", sel("mod_channel", s.choices.mod_channel, {
          release: "Releases only", beta: "Releases and betas", alpha: "Releases, betas and alphas (least stable)" })),
        h("label", {}, "Check every (e.g. 6h, 30m)", txt("check_interval")),
        h("label", {}, "In-game warnings (minutes, comma separated)", txt("warn_minutes", { value: s.warn_minutes.join(", ") }))),
      h("div", { class: "grid mt-s" },
        chk("auto_upgrade", "Apply updates automatically (a new Minecraft only once every mod supports it)"),
        chk("wait_for_empty", "Wait until nobody is online"),
        chk("verify_boot", "Test-boot and roll back on failure"),
        chk("rehearse", "Before a new Minecraft goes in by itself, try it on a copy of the server first")),
      h("div", { class: "grid mt-s" }, chk("find_lag", "When it keeps lagging with players on, find out why by itself (and tell me)")),
      h("h3", { class: "mt-l" }, "Server"),
      h("div", { class: "grid" },
        h("label", {}, "Memory (e.g. 6G)", txt("memory")),
        h("label", {}, "Port players connect to", txt("port", { type: "number", min: 1024, max: 65535 })),
        h("label", {}, "Backups to keep", txt("backups_keep", { type: "number", min: 1 })),
        h("label", {}, "Discord webhook URL", txt("discord_webhook", { type: "url", placeholder: "https://discord.com/api/webhooks/…" }))),
      h("div", { class: "grid mt-s" }, chk("restart_on_crash", "Restart after crashes"),
        h("label", { class: "row", title: "Garbage-collection settings that avoid lag spikes with lots of memory" },
          (f.aikar_flags = h("input", { type: "checkbox", checked: s.aikar_flags })), h("span", {}, "Use Aikar's flags (smoother with 16 GB+)"))),
      // Limits (limits.py): CPU cores where the computer allows it, and a lower priority everywhere.
      h("div", { class: "grid mt-s" },
        s.can_pin_cores ? h("label", {}, "CPU cores it may use",
          (f.cpu_cores = h("select", {}, h("option", { value: "0" }, t("All ({n})").replace("{n}", s.cpu_count)),
            Array.from({ length: Math.max(0, s.cpu_count - 1) }, (_, i) => h("option", { value: String(i + 1), selected: s.cpu_cores === i + 1 }, String(i + 1))))),
          h("span", { class: "muted small" }, "Leaves the other cores to the rest of this computer (and other servers). Applies at the next start.")) : null,
        h("label", { class: "row", title: "Other programs on this computer, and other servers, come first when the CPU is busy" },
          (f.priority = h("input", { type: "checkbox", checked: s.priority === "low" })), h("span", {}, "Lower priority (the rest of this computer comes first)"))),
      h("h3", { class: "mt-l" }, "Schedule"),
      h("p", { class: "muted small" }, "Times are this computer's. A scheduled restart gives players the in-game countdown first."),
      h("div", { class: "grid" },
        (sched.restart = schedulePicker("Restart the server", s.schedule_restart, "restart", s.schedule_restart_next)).el,
        (sched.backup = schedulePicker("Make a backup", s.schedule_backup, "backup", s.schedule_backup_next)).el),
      chk("restart_when_empty", "Skip a scheduled restart while players are online"),
      h("h3", { class: "mt-l" }, "playit.gg tunnel"),
      h("div", { class: "grid" },
        h("label", {}, "This server's playit.gg address (a Minecraft Java tunnel)", txt("tunnel_address", { placeholder: "e.g. name.gl.joinmc.link (optional)", class: "mono" }),
          h("span", { class: "muted small" }, "For friends outside your home when you can't forward ports: their game joins through this address. Leave empty to use your own address."))),
      playitNote(),
      h("h3", { class: "mt-l" }, "Backup copies"),
      h("div", { class: "grid" },
        h("label", {}, "Also copy every backup to", txt("backup_copy_to", { placeholder: "e.g. E:\\craft-conductor-backups, or a OneDrive / Google Drive folder" }),
          h("span", { class: s.backup_copy_ok ? "muted small" : "small bad-text" }, s.backup_copy_ok
            ? "A USB drive or a folder that syncs to the cloud, so a broken disk doesn't take the backups with it. Empty: no copies."
            : "That folder isn't there right now (is the drive plugged in?). Copies are skipped until it is.")),
        h("label", { class: "self-start" }, "Copies to keep there", txt("backup_copy_keep", { type: "number", min: 1 }))),
      advancedEl,
      h("div", { class: "row mt" }, h("button", { class: "btn primary", type: "submit" }, "Save settings"),
        h("span", { class: "muted small" }, "Memory, port and advanced changes apply at the next restart.")),
    );
    form.onsubmit = (e) => {
      e.preventDefault();
      const body = {
        strategy: f.strategy.value, mod_channel: f.mod_channel.value, check_interval: f.check_interval.value.trim(),
        warn_minutes: f.warn_minutes.value.split(",").map((x) => x.trim()).filter(Boolean).map(Number),
        auto_upgrade: f.auto_upgrade.checked, wait_for_empty: f.wait_for_empty.checked, verify_boot: f.verify_boot.checked,
        rehearse: f.rehearse.checked, find_lag: f.find_lag.checked, memory: f.memory.value.trim(),
        priority: f.priority.checked ? "low" : "normal", ...(f.cpu_cores ? { cpu_cores: Number(f.cpu_cores.value) } : {}), backups_keep: Number(f.backups_keep.value), discord_webhook: f.discord_webhook.value.trim(),
        port: Number(f.port.value),
        restart_on_crash: f.restart_on_crash.checked, aikar_flags: f.aikar_flags.checked,
        schedule_restart: sched.restart.value(), schedule_backup: sched.backup.value(),
        restart_when_empty: f.restart_when_empty.checked,
        backup_copy_to: f.backup_copy_to.value.trim(), backup_copy_keep: Number(f.backup_copy_keep.value) || 10,
        tunnel_address: f.tunnel_address.value.trim(),
        properties: changedProps(advanced, s.properties),
      };
      const gb = memoryGb(body.memory);
      if (gb > AIKAR_ABOVE_GB && !body.aikar_flags) {
        offerAikar(gb, () => { f.aikar_flags.checked = true; act(() => api("/api/settings", { method: "POST", body: { aikar_flags: true } }), "Aikar's flags on").then(load); });
      }
      act(() => api("/api/settings", { method: "POST", body }), "Settings saved").then((r) => { if (r) edited = false; load(); });
    };
  };
  const danger = h("div", { class: "card danger-zone mt" });
  const renderDanger = () => {
    const me = hubInfo && hubInfo.servers ? hubInfo.servers.find((x) => x.id === server) : null;
    if (!me || hubInfo.single) { fill(danger); danger.classList.add("hidden"); return; }
    danger.classList.remove("hidden");
    fill(danger, h("h3", {}, "Delete this server"),
      h("div", { class: "row" },
        h("span", { class: "grow muted" }, "Take it off your list, and choose whether to also erase its world, mods and backups."),
        h("button", { class: "btn danger", onclick: () => deleteServer(me, () => { location.hash = "#servers"; }) }, "Delete server…")));
  };
  // Move to another computer: export everything to one file, import it there.
  const exportCard = h("div", { class: "card mt" });
  const withBackups = h("input", { type: "checkbox" });
  const loadExports = async () => {
    const r = await api("/api/export").catch(() => null);
    if (!r) return;
    fill(exportCard, h("h3", {}, "Move to another computer"),
      h("p", { class: "muted small" }, "Export saves this server (worlds, mods, configs, settings, player lists) in one .zip. " +
        "On the other computer, install Craft Conductor, then choose Import a server on the server list. The world is saved first, " +
        "so this works while the server runs."),
      h("div", { class: "row" },
        h("button", { class: "btn primary", disabled: !!(status && status.job), onclick: () => act(() => api("/api/export", { method: "POST", body: { backups: withBackups.checked } }), "Exporting…") }, "Export server"),
        h("label", { class: "row" }, withBackups, h("span", {}, "Include backups (bigger file)"))),
      r.exports.length ? h("table", { class: "mt-s" },
        h("thead", {}, h("tr", {}, h("th", {}, "Export"), h("th", {}, "Made"), h("th", {}, "Size"), h("th", {}))),
        h("tbody", {}, r.exports.map((x) => h("tr", {},
          h("td", {}, h("code", {}, x.name)), h("td", {}, fmtTime(x.created)), h("td", {}, fmtBytes(x.size)),
          h("td", { class: "row" },
            h("a", { class: "btn small", href: scoped(`/api/export/download?name=${encodeURIComponent(x.name)}`), download: x.name }, "Download"),
            h("button", { class: "btn small danger", onclick: async () => (await ask(`Delete ${x.name}?`, { ok: "Delete", danger: true })) && act(() => api("/api/export/delete", { method: "POST", body: { name: x.name } }), "Deleted").then(loadExports) }, "Delete"))))))
        : null,
      h("div", { class: "row mt-s" }, h("p", { class: "muted small grow" }, "Exports are kept in ", h("code", {}, r.folder)),
        folderBtn("exports", "Exports folder"), folderBtn("server", "Server folder")));
  };
  const worldCard = card("World",
    h("p", { class: "muted small" }, "Put a different world on this server: a singleplayer world or a world .zip. " +
      "The current world is backed up first (see Backups), so you can go back."),
    h("div", { class: "row" },
      h("button", { class: "btn", onclick: () => pickWorld(async (w) => {
        if (!(await ask(`Replace this server's world with ${w.name}? The current world is backed up first.`, { ok: "Replace", danger: true }))) return;
        await act(() => api("/api/world/replace", { method: "POST", body: { world: w.world } }), "Replacing the world…");
      }) }, "Replace the world…"),
      folderBtn("world", "World folder")));
  worldCard.classList.add("mt");
  const tools = worldTools();
  const map = webMapCard();
  fill($("#main"), h("h2", { class: "view-title" }, "Server settings"), form, worldCard, tools.el, map.el, exportCard, danger);
  tools.load();
  map.load();
  load();
  loadExports();
  renderDanger();
  return { onStatus: renderDanger, onJobDone: loadExports };
};

// ------------------------------------------------------------------ friends
// A download friends run to set up their Minecraft for this server (mods and all).
// Bedrock players (phones, tablets, Windows, consoles) join a Java server through Geyser, with
// Floodgate so they don't need a Java account. Both are mods (or plugins on Paper) from Modrinth.
function bedrockCard() {
  const box = h("div");
  const load = async () => {
    const r = await api("/api/bedrock").catch(() => null);
    if (!r) return;
    if (!r.supported) {
      fill(box, card("Bedrock players (phones, tablets, consoles)",
        h("p", { class: "muted small" }, "Players on Minecraft Bedrock can join through Geyser, which runs on Fabric, Quilt, NeoForge, Paper and Purpur servers. This server's type doesn't support it.")));
      return;
    }
    const turnOn = h("button", { class: "btn primary", onclick: async () => {
      turnOn.disabled = true;
      try {
        const check = await api("/api/bedrock/check");
        const missing = check.mods.filter((m) => !r[m.id]);
        if (!(await confirmEarly(missing))) { turnOn.disabled = false; return; }
        for (const mod of missing) {
          await api("/api/mods/add", { method: "POST", body: { ...mod, required: true } });
        }
        if (await ask(`Geyser and Floodgate are added. Install them now?\n\nThe server updates its mods for Minecraft ${r.minecraft} and restarts (players get the countdown first). Otherwise they're installed with the next update.`, { ok: "Install now" })) {
          await act(() => api("/api/updates/apply", { method: "POST", body: { target: r.minecraft } }), "Installing Geyser and Floodgate…");
        } else toast("Added: they're installed with the next update.");
      } catch (e) { if (!(e instanceof Unauthorized)) toast(e.message, true); }
      turnOn.disabled = false;
      load();
    } }, "Let Bedrock players join");
    const on = r.geyser && r.floodgate;
    fill(box, card("Bedrock players (phones, tablets, consoles)",
      h("p", { class: "muted small" }, "Friends playing Minecraft on a phone, tablet, Windows (the Microsoft Store version) or a console can join too, through ",
        h("a", { href: "https://geysermc.org", target: "_blank", rel: "noopener noreferrer" }, "Geyser ↗"),
        ". They sign in with their own Microsoft account; they don't need Java Edition."),
      on ? [
        h("div", { class: `notice ${r.installed ? "ok" : "warn"} mt-s` }, r.installed ? "Bedrock players can join." : "Added: installed with the next update (Updates page)."),
        h("ul", { class: "small mt-s" },
          h("li", {}, "In Bedrock: Play → Servers → Add Server, with the same address as your Java friends use, and port ", h("strong", {}, String(r.port)), "."),
          h("li", {}, "Friends outside your home: also forward ", h("strong", {}, `UDP port ${r.port}`), " on your router (Bedrock uses UDP, not TCP; see Help → Router setup)."),
          h("li", {}, "Xbox, PlayStation and Switch can't add servers by themselves; GeyserMC's guide shows the workarounds."),
          h("li", {}, "With the whitelist on, add Bedrock players with the console command ", h("code", {}, "fwhitelist add <name>"), "; their names start with a dot (.) in game."))]
        : h("div", { class: "row mt-s" }, turnOn, h("span", { class: "muted small" }, "Adds the Geyser and Floodgate mods from Modrinth; remove them on the Mods page any time."))));
  };
  load();
  return box;
}

views.friends = () => {
  const body = h("div");
  let data = null;
  const save = async (changes, message) => {
    const r = await act(() => api("/api/client", { method: "POST", body: changes }), message);
    if (r) { data = r; render(); }
  };
  const reload = async () => { const r = await api("/api/client").catch(() => null); if (r) { data = r; render(); } };
  // Your own mod files for players (e.g. ones that aren't on Modrinth).
  const picker = h("input", { type: "file", multiple: true, accept: ".jar", class: "hidden" });
  picker.addEventListener("change", async () => {
    for (const f of [...picker.files]) {
      const r = await api(`/api/client/local?filename=${encodeURIComponent(f.name)}`, { method: "POST", raw: f })
        .catch((e) => { toast(`${f.name}: ${e.message}`, true); return null; });
      if (r) toast(`${f.name} added for players`);
    }
    picker.value = "";
    reload();
  });
  // Mods the server's mods need on players' computers are added by themselves; say so once.
  const announceCompanions = (d) => {
    const key = `craft-conductor-companions-${server}`;
    let seen = [];
    try { seen = JSON.parse(localStorage.getItem(key) || "[]"); } catch (_) { /* private mode */ }
    const fresh = ((d.pack && d.pack.mods) || []).filter((m) => m.needed_by && !seen.includes(m.project));
    if (!fresh.length) return;
    const byMod = new Map();
    for (const m of fresh) byMod.set(m.needed_by, [...(byMod.get(m.needed_by) || []), m.name]);
    for (const [by, names] of byMod) toast(`Added ${names.join(", ")} for players, because ${by} needs ${names.length === 1 ? "it" : "them"} on their computers.`);
    try { localStorage.setItem(key, JSON.stringify([...seen, ...fresh.map((m) => m.project)])); } catch (_) { /* private mode */ }
  };

  const render = () => {
    const d = data;
    if (!d.available) {
      fill(body, card(null, h("p", {}, "Friend downloads are part of Craft Conductor's server list. Start Craft Conductor by double-clicking it (or `craft-conductor start`) to use them.")));
      return;
    }
    const toggle = h("input", { type: "checkbox", checked: d.enabled, onchange: (e) => save({ enabled: e.target.checked },
      e.target.checked ? "Friend download switched on" : "Friend download switched off") });
    const intro = card("Let friends set up their Minecraft",
      h("p", {}, "Send your friends a link. They click it, download Craft Conductor and run it: it adds a ", h("strong", {}, (status && status.motd) || "server"),
        " instance to their launcher (Minecraft Launcher, Prism Launcher, Modrinth App or CurseForge: they choose) with the right Minecraft version, mod loader and mods, and puts this server in their multiplayer list. They sign in with their own Minecraft account as usual."),
      h("p", { class: "muted small" }, "🔒 Friends' Craft Conductor connects to this computer over HTTPS, and only to this computer: the invite carries its security fingerprint."),
      h("label", { class: "row mt-s" }, toggle, h("span", {}, "Make a download for friends")));
    if (!d.enabled) { fill(body, intro); return; }
    const s = d.share || {};
    const links = d.links || {};
    const linkRow = (label, hint, url) => {
      const input = h("input", { readonly: true, value: url, class: "grow mono", "aria-label": label });
      return h("div", { class: "invite" }, h("strong", {}, label), h("div", { class: "muted small" }, hint),
        h("div", { class: "row" }, input, h("button", { class: "btn primary", onclick: async () => {
          try { await navigator.clipboard.writeText(input.value); toast(`${label} copied`); }
          catch (_) { input.select(); document.execCommand("copy"); toast(`${label} copied`); }
        } }, "Copy")));
    };
    const findIp = h("button", { class: "btn", onclick: async () => {
      findIp.disabled = true;
      const r = await act(() => api("/api/hub/share/public-ip", { method: "POST", body: {} }));
      findIp.disabled = false;
      if (r) { toast(`Your public address is ${r.ip}`); data = await api("/api/client"); render(); }
    } }, links.internet ? "Check my public IP again" : "🌐 Use my public IP");
    const pack = d.pack;
    const companions = ((pack && pack.mods) || []).filter((m) => m.needed_by);
    const sideTag = (m) => h("span", { class: "tag" }, m.side === "client" ? "players only" : "server + players");
    fill(body,
      intro,
      h("div", { class: "mt" }, card("Invite links",
        h("p", { class: "small" }, "Send one of these links (by Discord, text or email). Your friend clicks it, presses ",
          h("strong", {}, "Download"), " and runs the file: Craft Conductor sets up their game. Next time, the link opens their Craft Conductor directly."),
        links.local ? linkRow("Local link", `For friends on the same Wi-Fi or network as this computer (${s.lan_ip}).`, links.local) : null,
        links.internet ? linkRow("Internet link", `For friends anywhere else, through your public address (${s.address}).`, links.internet)
          : h("div", { class: "invite" }, h("strong", {}, "Internet link"),
            h("div", { class: "muted small" }, "For friends elsewhere, Craft Conductor needs your public address. It can find it for you.")),
        h("div", { class: "row mt-s" }, findIp,
          links.internet || links.local ? h("button", { class: "btn", onclick: () => openDiscord(links) }, "💬 Post to Discord") : null,
          h("button", { class: "btn ghost", onclick: async () => {
            if (await ask("Make new links? The old ones stop working (friends who already set up keep playing, but can't update until they get a new link).", { ok: "Make new links", danger: true })) {
              act(() => api("/api/client/new-link", { method: "POST", body: {} }), "New links made").then((r) => { if (r) { data = r; render(); } });
            }
          } }, "New links")),
        links.internet || links.local ? h("details", { class: "mt-s small" }, h("summary", {}, "Advanced: invite codes and security"),
          h("p", { class: "muted" }, "🔒 Friends' Craft Conductor connects to this computer over HTTPS and only to this computer: the invite carries its security fingerprint. " +
            "The link's invite is after the #, which browsers never send anywhere; the page is Craft Conductor's own, on GitHub."),
          h("p", { class: "muted" }, "For ", h("code", {}, "craft-conductor join <code>"), " or pasting into Craft Conductor:"),
          [["Local", links.local], ["Internet", links.internet]].filter(([, l]) => l).map(([label, l]) =>
            h("div", { class: "row mt-s" }, h("span", { class: "tag" }, label),
              h("input", { readonly: true, value: l.split("#")[1].split("/")[0], class: "grow mono", "aria-label": `${label} invite code` })))) : null,
        s.error ? h("div", { class: "notice bad mt-s" }, s.error)
          : h("p", { class: "muted small" }, s.running ? `Sharing on port ${s.port}.` : "Sharing starts in a few seconds."),
        h("p", { class: "muted small" },
          "For the internet link to work, forward two TCP ports on your router to this computer: ", h("strong", {}, String(s.port)),
          " (the download) and ", h("strong", {}, String((status && status.port) || 25565)), " (Minecraft). Your public address can change; ",
          "press the button again if friends can't connect. You can also type an address (e.g. a domain) under ",
          h("a", { href: "#craft-conductor" }, "Craft Conductor settings → Connections → Sharing with friends"), "."))),
      h("div", { class: "mt" }, card("What friends get",
        d.pack_error ? h("div", { class: "notice warn" }, d.pack_error)
          : !pack ? h("p", { class: "empty" }, "Install the server first; the list appears once it's set up.")
          : [h("p", {}, `Minecraft ${pack.minecraft} with ${pack.loader === "vanilla" ? "no mod loader" : pack.loader + " " + pack.loader_version}, ${pack.mods.length} mod(s), ${pack.memory_gb} GB of memory.`),
             pack.mods.length ? h("ul", { class: "list" }, pack.mods.map((m) => h("li", {}, h("span", { class: "grow" }, m.name), sideTag(m)))) : null,
             pack.manual.length ? h("div", { class: "notice warn mt-s" }, "Players have to download these themselves (their authors block automatic downloads): ",
               pack.manual.map((m) => m.name).join(", ")) : null,
             pack.skipped.length ? h("div", { class: "notice warn mt-s" }, pack.skipped.map((x) => `${x.name}: ${x.reason}`).join("; ")) : null],
        d.mods.length ? h("div", { class: "mt-s" }, h("strong", {}, "Mods you added for players: "),
          d.mods.map((x) => h("span", { class: "tag" }, x, " ", h("button", { class: "link-btn", "aria-label": `Remove ${x}`,
            onclick: () => save({ mods: d.mods.filter((y) => y !== x) }, `${x} removed`) }, "✕")))) : null,
        h("label", { class: "mt" }, "Memory for friends' Minecraft",
          (() => { const sel = h("select", { onchange: (e) => save({ memory_gb: Number(e.target.value) }, "Saved") },
            [2, 3, 4, 5, 6, 8, 10, 12, 14, 16, 20, 24, 28, 32].map((g) => h("option", { value: String(g) }, `${g} GB`))); sel.value = String(d.memory_gb); return sel; })()))),
      d.loader === "vanilla" || runsPlugins(d.loader) ? null : h("div", { class: "mt" }, card("Mods for players",
        h("p", { class: "muted small" }, "Client-side mods like minimaps, recipe viewers or performance mods. The server's own mods that players need are included automatically, and so are the client-side mods they need."),
        h("div", { class: "source-buttons" },
          h("button", { type: "button", class: "btn", onclick: () => openBrowser({ type: "mod", target: server, side: "client", loader: d.loader, version: d.minecraft || "" }) },
            "🔎 Set up now", h("span", { class: "small muted" }, "Browse mods that run on players' computers")),
          h("button", { type: "button", class: "btn", onclick: () => picker.click() }, "📁 Local files",
            h("span", { class: "small muted" }, ".jar files on this computer, for players")),
          picker),
        h("h3", { class: "mt" }, "Your players' mods"),
        d.mods.length || d.local_mods.length || companions.length ? h("ul", { class: "list" },
          d.mods.map((x) => h("li", {}, h("strong", { class: "grow" }, x),
            h("button", { class: "btn small danger", onclick: () => save({ mods: d.mods.filter((y) => y !== x) }, `${x} removed`) }, "Remove"))),
          d.local_mods.map((x) => h("li", {}, h("div", { class: "grow" }, h("strong", {}, x), h("span", { class: "tag" }, "local file")),
            h("button", { class: "btn small danger", onclick: async () => (await ask(`Remove ${x} from the players' download?`, { ok: "Remove", danger: true })) &&
              act(() => api("/api/client/local/remove", { method: "POST", body: { name: x } }), `${x} removed`).then(reload) }, "Remove"))),
          companions.map((m) => h("li", { class: "dep" }, h("div", { class: "grow" }, "↳ ", h("strong", {}, m.name),
            h("span", { class: "tag" }, `added automatically: ${m.needed_by} needs it`)))))
          : h("p", { class: "empty" }, "None yet. Leave it empty if you like: players get the server's mods either way."),
        h("div", { class: "row mt-s" }, testButton({ check: ["/api/client/check", {}], trial: null }),
          h("span", { class: "muted small" }, "Checks the server's mods and these together.")))),
    );
    announceCompanions(d);
  };
  fill($("#main"), h("h2", { class: "view-title" }, "Friends"), body, h("div", { class: "mt" }, bedrockCard()));
  api("/api/client").then((r) => { data = r; render(); }).catch((e) => { if (!(e instanceof Unauthorized)) toast(e.message, true); });
  return { refresh: reload };
};

// ------------------------------------------------------------------ mod browser
// Opened from setup, the Mods page and Friends: the page slides left into a narrow rail
// (click it or press Escape to go back) and the browser takes the screen, with search,
// filters and sort at the top left, results with checkboxes below, "Add selected" at the
// bottom, and the mod's page on the right.
let browserOpen = null;
function openBrowser(params) {
  const refresh = () => { if (current && current.refresh) current.refresh(); };
  const b = browserPanel(new URLSearchParams(params), {
    close: () => closeBrowser(),
    addMods: (mods) => {
      for (const m of mods) setupAddMod(setupModKey(m), m.name, m.channel);
      toast(`${mods.length} mod(s) added`);
      closeBrowser();
      refresh();
    },
    pickPack: (pack) => {
      Object.assign(setupState, { modpack: pack, loader: pack.loader, minecraft: pack.minecraft });
      toast(`Modpack chosen: ${pack.name}`);
      closeBrowser();
      if (currentName === "new" || currentName === "setup") refresh(); else location.hash = "#new";
    },
    changed: () => { closeBrowser(); refresh(); },
  });
  openSidePane(b.el, "Mod browser");
  b.start();
}
// The page slides left into a narrow rail (click it or press Escape to go back) and ``el``
// takes the screen: the mod browser, and the Updates tab's "Show why".
function openSidePane(el, label) {
  closeBrowser(true);
  const stage = $("#stage");
  const back = { setup: "setup", new: "setup", mods: "Mods", friends: "Friends", updates: "Updates" }[currentName] || "the page";
  const rail = h("button", { type: "button", class: "browse-rail", title: `Back to ${back} (Esc)`, "aria-label": `Back to ${back}`,
    onclick: () => closeBrowser() }, h("span", { class: "rail-arrow" }, "‹"), h("span", { class: "rail-label" }, `Back to ${back}`));
  const panel = h("section", { class: "inpage-browser", "aria-label": label }, el);
  const focus = document.activeElement;
  $("#main").inert = true;
  stage.append(rail, panel);
  stage.classList.add("browsing");
  browserOpen = { rail, panel, focus };
  rail.focus({ preventScroll: true });
}
function closeBrowser(instant = false) {
  if (!browserOpen) return;
  const { rail, panel, focus } = browserOpen;
  browserOpen = null;
  const stage = $("#stage");
  stage.classList.remove("browsing");
  $("#main").inert = false;
  if (!instant && focus && focus.isConnected) focus.focus({ preventScroll: true });
  if (instant || lessMotion()) { rail.remove(); panel.remove(); return; }
  panel.classList.add("leaving");
  rail.remove();
  setTimeout(() => panel.remove(), 260);
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && helpOpen && !document.querySelector(".modal")) closeHelp();
  else if (e.key === "Escape" && browserOpen && !document.querySelector(".modal")) closeBrowser();
});

function lessMotion() {
  const choice = document.documentElement.dataset.motion;
  return choice === "less" || (choice !== "normal" && matchMedia("(prefers-reduced-motion: reduce)").matches);
}

// Help overlays the navigation and content without routing away or rebuilding forms.
let helpOpen = null;
function closeHelp(instant = false) {
  if (!helpOpen) return;
  const { el, focus, inert } = helpOpen;
  helpOpen = null;
  for (const [node, before] of inert) node.inert = before;
  if (!instant && focus && focus.isConnected) focus.focus({ preventScroll: true });
  if (instant || lessMotion()) el.remove();
  else { el.classList.add("leaving"); setTimeout(() => el.remove(), 260); }
}
function openHelp(name = "help") {
  const previousFocus = helpOpen ? helpOpen.focus : document.activeElement;
  closeHelp(true);
  const content = h("div", { class: "help-content", tabindex: "-1" });
  const contents = h("aside", { class: "help-contents" },
    h("button", { class: "btn", type: "button", onclick: () => closeHelp() }, "← Close Help"),
    h("div", { class: "row mt" },
      h("button", { class: "btn small", onclick: () => openHelp("help") }, "Help"),
      h("button", { class: "btn small", onclick: () => openHelp("manual") }, "User manual")));
  const el = h("section", { class: "help-overlay", role: "dialog", "aria-modal": "true", "aria-label": name === "manual" ? "User manual" : "Help" }, contents, content);
  const inert = [...$("#app").children].map((node) => [node, node.inert]);
  for (const [node] of inert) node.inert = true;
  $("#app").append(el);
  helpOpen = { el, focus: previousFocus, inert };
  views[name](content);
  const toc = content.querySelector(".help-toc");
  if (toc) contents.append(toc);
  contents.querySelector("button").focus({ preventScroll: true });
  el.addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    const nodes = focusables(el);
    const first = nodes[0], last = nodes[nodes.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
}
document.addEventListener("click", (e) => {
  const a = e.target.closest("a[href]");
  if (e.defaultPrevented || !a || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
  const hash = a.getAttribute("href");
  if (hash === "#help" || hash === "#manual") { e.preventDefault(); openHelp(hash.slice(1)); }
});

views.browse = (params) => {  // a direct #browse link: the browser on its own
  document.body.classList.add("browse-mode");
  const b = browserPanel(params, null);
  fill($("#main"), b.el);
  b.start();
  return {};
};

// ------------------------------------------------------------ world generation
// The World card's "World generation & map preview": world-generation mods (ticking one adds it
// to the new server) and a map of the seed, made by a private throwaway server with those mods.
const WORLD_TYPES = [["minecraft:normal", "Normal", "The usual Minecraft world."], ["minecraft:large_biomes", "Large biomes", "Biomes 4× bigger."],
  ["minecraft:amplified", "Amplified", "Huge mountains (needs a fast computer)."], ["minecraft:flat", "Flat", "Superflat, for building."],
  ["minecraft:single_biome_surface", "Single biome", "One biome everywhere."]];
const MAP_SIZES = [[128, "256 × 256 (quick)"], [256, "512 × 512"], [512, "1024 × 1024 (slow)"]];
const biomeLabel = (id) => {
  const [ns, name] = id.includes(":") ? id.split(":") : ["minecraft", id];
  const words = name.replace(/[_/]/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1) + (ns === "minecraft" ? "" : ` (${ns})`);
};
function randomSeed() {
  const b = new Uint32Array(2);
  crypto.getRandomValues(b);
  return String((BigInt(b[0] & 0x7fffffff) << 32n | BigInt(b[1])) * (b[0] & 0x80000000 ? -1n : 1n));
}

// New server → Quick start. Mods are Modrinth slugs; all run on the server only, so friends join
// with plain Minecraft.
const PERFORMANCE_MODS = [["lithium", "Lithium"], ["ferrite-core", "FerriteCore"], ["krypton", "Krypton"]];
const SETUP_PRESETS = [
  { icon: "🟩", name: "Vanilla Minecraft with friends", desc: "Vanilla, always the newest version, with a download that sets up your friends' game.",
    loader: "vanilla", mods: [], friends: true, memory: [2, 4] },
  { icon: "⚡", name: "Smooth survival", desc: "Fabric with performance mods (Lithium, FerriteCore, Krypton): less lag, same game. Friends join with plain Minecraft.",
    loader: "fabric", mods: PERFORMANCE_MODS, memory: [3, 6] },
  { icon: "🗺️", name: "New lands to explore", desc: "Fabric with Terralith (almost 100 new biomes, vanilla blocks) and the performance mods. Friends join with plain Minecraft.",
    loader: "fabric", mods: [["terralith", "Terralith"], ...PERFORMANCE_MODS.slice(0, 2)], memory: [4, 6] },
  { icon: "🧩", name: "Plugins (Paper)", desc: "A fast Paper server for plugins (add them in step 3). Friends join with plain Minecraft.",
    loader: "paper", mods: [], memory: [3, 6] },
  { icon: "📦", name: "A modpack", desc: "Browse Modrinth's modpacks: the pack decides the version and mods.", modpack: true },
];
async function applyPreset(p, opts) {
  if (p.modpack) { openBrowser({ type: "modpack", target: "setup", loader: "" }); return; }
  const st = setupState;
  Object.assign(st, { loader: p.loader, minecraft: "latest", modpack: null, localMods: [], friends: !!p.friends });
  st.mods.clear();
  const [lo, hi] = p.memory;
  st.memory_gb = Math.max(lo, Math.min(hi, opts.memory_gb || lo));
  for (const [slug, name] of p.mods) await setupAddMod(slug, name);
  toast(`Starting point: ${p.name}. Change anything below.`);
  setupChanged();
  if (current && current.refresh) current.refresh();
}

// The explorable map: the previewed world in tiles, dragged around and zoomed (from 4 pixels a
// block out to 32 blocks a pixel). "Make this area" asks the private server for the land in
// view; "Keep making the map as I move" does that by itself.
const MAP_LEVELS = [1, 2, 4, 8, 16];  // blocks a pixel the server draws tiles at
// Landmarks (preview.py): the villages, temples and other structures Minecraft placed, as symbols
// on the map (named for screen readers and on hover), and a list under it.
const LANDMARKS_KEY = "craft-conductor-map-landmarks";
const landmarksShown = () => { try { return localStorage.getItem(LANDMARKS_KEY) !== "off"; } catch (_) { return true; } };
function landmarkMark(l) {
  const words = `${t(l.name)}: x ${l.x}, z ${l.z}`;
  return h("span", { class: "map-mark", title: words, role: "img", "aria-label": words }, l.symbol);
}
function landmarkList(marks, onPick) {
  if (!marks.length) return h("p", { class: "muted small" }, "No landmarks (villages, temples and the like) in the land made so far.");
  const counts = {};
  for (const l of marks) counts[l.name] = (counts[l.name] || 0) + 1;
  const toggle = h("input", { type: "checkbox", checked: landmarksShown() });
  toggle.addEventListener("change", () => {
    try { localStorage.setItem(LANDMARKS_KEY, toggle.checked ? "on" : "off"); } catch (_) { /* private mode */ }
    document.querySelectorAll(".map-marks").forEach((el) => el.classList.toggle("marks-off", !toggle.checked));
  });
  return h("details", { class: "small mt-s landmarks" },
    h("summary", {}, t("Landmarks:") + " " + Object.entries(counts).map(([n, c]) => `${c} × ${t(n)}`).join(", ")),
    h("label", { class: "row" }, toggle, h("span", {}, "Show them on the map")),
    h("ul", { class: "list compact" }, marks.slice(0, 60).map((l) => h("li", {}, h("span", { "aria-hidden": "true" }, l.symbol + " "),
      h("span", { class: "grow" }, t(l.name)),
      onPick ? h("button", { type: "button", class: "link-btn", onclick: () => onPick(l) }, `x ${l.x}, z ${l.z}`) : h("code", {}, `x ${l.x}, z ${l.z}`)))));
}
function mapExplorer(m, info, readout) {
  const id = m.id;
  const home = info.spawn ? { x: info.spawn.x, z: info.spawn.z }
    : info.areas.length ? { x: info.areas[0][0], z: info.areas[0][1] } : { x: 0, z: 0 };
  const view = { x: home.x, z: home.z, bpp: 0.5 };  // the block in the middle; blocks a screen pixel
  let state = info;
  const layer = h("div", { class: "map-layer" });
  const spawn = h("span", { class: "map-spawn", title: "Spawn" });
  const status = h("div", { class: "map-status small" });
  const marksLayer = h("div", { class: "map-layer map-marks" + (landmarksShown() ? "" : " marks-off") });
  const marksBox = h("div");
  let marks = [], marksFrom = null;  // the landmark symbols, and the list they were made from
  const frame = h("div", { class: "map-frame map-live", tabindex: "0", "aria-label": "Map: drag to move, scroll to zoom" }, layer, marksLayer, spawn, status);
  const tiles = new Map();
  let regions = new Set(state.regions.map(([x, z]) => `${x},${z}`));
  const auto = h("input", { type: "checkbox" });
  const makeBtn = h("button", { type: "button", class: "btn small" }, "Make this area");
  const size = () => ({ w: frame.clientWidth || 600, hgt: frame.clientHeight || 600 });

  const draw = () => {
    const { w, hgt } = size();
    const level = MAP_LEVELS.reduce((best, l) => (l <= Math.max(1, view.bpp) ? l : best), 1);
    const span = 256 * level;  // blocks a tile covers
    const left = view.x - (w / 2) * view.bpp, top = view.z - (hgt / 2) * view.bpp;
    const want = new Set();
    for (let tx = Math.floor(left / span); tx <= Math.floor((left + w * view.bpp) / span); tx++) {
      for (let tz = Math.floor(top / span); tz <= Math.floor((top + hgt * view.bpp) / span); tz++) {
        let any = false;  // only ask for tiles where the world has land files
        for (let rx = Math.floor(tx * span / 512); rx <= Math.floor(((tx + 1) * span - 1) / 512) && !any; rx++)
          for (let rz = Math.floor(tz * span / 512); rz <= Math.floor(((tz + 1) * span - 1) / 512) && !any; rz++)
            any = regions.has(`${rx},${rz}`);
        if (!any) continue;
        const key = `${level}:${tx}:${tz}`;
        want.add(key);
        let img = tiles.get(key);
        if (!img) {
          img = h("img", { alt: "", draggable: "false", class: "map-tile" });
          img.dataset.v = "";
          tiles.set(key, img);
          layer.append(img);
        }
        if (img.dataset.v !== String(state.version)) {
          img.dataset.v = String(state.version);
          img.src = `/api/hub/map/tile?id=${id}&s=${level}&x=${tx}&z=${tz}&v=${state.version}`;
        }
        const px = span / view.bpp;  // (positions set here: the page's CSP allows no inline styles)
        img.style.left = `${(tx * span - left) / view.bpp}px`;
        img.style.top = `${(tz * span - top) / view.bpp}px`;
        img.style.width = img.style.height = `${px}px`;
      }
    }
    for (const [key, img] of tiles) if (!want.has(key)) { img.remove(); tiles.delete(key); }
    if (state.spawn) {
      spawn.classList.remove("hidden");
      spawn.style.left = `${(state.spawn.x - left) / view.bpp}px`;
      spawn.style.top = `${(state.spawn.z - top) / view.bpp}px`;
    } else spawn.classList.add("hidden");
    if (marksFrom !== state.landmarks) {  // (new land, new landmarks)
      marksFrom = state.landmarks || [];
      marks = marksFrom.map((l) => [l, landmarkMark(l)]);
      fill(marksLayer, marks.map(([, el]) => el));
      fill(marksBox, landmarkList(marksFrom, (l) => { view.x = l.x; view.z = l.z; view.bpp = 0.5; moved(); frame.focus(); }));
    }
    for (const [l, el] of marks) {
      el.style.left = `${(l.x - left) / view.bpp}px`;
      el.style.top = `${(l.z - top) / view.bpp}px`;
    }
    const r = visibleRadius();
    makeBtn.disabled = !!(state.job && state.job.state === "running");
    makeBtn.title = `About ${estimate(r)} for ${Math.round(r * 2)} × ${Math.round(r * 2)} blocks`;
  };
  const visibleRadius = () => { const { w, hgt } = size(); return Math.min(1024, Math.max(64, Math.ceil(Math.max(w, hgt) * view.bpp / 2 / 16) * 16)); };
  const chunksFor = (r) => (2 * r / 16 + 1) ** 2;
  const estimate = (r) => {
    const s = Math.round(chunksFor(r) / (state.rate || 60));
    return s < 90 ? `${Math.max(5, s)} seconds` : `${Math.round(s / 60)} minutes`;
  };
  // Whether the land in view has all been made (the squares made so far cover it).
  const covered = () => {
    const { w, hgt } = size();
    const pts = [];
    for (let i = 0; i <= 4; i++) for (let j = 0; j <= 4; j++)
      pts.push([view.x + (i / 4 - 0.5) * w * view.bpp, view.z + (j / 4 - 0.5) * hgt * view.bpp]);
    return pts.every(([x, z]) => state.areas.some(([ax, az, r]) => Math.abs(x - ax) <= r && Math.abs(z - az) <= r));
  };

  const make = async (quiet = false) => {
    const r = visibleRadius();
    const secs = chunksFor(r) / (state.rate || 60);
    if (!quiet && secs > 60 && !(await ask(`Make ${Math.round(r * 2)} × ${Math.round(r * 2)} blocks of this world? ` +
      `It takes about ${estimate(r)}, and the computer works hard meanwhile (the fans may spin up).`, { id: "map-make-area", ok: "Make it" }))) return;
    const res = await api("/api/hub/map/explore", { method: "POST", body: { id, x: Math.round(view.x), z: Math.round(view.z), radius: r } })
      .catch((e) => { if (!quiet && !(e instanceof Unauthorized)) toast(e.message, true); return null; });
    if (res) { state = { ...state, job: res }; showStatus(); watch(); }
  };
  makeBtn.addEventListener("click", () => make());

  const showStatus = () => {
    const j = state.job;
    if (j && j.state === "running") {
      fill(status, h("span", {}, `${t(j.step)}${j.progress !== null && j.progress !== undefined ? ` ${Math.round(j.progress * 100)}%` : ""}`),
        h("button", { type: "button", class: "link-btn", onclick: () => api("/api/hub/map/stop", { method: "POST", body: { id } }).catch(() => null) }, "Stop"));
      status.classList.remove("hidden");
    } else if (j && j.state === "failed") {
      fill(status, h("span", { class: "bad-text" }, j.error));
      status.classList.remove("hidden");
    } else status.classList.add("hidden");
  };
  let polling = null;
  const watch = () => {
    if (polling) return;
    polling = setInterval(async () => {
      if (!frame.isConnected) { clearInterval(polling); polling = null; return; }
      const r = await api(`/api/hub/map?id=${id}`).catch(() => null);
      if (!r) return;
      const grew = r.version !== state.version;
      state = r;
      regions = new Set(r.regions.map(([x, z]) => `${x},${z}`));
      showStatus();
      if (grew) draw();
      if (!r.job || r.job.state !== "running") { clearInterval(polling); polling = null; draw(); }
    }, 1500);
  };

  // Moving and zooming
  let drag = null, autoTimer = null;
  const moved = () => {
    draw();
    clearTimeout(autoTimer);
    autoTimer = setTimeout(() => { if (auto.checked && !covered() && !(state.job && state.job.state === "running") && view.bpp <= 4) make(true); }, 900);
  };
  frame.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY }; frame.setPointerCapture(e.pointerId); frame.classList.add("dragging"); });
  frame.addEventListener("pointerup", () => { drag = null; frame.classList.remove("dragging"); });
  frame.addEventListener("pointermove", (e) => {
    const r = frame.getBoundingClientRect();
    const k = frame.clientWidth ? r.width / frame.clientWidth : 1;  // (the page may be zoomed: see Display)
    if (drag) {
      view.x -= (e.clientX - drag.x) / k * view.bpp;
      view.z -= (e.clientY - drag.y) / k * view.bpp;
      drag = { x: e.clientX, y: e.clientY };
      moved();
    }
    const bx = Math.floor(view.x + ((e.clientX - r.left) / k - frame.clientWidth / 2) * view.bpp);
    const bz = Math.floor(view.z + ((e.clientY - r.top) / k - frame.clientHeight / 2) * view.bpp);
    readout.textContent = `x ${bx}, z ${bz}`;
    clearTimeout(frame.biomeTimer);
    frame.biomeTimer = setTimeout(async () => {
      const b = await api(`/api/hub/map/biome?id=${id}&x=${bx}&z=${bz}`).catch(() => null);
      if (b && readout.textContent === `x ${bx}, z ${bz}`) readout.textContent = `x ${bx}, z ${bz} · ${b.made ? (b.biome ? biomeLabel(b.biome) : "") : t("not made yet")}`;
    }, 150);
  });
  const zoom = (factor, cx = null, cy = null) => {
    const { w, hgt } = size();
    const next = Math.min(32, Math.max(0.25, view.bpp * factor));
    if (cx !== null) {  // keep the block under the pointer where it is
      view.x += (cx - w / 2) * (view.bpp - next);
      view.z += (cy - hgt / 2) * (view.bpp - next);
    }
    view.bpp = next;
    moved();
  };
  frame.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = frame.getBoundingClientRect(), k = frame.clientWidth ? r.width / frame.clientWidth : 1;
    zoom(e.deltaY > 0 ? 1.25 : 0.8, (e.clientX - r.left) / k, (e.clientY - r.top) / k);
  }, { passive: false });
  frame.addEventListener("keydown", (e) => {
    const step = 64 * view.bpp;
    const keys = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (keys[e.key]) { e.preventDefault(); view.x += keys[e.key][0]; view.z += keys[e.key][1]; moved(); }
    else if (e.key === "+" || e.key === "=") zoom(0.8);
    else if (e.key === "-") zoom(1.25);
  });
  new ResizeObserver(() => draw()).observe(frame);

  const tools = h("div", { class: "row map-tools mt-s" },
    h("button", { type: "button", class: "btn small", title: "Zoom in", "aria-label": "Zoom in", onclick: () => zoom(0.5) }, "+"),
    h("button", { type: "button", class: "btn small", title: "Zoom out", "aria-label": "Zoom out", onclick: () => zoom(2) }, "−"),
    h("button", { type: "button", class: "btn small", onclick: () => { view.x = home.x; view.z = home.z; view.bpp = 0.5; moved(); } }, "⌖ Back to spawn"),
    makeBtn,
    h("label", { class: "row small" }, auto, h("span", {}, "Keep making the map as I move")));
  showStatus();
  if (state.job && state.job.state === "running") watch();
  setTimeout(draw, 0);
  return { el: h("div", {}, frame, tools, marksBox) };
}

function openWorldPanel() {
  const refresh = () => { if (current && current.refresh) current.refresh(); };
  const p = worldPanel({ close: () => { closeBrowser(); refresh(); }, changed: refresh });
  openSidePane(p.el, "World generation");
  p.start();
}

function worldPanel(host) {
  const st = setupState;
  const P = st.properties;
  st.previews = st.previews || [];
  const moddable = !!(st.loader && st.loader !== "vanilla");
  const plugins = runsPlugins(st.loader);
  let poll = null, shown = null;

  // --- the world's settings (the same ones as on the World card)
  const seed = h("input", { value: P["level-seed"] || "", maxlength: 64, placeholder: "Random", "aria-label": "Seed",
    oninput: (e) => { P["level-seed"] = e.target.value; }, onchange: () => host.changed() });
  const dice = h("button", { type: "button", class: "btn", title: "A random seed", "aria-label": "A random seed",
    onclick: () => { seed.value = P["level-seed"] = randomSeed(); host.changed(); } }, "🎲");
  const type = h("select", { "aria-label": "World type", onchange: () => { P["level-type"] = type.value; host.changed(); } },
    WORLD_TYPES.map(([v, label]) => h("option", { value: v }, label)));
  type.value = P["level-type"] || "minecraft:normal";
  const structures = h("input", { type: "checkbox", checked: P["generate-structures"] !== "false",
    onchange: () => { P["generate-structures"] = String(structures.checked); host.changed(); } });
  const size = h("select", { "aria-label": "Map size" }, MAP_SIZES.map(([v, label]) => h("option", { value: String(v) }, label)));
  size.value = String(st.previewSize || 128);
  size.addEventListener("change", () => { st.previewSize = Number(size.value); });
  const go = h("button", { type: "button", class: "btn primary" }, "🗺️ Preview map");
  const compare = h("button", { type: "button", class: "btn", title: "Maps of 10 random seeds side by side, to pick from" }, "Compare 10 seeds");

  // --- world-generation mods
  const list = h("div", { class: "browse-results" });
  const q = h("input", { type: "search", placeholder: plugins ? "Search world generation plugins…" : "Search world generation mods…", "aria-label": "Search" });
  const inServer = h("span", { class: "grow muted small" });
  let results = [], seq = 0, timer;
  const countMods = () => {
    const all = [...st.mods.values()];
    const n = all.filter((m) => m.explicit).length, needed = all.length - n;
    inServer.textContent = !n ? "No mods yet: the map shows plain Minecraft."
      : needed ? `The map is made with all ${n} of the server's ${plugins ? "plugins" : "mods"} and the ${needed} they need.`
        : `The map is made with all ${n} of the server's ${plugins ? "plugins" : "mods"}.`;
  };
  const search = async () => {
    if (!moddable) {
      fill(list, h("p", { class: "empty" }, "Vanilla servers don't run mods. Pick Fabric, NeoForge, Forge, Quilt or Paper under 1. Server type to add world generation mods."));
      return;
    }
    const mine = ++seq;
    const params = new URLSearchParams({ type: "mod", q: q.value.trim(), source: "modrinth", sort: q.value.trim() ? "relevance" : "downloads",
      offset: "0", category: "worldgen", version: setupModVersion(), loader: st.loader });
    fill(list, h("p", { class: "empty" }, "Searching…"));
    const r = await api(`/api/hub/browse/search?${params}`).catch((e) => { if (!(e instanceof Unauthorized)) fill(list, h("div", { class: "notice bad" }, e.message)); return null; });
    if (!r || mine !== seq) return;
    results = r.results;
    renderList();
  };
  const renderList = () => {
    countMods();
    fill(list, results.length ? results.map((m) => {
      const key = setupModKey(m);
      const box = h("input", { type: "checkbox", checked: st.mods.has(key), "aria-label": `Use ${m.name}`, onchange: async (e) => {
        if (e.target.checked) {
          if (!(await confirmEarly([m]))) { e.target.checked = false; return; }
          await setupAddMod(key, m.name, m.channel && m.channel !== "release" ? m.channel : null);
        } else await setupRemoveMod(key);
        renderList();
        host.changed();
      } });
      return h("label", { class: "result" }, box,
        m.icon ? h("img", { src: m.icon, alt: "", loading: "lazy", referrerpolicy: "no-referrer" }) : h("div", { class: "noicon" }),
        h("div", { class: "info" }, h("div", { class: "name" }, m.name, " ", channelTag(m.channel)), h("div", { class: "desc" }, m.summary),
          h("a", { class: "small", href: m.url || `https://modrinth.com/mod/${m.slug || m.id}`, target: "_blank", rel: "noopener noreferrer",
            onclick: (e) => e.stopPropagation() }, "About it ↗")));
    }) : [h("p", { class: "empty" }, "Nothing found for this Minecraft version. Try other words.")]);
  };
  q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(search, 350); });

  // --- the map
  const right = h("div", { class: "browse-right world-map-pane" });
  const empty = () => h("div", { class: "empty-map" },
    h("h2", {}, "See the world before you make it"),
    h("p", {}, "Pick a seed (or leave it empty for a random one) and press Preview map. Craft Conductor makes the world in a private server on this computer, with the server's mods, then draws it from above."),
    h("p", { class: "muted small" }, "It takes a minute or two, longer with many mods or a bigger map. Nothing is installed for the server yet: that happens when you create it."));
  const strip = () => st.galleryDone && st.galleryDone.maps.length && !st.galleryJob ? h("div", { class: "mt" },
    h("button", { type: "button", class: "btn small", onclick: () => gallery(st.galleryDone) }, "← Back to the seeds compared"))
    : st.previews.length > 1 ? h("div", { class: "mt" }, h("h3", {}, "Earlier maps"),
    h("div", { class: "map-strip" }, st.previews.map((m) => h("button", { type: "button", class: "map-thumb" + (shown === m.id ? " selected" : ""),
      title: `Seed ${m.seed}`, onclick: () => showMap(m) },
      h("img", { src: `/api/hub/preview/map?id=${m.id}`, alt: "" }), h("span", { class: "small" }, m.seed))))) : null;
  const showMap = (m) => {
    shown = m.id;
    const meta = m.map;
    const readout = h("div", { class: "map-readout small" }, "Point at the map to see where it is.");
    const img = h("img", { src: `/api/hub/preview/map?id=${m.id}`, alt: `Map of seed ${m.seed}`, class: "world-map" });
    const pct = (v) => `${Math.max(0, Math.min(100, v * 100))}%`;
    const spawn = h("span", { class: "map-spawn", title: "Spawn" });
    const inside = (v, o) => v >= o && v < o + meta.size;
    if (meta.spawn && inside(meta.spawn.x, meta.x) && inside(meta.spawn.z, meta.z)) {
      spawn.style.left = pct((meta.spawn.x - meta.x) / meta.size);  // (styles set here: the page's CSP allows no inline ones)
      spawn.style.top = pct((meta.spawn.z - meta.z) / meta.size);
    } else spawn.classList.add("hidden");
    const marks = (meta.landmarks || []).map((l) => {
      const el = landmarkMark(l);
      el.style.left = pct((l.x - meta.x) / meta.size);
      el.style.top = pct((l.z - meta.z) / meta.size);
      return el;
    });
    const frame = h("div", { class: "map-frame" }, img, h("div", { class: "map-layer map-marks" + (landmarksShown() ? "" : " marks-off") }, marks), spawn);
    frame.addEventListener("mousemove", (e) => {
      const r = img.getBoundingClientRect();
      const bx = Math.floor(meta.x + (e.clientX - r.left) / r.width * meta.size);
      const bz = Math.floor(meta.z + (e.clientY - r.top) / r.height * meta.size);
      const b = meta.biomes, row = b.grid[(bz >> 4) - b.chunk_z];
      const i = row ? row[(bx >> 4) - b.chunk_x] : -1;
      readout.textContent = `x ${bx}, z ${bz}` + (i >= 0 ? ` · ${biomeLabel(b.names[i])}` : "");
    });
    const same = (P["level-seed"] || "") === m.seed && (P["level-type"] || "minecraft:normal") === m.level_type;
    const typeName = (WORLD_TYPES.find(([v]) => v === m.level_type) || [, m.level_type])[1];
    const biomes = meta.biomes.names.length;
    fill(right,
      h("div", { class: "row" }, h("div", { class: "grow" }, h("h2", {}, `Seed ${m.seed}`),
        h("div", { class: "muted small" }, `${t(typeName)} · ${m.mods.length ? `${m.mods.length} mod(s)` : "no mods"} · ${biomes} biome(s) in view`)),
        same ? h("span", { class: "tag" }, "✓ The server's seed") : h("button", { type: "button", class: "btn primary", onclick: () => {
          seed.value = P["level-seed"] = m.seed; type.value = P["level-type"] = m.level_type;
          P["generate-structures"] = String(m.structures); structures.checked = m.structures;
          host.changed(); toast(`The server will use seed ${m.seed}`); showMap(m);
        } }, "Use this seed")),
      frame, readout,
      h("p", { class: "muted small", id: "map-note" }, "North is up; one pixel is one block, around the spawn point (★). Villages, temples and other landmarks are marked."),
      meta.landmarks ? h("div", { id: "map-landmarks" }, landmarkList(meta.landmarks, null)) : null,
      strip());
    // The world is still here (the newest preview): make the map explorable.
    api(`/api/hub/map?id=${m.id}`).then((info) => {
      if (shown !== m.id || !frame.isConnected) return;
      const ex = mapExplorer(m, info, readout);
      frame.replaceWith(ex.el);
      const listed = document.getElementById("map-landmarks");
      if (listed) listed.remove();  // (the explorable map has its own list)
      const note = document.getElementById("map-note");
      if (note) note.textContent = t("Drag to move and scroll (or + and −) to zoom. Make this area asks the private server for the land in view; it stops by itself after a few minutes of not being needed.");
    }).catch(() => null);
  };
  const showJob = (job) => {
    const bar = h("div", { class: "bar" + (job.progress === null ? " indeterminate" : "") }, h("span", { class: "bar-fill" }));
    if (job.progress !== null) bar.firstChild.style.width = `${Math.round(job.progress * 100)}%`;
    fill(right, h("h2", {}, `Seed ${job.seed}`),
      h("div", { class: "row mt-s" }, h("span", { class: "grow" }, job.step, job.progress !== null ? ` ${Math.round(job.progress * 100)}%` : ""),
        h("span", { class: "muted small" }, `${Math.floor(job.elapsed / 60)}:${String(job.elapsed % 60).padStart(2, "0")}`)),
      bar, h("p", { class: "muted small" }, "You can close this and keep setting up the server: the map carries on, and it's here when you come back."),
      strip());
  };
  // --- the seed gallery: 10 random seeds, one after another
  let gpoll = null;
  const gallery = (g) => {
    const cur = g.current;
    const tiles = g.maps.map((m) => h("button", { type: "button", class: "map-thumb gallery-thumb", title: `Seed ${m.seed}`, onclick: () => {
      st.previews = [m, ...st.previews.filter((x) => x.id !== m.id)].slice(0, 14); showMap(m); } },
      h("img", { src: `/api/hub/preview/map?id=${m.id}`, alt: `Map of seed ${m.seed}` }),
      h("span", { class: "small" }, m.seed), h("span", { class: "muted small" }, `${m.map.biomes.names.length} biome(s)`)));
    for (let i = g.maps.length + (cur ? 1 : 0); i < (g.state === "running" ? g.count : 0); i++) tiles.push(h("div", { class: "gallery-wait" }, "…"));
    if (cur) tiles.splice(g.maps.length, 0, h("div", { class: "gallery-wait" }, h("span", { class: "spinner" }),
      h("span", { class: "small" }, `${t(cur.step)}${cur.progress !== null ? ` ${Math.round(cur.progress * 100)}%` : ""}`)));
    fill(right,
      h("div", { class: "row" }, h("h2", { class: "grow" }, "Compare seeds"),
        g.state === "running" ? h("span", { class: "muted small" }, `${Math.min(g.index, g.count)} / ${g.count} · ${Math.floor(g.elapsed / 60)}:${String(g.elapsed % 60).padStart(2, "0")}`) : null),
      g.state === "running" ? h("p", { class: "muted small" }, "Pick one when you see one you like: press it to look closer and use its seed. You can close this panel meanwhile.")
        : g.state === "failed" ? h("div", { class: "notice bad" }, h("strong", {}, "The maps couldn't be made"), h("div", {}, g.error))
          : h("p", { class: "muted small" }, g.maps.length ? "Press a map to look closer and use its seed." : "Stopped before the first map."),
      h("div", { class: "gallery-grid" }, tiles),
      g.failed ? h("p", { class: "muted small" }, `${g.failed} map(s) couldn't be made and were skipped.`) : null);
  };
  const watchGallery = () => {
    clearInterval(gpoll);
    compare.textContent = t("Stop comparing");
    compare.onclick = () => api("/api/hub/preview/gallery/cancel", { method: "POST", body: { id: st.galleryJob } }).catch(() => null);
    go.disabled = true;
    const tick = async () => {
      if (!el.isConnected) { clearInterval(gpoll); return; }
      const g = await api(`/api/hub/preview/gallery?id=${st.galleryJob}`).catch(() => null);
      if (!g) { clearInterval(gpoll); st.galleryJob = null; galleryIdle(); return; }
      gallery(g);
      if (g.state !== "running") { clearInterval(gpoll); st.galleryDone = g; st.galleryJob = null; galleryIdle(); }
    };
    tick();
    gpoll = setInterval(tick, 1500);
  };
  const galleryIdle = () => {
    compare.textContent = t("Compare 10 seeds");
    compare.onclick = startGallery;
    go.disabled = false;
  };
  async function startGallery() {
    const times = st.previews.map((m) => m.elapsed).filter((x) => x > 0);
    const each = times.length ? Math.max(30, times.reduce((a, b) => a + b, 0) / times.length) : 90;
    const mins = Math.max(5, Math.round(each * 10 / 60));
    if (!(await ask(`Make maps of 10 random seeds? It takes about ${mins} minutes (each map is a fresh world), and the computer works hard the whole time: the fans may spin up and games may run slower. You can keep setting up the server meanwhile.`,
      { id: "seed-gallery", ok: "Make 10 maps" }))) return;
    const body = { loader: st.loader, minecraft: st.minecraft, level_type: type.value, structures: structures.checked,
      radius: Number(size.value), mods: [...st.mods].filter(([, m]) => m.explicit).map(([k]) => k), channels: earlyChannels(), count: 10 };
    const r = await act(() => api("/api/hub/preview/gallery", { method: "POST", body }), null);
    if (!r) return;
    st.galleryJob = r.id;
    watchGallery();
  }
  galleryIdle();

  const running = () => {
    compare.disabled = true;
    go.textContent = t("Stop");
    go.classList.remove("primary");
    go.onclick = async () => { if (st.previewJob) await api("/api/hub/preview/cancel", { method: "POST", body: { id: st.previewJob } }).catch(() => null); };
  };
  const idle = () => {
    compare.disabled = false;
    go.textContent = t("🗺️ Preview map");
    go.classList.add("primary");
    go.onclick = start;
  };
  const watch = () => {
    clearInterval(poll);
    running();
    const tick = async () => {
      if (!el.isConnected) { clearInterval(poll); return; }  // (the panel was closed; the map carries on)
      const job = await api(`/api/hub/preview?id=${st.previewJob}`).catch(() => null);
      if (!job) { clearInterval(poll); st.previewJob = null; idle(); return; }
      if (job.state === "running") { showJob(job); return; }
      clearInterval(poll);
      st.previewJob = null;
      idle();
      if (job.state === "done") { st.previews = [job, ...st.previews.filter((m) => m.id !== job.id)].slice(0, 12); showMap(job); }
      else if (job.state === "failed") fill(right, h("div", { class: "notice bad" }, h("strong", {}, "The map couldn't be made"), h("div", {}, job.error)), strip());
      else fill(right, empty(), strip());
    };
    tick();
    poll = setInterval(tick, 1000);
  };
  async function start() {
    const body = { loader: st.loader, minecraft: st.minecraft, seed: seed.value.trim(), level_type: type.value, structures: structures.checked,
      radius: Number(size.value), mods: [...st.mods].filter(([, m]) => m.explicit).map(([k]) => k), channels: earlyChannels() };
    const r = await act(() => api("/api/hub/preview", { method: "POST", body }), null);
    if (!r) return;
    st.previewJob = r.id;
    if (!seed.value.trim()) toast(`A random seed: ${r.seed}`);
    watch();
  }
  idle();

  const el = h("div", { class: "browse" },
    h("div", { class: "browse-left" },
      h("div", { class: "browse-filters" },
        h("div", { class: "row" }, h("strong", { class: "grow" }, "World generation"),
          st.loader ? h("span", { class: "tag" }, st.loader) : null,
          h("button", { class: "btn ghost small", onclick: () => host.close() }, "Close")),
        h("label", {}, "Seed", h("div", { class: "row" }, seed, dice)),
        h("div", { class: "row" }, type, size),
        h("label", { class: "row small" }, structures, h("span", {}, "Villages, temples and other structures")),
        h("div", { class: "row" }, go, compare),
        h("h3", { class: "mt-s" }, plugins ? "World generation plugins" : "World generation mods"),
        moddable ? q : null),
      list,
      h("div", { class: "browse-footer" }, inServer)),
    right);
  return { el, start: () => {
    if (!st.loader) { fill(right, h("div", { class: "notice warn" }, "Pick a server type first (1. Server type)."));  go.disabled = true; }
    else if (st.previewJob) watch();
    else if (st.galleryJob) watchGallery();
    else if (st.galleryDone && st.galleryDone.maps.length) gallery(st.galleryDone);
    else if (st.previews.length) showMap(st.previews[0]);
    else fill(right, empty());
    search();
    countMods();
  } };
}

function browserPanel(params, host) {
  const kind = params.get("type") === "modpack" ? "modpack" : "mod";
  const target = params.get("target") || "setup";
  const loader = params.get("loader") || "";
  const noun = runsPlugins(loader) ? "plugin" : kind;
  const forPlayers = params.get("side") === "client";  // the Friends page: mods for players' computers
  const base = target === "setup" ? "/api/hub/browse" : `/api/servers/${encodeURIComponent(target)}/browse`;
  const st = { q: "", source: "modrinth", sort: "relevance", category: "", env: "", version: params.get("version") || "",
    offset: 0, total: 0, results: [], selected: new Map(), active: null, early: false, hidden: 0, earlyHidden: 0 };
  const earlyBox = h("input", { type: "checkbox", onchange: (e) => { st.early = e.target.checked; search(); } });
  const earlyRow = kind === "mod" && !forPlayers ? h("label", { class: "row small early-opt", title: EARLY_WARNING }, earlyBox,
    h("span", {}, "Also show mods with only alpha/beta builds (less stable)")) : null;
  const list = h("div", { class: "browse-results" });
  const details = h("div", { class: "browse-right" }, h("p", { class: "empty" }, `Pick a ${noun} on the left to read about it here.`));
  const count = h("span", { class: "grow muted small" });
  const addBtn = h("button", { class: "btn primary" + (kind === "modpack" ? " hidden" : ""), disabled: true }, `Add selected ${noun}s`);
  guardLeave(addBtn, () => st.selected.size > 0);  // picked, not added yet
  const q = h("input", { type: "search", placeholder: `Search ${noun}s…`, "aria-label": "Search" });
  const sort = h("select", { "aria-label": "Sort by" }, [["relevance", "Best match"], ["downloads", "Most downloaded"],
    ["follows", "Most followed"], ["newest", "Newest"], ["updated", "Recently updated"]].map(([v, l]) => h("option", { value: v }, l)));
  const source = h("select", { "aria-label": "Source" }, h("option", { value: "modrinth" }, "Modrinth"),
    kind === "mod" && noun !== "plugin" && !forPlayers ? h("option", { value: "curseforge" }, "CurseForge") : null,
    kind === "mod" && noun === "plugin" && !forPlayers ? h("option", { value: "hangar" }, "Hangar (PaperMC)") : null);
  // Modrinth's environment tags: where each mod runs. Server pages list server-side and both,
  // players' pages client-side and both; this narrows it to one of the two.
  const envSel = kind === "mod" && noun !== "plugin" ? h("select", { "aria-label": "Runs on", title: "Where the mods run (Modrinth's environment tags)" },
    forPlayers ? [["", "Client-side and both"], ["only", "Client-side only"], ["both", "Both (client and server)"]].map(([v, l]) => h("option", { value: v }, l))
      : [["", "Server-side and both"], ["only", "Server-side only"], ["both", "Both (server and client)"]].map(([v, l]) => h("option", { value: v }, l))) : null;
  const envTag = (m) => m.environment ? h("span", { class: "tag env-" + m.environment },
    { server: "server-side", client: "client-side", both: "server + client" }[m.environment]) : null;
  let cfKey = null;  // whether a CurseForge API key is set (asked once)
  const category = h("select", { "aria-label": "Category" }, h("option", { value: "" }, "All categories"));
  const version = h("input", { value: st.version, placeholder: "Any version", "aria-label": "Minecraft version", class: "narrow" });
  let timer, seq = 0;

  const fmtNum = (n) => n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? Math.round(n / 1e3) + "k" : String(n);
  // What a ticked mod brings along (the page adds those too).
  const needs = async (m) => {
    if (m.source !== "modrinth" || m.deps || forPlayers) return;
    const reqBase = target === "setup" ? "/api/hub/mods/requires" : `/api/servers/${encodeURIComponent(target)}/mods/requires`;
    const p = new URLSearchParams({ id: m.id });
    if (m.channel && m.channel !== "release") p.set("channel", m.channel);
    if (target === "setup" && loader) p.set("loader", loader);
    if (st.version || target === "setup") p.set("version", st.version);
    const r = await api(`${reqBase}?${p}`).catch(() => null);
    if (!r) return;
    m.deps = r.deps.map((d) => d.name);
    m.bad = r.compatible ? "" : r.reason;
    updateFooter();
  };
  const updateFooter = () => {
    const n = st.selected.size;
    const extra = [...new Set([...st.selected.values()].flatMap((m) => m.deps || []))];
    const bad = [...st.selected.values()].filter((m) => m.bad);
    count.textContent = kind === "modpack" ? (st.active ? "" : "Pick a modpack to see its versions.")
      : n ? `${n} selected: ${[...st.selected.values()].map((m) => m.name).slice(0, 3).join(", ")}${n > 3 ? "…" : ""}` +
        (extra.length ? ` · also adds ${extra.join(", ")} (needed)` : "") + (bad.length ? ` · ⚠ ${bad.map((m) => m.bad).join("; ")}` : "")
        : `Tick the ${noun}s you want.`;
    addBtn.disabled = kind === "modpack" ? true : n === 0;
  };
  // CurseForge only answers apps with an API key (free); explain and take one here.
  const keyPanel = () => {
    const input = h("input", { type: "password", placeholder: "Paste your CurseForge API key", autocomplete: "off", "aria-label": "CurseForge API key" });
    const save = h("button", { class: "btn primary", onclick: async () => {
      save.disabled = true;
      try {
        await api("/api/hub/curseforge", { method: "POST", body: { key: input.value } });
        cfKey = true;
        toast("CurseForge key saved. It works for all your servers.");
        loadCategories();
        search();
      } catch (e) { if (!(e instanceof Unauthorized)) toast(e.message, true); save.disabled = false; }
    } }, "Save key");
    fill(list, h("div", { class: "notice key-panel" },
      h("strong", {}, "CurseForge needs an API key"),
      h("p", { class: "small" }, "CurseForge only lets apps search it with a key. It's free and takes a minute:"),
      h("ol", { class: "small" },
        h("li", {}, "Open ", h("a", { href: "https://console.curseforge.com/", target: "_blank", rel: "noopener noreferrer" }, "console.curseforge.com ↗"), " and sign in (a CurseForge or Google account works)."),
        h("li", {}, "Go to ", h("strong", {}, "API keys"), " and copy your key."),
        h("li", {}, "Paste it here. Craft Conductor checks it with CurseForge and keeps it in Craft Conductor settings.")),
      h("div", { class: "row" }, input, save)));
  };
  const search = async (more = false) => {
    if (st.source === "curseforge") {
      if (cfKey === null) cfKey = (await api("/api/hub/curseforge").catch(() => ({ set: false }))).set;
      if (!cfKey) { keyPanel(); st.results = []; updateFooter(); return; }
    }
    const mine = ++seq;
    if (!more) { st.offset = 0; list.scrollTop = 0; }
    const p = new URLSearchParams({ type: kind, q: st.q, source: st.source, sort: st.sort, offset: String(st.offset) });
    if (st.category) p.set("category", st.category);
    if (st.early) p.set("early", "1");
    if (forPlayers) p.set("side", "client");
    if (st.env && st.source === "modrinth") p.set("env", st.env);
    p.set("version", st.version);
    if (loader) p.set("loader", loader);
    if (!more) fill(list, h("p", { class: "empty" }, "Searching…"));
    const r = await api(`${base}/search?${p}`).catch((e) => { if (!(e instanceof Unauthorized)) fill(list, h("div", { class: "notice bad" }, e.message)); return null; });
    if (!r || mine !== seq) return;
    st.results = more ? st.results.concat(r.results) : r.results;
    st.total = r.total;
    st.hidden = (more ? st.hidden : 0) + (r.hidden || 0);
    st.earlyHidden = (more ? st.earlyHidden : 0) + (r.early_hidden || 0);
    renderList();
  };
  const renderList = () => {
    // Search results the chosen version can't run are left out; say so.
    const where = `${loader ? loader + " " : ""}Minecraft ${st.version}`;
    const note = st.version && (st.hidden || st.earlyHidden) ? h("p", { class: "muted small hidden-note" },
      st.hidden ? `${st.hidden} result(s) hidden: no build for ${where}. ` : "",
      st.earlyHidden ? [`${st.earlyHidden} only ${st.earlyHidden === 1 ? "has" : "have"} alpha/beta builds. `,
        h("button", { class: "link-btn", onclick: () => { earlyBox.checked = st.early = true; search(); } }, "Show them")] : null) : null;
    fill(list, note, st.results.length ? st.results.map((m) => {
      const key = `${m.source}:${m.id}`;
      const box = kind === "mod" ? h("input", { type: "checkbox", checked: st.selected.has(key), "aria-label": `Select ${m.name}`,
        onclick: (e) => e.stopPropagation(),
        onchange: (e) => { if (e.target.checked) { st.selected.set(key, m); needs(m); } else st.selected.delete(key); updateFooter(); } }) : null;
      return h("div", { class: "result" + (st.active === key ? " active" : ""), tabindex: "0", role: "button",
        onclick: () => showDetails(m), onkeydown: (e) => { if (e.key === "Enter") showDetails(m); } },
        box || h("span"),
        m.icon ? h("img", { src: m.icon, alt: "", loading: "lazy", referrerpolicy: "no-referrer" }) : h("div", { class: "noicon" }),
        h("div", { class: "info" },
          h("div", { class: "name" }, m.name, m.author ? h("span", { class: "muted small" }, ` by ${m.author}`) : null, " ", channelTag(m.channel), " ", envTag(m)),
          h("div", { class: "desc" }, m.summary),
          h("div", { class: "muted small" }, `⬇ ${fmtNum(m.downloads)}`, m.follows ? ` · ♥ ${fmtNum(m.follows)}` : "",
            m.updated ? ` · updated ${new Date(m.updated).toLocaleDateString()}` : "")));
    }).concat(st.results.length < st.total ? [h("div", { class: "row mt-s" }, h("button", { class: "btn small", onclick: () => { st.offset += 20; search(true); } }, "Load more"))] : [])
      : [h("p", { class: "empty" }, "Nothing found. Try other words or fewer filters.")]);
    updateFooter();
  };
  const showDetails = async (m) => {
    st.active = `${m.source}:${m.id}`;
    renderList();
    fill(details, h("p", { class: "empty" }, `Loading ${m.name}…`));
    const p = await api(`${base}/project?source=${m.source}&id=${encodeURIComponent(m.id)}`).catch((e) => { toast(e.message, true); return null; });
    if (!p || st.active !== `${m.source}:${m.id}`) return;
    const key = `${p.source}:${p.id}`;
    const pick = kind === "mod" ? h("button", { class: "btn" + (st.selected.has(key) ? "" : " primary"), onclick: () => {
      if (st.selected.has(key)) st.selected.delete(key); else st.selected.set(key, m);
      renderList(); showDetails(m);
    } }, st.selected.has(key) ? "✓ Selected" : "Select") : null;
    const versionSel = kind === "modpack" && p.versions.length ? h("select", { "aria-label": "Modpack version" },
      p.versions.map((v) => h("option", { value: v.id }, `${v.name} · Minecraft ${v.minecraft.join(", ")} · ${v.loaders.join(", ")}`))) : null;
    const usePack = kind === "modpack" ? h("button", { class: "btn primary", disabled: !versionSel, onclick: () => {
      const v = p.versions.find((x) => x.id === versionSel.value);
      const packLoader = (v.loaders.find((l) => ["fabric", "neoforge", "forge", "quilt"].includes(l)) || "vanilla");
      const pack = { project: p.id, version_id: v.id, name: p.name, version: v.name, minecraft: v.minecraft[0], loader: packLoader, icon: p.icon };
      if (host) host.pickPack(pack);
      else { Object.assign(setupState, { modpack: pack, loader: pack.loader, minecraft: pack.minecraft }); location.hash = "#new"; }
    } }, "Use this modpack") : null;
    fill(details,
      h("div", { class: "browse-head" },
        p.icon ? h("img", { src: p.icon, alt: "", referrerpolicy: "no-referrer" }) : h("div", { class: "noicon" }),
        h("div", { class: "grow" }, h("h2", {}, p.name), h("div", { class: "muted" }, p.summary),
          h("div", { class: "muted small" }, `⬇ ${fmtNum(p.downloads)}`, p.follows ? ` · ♥ ${fmtNum(p.follows)}` : "",
            p.license ? ` · ${p.license}` : "", p.updated ? ` · updated ${new Date(p.updated).toLocaleDateString()}` : "")),
        h("div", { class: "row" }, pick,
          h("a", { class: "btn ghost", href: p.url, target: "_blank", rel: "noopener noreferrer" }, `Open on ${p.source === "curseforge" ? "CurseForge" : "Modrinth"} ↗`))),
      kind === "modpack" ? h("div", { class: "card mt-s" }, h("label", {}, "Version", versionSel || h("p", { class: "empty" }, "No versions.")),
        h("p", { class: "muted small" }, "The new server is set up with this pack's Minecraft version, mod loader, server mods and configs, and stays on that Minecraft version."),
        h("div", { class: "row mt-s" }, usePack)) : null,
      p.categories.length ? h("div", { class: "mt-s" }, p.categories.map((c) => h("span", { class: "tag" }, c))) : null,
      p.gallery.length ? h("div", { class: "gallery mt" }, p.gallery.map((g) => h("a", { href: g.url, target: "_blank", rel: "noopener noreferrer" },
        h("img", { src: g.url, alt: g.title || "", loading: "lazy", referrerpolicy: "no-referrer" })))) : null,
      Object.keys(p.links).length ? h("div", { class: "row mt-s small" }, Object.entries(p.links).map(([k, v]) =>
        h("a", { href: v, target: "_blank", rel: "noopener noreferrer" }, k.replace("_url", "").replace(/^./, (x) => x.toUpperCase()) + " ↗"))) : null,
      h("div", { class: "mt" }, richText(p.body, p.body_format)));
    details.scrollTop = 0;
  };

  addBtn.addEventListener("click", async () => {
    const mods = [...st.selected.values()].map((m) => ({ source: m.source, id: m.id, slug: m.slug, name: m.name,
      channel: m.channel && m.channel !== "release" ? m.channel : null }));
    if (!(await confirmEarly(mods))) return;
    if (forPlayers && target === "setup") {  // a new server: kept with the setup form until it's created
      for (const m of mods) setupState.clientMods.set(m.slug || m.id, m.name);
      setupState.friends = true;
      toast(`Added ${mods.map((m) => m.name).join(", ")} to your friends' download`);
      if (host) host.changed(); else location.hash = "#new";
      return;
    }
    if (forPlayers) {  // extras in the friends' download (their dependencies come along there)
      const cur = await api(`/api/servers/${encodeURIComponent(target)}/client`).catch(() => null);
      if (!cur) return;
      const r = await act(() => api(`/api/servers/${encodeURIComponent(target)}/client`, { method: "POST",
        body: { mods: [...new Set([...cur.mods, ...mods.map((m) => m.slug || m.id)])] } }), `Added ${mods.map((m) => m.name).join(", ")} for players`);
      if (r && host) host.changed();
      return;
    }
    if (target === "setup") {
      if (host) { host.addMods(mods); return; }
      for (const m of mods) setupAddMod(setupModKey(m), m.name, m.channel);
      location.hash = "#new";
      return;
    }
    const r = await act(() => api(`/api/servers/${encodeURIComponent(target)}/mods/add-many`, { method: "POST", body: { mods } }));
    if (!r) return;
    toast(`Added ${r.added.length} mod(s)` + (r.skipped.length ? `; skipped ${r.skipped.map((x) => `${x.name} (${x.reason})`).join(", ")}` : ""), r.skipped.length > 0);
    st.selected.clear(); renderList();
    if (host) host.changed();
  });
  q.addEventListener("input", () => { st.q = q.value.trim(); clearTimeout(timer); timer = setTimeout(() => search(), 350); });
  sort.addEventListener("change", () => { st.sort = sort.value; search(); });
  source.addEventListener("change", () => {
    st.source = source.value; st.category = "";
    if (envSel) envSel.classList.toggle("hidden", st.source !== "modrinth");  // CurseForge has no such tags
    loadCategories(); search();
  });
  category.addEventListener("change", () => { st.category = category.value; search(); });
  if (envSel) envSel.addEventListener("change", () => { st.env = envSel.value; search(); });
  version.addEventListener("change", () => { st.version = version.value.trim(); search(); });
  const loadCategories = async () => {
    const r = await api(`${base}/categories?type=${kind}&source=${st.source}`).catch(() => null);
    fill(category, h("option", { value: "" }, "All categories"), r ? r.categories.map((c) => h("option", { value: c.id }, c.name)) : []);
  };

  const el = h("div", { class: "browse" },
    h("div", { class: "browse-left" },
      h("div", { class: "browse-filters" },
        h("div", { class: "row" }, h("strong", { class: "grow" }, forPlayers ? "Mods for players" : { modpack: "Modpacks", plugin: "Plugins", mod: "Mods" }[noun]),
          loader ? h("span", { class: "tag" }, loader) : null,
          host ? h("button", { class: "btn ghost small", onclick: () => host.close() }, "Close") : h("a", { class: "btn ghost small", href: target === "setup" ? "#new" : `#s/${target}/mods` }, "Back")),
        q,
        h("div", { class: "row" }, source, sort),
        envSel ? h("div", { class: "row" }, envSel) : null,
        h("div", { class: "row" }, category, version),
        earlyRow),
      list,
      h("div", { class: "browse-footer" }, count, addBtn)),
    details);
  return { el, start: () => { q.focus(); loadCategories(); search(); } };
}

// ------------------------------------------------------------ advanced settings
// Every other server.properties setting, grouped; edits `values` (key -> string) in place.
const WORLD_CARD_PROPS = ["level-seed", "level-type", "generate-structures", "hardcore"];
function propsEditor(schema, values) {
  const pretty = (c) => c.replace(/^minecraft:/, "").replace(/_/g, " ").replace(/^./, (x) => x.toUpperCase());
  const field = (p) => {
    const set = (v) => { values[p.key] = String(v); };
    const hint = p.help ? h("span", { class: "muted small" }, p.help) : null;
    if (p.kind === "bool") {
      return h("label", { class: "row prop-bool" },
        h("input", { type: "checkbox", checked: values[p.key] === "true", onchange: (e) => set(e.target.checked) }),
        h("span", {}, p.label, hint ? h("br") : null, hint));
    }
    let input;
    if (p.kind === "int") input = h("input", { type: "number", min: p.min, max: p.max, value: values[p.key], oninput: (e) => set(e.target.value) });
    else if (p.kind === "choice") {
      input = h("select", { onchange: (e) => set(e.target.value) }, p.choices.map((c) => h("option", { value: c }, pretty(c))));
      input.value = values[p.key];
    } else input = h("input", { value: values[p.key], maxlength: p.max_len || null, oninput: (e) => set(e.target.value) });
    return h("label", {}, p.label, input, hint);
  };
  const groups = [...new Set(schema.map((p) => p.group))];
  return h("div", { class: "props" }, groups.map((g) => h("fieldset", {},
    h("legend", {}, g), h("div", { class: "grid" }, schema.filter((p) => p.group === g).map(field)))));
}
// Only the settings that differ from `base`, so untouched ones keep Minecraft's own defaults.
function changedProps(values, base) {
  return Object.fromEntries(Object.entries(values).filter(([k, v]) => v !== base[k]));
}

// ------------------------------------------------------------------ help
// The router guide: shown on the Help page, and under a new server's progress (friends
// outside your home can only join once the router passes Minecraft's port to this computer).
function routerHelp(opts = {}) {
  const mc = opts.port || 25565;
  const share = opts.sharePort || ((hubInfo && hubInfo.share && hubInfo.share.port) || 8798);
  const ip = opts.lanIp || (hubInfo && hubInfo.share && hubInfo.share.lan_ip) || "this computer's address";
  return h("div", { class: "help-router" },
    h("p", {}, "Friends on your home Wi-Fi can join straight away. Friends ", h("strong", {}, "anywhere else"),
      " reach your server through your router, which has to be told to pass Minecraft's port on to this computer. That's called ",
      h("strong", {}, "port forwarding"), ", and you set it up once:"),
    h("div", { class: "notice" }, h("strong", {}, "Let Craft Conductor try first: "), "many routers can do it by themselves (UPnP). Switch on ",
      h("a", { href: "#craft-conductor" }, "Craft Conductor settings → Connections → Sharing with friends → Open the ports on my router by itself"),
      " and Craft Conductor says whether it worked. If it didn't, or you'd rather not, do it by hand:"),
    h("img", { class: "help-img", src: "/help-network.svg", alt: "A friend on the internet connects to your router, which forwards port " + mc + " to this computer." }),
    h("ol", { class: "steps" },
      h("li", {}, "Give this computer a fixed address on your network, so the rule keeps working: in the router's ", h("strong", {}, "LAN / DHCP"),
        " settings, look for ", h("em", {}, "address reservation"), " or ", h("em", {}, "static lease"), ` and reserve ${ip} for it.`),
      h("li", {}, "Open your router's page in a browser. It's usually ", h("code", {}, "http://192.168.0.1"), " or ", h("code", {}, "http://192.168.1.1"),
        ", and the address and admin password are often on a sticker on the router."),
      h("li", {}, "Find ", h("strong", {}, "Port Forwarding"), ". Routers also call it Virtual Server, NAT, Port Mapping, or Applications & Gaming."),
      h("li", {}, "Add a rule: protocol ", h("strong", {}, "TCP"), ", external and internal port ", h("strong", {}, String(mc)),
        ", to ", h("strong", {}, ip), ". That's Minecraft."),
      h("li", {}, "If friends download their setup from you over the internet, add a second rule for port ", h("strong", {}, String(share)), " the same way."),
      h("li", {}, "Save, then test: ask a friend (or use your phone with Wi-Fi off) to connect.")),
    h("img", { class: "help-img", src: "/help-router.svg", alt: "An example port forwarding rule: Minecraft, TCP, port " + mc + ", to this computer's address." }),
    h("div", { class: "notice warn" }, h("strong", {}, "Every router is different. "),
      "The menus and names above are typical, not exact. If you can't find the setting, check your router's manual or its maker's support site ",
      "(search for your router's model and “port forwarding”), or ask your internet provider. Some providers share one public address between ",
      "customers (called CGNAT); port forwarding can't work then, and they may give you your own address if you ask."),
    h("p", { class: "muted small" }, "Only forward the ports above. Never forward the control panel's port (8765): to manage Craft Conductor from elsewhere, use ",
      h("button", { type: "button", class: "link-btn", onclick: openRemoteAccess }, "Remote access & phones"), " instead."));
}

const HELP = [
  ["navigation", "Finding your way", () => [
    h("p", {}, "Help and User manual keep your current page open underneath. Use the contents on the left, then Close Help or Escape to return to the same place, with your unsaved entries intact."),
    h("p", {}, "Craft Conductor settings are grouped into Appearance, Sounds & notifications, Sign-in & security, Connections, and About & updates."),
    h("img", { class: "help-img", src: "/screenshots/craft-conductor-settings.png", alt: "Craft Conductor settings with section navigation", loading: "lazy" }),
    h("p", {}, "Update readiness uses green for releases, yellow for early builds, red for missing builds and gray when compatibility could not be checked. A Minecraft upgrade waits for unverified local files. World-generation mods bring their required mods; if one only has an early build, adding it asks you first."),
    h("p", {}, "Bedrock setup checks both Geyser and Floodgate, and offers compatible early builds with a confirmation when releases are unavailable.")]],
  ["start", "Getting started", () => [
    h("p", {}, "Craft Conductor keeps your Minecraft servers running and up to date by themselves. Make a server under ", h("strong", {}, "New server"),
      ": pick the server type (Fabric, NeoForge, Forge, Quilt, Paper or plain Minecraft), the Minecraft version and your mods, then press ",
      h("strong", {}, "Create my server"), ". Craft Conductor downloads Java, Minecraft, the mod loader and the mods, and checks that the server starts."),
    h("p", {}, "Press ", h("strong", {}, "Start"), " when you want to play. In Minecraft, choose Multiplayer → Add Server and use this computer's address."),
    h("p", {}, "Something not working? Press ", h("strong", {}, "🩺 Check my setup"), " on the server's Dashboard: it checks the usual causes ",
      "(Java, memory, disk space, the port, the firewall) and says what to do. ", h("strong", {}, "Test from the internet"), " there checks friends outside your home can connect."),
    h("p", {}, "To play on this computer too, press ", h("strong", {}, "Play on this computer"), " on the server's Dashboard: Craft Conductor sets up Minecraft here ",
      "with the server's mods (it says first whether this computer has the memory for both)."),
    h("p", {}, "Closing this browser tab doesn't stop Craft Conductor: servers keep running and jobs carry on. Open Craft Conductor again from its icon to come back; ",
      h("strong", {}, "Quit"), " (bottom left) stops everything.")]],
  ["friends", "Letting friends join", () => [
    h("p", {}, "On a server's ", h("strong", {}, "Friends"), " page, turn on the friends' download and send the link. Their copy of Craft Conductor sets up ",
      "the right Minecraft version, mod loader and mods in their launcher, and adds your server to their list."),
    h("p", {}, "Friends outside your home also need the router set up (below).")]],
  ["router", "Router setup (port forwarding)", () => [routerHelp()]],
  ["mods", "Mods and updates", () => [
    h("p", {}, "Every mod you add is kept up to date. A new Minecraft version is only installed once every mod supports it; ",
      "the ", h("strong", {}, "Updates"), " tab says what it's waiting for (", h("strong", {}, "Show why"), ")."),
    h("p", {}, "Before installing, use ", h("strong", {}, "🧪 Test these mods"), " to check that a set of mods works together.")]],
  ["crash", "When something goes wrong", () => [
    h("p", {}, "If a server won't start or crashes, Craft Conductor says which mod it suspects and writes a report. The message shows where it is ",
      "(in the server's ", h("code", {}, ".craft-conductor/logs"), " folder), and Minecraft's own log is in the server's ", h("code", {}, "logs/latest.log"), "."),
    h("p", {}, "Every update makes a backup first and rolls back by itself if the new version doesn't start. Backups are on the ", h("strong", {}, "Backups"), " tab.")]],
  ["headless", "Running Craft Conductor on another computer", () => [
    h("p", {}, "Craft Conductor can run on a spare Linux computer or a Raspberry Pi (64-bit) with no screen, and you manage it from here in the browser. " +
      "The easy way: ", h("a", { href: "#new" }, "New server"), " → ", h("strong", {}, "Install on a Linux computer"),
      " opens SSH in a terminal and installs Craft Conductor there. Or, from your own computer (PowerShell on Windows, Terminal on a Mac or Linux), run one command, using that computer's user and address:"),
    h("pre", { class: "log" }, 'ssh minecraft@192.168.1.50 "curl -fsSL https://raw.githubusercontent.com/silverWRX03/craft-conductor/main/packaging/install.sh | sh"'),
    h("p", {}, "It installs Craft Conductor there, starts it at boot, and prints the address to open and a one-time password. ",
      h("a", { href: "https://github.com/silverWRX03/craft-conductor/blob/main/docs/headless.md", target: "_blank", rel: "noopener noreferrer" }, "Step-by-step guide ↗"),
      " · ", h("a", { href: "https://github.com/silverWRX03/craft-conductor/blob/main/docs/docker.md", target: "_blank", rel: "noopener noreferrer" }, "Docker ↗"))]],
  ["remote", "Using Craft Conductor from your phone", () => [
    h("p", {}, "The hamburger menu at the top left opens navigation. The Light / Dark slider inside it remembers your theme. On desktop the slider is in the top bar. The Dashboard shows CPU, RAM, server-volume Disk usage and Players in four cards, above the boxed Live console."),
    h("p", {}, "Open ", h("button", { type: "button", class: "link-btn", onclick: openRemoteAccess }, "Remote access & phones"),
      ": set a strong password, allow other devices, and pair your phone by scanning a QR code. Away from home, use Tailscale rather than opening ports.")]],
  ["keyboard", "Keyboard, screen readers and display", () => [
    h("p", {}, "Everything works with the keyboard: Tab moves, Enter or Space presses, Escape closes a window. The first Tab reaches ",
      h("strong", {}, "Skip to main content"), ". Screen readers read out messages as they appear."),
    h("p", {}, "Bigger text, ", h("strong", {}, "High contrast"), " and ", h("strong", {}, "Less motion"), " are under ",
      h("a", { href: "#craft-conductor" }, "Craft Conductor settings"), " → Appearance → ", h("strong", {}, "Display"), ".")]],
];

// The user manual (manual.md, part of Craft Conductor): the same text as on GitHub, shown here with a
// table of contents. Sections link within the page; printing gives a paper copy.
const MANUAL_ON_GITHUB = "https://github.com/silverWRX03/craft-conductor/wiki/Craft-Conductor-Manual";  // (the same manual, a page a section, with pictures)
const MANUAL_PICTURES = {
  "Creating a server": ["new-server", "map-preview"], "Dashboard": ["dashboard"], "Console": ["console"],
  "Players": ["players"], "Updates": ["updates", "update-readiness"], "Mods": ["mods"],
  "Friends: playing with friends": ["friends"], "Backups": ["backups"], "Java": ["java"],
  "Settings": ["settings"], "Craft Conductor settings": ["craft-conductor-settings"], "Troubleshooting": ["help"],
};
views.manual = (target = $("#main")) => {
  const body = h("div", { class: "card manual" }, h("p", { class: "empty" }, "Loading the manual…"));
  const toc = h("nav", { class: "help-toc card" }, h("strong", {}, "Contents"));
  fill(target,
    h("div", { class: "row mb" }, h("h2", { class: "view-title grow" }, "User manual"),
      h("button", { class: "btn small", onclick: () => window.print() }, "🖨 Print"),
      h("a", { class: "btn small ghost", href: MANUAL_ON_GITHUB, target: "_blank", rel: "noopener noreferrer" }, "On the wiki, with pictures ↗")),
    toc, h("div", { class: "mt" }, body));
  fetch("/manual.md", { credentials: "same-origin" }).then((r) => r.ok ? r.text() : Promise.reject(new Error(r.statusText)))
    .then((md) => {
      const rich = richText(md, "markdown");
      rich.querySelector("h1") && rich.querySelector("h1").remove();  // the page has its own title
      const heads = [...rich.querySelectorAll("h2, h3")];
      heads.forEach((el, i) => { el.id = `manual-${i}`; });
      for (const heading of heads) {
        const pictures = MANUAL_PICTURES[heading.textContent.trim()];
        if (pictures) heading.after(h("details", { class: "manual-pictures" }, h("summary", {}, "See this screen"),
          pictures.map((name) => h("img", { class: "help-img", src: `/screenshots/${name}.png`, alt: heading.textContent, loading: "lazy" }))));
      }
      fill(toc, h("strong", {}, "Contents"), h("ul", {}, heads.map((el) => h("li", { class: el.tagName === "H3" ? "sub" : null },
        h("a", { href: "#manual", onclick: (e) => { e.preventDefault(); el.scrollIntoView({ behavior: "smooth" }); } }, el.textContent)))));
      fill(body, rich);
    })
    .catch((e) => fill(body, h("div", { class: "notice bad" }, `Couldn't load the manual (${e.message}). It's also on `,
      h("a", { href: MANUAL_ON_GITHUB, target: "_blank", rel: "noopener noreferrer" }, "GitHub ↗"), ".")));
  return {};
};

views.help = (target = $("#main")) => {
  fill(target, h("h2", { class: "view-title" }, "Help"),
    hubInfo && hubInfo.guide ? h("div", { class: "card mb row" }, h("div", { class: "grow" }, h("strong", {}, "🧭 Guided setup"),
      h("div", { class: "muted small" }, "Step by step from making a server to a friend joining it, with each step ticked as you go.")),
      h("button", { class: "btn primary", onclick: startGuide }, hubInfo.guide.active ? "Show the guide" : "Start the guided setup")) : null,
    h("div", { class: "notice mb" }, "📖 Everything Craft Conductor does, step by step: ", h("a", { href: "#manual" }, h("strong", {}, "the user manual")), ". ",
      "Something wrong? ", h("a", { href: "https://github.com/silverWRX03/craft-conductor/issues/new/choose", target: "_blank", rel: "noopener noreferrer" }, "Report a bug ↗"),
      " · ", h("a", { href: "https://github.com/silverWRX03/craft-conductor/blob/main/CHANGELOG.md", target: "_blank", rel: "noopener noreferrer" }, "What's new ↗")),
    h("nav", { class: "help-toc card" }, h("strong", {}, "Contents"),
      h("ul", {}, HELP.map(([id, title]) => h("li", {}, h("a", { href: "#help", onclick: (e) => { e.preventDefault(); $(`#help-${id}`).scrollIntoView({ behavior: "smooth" }); } }, title))))),
    HELP.map(([id, title, body]) => h("section", { class: "card mt help-section", id: `help-${id}` }, h("h3", {}, title), body())));
  return {};
};

// ------------------------------------------------------------ remote access
// Using Craft Conductor from other devices: a strong password (never a PIN), then phones paired by
// scanning a QR code. A paired phone gets its own key and only the everyday controls.
function strongPassword(p) {
  return p.length >= 12 && /[A-Z]/.test(p) && /[a-z]/.test(p) && /[^A-Za-z0-9\s]/.test(p);
}
function passwordChecklist(input) {
  const rules = [["12 or more characters", (p) => p.length >= 12], ["an uppercase letter", (p) => /[A-Z]/.test(p)],
    ["a lowercase letter", (p) => /[a-z]/.test(p)], ["a special character (like ! ? # %)", (p) => /[^A-Za-z0-9\s]/.test(p)]];
  const list = h("ul", { class: "checklist small" });
  const update = () => fill(list, rules.map(([text, ok]) => h("li", { class: ok(input.value) ? "ok-text" : "muted" }, (ok(input.value) ? "✓ " : "• ") + text)));
  input.addEventListener("input", update);
  update();
  return list;
}
// A server on another computer: a Linux PC without a screen on this network, set up over SSH.
function openSshInstall() {
  if ($("#ssh-install")) return;
  const close = () => $("#ssh-install").remove();
  const host = h("input", { placeholder: "192.168.1.50", autocomplete: "off", spellcheck: "false", "aria-label": "Address" });
  const user = h("input", { placeholder: "minecraft", autocomplete: "off", spellcheck: "false", "aria-label": "User name" });
  const port = h("input", { type: "number", value: 22, min: 1, max: 65535, class: "narrow", "aria-label": "SSH port" });
  const out = h("div", { class: "mt" });
  // A rented server (a VPS) is on the internet: its control panel stays private, reached through SSH.
  const rented = h("input", { type: "checkbox" });
  let rentedTouched = false;
  rented.addEventListener("change", () => { rentedTouched = true; });
  const homeNetwork = (v) => /^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.|127\.|169\.254\.|fd|fe80)/i.test(v) || !v.includes(".") || /\.(local|lan|home|internal)\.?$/i.test(v);
  host.addEventListener("input", () => { if (!rentedTouched) rented.checked = !!host.value.trim() && !homeNetwork(host.value.trim()); });
  const body = () => ({ host: host.value.trim(), user: user.value.trim(), port: Number(port.value), rented: rented.checked });
  const openPanel = async (r) => {
    if (hubInfo && hubInfo.local) {
      const t = await api("/api/hub/remote-install/open", { method: "POST", body: { ...body(), tunnel: true } }).catch((e) => { toast(e.message, true); return null; });
      if (t) toast("An SSH window opened: sign in there, keep it open, then open the control panel.");
    }
  };
  const after = (r, opened) => r.rented ? fill(out,
    opened ? h("div", { class: "notice ok" }, h("strong", {}, "A terminal window opened. "),
      "Type the server's password there when asked (the first time, answer ", h("code", {}, "yes"), " to trust it). It installs Craft Conductor and shows a one-time password.") : null,
    h("p", { class: "small mt-s" }, opened ? "The command it runs:" : "Run this in a terminal on this computer (PowerShell on Windows):"),
    h("pre", { class: "log" }, r.command),
    h("div", { class: "notice mt-s" }, h("strong", {}, "A rented server's control panel stays private. "),
      "It isn't open to the internet: you reach it through SSH, an encrypted tunnel to this computer. Press ", h("strong", {}, "Open an SSH tunnel"),
      " (keep that window open while you use it), then ", h("strong", {}, "Open its control panel"), "."),
    h("div", { class: "row mt-s" },
      hubInfo && hubInfo.local ? h("button", { class: "btn small", onclick: () => openPanel(r) }, "🔐 Open an SSH tunnel") : null,
      h("a", { class: "btn small primary", href: r.panel, target: "_blank", rel: "noopener noreferrer" }, "Open its control panel ↗"),
      h("button", { class: "btn small ghost", onclick: () => navigator.clipboard.writeText(r.tunnel_command).then(() => toast("Tunnel command copied")) }, "Copy the tunnel command")),
    h("pre", { class: "log small" }, r.tunnel_command),
    h("p", { class: "muted small" }, "On the server, let players in through its firewall (and in your provider's firewall, if it has one): ",
      h("code", {}, "sudo ufw allow OpenSSH && sudo ufw allow 25565/tcp && sudo ufw allow 8766/tcp && sudo ufw enable"),
      ". Friends join at the server's own address. More in the rented servers guide."))
    : fill(out,
    opened ? h("div", { class: "notice ok" }, h("strong", {}, "A terminal window opened. "),
      "Type that computer's password there when asked (the first time, answer ", h("code", {}, "yes"),
      " to trust it). When it finishes it shows the control panel's address and a one-time password.") : null,
    h("p", { class: "small mt-s" }, opened ? "The command it runs:" : "Run this in a terminal on this computer (PowerShell on Windows):"),
    h("pre", { class: "log" }, r.command),
    h("div", { class: "row mt-s" },
      h("button", { class: "btn small", onclick: () => navigator.clipboard.writeText(r.command).then(() => toast("Command copied")) }, "Copy command"),
      h("a", { class: "btn small primary", href: r.panel, target: "_blank", rel: "noopener noreferrer" }, "Open its control panel ↗")),
    h("p", { class: "muted small" }, "Sign in there with the one-time password from the terminal; it asks you to choose your own. " +
      "Keep that address: that computer's servers are managed from its own control panel."));
  const openBtn = h("button", { class: "btn primary", type: "submit" }, "🔐 Connect with SSH");
  const submit = async (e) => {
    e.preventDefault();
    openBtn.disabled = true;
    const local = hubInfo && hubInfo.local;
    try {
      const r = await api(local ? "/api/hub/remote-install/open" : "/api/hub/remote-install", { method: "POST", body: body() });
      after(r, local);
    } catch (err) {
      if (!(err instanceof Unauthorized)) {
        // No terminal could be opened: still show the command to run by hand.
        const r = await api("/api/hub/remote-install", { method: "POST", body: body() }).catch(() => null);
        if (r) { toast(err.message, true); after(r, false); } else fill(out, h("div", { class: "notice bad" }, err.message));
      }
    }
    openBtn.disabled = false;
  };
  document.body.append(h("div", { class: "modal-backdrop", id: "ssh-install", role: "dialog", "aria-modal": "true", "aria-labelledby": "ssh-title" },
    h("div", { class: "modal remote" },
      h("div", { class: "row" }, h("h2", { id: "ssh-title", class: "grow" }, "Install on a Linux computer or rented server (SSH)"), h("button", { class: "btn ghost small", onclick: close }, "Close")),
      h("p", { class: "muted small" }, "For a spare PC, home server or Raspberry Pi 4/5 (64-bit) on this network, or a rented Linux server (a VPS), with SSH turned on. " +
        "Craft Conductor opens a terminal that connects to it and installs Craft Conductor there; your password is typed into SSH, never into Craft Conductor. " +
        "Use a normal user on that computer (not root), e.g. one made with ", h("code", {}, "sudo adduser minecraft"), "."),
      h("form", { onsubmit: submit },
        h("div", { class: "grid" },
          h("label", {}, "Its address or name", host, h("span", { class: "muted small" }, "Your router's list of devices shows it, or run hostname -I on it.")),
          h("label", {}, "User name on it", user, h("span", { class: "muted small" }, "A normal user (not root). SSH asks for its password.")),
          h("label", {}, "SSH port", port)),
        h("label", { class: "row mt-s" }, rented, h("span", {}, "It's a rented server on the internet (a VPS): keep its control panel private, reached through SSH")),
        h("div", { class: "row mt" }, openBtn)),
      out,
      h("p", { class: "muted small mt" }, "More in ",
        h("a", { href: "https://github.com/silverWRX03/craft-conductor/blob/main/docs/headless.md", target: "_blank", rel: "noopener noreferrer" }, "the headless guide ↗"), "."))));
  host.focus();
}

function openRemoteAccess() {
  if ($("#remote")) return;
  const body = h("div", {});
  let timer = null;
  const close = () => { clearInterval(timer); $("#remote").remove(); };
  document.body.append(h("div", { class: "modal-backdrop", id: "remote", role: "dialog", "aria-modal": "true", "aria-labelledby": "remote-title" },
    h("div", { class: "modal remote" },
      h("div", { class: "row" }, h("h2", { id: "remote-title", class: "grow" }, "Remote access & phones"), h("button", { class: "btn ghost small", onclick: close }, "Close")),
      body)));
  const step = (n, title, ...kids) => h("section", { class: "remote-step" }, h("h3", {}, `${n}. ${title}`), ...kids);
  const load = async () => {
    const r = await api("/api/hub/remote").catch((e) => { fill(body, h("div", { class: "notice bad" }, e.message)); return null; });
    if (!r) return;
    if (!r.available) { fill(body, h("p", {}, "Remote access is part of Craft Conductor's server list. Start Craft Conductor by double-clicking it (or `craft-conductor start`).")); return; }
    // 1. a strong password
    let pw;
    if (r.strong) pw = h("p", { class: "ok-text" }, "✓ Your password is strong enough for remote access.");
    else {
      const p1 = h("input", { type: "password", autocomplete: "new-password", "aria-label": "New password" });
      const p2 = h("input", { type: "password", autocomplete: "new-password", "aria-label": "Repeat it" });
      const save = h("button", { class: "btn primary", onclick: async () => {
        if (!strongPassword(p1.value)) { toast(`The password needs ${r.rules}.`, true); return; }
        if (p1.value !== p2.value) { toast("The two passwords don't match", true); return; }
        const ok = await act(() => api("/api/auth/change", { method: "POST", body: { mode: "password", secret: p1.value } }), "Password changed");
        if (ok) load();
      } }, "Set password");
      pw = [h("p", { class: "small" }, r.mode === "pin" ? "PINs can't be used for remote access: they're too easy to guess. Choose a password:"
          : "Choose a strong password (PINs aren't allowed for remote access):"),
        h("div", { class: "grid" }, h("label", {}, "New password", p1), h("label", {}, "Repeat it", p2)), passwordChecklist(p1),
        h("div", { class: "row" }, save)];
    }
    // 2. other devices
    const toggle = h("input", { type: "checkbox", checked: r.network_access, disabled: !r.strong && !r.network_access, onchange: async (e) => {
      const ok = await act(() => api("/api/hub/network", { method: "POST", body: { enabled: e.target.checked } }));
      if (ok) toast(ok.restart_needed ? "Saved. Close and reopen Craft Conductor (Quit, then start it again) for this to take effect." : "Saved");
      load();
    } });
    const restartNote = r.configured !== r.running_on_network ? h("div", { class: "notice warn small mt-s" }, "Close and reopen Craft Conductor (Quit, then start it again) for this to take effect.") : null;
    // 3. away from home
    const away = [
      h("p", { class: "small" }, "On your home Wi-Fi, a phone reaches this computer directly. To use it away from home, use a private network app instead of opening ports:"),
      h("ol", { class: "steps small" },
        h("li", {}, "Install ", h("a", { href: "https://tailscale.com/download", target: "_blank", rel: "noopener noreferrer" }, "Tailscale ↗"), " (free for personal use) on this computer and on your phone."),
        h("li", {}, "Sign in to the same account on both."),
        h("li", {}, "Reopen this window: a Tailscale address appears under “Pair a phone”.")),
      h("div", { class: "notice warn small" }, h("strong", {}, "Don't forward the control panel's port on your router. "),
        "That puts it on the open internet, where bots try passwords all day. Tailscale keeps it private and encrypted.")];
    // HTTPS (optional)
    const cert = h("input", { value: r.tls_cert || "", placeholder: "Certificate file (.crt / .pem)", "aria-label": "Certificate file" });
    const key = h("input", { value: r.tls_key || "", placeholder: "Key file (.key / .pem)", "aria-label": "Key file" });
    const https = h("details", { class: "mt-s" }, h("summary", {}, `HTTPS (encryption) ${r.tls ? "· on" : "· optional"}`),
      h("p", { class: "small muted" }, "Tailscale already encrypts everything between your devices. To also serve the panel over HTTPS, " +
        "give Craft Conductor a certificate: with Tailscale, run `tailscale cert <this computer's name>` and enter the two files it makes."),
      h("div", { class: "grid" }, cert, key),
      h("div", { class: "row mt-s" }, h("button", { class: "btn", onclick: () => act(() => api("/api/hub/remote/tls", { method: "POST", body: { cert: cert.value, key: key.value } }),
        "Saved. Close and reopen Craft Conductor to switch to HTTPS.").then(load) }, "Save")));
    // 4. pair a phone
    const pairBox = h("div", { class: "pair-box" });
    const addr = h("select", { "aria-label": "Address the phone uses" }, r.addresses.map((a) => h("option", { value: a.host, "data-kind": a.kind }, a.label)));
    // Phones only install the app (and get notifications) from a secure address: say so for the others.
    const addrNote = h("div", { class: "small muted" });
    const hasSecure = r.addresses.some((a) => a.kind === "tailscale-https");
    const useTailscale = async () => {
      const res = await api("/api/hub/phone/tailscale", { method: "POST", body: { on: true } }).catch((e) => { toast(e.message, true); return null; });
      if (!res) return;
      if (res.ok) { toast("The secure Tailscale address is ready"); load(); return; }
      if (!res.enable_url) { toast(res.message, true); return; }
      fill(addrNote, "Tailscale needs HTTPS switched on for your account first (one click): ",
        h("a", { href: res.enable_url, target: "_blank", rel: "noopener noreferrer" }, "switch it on ↗"), ", then press the button again.", " ",
        h("button", { class: "btn small", onclick: useTailscale }, "Set up the secure Tailscale address"));
    };
    const noteAddr = () => {
      const secure = (addr.selectedOptions[0] || {}).dataset && addr.selectedOptions[0].dataset.kind === "tailscale-https";
      addrNote.className = secure ? "small ok-text" : "notice warn small";
      fill(addrNote, secure ? t("A secure address: the phone can install Craft Conductor as an app, with notifications.")
        : [t("At this address Craft Conductor opens in the phone's browser, as a web page, not as an app. To install it as an app with notifications, pair with the Tailscale, secure address."), " ",
          hasSecure ? null : h("button", { class: "btn small", onclick: useTailscale }, "Set up the secure Tailscale address")]);
    };
    addr.addEventListener("change", noteAddr);
    noteAddr();
    const role = h("select", { "aria-label": "What it may do" },
      h("option", { value: "helper" }, "Helper: everyday controls"), h("option", { value: "viewer" }, "Viewer: look only"));
    const pair = h("button", { class: "btn primary", disabled: !r.strong || !r.running_on_network || !r.addresses.length, onclick: async () => {
      const p = await api("/api/hub/devices/pair", { method: "POST", body: { host: addr.value, role: role.value } }).catch((e) => { toast(e.message, true); return null; });
      if (!p) return;
      let left = p.expires_in;
      const clock = h("span", { class: "muted small" });
      const tick = () => { left -= 1; clock.textContent = left > 0 ? `This code works once, for ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")} more.` : "This code has expired; make a new one."; if (left <= 0) { clearInterval(timer); pairBox.querySelector("img").classList.add("expired"); } };
      clearInterval(timer);
      timer = setInterval(tick, 1000);
      tick();
      fill(pairBox, h("img", { class: "qr", alt: "QR code for pairing a phone", src: "data:image/svg+xml;base64," + btoa(p.qr) }),
        h("p", { class: "small" }, p.secure ? "Scan it with the phone's camera and open the link. The phone is paired, then it offers to install the app (an iPhone adds it to the Home Screen first)."
          : "Scan it with the phone's camera and open the link. The phone is paired, and Craft Conductor opens in its browser."),
        h("p", { class: "small" }, "Or, on the phone's sign-in page, choose ", h("strong", {}, "Pair with a code"), " and type ", h("code", { class: "pair-code" }, p.code), "."),
        clock);
    } }, "Show a pairing QR code");
    const devices = r.devices.length ? h("ul", { class: "list" }, r.devices.map((d) => h("li", {},
      h("div", { class: "grow" }, h("strong", {}, d.name), " ", h("span", { class: "tag" }, d.role === "viewer" ? "viewer" : "helper"),
        h("div", { class: "muted small" }, `paired ${new Date(d.created * 1000).toLocaleDateString()} · last used ${ago(d.last_seen)}${d.last_ip ? " from " + d.last_ip : ""}`)),
      h("button", { class: "btn small danger", onclick: async () => (await ask(`Sign out ${d.name}? It will need to be paired again.`, { ok: "Sign out", danger: true })) &&
        act(() => api("/api/hub/devices/remove", { method: "POST", body: { id: d.id } }), `${d.name} signed out`).then(load) }, "Sign out"))))
      : h("p", { class: "empty" }, "No phones paired yet.");
    fill(body,
      step(1, "A strong password", pw),
      step(2, "Let other devices connect", h("label", { class: "row" }, toggle, h("span", {}, "Allow access to this control panel from other devices (phones, other computers)")),
        !r.strong ? h("p", { class: "small muted" }, "Set a strong password first.") : null, restartNote),
      step(3, "Away from home", ...away, https),
      step(4, "Pair a phone (or a co-admin)",
        h("p", { class: "small" }, "A paired device signs in by itself. A ", h("strong", {}, "helper"), " can start, stop and restart servers, make backups, run updates and manage players; " +
          "a ", h("strong", {}, "viewer"), " can only look. Neither can change settings, mods or files, or use the console, and what they do shows in the activity with their name. " +
          "Pair a friend who helps run the server the same way, on their own phone or computer. Changing your password signs all devices out."),
        r.addresses.length ? [h("div", { class: "row" }, addr, role, pair), addrNote] : h("p", { class: "small muted" }, "No network address found for this computer."),
        !r.running_on_network ? h("p", { class: "small muted" }, "Pairing works once access from other devices is on and Craft Conductor has been reopened.") : null,
        pairBox),
      step(5, "Paired phones", devices,
        r.devices.length > 1 ? h("button", { class: "btn ghost small", onclick: async () => (await ask("Sign out every paired phone?", { ok: "Sign out all", danger: true })) &&
          act(() => api("/api/hub/devices/remove", { method: "POST", body: { id: "all" } }), "All phones signed out").then(load) }, "Sign out all") : null));
  };
  load();
}
// The page a phone opens from the QR code (or Pair with a code on the sign-in page): name it, and
// it's paired; then it offers the app. An iPhone's Home Screen app doesn't share Safari's sign-in,
// so on an iPhone the app is added first and paired there by typing the code.
const IOS = /iPhone|iPad|iPod/.test(navigator.userAgent);
function standaloneApp() { return !!(window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) || navigator.standalone === true; }
function secureAddress() { return window.isSecureContext && "serviceWorker" in navigator; }
function pairingScreen(...children) {
  $("#app").classList.add("hidden");
  $("#login").classList.add("hidden");
  if ($("#pairing")) $("#pairing").remove();
  document.body.append(h("div", { class: "login", id: "pairing" }, h("div", { class: "login-card" },
    h("div", { class: "brand big" }, h("span", { class: "logo" }), "Craft Conductor"), ...children)));
}
function showPairing(code, inBrowser = false) {
  if (code && IOS && secureAddress() && !standaloneApp() && !inBrowser) {
    pairingScreen(h("h2", {}, "Get the app first"),
      h("ol", { class: "steps" },
        h("li", {}, "Press Share (the square with an arrow), then Add to Home Screen."),
        h("li", {}, "Open Craft Conductor from your Home Screen."),
        h("li", {}, "Choose Pair with a code, and type:")),
      h("p", { class: "pair-code" }, code),
      h("p", { class: "muted small" }, "The code works once, for five minutes. The Home Screen app doesn't share Safari's sign-in, so it's paired there."),
      h("button", { class: "btn ghost", onclick: () => showPairing(code, true) }, "Just use it in Safari"));
    return;
  }
  const typed = code ? null : h("input", { autocomplete: "one-time-code", autocapitalize: "characters", spellcheck: "false", maxlength: 20,
    placeholder: "ABCD-EFGH-JKLM", "aria-label": "Pairing code" });
  const name = h("input", { value: deviceName(), maxlength: 40, "aria-label": "Name for this phone" });
  const go = h("button", { class: "btn primary", onclick: async () => {
    go.disabled = true;
    try {
      await api("/api/pair", { method: "POST", body: { code: code || typed.value, name: name.value } });
      history.replaceState(null, "", location.pathname);
      toast("Paired. This phone now signs in by itself.");
      if (standaloneApp()) start(); else showGetApp();
    } catch (e) { toast(e.message, true); go.disabled = false; }
  } }, "Pair this phone");
  pairingScreen(h("p", {}, "Pair this phone with your Minecraft server manager?"),
    typed ? h("label", {}, "The code shown on the computer (Craft Conductor settings → Connections → Remote access & phones)", typed) : null,
    h("label", {}, "Name it (so you can tell phones apart)", name), go,
    typed ? h("button", { class: "btn ghost", onclick: () => { $("#pairing").remove(); showLogin(); } }, "Back") : null,
    h("p", { class: "muted small" }, "Only pair your own phone. You can sign it out any time in Craft Conductor settings on the computer."));
  (typed || name).focus();
}
// Right after pairing in the browser: put Craft Conductor on the home screen, as an app.
function showGetApp(installed = false) {
  const later = h("button", { class: "btn ghost", onclick: () => start() }, "Continue in the browser");
  if (!secureAddress()) {
    pairingScreen(h("h2", {}, "Paired ✓"),
      h("div", { class: "notice warn small" }, h("strong", {}, "This address opens Craft Conductor in the browser, not as an app."), " ",
        t("Phones only install it as an app (with notifications, even when it's closed) from a secure address. On the computer: Craft Conductor settings → Connections → Phone app → Use Tailscale for the phone app, then pair again with the Tailscale, secure address.")),
      h("button", { class: "btn primary", onclick: () => start() }, "Continue"));
    return;
  }
  const how = installed ? h("div", { class: "notice ok small" }, "Installed. Open Craft Conductor from your home screen.")
    : installPrompt ? h("button", { class: "btn primary", onclick: async () => {
        const p = installPrompt;
        installPrompt = null;
        p.prompt();
        const choice = await p.userChoice.catch(() => null);
        showGetApp(!!choice && choice.outcome === "accepted");
      } }, "Install the app")
      : IOS ? h("p", {}, "Press Share, then Add to Home Screen. The Home Screen app signs in separately: make a new pairing code on the computer and choose Pair with a code in the app.")
        : [h("p", {}, "In the browser's menu (⋮), choose Install app or Add to Home screen."),
          h("p", { class: "muted small" }, "Don't see it? The QR code may have opened inside the camera app: open this page in Chrome (or your usual browser) first.")];
  pairingScreen(h("h2", {}, "Paired ✓"), h("p", {}, "Now put Craft Conductor on your home screen: it opens like an app, and can tell you when a server needs you."),
    how, later);
  $("#pairing").dataset.getApp = "1";
}

// ------------------------------------------------------------------ Discord
// Posting the invite to a channel, through the user's own bot (a webhook only reaches one
// channel). The first time, it walks through making the bot and adding it to a server.
function openDiscord(links) {
  if ($("#discord")) return;
  const body = h("div", {});
  const close = () => $("#discord").remove();
  document.body.append(h("div", { class: "modal-backdrop", id: "discord", role: "dialog", "aria-modal": "true", "aria-labelledby": "discord-title" },
    h("div", { class: "modal discord" },
      h("div", { class: "row" }, h("h2", { id: "discord-title", class: "grow" }, "Post the invite to Discord"),
        h("button", { class: "btn ghost small", onclick: close }, "Close")),
      body)));
  const ext = (href, text) => h("a", { href, target: "_blank", rel: "noopener noreferrer" }, text);

  const askToken = (info) => {
    const input = h("input", { type: "password", autocomplete: "off", placeholder: "Paste the bot token", "aria-label": "Bot token", class: "grow" });
    const save = h("button", { class: "btn primary", onclick: async () => {
      save.disabled = true;
      try {
        const r = await api("/api/hub/discord", { method: "POST", body: { token: input.value } });
        toast(`Connected as ${r.bot.name}`);
        load();
      } catch (e) { if (!(e instanceof Unauthorized)) toast(e.message, true); save.disabled = false; }
    } }, "Connect");
    fill(body,
      h("p", {}, "Craft Conductor posts through a Discord bot that belongs to you. Setting one up takes a couple of minutes, once:"),
      h("ol", { class: "steps" },
        h("li", {}, "Open the ", ext(info.portal, "Discord Developer Portal ↗"), " and press ", h("strong", {}, "New Application"), ". Name it (e.g. “Minecraft server”)."),
        h("li", {}, "Open the ", h("strong", {}, "Bot"), " tab, press ", h("strong", {}, "Reset Token"), ", then ", h("strong", {}, "Copy"), "."),
        h("li", {}, "Paste the token here. Craft Conductor checks it with Discord and keeps it in Craft Conductor settings; it never leaves this computer otherwise.")),
      h("div", { class: "row" }, input, save),
      h("p", { class: "muted small" }, "The bot only needs to see channels and send messages. Craft Conductor never reads messages, and its posts can't ping @everyone."));
    input.focus();
  };

  const pick = async (info) => {
    let guilds;
    try { guilds = (await api("/api/hub/discord/guilds")).guilds; }
    catch (e) { fill(body, h("div", { class: "notice bad" }, e.message), h("button", { class: "btn mt-s", onclick: () => askToken(info) }, "Use another bot token")); return; }
    const addBot = h("p", { class: "small" }, ext(info.invite_url, `Add ${info.bot.name} to a Discord server ↗`),
      " (you need “Manage Server” there), then ", h("button", { class: "link-btn", onclick: load }, "refresh the list"), ".");
    if (!guilds.length) {
      fill(body, h("div", { class: "notice" }, h("strong", {}, `${info.bot.name} isn't in any Discord server yet. `), "Add it to the one you want to post in:"), addBot);
      return;
    }
    const guildSel = h("select", { "aria-label": "Discord server" }, guilds.map((g) => h("option", { value: g.id }, g.name)));
    const chanSel = h("select", { "aria-label": "Channel" });
    const loadChannels = async () => {
      fill(chanSel, h("option", { value: "" }, "Loading…"));
      const r = await api(`/api/hub/discord/channels?guild=${guildSel.value}`).catch((e) => { toast(e.message, true); return null; });
      const chans = r ? r.channels : [];
      fill(chanSel, chans.length ? chans.map((c) => h("option", { value: c.id }, (c.category ? `${c.category} / ` : "") + "#" + c.name + (c.kind === "announcements" ? " (announcements)" : "")))
        : h("option", { value: "" }, "No text channels the bot can see"));
      if (chans.some((c) => c.id === info.channel)) chanSel.value = info.channel;
    };
    guildSel.addEventListener("change", loadChannels);
    if (guilds.some((g) => g.id === info.guild)) guildSel.value = info.guild;
    const name = (hubInfo && hubInfo.servers && (hubInfo.servers.find((x) => x.id === server) || {}).name) || "our Minecraft server";
    const message = h("textarea", { rows: 3, maxlength: 1800, "aria-label": "Message" },
      `${name} is up! Open the link, run the download, and it sets up Minecraft with everything you need to join.`);
    const useInternet = h("input", { type: "checkbox", checked: !!links.internet, disabled: !links.internet });
    const useLocal = h("input", { type: "checkbox", checked: !links.internet && !!links.local, disabled: !links.local });
    const post = h("button", { class: "btn primary", onclick: async () => {
      const chosen = [useInternet.checked ? "internet" : null, useLocal.checked ? "local" : null].filter(Boolean);
      if (!chanSel.value) { toast("Pick a channel", true); return; }
      if (!chosen.length) { toast("Pick at least one link to post", true); return; }
      post.disabled = true;
      try {
        await api("/api/client/discord", { method: "POST", body: { guild: guildSel.value, channel: chanSel.value, message: message.value, links: chosen } });
        toast(`Posted to #${chanSel.selectedOptions[0].textContent.split("#").pop().replace(/ \(.*$/, "")}`);
        close();
      } catch (e) { if (!(e instanceof Unauthorized)) toast(e.message, true); post.disabled = false; }
    } }, "Post");
    fill(body,
      h("div", { class: "grid" }, h("label", {}, "Discord server", guildSel), h("label", {}, "Channel", chanSel)),
      h("label", { class: "mt-s" }, "Message", message),
      h("div", { class: "mt-s" },
        h("label", { class: "row" }, useInternet, h("span", {}, "Internet link", links.internet ? "" : " (use your public IP on the Friends page first)")),
        h("label", { class: "row" }, useLocal, h("span", {}, "Local link (only works on this computer's network)"))),
      h("div", { class: "row mt" }, post, h("span", { class: "muted small grow" }, `Posting as ${info.bot.name}.`)),
      addBot);
    loadChannels();
  };

  const load = async () => {
    fill(body, h("p", { class: "muted" }, "Loading…"));
    const info = await api("/api/hub/discord").catch((e) => { fill(body, h("div", { class: "notice bad" }, e.message)); return null; });
    if (!info) return;
    if (info.set) pick(info); else askToken(info);
  };
  load();
}

// ------------------------------------------------------------ try before you buy
// "Test these mods": an instant check (builds for this version, declared conflicts), then,
// where a server can be started, a test boot in a throwaway server; if that fails, an
// offer to find the culprits by adding the mods back a group at a time.
//   opts.quick()      -> Promise of /check's result
//   opts.trial        -> body for POST /api/hub/trial (without bisect), or null (friends: no boot)
//   opts.keepWorking  -> called with the report, to drop the mods that don't work
function testButton(opts) {
  return h("button", { type: "button", class: "btn", onclick: () => openTester(opts) }, "🧪 Test these mods");
}
function openTester(opts) {
  if ($("#tester")) { $("#tester").classList.remove("hidden"); return; }
  const body = h("div", {});
  let poll = null, running = null, quickResult = null;
  const clock = (sec) => `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
  // What it's doing right now: in the dialog, and in a toast that stays while the dialog is hidden.
  const stepText = h("span", { class: "grow" }, "Starting…");
  const bar = h("div", { class: "bar" }, h("span", { class: "bar-fill" }));
  const toastText = h("span", { class: "small" }, "Starting…");
  const toastBar = h("div", { class: "bar" }, h("span", { class: "bar-fill" }));
  const setStep = (text, fraction = null) => {
    stepText.textContent = toastText.textContent = text;
    for (const b of [bar, toastBar]) {
      b.classList.toggle("indeterminate", fraction === null);
      b.firstChild.style.width = fraction === null ? "" : `${Math.round(fraction * 100)}%`;
    }
  };
  const hide = () => $("#tester").classList.add("hidden");
  const show = () => $("#tester").classList.remove("hidden");
  const close = async () => {
    if (running && !(await ask("Stop the test?", { ok: "Stop", danger: true }))) return;
    if (running) api("/api/hub/trial/cancel", { method: "POST", body: { id: running } }).catch(() => {});
    clearInterval(poll);
    $("#tester").remove();
    closeToast("tester-toast");
  };
  const finished = (text) => {
    closeToast("tester-toast");
    if (!$("#tester") || !$("#tester").classList.contains("hidden")) return;
    stickyToast("tester-toast", [h("strong", {}, "Mod test finished"), h("span", { class: "small" }, text),
      h("div", { class: "row mt-s" }, h("button", { class: "btn small primary", onclick: () => { closeToast("tester-toast"); show(); } }, "See the results"),
        h("button", { class: "btn small ghost", onclick: close }, "Close"))]);
  };
  const box = h("div", { class: "modal tester" },
    h("div", { class: "row" }, h("h2", { id: "tester-title", class: "grow" }, "Test these mods"),
      h("button", { class: "btn ghost small", title: "The test keeps going; its progress stays in a message at the top", onclick: hide }, "Keep working"),
      h("button", { class: "btn ghost small", onclick: close }, "Close")),
    h("div", { class: "tester-step" }, h("div", { class: "row" }, h("span", { class: "spinner" }), stepText,
      h("span", { class: "muted small tester-time" })), bar),
    body);
  document.body.append(h("div", { class: "modal-backdrop", id: "tester", role: "dialog", "aria-modal": "true", "aria-labelledby": "tester-title" }, box));
  guardLeave(box, () => !!running);  // the report is shown only here
  const stepBox = box.querySelector(".tester-step");
  const idle = () => stepBox.classList.add("hidden");
  const busy = () => stepBox.classList.remove("hidden");
  stickyToast("tester-toast", [h("strong", {}, "Testing mods"),
    h("span", { class: "small" }, "This can take a long time: looking the mods up takes seconds, but a test boot takes a few minutes, and finding which mods break it can take much longer. You can keep using Craft Conductor meanwhile."),
    toastText, toastBar,
    h("div", { class: "row mt-s" }, h("button", { class: "btn small", onclick: show }, "Show"),
      h("button", { class: "btn small ghost", onclick: hide }, "Hide the dialog"))], { blocking: false });

  const issues = (r) => [
    ...r.conflicts.map((c) => h("li", {}, h("strong", {}, c.mods.join(" + ")), h("div", { class: "small muted" }, c.reason))),
    ...r.problems.map((p) => h("li", {}, h("strong", {}, p.mod), h("div", { class: "small muted" }, p.reason)))];

  const runTrial = async (bisect) => {
    const log = h("pre", { class: "log" });
    busy();
    setStep(bisect ? "Finding which mods don't work together…" : "Test boot: installing the mods in a throwaway server and starting it…");
    fill(body, log, h("p", { class: "muted small" }, "Your servers aren't touched. The test server is deleted afterwards."));
    if (!$("#tester-toast")) stickyToast("tester-toast", [h("strong", {}, "Testing mods"), toastText, toastBar,
      h("div", { class: "row mt-s" }, h("button", { class: "btn small", onclick: show }, "Show"))], { blocking: false });
    let r;
    try { r = await api("/api/hub/trial", { method: "POST", body: { ...opts.trial, bisect } }); }
    catch (e) { idle(); fill(body, h("div", { class: "notice bad" }, e.message)); finished(e.message); return; }
    running = r.id;
    let seen = 0;
    poll = setInterval(async () => {
      const t = await api(`/api/hub/trial?id=${running}&since=${seen}`).catch(() => null);
      if (!t) return;
      seen = t.next;
      log.textContent += t.log.map((x) => x + "\n").join("");
      log.scrollTop = log.scrollHeight;
      box.querySelector(".tester-time").textContent = clock(t.elapsed);
      const last = t.log.filter((x) => x.startsWith("Test ")).pop();
      if (last) setStep(last + (bisect ? ` (${t.tests} test${t.tests === 1 ? "" : "s"} so far)` : ""));
      if (t.state === "running") return;
      clearInterval(poll);
      running = null;
      idle();
      report(t, log.textContent);
      const res = t.result || {};
      finished(t.state === "cancelled" ? "The test was stopped." : res.ok ? "✓ The server started with these mods."
        : res.bisected ? `${(res.outliers || []).length} mod(s) don't work.` : "✗ The server didn't start.");
    }, 1500);
  };

  const report = (t, logText) => {
    const res = t.result || {};
    const details = h("details", { class: "mt-s" }, h("summary", {}, "What was tested"), h("pre", { class: "log" }, logText));
    if (t.state === "cancelled") { fill(body, h("div", { class: "notice" }, "The test was stopped."), details); return; }
    if (res.ok) {
      fill(body, h("div", { class: "notice ok" }, h("strong", {}, "✓ It works. "),
        `The server started with ${res.working.length ? "all these mods" : "these settings"}` + (res.minecraft ? ` on Minecraft ${res.minecraft}.` : ".")), details);
      return;
    }
    const diag = res.diagnosis && res.diagnosis.summary;
    if (!res.bisected) {
      fill(body,
        h("div", { class: "notice bad" }, h("strong", {}, "✗ The server didn't start. "), diag || res.reason),
        h("p", {}, "Craft Conductor can find which mods are the problem: it starts test servers with the mods added back a group at a time, splitting any group that fails, until it knows which mods work together."),
        dismissible("test-takes-a-while", h("div", { class: "notice warn" }, "This can take a while: each test starts a server (usually 1 to 3 minutes each), and a long mod list can need a dozen tests or more.")),
        h("div", { class: "row mt-s" },
          h("button", { class: "btn primary", onclick: () => runTrial(true) }, "Find the culprits"),
          h("button", { class: "btn ghost", onclick: close }, "Not now")),
        details);
      return;
    }
    fill(body,
      res.outliers.length ? h("div", { class: "notice warn" }, h("strong", {}, `${res.working.length} of ${res.working.length + res.outliers.length} mods work together. `),
        "These don't:") : h("div", { class: "notice bad" }, res.reason),
      res.outliers.length ? h("ul", { class: "list" }, res.outliers.map((o) => h("li", {},
        h("div", { class: "grow" }, h("strong", {}, o.id), h("div", { class: "small muted" }, o.reason))))) : null,
      res.working.length ? h("div", { class: "mt-s" }, h("strong", {}, "Working together: "), res.working.join(", ")) : null,
      quickResult && (quickResult.conflicts.length || quickResult.problems.length) ? h("div", { class: "mt-s" },
        h("strong", {}, "Known problems (from the mods' own information):"), h("ul", { class: "list" }, issues(quickResult))) : null,
      opts.keepWorking && res.outliers.length ? h("div", { class: "row mt" },
        h("button", { class: "btn primary", onclick: async () => { await opts.keepWorking(res); clearInterval(poll); $("#tester").remove(); } },
          `Remove the ${res.outliers.length === 1 ? "mod that doesn't work" : `${res.outliers.length} mods that don't work`}`),
        h("button", { class: "btn ghost", onclick: close }, "Keep them for now")) : null,
      details);
  };

  // The quick check runs in the background too, so it can say which mod it's looking at.
  const quick = async () => {
    const [path, payload] = opts.check;
    setStep("Looking the mods up on Modrinth…");
    const started = await api(path, { method: "POST", body: { ...payload, background: true } });
    for (;;) {
      await new Promise((ok) => setTimeout(ok, 500));
      if (!$("#tester")) throw new Error("closed");
      const j = await api(`/api/hub/mods/check?id=${started.id}`);
      box.querySelector(".tester-time").textContent = clock(j.elapsed);
      if (j.total) setStep(`Checked ${j.current} (${j.done} of ${j.total})`, j.done / j.total);
      if (j.state === "done") return j.result;
      if (j.state === "failed") throw new Error(j.error || "the check failed");
    }
  };

  (async () => {
    let r;
    try { r = await quick(); } catch (e) { idle(); fill(body, h("div", { class: "notice bad" }, e.message)); finished(e.message); return; }
    idle();
    quickResult = r;
    const found = issues(r);
    fill(body,
      found.length ? [h("div", { class: "notice warn" }, h("strong", {}, "Found problems before starting anything:")), h("ul", { class: "list" }, found)]
        : h("div", { class: "notice ok" }, h("strong", {}, "✓ No known problems. "),
          `${r.mods.length} mod(s) have builds for ${r.minecraft ? `Minecraft ${r.minecraft}` : "this Minecraft"}, and none say they conflict with another.`),
      opts.trial ? [
        h("p", { class: "mt" }, "To be sure, Craft Conductor can start a throwaway server with these mods and see if Minecraft loads. It takes a few minutes; your servers aren't touched."),
        h("div", { class: "row" }, h("button", { class: "btn primary", onclick: () => runTrial(false) }, "Start a test boot"))]
        : h("p", { class: "muted small mt" }, "These mods run on players' computers, and a game can't be started here to try them, so this checks versions and known conflicts. " +
          "The server's own mods can be test-booted on its Mods page."));
    const summary = found.length ? `Found ${found.length} problem(s).` : "✓ No known problems.";
    if (opts.trial) setStep(`${summary} Next: a test boot, which takes a few minutes.`, 1);  // the toast stays till you're done
    else finished(summary);
  })();
}

// ------------------------------------------------------------- code editor
// A config file editor with IDE-style colours: a transparent <textarea> typed into over a
// highlighted copy of the same text. Each language is a list of [sticky regex, token class]
// tried in order at every position; anything unmatched is plain text.
const STR = /"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'/y;
const NUM = /[+-]?(?:0x[0-9a-fA-F_]+|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?[dDfFlLbBsS]?)(?![\w.])/y;
const HIGHLIGHT = {
  toml: [[/#.*/y, "c"], [/^[ \t]*\[\[?[^\]\n]*\]\]?/my, "h"], [/"""[\s\S]*?"""|'''[\s\S]*?'''/y, "s"], [STR, "s"],
    [/(?:true|false)(?![\w-])/y, "b"], [NUM, "n"], [/[A-Za-z0-9_.-]+(?=[ \t]*=)/y, "k"], [/[=,{}[\]]/y, "p"]],
  json: [[/\/\/.*|\/\*[\s\S]*?\*\//y, "c"], [/"(?:\\.|[^"\\\n])*"(?=\s*:)/y, "k"], [STR, "s"],
    [/(?:true|false|null)(?!\w)/y, "b"], [NUM, "n"], [/[A-Za-z_$][\w$]*(?=\s*:)/y, "k"], [/[{}[\],:]/y, "p"]],
  snbt: [[STR, "s"], [/[A-Za-z_][\w.+-]*(?=\s*:)/y, "k"], [/(?:true|false)(?!\w)/y, "b"], [NUM, "n"], [/[{}[\],:;]/y, "p"]],
  yaml: [[/#.*/y, "c"], [/^---|^\.\.\./my, "h"], [/^[ \t]*(?:- +)?[^\s#:'"][^:#\n]*?(?=:(?:\s|$))/my, "k"],
    [STR, "s"], [/(?:true|false|yes|no|on|off|null|~)(?![\w-])/iy, "b"], [NUM, "n"], [/[:\-|>[\]{},&*!]/y, "p"]],
  properties: [[/^[ \t]*[#!].*/my, "c"], [/^[ \t]*[^=:\s#!][^=:\n]*?(?=[ \t]*[=:])/my, "k"], [/(?:true|false)(?![\w-])/y, "b"],
    [NUM, "n"], [/[=:]/y, "p"]],
  ini: [[/^[ \t]*[;#].*/my, "c"], [/^[ \t]*\[[^\]\n]*\]/my, "h"], [/^[ \t]*[^=\s;#[][^=\n]*?(?=[ \t]*=)/my, "k"], [STR, "s"],
    [/(?:true|false)(?![\w-])/iy, "b"], [NUM, "n"], [/=/y, "p"]],
  // Forge's old .cfg: "B:name=true", "S:name=text", lists in < >, blocks in { }
  cfg: [[/#.*/y, "c"], [/^[ \t]*[\w. -]+(?=[ \t]*\{)/my, "h"], [/[BISD]:/y, "t"], [/"[^"\n]*"(?=[ \t]*[=<])|[\w.-]+(?=[ \t]*[=<])/y, "k"],
    [STR, "s"], [/(?:true|false)(?![\w-])/y, "b"], [NUM, "n"], [/[=<>{}]/y, "p"]],
  text: [[/^[ \t]*#.*/my, "c"]],
};
function highlight(text, lang) {
  const rules = HIGHLIGHT[lang] || HIGHLIGHT.text;
  const out = [];
  let i = 0, plain = "";
  const flush = () => { if (plain) { out.push(plain); plain = ""; } };
  while (i < text.length) {
    let hit = null;
    for (const [re, cls] of rules) {
      re.lastIndex = i;
      const m = re.exec(text);
      if (m && m[0].length) { hit = [m[0], cls]; break; }
    }
    if (hit) { flush(); out.push(h("span", { class: "tk-" + hit[1] }, hit[0])); i += hit[0].length; continue; }
    // plain text: a whole word at once (a word can't start a token midway), else one character
    const word = /[A-Za-z_]\w*/y;
    word.lastIndex = i;
    const w = /[A-Za-z_]/.test(text[i]) ? word.exec(text) : null;
    const take = w ? w[0] : text[i];
    plain += take;
    i += take.length;
  }
  flush();
  return out;
}

function codeEditor(text, lang, onChange) {
  const pre = h("pre", { class: "code-hl", "aria-hidden": "true" });
  const gutter = h("div", { class: "code-gutter", "aria-hidden": "true" });
  const input = h("textarea", { class: "code-input", spellcheck: "false", autocapitalize: "off", autocomplete: "off", wrap: "off", "aria-label": "File contents",
    "data-keys": "own", "aria-description": t("Tab indents. To leave the editor with the keyboard, press Escape, then Tab.") });
  input.value = text;
  let lines = 0, frame = 0, leaving = false;
  const sync = () => { pre.scrollTop = input.scrollTop; pre.scrollLeft = input.scrollLeft; gutter.scrollTop = input.scrollTop; };
  const paint = () => {
    frame = 0;
    fill(pre, highlight(input.value, lang), "\n");  // the extra line keeps the last one visible
    const n = input.value.split("\n").length;
    if (n !== lines) { lines = n; gutter.textContent = Array.from({ length: n }, (_, k) => k + 1).join("\n") + "\n"; }
    sync();
  };
  input.addEventListener("input", () => { if (!frame) frame = requestAnimationFrame(paint); onChange(); });
  input.addEventListener("scroll", sync);
  input.addEventListener("blur", () => { leaving = false; });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { leaving = true; return; }  // (then Tab leaves, as in other code editors)
    if (e.key === "Tab" && leaving) return;
    leaving = false;
    if (e.key === "Tab" && !e.ctrlKey && !e.metaKey && !e.altKey) {  // indent instead of leaving the editor
      e.preventDefault();
      input.setRangeText("  ", input.selectionStart, input.selectionEnd, "end");
      input.dispatchEvent(new Event("input"));
    }
  });
  paint();
  const el = h("div", { class: "code-editor" }, gutter, h("div", { class: "code-wrap" }, pre, input));
  return { el, input, get value() { return input.value; }, set value(v) { input.value = v; paint(); } };
}

// The config files of one mod (or all of them), in a big dialog: a file list and the editor.
function openConfigEditor(title, files, first) {
  if ($("#config-editor")) return;
  let current = null;   // { path, text, modified, format }
  let editor = null;
  let dirty = false;
  const list = h("ul", { class: "cfg-files" });
  const pane = h("div", { class: "cfg-pane" }, h("p", { class: "empty" }, "Pick a file."));
  const status = h("span", { class: "muted small grow" });
  const saveBtn = h("button", { class: "btn primary small", disabled: true }, "Save");
  const revertBtn = h("button", { class: "btn small", disabled: true }, "Revert");
  const keys = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); save(); }
    if (e.key === "Escape" && !(e.target.dataset && e.target.dataset.keys === "own")) close();  // (in the editor, Escape readies Tab to leave it)
  };
  const close = async () => {
    if (dirty && !(await ask("Close without saving your changes?", { ok: "Close without saving", danger: true }))) return;
    $("#config-editor").remove();
    document.removeEventListener("keydown", keys);
  };
  const checkJson = () => {
    if (!current || !current.path.endsWith(".json")) return "";
    try { JSON.parse(editor.value); return ""; } catch (e) { return `JSON problem: ${e.message}`; }
  };
  const showPos = () => {
    if (!editor) return;
    const upto = editor.input.value.slice(0, editor.input.selectionStart).split("\n");
    const problem = checkJson();
    status.className = "small grow " + (problem ? "bad-text" : "muted");
    status.textContent = problem || `Line ${upto.length}, column ${upto[upto.length - 1].length + 1} · ${current.format.toUpperCase()}` +
      (dirty ? " · unsaved changes" : "");
  };
  const renderList = () => fill(list, files.map((path) => h("li", {},
    h("button", { type: "button", class: current && current.path === path ? "active" : null, title: path, onclick: () => load(path) },
      path, current && current.path === path && dirty ? " •" : ""))));
  const setDirty = (v) => { dirty = v; saveBtn.disabled = !v; revertBtn.disabled = !v; renderList(); };
  const load = async (path) => {
    if (dirty && !(await ask("Switch files without saving your changes?", { ok: "Switch", danger: true }))) return;
    const f = await api(`/api/configs/file?path=${encodeURIComponent(path)}`).catch((e) => { toast(e.message, true); return null; });
    if (!f) return;
    current = f;
    editor = codeEditor(f.text, f.format, () => { setDirty(editor.value !== current.text); showPos(); });
    editor.input.addEventListener("keyup", showPos);
    editor.input.addEventListener("click", showPos);
    fill(pane, editor.el);
    setDirty(false);
    showPos();
    editor.input.focus();
  };
  const save = async () => {
    if (!current || !dirty) return;
    const problem = checkJson();
    if (problem && !(await ask(`${problem}\n\nSave anyway?`, { ok: "Save anyway", danger: true }))) return;
    try {
      const r = await api("/api/configs/file", { method: "POST", body: { path: current.path, text: editor.value, modified: current.modified } });
      current = { ...current, text: editor.value, modified: r.modified };
      setDirty(false);
      showPos();
      toast(r.running ? "Saved. Restart the server for it to take effect (some mods reload their config by themselves)." : "Saved.");
    } catch (e) { if (!(e instanceof Unauthorized)) toast(e.message, true); }
  };
  saveBtn.addEventListener("click", save);
  revertBtn.addEventListener("click", async () => { if (current && await ask("Undo your unsaved changes?", { ok: "Undo", danger: true })) { editor.value = current.text; setDirty(false); showPos(); } });
  renderList();
  const box = h("div", { class: "modal editor-modal" },
    h("div", { class: "row" }, h("h2", { id: "config-editor-title", class: "grow" }, title), folderBtn("config", "Config folder"),
      h("button", { class: "btn ghost small", onclick: close }, "Close")),
    h("div", { class: "cfg-body" + (files.length > 1 ? "" : " single") }, files.length > 1 ? list : null, pane),
    h("div", { class: "row mt-s" }, status, revertBtn, saveBtn));
  document.body.append(h("div", { class: "modal-backdrop", id: "config-editor", role: "dialog", "aria-modal": "true", "aria-labelledby": "config-editor-title" }, box));
  guardLeave(box, () => dirty);
  document.addEventListener("keydown", keys);
  if (first || files.length) load(first || files[0]);
}

// ------------------------------------------------------------- pick a world
// An existing world: a .zip uploaded from here, or a singleplayer world on the server's
// computer (Minecraft Launcher, Prism, Modrinth App, CurseForge). Calls onPick with
// { world, name, version } where `world` is what the API takes.
function pickWorld(onPick) {
  if ($("#pick-world")) return;
  const close = () => { const m = $("#pick-world"); if (m) m.remove(); };
  const list = h("div", {}, h("p", { class: "muted" }, "Looking for worlds…"));
  const note = h("p", { class: "muted small" });
  const picker = h("input", { type: "file", accept: ".zip", class: "hidden" });
  const choose = (w) => { close(); onPick(w); };
  picker.addEventListener("change", async () => {
    const f = picker.files[0];
    picker.value = "";
    if (!f) return;
    try {
      const r = await upload(`/api/hub/stage?filename=${encodeURIComponent(f.name.replace(/[^A-Za-z0-9 ()\[\]+_.,'-]/g, "_"))}`, f,
        (done) => { note.textContent = `Uploading ${f.name}: ${Math.round(done * 100)}%`; });
      choose({ world: r.id, name: f.name.replace(/\.zip$/i, ""), version: null });
    } catch (e) { if (!(e instanceof Unauthorized)) { note.textContent = ""; toast(e.message, true); } }
  });
  const box = h("div", { class: "modal" },
    h("h2", { id: "pick-world-title" }, "Choose a world"),
    h("h3", {}, "Upload a world"),
    h("p", { class: "muted small" }, "A .zip of a world folder (the folder with level.dat in it). On Windows: right-click the folder → Send to → Compressed (zipped) folder."),
    h("div", { class: "row" }, h("button", { class: "btn", type: "button", onclick: () => picker.click() }, "Upload a .zip…"), picker), note,
    h("h3", { class: "mt" }, "Worlds on ", hubInfo && hubInfo.local ? "this computer" : "the server's computer"),
    list,
    h("div", { class: "row mt" }, h("button", { class: "btn ghost", type: "button", onclick: close }, "Cancel")));
  document.body.append(h("div", { class: "modal-backdrop", id: "pick-world", role: "dialog", "aria-modal": "true", "aria-labelledby": "pick-world-title" }, box));
  api("/api/hub/saves").then((r) => {
    fill(list, r.worlds.length ? h("ul", { class: "list worlds" }, r.worlds.map((w) => h("li", {},
      w.icon ? h("img", { src: w.icon, alt: "" }) : h("div", { class: "noicon" }),
      h("div", { class: "grow" }, h("strong", {}, w.name), w.hardcore ? h("span", { class: "tag bad" }, "hardcore") : null,
        h("div", { class: "small muted" }, [w.launcher, w.version ? `Minecraft ${w.version}` : null, `played ${fmtTime(w.played)}`].filter(Boolean).join(" · "))),
      h("button", { class: "btn small primary", type: "button", onclick: () => choose({ world: "save:" + w.id, name: w.name, version: w.version }) }, "Use"))))
      : h("p", { class: "empty" }, "No singleplayer worlds found. Upload one as a .zip instead."));
  }).catch((e) => fill(list, h("p", { class: "empty" }, e.message)));
}

// ------------------------------------------------------------ delete a server
function deleteServer(s, after) {
  if ($("#delete-server")) return;
  let everything = false;
  const box = h("div", { class: "modal compact" });
  const close = () => { const m = $("#delete-server"); if (m) m.remove(); };
  const render = (error) => {
    const typed = h("input", { autocomplete: "off", placeholder: s.name });
    const go = async (e) => {
      e.preventDefault();
      if (everything && typed.value.trim() !== s.name) return render(`Type the server's name, ${s.name}, to delete everything.`);
      try {
        const r = await api("/api/hub/delete", { method: "POST", body: { id: s.id, delete_files: everything } });
        close();
        toast(`${s.name}: ${r.message}`);
        if (after) after();
      } catch (err) { if (!(err instanceof Unauthorized)) render(err.message); }
    };
    const choice = (value, title, desc) => h("button", { type: "button", class: "choice" + (everything === value ? " selected" : "") + (value ? " danger" : ""),
      onclick: () => { everything = value; render(); } }, h("strong", {}, title), h("span", { class: "small muted" }, desc));
    fill(box,
      h("h2", { id: "delete-title" }, `Delete ${s.name}?`),
      s.state === "running" || s.state === "starting" ? h("div", { class: "notice warn" }, "Stop the server first.") : null,
      h("p", {}, "Would you also like to delete its world, mods and everything else that belongs to it?"),
      h("div", { class: "choices" },
        choice(false, "Keep the files", `Take it off the list; the world and mods stay in ${s.folder}.`),
        choice(true, "Delete everything", "The world, mods, backups and settings are erased. This can't be undone.")),
      h("form", { class: "mt", onsubmit: go },
        everything ? h("label", {}, `Type ${s.name} to confirm`, typed) : null,
        h("p", { class: "error" }, error || ""),
        h("div", { class: "row" },
          h("button", { class: "btn danger", type: "submit" }, everything ? "Delete everything" : "Remove from the list"),
          h("button", { class: "btn ghost", type: "button", onclick: close }, "Cancel"))));
    if (everything) typed.focus();
  };
  render();
  document.body.append(h("div", { class: "modal-backdrop", id: "delete-server", role: "dialog", "aria-modal": "true", "aria-labelledby": "delete-title" }, box));
}

// The home page: every server, each started and stopped by hand.
views.servers = () => {
  const list = h("div", { class: "server-list" });
  const busy = new Set();
  const control = async (s, action) => {
    if (action === "stop" && s.players && !(await ask(`Stop ${s.name}? ${s.players} player(s) will be disconnected.`, { id: "stop-server", ok: "Stop" }))) return;
    if (action === "start" && !(await memoryOkToStart(s.id, s.name))) return;
    busy.add(s.id);
    await act(() => api(`/api/servers/${s.id}/server/${action}`, { method: "POST" }),
      action === "start" ? `Starting ${s.name}…` : `Stopping ${s.name}…`);
    busy.delete(s.id);
  };
  const memLine = h("p", { class: "muted small" });
  let memAt = 0;
  const render = (hb) => {
    if (!hb) return;
    if (Date.now() - memAt > 15000) {  // (the memory given to the running servers; every 15 s is plenty)
      memAt = Date.now();
      api("/api/hub/memory").then((m) => { memLine.textContent = m.total_gb ? t("Memory given to the running servers: {used} GB of this computer's {total} GB.")
        .replace("{used}", m.running_gb).replace("{total}", m.total_gb) : ""; }).catch(() => null);
    }
    const label = (s) => s.state === "unavailable" ? "unavailable" : s.setup_pending ? "not set up" : s.state;
    fill(list,
      hb.servers.map((s) => h("div", { class: "card server-card" },
        h("div", { class: "row" },
          h("span", { class: "pill " + (s.setup_pending ? "pending" : s.state) }, label(s)),
          h("strong", { class: "grow server-name" }, s.name)),
        h("div", { class: "muted" }, s.problem || (s.minecraft ? `Minecraft ${s.minecraft} · ${s.loader}` : `${s.loader} · not installed yet`)),
        s.state === "unavailable" || s.setup_pending ? null
          : h("div", { class: "muted small" }, `${s.players} / ${s.max_players} players · port ${s.port}`, s.update ? " · update ready" : ""),
        s.job ? h("div", { class: "row small" }, h("span", { class: "spinner" }), `${s.job.name}…`) : null,
        s.state === "unavailable" ? null : h("div", { class: "row mt-s" },
          s.setup_pending ? h("a", { class: "btn primary", href: `#s/${s.id}/setup` }, s.job ? "See progress" : "Finish setup")
            : s.state === "stopped"
              ? h("button", { class: "btn primary", disabled: !!s.job || busy.has(s.id), onclick: () => control(s, "start") }, "Start")
              : h("button", { class: "btn danger", disabled: busy.has(s.id), onclick: () => control(s, "stop") }, "Stop"),
          s.setup_pending ? null : h("a", { class: "btn", href: `#s/${s.id}/dashboard` }, "Open"),
          !hb.single && !s.job ? h("button", { class: "btn ghost", onclick: () => deleteServer(s, refreshStatus) }, "Delete") : null),
        h("div", { class: "row" }, h("div", { class: "muted small folder grow" }, s.folder), folderBtn("server", "Folder", s.id)))),
      hb.single ? null : h("a", { class: "card server-card new", href: "#new" },
        h("strong", {}, "+ New server"), h("span", { class: "muted small" }, "Pick a server type, Minecraft version and mods")));
  };
  // Import a server exported on another computer (Settings → Export).
  const picker = h("input", { type: "file", accept: ".zip", class: "hidden" });
  const importNote = h("span", { class: "muted small" });
  const importBtn = h("button", { class: "btn", onclick: () => picker.click() }, "Import a server…");
  picker.addEventListener("change", async () => {
    const f = picker.files[0];
    picker.value = "";
    if (!f) return;
    importBtn.disabled = true;
    try {
      const staged = await upload(`/api/hub/stage?filename=${encodeURIComponent(f.name.replace(/[^A-Za-z0-9 ()\[\]+_.,'-]/g, "_"))}`, f,
        (done) => { importNote.textContent = `Uploading ${f.name}: ${Math.round(done * 100)}%`; });
      importNote.textContent = t("Unpacking…");
      const r = await api("/api/hub/import", { method: "POST", body: { id: staged.id } });
      toast("Imported. Press Start when you're ready.");
      await refreshStatus();
      location.hash = `#s/${r.id}/dashboard`;
    } catch (e) {
      if (!(e instanceof Unauthorized)) toast(e.message, true);
    } finally {
      importBtn.disabled = false;
      importNote.textContent = "";
    }
  });
  const sp = hubInfo && !hubInfo.single ? singleplayerCard() : null;
  fill($("#main"),
    closingTip(),
    h("div", { class: "row mb wrap" },
      h("p", { class: "muted grow" }, "Servers only run when you start them here, and stop when you press Stop or Quit Craft Conductor."),
      hubInfo && hubInfo.guide ? h("button", { class: "btn ghost", title: "Step by step from making a server to a friend joining it", onclick: startGuide }, "🧭 Guided setup") : null,
      hubInfo && hubInfo.single ? null : h("div", { class: "row" }, importNote, importBtn, picker)),
    memLine,
    list,
    sp ? sp.el : null);
  render(hubInfo);
  return { onHub: render };
};

// Modded single-player games: Craft Conductor sets one up in the launcher you use (it isn't a launcher) and
// keeps it up to date. The worlds stay in that installation when the mods are updated.
const SP_LOADERS = [["fabric", "Fabric"], ["neoforge", "NeoForge"], ["forge", "Forge"], ["quilt", "Quilt"]];
function singleplayerCard() {
  const list = h("div", { class: "sp-list" });
  const el = h("section", { class: "mt-l" },
    h("div", { class: "row" }, h("h2", { class: "grow" }, "Modded single-player games"),
      h("button", { class: "btn", onclick: () => openSpEditor(null, load) }, "+ New single-player game")),
    h("p", { class: "muted small" }, "Pick a mod loader and mods, and Craft Conductor puts the game into your launcher (the Minecraft Launcher, Prism, the Modrinth App or CurseForge) and keeps it up to date. No server needed; your worlds stay in the game when it's updated."),
    list);
  const LAUNCHER = { minecraft: "Minecraft Launcher", prism: "Prism", modrinth: "Modrinth App", curseforge: "CurseForge" };
  const gameCard = (g) => {
    const out = h("div", { class: "sp-check" });
    const inst = g.installed;
    const check = async () => {
      fill(out, h("div", { class: "row small" }, h("span", { class: "spinner" }), t("Checking Modrinth…")));
      const r = await api("/api/hub/singleplayer/check", { method: "POST", body: { id: g.id } }).catch((e) => { fill(out, h("div", { class: "notice bad small" }, e.message)); return null; });
      if (!r) return;
      fill(out, r.changes.length ? h("div", { class: inst ? "notice warn small" : "notice small" },
        h("strong", {}, inst ? "An update is ready:" : "It will install:"),
        h("ul", { class: "list" }, r.changes.map((c) => h("li", { class: c.startsWith("+") ? "change-add" : c.startsWith("−") ? "change-rm" : "" }, c))),
        r.skipped.length ? h("div", { class: "muted" }, t("Left out (no build for this Minecraft yet):") + " " + r.skipped.map((x) => x.name).join(", ")) : null,
        h("button", { class: "btn primary small mt-s", onclick: () => install() }, inst ? "Update it in my launcher" : "Put it in my launcher"))
        : h("div", { class: "notice ok small" }, `Up to date: Minecraft ${r.minecraft} and every mod are the newest that work together.`));
    };
    const install = async () => {
      const r = await api("/api/hub/singleplayer/install", { method: "POST", body: { id: g.id } }).catch((e) => { toast(e.message, true); return null; });
      if (r) toast("A new tab opens: pick your launcher there. (No tab? Allow pop-ups, or use the address it shows.)");
    };
    return h("div", { class: "card server-card" },
      h("div", { class: "row" }, h("span", { class: "pill " + (inst ? "running" : "pending") }, inst ? "installed" : "not installed"),
        h("strong", { class: "grow server-name" }, g.name)),
      h("div", { class: "muted" }, `${(SP_LOADERS.find(([v]) => v === g.loader) || [, g.loader])[1]} · Minecraft ${inst ? inst.minecraft : g.minecraft === "latest" ? t("newest the mods support") : g.minecraft} · ${g.mods.length} mod(s)`),
      inst ? h("div", { class: "muted small" }, t("In:") + " " + (g.launchers || []).map((x) => LAUNCHER[x] || x).join(", ") + ` · ${ago(inst.at)}`) : null,
      h("div", { class: "row mt-s" },
        h("button", { class: "btn primary", onclick: check }, inst ? "Check for updates" : "Install…"),
        h("button", { class: "btn", onclick: () => openSpEditor(g, load) }, "Edit"),
        h("button", { class: "btn ghost", onclick: async () => {
          if (!(await ask(`Forget "${g.name}"? Craft Conductor stops keeping it up to date. The game and its worlds stay in your launcher; delete them there if you want them gone.`, { ok: "Forget it", danger: true }))) return;
          await act(() => api("/api/hub/singleplayer/delete", { method: "POST", body: { id: g.id } }), "Forgotten");
          load();
        } }, "Delete")),
      out);
  };
  async function load() {
    const r = await api("/api/hub/singleplayer").catch(() => null);
    if (!r) return;
    fill(list, r.games.length ? h("div", { class: "server-list" }, r.games.map(gameCard))
      : h("p", { class: "empty" }, "No single-player games yet."));
  }
  load();
  return { el };
}

function openSpEditor(game, done) {
  const g = game || { name: "", loader: "fabric", minecraft: "latest", mods: [], memory_gb: 6 };
  const chosen = new Map(g.mods.map((slug) => [slug, slug]));
  const name = h("input", { value: g.name, maxlength: 60, placeholder: "e.g. Cozy modded survival" });
  const loader = h("select", { disabled: !!(game && game.installed) }, SP_LOADERS.map(([v, l]) => h("option", { value: v }, l)));
  loader.value = g.loader;
  const mc = h("select", {}, h("option", { value: "latest" }, "The newest one all the mods support"));
  api("/api/hub/setup").then((o) => { for (const v of o.versions || []) mc.append(h("option", { value: v }, `Minecraft ${v}`)); mc.value = g.minecraft; }).catch(() => null);
  const memory = h("select", {}, [2, 3, 4, 6, 8, 10, 12, 16].map((n) => h("option", { value: n }, `${n} GB`)));
  memory.value = String(g.memory_gb || 6);
  const q = h("input", { type: "search", placeholder: "Search Modrinth for mods…", "aria-label": "Search" });
  const results = h("div", { class: "browse-results sp-results" });
  const picked = h("div", { class: "sp-picked" });
  const showPicked = () => fill(picked, chosen.size ? [...chosen].map(([slug, label]) => h("span", { class: "tag sp-mod" }, label, " ",
    h("button", { type: "button", class: "link-btn", "aria-label": `Remove ${label}`, onclick: () => { chosen.delete(slug); showPicked(); } }, "×")))
    : h("span", { class: "muted small" }, "No mods yet: search above and press Add."));
  let seq = 0, timer;
  const search = async () => {
    const mine = ++seq;
    const params = new URLSearchParams({ type: "mod", q: q.value.trim(), source: "modrinth", sort: q.value.trim() ? "relevance" : "downloads",
      offset: "0", loader: loader.value, version: mc.value === "latest" ? "" : mc.value, side: "client" });
    const r = await api(`/api/hub/browse/search?${params}`).catch(() => null);
    if (!r || mine !== seq) return;
    fill(results, r.results.map((m) => h("div", { class: "result" },
      m.icon ? h("img", { src: m.icon, alt: "", loading: "lazy", referrerpolicy: "no-referrer" }) : h("div", { class: "noicon" }),
      h("div", { class: "info grow" }, h("div", { class: "name" }, m.name), h("div", { class: "desc" }, m.summary)),
      h("button", { type: "button", class: "btn small", disabled: chosen.has(m.slug || m.id), onclick: (e) => {
        chosen.set(m.slug || m.id, m.name); e.target.disabled = true; showPicked(); } }, chosen.has(m.slug || m.id) ? "Added" : "Add"))));
  };
  q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(search, 350); });
  loader.addEventListener("change", search);
  mc.addEventListener("change", search);
  const error = h("p", { class: "error" });
  const save = async (e) => {
    e.preventDefault();
    const body = { name: name.value.trim(), loader: loader.value, minecraft: mc.value, mods: [...chosen.keys()], memory_gb: Number(memory.value) };
    try {
      await api(game ? "/api/hub/singleplayer/edit" : "/api/hub/singleplayer", { method: "POST", body: game ? { id: game.id, ...body } : body });
      closeBrowser();
      toast(game ? "Saved. Check for updates to put the changes into your launcher." : "Made. Press Install… to put it into your launcher.");
      done();
    } catch (err) { if (!(err instanceof Unauthorized)) error.textContent = err.message; }
  };
  openSidePane(h("form", { class: "browse sp-editor", onsubmit: save },
    h("div", { class: "browse-left" },
      h("div", { class: "browse-filters" },
        h("div", { class: "row" }, h("strong", { class: "grow" }, game ? `Edit ${game.name}` : "New single-player game"),
          h("button", { type: "button", class: "btn ghost small", onclick: () => closeBrowser() }, "Close")),
        h("label", {}, "Name", name),
        h("div", { class: "grid" }, h("label", {}, "Mod loader", loader), h("label", {}, "Memory for the game", memory)),
        h("label", {}, "Minecraft", mc),
        h("h3", { class: "mt-s" }, "Mods"), picked, q),
      results,
      h("div", { class: "browse-footer" }, error, h("button", { class: "btn primary", type: "submit" }, game ? "Save" : "Make the game"))),
    h("div", { class: "browse-right" }, h("div", { class: "empty-map" },
      h("h2", {}, "Your own modded Minecraft"),
      h("p", {}, "Craft Conductor finds a build of every mod (and the mods they need) for the same Minecraft version, then sets the game up in your launcher. When the mods update, Check for updates brings them in; with “the newest one all the mods support”, Minecraft moves up too once every mod is ready."),
      h("p", { class: "muted small" }, "Only mods that run on players' computers are listed. Shaders and resource packs can be added on the launcher page when you install.")))),
    game ? "Edit single-player game" : "New single-player game");
  showPicked();
  search();
}

// A notice people see every time, once they know it: "Don't show again" (see Craft Conductor settings → Sounds & notifications → Warnings).
function dismissible(id, notice) {
  if (skippedWarnings().includes(id)) return null;
  notice.append(" ", h("button", { class: "link-btn small", onclick: () => { skipWarning(id); notice.remove(); } }, "Don't show again"));
  return notice;
}

// Closing the browser tab doesn't stop Craft Conductor (there's no window of its own to close): say so
// until the person says they've got it.
function closingTip() {
  if (skippedWarnings().includes("closing-tip")) return null;
  const tip = h("div", { class: "notice mb row" },
    h("span", { class: "grow" }, h("strong", {}, "Closing this tab doesn't stop Craft Conductor. "),
      "Your servers keep running and anything Craft Conductor is doing carries on. ",
      hubInfo && hubInfo.local ? "Open Craft Conductor again from its icon to come back here; " : "Open this page again to come back; ",
      "Quit (bottom left) stops everything."),
    h("button", { class: "btn small", onclick: () => { skipWarning("closing-tip"); tip.remove(); } }, "Got it"));
  return tip;
}

// Notifications from this browser while Craft Conductor's tab is in the background (a crash, an update,
// someone joining, a job that failed). Kept per browser; checks every 20 seconds while on.
const NOTIFY_KEY = "craft-conductor-notify";
const NOTIFY_KINDS = [["crash", "A server stops unexpectedly", true], ["update", "An update is ready", true],
  ["request", "A friend asks to be let in", true],
  ["join", "Someone joins a server", false], ["job", "Something Craft Conductor was doing fails", true]];
function notifyPrefs() { try { return JSON.parse(localStorage.getItem(NOTIFY_KEY) || "null"); } catch (_) { return null; } }
function saveNotifyPrefs(p) { try { localStorage.setItem(NOTIFY_KEY, JSON.stringify(p)); } catch (_) { /* private mode */ } }
let notifySeen = null;
async function notifyWatch() {
  const prefs = notifyPrefs();
  if (!prefs || !prefs.on || !("Notification" in window) || Notification.permission !== "granted") return;
  // (while the page shows, the status refresh has just fetched this; it pauses when hidden)
  const r = document.hidden || !hubInfo ? await api("/api/hub").catch(() => null) : hubInfo;
  if (!r || !r.servers) return;
  const now = new Map(r.servers.map((s) => [s.id, s]));
  if (notifySeen && document.hidden) {
    const say = (title, body) => { try { new Notification(title, { body, icon: "/icon.png", tag: `${title}|${body}` }); } catch (_) { /* not allowed */ } };
    for (const [id, s] of now) {
      const before = notifySeen.get(id);
      if (!before) continue;
      if (prefs.crash && s.crashed_at && s.crashed_at !== before.crashed_at) say(`${s.name} stopped unexpectedly`, "Craft Conductor restarts it if it can. Open Craft Conductor to see why.");
      if (prefs.update && s.update && !before.update) say(`Update ready for ${s.name}`, "Open Craft Conductor's Updates page to see it.");
      if (prefs.join && s.players > before.players) say(`Someone joined ${s.name}`, `${s.players} online now.`);
      if (prefs.request && (s.join_requests || 0) > (before.join_requests || 0)) say(`A friend asks to join ${s.name}`, "Allow them on the Players page.");
      const j = s.last_job, bj = before.last_job;
      if (prefs.job && j && j.ok === false && (!bj || bj.finished !== j.finished)) say(`${s.name}: ${j.name} failed`, j.message || "");
    }
  }
  notifySeen = now;
}
setInterval(notifyWatch, 20000);

function notificationsCard() {
  const box = h("div");
  const render = () => {
    const supported = "Notification" in window && window.isSecureContext;
    const prefs = notifyPrefs() || { on: false, ...Object.fromEntries(NOTIFY_KINDS.map(([k, , d]) => [k, d])) };
    const perm = supported ? Notification.permission : "unsupported";
    const on = h("input", { type: "checkbox", checked: !!prefs.on && perm === "granted", disabled: !supported || perm === "denied" });
    on.addEventListener("change", async () => {
      if (on.checked && Notification.permission !== "granted") {
        const answer = await Notification.requestPermission().catch(() => "denied");
        if (answer !== "granted") { toast("The browser didn't allow notifications for this page.", true); render(); return; }
      }
      saveNotifyPrefs({ ...prefs, on: on.checked });
      if (on.checked) { notifySeen = null; notifyWatch(); toast("Notifications on for this browser"); }
      render();
    });
    fill(box, card("Notifications",
      h("p", { class: "muted small" }, "Get a notification from this browser when something happens while Craft Conductor's tab is in the background."),
      !supported ? h("p", { class: "small" }, "This browser can't show notifications for this page (they need the address to be localhost, or HTTPS).")
        : perm === "denied" ? h("p", { class: "small bad-text" }, "Notifications are blocked for this page in the browser's site settings.") : null,
      h("label", { class: "row" }, on, h("span", {}, "Notify me in this browser")),
      prefs.on && perm === "granted" ? h("div", { class: "grid mt-s" }, NOTIFY_KINDS.map(([k, label]) => {
        const c = h("input", { type: "checkbox", checked: !!prefs[k] });
        c.addEventListener("change", () => saveNotifyPrefs({ ...(notifyPrefs() || prefs), [k]: c.checked }));
        return h("label", { class: "row" }, c, h("span", {}, label));
      })) : null));
  };
  render();
  return box;
}

// Questions answered with "Don't ask me again" (kept in this browser): bring them back here.
// The language of Craft Conductor's pages (this browser): automatic (the browser's) or one picked here.
// Automatic port forwarding (UPnP): Craft Conductor asks the router to forward its own ports to this
// computer, renews them while it runs and takes them back when switched off (or on quit).
function routerBox() {
  const box = h("div", { class: "mt" });
  const render = (st, busy = "") => {
    const on = h("input", { type: "checkbox", checked: !!st.enabled, disabled: !!busy, onchange: async () => {
      render({ ...st, enabled: on.checked }, on.checked ? "Asking your router…" : "Taking the ports back…");
      const r = await api("/api/hub/upnp", { method: "POST", body: { enabled: on.checked } }).catch((e) => { toast(e.message, true); return null; });
      render(r || st);
    } });
    const ports = (st.ports || []).map((p) => h("li", {}, p.ok ? "✓ " : "✗ ", h("strong", {}, `${p.protocol} ${p.port}`),
      h("span", { class: "muted" }, ` · ${p.label}`), p.ok ? null : h("span", { class: "bad-text" }, ` · ${p.error}`)));
    fill(box, h("h3", {}, "Router"),
      h("label", { class: "row check-row" }, on, h("span", {}, "Open the ports on my router by itself (UPnP)")),
      h("p", { class: "muted small" }, "Craft Conductor asks your router to forward each server's Minecraft port and the friends' download port to this computer, " +
        "and takes them back when you switch this off or quit Craft Conductor. Only Craft Conductor's own ports are opened. Many routers have UPnP switched off: " +
        "then forward the ports by hand (Help → Router setup), or use playit.gg."),
      busy ? h("p", { class: "small" }, busy) : null,
      !busy && st.enabled && st.error ? h("div", { class: "notice warn" }, h("strong", {}, "It didn't work: "), st.error, ".") : null,
      !busy && st.enabled && !st.error && st.router ? h("p", { class: "small ok-text" },
        `${st.router}${st.external_ip ? ` (internet address ${st.external_ip})` : ""}`) : null,
      !busy && st.warning ? h("div", { class: "notice warn" }, st.warning[0].toUpperCase() + st.warning.slice(1) + ".") : null,
      !busy && ports.length ? h("ul", { class: "list small" }, ports) : null,
      !busy && st.enabled ? h("button", { class: "btn small", onclick: async () => {
        render(st, "Asking your router…");
        render((await api("/api/hub/upnp", { method: "POST", body: {} }).catch(() => null)) || st);
      } }, "Check again") : null);
  };
  api("/api/hub/upnp").then((st) => render(st)).catch(() => null);
  return box;
}

// Size: automatic (bigger on big screens) or chosen, kept in this browser (see style.css).
const SIZE_KEY = "craft-conductor-size";
const SIZES = [["", "Automatic (bigger on big screens)"], ["smaller", "Smaller"], ["normal", "Normal"], ["larger", "Larger"], ["largest", "Largest"]];
function applySize() {
  let v = "";
  try { v = localStorage.getItem(SIZE_KEY) || ""; } catch (_) { /* private mode */ }
  if (SIZES.some(([k]) => k === v) && v) document.documentElement.dataset.size = v;
  else delete document.documentElement.dataset.size;
}
applySize();
// Display: size, contrast and motion, each kept in this browser (see style.css).
function displayCard() {
  const pick = (label, key, options, apply) => {
    const sel = h("select", {}, options.map(([v, l]) => h("option", { value: v }, l)));
    try { sel.value = localStorage.getItem(key) || ""; } catch (_) { /* private mode */ }
    sel.addEventListener("change", () => {
      try { if (sel.value) localStorage.setItem(key, sel.value); else localStorage.removeItem(key); } catch (_) { /* private mode */ }
      apply();
    });
    return h("label", {}, label, sel);
  };
  return card("Display",
    h("div", { class: "grid three" },
      pick("Size", SIZE_KEY, SIZES, applySize),
      pick("Contrast", CONTRAST_KEY, [["", "Automatic (this computer's setting)"], ["high", "High contrast"], ["normal", "Normal"]], applyDisplay),
      pick("Motion", MOTION_KEY, [["", "Automatic (this computer's setting)"], ["less", "Less motion"], ["normal", "Normal"]], applyDisplay)),
    h("p", { class: "muted small" }, "How big text and buttons are (Automatic makes everything bigger on big screens), stronger colours and outlines for easier reading, and fewer animations. Kept in this browser."));
}

// Mod conflict memory (conflicts.py): share what "Find which mods break it" finds, anonymously.
function conflictsCard() {
  const box = h("div", { class: "mb" });
  const render = (r) => {
    if (!r) { fill(box); return; }
    const on = h("input", { type: "checkbox", checked: r.enabled, disabled: !r.available, onchange: async () => {
      const res = await act(() => api("/api/hub/conflicts", { method: "POST", body: { enabled: on.checked } }), on.checked ? "Thank you: sharing is on" : "Sharing is off");
      if (res) render(res);
    } });
    fill(box, card("Mod conflicts",
      h("label", { class: "rule" }, on, " ", "Share mod conflicts anonymously"),
      h("p", { class: "muted small" }, "When \"Find which mods break it\" finds a mod that doesn't work, Craft Conductor sends only the mod loader, the Minecraft version and the mods' ids: nothing about you or your server. Once several people report the same conflict, everyone's Craft Conductor warns about it on the Mods page."),
      r.available ? null : h("p", { class: "small" }, "The shared list isn't available in this version yet. The warnings start once it is.")));
  };
  api("/api/hub/conflicts").then(render).catch(() => render(null));
  return box;
}

function soundsCard() {
  const p = soundPrefs();
  const save = () => saveSoundPrefs(p);
  const volume = h("select", { onchange: () => { p.volume = volume.value; save(); if (p.volume !== "off") playSound("go", true); } },
    [["off", "Off"], ["quiet", "Quiet"], ["normal", "Normal"]].map(([v, l]) => h("option", { value: v }, l)));
  volume.value = p.volume;
  const box = (key, label) => h("label", { class: "rule small" },
    h("input", { type: "checkbox", checked: !!p[key], onchange: (e) => { p[key] = e.target.checked; save(); if (e.target.checked && key !== "vibrate") playSound(key, true); } }), " ", label);
  return card("Sounds",
    h("div", { class: "row wrap" }, h("label", {}, "Volume", volume)),
    h("fieldset", { class: "mt-s choices" }, h("legend", { class: "small" }, "Play a sound for"), SOUND_KINDS.map(([k, l]) => box(k, l))),
    "vibrate" in navigator ? h("div", { class: "mt-s" }, box("vibrate", "Vibrate on button presses")) : null,
    h("p", { class: "muted small" }, "Short sounds, the same on the computer and the phone app. Kept on this device: each device has its own choice."));
}

function languageCard() {
  const sel = h("select", { "aria-label": "Language" }, h("option", { value: "" }, "Automatic (this browser's language)"),
    Object.entries(LANGS).map(([code, name]) => h("option", { value: code }, name)));
  sel.value = savedLanguage();
  sel.addEventListener("change", () => setLanguage(sel.value));
  return card("Language", h("div", { class: "row" }, sel),
    h("p", { class: "muted small" }, "Translations are machine-made and may have mistakes; the user manual is in English."));
}

function warningsCard() {
  const box = h("div");
  const render = () => {
    const n = skippedWarnings().length;
    fill(box, card("Warnings",
      h("p", { class: "muted small" }, n ? `You've hidden ${n} warning${n === 1 ? "" : "s"} (“Don't ask me again”, “Don't show again”, “Got it”) in this browser.`
        : "Warnings you see often (like “Stop the server?”) have a “Don't ask me again” box. None are hidden in this browser."),
      h("button", { class: "btn", disabled: !n, onclick: () => { showAllWarnings(); toast("You'll see every warning again"); render(); } }, "Show all warnings again")));
  };
  render();
  return box;
}

// Whitelist through Discord (discordbot.py): friends type /whitelist <their Minecraft name> in your
// Discord server. Ask me first (the Players page's requests) or Let them in (optionally only
// members with a role).
const DISCORD_STATE = { connected: "✓ Listening for /whitelist", starting: "Connecting to Discord…", retrying: "Reconnecting to Discord…", stopped: "Stopped" };
function discordWhitelistBox(r, after) {
  const w = r.whitelist;
  const mode = h("select", { "aria-label": "When someone asks" },
    h("option", { value: "ask" }, "Ask me first (they appear on the Players page)"),
    h("option", { value: "allow" }, "Let them in straight away"));
  mode.value = w.mode || "ask";
  const guild = h("select", { "aria-label": "Discord server for the role" }, h("option", { value: "" }, "Pick a Discord server…"));
  const role = h("select", { "aria-label": "Role" }, h("option", { value: "" }, "Anyone in the Discord server"));
  if (w.role) role.append(h("option", { value: w.role }, "The role you picked before"));
  role.value = w.role || "";
  const roleRow = h("div", { class: "row mt-s" + (mode.value === "allow" ? "" : " hidden") }, h("span", { class: "small" }, "Only members with this role:"), guild, role);
  mode.addEventListener("change", () => roleRow.classList.toggle("hidden", mode.value !== "allow"));
  guild.addEventListener("change", async () => {
    fill(role, h("option", { value: "" }, "Anyone in the Discord server"));
    if (!guild.value) return;
    const x = await api(`/api/hub/discord/roles?guild=${encodeURIComponent(guild.value)}`).catch((e) => { toast(e.message, true); return null; });
    if (x) role.append(...x.roles.map((y) => h("option", { value: y.id }, `@${y.name}`)));
  });
  api("/api/hub/discord/guilds").then((g) => guild.append(...g.guilds.map((x) => h("option", { value: x.id }, x.name)))).catch(() => {});
  const save = (enabled) => act(() => api("/api/hub/discord/whitelist", { method: "POST", body: { enabled, mode: mode.value, role: mode.value === "allow" ? role.value : "" } }),
    enabled ? "Whitelist through Discord is on" : "Whitelist through Discord is off").then(after);
  const st = w.status;
  return h("div", { class: "mt" }, h("h4", {}, "Whitelist through Discord"),
    h("p", { class: "muted small" }, "Friends type ", h("code", {}, "/whitelist"), " and their Minecraft name in your Discord server. Only they see the answer. The bot still never reads messages."),
    h("div", { class: "row" }, mode, w.enabled
      ? [h("button", { class: "btn small", onclick: () => save(true) }, "Save"), h("button", { class: "btn small ghost", onclick: () => save(false) }, "Turn off")]
      : h("button", { class: "btn small primary", onclick: () => save(true) }, "Turn on")),
    roleRow,
    w.enabled && st ? h("p", { class: `small ${st.state === "connected" ? "ok-text" : st.state === "stopped" ? "bad-text" : "muted"}` },
      t(DISCORD_STATE[st.state] || st.state), st.state === "connected" ? ` (${st.guilds} ${t("Discord server(s)")})` : "", st.error && st.state !== "connected" ? ` · ${st.error}` : "") : null,
    w.enabled ? h("p", { class: "muted small" }, "Don't see /whitelist in Discord? Add the bot again with “Add it to another Discord server” above (it now needs permission for commands), then restart Discord.") : null);
}

// A live status message in a Discord channel: each server's state, players and version, kept up
// to date by editing one message (the bot never reads the channel).
function discordStatusPicker(r, after) {
  const guild = h("select", { "aria-label": "Discord server" }, h("option", { value: "" }, "Pick a Discord server…"));
  const channel = h("select", { "aria-label": "Channel" }, h("option", { value: "" }, "…then a channel"));
  const loadChannels = async () => {
    fill(channel, h("option", { value: "" }, "…then a channel"));
    if (!guild.value) return;
    const c = await api(`/api/hub/discord/channels?guild=${encodeURIComponent(guild.value)}`).catch((e) => { toast(e.message, true); return null; });
    if (c) channel.append(...c.channels.map((x) => h("option", { value: x.id }, `#${x.name}`)));
  };
  guild.addEventListener("change", loadChannels);
  api("/api/hub/discord/guilds").then((g) => { guild.append(...g.guilds.map((x) => h("option", { value: x.id }, x.name))); }).catch(() => {});
  const set = (id) => act(() => api("/api/hub/discord/status", { method: "POST", body: { channel: id } }),
    id ? "The status message is posted there and kept up to date" : "Status message stopped").then(after);
  return h("div", { class: "mt" }, h("h4", {}, "Live status message"),
    h("p", { class: "muted small" }, "One message in a channel that always shows whether each server is online, who's playing and its Minecraft version. Craft Conductor edits it as things change, and says when Craft Conductor is closed."),
    r.status_channel ? h("div", { class: "row" }, h("span", { class: "grow small ok-text" }, "✓ On, in a channel you picked."),
      h("button", { class: "btn small ghost", onclick: () => set("") }, "Stop"))
      : h("div", { class: "row" }, guild, channel, h("button", { class: "btn small", onclick: () => channel.value ? set(channel.value) : toast("Pick a channel.", true) }, "Keep a status message there")));
}

// Craft Conductor itself: sign-in, network access, and what Craft Conductor is.
// ------------------------------------------------------------- the phone app
// Craft Conductor on a phone's home screen (an installable web app), with notifications when it's
// closed (push.py). Phones need a secure address for both: Tailscale gives one in a click.
let installPrompt = null;  // (Chrome and Edge offer "Install app" through this event)
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault(); installPrompt = e;
  const b = $("#phone-banner");  // (it can come after the phone banner was drawn: show its Install button)
  if (b) { b.remove(); phoneBanner(); }
  if ($("#pairing") && $("#pairing").dataset.getApp) showGetApp();
});
function registerWorker() {
  if (window.isSecureContext && "serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => null);
}
function b64uBytes(text) {
  const s = atob(text.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - text.length % 4) % 4));
  return Uint8Array.from(s, (c) => c.charCodeAt(0));
}
function deviceName() {
  const ua = navigator.userAgent;
  return /iPhone/.test(ua) ? "iPhone" : /iPad/.test(ua) ? "iPad" : /Android/.test(ua) ? (/Mobile/.test(ua) ? "Android phone" : "Android tablet")
    : /Windows/.test(ua) ? "Windows computer" : /Mac/.test(ua) ? "Mac" : /Linux/.test(ua) ? "Linux computer" : "A device";
}
// On a phone, a line at the top says how to get the app: why it's a browser tab on a plain address
// (phones only install web apps from a secure one), Install the app on a secure one, then
// notifications once it's installed. Paired phones can't open Craft Conductor settings, so this is
// how they get there. "Not now" hides it for two weeks.
const PHONE = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
const PHONE_BANNER_KEY = "craft-conductor-phone-banner";
async function phoneBanner() {
  if (!PHONE || $("#phone-banner")) return;
  const standalone = window.matchMedia && window.matchMedia("(display-mode: standalone)").matches;
  const secure = window.isSecureContext && "serviceWorker" in navigator;
  const pushOk = secure && "PushManager" in window && "Notification" in window;
  let subscribed = false;
  if (standalone && pushOk) {
    const reg = await navigator.serviceWorker.getRegistration().catch(() => null);
    subscribed = !!(reg && await reg.pushManager.getSubscription().catch(() => null));
    if (subscribed) return;
  }
  if (standalone && !pushOk) return;  // (an older phone that can't get notifications from web apps)
  const kind = !secure ? "plain" : standalone ? "notify" : "install";
  try { if (Number(localStorage.getItem(`${PHONE_BANNER_KEY}-${kind}`) || 0) > Date.now()) return; } catch (_) { /* private mode */ }
  const later = () => {
    try { localStorage.setItem(`${PHONE_BANNER_KEY}-${kind}`, String(Date.now() + 14 * 86400e3)); } catch (_) { /* private mode */ }
    box.remove();
  };
  const iOS = /iPhone|iPad|iPod/.test(navigator.userAgent);
  const box = h("div", { class: "notice phone-banner small", id: "phone-banner", role: "region", "aria-label": "Phone app" });
  const openSettings = () => {
    const close = () => { const m = $("#phone-dialog"); if (m) m.remove(); };
    document.body.append(h("div", { class: "modal-backdrop", id: "phone-dialog", role: "dialog", "aria-modal": "true", "aria-labelledby": "phone-dialog-title" },
      h("div", { class: "modal compact" }, h("div", { class: "row" }, h("h2", { id: "phone-dialog-title", class: "grow" }, "Phone app"),
        h("button", { class: "btn ghost small", onclick: close }, "Close")), phoneCard({ deviceOnly: true }))));
  };
  let secureUrl = null;
  if (kind === "plain") {
    const info = await api("/api/hub/phone?tailscale=1").catch(() => null);
    secureUrl = info && info.secure_url;
  }
  const notNow = h("button", { class: "btn small ghost", onclick: later }, "Not now");
  if (kind === "plain") fill(box, h("strong", {}, "This is Craft Conductor in your browser, not the app yet."), " ",
    t("Phones only install it as an app (with notifications, even when it's closed) from a secure address."), " ",
    secureUrl ? h("span", {}, t("Open the secure address with Tailscale on:"), " ", h("a", { href: secureUrl }, secureUrl))
      : t("On the computer, open Craft Conductor settings → Connections → Phone app → Use Tailscale for the phone app, then open the https://….ts.net address it shows here."),
    h("div", { class: "row mt-s" }, notNow));
  else if (kind === "install") fill(box, h("strong", {}, "Put Craft Conductor on your home screen."), " ",
    iOS ? t("Press Share, then Add to Home Screen, and open it from there. It signs in separately: with your password, or Pair with a code.")
      : installPrompt ? t("It opens like an app, and can tell you when a server needs you.")
        : t("In the browser's menu (⋮), choose Install app or Add to Home screen."),
    h("div", { class: "row mt-s" },
      installPrompt ? h("button", { class: "btn small primary", onclick: async () => { installPrompt.prompt(); installPrompt = null; box.remove(); } }, "Install the app") : null,
      h("button", { class: "btn small", onclick: openSettings }, "Notifications"), notNow));
  else fill(box, h("strong", {}, "Get a notification when a server needs you."), " ",
    t("A crash, a friend asking to join, an update held back: even when the app is closed."),
    h("div", { class: "row mt-s" }, h("button", { class: "btn small primary", onclick: openSettings }, "Turn on notifications"), notNow));
  $("#stage").before(box);
}
function phoneCard({ deviceOnly = false } = {}) {  // deviceOnly: just this phone (the phone banner's window)
  const body = h("div", {}, h("p", { class: "muted small" }, "Loading…"));
  const el = card(deviceOnly ? null : "Phone app", body);
  const secure = window.isSecureContext && "serviceWorker" in navigator;
  const pushOk = secure && "PushManager" in window && "Notification" in window;
  const standalone = window.matchMedia && window.matchMedia("(display-mode: standalone)").matches;
  const iOS = /iPhone|iPad/.test(navigator.userAgent);
  let info = null, mine = null, prefs = null, ts = null;
  const tsOut = h("div", { class: "mt-s" });
  const subscription = async () => {
    if (!pushOk) return null;
    const reg = await navigator.serviceWorker.getRegistration();
    return reg ? reg.pushManager.getSubscription() : null;
  };
  const load = async (checkTailscale = false) => {
    info = await api(`/api/hub/phone${checkTailscale ? "?tailscale=1" : ""}`).catch(() => null);
    if (info && info.tailscale) ts = info.tailscale;
    mine = await subscription().catch(() => null);
    prefs = mine ? await api("/api/hub/phone/prefs", { method: "POST", body: { endpoint: mine.endpoint } }).catch(() => null) : null;
    render();
  };
  const choices = () => {  // what this device hears about
    if (!mine || !prefs) return null;
    const save = async () => {
      const kinds = Object.keys(prefs.all).filter((k) => boxes[k].checked);
      const r = await api("/api/hub/phone/prefs", { method: "POST", body: { endpoint: mine.endpoint, kinds } }).catch((e) => { toast(e.message, true); return null; });
      if (r) { prefs = r; toast("Saved"); }
    };
    const boxes = {};
    return h("fieldset", { class: "mt-s choices" }, h("legend", { class: "small" }, "Notify this device about"),
      Object.entries(prefs.all).map(([k, label]) => h("label", { class: "rule small" },
        boxes[k] = h("input", { type: "checkbox", checked: prefs.kinds.includes(k), onchange: save }), " ", label)));
  };
  const enable = async () => {
    const perm = await Notification.requestPermission();
    if (perm !== "granted") { toast("Notifications are blocked for this site: allow them in the browser's settings, then try again.", true); return; }
    const reg = await navigator.serviceWorker.register("/sw.js");
    await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64uBytes(info.public_key) })
      .catch((e) => { toast(e.message, true); return null; });
    if (!sub) return;
    const j = sub.toJSON();
    const r = await api("/api/hub/phone/subscribe", { method: "POST", body: { endpoint: j.endpoint, keys: j.keys, name: deviceName() } })
      .catch((e) => { toast(e.message, true); return null; });
    if (r) toast("Notifications are on for this device");
    load();
  };
  const disable = async () => {
    const sub = await subscription();
    if (sub) {
      await api("/api/hub/phone/unsubscribe", { method: "POST", body: { endpoint: sub.endpoint } }).catch(() => null);
      await sub.unsubscribe().catch(() => null);
    }
    toast("Notifications are off for this device");
    load();
  };
  const test = async () => {
    const sub = await subscription();
    if (!sub) return;
    const r = await api("/api/hub/phone/test", { method: "POST", body: { endpoint: sub.endpoint } }).catch((e) => { toast(e.message, true); return null; });
    if (r) toast(r.ok ? "Sent: it should appear in a moment" : `It didn't go through: ${(r.results[0] || {}).error || "the push service said no"}`, !r.ok);
  };
  const useTailscale = async () => {
    const r = await api("/api/hub/phone/tailscale", { method: "POST", body: { on: true } }).catch((e) => { toast(e.message, true); return null; });
    if (!r) return;
    if (!r.ok) {
      fill(tsOut, h("div", { class: "notice warn small" }, r.message,
        r.enable_url ? h("div", {}, "Tailscale needs HTTPS switched on for your account first (one click): ",
          h("a", { href: r.enable_url, target: "_blank", rel: "noopener noreferrer" }, "switch it on ↗"), ", then press the button again.") : null));
      return;
    }
    toast("Done: your phone can open " + r.url);
    load(true);
  };
  const stopTailscale = async () => {
    await act(() => api("/api/hub/phone/tailscale", { method: "POST", body: { on: false } }), "Stopped");
    load(true);
  };
  const tailscaleBox = () => {
    if (!ts) return h("button", { class: "btn small", onclick: () => load(true) }, "Check for Tailscale");
    if (!ts.installed) return h("p", { class: "small" }, "Tailscale isn't on this computer. It's free for personal use: install it here and on your phone from ",
      h("a", { href: "https://tailscale.com/download", target: "_blank", rel: "noopener noreferrer" }, "tailscale.com/download ↗"),
      ", sign in to the same account on both, then ", h("button", { class: "link-btn", onclick: () => load(true) }, "check again"), ".");
    if (!ts.running || !ts.name) return h("p", { class: "small" }, "Tailscale is installed but isn't signed in and connected on this computer. Open it and sign in, then ",
      h("button", { class: "link-btn", onclick: () => load(true) }, "check again"), ".");
    if (ts.serving) return h("div", {},
      h("div", { class: "notice ok small" }, "Ready. On your phone (with Tailscale on), open ",
        h("a", { href: `https://${ts.name}/`, target: "_blank", rel: "noopener noreferrer" }, h("strong", {}, `https://${ts.name}`)),
        ". Sign in with your password, or pair the phone under Remote access & phones and pick the \"Tailscale, secure\" address."),
      h("button", { class: "btn small ghost mt-s", onclick: stopTailscale }, "Stop using Tailscale for this"));
    return h("div", {},
      h("p", { class: "small" }, `Tailscale is on (${ts.name}). Craft Conductor can use it to give this computer a secure address that only your own devices can reach.`),
      h("button", { class: "btn primary small", onclick: useTailscale }, "Use Tailscale for the phone app"), tsOut);
  };
  const render = () => {
    if (!info) { fill(body, h("p", { class: "muted small" }, "Couldn't load the phone app settings.")); return; }
    const here = !secure
      ? h("div", { class: "notice small" }, "This page isn't on a secure address, so this device can't install the app or get notifications here. Open Craft Conductor on your phone at a secure address (see below), and turn them on there.")
      : !pushOk
        ? h("div", { class: "notice small" }, iOS && !standalone
          ? "On iPhone and iPad, first add Craft Conductor to the Home Screen: press Share, then Add to Home Screen. Open it from there, and turn notifications on here."
          : "This browser can't get notifications from web apps.")
        : h("div", { class: "row wrap" },
          mine ? [h("span", { class: "ok-text small grow" }, "✓ Notifications are on for this device."),
            h("button", { class: "btn small", onclick: test }, "Send a test"),
            h("button", { class: "btn small ghost", onclick: disable }, "Turn off")]
            : [h("span", { class: "small grow" }, "Get a notification when a server crashes, a friend asks to join, an update is held back or it lags."),
              h("button", { class: "btn primary small", onclick: enable }, "Turn on notifications here")]);
    fill(body,
      h("p", { class: "muted small" }, "Craft Conductor can live on your phone's home screen like an app, and tell you when something needs you, even when it's closed."),
      h("h4", {}, "This device"), here, choices(),
      installPrompt && !standalone ? h("button", { class: "btn small mt-s", onclick: () => { installPrompt.prompt(); installPrompt = null; render(); } }, "Install the app") : null,
      info.devices.length && !deviceOnly ? h("div", { class: "mt-s" }, h("h4", {}, "Devices with notifications on"),
        h("ul", { class: "list" }, info.devices.map((d) => h("li", {}, h("span", { class: "grow" }, d.name, h("span", { class: "muted small" }, ` · since ${fmtTime(d.created)}`)),
          h("button", { class: "btn small ghost", onclick: async () => { await act(() => api("/api/hub/phone/remove", { method: "POST", body: { id: d.id } }), "Removed"); load(); } }, "Remove"))))) : null,
      deviceOnly ? null : [h("h4", { class: "mt" }, "Reach it from your phone, securely"),
      h("p", { class: "muted small" }, "Phones only install web apps and deliver their notifications for pages with a real certificate. The easy way is Tailscale: a private network of your own devices."),
      info.strong ? tailscaleBox() : h("div", { class: "notice warn small" }, "First set a strong password above: the phone signs in from another device."),
      h("details", { class: "mt-s small" }, h("summary", {}, "Put it on your phone"),
        h("ol", {},
          h("li", {}, "On the phone, open the secure address (with Tailscale on)."),
          h("li", {}, "iPhone or iPad: in Safari press Share → Add to Home Screen, then open Craft Conductor from the Home Screen. Android: in Chrome press ⋮ → Install app (or Add to Home screen)."),
          h("li", {}, "In the app, go to Craft Conductor settings → Connections → Phone app → Turn on notifications here."))),
      h("details", { class: "small" }, h("summary", {}, "Other ways to get a secure address"),
        h("p", {}, "A Cloudflare Tunnel, or your own domain with a reverse proxy (Caddy, nginx) that has a real certificate, works too: add its host name to [web] allowed_hosts, and keep a strong password, since that address is on the internet."))]);
  };
  load();
  return el;
}

views["craft-conductor"] = () => {
  const security = h("div", { class: "mb" });
  const network = h("div", { class: "mb" });
  const sharing = h("div", { class: "mb", id: "sharing" });
  let sharingDrawn = false;
  const renderSharing = (hb) => {
    if (!hb || hb.single || !hb.share) { fill(sharing); return; }
    if (sharingDrawn) return;  // don't wipe what's being typed on every refresh
    sharingDrawn = true;
    const s = hb.share;
    const address = h("input", { value: s.address, placeholder: s.lan_ip ? `automatic (${s.lan_ip} on your network)` : "automatic" });
    const port = h("input", { type: "number", min: 1024, max: 65535, value: s.port });
    const tunnelIn = h("input", { value: s.tunnel || "", placeholder: "e.g. name.gl.joinmc.link:12345 (optional)", class: "mono" });
    fill(sharing, card("Sharing with friends",
      h("p", { class: "muted small" }, "Used by servers whose friend download is switched on (see each server's Friends page)."),
      h("div", { class: "grid" },
        h("label", {}, "Your public address (host name or IP)", address,
          h("span", { class: "muted small" }, "What friends outside your home network use to reach you. Leave empty to use the address in the link they opened.")),
        h("label", {}, "Download port", port, h("span", { class: "muted small" }, "Forward this TCP port on your router, too."))),
      h("details", { class: "mt-s", open: !!s.tunnel }, h("summary", {}, "No port forwarding? Use playit.gg"),
        playitNote(),
        h("label", { class: "mt-s" }, "playit.gg tunnel for friends' downloads (a TCP tunnel to port " + s.port + ")", tunnelIn,
          h("span", { class: "muted small" }, "When set, internet invites use it instead of your public address. Each server's own Minecraft tunnel goes in its Settings."))),
      h("div", { class: "row mt-s" }, h("button", { class: "btn primary", onclick: async () => {
        const r = await act(() => api("/api/hub/share", { method: "POST", body: { address: address.value.trim(), port: Number(port.value), tunnel: tunnelIn.value.trim() } }), "Saved");
        if (r && r.share.error) toast(r.share.error, true);
      } }, "Save"),
      h("span", { class: "muted small" }, s.running ? `Sharing is on (port ${s.port}).` : s.error || "Sharing is off: no server has a friend download switched on.")),
      routerBox()));
  };
  const renderSecurity = (hb) => {
    const a = (hb && hb.auth) || {};
    const label = { password: "Password", pin: "PIN" }[a.mode] || "…";
    fill(security, card("Sign-in",
      h("div", { class: "row" },
        h("span", { class: "grow" }, a.managed ? "Password set in craft-conductor.toml ([web] password)" : a.default ? "Default password (PASSWORD) — please change it" : label),
        a.managed ? null : h("button", { class: "btn", onclick: () => showSecurity(false) }, "Change"))));
    if (!hb || hb.single) { fill(network); return; }
    fill(network, card("Remote access & phones",
      h("p", { class: "muted small" }, hb.network_access
        ? "Other devices can open this control panel (with your strong password), and paired phones get the everyday controls."
        : "Only this computer can open the control panel. Turn on remote access to use it from a phone or another computer."),
      h("div", { class: "row" }, h("button", { class: "btn", onclick: openRemoteAccess }, "🔒 Remote access & phones…")),
      h("p", { class: "muted small" }, `Servers are kept in ${hb.home}.`)));
  };
  const about = h("div", { class: "mt" });
  const loadAbout = async () => {
    const [n, lic] = await Promise.all([api("/api/notice").catch(() => null), api("/api/licenses").catch(() => null)]);
    if (!n || !lic) return;
    const s = hubInfo || {};
    const row = (x) => h("tr", {}, h("td", {}, x.name), h("td", {}, x.license), h("td", { class: "muted" }, x.use),
      h("td", {}, h("a", { href: x.url, target: "_blank", rel: "noopener noreferrer" }, "↗")));
    const table = (title, rows) => [h("h3", { class: "mt-l" }, title), h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "Name"), h("th", {}, "License"), h("th", {}, "Used for"), h("th", {}))),
      h("tbody", {}, rows.map(row)))];
    fill(about,
      card("About Craft Conductor",
        h("dl", { class: "kv" },
          h("dt", {}, "Version"), h("dd", {}, s.version || ""),
          h("dt", {}, "License"), h("dd", {}, h("a", { href: lic.project.url, target: "_blank", rel: "noopener noreferrer" }, lic.project.license))),
        h("div", { class: "row mt-s" },
          h("button", { class: "btn", onclick: async () => {
            try { localStorage.removeItem(DISMISS_KEY); } catch (_) {}
            closeToast("self-update");
            await act(() => api("/api/self-update/check", { method: "POST", body: {} }), "Checking for a new Craft Conductor version…");
          } }, "Check for Craft Conductor updates"), s.single ? null : folderBtn("home", "Craft Conductor folder", null, "btn"))),
      h("div", { class: "mt" }, card("What Craft Conductor does and doesn't do",
        h("ul", { class: "notice-points" }, n.points.map((p) => h("li", {}, p))))),
      h("div", { class: "mt" }, card("Open-source licenses",
        h("p", { class: "muted" }, "Craft Conductor has no third-party runtime dependencies, and the web UI uses no third-party code, fonts or images. Software it downloads for you is never bundled or redistributed by Craft Conductor."),
        table("Used by Craft Conductor", lic.runtime),
        table("Bundled into the downloadable executables", lic.bundled),
        table("Used only for development", lic.development),
        table("Downloaded for you", lic.downloaded),
        h("h3", { class: "mt-l" }, "Online services"),
        h("ul", { class: "list" }, lic.services.map((x) => h("li", {}, h("span", { class: "grow" }, x.name),
          x.url.startsWith("http") ? h("a", { href: x.url, target: "_blank", rel: "noopener noreferrer" }, "terms ↗") : h("span", { class: "muted small" }, x.url)))))),
    );
  };
  // CurseForge's API key (for CurseForge mods and searching CurseForge)
  const cf = h("div", { class: "mb" });
  const renderCf = async () => {
    if (hubInfo && hubInfo.single) return;
    const r = await api("/api/hub/curseforge").catch(() => null);
    if (!r) return;
    const input = h("input", { type: "password", placeholder: r.own ? "•••••••• (saved)" : "Paste your CurseForge API key", autocomplete: "off", "aria-label": "CurseForge API key" });
    const saveKey = (key, msg) => act(() => api("/api/hub/curseforge", { method: "POST", body: { key } }), msg).then(renderCf);
    fill(cf, card("CurseForge",
      h("p", { class: "muted small" }, "Needed to search CurseForge and to use CurseForge mods (Modrinth works without it). Get a free key at ",
        h("a", { href: "https://console.curseforge.com/", target: "_blank", rel: "noopener noreferrer" }, "console.curseforge.com ↗"), " → API keys."),
      h("div", { class: "row" }, input,
        h("button", { class: "btn primary", onclick: () => input.value.trim() && saveKey(input.value, "CurseForge key saved") }, r.own ? "Replace key" : "Save key"),
        r.own ? h("button", { class: "btn ghost", onclick: async () => (await ask("Remove the CurseForge key?", { ok: "Remove", danger: true })) && saveKey("", "CurseForge key removed") }, "Remove") : null),
      r.own ? h("p", { class: "small ok-text" }, "✓ Your own key is saved.")
        : r.builtin ? h("p", { class: "small ok-text" }, "✓ This version of Craft Conductor has CurseForge built in. You only need your own key if CurseForge starts refusing requests.")
        : null));
  };
  renderCf();
  // The Discord bot that posts invites (set up from a server's Friends page)
  const dc = h("div", { class: "mb" });
  const renderDc = async () => {
    if (hubInfo && hubInfo.single) return;
    const r = await api("/api/hub/discord").catch(() => null);
    if (!r) return;
    fill(dc, card("Discord",
      h("p", { class: "muted small" }, "Post your friends' invite to a Discord channel from a server's Friends page (“Post to Discord”)."),
      r.set ? h("div", { class: "row" }, h("span", { class: "grow small ok-text" }, `✓ Connected as ${r.bot ? r.bot.name : "your bot"}.`),
        r.invite_url ? h("a", { class: "btn small", href: r.invite_url, target: "_blank", rel: "noopener noreferrer" }, "Add it to another Discord server ↗") : null,
        h("button", { class: "btn ghost small", onclick: async () => (await ask("Disconnect the Discord bot? (It stays in your Discord servers until you remove it there.)", { ok: "Disconnect", danger: true })) &&
          act(() => api("/api/hub/discord", { method: "POST", body: { token: "" } }), "Discord bot disconnected").then(renderDc) }, "Disconnect"))
        : h("p", { class: "small" }, "Not set up. Use “Post to Discord” on a server's Friends page to connect a bot."),
      r.set ? discordStatusPicker(r, renderDc) : null,
      r.set && r.whitelist ? discordWhitelistBox(r, renderDc) : null));
  };
  renderDc();
  const phone = hubInfo && !hubInfo.single ? phoneCard() : null;
  const owner = !(hubInfo && hubInfo.role && hubInfo.role !== "owner");
  const sections = [
    ["Appearance", "Language, size, contrast and motion on this device.", languageCard(), displayCard()],
    ["Sounds & notifications", "Choose what you hear and which alerts you see.", soundsCard(), notificationsCard(), warningsCard()],
    ["Sign-in & security", "Manage how you and your devices sign in.", security, owner ? passkeyCard() : null],
    ["Connections", "Phones, sharing with friends and connected services.", network, phone, sharing, cf, dc,
      owner && hubInfo && !hubInfo.single ? conflictsCard() : null],
    ["About & updates", "Craft Conductor version, updates and licenses.", about],
  ];
  const panels = sections.map(([title, description, ...cards], i) => h("section", {
    id: `preferences-${i}`, class: "preferences-panel" + (i ? " hidden" : ""), "aria-labelledby": `preferences-button-${i}`,
  }, h("h3", {}, title), h("p", { class: "muted" }, description), ...cards.filter(Boolean)));
  const buttons = sections.map(([title], i) => h("button", { type: "button", id: `preferences-button-${i}`,
    class: "btn preferences-button", "aria-controls": `preferences-${i}`, "aria-pressed": String(i === 0), onclick: () => {
      panels.forEach((panel, n) => panel.classList.toggle("hidden", n !== i));
      buttons.forEach((button, n) => button.setAttribute("aria-pressed", String(n === i)));
    } }, title));
  fill($("#main"), h("h2", { class: "view-title" }, "Craft Conductor settings"),
    h("p", { class: "muted" }, "Choose a section to find the settings you need."),
    h("div", { class: "preferences-layout" }, h("nav", { class: "preferences-nav", "aria-label": "Settings sections" }, buttons),
      h("div", { class: "preferences-content" }, panels)));
  renderSecurity(hubInfo);
  renderSharing(hubInfo);
  loadAbout();
  return { onHub: (hb) => { renderSecurity(hb); renderSharing(hb); } };
};

// ------------------------------------------------------------------- setup
// Kept outside the view so choices survive re-renders and a failed attempt.
// The setup form's choices. One form at a time: `target` is what it's filling in ("new", or a
// server's id), and it starts fresh when that changes, so a new server never inherits the
// choices of the last one set up.
const freshSetup = () => ({ target: null, friends: false, loader: null, minecraft: "latest", mods: new Map(), motd: "A Minecraft server",
  properties: null, advancedOpen: false, max_players: 20, difficulty: "normal", gamemode: "survival", port: 25565, memory_gb: null,
  network_access: null, accept_eula: false, submitted: false, prefilled: false, modpack: null, localMods: [], world: null, showBetas: false,
  aikar: false, clientMods: new Map(), clientLocal: [], companionsSeen: new Set() });  // friends' download: slug -> name; staged files
const setupState = freshSetup();
function resetSetup() {
  const keep = { friendsFor: setupState.friendsFor };  // (a server just made with friends opens its Friends page when ready)
  for (const k of Object.keys(setupState)) delete setupState[k];
  Object.assign(setupState, freshSetup(), keep);
}

// A mod picked in setup brings the mods it needs along (marked "needed by ..."). Entries:
// key -> { name, required, explicit (picked by you), by: Set(keys of mods that need it), bad }.
// Removing a mod removes the dependencies nothing else needs; removing a dependency removes
// the mods that need it (after asking).
const setupModKey = (m) => (m.source === "curseforge" ? `curseforge:${m.id}` : m.slug || m.id);
function setupChanged() { if (setupState.onChange) setupState.onChange(); }
const earlyChannels = () => Object.fromEntries([...setupState.mods].filter(([, m]) => m.channel).map(([k, m]) => [k, m.channel]));
function setupModVersion() {
  const st = setupState;
  return st.minecraft === "latest" ? (st.newest || "") : st.minecraft;
}
// Mods with only alpha/beta builds for this version: shown on request, added after a warning.
const EARLY_WARNING = "Early builds (alpha and beta) are unfinished: they can crash the server, break other mods " +
  "or damage your world. Back up before you rely on them.";
const channelTag = (c) => (c && c !== "release" ? h("span", { class: "tag warn", title: EARLY_WARNING }, `${c} only`) : null);
async function confirmEarly(mods) {
  const early = mods.filter((m) => m.channel && m.channel !== "release");
  return !early.length || ask(`${early.map((m) => m.name).join(", ")} ${early.length === 1 ? "only has" : "only have"} ` +
    `alpha or beta builds for this Minecraft version.\n\n${EARLY_WARNING}\n\nAdd ${early.length === 1 ? "it" : "them"} anyway?`, { id: "early-builds", ok: "Add anyway" });
}
async function setupAddMod(key, name, channel = null) {
  const st = setupState;
  const e = st.mods.get(key);
  if (e) { e.explicit = true; if (channel && channel !== "release") e.channel = channel; }
  else st.mods.set(key, { name, required: true, explicit: true, by: new Set(), bad: "", channel: channel && channel !== "release" ? channel : null });
  setupChanged();
  await setupCheckMod(key);
}
async function setupCheckMod(key, quiet = false) {
  const st = setupState;
  const e = st.mods.get(key);
  if (!e || !st.loader || key.startsWith("curseforge:")) return;
  const v = setupModVersion();
  const url = `/api/hub/mods/requires?id=${encodeURIComponent(key)}&loader=${encodeURIComponent(st.loader)}` +
    (v ? `&version=${encodeURIComponent(v)}` : "");
  let r = await api(url + (e.channel ? `&channel=${e.channel}` : "")).catch((err) => {
    e.bad = `Couldn't check required mods: ${err.message}`; setupChanged(); return null;
  });
  if (!r || st.mods.get(key) !== e) return;
  if (!r.compatible && !quiet) {
    for (const channel of ["beta", "alpha"].filter((c) => c !== e.channel)) {
      const candidate = await api(url + `&channel=${channel}`).catch(() => null);
      if (st.mods.get(key) !== e || setupModVersion() !== v) return;
      if (!candidate || !candidate.compatible) continue;
      const needed = candidate.deps.filter((d) => d.channel && d.channel !== "release");
      if (await confirmEarly(needed.length ? needed : [{ name: e.name, channel }])) {
        e.channel = channel; r = candidate;
      }
      break;
    }
  }
  e.name = r.project.name;
  e.bad = r.compatible ? "" : r.reason;
  e.companions = r.companions || [];  // what players need on their computers for it
  if (!quiet) setupAnnounceCompanions();
  const added = [];
  for (const d of r.deps) {
    const dk = d.slug || d.id;
    if (!st.mods.has(dk)) { st.mods.set(dk, { name: d.name, required: e.required, explicit: false, by: new Set(), bad: "", channel: e.channel }); added.push(d); }
    const dep = st.mods.get(dk);
    dep.by.add(key);
    dep.bad = d.compatible ? "" : `No compatible build for Minecraft ${v}`;
    if (!dep.explicit) dep.channel = d.channel && d.channel !== "release" ? d.channel : e.channel;
  }
  if (added.length && !quiet) {
    toast(`Added ${added.map((d) => d.name).join(", ")} because ${added.length === 1 ? "it's" : "they're"} needed by ` +
      [...new Set(added.map((d) => d.needed_by))].join(" and ") + ".");
  }
  setupChanged();
}
// Mods the picked server mods need on players' computers: they go in the friends' download
// by themselves. Each one is announced once.
function setupCompanions() {
  const out = new Map();
  for (const m of setupState.mods.values()) for (const c of m.companions || []) {
    const k = c.slug || c.id;
    if (!out.has(k) && !setupState.mods.has(k)) out.set(k, { name: c.name, needed_by: c.needed_by });
  }
  return out;
}
function setupAnnounceCompanions() {
  const st = setupState;
  if (!st.friends) return;
  const byMod = new Map();
  for (const [k, c] of setupCompanions()) {
    if (st.companionsSeen.has(k)) continue;
    st.companionsSeen.add(k);
    byMod.set(c.needed_by, [...(byMod.get(c.needed_by) || []), c.name]);
  }
  for (const [by, names] of byMod) toast(`Added ${names.join(", ")} to your friends' download, because ${by} needs ${names.length === 1 ? "it" : "them"} on players' computers.`);
}
async function setupRemoveMod(key) {
  const st = setupState;
  const e = st.mods.get(key);
  if (!e) return;
  const needers = [...e.by].filter((k) => st.mods.has(k));
  if (needers.length && !(await ask(`${e.name} is needed by ${needers.map((k) => st.mods.get(k).name).join(", ")}. ` +
    `Remove ${needers.length === 1 ? "that" : "those"} too?`, { id: "remove-needed-mods", ok: "Remove them" }))) return;
  const stays = new Map();  // dependency name -> the mods that still need it
  const drop = (k) => {
    const x = st.mods.get(k);
    if (!x) return;
    st.mods.delete(k);
    stays.delete(x.name);
    for (const n of x.by) drop(n);  // what needs it goes with it
    for (const [ok, o] of [...st.mods]) {
      if (!o.by.delete(k)) continue;
      if (!o.explicit && o.by.size === 0) drop(ok);  // nothing needs it any more
      else if (!o.explicit) stays.set(o.name, [...o.by].map((b) => (st.mods.get(b) || {}).name).filter(Boolean));
    }
  };
  drop(key);
  for (const [name, needers] of stays) {
    if (needers.length) toast(`${name} stays: ${needers.join(" and ")} ${needers.length === 1 ? "needs" : "need"} it too.`);
  }
  setupChanged();
}
function setupRecheckMods() {
  // The Minecraft version or server type changed: dependencies and compatibility may differ.
  const st = setupState;
  for (const [k, e] of [...st.mods]) { if (!e.explicit) st.mods.delete(k); else e.by.clear(); }
  for (const k of st.mods.keys()) setupCheckMod(k, true);
}

// A failed job's message, with where its details were written (and a button to open that folder).
function failureText(message, sid) {
  const [what, where] = String(message || "").split("\nThe details are in ");
  if (!where) return what;
  return h("span", {}, what, h("div", { class: "small mt-s" }, "The details are in ", h("code", { class: "path" }, where),
    hubInfo && hubInfo.local && sid ? [" ", h("button", { type: "button", class: "link-btn", onclick: () =>
      api(`/api/servers/${sid}/open`, { method: "POST", body: { what: "reports" } }).catch((e) => toast(e.message, true)) }, "Open the folder")] : null));
}

// Aikar's flags: tuned garbage collection so big heaps don't cause lag spikes. Offered when a
// server gets more than 16 GB.
const AIKAR_ABOVE_GB = 16;
const memoryGb = (text) => { const m = /^(\d+)([MG])$/i.exec(String(text || "").trim()); return m ? Number(m[1]) / (m[2].toUpperCase() === "M" ? 1024 : 1) : 0; };
function offerAikar(gb, accept, decline = () => {}) {
  closeToast("aikar-offer");
  if (skippedWarnings().includes("aikar")) { decline(); return; }  // "No thanks, don't ask again"
  const again = h("input", { type: "checkbox" });
  stickyToast("aikar-offer", [
    h("strong", {}, `${gb} GB: use Aikar's flags?`),
    h("span", { class: "small" }, "With this much memory, Java's default garbage collection can pause the server for long enough to cause lag spikes. " +
      "Aikar's flags are widely used settings that keep those pauses short. Recommended."),
    h("div", { class: "row mt-s" },
      h("button", { class: "btn small primary", onclick: () => { closeToast("aikar-offer"); accept(); } }, "Use them"),
      h("button", { class: "btn small ghost", onclick: () => { if (again.checked) skipWarning("aikar"); closeToast("aikar-offer"); decline(); } }, "No thanks"),
      h("a", { class: "small", href: "https://docs.papermc.io/paper/aikars-flags", target: "_blank", rel: "noopener noreferrer" }, "What are they? ↗")),
    h("label", { class: "row small mt-s dont-ask" }, again, "Don't ask me again (No thanks)")]);
}

// A new server is ready: its dashboard, or the friends' invite when it was made with friends.
function setupFinished() {
  if (!location.hash.endsWith("/setup")) return;  // already on its way (status and job-done both call this)
  if (setupState.friendsFor !== server) { location.hash = link("dashboard"); return; }  // the job's toast says it's ready
  setupState.friendsFor = null;
  toast("Your server is ready. Here's your friends' invite.");
  location.hash = link("friends");
}

views.setup = () => {
  const main = h("div", { class: "setup" });
  let opts = null;
  const st = setupState;
  const isNew = !server;  // #new: a brand-new server; #s/<id>/setup: finish one that exists
  if (setupState.target !== (isNew ? "new" : server)) {  // another form than last time: start fresh
    resetSetup();
    setupState.target = isNew ? "new" : server;
  }
  // Choices made but not created yet (once it's creating, it carries on without this page).
  guardLeave(main, () => !st.submitted && !!(st.mods.size || st.modpack || st.localMods.length || st.world || st.clientMods.size));
  let propDefaults = {};

  const field = (label, input, hint) => h("label", {}, label, input, hint ? h("span", { class: "muted small" }, hint) : null);

  const renderForm = (error) => {
    const loaderCards = h("div", { class: "choices" }, opts.loaders.map((l) => h("button", {
      type: "button", class: "choice" + (st.loader === l.name ? " selected" : ""),
      "aria-pressed": String(st.loader === l.name), "aria-label": `${t(l.label)}: ${t(l.description)}`,
      disabled: !!st.modpack && st.loader !== l.name,
      onclick: () => { st.loader = l.name; if (!l.mods) { st.mods.clear(); st.localMods = []; } else setupRecheckMods(); renderForm(); },
    }, h("strong", {}, l.label), h("span", { class: "small muted" }, l.description))));
    const intro = [
      h("h2", { class: "view-title" }, isNew ? "Create a new server" : "Set up your server"),
      h("p", { class: "muted" }, "Choose what kind of server you want. Craft Conductor downloads everything it needs (Minecraft, the mod loader, mods and Java) and keeps it up to date from then on. " +
        (opts.network_option ? "" : "It won't start until you press Start.")),
      error ? h("div", { class: "notice bad" }, h("strong", {}, "Setup didn't finish: "), failureText(error, server),
        h("div", { class: "small mt-s" }, "Change your choices below and try again.")) : null,
    ];
    // Or on another computer: a Linux PC without a screen, installed over SSH.
    const elsewhere = isNew && !opts.network_option ? h("div", { class: "mt" }, card("Or on another computer",
      h("div", { class: "row" },
        h("span", { class: "grow small" }, "Run the server on a Linux PC without a screen on this network (a spare PC, a home server, a Raspberry Pi): Craft Conductor installs itself there over SSH."),
        h("button", { type: "button", class: "btn", onclick: openSshInstall }, "🐧 Install on a Linux computer…")))) : null;
    // Quick start: a ready-made starting point that fills the form in (everything stays changeable).
    const presetCards = isNew ? card("Quick start (optional)",
      h("p", { class: "muted small" }, "Pick a starting point and change anything afterwards, or choose each step yourself below."),
      h("div", { class: "choices presets" }, SETUP_PRESETS.map((p) => h("button", { type: "button", class: "choice", onclick: () => applyPreset(p, opts) },
        h("strong", {}, `${p.icon} `, p.name), h("span", { class: "small muted" }, p.desc))))) : null;
    if (!st.loader) {  // one step at a time: the rest depends on the server type
      fill(main, intro, presetCards ? h("div", { class: "mb" }, presetCards) : null, card("1. Server type", loaderCards,
        h("p", { class: "muted small mt-s" }, "Pick a server type to continue. Fabric, NeoForge, Forge and Quilt run mods; Vanilla is plain Minecraft.")),
        elsewhere);
      return;
    }

    const betas = opts.betas || [];
    const version = h("select", { onchange: (e) => { st.minecraft = e.target.value; setupRecheckMods(); renderForm(); } },
      h("option", { value: "latest" }, st.loader === "vanilla" ? "Newest release (recommended)" : "Newest version your mods support (recommended)"),
      st.showBetas && betas.length ? h("optgroup", { label: "Beta versions (for testing)" }, betas.map((v) => h("option", { value: v }, `Minecraft ${v} (beta)`))) : null,
      h("optgroup", { label: "Releases" }, opts.versions.map((v) => h("option", { value: v }, `Minecraft ${v}`))));
    const isBeta = betas.includes(st.minecraft);
    const betaToggle = betas.length ? h("label", { class: "row mt-s" },
      h("input", { type: "checkbox", checked: !!st.showBetas || isBeta, onchange: (e) => {
        st.showBetas = e.target.checked;
        if (!st.showBetas && betas.includes(st.minecraft)) st.minecraft = "latest";
        renderForm();
      } }),
      h("span", {}, "Show beta versions (snapshots and pre-releases of the next Minecraft)")) : null;
    const betaNote = isBeta ? h("div", { class: "notice warn mt-s" }, h("strong", {}, `Minecraft ${st.minecraft} is a beta. `),
      "It's for trying what's coming: things may break, a world opened in it can't go back to a release, and most mods " +
      "(and the NeoForge and Forge loaders) don't support betas yet. The server stays on this version until you change it in Settings. " +
      "To try a beta with an existing world, use \"Test a beta version\" on that server's Updates page instead: it works on a copy.") : null;
    if (st.modpack && ![...version.options].some((o) => o.value === st.minecraft)) version.append(h("option", { value: st.minecraft }, `Minecraft ${st.minecraft}`));
    version.value = st.minecraft;
    version.disabled = !!st.modpack;

    // Mods
    const selected = h("div");
    // Each picked mod, with the mods it needs listed under it.
    const modRows = () => {
      const rows = [];
      const shown = new Set();
      const row = (key, depth) => {
        const m = st.mods.get(key);
        if (!m || (depth === 0 && shown.has(key)) || depth > 6) return;  // (mods that need each other)
        shown.add(key);
        const needers = [...m.by].filter((k) => st.mods.has(k)).map((k) => st.mods.get(k).name);
        rows.push(h("li", { class: depth ? "dep" : null },
          h("div", { class: "grow" }, depth ? "↳ " : null, h("strong", {}, m.name), depth ? null : channelTag(m.channel),
            key.startsWith("curseforge:") ? h("span", { class: "tag" }, "CurseForge") : null,
            !m.explicit || needers.length ? h("span", { class: "tag" }, `needed by ${needers.join(", ")}`) : null,
            m.bad ? h("div", { class: "small bad-text" }, m.bad) : null),
          m.explicit ? h("label", { class: "row", title: "Every mod holds back Minecraft upgrades until it supports the new version. Required ones also decide the Minecraft version a new server starts on." },
            h("input", { type: "checkbox", checked: m.required, onchange: (e) => { m.required = e.target.checked; } }), "required") : null,
          h("button", { type: "button", class: "btn small danger", onclick: async () => { await setupRemoveMod(key); search(); } }, "Remove")));
        for (const [k, o] of st.mods) if (o.by.has(key) && !o.explicit) row(k, depth + 1);
      };
      for (const [k, m] of st.mods) if (m.explicit) row(k, 0);
      for (const k of st.mods.keys()) row(k, 0);  // anything left over
      return rows;
    };
    st.onChange = () => renderSelected();
    const renderSelected = () => fill(selected, st.mods.size || st.localMods.length ? h("ul", { class: "list" }, st.localMods.map((m) => h("li", {},
      h("div", { class: "grow" }, h("strong", {}, m.name), h("span", { class: "tag" }, "local file")),
      h("button", { type: "button", class: "btn small danger", onclick: () => { st.localMods = st.localMods.filter((x) => x !== m); renderSelected(); } }, "Remove"))),
      modRows())
      : h("p", { class: "empty" }, st.modpack ? "No extra mods. The modpack's own mods are added when the server is created."
        : "Nothing yet. Download mods or add files from this computer above, or leave it empty for an unmodded server."));
    const loaderLabel = (opts.loaders.find((l) => l.name === st.loader) || {}).label || st.loader;
    const plugins = runsPlugins(st.loader);
    renderSelected();
    // Three ways to add mods: files on this computer, the mod browser window, or a whole modpack.
    const picker = h("input", { type: "file", multiple: true, accept: ".jar", class: "hidden" });
    picker.addEventListener("change", async () => {
      for (const f of [...picker.files]) {
        const r = await api(`/api/hub/stage?filename=${encodeURIComponent(f.name)}`, { method: "POST", raw: f })
          .catch((e) => { toast(`${f.name}: ${e.message}`, true); return null; });
        if (r) st.localMods.push({ id: r.id, name: f.name });
      }
      picker.value = "";
      renderSelected();
    });
    const sources = h("div", { class: "source-buttons" },
      h("button", { type: "button", class: "btn", onclick: () => picker.click() }, "📁 Local files",
        h("span", { class: "small muted" }, ".jar files on this computer")),
      h("button", { type: "button", class: "btn", onclick: () => openBrowser({ type: "mod", target: "setup", loader: st.loader, version: setupModVersion() }) },
        plugins ? "🔎 Download plugins" : "🔎 Download mods", h("span", { class: "small muted" }, plugins ? "Browse Modrinth and Hangar" : "Browse Modrinth and CurseForge")),
      plugins ? null : h("button", { type: "button", class: "btn", onclick: () => openBrowser({ type: "modpack", target: "setup", loader: st.modpack ? "" : st.loader }) },
        "📦 Modpacks", h("span", { class: "small muted" }, "A ready-made pack of mods")),
      picker);
    const packCard = st.modpack ? h("div", { class: "notice mt-s pack" },
      st.modpack.icon ? h("img", { src: st.modpack.icon, alt: "", referrerpolicy: "no-referrer" }) : null,
      h("div", { class: "grow" }, h("strong", {}, st.modpack.name), " ", h("span", { class: "tag" }, st.modpack.version || ""),
        h("div", { class: "small muted" }, `Minecraft ${st.minecraft}, ${loaderLabel}. The pack decides the version and server type; its mods are installed and kept up to date.`)),
      h("button", { type: "button", class: "btn small danger", onclick: () => { st.modpack = null; st.minecraft = "latest"; renderForm(); } }, "Remove modpack")) : null;
    const modsCard = st.loader && opts.loaders.find((l) => l.name === st.loader).mods ? card(plugins ? "3. Plugins" : "3. Mods",
      sources, packCard, h("h3", { class: "mt" }, plugins ? "Your plugins" : "Your mods"), selected,
      h("div", { class: "row mt-s" }, testButton({
        check: ["/api/hub/mods/check", { loader: st.loader, minecraft: setupModVersion(),
          mods: [...st.mods].filter(([k, m]) => m.explicit && !k.startsWith("curseforge:")).map(([k]) => k), channels: earlyChannels() }],
        trial: { loader: st.loader, minecraft: st.minecraft, mods: [...st.mods].filter(([, m]) => m.explicit).map(([k]) => k), channels: earlyChannels() },
        keepWorking: async (res) => { for (const o of res.outliers) await setupRemoveMod(o.source === "curseforge" ? `curseforge:${o.id}` : o.id); },
      }), h("span", { class: "muted small" }, "Check that these mods work together before creating the server.")),
      st.loader === "fabric" || st.loader === "quilt" ? h("p", { class: "muted small" }, "Fabric API is added automatically, since almost every Fabric mod needs it.") : null,
      plugins ? h("p", { class: "muted small" }, "Paper and Purpur run server plugins (Paper, Spigot and Bukkit ones) from their plugins folder. Players join with plain Minecraft: plugins don't need anything on their side.") : null) : null;

    // Settings
    const inp = (key, attrs = {}) => h("input", { value: st[key], ...attrs, oninput: (e) => { st[key] = attrs.type === "number" ? Number(e.target.value) : e.target.value; } });
    const sel = (key, choices) => { const el = h("select", { onchange: (e) => { st[key] = e.target.value; } }, choices.map((c) => h("option", { value: c }, c[0].toUpperCase() + c.slice(1)))); el.value = st[key]; return el; };
    const ram = opts.total_ram_gb || 0;
    const mem = h("select", { onchange: (e) => {
      st.memory_gb = Number(e.target.value);
      if (st.memory_gb > AIKAR_ABOVE_GB && !st.aikar) offerAikar(st.memory_gb, () => { st.aikar = true; renderForm(); }, () => { st.aikar = false; });
      renderForm();
    } },
      Array.from({ length: 32 }, (_, i) => i + 1).map((g) => h("option", { value: String(g) },
        `${g} GB${g === opts.memory_gb ? " (suggested)" : ""}${ram && g > ram ? " (more than this computer has)" : ""}`)));
    mem.value = String(st.memory_gb);

    // The Minecraft port, checked as you type: other servers here, Craft Conductor itself, other programs.
    const portField = () => {
      const note = h("span", { class: "muted small" }, "25565 is Minecraft's usual port. Friends type the address as host:port when it's not 25565.");
      const input = h("input", { type: "number", min: 1024, max: 65535, value: st.port });
      let timer;
      const check = async () => {
        const port = Number(input.value);
        if (!Number.isInteger(port) || port < 1024 || port > 65535) { note.className = "small bad-text"; note.textContent = t("Pick a number between 1024 and 65535."); return; }
        if (opts.network_option) return;  // `craft-conductor run`: a single server, nothing to compare with
        const r = await api(`/api/hub/port?port=${port}${isNew ? "" : "&exclude=" + encodeURIComponent(server)}`).catch(() => null);
        if (!r || Number(input.value) !== port) return;
        if (r.used_by) { note.className = "small bad-text"; note.textContent = `Already used by ${r.used_by}. Try ${r.suggestion}.`; }
        else if (r["craft-conductor"]) { note.className = "small bad-text"; note.textContent = `craft-conductor itself uses this port. Try ${r.suggestion}.`; }
        else if (r.busy) { note.className = "small warn-text"; note.textContent = `Another program on this computer is using port ${port}; the server won't start until it's free. Try ${r.suggestion}.`; }
        else { note.className = "small ok-text"; note.textContent = `Port ${port} is free.` + (port === 25565 ? "" : " Friends connect with your address followed by :" + port + "."); }
      };
      input.addEventListener("input", () => { st.port = Number(input.value); clearTimeout(timer); timer = setTimeout(check, 300); });
      check();
      return field("Port (players connect to this)", input, note);
    };

    // World: a new one (seed, type, structures, hardcore) or one you already have.
    const P = st.properties;
    const worldTypes = WORLD_TYPES;
    const seed = h("input", { value: P["level-seed"] || "", maxlength: 64, placeholder: "Random",
      oninput: (e) => { P["level-seed"] = e.target.value; } });
    const flag = (key, text) => h("label", { class: "row" }, h("input", { type: "checkbox", checked: P[key] === "true",
      onchange: (e) => { P[key] = String(e.target.checked); } }), h("span", {}, text));
    const hasMods = !!(st.loader && opts.loaders.find((l) => l.name === st.loader).mods);
    const worldCard = card(hasMods ? "4. World" : "3. World",
      h("div", { class: "choices two" },
        h("button", { type: "button", class: "choice" + (st.world ? "" : " selected"), onclick: () => { st.world = null; renderForm(); } },
          h("strong", {}, "New world"), h("span", { class: "small muted" }, "Minecraft makes a fresh world the first time the server starts.")),
        h("button", { type: "button", class: "choice" + (st.world ? " selected" : ""), onclick: () => pickWorld((w) => { st.world = w; renderForm(); }) },
          h("strong", {}, "Import a world"), h("span", { class: "small muted" }, "Bring a singleplayer world or a world .zip, from any version of Minecraft Java."))),
      st.world ? h("div", { class: "notice mt-s" }, h("strong", {}, st.world.name),
        st.world.version ? h("span", { class: "muted" }, ` · last played on Minecraft ${st.world.version}`) : null,
        h("div", { class: "small muted" }, "Minecraft upgrades an older world when the server first starts; a world can't go back to an older version, " +
          "and blocks from mods the server doesn't have are lost."),
        h("div", { class: "row mt-s" }, h("button", { type: "button", class: "btn small", onclick: () => pickWorld((w) => { st.world = w; renderForm(); }) }, "Choose another"),
          h("button", { type: "button", class: "btn small ghost", onclick: () => { st.world = null; renderForm(); } }, "Use a new world instead")))
      : h("div", { class: "mt-s" },
        h("div", { class: "grid" }, field("Seed", seed, "A number or any text. The same seed makes the same world.")),
        h("h3", { class: "mt-s" }, "World type"),
        h("div", { class: "choices world-types" }, worldTypes.map(([v, label, desc]) => h("button", { type: "button",
          class: "choice" + ((P["level-type"] || "minecraft:normal") === v ? " selected" : ""),
          "aria-pressed": String((P["level-type"] || "minecraft:normal") === v),
          onclick: () => { P["level-type"] = v; renderForm(); } }, h("strong", {}, label), h("span", { class: "small muted" }, desc)))),
        h("div", { class: "grid mt-s" }, flag("generate-structures", "Villages, temples and other structures"),
          flag("hardcore", "Hardcore: one life, locked to hard")),
        st.modpack ? null : h("div", { class: "source-buttons mt-s" },
          h("button", { type: "button", class: "btn", onclick: () => openWorldPanel() }, "🗺️ World generation & map preview",
            h("span", { class: "small muted" }, "Mods that change how the world is made, and a map of your seed before you create the server"))),
        st.previews && st.previews.length && st.previews.some((m) => m.seed === (P["level-seed"] || "")) ?
          h("p", { class: "muted small" }, "✓ You've seen this seed's map.") : null));

    const eula = h("input", { type: "checkbox", checked: st.accept_eula, onchange: (e) => { st.accept_eula = e.target.checked; } });
    const lan = h("input", { type: "checkbox", checked: st.network_access, onchange: (e) => { st.network_access = e.target.checked; } });

    const submit = async (e) => {
      e.preventDefault();
      if (!st.accept_eula) { toast("Please read and accept the Minecraft EULA first.", true); return; }
      // Only the mods you picked: their dependencies are installed with them (and go with them).
      const bad = [...st.mods.values()].filter((m) => m.bad);
      if (bad.length && !(await ask(`${bad.map((m) => `${m.name}: ${m.bad}`).join("\n")}\n\nCreate the server anyway?`, { ok: "Create anyway" }))) return;
      const mods = [...st.mods].filter(([, m]) => m.explicit && m.required).map(([slug]) => slug);
      const optional = [...st.mods].filter(([, m]) => m.explicit && !m.required).map(([slug]) => slug);
      const body = { loader: st.loader, minecraft: st.minecraft, mods, optional_mods: optional, memory_gb: st.memory_gb,
        aikar_flags: !!st.aikar && st.memory_gb > AIKAR_ABOVE_GB,
        motd: st.motd, max_players: st.max_players, difficulty: st.difficulty, gamemode: st.gamemode, port: st.port,
        network_access: st.network_access, accept_eula: true, properties: changedProps(st.properties, propDefaults),
        friends: !!st.friends, local_mods: st.localMods.map((m) => m.id), world: st.world ? st.world.world : "",
        client_mods: st.friends ? [...st.clientMods.keys()] : [], client_local: st.friends ? st.clientLocal.map((m) => m.id) : [],
        mod_channels: Object.fromEntries([...st.mods].filter(([, m]) => m.explicit && m.channel).map(([k, m]) => [k, m.channel])) };
      if (st.modpack) body.modpack_version = st.modpack.version_id;
      if (isNew) {
        const r = await act(() => api("/api/hub/create", { method: "POST", body }));
        if (r) {
          setupState.friendsFor = body.friends || body.client_mods.length || body.client_local.length ? r.id : null;
          resetSetup();
          location.hash = `#s/${r.id}/setup`;
        }
        return;
      }
      const r = await act(() => api("/api/setup", { method: "POST", body }));
      if (r) { st.submitted = true; renderProgress(); }
    };

    // Friends: a download that sets up their Minecraft. "Set up now" opens the mod browser for
    // players' mods (client-side ones only); the server's mods and what they need on players'
    // computers come along by themselves.
    const friendsCard = () => {
      const moddable = hasMods && !plugins;
      const friendPicker = h("input", { type: "file", multiple: true, accept: ".jar", class: "hidden" });
      friendPicker.addEventListener("change", async () => {
        for (const f of [...friendPicker.files]) {
          const r = await api(`/api/hub/stage?filename=${encodeURIComponent(f.name)}`, { method: "POST", raw: f })
            .catch((e) => { toast(`${f.name}: ${e.message}`, true); return null; });
          if (r) st.clientLocal.push({ id: r.id, name: f.name });
        }
        friendPicker.value = "";
        st.friends = true;
        renderForm();
      });
      const companions = setupCompanions();
      const list = st.clientMods.size || st.clientLocal.length || companions.size ? h("ul", { class: "list" },
        [...st.clientMods].map(([k, name]) => h("li", {}, h("strong", { class: "grow" }, name), h("span", { class: "tag" }, "players only"),
          h("button", { type: "button", class: "btn small danger", onclick: () => { st.clientMods.delete(k); renderForm(); } }, "Remove"))),
        st.clientLocal.map((m) => h("li", {}, h("div", { class: "grow" }, h("strong", {}, m.name), h("span", { class: "tag" }, "local file")),
          h("button", { type: "button", class: "btn small danger", onclick: () => { st.clientLocal = st.clientLocal.filter((x) => x !== m); renderForm(); } }, "Remove"))),
        [...companions.values()].map((c) => h("li", { class: "dep" }, h("div", { class: "grow" }, "↳ ", h("strong", {}, c.name),
          h("span", { class: "tag" }, `added automatically: ${c.needed_by} needs it`)))))
        : h("p", { class: "empty" }, "No extra mods for players yet. Friends get the server's mods either way.");
      return card("Friends (optional)",
        h("label", { class: "row check-row" },
          h("input", { type: "checkbox", checked: st.friends, onchange: (e) => { st.friends = e.target.checked; if (st.friends) setupAnnounceCompanions(); renderForm(); } }),
          h("span", {}, "Make a download for my friends: it sets up their Minecraft with this server's version and mods, and adds the server to their list")),
        moddable ? h("div", { class: "source-buttons mt-s" },
          h("button", { type: "button", class: "btn", onclick: () => {
            if (!st.friends) { st.friends = true; setupAnnounceCompanions(); renderForm(); }
            openBrowser({ type: "mod", target: "setup", side: "client", loader: st.loader, version: setupModVersion() });
          } }, "🔎 Set up now", h("span", { class: "small muted" }, "Pick mods for your friends' Minecraft (a minimap, JEI, …)")),
          h("button", { type: "button", class: "btn", onclick: () => friendPicker.click() }, "📁 Local files",
            h("span", { class: "small muted" }, ".jar files on this computer, for players")),
          friendPicker) : null,
        moddable && st.friends ? [h("h3", { class: "mt" }, "Your friends' mods"), list,
          h("p", { class: "muted small" }, "Friends also get the server's mods that players need; server-only mods are left out.")] : null,
        !moddable ? h("p", { class: "muted small" }, plugins ? "Plugins run on the server only: friends join with plain Minecraft." : "Friends join with plain Minecraft.") : null,
        h("p", { class: "muted small" }, "You get a link to share on the server's Friends page. You can change all this later there."));
    };

    const advanced = h("details", { class: "card advanced", open: st.advancedOpen },
      h("summary", {}, "Advanced settings (optional)"),
      h("p", { class: "muted small" }, "The rest of Minecraft's server settings: PvP, spawn protection, view distance and more. The defaults suit most servers, and you can change these later in the server's Settings."),
      // The World card above covers the seed, type, structures and hardcore.
      propsEditor(opts.properties_schema.filter((p) => !WORLD_CARD_PROPS.includes(p.key)), st.properties));
    advanced.addEventListener("toggle", () => { st.advancedOpen = advanced.open; });

    fill(main, intro,
      h("form", { onsubmit: submit },
        card("1. Server type", loaderCards),
        h("div", { class: "mt" }, card("2. Minecraft version", field("Version", version,
          "\"Newest\" picks the newest Minecraft your mods work on, and upgrades only once every mod supports the next version: a forever server. " +
          "Picking a specific version keeps the server on that version (mods still update); you can change this later in Settings."),
          betaToggle, betaNote)),
        modsCard ? h("div", { class: "mt" }, modsCard) : null,
        h("div", { class: "mt" }, worldCard),
        h("div", { class: "mt" }, card(modsCard ? "5. Settings" : "4. Settings",
          h("div", { class: "grid" },
            field("Server name (shown in the server list)", inp("motd", { maxlength: 59 })),
            field("Max players", inp("max_players", { type: "number", min: 1, max: 1000 })),
            field("Difficulty", sel("difficulty", opts.difficulties)),
            field("Game mode", sel("gamemode", opts.gamemodes)),
            field("Memory", mem, [ram ? (st.memory_gb > ram - 2 ? `This computer has ${ram} GB. Leave some for Windows and other programs, or the server may crash.` : `This computer has ${ram} GB.`) : "",
              st.aikar && st.memory_gb > AIKAR_ABOVE_GB ? " Aikar's flags: on (smoother garbage collection)." : ""].join("") || null),
            portField()),
          opts.network_option ? h("label", { class: "row mt" }, lan, h("span", {}, "Let other devices on my network (like my phone) open this control panel")) : null,
          opts.network_option ? null : h("div", { class: "row mt" },
            h("button", { type: "button", class: "btn", onclick: openRemoteAccess }, "🔒 Remote access…"),
            h("span", { class: "muted small" }, "Manage your servers from your phone or another computer (needs a strong password).")))),
        h("div", { class: "mt" }, advanced),
        elsewhere,
        opts.network_option ? null : h("div", { class: "mt" }, friendsCard()),
        h("div", { class: "mt" }, card("Almost done",
          h("label", { class: "row" }, eula, h("span", {}, "I accept the ",
            h("a", { href: "https://aka.ms/MinecraftEULA", target: "_blank", rel: "noopener noreferrer" }, "Minecraft EULA ↗"),
            ", which every Minecraft server must follow.")),
          h("p", { class: "muted small" }, `Your server will be created in ${opts.server_dir}`),
          h("button", { type: "submit", class: "btn primary big" }, "Create my server")))));
  };

  const renderProgress = () => {
    const events = h("div", { class: "events" });
    let seq = 0;
    const panel = h("div", { class: "progress-panel" },
      h("h2", { class: "view-title" }, "Creating your server…"),
      h("div", { class: "notice" }, h("div", { class: "row" }, h("span", { class: "spinner" }),
        h("span", { class: "grow" }, "Downloading Java, the mod loader, Minecraft and your mods, then checking that the server starts. This usually takes a few minutes.")),
        h("div", { class: "small muted mt-s" }, "You can close this page: Craft Conductor keeps going. Open Craft Conductor again and choose See progress on the server.")),
      card("What's happening", events),
      // While it installs: what friends outside your home will need (the lower part of the screen).
      h("details", { class: "card mt router-help", open: true }, h("summary", {}, h("strong", {}, "While you wait: letting friends outside your home join")),
        routerHelp({ port: (status && status.port) || st.port })));
    fill(main, panel);
    let startedAt = null;  // only this setup's events, not an earlier attempt's
    every(1500, async () => {
      if (!events.isConnected && seq) return;  // slid away (or shown again in a newer panel)
      if (startedAt === null) {
        const s = await api("/api/status").catch(() => null);
        if (!s) return;
        startedAt = s.job && s.job.started ? s.job.started - 1 : Date.now() / 1000 - 5;
      }
      const r = await api(`/api/events?since=${seq}`).catch(() => null);
      if (!r) return;
      seq = r.last;
      for (const e of r.events.filter((x) => x.time >= startedAt)) {
        events.prepend(h("div", { class: "ev " + e.level }, h("time", {}, fmtClock(e.time)), h("span", {}, e.message)));
      }
    });
  };

  (async () => {
    opts = await api(isNew ? "/api/hub/setup" : "/api/setup").catch((e) => { toast(e.message, true); return null; });
    if (!opts) return;
    if (!st.prefilled && opts.current) {  // an existing craft-conductor.toml: start from its choices
      st.prefilled = true;
      const c = opts.current;
      if (opts.loaders.some((l) => l.name === c.loader)) st.loader = c.loader;
      st.minecraft = c.minecraft;
      for (const m of c.mods) st.mods.set(m.slug, { name: m.slug, required: m.required, explicit: true, by: new Set(), bad: "" });
      if (c.memory_gb) st.memory_gb = c.memory_gb;
    }
    st.newest = opts.versions[0] || "";
    if (st.mods.size) setupRecheckMods();  // names, dependencies and compatibility
    propDefaults = Object.fromEntries(opts.properties_schema.map((p) => [p.key, p.default]));
    if (!st.properties) st.properties = { ...propDefaults };
    if (st.memory_gb === null) st.memory_gb = opts.memory_gb;
    if (isNew && opts.port) st.port = opts.port;  // a port no other server here uses
    if (st.network_access === null) st.network_access = opts.network_access;
    if (opts.versions_error) toast(opts.versions_error, true);
    const s = status || (server ? await api("/api/status").catch(() => ({})) : {});
    if (s.job && s.job.name === "set up server") { st.submitted = true; renderProgress(); } else renderForm();
  })();

  $("#main").replaceChildren(main);
  return {
    refresh: () => { if (opts && !st.submitted) renderForm(); },
    onJobDone: () => {
      const last = status && status.last_job;
      if (!last || last.name !== "set up server") return;
      if (last.ok) setupFinished();
      else { st.submitted = false; clearTimers(); every(2000, refreshStatus); renderForm(last.message); }
    },
  };
};

// ------------------------------------------------------------------- router
const PHONE_VIEWS = ["dashboard", "players", "updates", "backups"];  // what a paired phone can use
const SERVER_VIEWS = [["dashboard", "Dashboard"], ["console", "Console"], ["players", "Players"], ["updates", "Updates"],
  ["mods", "Mods"], ["friends", "Friends"], ["backups", "Backups"], ["java", "Java"], ["settings", "Settings"]];
let currentName = null;

const NAV_ICONS = {"dashboard":"M3 3h18v18H3z M3 9h18 M9 9v12","console":"M3 4h18v16H3z M7 9l3 3-3 3 M13 15h4","players":"M6 20v-2a6 6 0 0 1 12 0v2 M9 4h6v6H9z","mods":"M12 3l9 5v9l-9 5-9-5V8z M3 8l9 5 9-5 M12 13v9","backups":"M4 5h16v15H4z M4 10h16 M4 15h16","settings":"M4 7h16 M4 17h16 M9 4v6 M15 14v6","manual":"M12 5C9 3 5 3 3 4v15c3-1 6-1 9 1 M12 5c3-2 7-2 9-1v15c-3-1-6-1-9 1 V5","default":"M4 4h16v16H4z M8 8h8 M8 12h8 M8 16h5"};
function navIcon(href) {
  const name = href.split("/").pop().replace("#", "");
  const span = h("span", { class: "cc-nav-icon", "aria-hidden": "true" });
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor"); svg.setAttribute("stroke-width", "1.5");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", NAV_ICONS[name] || NAV_ICONS.default); svg.append(path); span.append(svg);
  return span;
}

function renderNav() {
  const hb = hubInfo || {};
  const a = (href, label, active, extra) => h("a", { href, class: active ? "active" : null, "aria-current": active ? "page" : null }, navIcon(href), h("span", {}, label), extra || null);
  const me = server && hb.servers ? hb.servers.find((x) => x.id === server) : null;
  const pending = me ? me.setup_pending : false;
  fill($("#nav"),
    server ? [
      hb.single ? null : a("#servers", "← All servers", false),
      h("div", { class: "nav-server" }, me ? me.name : server),
      pending ? a(link("setup"), "Setup", currentName === "setup")
        : SERVER_VIEWS.filter(([v]) => !hb.device || PHONE_VIEWS.includes(v)).map(([v, label]) => a(link(v), label, currentName === v,
            v === "updates" ? h("span", { id: "nav-update-dot", class: "dot" + (me && me.update ? "" : " hidden"), role: "img", "aria-label": "An update is ready" }) : null)),
    ] : [
      a("#servers", "Servers", currentName === "servers"),
      hb.single || hb.device ? null : a("#new", "New server", currentName === "new"),
    ],
    h("div", { class: "nav-sep" }),
    a("#help", "Help", currentName === "help"),
    a("#manual", "User manual", currentName === "manual"),
    hb.device ? h("div", { class: "nav-server small", title: "A paired phone has the everyday controls only" }, `📱 ${hb.device} (limited)`)
      : a("#craft-conductor", "Craft Conductor settings", currentName === "craft-conductor"));
  const inServer = !!server;
  $(".server-id").classList.toggle("hidden", !inServer);
  $(".actions").classList.toggle("hidden", !inServer);
  $("#page-title").classList.toggle("hidden", inServer);
  $("#page-title").textContent = t({ servers: "Your servers", new: "New server", "craft-conductor": "Craft Conductor settings", help: "Help", manual: "User manual" }[currentName] || "");
  // The browser tab (and what a screen reader says on arriving): the page, the server, Craft Conductor.
  const viewName = (SERVER_VIEWS.find(([v]) => v === currentName) || [])[1] || (currentName === "setup" ? "Setup" : "");
  document.title = [inServer ? t(viewName) : $("#page-title").textContent, inServer ? (me ? me.name : server) : "", "Craft Conductor"].filter(Boolean).join(" · ");
  if (!inServer) $("#job").classList.add("hidden");
}

function route() {
  closeHelp(true);
  closeAppNavigation();
  closeBrowser(true);
  const hash = (location.hash || "#servers").slice(1);
  document.body.classList.remove("browse-mode");
  if (hash.startsWith("browse")) {  // the mod browser window: no navigation around it
    clearTimers();
    currentName = "browse";
    current = views.browse(new URLSearchParams(hash.split("?")[1] || ""));
    return;
  }
  const m = hash.match(/^s\/([a-z0-9][a-z0-9-]*)(?:\/(\w+))?$/);
  const before = server;
  let view;
  if (m) {
    server = m[1];
    view = m[2] === "setup" || SERVER_VIEWS.some(([v]) => v === m[2]) ? m[2] : "dashboard";
  } else {
    server = null;
    view = ["servers", "new", "craft-conductor", "help", "manual"].includes(hash) ? hash : "servers";
  }
  if (server !== before) { status = null; lastJobSeen = null; }
  currentName = view;
  clearTimers();
  document.body.classList.remove("setup-mode");
  renderNav();
  every(2000, refreshStatus);
  current = views[view === "new" ? "setup" : view]();
  if (routed && !topDialog()) $("#main").focus({ preventScroll: true });  // (not on the first page: the browser starts at the top)
  routed = true;
}
let routed = false;
window.addEventListener("hashchange", () => { if (!$("#app").classList.contains("hidden")) route(); });

// Responsive application navigation. Existing routes and permissions stay in renderNav().
const appNavigation = window.matchMedia("(max-width: 1023px)");
const menuTrigger = $("#cc-app-menu"), appSidebar = $(".sidebar"), menuOverlay = $("#cc-app-overlay");
function closeAppNavigation(returnFocus = false) {
  appSidebar.classList.remove("open"); menuOverlay.classList.remove("open");
  menuTrigger.setAttribute("aria-expanded", "false");
  $(".content").inert = false;
  appSidebar.inert = appNavigation.matches;
  if (returnFocus) menuTrigger.focus();
}
function syncAppNavigation() {
  closeAppNavigation();
  (appNavigation.matches ? $("#cc-theme-mobile") : $("#cc-theme-desktop")).append($("#cc-app-theme"));
}
menuTrigger.addEventListener("click", () => {
  if (appSidebar.classList.contains("open")) { closeAppNavigation(true); return; }
  appSidebar.inert = false; $(".content").inert = true;
  appSidebar.classList.add("open"); menuOverlay.classList.add("open");
  menuTrigger.setAttribute("aria-expanded", "true");
  const first = appSidebar.querySelector("a"); if (first) first.focus();
});
menuOverlay.addEventListener("click", () => closeAppNavigation(true));
$("#nav").addEventListener("click", (e) => { if (e.target.closest("a")) closeAppNavigation(); });
document.addEventListener("keydown", (e) => {
  if (!appSidebar.classList.contains("open")) return;
  if (e.key === "Escape") { e.preventDefault(); closeAppNavigation(true); }
  if (e.key === "Tab") {
    const items = [menuTrigger, ...focusables(appSidebar)];
    const index = items.indexOf(document.activeElement);
    if (e.shiftKey && index <= 0) { e.preventDefault(); items[items.length - 1].focus(); }
    else if (!e.shiftKey && index === items.length - 1) { e.preventDefault(); items[0].focus(); }
  }
});
appNavigation.addEventListener("change", syncAppNavigation);
syncAppNavigation();

async function start() {
  await loadLanguage("/");  // (i18n.js: the chosen language's words, before anything is drawn)
  if (/^#pair=/.test(location.hash)) { showPairing(location.hash.slice(6)); return; }
  if ($("#pairing")) $("#pairing").remove();
  try { hubInfo = await api("/api/hub"); } catch (_) { return; }
  $("#login").classList.add("hidden");
  $("#app").classList.remove("hidden");
  registerWorker();
  route();
  phoneBanner();
}
start();
