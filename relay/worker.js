// Craft Conductor's mod-conflict relay: a Cloudflare Worker (see relay/README.md).
//
// POST /report          one conflict "Find which mods break it" found, sent only by people who
//                       switched on sharing: {loader, minecraft, mod, with: [mod ids]}.
// GET  /conflicts.json  the conflicts reported by at least THRESHOLD different people.
//
// Anonymous: nothing about the sender is kept but a salted hash of their address (to count
// different people and limit how often one sends), and reports carry only mod ids and versions.
// Needs a KV namespace bound as CONFLICTS and a secret SALT.

const THRESHOLD = 3;          // different people before a conflict is listed
const PER_DAY = 20;           // reports one address may send a day
const MAX_REPORTERS = 20;     // kept per conflict (enough to count past THRESHOLD)
const ID = /^[a-z0-9][a-z0-9_.-]{0,63}$/;
const VERSION = /^\d+\.\d+(\.\d+)?(-[a-z0-9.]{1,20})?$/;
const LOADERS = new Set(["fabric", "quilt", "neoforge", "forge", "paper", "purpur"]);

const json = (body, status = 200, extra = {}) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": "*", ...extra } });

async function sha256(text) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function report(request, env) {
  if (!env.SALT || env.SALT.length < 16) return json({ error: "the relay isn't set up (SALT)" }, 500);
  const length = Number(request.headers.get("Content-Length") || 0);
  if (length > 2048) return json({ error: "too large" }, 413);
  let r;
  try { r = JSON.parse(await request.text()); } catch (_) { return json({ error: "bad JSON" }, 400); }
  const loader = String(r.loader || "").toLowerCase(), minecraft = String(r.minecraft || "").toLowerCase();
  const mod = String(r.mod || "").toLowerCase();
  const withMods = [...new Set((Array.isArray(r.with) ? r.with : []).map((x) => String(x).toLowerCase()))].filter((x) => x !== mod).sort();
  if (!LOADERS.has(loader) || !VERSION.test(minecraft) || !ID.test(mod) || withMods.length > 4 || !withMods.every((x) => ID.test(x))) {
    return json({ error: "that isn't a conflict report" }, 400);
  }
  const who = await sha256(env.SALT + "|" + (request.headers.get("CF-Connecting-IP") || ""));
  const day = new Date().toISOString().slice(0, 10);
  const limitKey = `rate:${day}:${who.slice(0, 32)}`;
  const sent = Number((await env.CONFLICTS.get(limitKey)) || 0);
  if (sent >= PER_DAY) return json({ ok: false, error: "slow down" }, 429);
  await env.CONFLICTS.put(limitKey, String(sent + 1), { expirationTtl: 2 * 86400 });

  const key = "c:" + (await sha256([loader, minecraft, mod, ...withMods].join("|"))).slice(0, 40);
  const stored = (await env.CONFLICTS.getWithMetadata(key, { type: "json" })) || {};
  const reporters = new Set((stored.value && stored.value.reporters) || []);
  reporters.add(who.slice(0, 16));
  const list = [...reporters].slice(-MAX_REPORTERS);
  const now = Math.floor(Date.now() / 1000);
  // (the listing reads the metadata only, so everything /conflicts.json shows lives there)
  const meta = { l: loader, v: minecraft, m: mod, w: withMods, n: list.length, t: now };
  await env.CONFLICTS.put(key, JSON.stringify({ reporters: list }), { metadata: meta, expirationTtl: 400 * 86400 });
  return json({ ok: true, reports: list.length });
}

async function listing(request, env, ctx) {
  const cache = caches.default;
  const hit = await cache.match(request);
  if (hit) return hit;
  const out = [];
  let cursor;
  do {
    const page = await env.CONFLICTS.list({ prefix: "c:", cursor });
    for (const k of page.keys) {
      const m = k.metadata;
      if (m && m.n >= THRESHOLD) out.push({ loader: m.l, minecraft: m.v, mod: m.m, with: m.w, reports: m.n, last: m.t });
    }
    cursor = page.list_complete ? null : page.cursor;
  } while (cursor && out.length < 20000);
  const response = json({ format: 1, threshold: THRESHOLD, conflicts: out }, 200, { "Cache-Control": "public, max-age=3600" });
  ctx.waitUntil(cache.put(request, response.clone()));
  return response;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    try {
      if (request.method === "POST" && url.pathname === "/report") return await report(request, env);
      if (request.method === "GET" && url.pathname === "/conflicts.json") return await listing(request, env, ctx);
      if (request.method === "GET" && url.pathname === "/") {
        return new Response("Craft Conductor's mod-conflict relay. The shared list: /conflicts.json\n",
          { headers: { "Content-Type": "text/plain; charset=utf-8" } });
      }
      return json({ error: "not found" }, 404);
    } catch (e) {
      return json({ error: "the relay had a problem" }, 500);
    }
  },
};
