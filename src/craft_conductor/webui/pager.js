"use strict";
// Shared by the control panel (app.js) and the friend's page (join.js).
// ---------------------------------------------------- results that keep coming (mod browsers)
// A search's first 20 results, then the next 20 asked for in the background once the reader gets
// to about the 12th row of the newest batch (8 loaded rows left below), and so on to the end.
// - New rows are appended: scroll position, focus, ticked boxes and the open details stay put.
// - One request at a time; results are keyed (source:id), so one a provider moved to the next
//   page isn't listed twice; a reply to an older search never lands in a newer one.
// - The server says where the end is ("next": null), counting results left out for having no
//   build for this version, so a batch that's all left out doesn't stop the list.
// - Nothing depends on scrolling alone: the bottom row has a "Load more" button (for keyboards,
//   and browsers without IntersectionObserver), and new results are announced politely.
const PAGER_AHEAD = 8;        // loaded rows left below the marker when the next batch is asked for
const PAGER_EMPTY_RUN = 3;    // batches in a row with nothing to show (each one also asks about every result's builds) before waiting for a button press

// fetchPage(offset) -> {results, next, ...}; row(item) -> element; key(item) -> string;
// empty() -> what an empty search shows; onPage(reply, first) after each batch (counts, notes);
// failed(error) -> false to show nothing (e.g. signed out); leaveOut(item) -> true for results not to
// show (e.g. mods already added), counted for onPage as reply.left_out.
function resultPager({ list, fetchPage, row, key, empty, onPage, failed, leaveOut }) {
  const head = h("div", { class: "pager-head" });   // notes above the results (hidden ones, …)
  const rows = h("div", { class: "pager-rows" });
  const msg = h("span", { class: "muted small" });
  const btn = h("button", { type: "button", class: "btn small", onclick: () => press() }, "Load more");
  const foot = h("div", { class: "pager-foot", tabindex: "-1" }, msg, btn);
  const live = h("p", { class: "sr-only", "aria-live": "polite" });
  const items = new Map();   // key -> { item, el }
  const leftOut = new Set(); // keys of results left out (each counted once)
  let gen = 0, next = null, loading = false, error = false, emptyRun = 0, io = null;

  const say = (text) => { live.textContent = text; };
  // The bottom row: what's happening, and the button that does what scrolling does.
  const showFoot = () => {
    const hadFocus = foot.contains(document.activeElement);
    foot.classList.toggle("busy", loading);
    let label = "Load more", note = "";
    if (loading) { label = "Loading more…"; }
    else if (error) { note = "Couldn't load more."; label = "Try again"; }
    else if (next === null) { note = items.size ? "That's everything" : ""; label = ""; }
    else if (emptyRun >= PAGER_EMPTY_RUN) { note = "Nothing to show in the last few pages."; label = "Keep looking"; }
    msg.textContent = t(note);
    btn.textContent = t(label);
    btn.classList.toggle("hidden", !label);
    btn.setAttribute("aria-disabled", loading ? "true" : "false");
    if (hadFocus && !label) foot.focus({ preventScroll: true });  // (never lose the keyboard's place)
  };
  const press = () => { if (loading) return; emptyRun = 0; error = false; more(); };
  // Watch the row with PAGER_AHEAD loaded rows after it (or the bottom row): when it's on screen,
  // or already scrolled past, the next batch is fetched.
  const arm = () => {
    if (io) io.disconnect();
    if (loading || error || next === null || emptyRun >= PAGER_EMPTY_RUN || !("IntersectionObserver" in window)) return;
    const marker = rows.children[rows.children.length - 1 - PAGER_AHEAD] || foot;
    io = io || new IntersectionObserver((entries) => {
      const top = Math.max(0, list.getBoundingClientRect().top);
      if (entries.some((e) => e.boundingClientRect.height > 0 && (e.isIntersecting || e.boundingClientRect.bottom <= top))) more();
    });
    io.observe(marker);  // (observing reports where it is right away, so a list that doesn't fill its box keeps going)
  };
  const more = async () => {
    if (loading || next === null) return;
    const mine = gen, first = items.size === 0 && !list.contains(rows), offset = next;
    const hadFocus = foot.contains(document.activeElement);
    loading = true;
    if (!first) showFoot();
    if (io) io.disconnect();
    let r;
    try { r = await fetchPage(offset); }
    catch (e) {
      if (mine !== gen) return;
      loading = false;
      if (first) {  // nothing to keep: say what went wrong in the list's place
        next = null;
        if (!failed || failed(e) !== false) list.replaceChildren(h("div", { class: "notice bad" }, e.message));
        return;
      }
      error = true;
      showFoot();
      say(t("Couldn't load more."));
      return;
    }
    if (mine !== gen) return;  // an older search's answer
    loading = false;
    const fresh = [];
    r.left_out = 0;
    for (const item of r.results || []) {
      const k = key(item);
      if (items.has(k) || leftOut.has(k)) continue;
      if (leaveOut && leaveOut(item)) { leftOut.add(k); r.left_out++; continue; }
      const el = row(item);
      items.set(k, { item, el });
      fresh.push(el);
    }
    next = typeof r.next === "number" && r.next > offset ? r.next : null;
    emptyRun = fresh.length ? 0 : emptyRun + 1;
    if (first) list.replaceChildren(head, rows, foot, live);
    rows.append(...fresh);
    if (!items.size && next === null) rows.replaceChildren(empty());  // (perhaps with a note above on what was left out)
    if (onPage) {  // (a note above that grows mustn't push the rows being read down; not every browser holds them)
      const was = rows.getBoundingClientRect().top;
      onPage(r, first);
      const moved = rows.getBoundingClientRect().top - was;
      if (moved && list.scrollTop > 0) list.scrollTop += moved;
    }
    showFoot();
    if (!first && (fresh.length || next === null)) {
      say((fresh.length ? `${fresh.length} ${t("more results loaded.")} ` : "") + (next === null ? t("That's everything") : ""));
    }
    if (!fresh.length && next !== null && emptyRun < PAGER_EMPTY_RUN) { more(); return; }  // all left out: on to the next batch
    if (hadFocus && fresh.length) fresh[0].focus({ preventScroll: false });  // pressed Load more: on to the new rows
    arm();
  };

  return {
    head,
    // A fresh first page (new words, filters, sort, source, version…).
    reset(searching = "Searching…") {
      gen++;
      if (io) io.disconnect();
      items.clear(); leftOut.clear();
      next = 0; loading = false; error = false; emptyRun = 0;
      head.replaceChildren(); rows.replaceChildren(); say("");
      list.scrollTop = 0;
      list.replaceChildren(h("p", { class: "empty" }, searching));
      more();
    },
    // Forget the search: replies on their way are dropped, nothing is watched (the browser closed,
    // or the list shows something else).
    stop() { gen++; next = null; loading = false; if (io) { io.disconnect(); io = null; } },
    el: (k) => (items.get(k) || {}).el || null,
    // Draw rows again in place (e.g. ones just added), for the items ``which`` picks.
    redraw(which) {
      for (const entry of items.values()) {
        if (!which(entry.item)) continue;
        const el = row(entry.item);
        entry.el.replaceWith(el);
        entry.el = el;
      }
      arm();  // (the marker may have been one of them)
    },
  };
}

// The mod lists (the mod browser, World generation's mods, a single-player game's mods, the friend's
// page): a resultPager over a search address that answers ``url?<words and filters>&offset=N``.
// search(params) starts again from the first page; every later page asks exactly what the first did.
// Results are keyed source:id unless ``key`` says otherwise.
function searchPager({ url, key = (m) => `${m.source}:${m.id}`, ...opts }) {
  let asked = new URLSearchParams();
  const pager = resultPager({ ...opts, key,
    fetchPage: (offset) => { const p = new URLSearchParams(asked); p.set("offset", String(offset)); return api(`${url}?${p}`); } });
  return { ...pager, search(params) { asked = new URLSearchParams(params); pager.reset(); } };
}
