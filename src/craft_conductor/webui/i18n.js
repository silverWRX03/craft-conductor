"use strict";
// Languages for craft-conductor's pages (the control panel and the friend's setup page). Each language is
// a file i18n/<code>.json mapping English text to its translation; text without one stays in
// English. The language is the one picked in craft-conductor settings (kept in this browser), or else the
// browser's own. Arabic is written right to left.
const LANGS = {
  en: "English", es: "Español", pt: "Português", fr: "Français", de: "Deutsch", hi: "हिन्दी",
  zh: "中文（简体）", vi: "Tiếng Việt", ar: "العربية", ko: "한국어",
};
const RTL = new Set(["ar"]);
const LANG_KEY = "craft-conductor-lang";
let I18N = {};

function savedLanguage() { try { return localStorage.getItem(LANG_KEY) || ""; } catch (_) { return ""; } }
function pickLanguage() {
  const saved = savedLanguage();
  if (LANGS[saved]) return saved;
  for (const l of navigator.languages || [navigator.language || "en"]) {
    const base = String(l).toLowerCase().split("-")[0];
    if (LANGS[base]) return base;
  }
  return "en";
}
const LANG = pickLanguage();

// The translation of a piece of text (itself when there's none).
function t(text) {
  if (typeof text !== "string") return text;
  const hit = I18N[text];
  if (hit) return hit;
  const trimmed = text.trim();  // (text written with spaces around it, to sit next to other text)
  return trimmed !== text && I18N[trimmed] ? text.replace(trimmed, () => I18N[trimmed]) : text;
}

// Translate what's already on the page (text and the attributes people read).
function translateTree(root) {
  if (LANG === "en") return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const n of nodes) n.nodeValue = t(n.nodeValue);
  root.querySelectorAll("[placeholder],[title],[aria-label]").forEach((el) => {
    for (const a of ["placeholder", "title", "aria-label"]) {
      const v = el.getAttribute(a);
      if (v) el.setAttribute(a, t(v));
    }
  });
}

async function loadLanguage(base = "") {
  document.documentElement.lang = LANG;
  document.documentElement.dir = RTL.has(LANG) ? "rtl" : "ltr";
  if (LANG === "en") return;
  try {
    const r = await fetch(`${base}i18n/${LANG}.json`, { credentials: "same-origin" });
    if (r.ok) I18N = await r.json();
  } catch (_) { /* stays in English */ }
  translateTree(document.body);
}

function setLanguage(code) {
  try { if (code) localStorage.setItem(LANG_KEY, code); else localStorage.removeItem(LANG_KEY); } catch (_) { /* private mode */ }
  location.reload();
}
