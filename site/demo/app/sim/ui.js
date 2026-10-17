"use strict";
// What the demo adds on top of the real page, kept small and in one corner: that it's a demo with
// made-up data, a hint for the page on show, the explanations for things the demo can't do, and
// the notifications a phone would get. All text is set as text (never HTML).
(function () {
  const sim = window.CCSim;
  const make = (tag, cls, text) => { const el = document.createElement(tag); if (cls) el.className = cls; if (text) el.textContent = text; return el; };
  let root, hintBox, notes, pushes;
  const HINTS = [
    [/^#browse|\/mods$/, "Mods here come from the demo's sample catalog: a fixed set saved for the demo, not live Modrinth or CurseForge results. Nothing is downloaded."],
    [/^#new$/, "Making a server here adds it to this demo only: nothing is downloaded or installed on your computer."],
    [/\/friends$/, "Invite links in the demo are made up (they end in .invalid) and don't lead anywhere."],
    [/\/console$/, "Try list, say hello, whitelist add Steve or gamerule keepInventory true: a stand-in Minecraft answers."],
    [/\/updates$/, "Updates are simulated. Use the demo controls (Make the next update fail) to see a failed update roll back."],
    [/\/backups$/, "Backups are simulated: restoring puts the demo's mods and Minecraft version back as they were."],
    [/^#craft-conductor$/, "Settings you change are kept only in this browser, for the demo. Nothing asks your browser or computer for anything."],
  ];
  // A page's hint shows for a while when the page opens, then folds into the badge (a click opens it).
  let fold = null, pinned = false;
  const browsing = () => !!document.querySelector(".inpage-browser, .browse") || document.body.classList.contains("browse-mode");
  function hint(opening = true) {
    if (!hintBox) return;
    const found = browsing() ? HINTS[0] : HINTS.find(([re]) => re.test(location.hash));
    hintBox.textContent = found ? found[1] : "";
    if (opening && found && !sim.mobile) setOpen(true);
    hintBox.hidden = !found || root.classList.contains("collapsed");
    clearTimeout(fold);
    if (!pinned) fold = setTimeout(() => setOpen(false), 12000);
  }
  function setOpen(open) {
    root.classList.toggle("collapsed", !open);
    root.querySelector(".cc-demo-badge-head").setAttribute("aria-expanded", String(open));
    hintBox.hidden = !open || !hintBox.textContent;
  }
  function note(text, kind = "note") {
    if (!notes) return;
    const el = make("div", "cc-demo-note " + kind);
    el.setAttribute("role", "status");
    el.append(make("strong", "", kind === "push" ? "📱 " : "ℹ "), make("span", "", text));
    const close = make("button", "cc-demo-close", "✕");
    close.type = "button";
    close.title = "Dismiss";
    close.setAttribute("aria-label", "Dismiss");
    close.addEventListener("click", () => el.remove());
    el.append(close);
    (kind === "push" ? pushes : notes).append(el);
    setTimeout(() => el.remove(), kind === "push" ? 9000 : 8000);
    while (notes.childElementCount > 3) notes.firstChild.remove();
  }
  function build() {
    root = make("aside", "cc-demo-badge");
    root.setAttribute("aria-label", "About this demo");
    const head = make("button", "cc-demo-badge-head");
    head.type = "button";
    head.setAttribute("aria-expanded", "true");
    head.append(make("span", "cc-demo-dot"), make("span", "", "DEMO · MADE-UP DATA"));
    head.addEventListener("click", () => {
      const open = root.classList.contains("collapsed");
      pinned = open;
      setOpen(open);
      clearTimeout(fold);
    });
    hintBox = make("p", "cc-demo-hint");
    root.append(head, hintBox);
    notes = make("div", "cc-demo-notes");
    pushes = make("div", "cc-demo-pushes");
    pushes.setAttribute("aria-live", "polite");
    notes.setAttribute("aria-live", "polite");
    document.body.append(root, notes, pushes);
    if (sim.mobile) root.classList.add("collapsed");
    hint();
  }
  sim.on((type, data) => {
    if (type === "note" && data && data.text) note(data.text);
    else if (type === "explained" && data && data.what) note("Demo: " + data.what);
    else if (type === "notification" && data) note(`${data.phone ? "Phone notification (simulated)" : "Notification (simulated)"}: ${data.title}${data.body ? ". " + data.body : ""}`, "push");
    else if (type === "unhandled" && data) note(`Demo: this part isn't simulated yet (${data.path}). Nothing was sent anywhere.`);
  });
  addEventListener("hashchange", () => hint());
  // The mod browser opens over a page (no new address): its hint shows while it's open.
  let wasBrowsing = false, queued = false;
  new MutationObserver(() => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; const now = browsing(); if (now !== wasBrowsing) { wasBrowsing = now; hint(now); } });
  }).observe(document.documentElement, { childList: true, subtree: true });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", build); else build();
})();
