"use strict";
// Craft Conductor's invite page (GitHub Pages). The invite is after the # in the link, which browsers
// never send to any server: this page reads it here, offers Craft Conductor's download from GitHub, and
// copies the invite when the download starts, so the friend just runs what they downloaded.
// Nothing is sent anywhere; the page makes no requests.

const RELEASES = "https://github.com/silverWRX03/craft-conductor/releases/latest";
const DOWNLOADS = {
  windows: ["Windows", "craft-conductor-join-windows-x64.exe"],
  macos: ["Mac (Apple silicon)", "craft-conductor-join-macos-arm64"],
  linux: ["Linux", "craft-conductor-join-linux-x64"],
  "linux-arm64": ["Linux (ARM)", "craft-conductor-join-linux-arm64"],
};
const OPEN_TIP = {
  windows: ["Open the file you downloaded (it's in your Downloads folder).",
    "If Windows says it \"protected your PC\", choose More info → Run anyway: Craft Conductor is free and isn't code-signed."],
  macos: ["Open your Downloads folder, right-click the file and choose Open (the first time only)."],
  linux: ["Make the file runnable (chmod +x) and run it."],
  "linux-arm64": ["Make the file runnable (chmod +x) and run it."],
};

// Languages: the friend's browser language, or the one picked at the bottom of the page.
const LANG_NAMES = { en: "English", es: "Español", pt: "Português", fr: "Français", de: "Deutsch", hi: "हिन्दी",
  zh: "中文（简体）", vi: "Tiếng Việt", ar: "العربية", ko: "한국어" };
const LANG_KEY = "craft-conductor-lang";
function pickLanguage() {
  let saved = "";
  try { saved = localStorage.getItem(LANG_KEY) || ""; } catch (_) { /* private mode */ }
  if (LANG_NAMES[saved]) return saved;
  for (const l of navigator.languages || [navigator.language || "en"]) {
    const base = String(l).toLowerCase().split("-")[0];
    if (LANG_NAMES[base]) return base;
  }
  return "en";
}
const LANG = pickLanguage();
const TR = (typeof SITE_I18N === "object" && SITE_I18N[LANG]) || {};
// The translation of a piece of text; {name} placeholders are filled in afterwards.
function t(text, vars) {
  if (typeof text !== "string") return text;
  const trimmed = text.trim();
  let out = TR[text] || (TR[trimmed] ? text.replace(trimmed, () => TR[trimmed]) : text);
  for (const [k, v] of Object.entries(vars || {})) out = out.replace(`{${k}}`, () => v);
  return out;
}

function languagePicker() {
  const sel = h("select", { "aria-label": "Language", onchange: () => {
    try { localStorage.setItem(LANG_KEY, sel.value); } catch (_) { /* private mode */ }
    location.reload();
  } }, Object.entries(LANG_NAMES).map(([code, name]) => h("option", { value: code, selected: code === LANG }, name)));
  return h("p", { class: "muted small center" }, "🌐 ", sel);
}

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else el.setAttribute(k, v === true ? "" : ["placeholder", "aria-label", "title"].includes(k) ? t(v) : v);
  }
  for (const c of children.flat(Infinity)) if (c !== null && c !== undefined && c !== false) el.append(typeof c === "string" ? t(c) : c);
  return el;
}

function readInvite(hash = location.hash.slice(1)) {
  let text;
  try { text = decodeURIComponent(hash); } catch (_) { return null; }
  const [code, ...rest] = text.split("/");
  if (!/^craft-conductor-[A-Za-z0-9_-]{40,400}$/.test(code)) return null;
  try {  // check it's a complete invite: host|port|secret|fingerprint
    const b64 = code.slice("craft-conductor-".length).replace(/-/g, "+").replace(/_/g, "/");
    const parts = atob(b64 + "=".repeat((4 - b64.length % 4) % 4)).split("|");
    if (parts.length !== 4 || !/^[A-Za-z0-9_-]{43}$/.test(parts[3])) return null;
  } catch (_) { return null; }
  return { code, name: rest.join("/").slice(0, 60) };
}

function readBedrockInvite(hash = location.hash.slice(1)) {
  if (!hash.startsWith("bedrock?")) return null;
  const params = new URLSearchParams(hash.slice(8));
  const host = params.get("host") || "", port = params.get("port") || "";
  if (!/^[A-Za-z0-9.:-]{1,253}$/.test(host) || !/^\d{1,5}$/.test(port) || +port < 1 || +port > 65535) return null;
  return { host, port: +port, name: (params.get("name") || "").slice(0, 60) };
}

