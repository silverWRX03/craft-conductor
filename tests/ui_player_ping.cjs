// Turning players' ping on and off from the Connected Players card, and the helper's row in Manage Mods
// (test_ui_player_ping.py starts the page and a fake server).
const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');

(async () => {
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const base = process.argv[2];
  const H = { 'X-CRAFT-CONDUCTOR': '1' };
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.addInitScript(() => { localStorage.setItem('craft-conductor-theme', 'night'); localStorage.setItem('craft-conductor-sounds', 'off'); });

  // The owner (the default password asks to be changed; then sign in again with the new one).
  assert.equal((await page.request.post(base + '/api/login', { data: { password: 'PASSWORD' }, headers: H })).status(), 200);
  assert.equal((await page.request.post(base + '/api/auth/change', { data: { mode: 'password', secret: 'Owner-Strong-Pass-1' }, headers: H })).status(), 200);
  assert.equal((await page.request.post(base + '/api/login', { data: { password: 'Owner-Strong-Pass-1' }, headers: H })).status(), 200);

  await page.goto(base + '/#s/alpha/dashboard');
  const card = page.locator('.players-card');
  await card.waitFor();
  const show = card.getByRole('button', { name: "Show players' ping…" });
  const stop = card.getByRole('button', { name: 'Stop showing ping' });
  await show.waitFor();                                   // (nobody is online: the card still says it can be turned on)
  assert.equal(await stop.count(), 0);

  // Cancel changes nothing.
  await show.click();
  const dialog = page.locator('.toast-dialog');
  await dialog.waitFor();
  assert.equal((await dialog.innerText()).replace(/\s+/g, ' '),
    "Show players' ping? Craft Conductor adds its own small helper (a mod or plugin that only runs on the server) at the next restart. Players don't install anything. Turn on Cancel");
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await dialog.waitFor({ state: 'detached' });
  assert.equal(await show.count(), 1);

  // Turn on: the setting is saved, the toast says when, and the button swaps at once.
  await show.click();
  await dialog.getByRole('button', { name: 'Turn on' }).click();
  await page.locator('.toast', { hasText: 'Ping shows after the next restart.' }).waitFor();
  await stop.waitFor();
  assert.equal(await show.count(), 0);
  const saved = await page.evaluate(() => fetch('/api/servers/alpha/settings', { headers: { 'X-CRAFT-CONDUCTOR': '1' } }).then((r) => r.json()));
  assert.equal(saved.player_ping, true);

  // Stop showing ping asks first.
  await stop.click();
  await dialog.waitFor();
  assert.equal((await dialog.innerText()).replace(/\s+/g, ' '),
    'Stop showing players\' ping? The helper is taken off the server at the next restart. Stop Cancel');
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await dialog.waitFor({ state: 'detached' });
  assert.equal(await stop.count(), 1);
  await stop.click();
  await dialog.getByRole('button', { name: 'Stop', exact: true }).click();
  await show.waitFor();
  assert.equal(await stop.count(), 0);

  // Manage Mods: the helper (its file is in the folder) is one row of its own, with nothing to change or remove.
  await page.goto(base + '/#s/alpha/mods');
  await page.getByRole('button', { name: 'Manage Mods', exact: true }).first().click();
  const drawer = page.locator('.mod-manager-drawer');
  await drawer.waitFor();
  const row = drawer.locator('.mod-manager-row[data-key^="helper:"]');
  await row.waitFor();
  assert.equal(await drawer.locator('.mod-manager-row[data-key^="helper:"]').count(), 1);
  assert.match(await row.innerText(), /Craft Conductor Ping/);
  assert.match(await row.innerText(), /Craft Conductor's own: shows players' ping/);
  assert.equal(await row.getByRole('button').count(), 0, 'no Change version, no Remove');
  assert.equal(await drawer.locator('.mod-manager-row').filter({ hasText: 'craft_conductor_ping' }).count(), 1, 'not listed again as a file added by hand');
  assert.equal(errors.length, 0, errors.join('\n'));
  await browser.close();
  console.log('OK');
})().catch((e) => { console.error(e); process.exit(1); });
