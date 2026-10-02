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

// The full catalogs are machine-translated. Keep human-reviewed corrections here so they are easy to
// audit and are not lost if the base catalogs are regenerated. Only wording whose meaning or naturalness
// was checked is overridden here; product names, commands and placeholders stay unchanged.
const REVIEWED_I18N = {
  de: {
    "A strong one: see below.": "Ein sicheres Passwort – siehe unten.",
    "Allow them on the Players page.": "Erlaube ihnen den Zugriff über die Seite „Spieler“.",
    "Ancient city": "Antike Stadt",
    "Can friends outside your home connect?": "Können sich Freunde von außerhalb deines Zuhauses verbinden?",
    "Check for Craft Conductor updates": "Nach Updates für Craft Conductor suchen",
    "Checking for a new Craft Conductor version…": "Suche nach einer neuen Version von Craft Conductor…",
    "Craft Conductor settings": "Einstellungen von Craft Conductor",
    "Fell behind": "Zurückgefallen",
    "Kept up": "Mitgehalten",
    "Open its control panel": "Bedienoberfläche öffnen",
    "Opening Craft Conductor's control panel…": "Die Bedienoberfläche von Craft Conductor wird geöffnet…",
    "Rehearse": "Testlauf",
    "Rehearse again": "Erneut testen",
    "Rehearse the update": "Update testen",
    "Ran for": "Laufzeit",
  },
  es: {
    "A strong one: see below.": "Una contraseña segura: consulta abajo.",
    "Allow them on the Players page.": "Autorízalos en la página Jugadores.",
    "Before a new Minecraft goes in by itself, try it on a copy of the server first": "Antes de instalar automáticamente una nueva versión de Minecraft, pruébala primero en una copia del servidor",
    "Button presses": "Pulsaciones de botones",
    "Configured (craft-conductor.toml)": "Configurado (craft-conductor.toml)",
    "Installed": "Instalado",
    "Kept up": "Siguió el ritmo",
    "Newest release (recommended)": "Versión estable más reciente (recomendada)",
    "Newest version your mods support (recommended)": "La versión más reciente que admiten tus mods (recomendada)",
    "Rehearse": "Probar",
    "Rehearse again": "Volver a probar",
    "Rehearse the update": "Probar la actualización",
    "Releases, betas and alphas (least stable)": "Estables, betas y alfas (estas últimas son las menos estables)",
  },
  pt: {
    "A strong one: see below.": "Uma senha forte: veja abaixo.",
    "Allow them on the Players page.": "Permita a entrada deles na página Jogadores.",
    "Before a new Minecraft goes in by itself, try it on a copy of the server first": "Antes de uma nova versão do Minecraft ser instalada automaticamente, teste-a primeiro em uma cópia do servidor",
    "Configured (craft-conductor.toml)": "Configurado (craft-conductor.toml)",
    "Couldn't reach the server": "Não foi possível conectar ao servidor",
    "Craft Conductor is in beta: expect some rough edges, and keep backups.": "O Craft Conductor está em beta: espere algumas imperfeições e mantenha backups.",
    "Open its control panel": "Abrir o painel de controle",
    "Rehearse": "Testar",
    "Rehearse again": "Testar novamente",
    "Rehearse the update": "Testar a atualização",
    "Releases, betas and alphas (least stable)": "Estáveis, betas e alfas (as menos estáveis)",
  },
  fr: {
    "(nobody is usually on)": "(il n’y a généralement personne)",
    "-1 turns the watchdog off.": "-1 désactive le watchdog.",
    "Allow them on the Players page.": "Autorisez-les sur la page Joueurs.",
    "Before a new Minecraft goes in by itself, try it on a copy of the server first": "Avant d’installer automatiquement une nouvelle version de Minecraft, essayez-la d’abord sur une copie du serveur",
    "Configured (craft-conductor.toml)": "Configuré (craft-conductor.toml)",
    "Craft Conductor can live on your phone's home screen like an app, and tell you when something needs you, even when it's closed.": "Craft Conductor peut s’installer sur l’écran d’accueil de votre téléphone comme une application et vous prévenir quand il a besoin de vous, même lorsqu’il est fermé.",
    "Installed": "Installé",
    "Kept up": "A suivi le rythme",
    "Letting friends join": "Autoriser les amis à rejoindre",
    "Rehearse": "Tester",
    "Rehearse again": "Tester à nouveau",
    "Rehearse the update": "Tester la mise à jour",
    "Releases, betas and alphas (least stable)": "Stables, bêtas et alphas (les moins stables)",
  },
  hi: {
    "Allow them on the Players page.": "खिलाड़ी पेज पर उन्हें अनुमति दें।",
    "Every day at…": "हर दिन … बजे",
    "Every week on…": "हर हफ़्ते … को",
    "Kept up": "रफ़्तार बनाए रखी",
    "Rehearse the update": "अपडेट आज़माएँ",
  },
  zh: {
    "Allow them on the Players page.": "在“玩家”页面允许他们加入。",
    "Button presses": "按钮操作",
    "Rehearse": "试运行",
    "Rehearse again": "再次试运行",
    "Rehearse the update": "试运行更新",
  },
  vi: {
    "Allow them on the Players page.": "Cho phép họ ở trang Người chơi.",
    "Any version": "Bất kỳ phiên bản nào",
    "Before a new Minecraft goes in by itself, try it on a copy of the server first": "Trước khi tự động cài phiên bản Minecraft mới, hãy thử trước trên một bản sao của máy chủ",
    "Kept up": "Theo kịp",
    "Backup copies": "Các bản sao lưu phụ",
  },
  ar: {
    "A Fabric fork that also runs most Fabric mods.": "نسخة متفرعة من Fabric تشغّل أيضًا معظم تعديلات Fabric.",
    "A modpack": "حزمة تعديلات",
    "Allow them on the Players page.": "اسمح لهم من صفحة اللاعبين.",
    "Also show mods with only alpha/beta builds (less stable)": "إظهار التعديلات التي لها إصدارات ألفا/بيتا فقط أيضًا (أقل استقرارًا)",
    "Downloading Minecraft and the mods…": "جارٍ تنزيل Minecraft والتعديلات…",
    "Each backup is a snapshot of the whole server: the world, the mods, their settings and Craft Conductor's settings for it. One is also made automatically before every update.": "كل نسخة احتياطية لقطة للخادم كله: العالم والتعديلات وإعداداتها وإعدادات Craft Conductor. وتُنشأ واحدة تلقائيًا قبل كل تحديث.",
    "Fabric with Terralith (almost 100 new biomes, vanilla blocks) and the performance mods. Friends join with plain Minecraft.": "Fabric مع Terralith (نحو 100 منطقة حيوية جديدة بكتل عادية) وتعديلات الأداء. ينضم الأصدقاء بـ Minecraft العادي.",
    "Fabric with performance mods (Lithium, FerriteCore, Krypton): less lag, same game. Friends join with plain Minecraft.": "Fabric مع تعديلات الأداء (Lithium وFerriteCore وKrypton): تأخر أقل، اللعبة نفسها. ينضم الأصدقاء بـ Minecraft العادي.",
    "From Craft Conductor's shared list of mod conflicts. If the server starts fine, you can ignore this.": "من قائمة Craft Conductor المشتركة لتعارضات التعديلات. إذا بدأ الخادم بشكل طبيعي فيمكنك تجاهل هذا.",
    "From mods:": "من التعديلات:",
    "Hardcore: one life, locked to hard": "الوضع المتشدد: حياة واحدة، مقفل على الصعب",
    "Installed": "تم التثبيت",
    "It takes a minute or two, longer with many mods or a bigger map. Nothing is installed for the server yet: that happens when you create it.": "يستغرق ذلك دقيقة أو اثنتين، وأطول مع كثرة التعديلات أو خريطة أكبر. لا يُثبَّت شيء للخادم بعد: يحدث ذلك عند إنشائه.",
    "Newest version your mods support (recommended)": "أحدث إصدار تدعمه تعديلاتك (مستحسن)",
    "No mods configured.": "لا توجد تعديلات مُعدّة.",
    "No mods yet: the map shows plain Minecraft.": "لا توجد تعديلات بعد: الخريطة تعرض Minecraft العادي.",
    "Not recommended: fix the problem first (update or remove the mod named).": "غير موصى به: أصلح المشكلة أولًا (حدّث التعديل المذكور أو أزله).",
    "Only the newest version (waits until every mod supports it)": "أحدث إصدار فقط (ينتظر حتى تدعمه كل التعديلات)",
    "Pick a server type, Minecraft version and mods": "اختر نوع الخادم وإصدار Minecraft والتعديلات",
    "Plain Minecraft with no mods.": "Minecraft عادي بدون تعديلات.",
    "Remove modpack": "إزالة حزمة التعديلات",
  },
  ko: {
    "A crash, a friend asking to join, an update held back: even when the app is closed.": "서버 충돌, 친구의 참가 요청, 보류된 업데이트: 앱이 닫혀 있어도.",
    "Allow them on the Players page.": "플레이어 페이지에서 이들을 허용하세요.",
    "Before …": "… 전에",
    "Closing this tab doesn't stop Craft Conductor.": "이 탭을 닫아도 Craft Conductor는 멈추지 않습니다.",
    "Discord server(s)": "Discord 서버",
    "From x": "x부터",
    "Get a notification when a server crashes, a friend asks to join, an update is held back or it lags.": "서버가 비정상 종료되거나, 친구가 참가를 요청하거나, 업데이트가 보류되거나, 렉이 발생하면 알림을 받으세요.",
    "Guided setup": "설정 안내",
    "Kept up": "정상 유지",
    "Pick a seed (or leave it empty for a random one) and press Preview map. Craft Conductor makes the world in a private server on this computer, with the server's mods, then draws it from above.": "시드를 고르고(비워 두면 무작위) 지도 미리보기를 누르세요. Craft Conductor가 이 컴퓨터의 비공개 서버에서 서버의 모드로 월드를 만든 뒤 위에서 본 모습을 그립니다.",
    "Rehearse": "시험 실행",
    "Rehearse again": "다시 시험 실행",
    "Rehearse the update": "업데이트 시험 실행",
    "Saved. Close and reopen Craft Conductor to switch to HTTPS.": "저장되었습니다. HTTPS로 전환하려면 Craft Conductor를 닫았다가 다시 여세요.",
  },
};

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
  Object.assign(I18N, REVIEWED_I18N[LANG] || {});
  translateTree(document.body);
}

function setLanguage(code) {
  try { if (code) localStorage.setItem(LANG_KEY, code); else localStorage.removeItem(LANG_KEY); } catch (_) { /* private mode */ }
  location.reload();
}
