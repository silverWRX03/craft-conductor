"use strict";
// The homepage: the section on screen marked in the menu, and the interactive demo (nav.js has the
// theme switch and the menu on small screens). The demo is the real control panel in a sandboxed frame
// (demo/host.js explains how it's kept apart); this page opens it over the website (blurred and
// inactive behind it), with the Leave demo bar on its left.
(function () {
  const $ = (id) => document.getElementById(id);
  const root = document.documentElement;
  const website = $("website"), sidebar = $("site-nav"), menu = $("menu-toggle");
  const overlay = $("demo-overlay"), intro = $("demo-intro"), stage = $("demo-stage"), holder = $("frame-holder");

  // No third-party connection until the visitor chooses to load the walkthrough.
  $("watch-video").addEventListener("click", () => {
    const player = document.createElement("iframe");
    player.src = "https://www.youtube-nocookie.com/embed/7facGOmax5M?autoplay=1&rel=0";
    player.title = "Craft Conductor product walkthrough";
    player.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
    player.allowFullscreen = true;
    player.referrerPolicy = "strict-origin-when-cross-origin";
    $("watch-video").replaceWith(player);
    player.focus();
  }, { once: true });

  // Keep the approved desktop hero height independent of the larger carousel.
  // The feature section is at least 1.5 times as tall and can grow to fit its screenshots.
  // Stacked mobile content keeps its natural height.
  const hero = $("home"), features = $("features");
  const desktopHero = window.matchMedia("(min-width: 1101px)");
  if ("ResizeObserver" in window) {
    const sizeHero = () => {
      if (desktopHero.matches && $("feature-carousel").classList.contains("ready")) {
        const style = getComputedStyle(hero);
        const contentHeight = Math.max(hero.querySelector(".hero-text").offsetHeight, hero.querySelector(".video-walkthrough").offsetHeight);
        const requiredHeight = contentHeight + parseFloat(style.paddingTop) + parseFloat(style.paddingBottom) + 1;
        features.style.setProperty("--features-min-height", `${Math.ceil(requiredHeight * 1.5)}px`);
        hero.style.setProperty("--hero-min-height", `${requiredHeight}px`);
      } else {
        hero.style.removeProperty("--hero-min-height");
        features.style.removeProperty("--features-min-height");
      }
    };
    // Apply size changes in the next frame, outside ResizeObserver delivery (including WebKit).
    let sizeFrame = 0;
    const scheduleSize = () => {
      if (!sizeFrame) sizeFrame = requestAnimationFrame(() => { sizeFrame = 0; sizeHero(); });
    };
    const sizes = new ResizeObserver(scheduleSize);
    sizes.observe(hero.querySelector(".hero-text"));
    sizes.observe(hero.querySelector(".video-walkthrough"));
    desktopHero.addEventListener("change", scheduleSize);
  }

  // The section on screen is marked in the menu.
  const links = [...document.querySelectorAll(".nav-link[data-section]")];
  if ("IntersectionObserver" in window) {
    const seen = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) for (const a of links) {
        const on = a.dataset.section === e.target.id;
        a.classList.toggle("active", on);
        if (on) a.setAttribute("aria-current", "true"); else a.removeAttribute("aria-current");
      }
    }, { rootMargin: "-10% 0px -80% 0px" });
    for (const s of document.querySelectorAll("main section[id]")) seen.observe(s);
  }

  // ------------------------------------------------------------ which release the demo shows
  fetch("demo/version.json", { cache: "no-store" }).then((r) => r.ok ? r.json() : Promise.reject(new Error(String(r.status)))).then((v) => {
    $("represented-version").textContent = `Demo: ${v.version} · ${v.channel}`;
    const line = $("demo-version");
    line.textContent = v.channel === "development"
      ? `This demo is a development build of Craft Conductor (${v.version}), not a published release. `
      : `The demo is Craft Conductor ${v.version} (${v.channel}), the newest published release. `;
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