function bedrockCard(invite) {
  return h("div", { class: "card" },
    h("h1", {}, invite.name ? t("You're invited to play on {name}", { name: invite.name }) : "You're invited to a Minecraft server"),
    h("h2", {}, "Join with Minecraft Bedrock Edition"),
    h("p", {}, "Open Minecraft, then Play → Servers → Add Server. Enter these details and save the server:"),
    h("p", {}, "Server name: ", h("strong", {}, invite.name || "Minecraft server")),
    h("p", {}, "Server address: ", h("code", {}, invite.host)),
    h("p", {}, "Port: ", h("code", {}, String(invite.port))),
    h("button", { class: "btn", onclick: async () => toast(await copy(invite.host) ? "Address copied" : "Couldn't copy; select the address above") }, "Copy address"),
    h("p", { class: "muted small" }, "Use your installed Minecraft Bedrock Edition. You don't need to download Craft Conductor."),
    h("p", { class: "muted small" }, "Xbox, PlayStation and Switch can't add servers directly. Ask the server owner for help joining from a console."),
    languagePicker());
}

function detectOS() {
  const ua = navigator.userAgent;
  if (/Windows/i.test(ua)) return "windows";
  if (/Mac OS X|Macintosh/i.test(ua) && !/iPhone|iPad/i.test(ua)) return "macos";
  if (/Linux/i.test(ua) && !/Android/i.test(ua)) return /aarch64|arm64/i.test(ua) ? "linux-arm64" : "linux";
  return null;  // a phone or tablet: Craft Conductor runs on a computer
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (_) { return false; }
}

function render() {
  const root = document.getElementById("join");
  const bedrock = readBedrockInvite();
  if (bedrock) {
    root.replaceChildren(bedrockCard(bedrock));
    return;
  }
  const invite = readInvite();
  if (!invite) {
    root.replaceChildren(pasteCard());
    return;
  }
  const os = detectOS();
  // (the server's name goes in after translating, so it's never translated itself)
  const title = invite.name ? t("You're invited to play on {name}", { name: invite.name }) : "You're invited to a Minecraft server";
  const steps = h("div", { class: "card hidden", id: "next" });
  const codeBox = h("input", { readonly: true, value: invite.code, "aria-label": "Invite code", class: "code" });
  const openHelp = h("div", { class: "notice hidden", role: "status" },
    h("strong", {}, "Opening Craft Conductor…"), " If your browser asks, choose Open. Craft Conductor brings back its page even if you closed that tab.",
    h("br"), "Nothing happened? Craft Conductor isn't set up to open links on this computer yet (Macs, or Craft Conductor never run): download it above and open it; the invite is already copied for it.");

  const download = (key) => async () => {
    const copied = await copy(invite.code);  // Craft Conductor finds it when it opens
    steps.classList.remove("hidden");
    steps.replaceChildren(...[
      h("h2", {}, "Next: open Craft Conductor"),
      h("ol", {}, (OPEN_TIP[key] || OPEN_TIP.windows).map((t) => h("li", {}, t)),
        h("li", {}, copied ? "Craft Conductor finds your invite by itself and sets up Minecraft: pick your launcher and press the button."
          : "When Craft Conductor asks for your invite, paste this:")),
      copied ? null : h("div", { class: "row" }, codeBox, h("button", { class: "btn", onclick: () => copy(invite.code).then((ok) => ok && toast("Copied")) }, "Copy")),
      h("p", { class: "muted small" }, "Downloading didn't start? ", h("a", { href: RELEASES }, "Get Craft Conductor from GitHub"), ".")].filter(Boolean));
    steps.scrollIntoView({ behavior: "smooth", block: "center" });
  };
  const link = (key) => h("a", { href: `${RELEASES}/download/${DOWNLOADS[key][1]}`, onclick: download(key) }, DOWNLOADS[key][0]);
  const main = os ? h("a", { class: "btn big", href: `${RELEASES}/download/${DOWNLOADS[os][1]}`, onclick: download(os) },
    t("⬇ Download Craft Conductor for {os}", { os: t(DOWNLOADS[os][0]) })) : null;

  root.replaceChildren(
    h("div", { class: "card" },
      h("div", { class: "head" }, h("img", { src: "../icon.png", alt: "", width: 56, height: 56 }), h("h1", {}, title)),
      h("p", {}, "Craft Conductor sets up your Minecraft for this server: the right version and mods, in a folder of its own. Your other worlds aren't touched, and you sign in with your own Minecraft account as usual."),
      os ? [main, h("p", { class: "muted small" }, "Other computers: ",
        Object.keys(DOWNLOADS).filter((k) => k !== os).map((k, i) => [i ? " · " : "", link(k)]))]
        : [h("p", { class: "notice" }, "Open this link on the computer you play Minecraft on (Windows, Mac or Linux)."),
          h("p", {}, Object.keys(DOWNLOADS).map((k, i) => [i ? " · " : "", link(k)]))]),
    steps,
    h("div", { class: "card" }, h("h2", {}, "Already have Craft Conductor?"),
      h("div", { class: "row" },
        h("a", { class: "btn", href: `craft-conductor://join/${invite.code}`, onclick: () => {
          copy(invite.code);  // so Craft Conductor finds it even if the link can't open it
          openHelp.classList.remove("hidden");
        } }, "Open in Craft Conductor"),
        h("button", { class: "btn ghost", onclick: () => copy(invite.code).then((ok) => toast(ok ? "Invite copied: open Craft Conductor" : "Couldn't copy; select the code below")) }, "Copy the invite")),
      openHelp,
      h("details", { class: "muted small" }, h("summary", {}, "For power users"),
        h("p", {}, "Run ", h("code", {}, "craft-conductor join"), " with this invite code, or paste it into Craft Conductor:"), codeBox.cloneNode())),
    h("p", { class: "muted small center" }, "Craft Conductor checks it's really your friend's server before connecting, and downloads mods only from Modrinth and CurseForge. ",
      h("a", { href: "https://github.com/silverWRX03/craft-conductor" }, "About Craft Conductor")),
    languagePicker());
  root.querySelectorAll("input.code").forEach((el) => { el.value = invite.code; });
}

