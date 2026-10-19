"use strict";
// The website's sidebar, on every page that has it (the homepage, the testing dashboard): the day and
// night switch (remembered for the whole site) and the menu on small screens.
(function () {
  const $ = (id) => document.getElementById(id);
  const root = document.documentElement;
  const sidebar = $("site-nav"), menu = $("menu-toggle"), scrim = $("site-scrim");

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
})();
