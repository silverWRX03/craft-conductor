"use strict";
// The friend's page ("mcfui"): pick launchers, add the server to them, watch progress.
const $ = (sel) => document.querySelector(sel);
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "checked") el.checked = !!v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json", "X-MCSM": "1" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { const e = new Error(data.error || res.statusText); e.data = data; e.status = res.status; throw e; }
  return data;
}
function toast(message, bad = false) {  // (top centre, like mcsm's control panel; click to dismiss)
  const el = h("div", { class: "toast" + (bad ? " bad" : ""), role: bad ? "alert" : "status", onclick: () => el.remove() },
    h("span", { class: "toast-icon", "aria-hidden": "true" }, bad ? "⚠" : "✓"), h("span", {}, message));
  $("#toasts").append(el);
  setTimeout(() => el.remove(), bad ? 12000 : 7000);
}

const LOADERS = { fabric: "Fabric", quilt: "Quilt", neoforge: "NeoForge", forge: "Forge", vanilla: "no mod loader" };
const OPEN_LABEL = { minecraft: "Open the Minecraft Launcher", prism: "Launch in Prism", modrinth: "Open the file", curseforge: "Show the file" };
let info = null;
let seen = 0;
let extras = { items: [], kinds: {} };

// ---------------------------------------------------------- your extras
// Shaders, resource packs and more mods on top of the server's own, picked from Modrinth in a
// panel that slides in (like mcsm's mod browser); mods bring what they need along.
const KIND = { shader: ["Shaders", "✨", "shaders"], resourcepack: ["Resource packs", "🎨", "resource packs"], mod: ["More mods", "🧩", "mods"] };
function extrasCard() {
  const list = h("div", { id: "extras-list" });
  // What an extra brings along (Sodium for Iris, Iris for shaders…), listed under it.
  const broughtBy = (names, depth, shown) => (extras.deps || []).filter((d) => names.includes(d.needed_by) && !shown.has(d.name) && depth < 6)
    .flatMap((d) => { shown.add(d.name); return [h("li", { class: "dep" }, h("span", { class: "grow" }, "↳ ", h("strong", {}, d.name),
      h("span", { class: "tag" }, `needed by ${d.needed_by}`))), ...broughtBy([d.name], depth + 1, shown)]; });
  const renderList = () => {
    const shown = new Set();
    let firstShader = true;
    list.replaceChildren(extras.items.length ? h("ul", { class: "list" }, extras.items.map((i) => [h("li", {},
      h("span", { class: "grow" }, h("strong", {}, i.name), " ", h("span", { class: "tag" }, KIND[i.kind][2].replace(/s$/, "")),
        i.enabled === false ? h("span", { class: "tag warn" }, "switched off") : null),
      i.kind !== "mod" ? h("label", { class: "row small", title: i.enabled === false ? "It may not work on this Minecraft version; switching it on may crash the game" : "" },
        h("input", { type: "checkbox", checked: i.enabled !== false, onchange: async (e) => {
          if (e.target.checked && i.enabled === false && !confirm(`${i.name} may not work on Minecraft ${extras.minecraft}. Switching it back on may crash the game. Switch it on anyway?`)) { e.target.checked = false; return; }
          extras = await api("api/extras/enable", { id: i.id, enabled: e.target.checked }).catch((err) => { toast(err.message, true); return extras; });
          renderList();
        } }), "on") : null,
      h("button", { class: "btn small ghost", onclick: async () => {
        extras = await api("api/extras/remove", { id: i.id }).catch((err) => { toast(err.message, true); return extras; });
        renderList();
      } }, "Remove")),
      ...broughtBy(i.kind === "shader" && firstShader && !(firstShader = false) ? [i.name, "your shaders"] : [i.name], 0, shown)]))
      : h("p", { class: "muted small" }, "Nothing added: you'll get exactly what the server needs."));
  };
  renderList();
  extrasCard.refresh = renderList;
  const buttons = Object.entries(KIND).filter(([k]) => extras.kinds[k]).map(([k, [label, icon]]) =>
    h("button", { type: "button", class: "btn", onclick: () => openPicker(k) }, `${icon} ${label}`));
  return h("div", { class: "card" },
    h("h2", {}, "Make it yours (optional)"),
    h("p", { class: "muted small" }, "Add shaders, resource packs or other mods that only run on your computer. They're installed with the server's mods, " +
      "and mods bring what they need along. The server doesn't need them."),
    h("div", { class: "row wrap" }, buttons),
    list);
}
// Laid out like mcsm's mod browser: search, sort and category at the top left, the results
// (tick the ones you want) below, "Add selected" pinned at the bottom, and the picked
// project's page on the right; the list scrolls on its own.
function openPicker(kind) {
  closePicker();
  const [label, , noun] = KIND[kind];
  const one = noun.replace(/s$/, "");
  const st = { q: "", sort: "", category: "", offset: 0, results: [], selected: new Map(), active: null };
  const q = h("input", { type: "search", placeholder: `Search ${noun}…`, "aria-label": `Search ${noun}` });
  const sort = h("select", { "aria-label": "Sort by" }, [["", "Best match"], ["downloads", "Most downloaded"],
    ["follows", "Most followed"], ["newest", "Newest"], ["updated", "Recently updated"]].map(([v, l]) => h("option", { value: v }, l)));
  const category = h("select", { "aria-label": "Category" }, h("option", { value: "" }, "All categories"));
  const list = h("div", { class: "browse-results" }, h("p", { class: "muted" }, "Loading…"));
  const details = h("div", { class: "browse-right" }, h("p", { class: "empty" }, `Pick a ${one} on the left to read about it here.`));
  const count = h("span", { class: "grow muted small" });
  const addBtn = h("button", { class: "btn primary", disabled: true }, `Add selected ${noun}`);
  let timer, seq = 0;
  const fmt = (n) => n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? Math.round(n / 1e3) + "k" : String(n);
  const icon = (src, cls) => src ? h("img", { src, alt: "", loading: "lazy", referrerpolicy: "no-referrer", class: cls })
    : h("div", { class: "noicon" });

  // What a ticked one brings along (shown before adding, like mcsm's mod browser).
  const needs = async (m) => {
    if (m.deps) return;
    if (kind !== "mod") { m.deps = kind === "shader" && !(extras.deps || []).some((d) => d.needed_by === "your shaders") ? ["a shader loader (Iris)"] : []; updateFooter(); return; }
    const r = await api(`api/extras/requires?id=${encodeURIComponent(m.id)}`).catch(() => null);
    if (!r) return;
    m.deps = r.deps.concat(r.companions).map((d) => d.name);
    m.bad = r.compatible ? "" : r.reason;
    updateFooter();
  };
  const updateFooter = () => {
    const n = st.selected.size;
    const extra = [...new Set([...st.selected.values()].flatMap((m) => m.deps || []))];
    const bad = [...st.selected.values()].filter((m) => m.bad);
    count.textContent = n ? `${n} selected: ${[...st.selected.values()].map((m) => m.name).slice(0, 3).join(", ")}${n > 3 ? "…" : ""}` +
      (extra.length ? ` · also adds ${extra.join(", ")} (needed)` : "") + (bad.length ? ` · ⚠ ${bad.map((m) => m.bad).join("; ")}` : "")
      : `Tick the ${noun} you want.`;
    addBtn.disabled = n === 0;
  };
  const renderList = (more) => {
    const have = new Set(extras.items.map((i) => i.id));
    list.replaceChildren(...(st.results.length ? st.results.map((m) => {
      const added = have.has(m.id);
      const box = added ? h("span", { class: "tag ok", title: "Already added" }, "✓")
        : h("input", { type: "checkbox", checked: st.selected.has(m.id), "aria-label": `Select ${m.name}`,
          onclick: (e) => e.stopPropagation(),
          onchange: (e) => { if (e.target.checked) { st.selected.set(m.id, m); needs(m); } else st.selected.delete(m.id); updateFooter(); } });
      return h("div", { class: "result" + (st.active === m.id ? " active" : ""), tabindex: "0", role: "button",
        onclick: () => showDetails(m), onkeydown: (e) => { if (e.key === "Enter") showDetails(m); } },
        box, icon(m.icon),
        h("div", { class: "info" },
          h("div", { class: "name" }, m.name, m.author ? h("span", { class: "muted small" }, ` by ${m.author}`) : null, added ? h("span", { class: "tag ok" }, "added") : null),
          h("div", { class: "desc" }, m.summary),
          h("div", { class: "muted small" }, `⬇ ${fmt(m.downloads || 0)}`, m.follows ? ` · ♥ ${fmt(m.follows)}` : "")));
    }).concat(more ? [h("div", { class: "row mt-s" }, h("button", { class: "btn small", onclick: () => { st.offset += 20; search(true); } }, "Load more"))] : [])
      : [h("p", { class: "muted" }, `No ${noun} found for Minecraft ${info.pack.minecraft}.`)]));
    updateFooter();
  };
  const search = async (append = false) => {
    const mine = ++seq;
    if (!append) { st.offset = 0; list.scrollTop = 0; list.replaceChildren(h("p", { class: "muted" }, "Searching…")); }
    const p = new URLSearchParams({ kind, q: st.q, offset: String(st.offset) });
    if (st.sort) p.set("sort", st.sort);
    if (st.category) p.set("category", st.category);
    let r;
    try { r = await api(`api/extras/search?${p}`); }
    catch (e) { list.replaceChildren(h("div", { class: "notice bad" }, e.message)); return; }
    if (mine !== seq) return;
    st.results = append ? st.results.concat(r.results) : r.results;
    renderList(r.results.length === 20);
  };
  const showDetails = async (m) => {
    st.active = m.id;
    renderList(false);
    details.replaceChildren(h("p", { class: "muted" }, `Loading ${m.name}…`));
    let p;
    try { p = await api(`api/extras/project?id=${encodeURIComponent(m.id)}`); }
    catch (e) { details.replaceChildren(h("div", { class: "notice bad" }, e.message)); return; }
    if (st.active !== m.id) return;
    const added = extras.items.some((i) => i.id === p.id);
    const pick = added ? h("span", { class: "tag ok" }, "added") : h("button", { class: "btn" + (st.selected.has(m.id) ? "" : " primary"), onclick: () => {
      if (st.selected.has(m.id)) st.selected.delete(m.id); else { st.selected.set(m.id, m); needs(m); }
      renderList(false); showDetails(m);
    } }, st.selected.has(m.id) ? "✓ Selected" : "Select");
    details.replaceChildren(...[
      h("div", { class: "browse-head" }, icon(p.icon),
        h("div", { class: "grow" }, h("h2", {}, p.name), h("div", { class: "muted" }, p.summary),
          h("div", { class: "muted small" }, `⬇ ${fmt(p.downloads)}`, p.follows ? ` · ♥ ${fmt(p.follows)}` : "",
            p.license ? ` · ${p.license}` : "", p.updated ? ` · updated ${new Date(p.updated).toLocaleDateString()}` : "")),
        h("div", { class: "row" }, pick, h("a", { class: "btn ghost", href: p.url, target: "_blank", rel: "noopener noreferrer" }, "Open on Modrinth ↗"))),
      p.categories.length ? h("div", { class: "mt-s" }, p.categories.map((c) => h("span", { class: "tag" }, c))) : null,
      p.gallery.length ? h("div", { class: "gallery mt" }, p.gallery.map((g) => h("a", { href: g.url, target: "_blank", rel: "noopener noreferrer" },
        h("img", { src: g.url, alt: g.title || "", loading: "lazy", referrerpolicy: "no-referrer" })))) : null,
      h("div", { class: "mt" }, richText(p.body, p.body_format))].filter(Boolean));  // (no "null" for missing parts)
    details.scrollTop = 0;
  };
  addBtn.addEventListener("click", async () => {
    addBtn.disabled = true;
    const added = [];
    const before = new Set((extras.deps || []).map((d) => d.name));
    for (const m of st.selected.values()) {
      try {
        extras = await api("api/extras/add", { kind, id: m.id, slug: m.slug, name: m.name });
        added.push(m.name);
      } catch (err) { toast(`${m.name}: ${err.message}`, true); }
    }
    const adds = (extras.deps || []).filter((d) => !before.has(d.name));  // what came along this time
    if (added.length) toast(`Added ${added.join(", ")}` + (adds.length ? `, with ${adds.map((a) => `${a.name} (needed by ${a.needed_by})`).join(", ")}` : ""));
    st.selected.clear();
    extrasCard.refresh && extrasCard.refresh();
    renderList(st.results.length && st.results.length % 20 === 0);
  });
  q.addEventListener("input", () => { st.q = q.value.trim(); clearTimeout(timer); timer = setTimeout(() => search(), 350); });
  sort.addEventListener("change", () => { st.sort = sort.value; search(); });
  category.addEventListener("change", () => { st.category = category.value; search(); });
  api(`api/extras/categories?kind=${kind}`).then((r) => category.append(...r.categories.map((c) => h("option", { value: c.id }, c.name)))).catch(() => {});

  const rail = h("button", { class: "jrail", type: "button", "aria-label": "Back", onclick: closePicker }, "‹ Back");
  const panel = h("section", { class: "jpanel", "aria-label": label },
    h("div", { class: "browse" },
      h("div", { class: "browse-left" },
        h("div", { class: "browse-filters" },
          h("div", { class: "row" }, h("strong", { class: "grow" }, `${label} for Minecraft ${info.pack.minecraft}`),
            h("button", { class: "btn ghost small", onclick: closePicker }, "Done")),
          kind === "shader" ? h("p", { class: "muted small" }, "Shaders need a shader loader (Iris, or Oculus on Forge); it's added for you. They need a good graphics card.") : null,
          q,
          h("div", { class: "row" }, sort, category)),
        list,
        h("div", { class: "browse-footer" }, count, addBtn)),
      details));
  document.body.append(rail, panel);
  document.body.classList.add("picking");
  q.focus();
  search();
}
function closePicker() {
  document.body.classList.remove("picking");
  document.querySelectorAll(".jrail, .jpanel").forEach((x) => x.remove());
}
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePicker(); });

