// The pictures in the user manual, the Help page, the wiki and the README (run by test_screenshots.py,
// which makes the example servers). Each picture is a real page of the control panel.
const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const path = require('node:path');
const fs = require('node:fs');
const { pathToFileURL } = require('node:url');

const base = process.argv[2];
const out = process.env.CRAFT_UI_SCREENSHOTS;
const home = process.env.CRAFT_UI_HOME;
const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
const DESKTOP = {width: 1440, height: 1000}, PHONE = {width: 390, height: 844};
const HEADERS = {'X-CRAFT-CONDUCTOR': '1'};

(async () => {
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({headless: true, ...(channel ? {channel} : {})});
  const context = await browser.newContext({viewport: DESKTOP, reducedMotion: 'reduce', locale: 'en-US', timezoneId: 'UTC'});
  await context.addInitScript(() => {
    localStorage.setItem('craft-conductor-theme', 'night');
    localStorage.setItem('craft-conductor-sounds', 'off');
    localStorage.setItem('craft-conductor-skip-warnings', JSON.stringify(['closing-tip']));
  });
  let page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));

  // The example servers live in a test folder: show them where Craft Conductor keeps servers on Windows.
  const tidy = () => page.evaluate(([folder, shown]) => {
    const swap = s => s.split(folder).map((part, i) => i ? part.replace(/^[^\s,;)]*/, p => p.replace(/\//g, '\\')) : part).join(shown);
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n; (n = walker.nextNode());) if (n.nodeValue.includes(folder)) n.nodeValue = swap(n.nodeValue);
    for (const el of document.querySelectorAll('input, textarea')) if (el.value.includes(folder)) el.value = swap(el.value);
  }, [home, 'C:\\Users\\you\\craft-conductor']);
  const shot = async (name, {full = false} = {}) => {
    await page.waitForFunction(() => !document.querySelector('#toasts .toast:not(.sticky)'), null, {timeout: 15000});
    await tidy();
    await page.screenshot({path: path.join(out, name + '.png'), fullPage: full});
    console.log('took', name);
  };
  const go = async hash => {
    await page.goto(base + '/#' + hash);
    await page.locator('#app').waitFor({state: 'visible'});
    await page.waitForLoadState('networkidle').catch(() => null);
    await page.waitForTimeout(800);
  };
  const scrollTo = async text => {
    await page.getByRole('heading', {name: text, exact: true}).first().scrollIntoViewIfNeeded();
    await page.getByRole('heading', {name: text, exact: true}).first().evaluate(el => el.scrollIntoView({block: 'start'}));
    await page.waitForTimeout(400);
  };
  const close = async () => { await page.keyboard.press('Escape'); await page.waitForTimeout(400); };

  // Getting started: signing in the first time, and choosing a password.
  await page.goto(base + '/');
  await page.locator('#login-password').waitFor({state: 'visible'});
  await page.waitForTimeout(500);
  await shot('sign-in');
  await page.fill('#login-password', 'PASSWORD');
  await page.keyboard.press('Enter');
  await page.locator('#security').waitFor();
  const boxes = page.locator('#security input[type=password]');
  await boxes.nth(0).fill('Creeper-Proof-42');
  await boxes.nth(1).fill('Creeper-Proof-42');
  await page.waitForTimeout(300);
  await shot('choose-password');
  await page.locator('#security').getByRole('button', {name: 'Save', exact: true}).click();
  await page.locator('#security').waitFor({state: 'detached'});

  // Your servers, and New server.
  await go('servers');
  await shot('servers');
  await page.evaluate(() => startGuide());
  await page.locator('#guide').waitFor();
  await page.waitForTimeout(400);
  await shot('guided-setup');
  await page.evaluate(async () => { await api('/api/hub/guide', {method: 'POST', body: {action: 'stop'}}); $('#guide').remove(); });
  await go('new');
  await shot('new-server');
  await page.evaluate(() => openBrowser({target: 'setup', loader: 'fabric', version: '1.21.1'}));
  await page.locator('.result').first().waitFor();
  await page.locator('.result').first().click();
  await page.waitForTimeout(800);
  await shot('mod-browser');
  await close();
  await page.evaluate(() => openSshInstall());
  await page.locator('#ssh-install').waitFor();
  await page.locator('#ssh-install input').first().fill('192.168.1.60');
  await page.waitForTimeout(300);
  await shot('ssh-install');
  await close();
  if (process.env.CRAFT_UI_WORLD) {  // (the map needs a real world: see test_screenshots.py)
    const id = await page.evaluate(async () => (await api('/api/hub/preview', {method: 'POST', body: {loader: 'fabric',
      minecraft: '1.21.1', mods: ['terralith'], seed: '25698412121455', level_type: 'minecraft:normal', structures: true,
      radius: 128}})).id);
    let map;
    for (let i = 0; i < 240 && !(map && ['done', 'failed'].includes(map.state)); i++) {
      await page.waitForTimeout(250);
      map = await page.evaluate(id => api(`/api/hub/preview?id=${id}`), id);
    }
    if (!map || map.state !== 'done') throw new Error('the map preview failed: ' + JSON.stringify(map));
    await page.evaluate(async m => {
      setupState.loader = 'fabric'; setupState.minecraft = '1.21.1';
      await setupAddMod('terralith', 'Terralith');
      setupState.previews = [m];
      openWorldPanel();
    }, map);
    await page.waitForFunction(() => [...document.querySelectorAll('.map-tile')].some(img => img.complete && img.naturalWidth > 0));
    await page.waitForTimeout(500);
    await shot('map-preview');
    await close();
  }

  // The server pages, on the example server friends play on.
  await go('s/survival/dashboard');
  await page.locator('.cc-telemetry-grid').waitFor();
  await page.waitForTimeout(2500);  // (CPU use needs two readings)
  await shot('dashboard');
  await page.setViewportSize(PHONE);  // (on a phone)
  await page.waitForTimeout(1500);
  await shot('phone');
  await page.setViewportSize(DESKTOP);
  await page.waitForTimeout(800);
  await scrollTo('Performance');
  await shot('performance');
  await page.locator('#main').evaluate(el => el.scrollTop = 0);
  await page.locator('#btn-stop').click();
  await page.locator('.toast-dialog').waitFor();
  await page.waitForTimeout(400);
  await shot('question');
  await close();
  await page.evaluate(() => openDoctor());
  await page.waitForFunction(() => document.querySelectorAll('.doctor-list li').length > 1);
  await page.waitForTimeout(500);
  await shot('check-my-setup');
  await close();
  await go('s/survival/console');
  await page.locator('#main input').last().fill('list');
  await page.keyboard.press('Enter');
  await page.waitForTimeout(1500);
  await shot('console');
  await go('s/survival/players');
  await shot('players');
  await scrollTo('Player activity');
  await shot('player-activity');
  await go('s/survival/updates');
  await shot('updates');
  await page.evaluate(() => openReadiness(['1.21.4', '1.21.1'], '1.21.1'));
  await page.locator('.ready-row').first().waitFor();
  await page.waitForTimeout(500);
  await shot('update-readiness');
  await close();
  await go('s/survival/mods');
  await shot('mods');
  await go('s/survival/backups');
  await page.evaluate(() => document.querySelectorAll('#main details').forEach(d => { d.open = true; }));
  await page.waitForTimeout(300);
  await shot('backups');
  await go('s/survival/java');
  await shot('java');
  await go('s/survival/settings');
  await shot('settings');
  await page.waitForFunction(() => [...document.querySelectorAll('#main h3')].some(el => el.textContent === 'World tools'
    && !el.parentElement.textContent.includes('Loading')), null, {timeout: 30000});
  await scrollTo('Web map');
  await shot('web-map');
  await go('s/survival/friends');
  await shot('friends');

  // When something goes wrong: the modded server didn't start.
  await go('s/adventure/dashboard');
  await page.locator('.problem').waitFor();
  await shot('dashboard-problem');

  // Craft Conductor settings, remote access and Help.
  await go('craft-conductor');
  await page.getByRole('button', {name: 'Connections', exact: true}).click();
  await page.waitForTimeout(500);
  await shot('craft-conductor-settings');
  await page.getByRole('button', {name: 'Appearance', exact: true}).click();
  await page.waitForTimeout(400);
  await shot('display');
  await page.evaluate(() => openRemoteAccess());
  await page.locator('.remote-step').first().waitFor();
  await page.waitForTimeout(500);
  await shot('remote-access');
  await close();
  await go('s/survival/dashboard');
  await page.evaluate(() => openHelp());
  await page.locator('.help-overlay').waitFor();
  await page.waitForTimeout(500);
  await shot('help');
  await close();

  // A friend's side: the invite page (GitHub Pages), then their Craft Conductor setting up Minecraft.
  const site = pathToFileURL(process.env.CRAFT_UI_SITE).href + '#' + process.env.CRAFT_UI_INVITE;
  await page.goto(site);
  await page.waitForTimeout(800);
  await shot('invite-page');
  await page.goto(process.env.CRAFT_UI_FRIEND);
  await page.waitForLoadState('networkidle').catch(() => null);
  await page.waitForTimeout(1200);
  await shot('friend-setup');

  if (errors.length) throw new Error('page errors: ' + errors.join('; '));
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
