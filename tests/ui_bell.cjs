// The bell (see test_ui_bell.py): a message lands in it, the dot shows and clears, the list works with the
// keyboard and on a phone, hostile text stays text, and one person's messages never reach another.
const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');
(async () => {
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  const base = process.argv[2], morganId = process.argv[3];
  const H = { 'X-CRAFT-CONDUCTOR': '1' };
  const errors = [];
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
  await context.addInitScript(() => { localStorage.setItem('craft-conductor-sounds', 'off'); });
  const page = await context.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  const stored = () => page.evaluate(() => localStorage.getItem('craft-conductor-bell'));
  const items = () => page.locator('#bell-items .bell-item');
  const focused = () => page.evaluate(() => document.activeElement && (document.activeElement.id || document.activeElement.textContent.trim()));
  const signIn = async (data) => {
    assert.equal((await page.request.post(base + '/api/login', { data, headers: H })).status(), 200);
    await page.goto(base + '/#s/alpha/dashboard');
    await page.locator('#app').waitFor({ state: 'visible' });
    await page.waitForFunction(() => bell.who);
  };

  // The owner, on a server's Dashboard: nothing unread yet.
  assert.equal((await page.request.post(base + '/api/login', { data: { password: 'PASSWORD' }, headers: H })).status(), 200);
  assert.equal((await page.request.post(base + '/api/auth/change', { data: { mode: 'password', secret: 'Owner-Strong-Pass-1' }, headers: H })).status(), 200);
  await signIn({ password: 'Owner-Strong-Pass-1' });
  const bellBtn = page.locator('#bell');
  await bellBtn.waitFor();
  assert.ok(await page.locator('#bell-dot').isHidden(), 'no dot before any message');

  // A real message (Check now), then one with text a mod or player could have written.
  await page.getByRole('button', { name: 'Check now' }).click();
  await page.locator('#toasts .toast', { hasText: 'Checking for updates' }).waitFor();
  await page.locator('#toasts .toast', { hasText: 'update check: up to date' }).waitFor();  // (when the check is done)
  await page.evaluate(() => toast('<img src=x id=evil onerror="window.pwned=1"> broke the server', true));
  await page.locator('#bell-dot').waitFor({ state: 'visible' });
  assert.match(await bellBtn.getAttribute('aria-label'), /Messages \(3 unread\)/);
  // The on-screen messages keep their timing: 5 seconds, errors 12.
  await page.locator('#toasts .toast:not(.bad)').last().waitFor({ state: 'detached', timeout: 6500 });
  assert.equal(await page.locator('#toasts .toast.bad').count(), 1, 'an error stays longer');

  // With the keyboard: Enter opens the list, focus goes into it, newest first, read once opened.
  await bellBtn.focus();
  await page.keyboard.press('Enter');
  await page.locator('#bell-list').waitFor({ state: 'visible' });
  assert.equal(await bellBtn.getAttribute('aria-expanded'), 'true');
  assert.equal(await focused(), 'bell-list');
  assert.equal(await items().count(), 3);
  const first = await items().nth(0).innerText();
  assert.match(first, /<img src=x id=evil onerror="window.pwned=1"> broke the server/, 'shown as text');
  assert.match(first, /New/);
  assert.match(first, /Alpha/, 'the server it was about');
  assert.match(await items().nth(1).innerText(), /update check: up to date[\s\S]*Alpha/);
  assert.match(await items().nth(2).innerText(), /Checking for updates…[\s\S]*Alpha/);
  assert.equal(await items().nth(0).locator('time').count(), 1, 'with its time');
  assert.equal(await page.locator('#evil').count(), 0, 'never HTML');
  assert.equal(await page.evaluate(() => window.pwned), undefined);
  assert.ok(await page.locator('#bell-dot').isHidden(), 'opening marks them read');
  // Tab goes through Clear, Close and the list; Escape closes it and the focus goes back to the bell.
  await page.keyboard.press('Tab');
  assert.equal(await focused(), 'bell-clear');
  await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement.getAttribute('aria-label')), 'Close');
  await page.keyboard.press('Tab');
  assert.equal(await focused(), 'bell-items');
  await page.keyboard.press('Escape');
  await page.locator('#bell-list').waitFor({ state: 'hidden' });
  assert.equal(await focused(), 'bell');
  assert.equal(await bellBtn.getAttribute('aria-expanded'), 'false');
  // Space opens it too; the Close button closes it.
  await page.keyboard.press('Space');
  await page.locator('#bell-list').waitFor({ state: 'visible' });
  assert.equal(await items().nth(0).locator('.tag', { hasText: 'New' }).count(), 0, 'read now');
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  await page.keyboard.press('Enter');
  await page.locator('#bell-list').waitFor({ state: 'hidden' });
  assert.equal(await focused(), 'bell');

  // Kept in this browser: after a reload they're still there, still read.
  await page.reload();
  await page.locator('#app').waitFor({ state: 'visible' });
  await page.waitForFunction(() => bell.who === 'owner');
  assert.ok(await page.locator('#bell-dot').isHidden());
  await bellBtn.click();
  assert.equal(await items().count(), 3);
  await page.mouse.click(5, 890);  // (a click elsewhere closes it)
  await page.locator('#bell-list').waitFor({ state: 'hidden' });

  // A browser notification shown, and a phone notification this device got (one for another person's device isn't kept).
  await page.evaluate(() => bellNote('Alpha stopped unexpectedly', { more: 'Craft Conductor restarts it if it can.', sid: 'alpha', from: 'browser' }));
  await page.evaluate(() => new Promise((resolve, reject) => {
    const open = indexedDB.open('craft-conductor-bell', 1);
    open.onupgradeneeded = () => open.result.createObjectStore('pushes', { autoIncrement: true });
    open.onsuccess = () => {
      const tx = open.result.transaction('pushes', 'readwrite');
      tx.objectStore('pushes').add({ time: Date.now() / 1000, title: 'Alpha', body: 'Someone else\'s phone', sid: 'alpha', who: 'user:other' });
      tx.oncomplete = () => { open.result.close(); resolve(); };
      tx.onerror = () => reject(tx.error);
    };
  }));
  await page.waitForFunction(() => navigator.serviceWorker.controller);
  // (a real push, through sw.js: as a paired phone gets it)
  const cdp = await context.newCDPSession(page);
  const registered = new Promise((resolve) => cdp.on('ServiceWorker.workerRegistrationUpdated', (e) => {
    const r = e.registrations.find((x) => !x.isDeleted);
    if (r) resolve(r);
  }));
  await cdp.send('ServiceWorker.enable');
  const reg = await registered;
  await cdp.send('ServiceWorker.deliverPushMessage', { origin: new URL(base).origin, registrationId: reg.registrationId,
    data: JSON.stringify({ title: 'Alpha', body: 'A friend asks to join', url: '/#s/alpha/players', tag: 'alpha', sid: 'alpha', who: 'owner' }) });
  await page.locator('#bell-dot').waitFor({ state: 'visible' });
  await bellBtn.click();
  assert.equal(await items().count(), 5);
  const texts = await items().allInnerTexts();
  assert.ok(texts.some((x) => /A friend asks to join[\s\S]*Alpha · Phone notification/.test(x)), texts.join('\n'));
  assert.ok(texts.some((x) => /Alpha stopped unexpectedly[\s\S]*Craft Conductor restarts it[\s\S]*Browser notification/.test(x)), texts.join('\n'));
  assert.ok(!texts.some((x) => /Someone else/.test(x)), 'another person\'s push stays out');

  // Clear empties it (and this browser's copy).
  await page.getByRole('button', { name: 'Clear' }).click();
  await page.locator('.bell-empty').waitFor();
  assert.equal(JSON.parse(await stored()).items.length, 0);
  await page.keyboard.press('Escape');

  // On a phone: the bell and its list fit, with no sideways scrolling.
  await page.evaluate(() => toast('A long message from a mod: ' + 'x'.repeat(300)));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(300);
  await bellBtn.click();
  await page.locator('#bell-list').waitFor({ state: 'visible' });
  const box = await page.locator('#bell-list').boundingBox();
  assert.ok(box.x >= 0 && box.x + box.width <= 390, JSON.stringify(box));
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= 390), 'no sideways scrolling');
  const btnBox = await bellBtn.boundingBox();
  assert.ok(btnBox.x + btnBox.width <= 390 && btnBox.y >= 0, JSON.stringify(btnBox));
  await page.keyboard.press('Escape');
  await page.setViewportSize({ width: 1280, height: 900 });

  // One person at a time: Morgan signs in on the same browser and doesn't see the owner's messages.
  await page.evaluate(() => toast('The owner\'s secret plans'));
  assert.match(await stored(), /secret plans/);
  await signIn({ username: 'morgan', password: 'Morgan-Strong-Pass-3' });
  await page.waitForFunction((id) => bell.who === 'user:' + id, morganId);
  assert.ok(!/secret plans/.test(await stored() || ''), 'the owner\'s messages are gone from this browser');
  assert.ok(await page.locator('#bell-dot').isHidden());
  await page.evaluate(() => toast('Saved on Alpha'));
  await page.locator('#bell-dot').waitFor({ state: 'visible' });
  // The owner narrows what Morgan may do on Alpha: what Morgan was told about it goes.
  const owner = await browser.newContext();
  assert.equal((await owner.request.post(base + '/api/login', { data: { password: 'Owner-Strong-Pass-1' }, headers: H })).status(), 200);
  assert.equal((await owner.request.post(base + '/api/hub/users/update', { data: { id: morganId, grants: { alpha: ['status.view'] } }, headers: H })).status(), 200);
  await page.waitForFunction(() => !bell.items.length, null, { timeout: 10000 });
  assert.ok(await page.locator('#bell-dot').isHidden());

  // Sign out: this browser forgets them.
  await page.evaluate(() => toast('Saved again'));
  assert.match(await stored(), /Saved again/);
  await page.locator('#logout').click();
  await page.locator('#login').waitFor({ state: 'visible' });
  assert.equal(await stored(), null);

  assert.deepEqual(errors, []);
  await browser.close();
  console.log('ok');
})().catch((e) => { console.error(e); process.exit(1); });
