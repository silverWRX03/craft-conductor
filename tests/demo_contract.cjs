// The website demo's simulation (site/demo/app/sim/), run without a browser for
// test_website_demo_contract.py: it reads requests (JSON lines on stdin: {"method", "path", "body",
// "advance"}) and writes the simulation's answers (JSON lines). The built demo's catalog-release.js
// (Craft Conductor's own texts, from tools/build_website.py) is argv[2]; the scenario argv[3].
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const readline = require('node:readline');

const [catalogFile, scenario = 'existing'] = process.argv.slice(2);
const simDir = path.resolve(__dirname, '..', 'site', 'demo', 'app', 'sim');
let clock = Date.now();
const timers = [];
const context = {
  console, JSON, Math, Object, Array, String, Number, Boolean, Set, Map, Promise, RegExp, Error, TypeError, URL, URLSearchParams,
  TextEncoder, btoa: (s) => Buffer.from(s, 'binary').toString('base64'), crypto: require('node:crypto').webcrypto,
  Date: class extends Date { constructor(...a) { super(...(a.length ? a : [clock])); } static now() { return clock; } },
  setTimeout: (fn, ms) => { timers.push({ at: clock + (ms || 0), fn }); return timers.length; },
  clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {},
  location: { hostname: 'demo.invalid', hash: '', href: 'https://demo.invalid/demo/app/' },
  document: { createElement: () => { throw new Error('no pictures in the contract test'); } },
  addEventListener: () => {},
};
context.window = context;
vm.createContext(context);
vm.runInContext(fs.readFileSync(catalogFile, 'utf8'), context, { filename: 'catalog-release.js' });
for (const name of ['core.js', 'catalog.js', 'engine.js', 'world.js', 'routes-hub.js', 'routes-server.js', 'routes-mods.js']) {
  vm.runInContext(fs.readFileSync(path.join(simDir, name), 'utf8'), context, { filename: name });
}
const sim = context.CCSim;
sim.start({ scenario, state: null, mobile: false, release: {} });
const advance = (seconds) => {
  const end = clock + seconds * 1000;
  while (clock < end) {
    clock = Math.min(end, clock + 1000);
    for (const t of timers.splice(0).filter((x) => { if (x.at <= clock) return true; timers.push(x); return false; })) t.fn();
    sim.tick();
  }
};
const rl = readline.createInterface({ input: process.stdin });
rl.on('line', (line) => {
  if (!line.trim()) return;
  const req = JSON.parse(line);
  if (req.advance) advance(req.advance);
  const answer = req.path ? sim.request(req.method || 'GET', req.path, req.body || {}) : { status: 200, body: { ok: true } };
  process.stdout.write(JSON.stringify({ ...answer, unhandled: sim.unhandled.splice(0) }) + '\n');
});
