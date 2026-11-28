const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');
(async () => {
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({headless: true, ...(channel ? {channel} : {})});
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}, reducedMotion: 'no-preference'});
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const base = process.argv[2];
  const response = await page.request.post(base + '/api/login', {data: {password: 'PASSWORD'}, headers: {'X-CRAFT-CONDUCTOR': '1'}});
  assert.equal(response.status(), 200);
  assert.equal((await page.request.post(base + '/api/auth/change', {data:{mode:'pin',secret:'2468'}, headers:{'X-CRAFT-CONDUCTOR':'1'}})).status(), 200);
  await page.addInitScript(() => { localStorage.setItem('craft-conductor-theme', 'night'); localStorage.setItem('craft-conductor-sounds', 'off'); });
  const go = async hash => {
    await page.goto(base + '/#' + hash);
    await page.locator('#app').waitFor({state:'visible'});
    await page.waitForTimeout(600);
  };
  // Every checkbox on the screen sits beside its words (not above them, nor alone on its line).
  const misplacedCheckboxes = () => page.evaluate(() => [...document.querySelectorAll('input[type=checkbox]')]
    .filter(b => b.offsetParent !== null && b.closest('label')).map(b => {
      const label = b.closest('label'), words = document.createRange();
      words.setStartAfter(b); words.setEnd(label, label.childNodes.length);
      const w = [...words.getClientRects()].find(r => r.width > 0 && r.height > 0), box = b.getBoundingClientRect();
      return !w || (w.left >= box.right - 1 && w.top < box.bottom && w.bottom > box.top) ? null : label.textContent.trim().slice(0, 60);
    }).filter(Boolean));
  await go('craft-conductor');
  await page.getByRole('button', {name:'Appearance', exact:true}).waitFor();
  assert.equal(await page.locator('.preferences-panel:not(.hidden)').count(), 1);
  await page.evaluate(() => applyTheme('day'));
  await page.evaluate(() => applyTheme('night'));
  await page.getByRole('button', {name:'Connections', exact:true}).click();
  await page.getByLabel('CurseForge API key', {exact:true}).fill('unsaved-test-value');
  await page.getByRole('button', {name:'Appearance', exact:true}).click();
  await page.getByRole('button', {name:'Connections', exact:true}).click();
  assert.equal(await page.getByLabel('CurseForge API key', {exact:true}).inputValue(), 'unsaved-test-value');
  await page.getByLabel('CurseForge API key', {exact:true}).fill('');
  await go('s/alpha/settings');
  await page.getByRole('button', {name:'Save settings', exact:true}).waitFor();
  const memory = page.locator('#main input').filter({visible:true});
  await page.evaluate(() => { window.savedMain = document.querySelector('#main').firstElementChild; document.querySelector('#main').scrollTop = 200; });
  const scroll = await page.locator('#main').evaluate(el => el.scrollTop);
  await page.locator('#nav a[href="#help"]').click();
  await page.locator('.help-overlay').waitFor();
  await page.waitForTimeout(350);
  assert.equal(await page.locator('.help-contents .help-toc').count(), 1);
  await page.getByRole('button', {name:'User manual', exact:true}).click();
  await page.locator('.help-contents .help-toc li').first().waitFor();
  await page.waitForTimeout(350);
  await page.keyboard.press('Escape');
  await page.locator('.help-overlay').waitFor({state:'detached'});
  assert.equal(await page.evaluate(() => document.querySelector('#main').firstElementChild === window.savedMain), true);
  assert.equal(await page.locator('#main').evaluate(el => el.scrollTop), scroll);
  assert.equal(new URL(page.url()).hash, '#s/alpha/settings');
  await page.locator('#main').evaluate(el => el.scrollTop = 0);
  // Server settings: each checkbox beside its words at any width, Save settings and Cancel always
  // in view, and unsaved changes must be saved or cancelled before going to another page.
  const barInView = () => page.locator('.save-bar').evaluate(el => el.getBoundingClientRect().bottom <= innerHeight + 1);
  assert.deepEqual(await misplacedCheckboxes(), []);
  assert.equal(await barInView(), true);
  await page.setViewportSize({width:390,height:844});
  assert.deepEqual(await misplacedCheckboxes(), []);
  assert.equal(await barInView(), true);
  await page.setViewportSize({width:1440,height:1000});
  const cancel = page.locator('.save-bar').getByRole('button', {name:'Cancel', exact:true});
  const waitBox = page.getByLabel('Wait until nobody is online', {exact:true});
  const waited = await waitBox.isChecked();
  assert.equal(await cancel.isDisabled(), true);
  await waitBox.click();
  assert.equal(await cancel.isDisabled(), false);
  await page.locator('#nav a[href="#s/alpha/dashboard"]').click();
  await page.locator('#unsaved').waitFor();
  assert.equal(new URL(page.url()).hash, '#s/alpha/settings');
  await page.locator('#unsaved').getByRole('button', {name:'Stay here', exact:true}).click();
  assert.equal(await waitBox.isChecked(), !waited);
  await page.locator('#nav a[href="#help"]').click();  // (Help opens over the page: nothing to ask)
  await page.locator('.help-overlay').waitFor();
  assert.equal(await page.locator('#unsaved').count(), 0);
  await page.keyboard.press('Escape');
  await page.locator('.help-overlay').waitFor({state:'detached'});
  await page.evaluate(() => { location.hash = '#servers'; });  // (Back, or a typed address)
  await page.locator('#unsaved').waitFor();
  assert.equal(new URL(page.url()).hash, '#s/alpha/settings');
  await page.locator('#unsaved').getByRole('button', {name:'Cancel changes', exact:true}).click();
  await page.waitForFunction(() => location.hash === '#servers' && !document.querySelector('.save-bar'));
  await go('s/alpha/settings');
  assert.equal(await waitBox.isChecked(), waited);
  await waitBox.click();
  await page.locator('.save-bar').getByRole('button', {name:'Cancel', exact:true}).click();
  await page.waitForFunction(w => document.querySelector('.save-bar button[type=button]').disabled &&
    [...document.querySelectorAll('.checks label')].find(l => l.textContent === 'Wait until nobody is online').querySelector('input').checked === w, waited);
  await page.getByLabel('Port players connect to', {exact:true}).fill('25570');  // (the test's other server has 25565)
  await waitBox.click();
  await page.locator('#nav a[href="#s/alpha/dashboard"]').click();
  await page.locator('#unsaved').getByRole('button', {name:'Save settings', exact:true}).click();
  await page.waitForFunction(() => location.hash === '#s/alpha/dashboard');
  await go('s/alpha/settings');
  assert.equal(await waitBox.isChecked(), !waited);
  // The Remote access & phones dialog keeps its Close button in view however far it's scrolled.
  await page.evaluate(() => openRemoteAccess());
  await page.locator('.remote-step').first().waitFor();
  await page.locator('#remote .modal').evaluate(el => { el.scrollTop = el.scrollHeight; });
  const closeShown = () => page.locator('#remote .modal-head button').evaluate(b => {
    const r = b.getBoundingClientRect();
    return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) === b;
  });
  assert.equal(await closeShown(), true);
  await page.locator('#remote').getByRole('button', {name:'Close',exact:true}).click();
  for (const view of ['servers', 's/alpha/dashboard', 's/alpha/players', 's/alpha/updates', 's/alpha/mods', 's/alpha/friends', 's/alpha/backups', 's/alpha/java', 'new']) {
    await go(view);
    assert.deepEqual(await misplacedCheckboxes(), [], view);
  }
  // The sidebar: the pages used every day first, then Maintenance, folded until opened (remembered in this browser),
  // and open by itself while one of its pages is on show.
  await go('s/alpha/dashboard');
  const order = await page.locator('#nav a[href^="#s/alpha/"]').evaluateAll((as) => as.map((a) => a.getAttribute('href').split('/').pop()));
  assert.deepEqual(order, ['dashboard', 'friends', 'players', 'mods', 'updates', 'backups', 'java', 'settings']);
  const upkeep = page.locator('#nav .nav-group');
  const backupsLink = page.locator('#nav a[href="#s/alpha/backups"]');
  assert.equal(await upkeep.getAttribute('aria-expanded'), 'false', 'Maintenance starts folded');
  assert.ok(!(await backupsLink.isVisible()), 'Backups is folded away');
  await upkeep.click();
  assert.equal(await upkeep.getAttribute('aria-expanded'), 'true');
  await backupsLink.waitFor();
  await page.reload();
  await page.locator('#nav .nav-group').waitFor();
  assert.equal(await upkeep.getAttribute('aria-expanded'), 'true', 'kept open after a reload');
  await upkeep.click();
  assert.ok(!(await backupsLink.isVisible()), 'folded again');
  await go('s/alpha/backups');
  assert.equal(await upkeep.getAttribute('aria-expanded'), 'true', 'open while on Backups');
  assert.equal(await backupsLink.getAttribute('aria-current'), 'page');
  await go('s/alpha/dashboard');
  assert.equal(await upkeep.getAttribute('aria-expanded'), 'false', 'folded again on the Dashboard: as it was left');
  // There's no Console page: the console is the Dashboard's, with the logs and crash reports folders at its top right,
  // and an old Console link opens the Dashboard with the command box ready.
  assert.equal(await page.locator('#nav a[href="#s/alpha/console"]').count(), 0);
  const head = page.locator('.cc-console-widget .console-head');
  assert.deepEqual(await head.locator('.console-tools button').allInnerTexts().then((t) => t.map((x) => x.replace(/^\W+/, '').trim())), ['Logs folder', 'Crash reports']);
  const sides = await head.evaluate((el) => { const h = el.querySelector('h3').getBoundingClientRect(), t = el.querySelector('.console-tools').getBoundingClientRect(), r = el.getBoundingClientRect();
    return { titleLeft: Math.round(h.left - r.left), toolsRight: Math.round(r.right - t.right), sameRow: Math.abs(h.top + h.height / 2 - (t.top + t.height / 2)) < 12 }; });
  assert.ok(sides.titleLeft <= 2 && sides.toolsRight <= 2 && sides.sameRow, 'title on the left, folders on the right: ' + JSON.stringify(sides));
  assert.ok(await page.locator('.cc-dashboard-rail .players-card').isVisible(), 'Connected Players beside the console');
  await go('s/alpha/console');
  assert.ok((await page.title()).startsWith('Dashboard'), 'an old Console link opens the Dashboard');
  await page.waitForFunction(() => document.activeElement && document.activeElement.getAttribute('aria-label') === 'Server command');
  // The top row: CPU, RAM, Disk, Players and Performance. The console's Activity / Console switch (remembered, with the
  // command box in both); under it Check my setup and Why am I lagging?; no Updates card; no state in Runtime Parameters.
  await go('s/alpha/dashboard');
  assert.deepEqual(await page.locator('.cc-telemetry-grid .meter-head span').allInnerTexts(), ['CPU', 'RAM', 'Disk', 'Players', 'Performance']);
  const minecraft = page.locator('.cc-console-widget .console:not(.activity-log)'), activityBox = page.locator('.activity-log');
  assert.ok(await minecraft.isVisible() && !(await activityBox.isVisible()), 'the console at first');
  await page.getByRole('group', { name: 'What the box shows' }).getByRole('radio', { name: 'Activity' }).check();
  assert.ok(await activityBox.isVisible() && !(await minecraft.isVisible()), 'Activity instead');
  assert.equal(await page.locator('.cc-console-widget h3').innerText(), 'Activity');
  assert.ok(await page.locator('.console-input input').isVisible(), 'the command box in Activity too');
  await page.reload();
  await activityBox.waitFor();
  assert.ok(await activityBox.isVisible(), 'Activity kept after a reload');
  await page.getByRole('group', { name: 'What the box shows' }).getByRole('radio', { name: 'Console' }).check();
  assert.ok(await minecraft.isVisible());
  assert.match(await page.locator('.dash-tools').innerText(), /Check my setup[\s\S]*Why am I lagging\?/);
  assert.equal(await page.getByRole('heading', { name: 'Updates', level: 3 }).count(), 0, 'no Updates card on the Dashboard');
  assert.ok(!(await page.locator('.cc-dashboard-rail dl.kv').innerText()).includes('State'), 'the state is in the top bar');
  assert.ok(!(await page.locator('.console-input button').getAttribute('class')).includes('primary'), 'Send is an ordinary button');
  assert.ok(await page.getByRole('heading', { level: 1, name: 'Dashboard' }).count() === 1 && !(await page.locator('h1.view-title').evaluate((e) => e.getBoundingClientRect().width > 1)),
    'the page heading is there for screen readers, not drawn');
  await go('s/alpha/dashboard');
  await page.evaluate(() => openDoctor());
  await page.waitForFunction(() => document.querySelectorAll('.doctor-list li').length > 1);
  await page.locator('#doctor').getByRole('button', {name:'Close',exact:true}).click();
  await go('s/alpha/players');
  await page.getByRole('heading', {name:'Player activity',exact:true}).scrollIntoViewIfNeeded();
  // Step 4: Friends page decluttering — no toggle card, no "recommended", reach descriptions behind ⓘ,
  // and ordinary action buttons (not .cta) use the standard button style.
  await go('s/alpha/friends');
  await page.locator('.choice-wrap .info-tip').first().waitFor();
  const friendsText = await page.locator('#main').innerText();
  assert.ok(!friendsText.includes("How friends who aren't on your Wi-Fi join this server"), 'no redundant subtitle');
  assert.ok(!friendsText.includes('(recommended)'), 'no (recommended) tag on playit.gg');
  assert.ok(!friendsText.includes('Let friends set up their Minecraft') && !friendsText.includes('Make a download for friends'),
    'friends download is always on without a toggle card');
  const firstTip = page.locator('.choice-wrap .info-tip').first();
  await firstTip.click();
  assert.equal(await firstTip.getAttribute('aria-expanded'), 'true');
  const bubble = page.locator('.choice-wrap .info-bubble').first();
  assert.ok(await bubble.isVisible() && (await bubble.innerText()).includes('Nothing is opened on your router'));
  await page.keyboard.press('Escape');
  assert.equal(await firstTip.getAttribute('aria-expanded'), 'false');
  await go('s/alpha/backups');
  const backupBtnBg = await page.getByRole('button', { name: 'Back up now', exact: true }).evaluate((b) => getComputedStyle(b).backgroundColor);
  const startBtnBg = await page.locator('#btn-start').evaluate((b) => getComputedStyle(b).backgroundColor);
  assert.notEqual(backupBtnBg, startBtnBg, 'ordinary primary buttons do not carry the filled accent');
  assert.ok((await page.locator('#main .info-tip').count()) >= 3, 'Backups helper text behind ⓘ');
  await go('s/alpha/java');
  await page.locator('#main .info-tip').first().waitFor();
  assert.ok((await page.locator('#main .info-tip').count()) >= 2, 'Java helper text behind ⓘ');
  await go('s/alpha/settings');
  await page.locator('#main .info-tip').first().waitFor();
  assert.ok((await page.locator('#main .info-tip').count()) >= 5, 'Settings helper text behind ⓘ');
  await page.getByRole('heading', {name:/^Web map/}).scrollIntoViewIfNeeded();
  await go('craft-conductor');
  await page.evaluate(() => openRemoteAccess());
  await page.locator('.remote-step').first().waitFor();
  await page.locator('#remote').getByRole('button', {name:'Close',exact:true}).click();
  await go('new');
  await page.evaluate(() => openBrowser({target:'setup',loader:'fabric',version:'1.21.1'}));
  await page.locator('.result').first().waitFor();
  await page.waitForTimeout(350);
  await page.keyboard.press('Escape');
  await page.locator('.inpage-browser').waitFor({state:'detached'});
  await page.evaluate(() => {
    setupState.loader = 'fabric'; setupState.minecraft = '1.21.1';
    window.addingDependency = setupAddMod('example-worldgen', 'Example world generation');
  });
  await page.getByRole('button', {name:'Add anyway', exact:true}).click();
  await page.evaluate(() => window.addingDependency);
  assert.equal(await page.evaluate(() => setupState.mods.get('example-worldgen').channel), 'beta');
  assert.equal(await page.evaluate(() => setupState.mods.has('example-library')), true);
  // Step 5: New server opens on Quick start; picking a preset shows Finish setup without the 5-step form,
  // and Custom setup keeps the preset's choices pre-filled.
  await go('new');
  const quickTab = page.getByRole('tab', { name: 'Quick start' });
  const customTab = page.getByRole('tab', { name: 'Custom setup' });
  assert.equal(await quickTab.getAttribute('aria-selected'), 'true', 'Quick start opens first');
  assert.equal(await page.getByRole('heading', { name: '1. Server type' }).count(), 0, 'Custom form hidden on Quick start');
  await page.locator('button.choice', { hasText: 'Vanilla Minecraft with friends' }).click();
  await page.getByRole('heading', { name: 'Finish setup' }).waitFor();
  assert.equal(await page.locator('#setup-version').count(), 0, 'preset keeps Quick start compact');
  await quickTab.focus();
  await page.keyboard.press('ArrowRight');
  assert.equal(await customTab.getAttribute('aria-selected'), 'true', 'ArrowRight switches to Custom setup');
  await page.locator('#setup-version').waitFor();
  // A required library with no build for the chosen Minecraft: the row explains, and only you change the version.
  await page.evaluate(() => resetSetup());
  await go('s/alpha/dashboard');
  await go('new');
  await page.getByRole('tab', { name: 'Custom setup' }).click();
  await page.locator('.choice', {hasText: 'Lightweight and quick to update'}).click();
  await page.locator('#setup-version').waitFor();
  await page.evaluate(() => { setupState.mods.clear(); setupState.minecraft = '1.21.2'; setupState.rerender(); });
  await page.evaluate(() => setupAddMod('needs-gone', 'Needs Gone'));
  await page.waitForFunction(() => setupState.mods.get('needs-gone') && setupState.mods.get('needs-gone').conflict);
  // (the mod's row in Manage Mods explains)
  const manage = page.getByRole('button', {name: 'Manage Mods', exact: true});
  const drawer = page.locator('.mod-manager-drawer');
  await manage.click();
  const conflict = drawer.locator('.notice.warn', {hasText: 'Dependency unavailable'});
  await conflict.waitFor();
  assert.match(await conflict.innerText(), /Needs Gone requires Gone Library, but no compatible Gone Library release was found for Minecraft 1\.21\.2 using Fabric\. Craft Conductor checked Modrinth/);
  assert.match(await conflict.innerText(), /will not change your server type or Minecraft version automatically/);
  assert.equal(await page.evaluate(() => setupState.minecraft), '1.21.2');
  await conflict.getByRole('button', {name: 'Remove Needs Gone', exact: true}).waitFor();
  // Choose another Minecraft version: back to the page, at the version picker.
  await conflict.getByRole('button', {name: 'Choose another Minecraft version', exact: true}).click();
  await drawer.waitFor({state: 'detached'});
  assert.equal(await page.evaluate(() => document.activeElement.id), 'setup-version');
  assert.equal(await page.evaluate(() => setupState.minecraft), '1.21.2');
  await manage.click();
  await conflict.getByRole('button', {name: 'Use Minecraft 1.21.1', exact: true}).click();
  await page.getByRole('button', {name: 'Change Minecraft version', exact: true}).click();
  await page.waitForFunction(() => setupState.minecraft === '1.21.1' && !setupState.mods.get('needs-gone').bad);
  assert.equal(await page.locator('#setup-version').inputValue(), '1.21.1');
  await page.keyboard.press('Escape');
  await drawer.waitFor({state: 'detached'});
  await page.evaluate(() => setupRemoveMod('needs-gone'));
  // A new server type the mods don't all have (#81): Manage Mods glows (no red dot) and the page goes
  // to it; it says what changed and offers the ways out, the datapack too. Then the players' mods.
  await page.evaluate(() => {
    setupState.mods.clear(); setupState.clientMods.clear(); setupState.loader = 'fabric'; setupState.minecraft = '1.21.1'; setupState.rerender();
  });
  await page.evaluate(() => setupAddMod('terralith', 'Terralith'));
  await page.waitForFunction(() => setupState.mods.has('lithostitched'));
  await page.evaluate(() => {
    setupState.friends = true; setupState.clientMods.set('fabric-zoom', 'Fabric Zoom'); setupState.clientMeta.set('fabric-zoom', {}); setupState.rerender();
  });
  const glows = (id) => page.evaluate(id => !!document.querySelector(`#${id}.attention`), id);
  const inView = (id) => page.waitForFunction(id => {
    const r = document.getElementById(id).getBoundingClientRect();
    return r.top >= 0 && r.bottom <= innerHeight;
  }, id);
  assert.equal(await glows('setup-manage-mods'), false);
  assert.equal(await page.locator('#setup-manage-mods .update-dot').count(), 0);
  await page.evaluate(() => { window.scrollTo(0, 0); setupState.loader = 'forge'; setupRecheckMods(true); setupState.rerender(); });
  await page.waitForFunction(() => document.querySelector('#setup-manage-mods.attention'));
  await inView('setup-manage-mods');
  assert.equal(await glows('setup-manage-friends'), true);
  assert.equal(await page.evaluate(() => setupState.mods.has('lithostitched')), false);
  const shot = process.env.CRAFT_UI_ATTENTION_SCREENSHOT;  // (to look at: the glowing button, then the notice)
  if (shot) await page.screenshot({path: shot});
  await page.locator('#setup-manage-mods').click();
  if (shot) { await page.waitForTimeout(400); await page.screenshot({path: shot.replace(/\.png$/, '-drawer.png')}); }
  const whatChanged1 = drawer.locator('details[aria-label="What changed"]');
  assert.equal(await whatChanged1.evaluate((el) => el.open), false, 'What changed starts folded');
  await whatChanged1.locator('summary').click();
  assert.match(await whatChanged1.innerText(),
    /Lithostitched was removed: Terralith has no build for Forge 1\.21\.1, so nothing needs it now/);
  const noForge = drawer.locator('.notice.warn', {hasText: 'No Forge build for Minecraft 1.21.1'});
  assert.match(await noForge.innerText(), /It has NeoForge and Fabric builds for Minecraft 1\.21\.1 and a datapack build/);
  await noForge.getByRole('button', {name: 'Use NeoForge', exact: true}).waitFor();
  await noForge.getByRole('button', {name: 'Stay on Forge: use its datapack', exact: true}).click();
  await drawer.locator('.tag', {hasText: 'datapack'}).waitFor();
  const whatChanged1b = drawer.locator('details[aria-label="What changed"]');
  if (!(await whatChanged1b.evaluate((el) => el.open))) await whatChanged1b.locator('summary').click();
  await drawer.getByText("Terralith uses its datapack build on Forge, in the world's datapacks folder: it doesn't need Lithostitched.", {exact: true}).waitFor();
  assert.deepEqual(await page.evaluate(() => setupDatapacks()), ['terralith']);
  await page.keyboard.press('Escape');
  await drawer.waitFor({state: 'detached'});
  assert.equal(await glows('setup-manage-mods'), false);  // (nothing left to fix: no glow)
  await inView('setup-manage-friends');  // then the players' mods
  assert.equal(await glows('setup-manage-friends'), true);
  await page.evaluate(() => {
    setupState.clientMods.clear(); setupState.clientMeta.clear(); setupState.friends = false;
    setupState.mods.clear(); setupState.loader = 'fabric'; setupState.rerender();
  });
  // The same when only the Minecraft version changes: Terralith has nothing at all for 1.21.2.
  await page.evaluate(() => setupAddMod('terralith', 'Terralith'));
  await page.waitForFunction(() => setupState.mods.has('lithostitched'));
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.locator('#setup-version').selectOption('1.21.2');
  await page.waitForFunction(() => document.querySelector('#setup-manage-mods.attention'));
  await inView('setup-manage-mods');
  await page.locator('#setup-manage-mods').click();
  const whatChanged2 = drawer.locator('details[aria-label="What changed"]');
  assert.equal(await whatChanged2.evaluate((el) => el.open), false, 'What changed starts folded');
  await whatChanged2.locator('summary').click();
  assert.match(await whatChanged2.innerText(),
    /Lithostitched was removed: Terralith has no build for Fabric 1\.21\.2, so nothing needs it now/);
  const noBuild = drawer.locator('.notice.warn', {hasText: 'No Fabric build for Minecraft 1.21.2'});
  await noBuild.getByRole('button', {name: 'Use Minecraft 1.21.1', exact: true}).click();
  await page.getByRole('button', {name: 'Change Minecraft version', exact: true}).click();
  await page.waitForFunction(() => setupState.minecraft === '1.21.1' && setupState.mods.has('lithostitched') && !setupState.mods.get('terralith').bad);
  const whatChanged3 = drawer.locator('details[aria-label="What changed"]');
  if (!(await whatChanged3.evaluate((el) => el.open))) await whatChanged3.locator('summary').click();
  await drawer.getByText('Lithostitched was added: Terralith needs it on Fabric 1.21.1.', {exact: true}).waitFor();
  await page.keyboard.press('Escape');
  await drawer.waitFor({state: 'detached'});
  assert.equal(await glows('setup-manage-mods'), false);
  await page.evaluate(() => { setupState.mods.clear(); setupState.rerender(); });
  // Exercise the actual backend preview and render it in the world-generation pane.
  const preview = await page.evaluate(async () => {
    const r = await api('/api/hub/preview', {method:'POST', body:{loader:'fabric', minecraft:'1.21.1', mods:['example-worldgen'], channels:{'example-worldgen':'beta'}, seed:'25698412121455', level_type:'minecraft:normal', structures:true, radius:128}});
    return r.id;
  });
  let map;
  for (let i = 0; i < 120; i++) {
    map = await page.evaluate(id => api(`/api/hub/preview?id=${id}`), preview);
    if (map.state === 'done' || map.state === 'failed') break;
    await page.waitForTimeout(250);
  }
  assert.equal(map.state, 'done', JSON.stringify(map));
  assert.ok(map.map, JSON.stringify(map));
  await page.evaluate(m => {
    setupState.loader = 'fabric'; setupState.minecraft = '1.21.1'; setupState.previews = [m];
    openWorldPanel();
  }, map);
  await page.locator('.map-tile').first().waitFor();
  await page.waitForFunction(() => [...document.querySelectorAll('.map-tile')].some(img => img.complete && img.naturalWidth > 0));
  assert.equal(await page.locator('.map-spawn').evaluate(el => Number.isFinite(parseFloat(el.style.left))), true);
  // The map panel has no structures box: maps are always made with them, and whether the server's
  // world has them stays on the World card (the panel says when it won't; Use this seed leaves it).
  const panel = page.locator('.inpage-browser');
  assert.equal(await panel.getByText('Villages, temples and other structures', {exact: true}).count(), 0);
  const noStructures = panel.getByText("this server's world won't have them", {exact: false});
  assert.equal(await noStructures.count(), 0);
  await page.keyboard.press('Escape');
  await panel.waitFor({state: 'detached'});
  const was = await page.evaluate(() => {
    const P = setupState.properties, before = {seed: P['level-seed'], structures: P['generate-structures']};
    P['generate-structures'] = 'false';
    openWorldPanel();
    return before;
  });
  await noStructures.waitFor();
  await panel.getByRole('button', {name: 'Use this seed', exact: true}).click();
  assert.equal(await page.evaluate(() => setupState.properties['level-seed']), '25698412121455');
  assert.equal(await page.evaluate(() => setupState.properties['generate-structures']), 'false');
  await page.evaluate(w => {
    const P = setupState.properties;
    for (const [k, v] of [['level-seed', w.seed], ['generate-structures', w.structures]]) { if (v === undefined) delete P[k]; else P[k] = v; }
  }, was);
  await page.waitForFunction(() => [...document.querySelectorAll('.map-tile')].some(img => img.complete && img.naturalWidth > 0));
  // The world generation mods keep coming as the list scrolls, as in the mod browser.
  await page.locator('.browse-results .result', {hasText: 'Example world generation'}).waitFor();
  await page.locator('.browse-results .pager-foot', {hasText: "That's everything"}).waitFor();
  // A clean map: points of interest stay hidden (and unfetched) until asked for, after a warning.
  const poiBox = page.getByLabel('Show Points of Interest', {exact: true});
  const pois = page.locator('.map-mark');
  let poiAsks = 0;
  page.on('request', req => { if (req.url().includes('/api/hub/map/poi')) poiAsks++; });
  await page.waitForTimeout(400);
  assert.equal(await poiBox.isChecked(), false);
  assert.equal(await pois.count(), 0);
  assert.equal(poiAsks, 0);
  await poiBox.click();
  const keep = page.getByRole('button', {name: 'Keep Hidden', exact: true});
  await keep.waitFor();
  const warning = await page.locator('.modal-backdrop', {has: keep}).innerText();
  assert.match(warning, /competitive speedrunning without a set seed/);
  assert.match(warning, /soft cheat/);
  assert.equal(await page.evaluate(() => document.activeElement.textContent), 'Keep Hidden');  // (the safe answer is the default)
  await page.keyboard.press('Enter');
  await keep.waitFor({state: 'detached'});
  assert.equal(await poiBox.isChecked(), false);
  assert.equal(poiAsks, 0);
  await poiBox.click();
  await page.getByRole('button', {name: 'Show Points of Interest', exact: true}).click();
  await pois.first().waitFor();
  assert.equal(await pois.count(), 1);
  assert.equal(await poiBox.isChecked(), true);
  await poiBox.click();  // off: gone at once
  assert.equal(await pois.count(), 0);
  await poiBox.click();  // on again: no second warning for this world
  await pois.first().waitFor();
  assert.equal(await keep.count(), 0);
  // Points of interest that can't be loaded: a small note with Try again; the map stays.
  await poiBox.click();
  await page.route('**/api/hub/map/poi*', route => route.fulfill({status: 500, contentType: 'application/json', body: '{"error": "test"}'}));
  await poiBox.click();
  await page.getByText("Couldn't load the points of interest.", {exact: true}).waitFor();
  assert.equal(await pois.count(), 0);
  assert.ok(await page.locator('.map-tile').count() > 0);
  await page.unroute('**/api/hub/map/poi*');
  await page.getByRole('button', {name: 'Try again', exact: true}).click();
  await pois.first().waitFor();
  await poiBox.click();
  await page.waitForTimeout(400);
  await page.getByLabel('Keep making the map as I move').check();
  await page.keyboard.press('Escape');
  await page.locator('.inpage-browser').waitFor({state:'detached'});
  await page.evaluate(() => openWorldPanel());
  await page.getByLabel('Keep making the map as I move').waitFor();
  assert.equal(await page.getByLabel('Keep making the map as I move').isChecked(), true);
  await page.keyboard.press('Escape');
  await page.locator('.inpage-browser').waitFor({state:'detached'});
  // Defer remote access until creation succeeds, then pair before Friends.
  await page.evaluate(() => { setupState.motd = 'Setup handoff'; setupState.friends = true; current.refresh(); openRemoteAccess(); });
  await page.getByLabel('New password', {exact:true}).fill('Correct-Horse-9');
  await page.getByLabel('Repeat it', {exact:true}).fill('Correct-Horse-9');
  await page.getByRole('button', {name:'Set password', exact:true}).click();
  await page.getByText('✓ Your password is strong enough for remote access.').waitFor();
  await page.getByLabel('Allow access to this control panel from other devices (phones, other computers)', {exact:true}).check();
  await page.getByText('Finish creating your server first.', {exact:false}).waitFor();
  assert.equal(await page.evaluate(async () => (await api('/api/hub/remote')).running_on_network), false);
  if (process.env.CRAFT_UI_REMOTE_SCREENSHOT)
    await page.screenshot({path: process.env.CRAFT_UI_REMOTE_SCREENSHOT});
  await page.locator('#remote').getByRole('button', {name:'Close', exact:true}).click();
  assert.equal(await page.evaluate(() => setupState.motd), 'Setup handoff');
  await page.getByLabel('I accept the', {exact:false}).check();
  // A double-click makes one server, and no "port already used" error beside it.
  const creates = [];
  const countCreate = r => { if (r.url().endsWith('/api/hub/create')) creates.push(r.method()); };
  page.on('request', countCreate);
  await page.getByRole('button', {name:'Create my server', exact:true}).dblclick();
  await page.getByRole('button', {name:'Continue to Friends', exact:true}).waitFor({timeout:60000});
  page.off('request', countCreate);
  assert.deepEqual(creates, ['POST']);
  assert.equal(await page.getByText('is already used by another server here', {exact:false}).count(), 0);
  assert.equal(await page.evaluate(async () => (await api('/api/hub/remote')).running_on_network), true);
  const createdServer = await page.evaluate(() => server);
  // Refresh at the phone step resumes it without creating a duplicate server.
  await page.reload();
  await page.getByRole('button', {name:'Continue to Friends', exact:true}).click();
  await page.waitForURL('**/#s/' + createdServer + '/friends');
  assert.equal(await page.evaluate(() => sessionStorage.getItem(SETUP_FOLLOWUP_KEY)), null);
  await go('s/alpha/updates');
  await page.getByRole('button', {name:'Check now', exact:true}).click();
  await page.getByRole('button', {name:'Apply update', exact:true}).waitFor();
  assert.equal(await page.getByRole('button', {name:'Apply update', exact:true}).isDisabled(), true);
  await page.evaluate(() => openReadiness(['1.21.2'], '1.21.1'));
  await page.locator('.ready-row.green').first().waitFor();
  await page.getByText('This server is set to stay on its current Minecraft version.', {exact:false}).waitFor();
  const color = await page.locator('.dotc.green').first().evaluate(el => getComputedStyle(el).backgroundColor);
  assert.equal(color, 'rgb(168, 245, 194)');  // (Modern's green, the look it has at first)
  await page.waitForTimeout(400);
  await page.evaluate(() => applyTheme('day'));
  assert.equal(await page.locator('.dotc.green').first().evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(9, 51, 23)');
  await page.evaluate(() => applyTheme('night'));
  await page.getByRole('button', {name:'Check Minecraft 1.21.2', exact:true}).click();
  await page.locator('.inpage-browser').waitFor({state:'detached'});
  await page.waitForFunction(() => [...document.querySelectorAll('#main button')].some(b => b.textContent === 'Apply update' && !b.disabled));
  await page.getByText('Ready: Minecraft 1.21.1 → 1.21.2', {exact:true}).waitFor();
  await page.setViewportSize({width:390,height:844});
  // On a phone too: the Mods page, the New server form, the SSH install dialog and Craft Conductor settings.
  await go('s/alpha/mods');
  assert.deepEqual(await misplacedCheckboxes(), []);
  await go('new');
  await page.getByRole('tab', { name: 'Custom setup' }).click();
  await page.locator('button.choice', {hasText: 'Lightweight and quick to update'}).first().click();
  await page.waitForFunction(() => document.querySelectorAll('#main input[type=checkbox]').length > 5);
  assert.deepEqual(await misplacedCheckboxes(), []);
  await page.evaluate(() => openSshInstall());
  assert.deepEqual(await misplacedCheckboxes(), []);
  await page.keyboard.press('Escape');
  await go('craft-conductor');
  for (const section of await page.locator('.preferences-button').all()) {
    await section.click();
    assert.deepEqual(await misplacedCheckboxes(), []);
  }
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.evaluate(() => openHelp());
  await page.waitForTimeout(350);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  assert.deepEqual(errors, []);
  await browser.close();
})().catch(e => {console.error(e); process.exit(1);});
