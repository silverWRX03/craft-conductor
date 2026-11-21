// Creating a server's steps and progress bar, and Make a modpack (see test_ui_mods_and_packs.py).
const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');
(async () => {
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  const base = process.argv[2];
  const H = { 'X-CRAFT-CONDUCTOR': '1' };
  const errors = [];
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce', acceptDownloads: true });
  await context.addInitScript(() => { localStorage.setItem('craft-conductor-sounds', 'off'); });
  const page = await context.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  assert.equal((await page.request.post(base + '/api/login', { data: { password: 'PASSWORD' }, headers: H })).status(), 200);
  assert.equal((await page.request.post(base + '/api/auth/change', { data: { mode: 'password', secret: 'Owner-Strong-Pass-1' }, headers: H })).status(), 200);
  assert.equal((await page.request.post(base + '/api/login', { data: { password: 'Owner-Strong-Pass-1' }, headers: H })).status(), 200);
  await page.goto(base + '/#servers');
  await page.locator('#app').waitFor({ state: 'visible' });

  // The steps of creating a server, and how far the bar is.
  const s = await page.evaluate(() => setupSteps({ steps: ['plan', 'java', 'mods', 'runtime', 'boot'], step: 'mods', done: 1, total: 4 }));
  assert.deepEqual(s.items.map((x) => x.state), ['done', 'done', 'now', 'later', 'later']);
  assert.equal(s.value, (2 + 0.25) / 5);
  assert.equal(s.label, 'Downloading the mods: 1 of 4');
  const none = await page.evaluate(() => setupSteps(undefined));
  assert.deepEqual(none, { items: [], value: 0, label: '' });

  // Make a modpack, on the Mods page: Modrinth's format first, CurseForge's on choosing it.
  await page.goto(base + '/#s/alpha/mods');
  await page.getByRole('button', { name: 'Make a modpack…' }).click();
  const dialog = page.getByRole('dialog', { name: 'Make a modpack' });
  await dialog.waitFor();
  assert.match(await dialog.innerText(), /Modrinth \(\.mrpack\)/);
  await dialog.getByText(/mod\(s\) go in/).waitFor();
  await dialog.getByLabel('CurseForge (.zip)').check();
  const link = dialog.getByRole('link', { name: 'Download' });
  await page.waitForFunction(() => /format=curseforge/.test((document.querySelector('[role=dialog] a[download]') || {}).href || ''));
  const [download] = await Promise.all([page.waitForEvent('download'), link.click()]);
  assert.match(download.suggestedFilename(), /\.zip$/);

  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