// Before installing: extras that don't fit the server's Minecraft need the friend's say-so.
function confirmChanges(changes) {
  return new Promise((resolve) => {
    const done = (v) => { back.remove(); resolve(v); };
    const back = h("div", { class: "modal-backdrop", role: "dialog", "aria-modal": "true" }, h("div", { class: "modal" },
      h("h2", {}, `The server now runs Minecraft ${info.pack.minecraft}`),
      h("p", {}, "Some of your extras don't have a version for it yet:"),
      h("ul", { class: "list" }, changes.map((c) => h("li", {}, h("span", { class: "grow" }, h("strong", {}, c.name),
        h("div", { class: "small muted" }, c.reason)), h("span", { class: "tag " + (c.action === "removed" ? "bad" : "warn") }, c.action)))),
      h("p", { class: "small" }, "If you continue, mods without a version are removed, and resource packs and shaders are kept but ",
        h("strong", {}, "switched off"), ". You can switch them back on later, but the game may crash."),
      h("p", { class: "small muted" }, "If you cancel, nothing changes, but you can't join the updated server until you continue."),
      h("div", { class: "row mt" }, h("button", { class: "btn primary", onclick: () => done(true) }, "Continue"),
        h("button", { class: "btn ghost", onclick: () => done(false) }, "Cancel"))));
    document.body.append(back);
  });
}

