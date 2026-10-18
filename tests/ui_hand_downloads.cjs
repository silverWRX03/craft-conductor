// Mods downloaded by hand on the setup page (see test_ui_hand_downloads.py): Craft Conductor finds
// them in Downloads by itself, says when the file there is another one, asks where they are after
// a Download link when they aren't there, and looks in the folder chosen (Always look here, which
// Craft Conductor settings → Folders lists, with Forget). Once found, the warnings go.
const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const [base, downloads, saved] = process.argv.slice(2);
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.route(/^https:\/\/www\.curseforge\.com\//, (route) => route.fulfill({ status: 200, contentType: 'text/html', body: 'CurseForge' }));
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const H = { 'X-CRAFT-CONDUCTOR': '1' };
  assert.equal((await page.request.post(base + '/api/login', { data: { password: 'PASSWORD' }, headers: H })).status(), 200);
  assert.equal((await page.request.post(base + '/api/auth/change', { data: { mode: 'pin', secret: '2468' }, headers: H })).status(), 200);
  await page.addInitScript(() => { localStorage.setItem('craft-conductor-sounds', 'off'); });
  const toast = (text) => page.locator('#toasts .toast', { hasText: text });

  await page.goto(base + '/#new');
  await page.locator('#app').waitFor({ state: 'visible' });
  await page.locator('button.choice', { hasText: 'Lightweight and quick to update' }).click();
  await page.locator('#setup-version').waitFor();
  // A CurseForge mod whose author keeps it to CurseForge
  await page.evaluate(() => {
    setupState.mods.set('curseforge:22', { name: 'Fancy Client', required: true, explicit: true, by: new Set(), bad: '' });
    setupState.rerender();
  });
  await toast('must be downloaded from CurseForge by hand').waitFor({ timeout: 20000 });
  assert.notEqual(await page.evaluate(() => setupServerAttention()), '');
  await page.locator('[data-mod-summary="mods"]').first().getByRole('button', { name: 'Manage Mods', exact: true }).click();
  const section = page.locator('.mod-manager-drawer section.hand-downloads');
  await section.waitFor();
  await section.getByText('Craft Conductor looks for them by itself in your Downloads folder').waitFor({ timeout: 10000 });
  assert.match(await section.innerText(), /Fancy Client\s*not downloaded yet/);

  // After its Download link, it isn't there: the section asks where it was saved.
  const popup = context.waitForEvent('page');
  await section.getByRole('link', { name: 'Download from CurseForge ↗' }).click();
  await (await popup).close();
  await page.bringToFront();
  await section.getByText('Not found in your Downloads folder. Where did you save it?').waitFor({ timeout: 15000 });

  // Another file under its name: refused, and said.
  fs.writeFileSync(path.join(downloads, 'fancy-client-2.1.jar'), 'another version');
  await toast("isn't the file CurseForge lists").waitFor({ timeout: 15000 });
  await section.locator('.tag.bad', { hasText: 'wrong file' }).waitFor();

  // The right one, saved as the browser's second copy: found, and the warnings go.
  fs.writeFileSync(path.join(downloads, 'fancy-client-2.1 (1).jar'), 'fancy jar');
  await toast('Found Fancy Client in your Downloads folder').waitFor({ timeout: 15000 });
  await section.getByText('All the mods to download by hand are loaded.').waitFor();
  assert.equal(await page.evaluate(() => setupServerAttention()), '');
  assert.equal(await page.locator('.btn.attention').count(), 0);
  assert.ok(fs.existsSync(path.join(downloads, 'fancy-client-2.1 (1).jar')), 'copied, not moved');

  // Saved somewhere else: Choose the folder…, then Always look here.
  for (const f of fs.readdirSync(downloads)) fs.unlinkSync(path.join(downloads, f));
  fs.writeFileSync(path.join(saved, 'fancy-client-2.1.jar'), 'fancy jar');
  await page.evaluate(() => { setupState.handGot.clear(); setupState.onHand(); });
  await section.getByText('Not found in your Downloads folder. Where did you save it?').waitFor({ timeout: 15000 });
  await section.locator('.notice').getByRole('button', { name: 'Choose the folder…' }).click();
  const chooser = page.locator('#folder-browser');
  await chooser.waitFor();
  await chooser.getByText('Where did you save the mods?').waitFor();
  assert.equal(await chooser.locator('input').inputValue(), fs.realpathSync(downloads));  // (it starts in Downloads)
  assert.match(await chooser.locator('.folder-list').innerText(), /Up\s+There are no folders in here\./);
  await chooser.locator('input').fill(saved);
  await chooser.getByRole('button', { name: 'Always look here' }).click();
  await chooser.waitFor({ state: 'detached' });
  await toast(`Found Fancy Client in ${fs.realpathSync(saved)}`).waitFor({ timeout: 15000 });
  await section.getByText('All the mods to download by hand are loaded.').waitFor();
  assert.equal(await page.evaluate(() => setupServerAttention()), '');
  await page.keyboard.press('Escape');

  // Craft Conductor settings → Folders lists it, and Forget takes it away.
  await page.goto(base + '/#craft-conductor');
  await page.getByRole('button', { name: 'Folders', exact: true }).click();
  const card = page.locator('.card', { hasText: 'Mods downloaded by hand' });
  await card.getByText(fs.realpathSync(saved), { exact: true }).waitFor();
  await card.getByRole('button', { name: 'Forget' }).click();
  await card.getByText('No other folders yet.', { exact: false }).waitFor();
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
