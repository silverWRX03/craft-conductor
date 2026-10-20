"use strict";
// Loaded in index.html's <head>, before anything is drawn: day or night, and Classic or Modern, so the page
// never shows the wrong one first. app.js keeps both up to date afterwards (applyTheme, applyStyle), with the
// same keys. Who will sign in isn't known yet, so the style is the one last used in this browser (Modern if
// none: index.html says so); each person's own choice replaces it once they're signed in (styleSignedIn).
(function () {
  const root = document.documentElement;
  try {
    const theme = localStorage.getItem("craft-conductor-theme");
    root.dataset.theme = theme === "day" || theme === "night" ? theme
      : window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "day" : "night";
    const style = localStorage.getItem("craft-conductor-style");
    if (style === "classic" || style === "modern") root.dataset.style = style;
  } catch (_) { /* private mode: app.js picks the theme; the style stays Modern */ }
})();
