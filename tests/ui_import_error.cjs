// A refused import stays on the Servers page (see test_ui_import_error.py): the reason is beside
// Import a server… until it is dismissed, and survives going to another page and back.
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

  await page.goto(base + '/#servers');
  await page.locator('#app').waitFor({ state: 'visible' });
  const notice = page.locator('#main .notice.bad[role=alert]');
  assert.equal(await notice.count(), 0);
  await page.locator('#main input[type=file]').setInputFiles({ name: 'broken.zip', mimeType: 'application/zip', buffer: Buffer.from('this is not a zip file') });
  await notice.waitFor({ timeout: 20000 });
  assert.match(await notice.innerText(), /The import didn't happen: broken\.zip: /);

  // it stays when the page is left and come back to, and goes when dismissed
  await page.goto(base + '/#s/alpha/dashboard');
  await page.locator('#btn-start').waitFor();
  await page.goto(base + '/#servers');
  await notice.waitFor();
  await notice.getByRole('button', { name: 'Dismiss' }).click();
  await notice.waitFor({ state: 'detached' });
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
