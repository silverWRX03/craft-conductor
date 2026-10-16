// Old firewall rules in Check my setup, and every rule in Craft Conductor settings (see test_ui_firewall_cleanup.py).
// The question opens above the Check my setup panel (it used to open underneath it, out of sight).
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

  await page.goto(base + '/#s/alpha/dashboard');
  await page.getByRole('button', { name: /Check my setup/ }).click();
  const panel = page.locator('#doctor');
  const old = panel.locator('.doctor-item', { hasText: 'Old Windows Firewall rules' });
  await old.waitFor({ timeout: 30000 });
  await old.getByRole('button', { name: 'Remove old rules' }).click();
  const question = page.getByRole('alertdialog').filter({ hasText: 'Remove the old Windows Firewall rules?' });
  await question.waitFor();
  // on top of the panel, so a person can see and press it
  assert.equal(await question.evaluate((el) => { const r = el.getBoundingClientRect(); const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return el.contains(top); }), true,
    'the question is not hidden under Check my setup');
  assert.match(await question.innerText(), /TCP 25611/);
  await question.getByRole('button', { name: 'Keep' }).click();
  await question.waitFor({ state: 'detached' });
  await old.getByRole('button', { name: 'Remove old rules' }).click();
  await question.waitFor();
  await question.getByRole('button', { name: 'Remove', exact: true }).click();
  await page.locator('.toast', { hasText: 'Removed from Windows Firewall' }).waitFor({ timeout: 20000 });
  await panel.getByRole('button', { name: 'Close' }).click();

  // Craft Conductor settings: every rule, with the list first
  await page.goto(base + '/#craft-conductor');
  await page.getByRole('button', { name: 'About & updates' }).click();
  await page.getByRole('button', { name: /Remove all Craft Conductor's firewall rules/ }).click();
  const all = page.getByRole('alertdialog').filter({ hasText: 'Windows Firewall rules' });
  await all.waitFor({ timeout: 20000 });
  assert.match(await all.innerText(), /all 2 Windows Firewall rules/);
  await all.getByRole('button', { name: 'Keep' }).click();
  await all.waitFor({ state: 'detached' });
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
