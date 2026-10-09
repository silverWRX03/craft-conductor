const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');

// Change version and the file check in a real browser (test_mod_checks_web.py sets the mods up):
// the friends' invite is paused while players' Minecraft wouldn't start, Manage Friends Mods glows
// and offers the fix; the version list; and Create my server waits on the setup page.
(async () => {
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({headless: true, ...(channel ? {channel} : {})});
  const page = await browser.newPage({viewport: {width: 1280, height: 900}});
  const base = process.argv[2];
  let r = await page.request.post(base + '/api/login', {data: {password: 'PASSWORD'}, headers: {'X-CRAFT-CONDUCTOR': '1'}});
  assert.equal(r.status(), 200);
  r = await page.request.post(base + '/api/auth/change', {data: {mode: 'pin', secret: '2468'}, headers: {'X-CRAFT-CONDUCTOR': '1'}});
  assert.equal(r.status(), 200);
  const drawer = page.locator('.mod-manager-drawer');
  const row = (name) => drawer.locator('.mod-manager-row').filter({has: page.locator('.mod-manager-name > strong', {hasText: new RegExp(`^${name}$`, 'i')})});

  // The Mods page: Terralith's file needs Lithostitched, which the server doesn't get. Manage Mods glows.
  await page.goto(base + '/#s/alpha/mods');
  await page.waitForFunction(() => [...document.querySelectorAll('button.attention')].some((b) => b.textContent.includes('Manage Mods')));
  await page.locator('button.attention', {hasText: 'Manage Mods'}).first().click();
  await drawer.waitFor();
  await drawer.locator('.mod-manager-row.has-problem').filter({has: page.locator('.mod-manager-name > strong', {hasText: /^terralith$/i})}).waitFor();
  assert.match(await row('Terralith').innerText(), /needs lithostitched \(1\.6\.3 or later\), which is missing/);
  assert.match(await drawer.innerText(), /The server wouldn't start with these mods/);
  await row('Terralith').getByRole('button', {name: 'Change version', exact: true}).waitFor();
  await page.keyboard.press('Escape');
  await drawer.waitFor({state: 'detached'});

  // The Friends page: Iris needs a Sodium players don't get.
  await page.goto(base + '/#s/alpha/friends');
  await page.getByText('The invite links are paused:', {exact: true}).waitFor();
  const manage = page.locator('[data-mod-summary] button', {hasText: 'Manage Friends Mods'}).first();
  await page.waitForFunction(() => [...document.querySelectorAll('button.attention')].some((b) => b.textContent.includes('Manage Friends Mods')));
  await manage.click();
  await drawer.waitFor();
  const iris = row('Iris');
  await drawer.locator('.mod-manager-row.has-problem').filter({has: page.locator('.mod-manager-name > strong', {hasText: /^Iris$/})}).waitFor();
  assert.match(await iris.innerText(), /needs Sodium any 0\.9\.x version, but Sodium 0\.8\.9 is the one there/);

  // Change version on Sodium: release builds always listed, beta ones on request, other Minecraft marked.
  const sodium = row('Sodium');
  await sodium.getByRole('button', {name: 'Change version', exact: true}).click();
  const picker = sodium.locator('.version-picker');
  await picker.locator('select').waitFor();
  const release = picker.getByRole('button', {name: 'Show release builds', exact: true});
  assert.equal(await release.isDisabled(), true);
  assert.equal(await release.getAttribute('aria-pressed'), 'true');
  const options = () => picker.locator('select option').allInnerTexts();
  assert.ok(!(await options()).some((o) => o.includes('0.9.0-beta')));
  await picker.getByRole('button', {name: 'Show beta builds', exact: true}).click();
  const withBeta = await options();
  assert.ok(withBeta.some((o) => o.startsWith('0.9.0-beta · Beta') && o.includes('made for Minecraft 1.21.2')), withBeta.join('\n'));
  await picker.locator('select').selectOption({label: withBeta.find((o) => o.startsWith('0.9.0-beta'))});
  assert.match(await picker.innerText(), /not 1\.21\.1: it may not start/);
  await picker.getByRole('button', {name: 'Cancel', exact: true}).click();
  await picker.waitFor({state: 'detached'});

  // The fix it found: Iris 1.10.9. The links work again, and Manage Friends Mods stops glowing.
  await iris.getByRole('button', {name: 'Use Iris 1.10.9', exact: true}).click();
  await iris.locator('.tag', {hasText: 'held at 1.10.9'}).waitFor();
  await page.waitForFunction(() => !document.querySelector('.mod-manager-row.has-problem'));
  await page.keyboard.press('Escape');
  await drawer.waitFor({state: 'detached'});
  await page.getByText('The invite links are paused:', {exact: true}).waitFor({state: 'detached'});
  assert.equal(await page.evaluate(() => [...document.querySelectorAll('button.attention')].some((b) => b.textContent.includes('Manage Friends Mods'))), false);

  // The setup page: a players' mod that wouldn't start keeps Create my server waiting.
  await page.goto(base + '/#new');
  await page.locator('#app').waitFor({state: 'visible'});
  await page.locator('button.choice', {hasText: 'Lightweight and quick to update'}).click();
  await page.locator('#setup-version').waitFor();
  await page.locator('#setup-version').selectOption('1.21.1');
  await page.evaluate(async () => {
    setupState.friends = true;
    setupState.clientMods.set('iris', 'Iris');
    await setupCheckFriendMods();
    setupState.rerender();
  });
  const create = page.getByRole('button', {name: 'Create my server', exact: true});
  await page.waitForFunction(() => document.querySelector('#setup-manage-friends.attention'), null, {timeout: 20000}).catch(async (e) => {
    console.error(JSON.stringify(await page.evaluate(() => ({check: setupState.fileCheck, body: setupCheckBody(), friends: setupFriendsAttention(),
      button: (document.querySelector('#setup-manage-friends') || {}).className}))));
    throw e;
  });
  assert.equal(await create.isDisabled(), true);
  await page.getByText('These mods wouldn\'t start together.', {exact: false}).waitFor();
  await page.locator('#setup-manage-friends').click();
  await drawer.waitFor();
  await drawer.getByRole('button', {name: 'Use Iris 1.10.9', exact: true}).click();
  await page.waitForFunction(() => setupState.fileCheck && !setupState.fileCheck.running && !fileCheckBad(setupState.fileCheck));
  assert.deepEqual(await page.evaluate(() => setupPins()), {'modrinth:IRIS': {version: 'IRIS-1.10.9', minecraft: '1.21.1'}});
  await page.keyboard.press('Escape');
  await drawer.waitFor({state: 'detached'});
  assert.equal(await create.isDisabled(), false);

  // A single-player game: the editor's Manage Mods glows, and the fix is offered there too.
  await page.goto(base + '/#servers');
  await page.evaluate(() => openSpEditor({id: 'abcdefabcdef', name: 'Shaders', loader: 'fabric', minecraft: '1.21.1', mods: ['iris'],
    memory_gb: 4, installed: null}, () => {}));
  const spManage = page.locator('.sp-picked button.attention', {hasText: 'Manage Mods'});
  await spManage.waitFor();
  await spManage.click();
  await drawer.waitFor();
  await row('Iris').getByRole('button', {name: 'Use Iris 1.10.9', exact: true}).click();
  await row('Iris').locator('.tag', {hasText: 'held at 1.10.9'}).waitFor();
  await page.waitForFunction(() => !document.querySelector('.mod-manager-row.has-problem') && !document.querySelector('.sp-picked button.attention'));

  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
