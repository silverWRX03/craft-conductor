// Export server… and Import a server… in a real browser (see test_ui_export_choices.py): pick
// what goes in, see the password once, and the import asks for it (a wrong one is asked again).
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

  // Export: everything but the world, and the CurseForge key, locked.
  await page.goto(base + '/#s/alpha/settings');
  await page.getByRole('button', { name: 'Export server…' }).click();
  const choices = page.getByRole('alertdialog').filter({ hasText: 'What goes in the export?' });
  await choices.waitFor();
  await choices.getByRole('checkbox', { name: 'The world' }).uncheck();
  await choices.getByRole('checkbox', { name: 'CurseForge key' }).check();
  await choices.getByRole('button', { name: 'Export', exact: true }).click();
  const shown = page.getByRole('alertdialog').filter({ hasText: "Write down this export's password" });
  await shown.waitFor();
  const password = (await shown.locator('code').textContent()).trim();
  assert.match(password, /^[A-Z2-9]{4}(-[A-Z2-9]{4}){5}$/);
  await shown.getByRole('button', { name: "I've saved it" }).click();
  let exports = [];
  for (let i = 0; i < 150 && !exports.length; i++) {
    exports = (await (await page.request.get(base + '/api/servers/alpha/export')).json()).exports;
    if (!exports.length) await page.waitForTimeout(200);
  }
  assert.equal(exports.length, 1);
  const file = await (await page.request.get(base + '/api/servers/alpha/export/download?name=' + encodeURIComponent(exports[0].name))).body();

  // Import it: the password is asked for; a wrong one is asked again.
  await page.goto(base + '/#servers');
  await page.getByRole('button', { name: 'Import a server…' }).waitFor();
  await page.locator('input[type=file][accept=".zip"]').setInputFiles({ name: 'alpha.zip', mimeType: 'application/zip', buffer: file });
  const asked = page.getByRole('alertdialog').filter({ hasText: "This export's passwords and keys are locked" });
  await asked.waitFor();
  await asked.locator('input').fill('AAAA-AAAA-AAAA-AAAA-AAAA-AAAA');
  await asked.getByRole('button', { name: 'Import', exact: true }).click();
  await page.locator('.toast.bad').filter({ hasText: "isn't the one" }).first().waitFor();
  await asked.waitFor();  // (again)
  await asked.locator('input').fill(password);
  await asked.getByRole('button', { name: 'Import', exact: true }).click();
  await page.waitForFunction(() => /^#s\/[a-z0-9-]+\/dashboard$/.test(location.hash) && !location.hash.startsWith('#s/alpha/'), null, { timeout: 30000 });
  console.log('IMPORTED ' + (await page.evaluate(() => location.hash)).split('/')[1]);
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
