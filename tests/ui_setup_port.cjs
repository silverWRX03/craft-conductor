// New server: a port typed in is kept when you go to another page and come back, like the
// server's name and the other choices (#195). See test_ui_browser.py.
const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');
(async () => {
  const [base] = process.argv.slice(2);
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.addInitScript(() => { localStorage.setItem('craft-conductor-sounds', 'off'); });
  const H = { 'X-CRAFT-CONDUCTOR': '1' };
  assert.equal((await page.request.post(base + '/api/login', { data: { password: 'PASSWORD' }, headers: H })).status(), 200);
  await page.goto(base + '/#new');
  await page.waitForLoadState('networkidle');
  if (await page.locator('#security').count()) {  // (the default password: not now)
    await page.locator('#security').getByRole('button', { name: 'Not now' }).click();
    await page.locator('#security').waitFor({ state: 'detached' });
  }
  await page.locator('.choice', { hasText: 'Lightweight and quick to update' }).click();
  const port = page.getByLabel('Port (players connect to this)');
  await port.fill('25615');
  await page.goto(base + '/#servers');
  await page.waitForLoadState('networkidle');
  await page.goto(base + '/#new');
  await page.waitForLoadState('networkidle');
  await page.getByLabel('Port (players connect to this)').waitFor();
  assert.equal(await page.getByLabel('Port (players connect to this)').inputValue(), '25615');
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
