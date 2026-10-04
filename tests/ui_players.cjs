// The Dashboard's Connected Players card in a real browser. Talks to test_ui_players.py over
// stdin/stdout: it prints "STEP <name>" and waits for a line back while Python makes players join or leave.
const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');
const readline = require('node:readline');
const lines = readline.createInterface({ input: process.stdin })[Symbol.asyncIterator]();
const step = async (name) => { console.log('STEP ' + name); await lines.next(); };
(async () => {
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  const base = process.argv[2];
  const H = { 'X-CRAFT-CONDUCTOR': '1' };
  const errors = [];
  let pin = false;
  const open = async (viewport) => {
    const ctx = await browser.newContext({ viewport, reducedMotion: 'no-preference' });
    const page = await ctx.newPage();
    page.on('pageerror', (e) => errors.push(e.message));
    await ctx.addInitScript(() => { localStorage.setItem('craft-conductor-theme', 'night'); localStorage.setItem('craft-conductor-sounds', 'off'); });
    assert.equal((await ctx.request.post(base + '/api/login', { data: { password: pin ? '2468' : 'PASSWORD' }, headers: H })).status(), 200);
    if (!pin) assert.equal((await ctx.request.post(base + '/api/auth/change', { data: { mode: 'pin', secret: '2468' }, headers: H })).status(), 200);  // (the default password asks to be changed)
    pin = true;
    return page;
  };
  const page = await open({ width: 1440, height: 1000 });
  await page.goto(base + '/#s/alpha/dashboard');
  const card = page.locator('.players-card');
  await card.waitFor();
  const rows = card.locator('.prow');
  await rows.nth(24).waitFor();

  // 25 players: the header, the compact rows, and a list that scrolls inside the card
  assert.match(await card.locator('h3').textContent(), /Connected Players\s+25 \/ 30/);
  assert.equal(await rows.count(), 25);
  const box = await card.boundingBox();
  assert.ok(box.height < 520, 'the card stays compact with 25 players: ' + box.height);
  const sc = card.locator('.player-scroll');
  assert.ok(await sc.evaluate((el) => el.scrollHeight > el.clientHeight + 50), 'the list scrolls inside the card');
  assert.ok(await rows.first().evaluate((el) => el.getBoundingClientRect().height) <= 40, 'a row is compact');

  // each row: dot, head, name, role, ping, Kick; roles only from ops.json; ping a dash that says why
  await page.waitForFunction(() => document.querySelectorAll('.players-card .badge:not(.hidden)').length === 2);   // (the roles come with the first poll)
  const steve = rows.filter({ has: page.locator('.pname', { hasText: /^Steve$/ }) });
  assert.equal(await steve.locator('.badge').innerText(), 'OP');
  const alex = rows.filter({ has: page.locator('.pname', { hasText: /^Alex$/ }) });
  assert.equal(await alex.locator('.badge').innerText(), 'OP 2');
  assert.match(await alex.locator('.badge').getAttribute('title'), /level 2/);
  assert.equal(await rows.filter({ has: page.locator('.badge:not(.hidden)') }).count(), 2);
  assert.equal(await steve.locator('canvas.head').count(), 1);
  assert.equal(await steve.locator('.pdot').count(), 1);
  assert.match(await steve.locator('.sr-only').first().innerText(), /Online/);
  assert.equal((await steve.locator('.ping').innerText()).startsWith('—'), true);
  assert.match(await steve.locator('.ping').getAttribute('title'), /doesn't share each player's ping/);
  await card.locator('summary', { hasText: 'Why no ping?' }).click();
  assert.match(await card.locator('details').innerText(), /doesn't share each player's ping/);
  assert.equal(await steve.getByRole('button', { name: 'Kick Steve' }).count(), 1);

  // pressing a row opens the other actions; Kick asks first
  const open7 = rows.nth(7);
  const name7 = await open7.locator('.pname').innerText();
  await open7.locator('button.prow-open').click();
  const acts = open7.locator('.player-actions');
  assert.equal(await acts.isVisible(), true);
  assert.equal(await open7.locator('button.prow-open').getAttribute('aria-expanded'), 'true');
  for (const n of ['Message', 'Make op', 'Ban', 'More…']) assert.equal(await acts.getByText(n, { exact: true }).count(), 1, n);
  assert.equal(await acts.getByText('Kick', { exact: true }).count(), 0, 'Kick is in the row, not the opened actions');
  await open7.getByRole('button', { name: 'Kick ' + name7 }).click();
  await page.locator('.toast-dialog').waitFor();
  assert.match(await page.locator('.toast-dialog').innerText(), new RegExp('Kick ' + name7 + '\\?'));
  await page.locator('.toast-dialog').getByRole('button', { name: 'Cancel' }).click();
  await page.locator('.toast-dialog').waitFor({ state: 'detached' });

  // live updates leave everything where it is: the same rows and heads, the open actions, the scroll
  await sc.evaluate((el) => { el.scrollTop = 120; });
  await open7.locator('button.prow-open').focus();
  await page.evaluate(() => {
    const c = document.querySelector('.players-card');
    window.mark = [...c.querySelectorAll('.prow')].map((r) => [r, r.querySelector('canvas.head')]);
    window.live = document.querySelector('.players-card [role=status]');
  });
  await step('a-player-joins');
  await page.waitForFunction(() => document.querySelectorAll('.players-card .prow').length === 26, null, { timeout: 15000 });
  const same = await page.evaluate(() => {
    const rowsNow = [...document.querySelectorAll('.players-card .prow')];
    return window.mark.every(([r, head]) => rowsNow.includes(r) && r.querySelector('canvas.head') === head);
  });
  assert.equal(same, true, 'existing rows and heads are the same elements after a join');
  assert.equal(await acts.isVisible(), true, 'the open actions stay open');
  assert.equal(await sc.evaluate((el) => el.scrollTop), 120, 'the scroll position stays');
  assert.equal(await page.evaluate(() => document.activeElement === document.querySelectorAll('.players-card .prow')[7].querySelector('button.prow-open')), true, 'the focus stays');
  assert.match(await card.locator('h3').textContent(), /26 \/ 30/);
  const said = await card.locator('[role=status]').innerText();
  assert.match(said, /Zed joined\./);
  const stable = await page.evaluate(() => window.live.textContent);
  await page.waitForTimeout(6500);   // (a couple of polls later it is not announced again, nor changed)
  assert.equal(await page.evaluate(() => window.live.textContent), stable);

  await step('a-player-leaves');
  await page.waitForFunction(() => document.querySelectorAll('.players-card .prow').length === 25, null, { timeout: 15000 });
  assert.match(await card.locator('[role=status]').innerText(), /Zed left\./);
  assert.equal(await acts.isVisible(), true);
  // a player who has the actions open leaves: they close, nothing else moves
  await step('the-open-player-leaves');
  await page.waitForFunction(() => document.querySelectorAll('.players-card .prow').length === 24, null, { timeout: 15000 });
  assert.equal(await card.locator('.player-actions:not(.hidden)').count(), 0);
  // Escape closes the actions and the focus goes back to the row
  const r3 = rows.nth(3);
  await r3.locator('button.prow-open').click();
  await r3.getByRole('button', { name: 'Ban' }).focus();
  await page.keyboard.press('Escape');
  assert.equal(await r3.locator('.player-actions').isVisible(), false);
  assert.equal(await page.evaluate(() => document.activeElement.classList.contains('prow-open')), true);

  // Whitelist
  await card.getByRole('button', { name: 'Whitelist', exact: true }).click();
  const wl = card.locator('#pc-whitelist');
  await wl.waitFor();
  await wl.getByText('Sam', { exact: true }).waitFor();
  const sw = wl.getByRole('switch');
  assert.equal(await sw.getAttribute('aria-checked'), 'false');
  assert.match(await wl.innerText(), /Anyone can join/);
  await sw.click();
  await page.waitForFunction(() => document.querySelector('#pc-whitelist [role=switch]').getAttribute('aria-checked') === 'true', null, { timeout: 15000 });
  assert.match(await wl.innerText(), /Only listed players can join/);
  await wl.getByLabel('Name to whitelist').fill('bad name!');
  await wl.getByRole('button', { name: 'Add', exact: true }).click();
  assert.match(await wl.locator('[role=alert]').innerText(), /1 to 16 letters/);
  await wl.getByLabel('Name to whitelist').fill('Kit_9');
  await wl.getByRole('button', { name: 'Add', exact: true }).click();
  await wl.getByText('Kit_9', { exact: true }).waitFor({ timeout: 15000 });
  await wl.getByRole('button', { name: 'Remove Sam from the whitelist' }).click();
  await page.waitForFunction(() => !document.querySelector('#pc-whitelist').innerText.includes('Sam'), null, { timeout: 15000 });
  assert.equal(await wl.getByRole('link', { name: /Players page/ }).count(), 1);

  // Broadcast
  await card.getByRole('button', { name: 'Broadcast', exact: true }).click();
  assert.equal(await wl.isVisible(), false, 'one panel at a time');
  const bc = card.locator('#pc-broadcast');
  await bc.getByLabel('Message to everyone online').fill('Restart in five minutes');
  assert.match(await bc.innerText(), /23 \/ 256/);
  await bc.getByRole('button', { name: 'Send' }).click();
  await page.locator('.console').getByText('> say Restart in five minutes').waitFor({ timeout: 15000 });
  assert.equal(await bc.getByLabel('Message to everyone online').inputValue(), '');

  // a phone: the card fits; a helper's phone has no Message (it types a console command); a viewer sees the list without buttons
  const phone = await open({ width: 390, height: 800 });
  const as = async (role) => {
    await phone.unroute('**/api/hub').catch(() => null);
    await phone.route('**/api/hub', async (route) => {
      const r = await route.fetch();
      const j = await r.json();
      await route.fulfill({ response: r, json: { ...j, role, device: 'Test phone' } });
    });
    await phone.goto(base + '/#s/alpha/dashboard');
    await phone.reload();
    await phone.locator('.players-card .prow').first().waitFor();
  };
  await as('helper');
  assert.ok(await phone.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'no sideways scrolling on a phone');
  assert.ok((await phone.locator('.players-card').boundingBox()).height < 560);
  await phone.locator('.players-card .prow button.prow-open').first().click();
  assert.equal(await phone.locator('.players-card .player-actions:not(.hidden)').getByText('Message', { exact: true }).count(), 0);
  assert.equal(await phone.locator('.players-card .player-actions:not(.hidden)').getByText('Ban', { exact: true }).count(), 1);
  assert.equal(await phone.locator('.players-card').getByRole('button', { name: 'Broadcast', exact: true }).count(), 1);
  await as('viewer');
  assert.equal(await phone.locator('.players-card button').count(), 0, 'a viewer sees the list without buttons');
  assert.equal(await phone.locator('.players-card .prow-open').count() > 20, true);
  await phone.waitForFunction(() => document.querySelectorAll('.players-card .badge:not(.hidden)').length === 2);
  assert.deepEqual(errors, []);
  await browser.close();
  console.log('OK');
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
