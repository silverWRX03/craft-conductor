// What the website's browser tests share (ui_website*.cjs, run by test_website_browser.py).
const path = require('node:path');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const pw = require(process.env.CRAFT_UI_PLAYWRIGHT);

const out = process.env.CRAFT_WEBSITE_OUT || '.';
const browsers = (process.env.CRAFT_UI_BROWSERS || 'chromium').split(',').map((s) => s.trim()).filter(Boolean);

async function launch(name) {
  const channel = name === 'chromium' ? (process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined)) : undefined;
  return pw[name].launch({ headless: true, ...(channel ? { channel } : {}) });
}

// A page that records what goes wrong: script errors, failed loads, and any request that isn't one
// of the website's own files (the demo makes none: no API calls, nothing outside).
function watch(page, base, problems, label) {
  const own = new URL(base);
  const allowed = (u) => u.origin === own.origin && u.pathname.startsWith(own.pathname);
  page.on('pageerror', (e) => problems.push(`${label}: script error: ${e.message}`));
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    const text = m.text();
    if (/Blocked autofocusing|Failed to load resource: net::ERR_BLOCKED_BY_CLIENT/.test(text)) return;  // (the browser's own rule for frames)
    // (Playwright's WebKit screenshots put a <style> in every frame, which the pages' CSP rightly refuses)
    if (label.startsWith('webkit') && /^Refused to apply a stylesheet because its hash, its nonce, or 'unsafe-inline'/.test(text)) return;
    problems.push(`${label}: console error: ${text.slice(0, 300)} (${(m.location() || {}).url || ''})`);
  });
  page.on('request', (r) => {
    let u;
    try { u = new URL(r.url()); } catch (_) { return; }
    if (u.protocol === 'data:' || u.protocol === 'blob:' || u.protocol === 'about:') return;
    if (!allowed(u)) problems.push(`${label}: a request left the website: ${r.method()} ${r.url()}`);
    if (u.pathname.includes('/api/')) problems.push(`${label}: an API request reached the network: ${r.url()}`);
  });
  page.on('response', (r) => { if (r.status() >= 400 && !/__not_here__|favicon/.test(r.url())) problems.push(`${label}: ${r.status()} ${r.url()}`); });
}

// The demo's frame (the real control panel) inside a page.
async function demoFrame(page, timeout = 20000) {
  const end = Date.now() + timeout;
  for (;;) {
    const f = page.frames().find((x) => x.url().includes('/demo/app/'));
    if (f) {
      try { await f.waitForSelector('#app:not(.hidden)', { timeout: Math.max(1000, end - Date.now()) }); return f; } catch (e) { if (Date.now() > end) throw e; }
    }
    if (Date.now() > end) throw new Error('the demo frame never showed the control panel');
    await page.waitForTimeout(150);
  }
}

// Steps, each run and reported; the script fails at the end if any did.
function suite(name) {
  const failures = [];
  const results = [];
  return {
    page: null,  // (a page to take a picture of when a step fails)
    async step(title, fn) {
      const started = Date.now();
      try { await fn(); results.push(`ok   ${title} (${Date.now() - started} ms)`); }
      catch (e) {
        failures.push(`${title}: ${e && e.stack ? e.stack.split('\n').slice(0, 4).join(' | ') : e}`);
        results.push(`FAIL ${title}`);
        if (this.page) await shot(this.page, 'FAILED ' + title.replace(/[^\w ]+/g, ' ').trim().slice(0, 80)).catch(() => null);
      }
    },
    done(problems = []) {
      for (const line of results) console.log(line);
      const all = [...failures, ...[...new Set(problems)].map((p) => 'problem: ' + p)];
      if (all.length) { console.error(`${name}: ${all.length} failure(s)\n` + all.join('\n')); process.exit(1); }
      console.log(`${name}: all ${results.length} steps passed`);
    },
  };
}

// (caret: 'initial': hiding the caret, Playwright's default, puts a style in the page that its CSP refuses in WebKit)
const shot = async (page, name) => { fs.mkdirSync(out, { recursive: true }); await page.screenshot({ path: path.join(out, name + '.png'), caret: 'initial' }); };
// No sideways scrolling on the page (a phone layout that's too wide).
const noSidewaysScroll = async (page, what) => {
  const [w, sw] = await page.evaluate(() => [window.innerWidth, document.documentElement.scrollWidth]);
  assert.ok(sw <= w + 1, `${what}: the page is ${sw}px wide in a ${w}px window`);
};
// Wait for something in a frame, retrying (the simulation answers after a moment).
async function until(fn, what, timeout = 15000) {
  const end = Date.now() + timeout;
  let last;
  for (;;) {
    try { const v = await fn(); if (v) return v; } catch (e) { last = e; }
    if (Date.now() > end) throw new Error(`timed out waiting for ${what}${last ? ': ' + last.message : ''}`);
    await new Promise((r) => setTimeout(r, 200));
  }
}

module.exports = { assert, browsers, launch, watch, demoFrame, suite, shot, noSidewaysScroll, until, out };
