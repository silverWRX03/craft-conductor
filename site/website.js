"use strict";
// The homepage: the theme switch, the menu on small screens, and the interactive demo. The demo is
// the real control panel in a sandboxed frame (demo/host.js explains how it's kept apart); this page
// opens it over the website (blurred and inactive behind it), with the Leave demo bar on its left.
(function () {
  const $ = (id) => document.getElementById(id);
  const root = document.documentElement;
  const website = $("website"), sidebar = $("site-nav"), menu = $("menu-toggle"), scrim = $("site-scrim");
  const overlay = $("demo-overlay"), intro = $("demo-intro"), stage = $("demo-stage"), holder = $("frame-holder");

  // ------------------------------------------------------------ day and night
  const THEME_KEY = "cc-site-theme";
  const toggle = $("theme-toggle");
  const setTheme = (dark) => {
    root.dataset.theme = dark ? "night" : "day";
    toggle.setAttribute("aria-checked", String(dark));
    document.querySelector('meta[name="theme-color"]').setAttribute("content", dark ? "#0A0A0A" : "#F4F4F4");
  };
  let saved = null;
  try { saved = localStorage.getItem(THEME_KEY); } catch (_) { /* private mode */ }
  setTheme(saved !== "light");
  toggle.addEventListener("click", () => {
    const dark = root.dataset.theme !== "night";
    setTheme(dark);
    try { localStorage.setItem(THEME_KEY, dark ? "dark" : "light"); } catch (_) { /* private mode */ }
  });

  // ------------------------------------------------------------ the menu on phones
  const openNav = (open) => {
    sidebar.classList.toggle("open", open);
    scrim.hidden = !open;
    menu.setAttribute("aria-expanded", String(open));
    if (open) sidebar.querySelector("a").focus();
  };
  menu.addEventListener("click", () => openNav(!sidebar.classList.contains("open")));
  scrim.addEventListener("click", () => { openNav(false); menu.focus(); });
  sidebar.addEventListener("click", (e) => { if (e.target.closest("a") && sidebar.classList.contains("open")) openNav(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && sidebar.classList.contains("open")) { openNav(false); menu.focus(); } });
  // The section on screen is marked in the menu.
  const links = [...document.querySelectorAll(".nav-link[data-section]")];
  if ("IntersectionObserver" in window) {
    const seen = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) for (const a of links) {
        const on = a.dataset.section === e.target.id;
        a.classList.toggle("active", on);
        if (on) a.setAttribute("aria-current", "true"); else a.removeAttribute("aria-current");
      }
    }, { rootMargin: "-30% 0px -60% 0px" });
    for (const s of document.querySelectorAll("main section[id]")) seen.observe(s);
  }

  // ------------------------------------------------------------ which release the demo shows
  fetch("demo/version.json", { cache: "no-store" }).then((r) => r.ok ? r.json() : Promise.reject(new Error(String(r.status)))).then((v) => {
    const label = v.channel === "development" ? `the development version (${v.version})` : `Craft Conductor ${v.version} (${v.channel})`;
    $("represented-version").textContent = `Demo: ${v.version} · ${v.channel}`;
    const line = $("demo-version");
    line.textContent = `The demo is ${label}, the newest published release it follows. `;
    if (v.release_url && /^https:\/\/github\.com\//.test(v.release_url)) {
      const a = document.createElement("a");
      a.href = v.release_url;
      a.textContent = "Its release notes";
      line.append(a, ".");
    }
  }).catch(() => { $("represented-version").textContent = "Free and open source"; });

  // ------------------------------------------------------------ the demo
  const frame = window.CraftDemoHost.frame();
  holder.append(frame);
  const host = window.CraftDemoHost.attach(frame, { app: "demo/app/", theme: () => root.dataset.theme });
  window.craftDemo = host;  // (for the website's own tests)
  const names = { new: "My first server", existing: "Family Survival (an existing server)" };
  let opener = null, phone = false;
  const status = (text) => { $("demo-status").textContent = text || ""; };

  function openDemo(scenario, from) {
    opener = from || document.activeElement;
    overlay.hidden = false;
    website.inert = true; sidebar.inert = true; menu.inert = true;
    document.body.classList.add("demo-open");
    if (scenario === "new" || scenario === "existing") start(scenario);
    else showChoices();
  }
  function closeDemo() {
    if (overlay.hidden) return;
    host.stop();
    overlay.hidden = true;
    website.inert = false; sidebar.inert = false; menu.inert = false;
    document.body.classList.remove("demo-open");
    if (opener && opener.isConnected) opener.focus();
  }
  function showChoices() {
    host.stop();
    stage.hidden = true; intro.hidden = false;
    $("demo-resume").hidden = !(host.hasSaved("new") || host.hasSaved("existing"));
    $("demo-heading").focus();
  }
  function start(scenario) {
    intro.hidden = true; stage.hidden = false;
    $("demo-which").textContent = names[scenario];
    $("demo-fail").checked = false;
    setPhone(phone, false);
    host.start(scenario, { mobile: phone });
    frame.focus();
    status(scenario === "new" ? "The New server page is open: pick a server type and create your first server." : "Family Survival's Dashboard is open. A friend will ask to join in a moment.");
  }
  function setPhone(on, reload = true) {
    phone = on;
    $("demo-workspace").classList.toggle("phone", on);
    $("phone-side").hidden = !on;
    $("demo-view").setAttribute("aria-pressed", String(on));
    $("demo-view").textContent = on ? "Desktop view" : "Phone view";
    if (reload) host.start(host.scenario, { mobile: on });
  }

  for (const b of document.querySelectorAll(".launch-demo")) b.addEventListener("click", () => openDemo(b.dataset.scenario, b));
  for (const b of document.querySelectorAll("[data-start]")) b.addEventListener("click", () => start(b.dataset.start));
  $("leave-demo").addEventListener("click", closeDemo);
  $("demo-shade").addEventListener("click", closeDemo);
  $("demo-choices").addEventListener("click", showChoices);
  $("demo-view").addEventListener("click", () => setPhone(!phone));
  $("demo-reset").addEventListener("click", () => { host.reset(); $("demo-fail").checked = false; status("The demo started again from the beginning."); });
  $("demo-forget").addEventListener("click", () => { host.reset(); host.stop(); $("demo-resume").hidden = true; status(""); });
  $("demo-request").addEventListener("click", () => { host.command("join-request"); status("A fictional friend used your invite and asked to join: see the Players page."); });
  $("demo-fail").addEventListener("change", (e) => {
    host.command("fail-next-update", { on: e.target.checked });
    status(e.target.checked ? "The next update will fail to start, and Craft Conductor will roll it back." : "Updates work normally again.");
  });
  // The QR code: on this computer, the phone-sized demo; the phone itself opens the link.
  $("phone-qr").addEventListener("click", () => { phone = true; openDemo("existing", $("phone-qr")); });
  host.on((type, data) => {
    if (type === "escape") closeDemo();
    else if (type === "unhandled") status("This part of the demo isn't simulated yet. Nothing was sent anywhere.");
    else if (type === "event" && data && data.kind === "update-failed") { $("demo-fail").checked = false; status("That update failed on purpose and was rolled back. Updates work normally again."); }
    void data;
  });
  document.addEventListener("keydown", (e) => {
    if (overlay.hidden || e.key !== "Escape") return;
    e.preventDefault();
    closeDemo();
  });
  // Opened from a link (#demo-new, #demo-existing): straight into that demo.
  const m = location.hash.match(/^#demo-(new|existing)$/);
  if (m) openDemo(m[1], null);
})();
