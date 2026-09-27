"use strict";
// mcsm's invite page (GitHub Pages). The invite is after the # in the link, which browsers
// never send to any server: this page reads it here, offers mcsm's download from GitHub, and
// copies the invite when the download starts, so the friend just runs what they downloaded.
// Nothing is sent anywhere; the page makes no requests.

const RELEASES = "https://github.com/silverWRX03/mc-server-management/releases/latest";
const DOWNLOADS = {
  windows: ["Windows", "mcsm-windows-x64.exe"],
  macos: ["Mac (Apple silicon)", "mcsm-macos-arm64"],
  linux: ["Linux", "mcsm-linux-x64"],
  "linux-arm64": ["Linux (ARM)", "mcsm-linux-arm64"],
};
const OPEN_TIP = {
  windows: ["Open the file you downloaded (it's in your Downloads folder).",
    "If Windows says it \"protected your PC\", choose More info → Run anyway: mcsm is free and isn't code-signed."],
  macos: ["Open your Downloads folder, right-click the file and choose Open (the first time only)."],
  linux: ["Make the file runnable (chmod +x) and run it."],
  "linux-arm64": ["Make the file runnable (chmod +x) and run it."],
};

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) if (c !== null && c !== undefined && c !== false) el.append(c);
  return el;
}

function readInvite() {
  const [code, ...rest] = decodeURIComponent(location.hash.slice(1)).split("/");
  if (!/^mcsm-[A-Za-z0-9_-]{40,400}$/.test(code)) return null;
  try {  // check it's a complete invite: host|port|secret|fingerprint
    const b64 = code.slice(5).replace(/-/g, "+").replace(/_/g, "/");
    const parts = atob(b64 + "=".repeat((4 - b64.length % 4) % 4)).split("|");
    if (parts.length !== 4 || !/^[A-Za-z0-9_-]{43}$/.test(parts[3])) return null;
  } catch (_) { return null; }
  return { code, name: rest.join("/").slice(0, 60) };
}

function detectOS() {
  const ua = navigator.userAgent;
  if (/Windows/i.test(ua)) return "windows";
  if (/Mac OS X|Macintosh/i.test(ua) && !/iPhone|iPad/i.test(ua)) return "macos";
  if (/Linux/i.test(ua) && !/Android/i.test(ua)) return /aarch64|arm64/i.test(ua) ? "linux-arm64" : "linux";
  return null;  // a phone or tablet: mcsm runs on a computer
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (_) { return false; }
}

function render() {
  const root = document.getElementById("join");
  const invite = readInvite();
  if (!invite) {
    root.replaceChildren(h("div", { class: "card" }, h("h1", {}, "This invite link isn't complete"),
      h("p", {}, "Part of it may have been cut off. Ask the server's owner to send it again (copy the whole link).")));
    return;
  }
  const os = detectOS();
  const title = invite.name ? `You're invited to play on ${invite.name}` : "You're invited to a Minecraft server";
  const steps = h("div", { class: "card hidden", id: "next" });
  const codeBox = h("input", { readonly: true, value: invite.code, "aria-label": "Invite code", class: "code" });

  const download = (key) => async () => {
    const copied = await copy(invite.code);  // mcsm finds it when it opens
    steps.classList.remove("hidden");
    steps.replaceChildren(...[
      h("h2", {}, "Next: open mcsm"),
      h("ol", {}, (OPEN_TIP[key] || OPEN_TIP.windows).map((t) => h("li", {}, t)),
        h("li", {}, copied ? "mcsm finds your invite by itself and sets up Minecraft: pick your launcher and press the button."
          : "When mcsm asks for your invite, paste this:")),
      copied ? null : h("div", { class: "row" }, codeBox, h("button", { class: "btn", onclick: () => copy(invite.code).then((ok) => ok && toast("Copied")) }, "Copy")),
      h("p", { class: "muted small" }, "Downloading didn't start? ", h("a", { href: RELEASES }, "Get mcsm from GitHub"), ".")].filter(Boolean));
    steps.scrollIntoView({ behavior: "smooth", block: "center" });
  };
  const link = (key) => h("a", { href: `${RELEASES}/download/${DOWNLOADS[key][1]}`, onclick: download(key) }, DOWNLOADS[key][0]);
  const main = os ? h("a", { class: "btn big", href: `${RELEASES}/download/${DOWNLOADS[os][1]}`, onclick: download(os) },
    `⬇ Download mcsm for ${DOWNLOADS[os][0]}`) : null;

  root.replaceChildren(
    h("div", { class: "card" },
      h("div", { class: "head" }, h("img", { src: "../icon.png", alt: "", width: 56, height: 56 }), h("h1", {}, title)),
      h("p", {}, "mcsm sets up your Minecraft for this server: the right version and mods, in a folder of its own. Your other worlds aren't touched, and you sign in with your own Minecraft account as usual."),
      os ? [main, h("p", { class: "muted small" }, "Other computers: ",
        Object.keys(DOWNLOADS).filter((k) => k !== os).map((k, i) => [i ? " · " : "", link(k)]))]
        : [h("p", { class: "notice" }, "Open this link on the computer you play Minecraft on (Windows, Mac or Linux)."),
          h("p", {}, Object.keys(DOWNLOADS).map((k, i) => [i ? " · " : "", link(k)]))]),
    steps,
    h("div", { class: "card" }, h("h2", {}, "Already have mcsm?"),
      h("div", { class: "row" },
        h("a", { class: "btn", href: `mcsm://join/${invite.code}` }, "Open in mcsm"),
        h("button", { class: "btn ghost", onclick: () => copy(invite.code).then((ok) => toast(ok ? "Invite copied: open mcsm" : "Couldn't copy; select the code below")) }, "Copy the invite")),
      h("details", { class: "muted small" }, h("summary", {}, "For power users"),
        h("p", {}, "Run ", h("code", {}, "mcsm join"), " with this invite code, or paste it into mcsm:"), codeBox.cloneNode())),
    h("p", { class: "muted small center" }, "mcsm checks it's really your friend's server before connecting, and downloads mods only from Modrinth and CurseForge. ",
      h("a", { href: "https://github.com/silverWRX03/mc-server-management" }, "About mcsm")));
  root.querySelectorAll("input.code").forEach((el) => { el.value = invite.code; });
}

function toast(text) {
  const el = h("div", { class: "toast" }, text);
  document.body.append(el);
  setTimeout(() => el.remove(), 3000);
}

window.addEventListener("hashchange", render);
render();
