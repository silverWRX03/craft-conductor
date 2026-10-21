// A move put back at the start (see test_ui_locations.py): Craft Conductor settings → Folders says so
// once in this browser, not at every visit (#141).
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
  const said = page.locator('#toasts .toast', { hasText: 'Moving the servers was stopped halfway' });
  const card = page.locator('.card', { hasText: 'Where files are kept' });
  const folders = async () => {
    await page.goto(base + '/#craft-conductor');
    await page.reload();  // (a new visit: the page loaded again)
    await page.waitForLoadState('networkidle');
    if (await page.locator('#security').count()) {  // (the default password: not now)
      await page.locator('#security').getByRole('button', { name: 'Not now' }).click();
      await page.locator('#security').waitFor({ state: 'detached' });
    }
    await page.getByRole('button', { name: 'Folders', exact: true }).click();
    await card.waitFor();
    await page.waitForLoadState('networkidle');
  };
  await folders();
  await said.waitFor();
  assert.equal(await said.count(), 1);
  await said.click();  // (closed)
  await said.waitFor({ state: 'detached' });
  for (let i = 0; i < 2; i++) {
    await folders();
    await page.waitForTimeout(500);
    assert.equal(await said.count(), 0, 'said again on another visit');
  }
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
