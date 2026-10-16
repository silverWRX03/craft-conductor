// Keyboard focus survives the page's live updates (see test_ui_focus.py): the server list and the sidebar used
// to be rebuilt every few seconds, which threw the focused control away (focus fell to the page, and the next Tab
// began again at the first card's Start).
const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');
(async () => {
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const base = process.argv[2];
  const H = { 'X-CRAFT-CONDUCTOR': '1' };
  assert.equal((await page.request.post(base + '/api/login', { data: { password: 'PASSWORD' }, headers: H })).status(), 200);
  assert.equal((await page.request.post(base + '/api/auth/change', { data: { mode: 'pin', secret: '2468' }, headers: H })).status(), 200);
  await page.addInitScript(() => { localStorage.setItem('craft-conductor-sounds', 'off'); });
  const focused = () => page.evaluate(() => { const a = document.activeElement; return a && a !== document.body ? (a.textContent || '').trim().slice(0, 40) + '|' + (a.getAttribute('href') || '') : 'BODY'; });

  // the server list: focus a card's Open link, and wait through several updates
  await page.goto(base + '/#servers');
  const card = page.locator('.server-card', { hasText: 'Alpha' });
  await card.waitFor();
  await card.getByRole('link', { name: 'Open', exact: true }).focus();
  const before = await focused();
  assert.match(before, /Open\|#s\/alpha\/dashboard/);
  await page.waitForTimeout(7000);
  assert.equal(await focused(), before, 'the server list keeps the focus');
  await page.keyboard.press('Tab');
  assert.notEqual(await focused(), 'BODY');
  assert.doesNotMatch(await focused(), /^Start/, 'Tab goes on from where it was, not from the first card');

  // when what a card shows does change (Start becomes Stop), the focus goes to the same place, not to the page
  await card.getByRole('button', { name: 'Start', exact: true }).focus();
  assert.equal((await page.request.post(base + '/api/servers/alpha/server/start', { headers: H })).status(), 200);
  await card.getByRole('button', { name: 'Stop', exact: true }).waitFor({ timeout: 40000 });
  assert.match(await focused(), /^Stop\|/, 'the focus followed the button that replaced Start');
  assert.equal((await page.request.post(base + '/api/servers/alpha/server/stop', { headers: H })).status(), 200);
  await card.getByRole('button', { name: 'Start', exact: true }).waitFor({ timeout: 40000 });
  assert.match(await focused(), /^Start\|/);

  // the sidebar on a server's page
  await page.goto(base + '/#s/alpha/dashboard');
  await page.locator('#btn-start').waitFor();
  const link = page.locator('#nav a', { hasText: 'Console' });
  await link.focus();
  const nav = await focused();
  assert.match(nav, /Console\|#s\/alpha\/console/);
  await page.waitForTimeout(7000);
  assert.equal(await focused(), nav, 'the sidebar keeps the focus');
  // a control in the server's own page bar too
  await page.locator('#btn-start').focus();
  await page.waitForTimeout(5000);
  assert.match(await focused(), /Start/);
  // pages that update themselves keep their controls: none is replaced while they are on screen
  for (const view of ['dashboard', 'players', 'settings']) {
    await page.goto(base + '/#s/alpha/' + view);
    await page.waitForTimeout(2500);
    await page.evaluate(() => { window.__m = [...document.querySelectorAll('#app a[href],#app button,#app input,#app select,#app textarea,#app summary')]
      .filter((e) => e.getClientRects().length).map((e) => [e, (e.textContent || e.id || e.tagName).trim().slice(0, 30)]); });
    await page.waitForTimeout(6500);
    const replaced = await page.evaluate(() => window.__m.filter(([e]) => !e.isConnected).map(([, n]) => n));
    assert.deepEqual(replaced, [], view + ' rebuilt controls that had not changed');
  }
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
