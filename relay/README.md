# The mod-conflict relay

Craft Conductor's shared memory of mod conflicts (the app side is `src/craft_conductor/conflicts.py`). It's a
small [Cloudflare Worker](https://developers.cloudflare.com/workers/) that keeps reports in
Cloudflare's KV storage; both fit in Cloudflare's free plan.

- `POST /report` takes one conflict: `{"loader", "minecraft", "mod", "with": [mod ids]}`. Only
  people who switched on **Share mod conflicts anonymously** send them.
- `GET /conflicts.json` lists the conflicts at least 3 different people reported. Craft Conductor
  reads it at most once a day, and the relay caches it for an hour.

Nothing about the sender is kept except a salted hash of their address. The relay uses it to count
different people and to allow at most 20 reports per address per day.

## Setting it up (once)

1. Create a free account at [dash.cloudflare.com](https://dash.cloudflare.com).
2. **Workers & Pages → Create → Start with Hello World!** (not "Import a repository"), name it
   `craft-conductor`, **Deploy**.
3. **Storage & Databases → KV → Create namespace**, name it `CONFLICTS`.
4. Open the Worker → **Settings → Bindings → Add → KV namespace**: variable name `CONFLICTS`,
   namespace `CONFLICTS`.
5. **Settings → Variables and Secrets → Add**: type **Secret**, name `SALT`, value any long random
   text (30+ characters). Keep it to yourself.
6. **Edit code**: replace everything with [`worker.js`](worker.js), then **Deploy**.
7. Put the Worker's address (`https://<worker name>.<you>.workers.dev`) in
   `RELAY` in `src/craft_conductor/conflicts.py`. From the next release, Craft Conductor uses it.

To try a different relay without a new release, set `CRAFT_CONDUCTOR_CONFLICTS_URL` (or `off`).

## Updating it

Paste the new `worker.js` under **Edit code** and **Deploy**. The stored reports stay.
`tests/test_relay.py` runs the Worker in Node against fake storage.