// The link arrived without its invite (some apps cut links short at the #): let the friend
// paste what they were sent. It's only read here, like a link's invite.
function fromPasted(text) {
  text = text.trim();
  const hash = text.includes("#") ? text.slice(text.indexOf("#") + 1) : text;
  if (readInvite(hash) || readBedrockInvite(hash)) return hash;
  const m = text.match(/craft-conductor-[A-Za-z0-9_-]{40,400}/);
  return m && readInvite(m[0]) ? m[0] : null;
}

function pasteCard() {
  const box = h("input", { class: "code", placeholder: "Paste the link or invite here", "aria-label": "Invite link or code", autocomplete: "off" });
  const err = h("p", { class: "error hidden" }, "That isn't a complete Craft Conductor invite. Ask the server's owner to send it again.");
  const go = () => {
    const hash = fromPasted(box.value);
    if (!hash) { err.classList.remove("hidden"); return; }
    location.hash = hash;  // shows the invite (render runs on hashchange)
  };
  box.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  box.addEventListener("input", () => { err.classList.add("hidden"); if (fromPasted(box.value)) go(); });
  const hadSomething = location.hash.length > 1;
  return h("div", { class: "card" },
    h("h1", {}, hadSomething ? "This invite link isn't complete" : "Paste your invite"),
    h("p", {}, hadSomething ? "Part of it was cut off on the way. " : "The link you opened didn't bring its invite with it (some apps cut links short). ",
      "Copy the whole link (or the invite code) you were sent and paste it here:"),
    h("div", { class: "row" }, box, h("button", { class: "btn", onclick: go }, "Open invite")),
    err,
    h("p", { class: "muted small" }, "Tip: in Discord, right-click the link and choose Copy Link. Nothing you paste leaves this page."),
    languagePicker());
}

function toast(text) {
  const el = h("div", { class: "toast" }, text);
  document.body.append(el);
  setTimeout(() => el.remove(), 3000);
}

document.documentElement.lang = LANG;
document.documentElement.dir = LANG === "ar" ? "rtl" : "ltr";
document.title = `${t("You're invited to a Minecraft server")} · Craft Conductor`;
window.addEventListener("hashchange", render);
render();
