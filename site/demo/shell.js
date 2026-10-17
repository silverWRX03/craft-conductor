"use strict";
// The phone demo (what the website's QR code opens): the real control panel full screen, with this
// device's own made-up data (nothing is shared with other devices or sent anywhere). It can be
// installed as an app where the browser offers it; its service worker covers only demo/.
(function () {
  const params = new URLSearchParams(location.search);
  const scenario = params.get("mode") === "new" ? "new" : "existing";
  const mobile = params.get("mobile") === "1" || matchMedia("(max-width: 700px)").matches;
  const stage = document.getElementById("shell-stage");
  const pick = document.getElementById("shell-scenario");
  const frame = window.CraftDemoHost.frame();
  stage.append(frame);
  const theme = () => { try { return localStorage.getItem("cc-site-theme") === "light" ? "day" : "night"; } catch (_) { return "night"; } };
  const host = window.CraftDemoHost.attach(frame, { app: "app/", scenario, mobile, theme });
  window.craftDemo = host;  // (for the website's own tests)
  pick.value = scenario;
  pick.addEventListener("change", () => {
    const url = new URL(location.href);
    url.searchParams.set("mode", pick.value);
    history.replaceState(null, "", url);
    host.start(pick.value, { mobile });
  });
  document.getElementById("shell-reset").addEventListener("click", () => host.reset());
  host.start(scenario, { mobile });

  // Installing (Chrome, Edge, Android): the browser's own prompt, only when asked.
  let prompt = null;
  const install = document.getElementById("shell-install");
  addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); prompt = e; install.hidden = false; });
  install.addEventListener("click", async () => { if (!prompt) return; prompt.prompt(); await prompt.userChoice.catch(() => null); prompt = null; install.hidden = true; });
  addEventListener("appinstalled", () => { install.hidden = true; });
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js", { scope: "./" }).catch(() => { /* the demo works without it */ });
})();
