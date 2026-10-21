// A server's Mods page: a mod added from the mod browser that went in friends' mods with its library,
// removed before the next update, is asked about by its name, with the library (#142). See
// test_friend_sides.py.
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
  const row = drawer.locator('.mod-manager-row', { hasText: 'Recipe Viewer' });
  await row.getByRole('button', { name: 'Remove', exact: true }).click();
  const sure = page.locator('.toast-dialog', { hasText: 'Remove Recipe Viewer?' });
  await sure.waitFor();
  await sure.getByRole('button', { name: 'Remove', exact: true }).click();
  const question = page.locator('.toast-dialog', { hasText: "also in your friends' mods" });
  await question.waitFor();
  assert.match(await question.innerText(), /Recipe Viewer and Recipe Library are also in your friends' mods/);
  await question.getByRole('button', { name: "Remove from friends' mods" }).click();
  await page.waitForFunction(async () => (await (await fetch('/api/servers/alpha/client', { headers: { 'X-CRAFT-CONDUCTOR': '1' } })).json()).mods.length === 0);
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
