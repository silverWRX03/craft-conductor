// Where files are kept (see test_ui_locations.py): after the password, the page asks once with
// today's folders filled in; Change… opens the folder browser (New folder… makes one); Craft
// Conductor settings → Folders moves the servers, asked first; Import a server… lists the exports.
const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const [base, home, elsewhere] = process.argv.slice(2);
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.addInitScript(() => { localStorage.setItem('craft-conductor-sounds', 'off'); });
  const toast = (text) => page.locator('#toasts .toast', { hasText: text });
  const row = (where, label) => where.locator('.place-row').filter({ has: page.locator('strong', { hasText: new RegExp(`^${label}$`) }) });
  const H = { 'X-CRAFT-CONDUCTOR': '1' };
  assert.equal((await page.request.post(base + '/api/login', { data: { password: 'PASSWORD' }, headers: H })).status(), 200);

  // First the password, then where files go.
  await page.goto(base + '/#servers');
  const security = page.locator('#security');
  await security.waitFor();
  assert.equal(await page.locator('#locations').count(), 0);
  await security.getByRole('button', { name: /PIN/ }).click();
  await security.locator('input[type=password]').nth(0).fill('2468');
  await security.locator('input[type=password]').nth(1).fill('2468');
  await security.getByRole('button', { name: 'Save' }).click();
  const first = page.locator('#locations');
  await first.waitFor({ timeout: 15000 });
  await first.getByText('Where should Craft Conductor keep your files?').waitFor();
  const text = await first.innerText();
  assert.ok(text.includes(path.join(home, 'servers')) && text.includes("In each server's own folder") && text.includes(path.join(home, 'exports')), text);
  assert.equal(await page.locator('#toasts .toast', { hasText: 'guided setup' }).count(), 0);  // (the guided setup waits)

  // Change… for exports: the folder browser, and New folder… there.
  await row(first, 'Exports').getByRole('button', { name: 'Change…' }).click();
  const chooser = page.locator('#folder-browser');
  await chooser.waitFor();
  await chooser.locator('input').fill(elsewhere);
  await chooser.getByRole('button', { name: 'Open', exact: true }).click();
  await chooser.getByText('There are no folders in here.').waitFor();
  await chooser.getByRole('button', { name: 'New folder…' }).click();
  await page.locator('.toast-dialog input').fill('Exports here');
  await page.locator('.toast-dialog').getByRole('button', { name: 'Make it' }).click();
  await chooser.locator('input').evaluate((el) => el.value).then((v) => assert.ok(v.endsWith('Exports here'), v));
  await chooser.getByRole('button', { name: 'Use this folder' }).click();
  await chooser.waitFor({ state: 'detached' });
  await first.getByText(path.join(fs.realpathSync(elsewhere), 'Exports here')).waitFor();
  await first.getByRole('button', { name: 'Use these folders' }).click();  // (nothing to move: saved at once)
  await first.waitFor({ state: 'detached', timeout: 15000 });
  await toast('Saved.').waitFor();

  // Craft Conductor settings → Folders: move the servers, asked first.
  await page.goto(base + '/#craft-conductor');
  await page.getByRole('button', { name: 'Folders', exact: true }).click();
  const card = page.locator('.card', { hasText: 'Where files are kept' });
  await row(card, 'Exports').getByText('Exports here').waitFor();
  await row(card, 'Servers').getByRole('button', { name: 'Change…' }).click();
  await chooser.waitFor();
  await chooser.locator('input').fill(elsewhere);
  await chooser.getByRole('button', { name: 'Open', exact: true }).click();
  await chooser.getByRole('button', { name: 'New folder…' }).click();
  await page.locator('.toast-dialog input').fill('Servers');
  await page.locator('.toast-dialog').getByRole('button', { name: 'Make it' }).click();
  await chooser.locator('.folder-row', { hasText: 'Up' }).waitFor();
  await chooser.getByRole('button', { name: 'Use this folder' }).click();
  const question = page.locator('.toast-dialog', { hasText: "Move what's there now?" });
  await question.waitFor();
  assert.match(await question.innerText(), /Servers: 1 folder/);
  await question.getByRole('button', { name: 'Move', exact: true }).click();
  await toast('Saved.').waitFor({ timeout: 30000 });
  await row(card, 'Servers').getByText(path.join(fs.realpathSync(elsewhere), 'Servers')).waitFor();

  // Import a server…: the exports in the exports folder (none yet), and Another file….
  await page.goto(base + '/#servers');
  await page.getByRole('button', { name: 'Import a server…' }).click();
  const list = page.locator('#exports-list');
  await list.getByText('There are no exports in the exports folder yet.').waitFor();
  assert.match(await list.innerText(), /Exports here/);
  await list.getByRole('button', { name: 'Cancel' }).click();
  await list.waitFor({ state: 'detached' });
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
