"use strict";
// Demo-only service worker, confined by scope to /craft-conductor/demo/.
// No push, no notifications, no filesystem access, no caching and no fetch interception.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", event => event.waitUntil(self.clients.claim()));
