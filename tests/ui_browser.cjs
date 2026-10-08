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
  for (const view of ['servers', 's/alpha/dashboard', 's/alpha/console', 's/alpha/players', 's/alpha/updates', 's/alpha/mods', 's/alpha/friends', 's/alpha/backups', 's/alpha/java', 'new']) {
    await go(view);
    assert.deepEqual(await misplacedCheckboxes(), [], view);
  }
  await go('s/alpha/dashboard');
  await page.evaluate(() => openDoctor());
  await page.waitForFunction(() => document.querySelectorAll('.doctor-list li').length > 1);
  await page.locator('#doctor').getByRole('button', {name:'Close',exact:true}).click();
  await go('s/alpha/players');
  await page.getByRole('heading', {name:'Player activity',exact:true}).scrollIntoViewIfNeeded();
  await go('s/alpha/settings');
  await page.getByRole('heading', {name:'Web map',exact:true}).scrollIntoViewIfNeeded();
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
  // A required library with no build for the chosen Minecraft: the row explains, and only you change the version.
  await go('new');
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
  assert.match(await conflict.innerText(), /will not change your Minecraft version automatically/);
  assert.equal(await page.evaluate(() => setupState.minecraft), '1.21.2');
  await conflict.getByRole('button', {name: 'Remove Needs Gone', exact: true}).waitFor();
  // Choose another Minecraft version: back to the page, at the version picker.
  await conflict.getByRole('button', {name: 'Choose another Minecraft version', exact: true}).click();
  await drawer.waitFor({state: 'detached'});
  assert.equal(await page.evaluate(() => document.activeElement.id), 'setup-version');
  assert.equal(await page.evaluate(() => setupState.minecraft), '1.21.2');
  await manage.click();
  await conflict.getByRole('button', {name: 'Use Minecraft 1.21.1', exact: true}).click();
  await page.getByRole('button', {name: 'Change version', exact: true}).click();
  await page.waitForFunction(() => setupState.minecraft === '1.21.1' && !setupState.mods.get('needs-gone').bad);
  assert.equal(await page.locator('#setup-version').inputValue(), '1.21.1');
  await page.keyboard.press('Escape');
  await drawer.waitFor({state: 'detached'});
  await page.evaluate(() => setupRemoveMod('needs-gone'));
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
  await page.getByRole('button', {name:'Create my server', exact:true}).click();
  await page.getByRole('button', {name:'Continue to Friends', exact:true}).waitFor({timeout:60000});
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
  assert.equal(color, 'rgb(34, 197, 94)');
  await page.waitForTimeout(400);
  await page.evaluate(() => applyTheme('day'));
  assert.equal(await page.locator('.dotc.green').first().evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(22, 101, 52)');
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
  await page.locator('button.choice', {hasText: 'Fabric'}).first().click();
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
