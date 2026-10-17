"use strict";
// The phone demo's service worker (registered by shell.js with scope demo/ only): it lets the demo
// be installed as an app and open without a connection. It never handles a page outside demo/
// (the website, the invite page, the testing dashboard), and the sandboxed control panel's frame
// isn't served by it at all. Network first, so a new release's demo shows as soon as it's online.
const CACHE = "craft-conductor-demo-shell-v1";
const SHELL = ["./", "index.html", "shell.css", "shell.js", "host.js", "manifest.webmanifest", "icon-192.png", "icon-512.png"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k.startsWith("craft-conductor-demo-") && k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  const scope = new URL(self.registration.scope);
  if (e.request.method !== "GET" || url.origin !== scope.origin || !url.pathname.startsWith(scope.pathname)) return;
  if (url.pathname.startsWith(scope.pathname + "app/")) return;  // (the panel itself: always from the network)
  e.respondWith(fetch(e.request).then((res) => {
    if (res.ok && SHELL.some((p) => new URL(p, scope).pathname === url.pathname)) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); }
    return res;
  }).catch(() => caches.match(e.request, { ignoreSearch: url.pathname === scope.pathname || url.pathname.endsWith("/index.html") })));
});
