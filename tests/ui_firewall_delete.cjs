// Deleting a server offers to remove its Windows Firewall rule (see test_ui_firewall_delete.py).
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
  const card = page.locator('.server-card', { hasText: 'Alpha' });
  await card.waitFor();
  await card.getByRole('button', { name: 'Delete', exact: true }).click();
  await page.getByRole('button', { name: 'Remove from the list' }).click();
  const question = page.getByRole('alertdialog').filter({ hasText: "Windows Firewall rule" });
  await question.waitFor({ timeout: 20000 });
  assert.match(await question.innerText(), /Craft Conductor: Alpha \(TCP 25599\)/);
  assert.equal(await question.getByRole('button', { name: 'Keep' }).count(), 1);
  await question.getByRole('button', { name: 'Remove', exact: true }).click();
  await page.locator('.toast', { hasText: 'Removed from Windows Firewall' }).waitFor({ timeout: 20000 });
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
