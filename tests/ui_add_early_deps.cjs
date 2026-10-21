// Adding a mod to a server whose required library only has beta builds (#133): asked as New server
// asks ("only has beta builds… Add it anyway?"), then added; the mod browser's Add selected mods too.
// See test_early_builds.py.
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
  const question = page.locator('.toast-dialog', { hasText: 'Add it anyway?' });
  const configured = async () => (await (await page.request.get(base + '/api/servers/alpha/mods', { headers: H })).json()).configured;

  // Manage Mods' add: asked, Cancel adds nothing.
  let adding = page.evaluate(() => addServerMod({ source: 'modrinth', id: 'jei', required: true }));
  await question.waitFor();
  assert.match(await question.innerText(), /MezzConfig only has beta builds for Minecraft 1\.21\.1/);
  assert.doesNotMatch(await question.innerText(), /no compatible/);
  await question.getByRole('button', { name: 'Cancel' }).click();
  assert.equal(await adding, null);
  assert.equal((await configured()).some((s) => s.id === 'jei'), false);
  // Add anyway: added with the beta channel.
  adding = page.evaluate(() => addServerMod({ source: 'modrinth', id: 'jei', required: true }));
  await question.getByRole('button', { name: 'Add anyway' }).click();
  assert.deepEqual((await adding).deps, ['MezzConfig']);
  assert.equal((await configured()).find((s) => s.id === 'jei').channel, 'beta');

  // The mod browser's Add selected mods: skipped at first, asked once, then added.
  const many = page.evaluate(async () => {
    const mods = [{ source: 'modrinth', id: 'appleskin', name: 'AppleSkin' }, { source: 'modrinth', id: 'other-viewer', name: 'Other Viewer' }];
    const r = await api('/api/servers/alpha/mods/add-many', { method: 'POST', body: { mods } });
    return addManyEarly('alpha', mods, r);
  });
  const again = page.locator('.toast-dialog', { hasText: 'Add it anyway?' });
  await again.waitFor();
  assert.match(await again.innerText(), /MezzConfig only has beta builds/);
  await again.getByRole('button', { name: 'Add anyway' }).click();
  const r = await many;
  assert.deepEqual(r.added.sort(), ['AppleSkin', 'Other Viewer']);
  assert.deepEqual(r.skipped, []);
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