// Opened without an invite: paste one (a copied one is filled in), pick a server joined
// before (to update it), or run a server of your own instead.
function renderAskInvite(error) {
  const input = h("input", { type: "text", value: info.copied_invite || "", placeholder: "mcsm-…", "aria-label": "Invite",
    autocomplete: "off", spellcheck: "false" });
  const use = async (code, btn) => {
    btn.disabled = true;
    try { info = await api("api/invite", { invite: code }); } catch (e) { btn.disabled = false; return renderAskInvite(e.message); }
    if (info.pack) extras = await api("api/extras").catch(() => extras);
    render();
  };
  const go = h("button", { class: "btn primary", type: "submit" }, "Continue");
  $("#join").replaceChildren(
    h("div", { class: "card" }, h("h1", {}, "Join a friend's Minecraft server"),
      h("p", { class: "muted" }, "Open the invite link you were sent, press ", h("strong", {}, "Copy the invite"),
        " there, and paste it here (or paste the whole link). mcsm checks it's really their server, then sets up your game."),
      info.copied_invite ? h("div", { class: "notice mt-s" }, "Found the invite you copied.") : null,
      h("form", { class: "row mt", onsubmit: (e) => { e.preventDefault(); if (input.value.trim()) use(input.value.trim(), go); } },
        h("div", { class: "grow" }, input), go),
      error ? h("div", { class: "notice bad mt-s" }, error) : null),
    info.remembered.length ? h("div", { class: "card" }, h("h2", {}, "Servers you've joined"),
      h("p", { class: "muted small" }, "Update your game for one of them (after the server updates, say):"),
      h("ul", { class: "list" }, info.remembered.map((r) => {
        const b = h("button", { class: "btn small" }, "Update");
        b.addEventListener("click", () => use(r.code, b));
        const state = h("span", { class: "small muted", "data-code": r.code }, "checking…");
        return h("li", {}, h("div", { class: "grow" }, h("strong", {}, r.name), " ", state), b);
      }))) : null,
    h("div", { class: "card" }, h("h2", {}, "Or run a Minecraft server of your own"),
      h("p", { class: "muted small" }, "mcsm sets one up on this computer and keeps it and its mods up to date."),
      h("button", { class: "btn", onclick: async () => {
        await api("api/own-server", {}).catch(() => null);
        $("#join").replaceChildren(h("div", { class: "card" }, h("h1", {}, "Opening mcsm's control panel…"),
          h("p", { class: "muted" }, "It opens in a new tab in a moment. You can close this one.")));
      } }, "Run my own server")),
    h("p", { class: "muted small center" }, "Need help? ", h("a", { href: "https://github.com/silverWRX03/mc-server-management/blob/main/src/mcsm/webui/manual.md#for-friends-joining-a-server",
      target: "_blank", rel: "noopener noreferrer" }, "The user manual: joining a server ↗")));
  input.focus();
  if (info.remembered.length) checkRemembered();
}

