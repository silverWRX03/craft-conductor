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

  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
