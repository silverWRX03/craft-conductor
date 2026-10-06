// Craft Conductor's own update in a real browser: tests/test_ui_update.py starts the hub and runs this.
// usage: node ui_update.cjs <base url> <scenario>      (later | update | failure | restart-timeout)
const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');
(async () => {
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({headless: true, ...(channel ? {channel} : {})});
  const context = await browser.newContext({viewport: {width: 1280, height: 900}});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const [base, scenario] = [process.argv[2], process.argv[3]];
  const post = (path, data) => page.request.post(base + path, {data, headers: {'X-CRAFT-CONDUCTOR': '1'}});
  assert.equal((await post('/api/login', {password: 'PASSWORD'})).status(), 200);
  assert.equal((await post('/api/auth/change', {mode: 'pin', secret: '2468'})).status(), 200);
  await page.addInitScript(() => {
    localStorage.setItem('craft-conductor-sounds', 'off');
    window.__opens = [];
    window.open = (...args) => { window.__opens.push(args); return null; };
  });
  // Whatever happens, one tab: no popup window, no second page in the browser.
  let popups = 0;
  context.on('page', () => { popups++; });
  const popup = page.locator('#self-update'), screen = page.locator('#self-updating');
  const dots = page.locator('[data-update-dot]:not(.hidden)');
  const shot = async name => { if (process.env.CRAFT_UI_SHOTS) await page.screenshot({path: `${process.env.CRAFT_UI_SHOTS}/${scenario}-${name}.png`}); };
  const quiet = async ms => { await page.waitForTimeout(ms); };   // (the page polls every 2 s)
  const open = async hash => { await page.goto(base + '/#' + hash); await page.locator('#app').waitFor({state: 'visible'}); };
  const aboutAndUpdates = async () => {
    await open('craft-conductor');
    await page.getByRole('button', {name: 'About & updates'}).click();
  };

  // "the new copy": after the restart the page asks the same service, which answers as the new version
  // with nothing left to update (a real restart starts afresh; here the old copy answers for it).
  const newCopy = {up: false, aborts: 0, version: '9.9.9'};
  await page.route('**/api/self-update?*', async route => {
    if (!newCopy.on) return route.continue();
    if (newCopy.aborts > 0) { newCopy.aborts--; return route.abort('connectionrefused'); }
    return route.fulfill({json: {version: newCopy.version, matches: true, self_update: null}});
  });
  await page.route('**/api/hub', async route => {
    const response = await route.fetch();
    if (!newCopy.reloaded) return route.fulfill({response});
    const body = await response.json();
    return route.fulfill({response, json: {...body, version: newCopy.version, self_update: null}});
  });

  await open('servers');
  await popup.waitFor();
  assert.match(await popup.innerText(), /Craft Conductor 9\.9\.9 is available/);
  assert.match(await popup.innerText(), /You have /);
  assert.equal(await page.locator('#nav a[href="#craft-conductor"] .update-dot:not(.hidden)').count(), 1);
  await shot('prompt');

  if (scenario === 'later') {
    await popup.getByRole('button', {name: 'Later'}).click();
    await popup.waitFor({state: 'detached'});
    await quiet(5200);                                   // polls go by: the popup stays away
    assert.equal(await popup.count(), 0);
    await page.reload();                                 // a refresh doesn't ask again either
    await page.locator('#app').waitFor({state: 'visible'});
    await quiet(3000);
    assert.equal(await popup.count(), 0);
    assert.equal(await page.locator('#nav a[href="#craft-conductor"] .update-dot:not(.hidden)').count(), 1);  // the dot stays
    await aboutAndUpdates();
    assert.equal(await page.locator('#preferences-button-4 .update-dot:not(.hidden)').count(), 1);
    const check = page.getByRole('button', {name: 'Check for Craft Conductor updates'});
    assert.equal(await check.locator('.update-dot:not(.hidden)').count(), 1);
    assert.match(await page.locator('#about-update').innerText(), /9\.9\.9 is available/);
    await check.click();                                 // the person asks: the same update is offered again
    await popup.waitFor();
    assert.match(await popup.innerText(), /Craft Conductor 9\.9\.9 is available/);
    await popup.getByRole('button', {name: 'Later'}).click();
    await popup.waitFor({state: 'detached'});
    await shot('about');
    assert.ok(await dots.count() >= 3);
  } else if (scenario === 'update' || scenario === 'restart-timeout') {
    // The page's own button, as fast as a hand can be: the update starts once.
    await page.evaluate(() => {
      const u = hubInfo.self_update;
      window.__clicks = [startSelfUpdate(u), startSelfUpdate(u), startSelfUpdate(u)];
    });
    assert.equal(await popup.count(), 0);                // the prompt is gone at once...
    await screen.waitFor();                              // ...and the update screen is there
    assert.match(await screen.innerText(), /Updating Craft Conductor/i);
    assert.equal(await screen.count(), 1);
    await shot('updating');
    await page.waitForFunction(() => /Installing update|Restarting Craft Conductor/i.test(document.querySelector('#self-updating').innerText));
    assert.equal(await popup.count(), 0);                // not offered again while it installs
    await quiet(2500);
    assert.equal(await popup.count(), 0);
    await page.waitForFunction(() => /Restarting Craft Conductor/i.test(document.querySelector("#self-updating-title").innerText + document.querySelector("#self-updating-stage").innerText));
    if (scenario === 'update') {
      // the service goes away (refusing connections), then answers as the new version
      newCopy.on = true; newCopy.aborts = 3;
      newCopy.reloaded = false;
      const reloaded = page.waitForEvent('load');
      await page.waitForFunction(() => /waiting for the new version|Waiting for the new version/i.test(document.querySelector('#self-updating').innerText));
      newCopy.reloaded = true;
      await reloaded;                                     // the same tab reloads into the new version
      await page.locator('#app').waitFor({state: 'visible'});
      await page.getByText('Craft Conductor is updated to 9.9.9').waitFor();
      assert.equal(await screen.count(), 0);
      assert.equal(await popup.count(), 0);
      await quiet(2500);
      assert.equal(await popup.count(), 0);
      assert.equal(await dots.count(), 0);                // updated: the red dots are gone
    } else {
      // The new version never answers: a useful message, not a retry loop.
      await page.evaluate(() => { const real = Date.now.bind(Date); const t0 = real(); Date.now = () => t0 + (real() - t0) * 400; });
      newCopy.on = true; newCopy.aborts = 1e9;
      await page.getByText('Craft Conductor could not restart after the update.').waitFor({timeout: 15000});
      await shot('restart-failed');
      for (const name of ['Retry connection', 'View update log', 'Restart Craft Conductor manually', 'Close'])
        await screen.getByRole('button', {name, exact: true}).waitFor();
      assert.equal(await popup.count(), 0);
      await screen.getByRole('button', {name: 'View update log'}).click();
      assert.match(await page.locator('#update-log').innerText(), /Restarting Craft Conductor/i);
      await screen.getByRole('button', {name: 'Restart Craft Conductor manually'}).click();
      assert.equal(await page.locator('#update-manual').isVisible(), true);
      await quiet(3500);                                  // no endless retrying: it stays on the message
      assert.equal(await screen.getByText('Craft Conductor could not restart after the update.').count(), 1);
      // Retry connection tries again; once the new version answers, this tab reloads into it
      newCopy.aborts = 0; newCopy.on = true;
      const reloaded = page.waitForEvent('load');
      await screen.getByRole('button', {name: 'Retry connection'}).click();
      newCopy.reloaded = true;
      await reloaded;
      await page.getByText('Craft Conductor is updated to 9.9.9').waitFor();
    }
  } else if (scenario === 'failure') {
    await popup.getByRole('button', {name: 'Update now'}).click();
    assert.equal(await popup.count(), 0);                // the prompt is gone at once
    await screen.getByText("The update didn't finish.").waitFor();
    await shot('failed');
    assert.match(await screen.innerText(), /checksum/);
    assert.match(await screen.innerText(), /still running/);
    await quiet(5200);                                   // no endless prompts, no reload loop
    assert.equal(await popup.count(), 0);
    assert.equal(await screen.getByText("The update didn't finish.").count(), 1);
    await screen.getByRole('button', {name: 'View update log'}).click();
    assert.match(await page.locator('#update-log').innerText(), /failed/);
    await screen.getByRole('button', {name: 'Close', exact: true}).click();
    await screen.waitFor({state: 'detached'});
    await quiet(3000);
    assert.equal(await popup.count(), 0);                // Close doesn't bring the prompt back
    assert.equal(await page.locator('#nav a[href="#craft-conductor"] .update-dot:not(.hidden)').count(), 1);  // the dot stays
    await aboutAndUpdates();
    assert.match(await page.locator('#about-update').innerText(), /last update attempt failed/);
    // try again from About & updates: its own button
    await page.locator('#about-update').getByRole('button', {name: 'Update now'}).click();
    await screen.waitFor();
    await screen.getByText("The update didn't finish.").waitFor();   // (the stand-in fails every time)
    await screen.getByRole('button', {name: 'Try again'}).click();   // ...and the button tries again
    await screen.getByText("The update didn't finish.").waitFor();
  } else {
    throw new Error('unknown scenario ' + scenario);
  }
  assert.equal(popups, 0, 'no other tab opened');
  assert.equal(context.pages().length, 1);
  assert.deepEqual(await page.evaluate(() => window.__opens), []);
  assert.deepEqual(errors, []);
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
