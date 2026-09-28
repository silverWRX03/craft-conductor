// Runs relay/worker.js against fake Cloudflare storage (see tests/test_relay.py).
import { pathToFileURL } from "node:url";
const worker = (await import(pathToFileURL(process.argv[2]).href)).default;

class KV {
  constructor() { this.data = new Map(); }
  async get(key) { const v = this.data.get(key); return v ? v.value : null; }
  async getWithMetadata(key, opts) {
    const v = this.data.get(key);
    if (!v) return { value: null, metadata: null };
    return { value: opts && opts.type === "json" ? JSON.parse(v.value) : v.value, metadata: v.metadata || null };
  }
  async put(key, value, opts = {}) { this.data.set(key, { value, metadata: opts.metadata }); }
  async list({ prefix }) {
    const keys = [...this.data.entries()].filter(([k]) => k.startsWith(prefix)).map(([name, v]) => ({ name, metadata: v.metadata }));
    return { keys, list_complete: true };
  }
}
globalThis.caches = { default: { match: async () => undefined, put: async () => undefined } };

const env = { CONFLICTS: new KV(), SALT: "a-test-salt-that-is-long-enough" };
const ctx = { waitUntil: () => undefined };
const send = (body, ip) => worker.fetch(new Request("https://relay.test/report", { method: "POST", body: JSON.stringify(body),
  headers: { "CF-Connecting-IP": ip, "Content-Length": String(JSON.stringify(body).length) } }), env, ctx);
const results = {};
const good = { loader: "fabric", minecraft: "1.21.1", mod: "badmod", with: ["sodium"] };
results.first = (await send(good, "203.0.113.1")).status;
results.same_person = (await (await send(good, "203.0.113.1")).json()).reports;
await send(good, "203.0.113.2");
results.listed_at_two = (await (await worker.fetch(new Request("https://relay.test/conflicts.json"), env, ctx)).json()).conflicts.length;
await send({ ...good, with: ["Sodium"] }, "203.0.113.3");
const list = (await (await worker.fetch(new Request("https://relay.test/conflicts.json"), env, ctx)).json()).conflicts;
results.listed_at_three = list;
results.bad_loader = (await send({ ...good, loader: "evil" }, "203.0.113.4")).status;
results.bad_id = (await send({ ...good, mod: "../x" }, "203.0.113.4")).status;
results.bad_json = (await worker.fetch(new Request("https://relay.test/report", { method: "POST", body: "{nope" }), env, ctx)).status;
for (let i = 0; i < 25; i++) results.last_flood = (await send({ ...good, mod: `m${i}` }, "198.51.100.9")).status;
results.stored_ips = [...env.CONFLICTS.data.values()].some((v) => String(v.value).includes("203.0.113"));
console.log(JSON.stringify(results));
