// New server: a mod from the mod browser that runs on both sides goes in friends' mods too, with its
// library; with no build of that library for the chosen Minecraft, its row says Dependency unavailable.
// Remove there asks about friends' mods, as the row's own Remove does (#147). See test_ui_browser.py.
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
  await page.goto(base + '/#new');
  await page.waitForLoadState('networkidle');
  if (await page.locator('#security').count()) {  // (the default password: not now)
    await page.locator('#security').getByRole('button', { name: 'Not now' }).click();
    await page.locator('#security').waitFor({ state: 'detached' });
  }
  await page.locator('.choice', { hasText: 'Lightweight and quick to update' }).click();
  await page.locator('#setup-version').waitFor();
  await page.evaluate(() => { setupState.mods.clear(); setupState.clientMods.clear(); setupState.minecraft = '1.21.2'; setupState.friends = true; setupState.rerender(); });
  await page.evaluate(() => setupAddFromBrowser([{ source: 'modrinth', id: 'recipes', slug: 'recipes', name: 'Recipe Viewer' }]));
  await page.waitForFunction(() => setupState.mods.get('recipes') && setupState.mods.get('recipes').conflict);
  assert.deepEqual(await page.evaluate(() => [...setupState.clientMods.keys()].sort()), ['recipe-lib', 'recipes']);
  await page.getByRole('button', { name: 'Manage Mods', exact: true }).click();
  const drawer = page.locator('.mod-manager-drawer');
  const conflict = drawer.locator('.notice.warn', { hasText: 'Dependency unavailable' });
  await conflict.getByRole('button', { name: 'Remove Recipe Viewer', exact: true }).click();
  const question = page.locator('.toast-dialog', { hasText: "also in your friends' mods" });
  await question.waitFor();
  assert.match(await question.innerText(), /Recipe Viewer and Recipe Library are also in your friends' mods/);
  await question.getByRole('button', { name: "Remove from friends' mods" }).click();
  await page.waitForFunction(() => setupState.clientMods.size === 0);
  assert.equal(await page.evaluate(() => setupState.mods.size), 0);
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
