// Recent servers and the Server icon card (see test_ui_recent_and_icon.py).
const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');
(async () => {
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  const base = process.argv[2], picture = process.argv[3];
  const H = { 'X-CRAFT-CONDUCTOR': '1' };
  const errors = [];
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
  await context.addInitScript(() => { localStorage.setItem('craft-conductor-sounds', 'off'); });
  const page = await context.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  assert.equal((await page.request.post(base + '/api/login', { data: { password: 'PASSWORD' }, headers: H })).status(), 200);
  assert.equal((await page.request.post(base + '/api/auth/change', { data: { mode: 'password', secret: 'Owner-Strong-Pass-1' }, headers: H })).status(), 200);
  assert.equal((await page.request.post(base + '/api/login', { data: { password: 'Owner-Strong-Pass-1' }, headers: H })).status(), 200);

  // The order: running ones first, by who last played; then by when they last started; never started last.
  await page.goto(base + '/#servers');
  await page.locator('#app').waitFor({ state: 'visible' });
  const order = await page.evaluate(() => recentServers([
    { id: 'a', name: 'A', state: 'stopped', last_started: 50 },
    { id: 'b', name: 'B', state: 'running', last_started: 10, last_played: 300 },
    { id: 'c', name: 'C', state: 'stopped', last_started: null },
    { id: 'd', name: 'D', state: 'running', last_started: 20, last_played: 400 },
    { id: 'e', name: 'E', state: 'unavailable' },
    { id: 'f', name: 'F', state: 'stopped', setup_pending: true },
  ]).map((s) => s.id));
  assert.deepEqual(order, ['d', 'b', 'a']);
  assert.deepEqual(await page.evaluate(() => recentServers([{ id: 'a', name: 'A', state: 'stopped' }])), [], 'one server: nothing to switch to');

  // In the panel, on every page: Beta (ran last), then Alpha (Main isn't set up yet).
  const recent = page.locator('#nav .nav-recent a');
  await recent.first().waitFor();
  assert.deepEqual(await recent.allInnerTexts(), ['Beta', 'Alpha']);
  await page.goto(base + '/#s/alpha/players');
  await page.locator('#nav .nav-recent a', { hasText: 'Beta' }).click();
  await page.waitForFunction(() => location.hash === '#s/beta/players');
  await page.locator('#nav .nav-recent a[aria-current="true"]', { hasText: 'Beta' }).waitFor();  // (the panel marks where you are)

  // Settings: the webhook help link, and the icon card (a wide picture becomes 64 × 64).
  await page.goto(base + '/#s/alpha/settings');
  const help = page.getByRole('link', { name: /How to make a webhook/ });
  await help.waitFor();
  assert.match(await help.getAttribute('href'), /^https:\/\/support\.discord\.com\//);
  assert.equal(await help.getAttribute('target'), '_blank');
  assert.match(await help.getAttribute('rel'), /noopener/);
  const iconCard = page.locator('.card', { has: page.getByRole('heading', { name: 'Server icon' }) });
  await iconCard.waitFor();
  assert.match(await iconCard.innerText(), /Minecraft's own picture/);
  await iconCard.locator('input[type=file]').setInputFiles(picture);
  await page.locator('#toasts .toast', { hasText: 'Server icon saved' }).waitFor();
  await iconCard.locator('img.server-icon').waitFor();
  assert.match(await iconCard.innerText(), /next restart/);
  await page.goto(base + '/#servers');
  await page.locator('.server-card img.server-icon').first().waitFor();

  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
