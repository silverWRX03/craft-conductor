const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');

(async () => {
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({headless: true, ...(channel ? {channel} : {})});
  const page = await browser.newPage({viewport: {width: 1280, height: 900}});
  const base = process.argv[2];

  let r = await page.request.post(base + '/api/login', {
    data: {password: 'PASSWORD'}, headers: {'X-CRAFT-CONDUCTOR': '1'}
  });
  assert.equal(r.status(), 200);
  r = await page.request.post(base + '/api/auth/change', {
    data: {mode: 'pin', secret: '2468'}, headers: {'X-CRAFT-CONDUCTOR': '1'}
  });
  assert.equal(r.status(), 200);

  await page.goto(base + '/#new');
  await page.locator('#app').waitFor({state: 'visible'});
  await page.locator('button.choice', {hasText: 'Lightweight and quick to update'}).click();
  await page.locator('#setup-version').waitFor();

  assert.deepEqual(await page.evaluate(() => modSummaryCounts([
    {name: 'Picked', channel: 'release'},
    {name: 'Library', dependency: true, channel: 'beta'},
    {name: 'Removed', channel: 'alpha', removed: true},
    {name: 'Client only', channel: 'release', excludedFromCount: true},
  ])), {total: 2, dependencies: 1, early: 1, removed: 1});

  await page.evaluate(() => {
    window.modManagementAdd = setupAddMod('drawer-main', 'Drawer Main');
  });
  await page.getByRole('button', {name: 'Add anyway', exact: true}).click();
  await page.evaluate(() => window.modManagementAdd);

  const summary = page.locator('[data-mod-summary="mods"]').first();
  await summary.waitFor();
  assert.match(await summary.innerText(), /2 mods added/);
  assert.match(await summary.innerText(), /1 added automatically as dependencies/);
  assert.match(await summary.innerText(), /1 are Beta or Alpha releases/);

  const before = await page.evaluate(() => [...setupState.mods.keys()]);
  await summary.getByRole('button', {name: 'Manage Mods', exact: true}).click();
  const drawer = page.locator('.mod-manager-drawer');
  await drawer.waitFor();
  await page.getByText('Drawer Library', {exact: true}).waitFor();
  assert.match(await drawer.innerText(), /dependency.*needed by Drawer Main/i);

  await page.keyboard.press('Escape');
  await drawer.waitFor({state: 'detached'});
  assert.deepEqual(await page.evaluate(() => [...setupState.mods.keys()]), before);

  // Removing a pack's mods asks nothing (ten removals were ten pop-ups): an Undo bar shows, and Undo puts the mod back
  await page.evaluate(() => {
    setupState.modpack = {name: 'Test Pack', version_id: 'curseforge:9', removed: new Set(),
      mods: [1, 2, 3].map((n) => ({path: `mods/pack${n}.jar`, name: `Pack Mod ${n}`, source: 'curseforge', project_id: String(n),
        version: '1', minecraft: ['1.21.1'], loaders: ['fabric'], included_on_server: true}))};
    openModManager({title: 'Pack test', getItems: () => setupServerModItems().filter((m) => m.key.startsWith('pack:'))});
  });
  const pack = page.locator('.mod-manager-drawer');
  await pack.waitFor();
  const rowOf = (n) => pack.locator('.mod-manager-row', {hasText: `Pack Mod ${n}`});
  for (const n of [1, 2]) await rowOf(n).getByRole('button', {name: 'Remove', exact: true}).click();
  assert.equal(await page.locator('.toast-dialog').count(), 0, 'no question');
  assert.deepEqual(await page.evaluate(() => [...setupState.modpack.removed]), ['mods/pack1.jar', 'mods/pack2.jar']);
  assert.match(await rowOf(1).innerText(), /manually removed/);
  const undo = page.locator('#toasts .toast.sticky').filter({hasText: 'Removed Pack Mod 2.'});
  await undo.getByRole('button', {name: 'Undo'}).click();
  assert.deepEqual(await page.evaluate(() => [...setupState.modpack.removed]), ['mods/pack1.jar']);
  assert.doesNotMatch(await rowOf(2).innerText(), /manually removed/);
  await page.keyboard.press('Escape');
  await pack.waitFor({state: 'detached'});

  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