// Has each server joined before changed since this computer was set up for it?
async function checkRemembered() {
  const r = await api("api/remembered/check").catch(() => null);
  for (const s of (r && r.servers) || []) {
    const el = document.querySelector(`[data-code="${CSS.escape(s.code)}"]`);
    if (!el) continue;
    el.className = "tag " + (s.error ? "" : s.changed ? "warn" : "ok");
    el.textContent = s.error ? "can't reach it right now" : s.changed ? `changed: update (Minecraft ${s.minecraft})` : "up to date";
    const btn = el.closest("li") && el.closest("li").querySelector("button");
    if (btn && s.changed) btn.classList.add("primary");
  }
}

// A server with a whitelist: ask its owner to let this Minecraft name in.
function askToJoinCard() {
  const name = h("input", { placeholder: "Your Minecraft name", maxlength: 16, autocomplete: "off", "aria-label": "Your Minecraft name" });
  const btn = h("button", { class: "btn", onclick: async () => {
    const v = name.value.trim();
    if (!/^[A-Za-z0-9_]{3,16}$/.test(v)) { toast("Type your Minecraft name (3 to 16 letters, numbers or _).", true); return; }
    btn.disabled = true;
    try {
      const r = await api("api/ask-to-join", { name: v });
      toast({ asked: `Asked. When the owner allows ${v} in their mcsm, you can join.`, "already allowed": `${v} is already allowed in.`,
        "slow down": "Wait a few seconds and try again." }[r.result] || "Asked.", r.result === "slow down");
    } catch (e) { toast(e.message, true); }
    btn.disabled = false;
  } }, "Ask to be let in");
  return h("div", { class: "card" }, h("h2", {}, "This server only lets in players its owner allows"),
    h("p", { class: "muted small" }, "Send your Minecraft name (the one you play with, not your email) and the owner can let you in with one click."),
    h("div", { class: "row" }, name, btn));
}

