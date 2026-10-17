"use strict";
// Craft Conductor's service worker: shows phone notifications (see push.py) and opens the right page
// when one is tapped. It doesn't cache the control panel: it always shows what's current.

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (_) { data = { body: event.data ? event.data.text() : "" }; }
  const title = data.title || "Craft Conductor";
  event.waitUntil(Promise.all([self.registration.showNotification(title, {
    body: data.body || "",
    icon: "/icon-192.png",
    badge: "/icon-192.png",
    tag: data.tag || undefined,
    renotify: !!data.tag,
    data: { url: typeof data.url === "string" && /^\/(?![\/\\])/.test(data.url) ? data.url : "/" },  // (a page here, never another site)
  }), keepForBell(title, data).catch(() => null)]));
});

// The page's bell (app.js, bellTakePushes) lists the phone notifications this device got: each is kept here,
// with whose device it is, until the page takes it (the page may be closed when it comes). Text only, capped.
const BELL_DB = "craft-conductor-bell", BELL_MAX = 100;
function keepForBell(title, data) {
  const push = { time: Date.now() / 1000, title: String(title).slice(0, 80), body: String(data.body || "").slice(0, 300),
    sid: typeof data.sid === "string" ? data.sid.slice(0, 64) : null, who: typeof data.who === "string" ? data.who.slice(0, 80) : "" };
  return new Promise((resolve, reject) => {
    const open = indexedDB.open(BELL_DB, 1);
    open.onupgradeneeded = () => open.result.createObjectStore("pushes", { autoIncrement: true });
    open.onerror = () => reject(open.error);
    open.onsuccess = () => {
      const db = open.result;
      const tx = db.transaction("pushes", "readwrite");
      const store = tx.objectStore("pushes");
      store.add(push);
      const keys = store.getAllKeys();
      keys.onsuccess = () => keys.result.slice(0, Math.max(0, keys.result.length - BELL_MAX)).forEach((k) => store.delete(k));
      tx.oncomplete = () => { db.close(); resolve(); };
      tx.onerror = () => { db.close(); reject(tx.error); };
    };
  }).then(() => self.clients.matchAll({ type: "window" })).then((open) => open.forEach((c) => c.postMessage({ bell: true })));
}

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data && event.notification.data.url || "/", self.location.origin).href;
  event.waitUntil((async () => {
    const open = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const c of open) {
      if (new URL(c.url).origin === self.location.origin) {
        await c.focus();
        if ("navigate" in c) await c.navigate(url);
        return;
      }
    }
    await self.clients.openWindow(url);
  })());
});

// (A fetch handler lets browsers offer "Install app"; it passes everything straight through.)
self.addEventListener("fetch", () => {});
