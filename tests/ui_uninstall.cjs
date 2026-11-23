// Uninstall Craft Conductor… in Craft Conductor settings → About & updates (see test_ui_uninstall.py).
const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');
(async () => {
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const base = process.argv[2];
  const H = { 'X-CRAFT-CONDUCTOR': '1' };
  assert.equal((await page.request.post(base + '/api/login', { data: { password: 'PASSWORD' }, headers: H })).status(), 200);
  assert.equal((await page.request.post(base + '/api/auth/change', { data: { mode: 'pin', secret: '2468' }, headers: H })).status(), 200);
  await page.addInitScript(() => { localStorage.setItem('craft-conductor-sounds', 'off'); });

  await page.goto(base + '/#craft-conductor');
  await page.getByRole('button', { name: 'About & updates' }).click();
  await page.getByRole('button', { name: 'Uninstall Craft Conductor…' }).click();
  const dialog = page.getByRole('dialog', { name: 'Uninstall Craft Conductor' });
  await dialog.getByText('Settings and state').first().waitFor({ timeout: 20000 });

  // The plan, with every box off.
  const boxes = dialog.getByRole('checkbox');
  assert.ok(await boxes.count() >= 5);
  for (let i = 0; i < await boxes.count(); i++) assert.equal(await boxes.nth(i).isChecked(), false);
  assert.match(await dialog.innerText(), /Servers and worlds/);

  // Deleting the servers asks again, naming how many.
  const servers = dialog.getByRole('checkbox', { name: 'Delete my servers and worlds' });
  await servers.click();
  let question = page.getByRole('alertdialog').filter({ hasText: 'for good' });
  await question.waitFor();
  assert.match(await question.innerText(), /2 servers and 1 world\b/);
  await question.getByRole('button', { name: 'Keep them' }).click();
  assert.equal(await servers.isChecked(), false);
  await servers.click();
  question = page.getByRole('alertdialog').filter({ hasText: 'for good' });
  await question.getByRole('button', { name: 'Delete them' }).click();
  await page.waitForFunction(() => /Servers and worlds[\s\S]*deleted: 2 servers/.test(document.querySelector('#uninstall').innerText));
  assert.equal(await servers.isChecked(), true);

  // The password again, then Uninstall: progress, then the report.
  await dialog.getByLabel('Type your PIN again').fill('1111');
  await dialog.getByRole('button', { name: 'Uninstall', exact: true }).click();
  await dialog.getByText('wrong PIN').waitFor();
  await dialog.getByLabel('Type your PIN again').fill('2468');
  await dialog.getByRole('button', { name: 'Uninstall', exact: true }).click();
  const report = page.getByRole('dialog', { name: /Craft Conductor has been removed/ });
  await report.waitFor({ timeout: 60000 });
  const text = await report.innerText();
  assert.match(text, /Removed/);
  assert.match(text, /Settings and state/);
  assert.match(text, /Stopping the servers/);
  assert.match(text, /Left for you to do/);

  // Craft Conductor closes; the report stays.
  const url = page.url();
  const deadline = Date.now() + 40000;
  let gone = false;
  while (!gone && Date.now() < deadline) {
    try { await page.request.get(base + '/api/auth', { timeout: 2000 }); await page.waitForTimeout(300); } catch (_) { gone = true; }
  }
  assert.ok(gone, 'Craft Conductor kept running');
  await page.waitForTimeout(4000);
  assert.equal(page.url(), url);
  assert.ok(await report.isVisible());
  assert.equal(await report.innerText(), text);
  assert.equal(await page.locator('#login:not(.hidden)').count(), 0);
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