function render() {
  const root = $("#join");
  if (info.need_invite) return renderAskInvite();
  if (!info.pack) {
    root.replaceChildren(h("div", { class: "card" }, h("h1", {}, "Couldn't reach the server"),
      h("div", { class: "notice bad" }, info.error || "The server didn't answer."),
      h("p", { class: "muted" }, "Check that the server is running and try again, or ask its owner for a new invite."),
      h("button", { class: "btn primary", onclick: load }, "Try again")));
    return;
  }
  const p = info.pack;
  const boxes = info.launchers.map((l) => {
    const box = h("input", { type: "checkbox", name: "launcher", value: l.key, checked: l.found });
    return h("label", { class: "choice launcher" + (l.found ? "" : " missing") }, box,
      h("span", { class: "grow" }, h("strong", {}, l.label), l.found ? h("span", { class: "tag ok" }, "found") : h("span", { class: "tag" }, "not found"),
        l.note ? h("span", { class: "small muted block" }, l.note) : null));
  });
  if (!info.launchers.some((l) => l.found)) boxes[0].querySelector("input").checked = true;
  const go = h("button", { class: "btn primary big", type: "submit" }, "Add to my launchers");
  // Memory for this Minecraft: the server owner's suggestion, changeable to suit this computer.
  const sys = info.system_gb;
  const choices = [2, 3, 4, 5, 6, 8, 10, 12, 14, 16, 20, 24, 32].filter((g) => !sys || g <= Math.max(2, sys - 2) || g === p.memory_gb);
  if (!choices.includes(p.memory_gb)) choices.push(p.memory_gb);
  const memory = h("select", { name: "memory", "aria-label": "Memory for Minecraft" },
    choices.sort((a, b) => a - b).map((g) => h("option", { value: String(g) }, `${g} GB${g === p.memory_gb ? " (suggested by the server)" : ""}`)));
  memory.value = String(p.memory_gb);
  const memHint = h("span", { class: "small muted block" });
  const updateHint = () => {
    const g = Number(memory.value);
    memHint.textContent = sys ? `This computer has ${sys} GB.` + (g > sys - 3 ? " Leave some for the rest of the computer, or Minecraft may crash." : "")
      + (g < p.memory_gb ? " Less than suggested: big modpacks may run slowly or crash." : "") : "";
  };
  memory.addEventListener("change", updateHint);
  updateHint();
  root.replaceChildren(
    h("div", { class: "join-head" },
      p.icon ? h("img", { src: p.icon, alt: "" }) : h("div", { class: "noicon" }),
      h("div", {}, h("h1", {}, p.name), h("div", { class: "muted" }, p.address))),
    h("div", { class: "card" },
      h("p", {}, `This server runs Minecraft ${p.minecraft} with ${LOADERS[p.loader] || p.loader}` +
        (p.loader_version && p.loader !== "vanilla" ? ` ${p.loader_version}` : "") +
        (p.mods.length ? ` and ${p.mods.length} mod${p.mods.length === 1 ? "" : "s"} you need too.` : ".")),
      p.mods.length ? h("details", {}, h("summary", {}, "Show the mods"), h("ul", { class: "small" }, p.mods.map((m) => h("li", {}, m)))) : null,
      h("p", { class: "muted small" }, "mcsm downloads Minecraft's mods straight from Modrinth and CurseForge, checks every file, " +
        "and keeps them in a folder of their own: your other worlds and installations aren't touched. It never asks for your " +
        "Microsoft password; your launcher signs you in.")),
    extrasCard(),
    p.whitelist ? askToJoinCard() : null,
    h("form", { class: "card", onsubmit: async (e) => {
      e.preventDefault();
      const launchers = [...document.querySelectorAll("input[name=launcher]:checked")].map((x) => x.value);
      if (!launchers.length) { toast("Tick at least one launcher.", true); return; }
      go.disabled = true;
      const body = { launchers, memory_gb: Number(memory.value) };
      try { await api("api/setup", body); poll(); }
      catch (err) {
        if (err.status === 409 && err.data && err.data.changes) {
          if (await confirmChanges(err.data.changes)) {
            try { await api("api/setup", { ...body, accept_changes: true }); extras = await api("api/extras").catch(() => extras); poll(); return; }
            catch (e2) { toast(e2.message, true); }
          } else toast("Nothing was changed. You can't join the updated server until you continue.", true);
        } else toast(err.message, true);
        go.disabled = false;
      }
    } },
      h("h2", {}, "Which launchers should have this server?"),
      h("div", { class: "launchers" }, boxes),
      h("label", { class: "mt memory" }, "Memory for Minecraft", memory, memHint),
      h("div", { class: "row mt" }, go)),
    h("div", { id: "progress", class: "card hidden" }, h("h2", {}, "Progress"), h("pre", { id: "log", class: "log" }), h("div", { id: "results" })),
  );
}

