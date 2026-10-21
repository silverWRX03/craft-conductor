// A server's Manage Mods: a mod you picked that another picked mod needs (Fabric API, needed by
// AppleSkin) is one row, "selected by you", saying it's also needed by AppleSkin; removing AppleSkin
// doesn't say Fabric API goes too. See test_mod_management.py.
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
  await page.goto(base + '/#s/alpha/mods');
  await page.waitForLoadState('networkidle');
  if (await page.locator('#security').count()) {  // (the default password: not now)
    await page.locator('#security').getByRole('button', { name: 'Not now' }).click();
    await page.locator('#security').waitFor({ state: 'detached' });
  }
  await page.getByRole('button', { name: 'Manage Mods', exact: true }).first().click();
  const drawer = page.locator('.mod-manager-drawer');
  await drawer.locator('.mod-manager-row', { hasText: 'AppleSkin' }).first().waitFor();
  const api = drawer.locator('.mod-manager-row', { hasText: 'Fabric API' });
  assert.equal(await api.count(), 1, 'Fabric API is listed once');
  const text = await api.innerText();
  assert.match(text, /selected by you/);
  assert.match(text, /also needed by AppleSkin/);
  assert.doesNotMatch(text, /dependency/);
  assert.match(await drawer.innerText(), /2 total · 0 dependencies/);
  await drawer.locator('.mod-manager-row', { hasText: 'AppleSkin', hasNotText: 'Fabric API' }).getByRole('button', { name: 'Remove', exact: true }).click();
  const sure = page.locator('.toast-dialog', { hasText: 'Remove AppleSkin?' });
  await sure.waitFor();
  assert.doesNotMatch(await sure.innerText(), /Fabric API/, 'Fabric API, which you picked, stays');
  await sure.getByRole('button', { name: 'Cancel', exact: true }).click();
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