let setupRunning = false;
async function poll() {
  $("#progress").classList.remove("hidden");
  const r = await api(`api/progress?since=${seen}`).catch(() => null);
  if (r) {
    seen = r.next;
    const log = $("#log");
    log.textContent += r.lines.map((x) => x + "\n").join("");
    log.scrollTop = log.scrollHeight;
    setupRunning = r.running;
    if (!r.running) { showResults(r.results); return; }
  }
  setTimeout(poll, 800);
}

function showResults(results) {
  const p = info.pack;
  const ok = results.filter((r) => r.ok);
  $("#results").replaceChildren(...[
    h("ul", { class: "list" }, results.map((r) => h("li", {},
      h("div", { class: "grow" }, h("strong", {}, r.label), h("span", { class: "tag " + (r.ok ? "ok" : "bad") }, r.ok ? "ready" : "failed"),
        h("div", { class: "small muted" }, r.message)),
      r.ok ? h("button", { class: "btn small", onclick: () => api("api/open", { launcher: r.launcher }).then((x) => x.ok || toast("Couldn't open it; open it yourself.", true)) },
        OPEN_LABEL[r.launcher]) : null))),
    p.manual.length ? h("div", { class: "notice warn mt" }, h("strong", {}, "Download these yourself: "),
      "their authors don't allow automatic downloads. Put them in the instance's mods folder.",
      h("ul", {}, p.manual.map((m) => h("li", {}, h("a", { href: m.url, target: "_blank", rel: "noopener noreferrer" }, m.name))))) : null,
    ok.length ? h("div", { class: "notice mt" }, h("strong", {}, "Next: "),
      `pick "${p.name}" in your launcher and press Play. ` +
      (p.quick_play ? "Minecraft joins the server by itself." : `Then choose Multiplayer: ${p.name} is in the list.`) +
      " If the server updates later, open mcsm again and pick it under “Servers you've joined” to update your mods.") : null,
    h("div", { class: "row mt" }, h("button", { class: "btn", onclick: async () => {
      await api("api/quit", {}).catch(() => null);
      document.body.replaceChildren(h("main", { class: "join" }, h("div", { class: "card" }, h("h1", {}, "All done"),
        h("p", { class: "muted" }, "You can close this tab."))));
    } }, "I'm done"))].filter(Boolean));
}

async function load() {
  try { info = await api("api/info"); } catch (e) { info = { pack: null, error: e.message, launchers: [] }; }
  if (info.pack) extras = await api("api/extras").catch(() => extras);
  render();
  if (info.pack && (info.running || info.finished)) {  // the tab was closed and mcsm opened it again
    const go = document.querySelector("form button[type=submit]");
    if (go && info.running) go.disabled = true;
    poll();
    $("#progress").scrollIntoView({ block: "start" });
  }
}
// Closing the tab doesn't stop mcsm, but while it's setting up Minecraft, check first.
// (Opening mcsm again, or "Open in mcsm" on the invite page, brings this page back.)
window.addEventListener("beforeunload", (e) => { if (setupRunning) { e.preventDefault(); e.returnValue = ""; } });
setInterval(() => fetch(`api/progress?since=${seen}`).catch(() => null), 30000);  // "still open"
load();
