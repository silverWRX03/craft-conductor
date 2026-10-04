// The mod browser's continuous results (see test_mod_scrolling.py for the made-up Modrinth).
const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');
(async () => {
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({headless: true, ...(channel ? {channel} : {})});
  const page = await browser.newPage({viewport: {width: 1280, height: 900}, reducedMotion: 'reduce'});
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const base = process.argv[2];
  if (process.argv[3] === 'friend') { await friend(page, base); assert.deepEqual(errors, []); await browser.close(); return; }
  assert.equal((await page.request.post(base + '/api/login', {data: {password: 'PASSWORD'}, headers: {'X-CRAFT-CONDUCTOR': '1'}})).status(), 200);
  assert.equal((await page.request.post(base + '/api/auth/change', {data: {mode: 'pin', secret: '2468'}, headers: {'X-CRAFT-CONDUCTOR': '1'}})).status(), 200);

  // Every search the page sends, answered a little late (a slow network); `hold` keeps answers back.
  const asked = [];
  let inFlight = 0, most = 0, hold = null;
  await page.route('**/api/hub/browse/search?*', async route => {
    const url = new URL(route.request().url());
    const req = {offset: Number(url.searchParams.get('offset')), sort: url.searchParams.get('sort')};
    asked.push(req);
    inFlight++; most = Math.max(most, inFlight);
    const reply = await route.fetch();
    const body = await reply.text();
    await new Promise(r => setTimeout(r, 250));
    if (hold && req.sort === 'relevance') await hold.promise;
    inFlight--;
    await route.fulfill({response: reply, body});
  });
  const rows = () => page.locator('.browse-results .result');
  const names = () => page.$$eval('.browse-results .result .name', els => els.map(e => e.firstChild.textContent));
  const scrollTo = async n => {  // the list scrolled so that row n (1 = the first) is at its bottom
    await page.evaluate(n => {
      const list = document.querySelector('.browse-results');
      const row = list.querySelectorAll('.result')[n - 1];
      list.scrollTop += row.getBoundingClientRect().bottom - list.getBoundingClientRect().bottom;
    }, n);
    await page.waitForTimeout(120);
  };

  await page.goto(base + '/#servers');
  await page.locator('#app').waitFor({state: 'visible'});
  await page.evaluate(() => openBrowser({type: 'mod', target: 'setup', loader: 'fabric', version: '1.21.1'}));
  await rows().nth(19).waitFor();
  assert.equal(await rows().count(), 20, 'the first batch is 20');
  // (like Safari, which doesn't hold what's on screen in place when something above it grows)
  await page.locator('.browse-results').evaluate(el => { el.style.overflowAnchor = 'none'; });
  assert.deepEqual(asked.map(a => a.offset), [0]);

  // Tick one, open another, and keep the keyboard on a third: none of it may move.
  await rows().nth(2).locator('input[type=checkbox]').check();
  await rows().nth(1).click();
  await page.getByRole('heading', {name: 'Mod 1', exact: true}).waitFor();
  await page.evaluate(() => { window.ticked = document.querySelectorAll('.browse-results .result')[2]; });

  // The next batch is asked for at about the 12th result, not at the bottom.
  let at = null;
  for (let n = 6; n <= 20 && at === null; n++) {
    await scrollTo(n);
    if (asked.length > 1) at = n;
  }
  assert.ok(at !== null && at >= 10 && at <= 13, `the second request started at row ${at}`);
  assert.equal(asked[1].offset, 20);
  const place = () => page.evaluate(() => document.querySelectorAll('.browse-results .result')[9].getBoundingClientRect().top);
  const shown = await place();
  // The second batch has nothing for this Minecraft: the third is asked for by itself.
  await page.waitForFunction(() => document.querySelectorAll('.browse-results .result').length > 20);
  assert.deepEqual(asked.map(a => a.offset), [0, 20, 40]);
  assert.equal(await rows().count(), 39);
  assert.ok(Math.abs(await place() - shown) < 1, 'the rows being read stayed where they were');
  assert.equal(await page.evaluate(() => window.ticked.isConnected && window.ticked.querySelector('input').checked), true);
  assert.equal(await rows().nth(1).evaluate(el => el.classList.contains('active')), true);
  await page.getByRole('heading', {name: 'Mod 1', exact: true}).waitFor();
  await page.getByText('21 result(s) hidden', {exact: false}).waitFor();  // (counted across batches)

  // The keyboard: focus moves down the rows; the last batch comes and focus stays where it was.
  await rows().nth(30).focus();
  await page.waitForFunction(() => document.querySelector('.pager-foot').textContent.includes('Loading more'));
  await page.waitForFunction(() => document.querySelectorAll('.browse-results .result').length > 39);
  assert.equal(await page.evaluate(() => document.activeElement === document.querySelectorAll('.browse-results .result')[30]), true);
  // At the end: everything once, a quiet last line, and no more requests however far it scrolls.
  await page.locator('.browse-results').evaluate(el => { el.scrollTop = el.scrollHeight; });
  await page.getByText("That's everything", {exact: true}).waitFor();
  const all = await names();
  assert.equal(all.length, 54);
  assert.equal(new Set(all).size, all.length, 'no result twice');
  assert.equal(all.filter(n => n === 'Mod 59').length, 1);
  assert.deepEqual(asked.map(a => a.offset), [0, 20, 40, 60]);
  assert.equal(most, 1, 'one request at a time');
  for (let i = 0; i < 3; i++) {
    await page.locator('.browse-results').evaluate(el => { el.scrollTop = 0; });
    await page.waitForTimeout(100);
    await page.locator('.browse-results').evaluate(el => { el.scrollTop = el.scrollHeight; });
    await page.waitForTimeout(300);
  }
  assert.equal(asked.length, 4, 'nothing asked for after the last page');
  assert.match(await page.locator('.browse-results [aria-live]').textContent(), /That's everything/);

  // A new sort while a batch is on its way: the old answer never lands in the new list.
  await page.getByLabel('Search', {exact: true}).fill('mod');
  await page.waitForFunction(() => document.querySelectorAll('.browse-results .result').length === 20);
  let release;
  hold = {promise: new Promise(r => { release = r; })};
  const before = asked.length;
  await scrollTo(14);
  await page.waitForFunction(n => document.querySelector('.pager-foot') && document.querySelector('.pager-foot').classList.contains('busy'), before);
  assert.equal(asked.length, before + 1);
  await page.getByLabel('Sort by', {exact: true}).selectOption('downloads');
  await page.waitForFunction(() => document.querySelectorAll('.browse-results .result').length === 20 &&
    document.querySelector('.browse-results .result .name').firstChild.textContent.startsWith('Top'));
  release();
  await page.waitForTimeout(700);
  const after = await names();
  assert.equal(after.length, 20);
  assert.ok(after.every(n => n.startsWith('Top ')), 'only the new search: ' + after.join(', '));

  // Without IntersectionObserver the "Load more" button does it (and it's there for keyboards).
  await page.evaluate(() => { closeBrowser(true); delete window.IntersectionObserver; });
  await page.evaluate(() => openBrowser({type: 'mod', target: 'setup', loader: 'fabric', version: '1.21.1'}));
  await rows().nth(19).waitFor();
  const n = asked.length;
  await page.locator('.browse-results').evaluate(el => { el.scrollTop = el.scrollHeight; });
  await page.waitForTimeout(500);
  assert.equal(asked.length, n, 'no observer, no automatic request');
  await page.locator('.pager-foot').getByRole('button', {name: 'Load more', exact: true}).focus();
  await page.keyboard.press('Enter');
  await page.waitForFunction(() => document.querySelectorAll('.browse-results .result').length > 20);
  assert.equal(await page.evaluate(() => document.activeElement.classList.contains('result')), true, 'focus moved on to the new rows');
  assert.deepEqual(errors, []);
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });

// The friend's page: Resource packs, 45 of them (test_a_friends_list_keeps_coming_too).
async function friend(page, base) {
  const asked = [];
  let hold = null;
  await page.route('**/api/extras/search?*', async route => {
    const url = new URL(route.request().url());
    const req = {offset: Number(url.searchParams.get('offset')), sort: url.searchParams.get('sort') || ''};
    asked.push(req);
    const reply = await route.fetch();
    const body = await reply.text();
    await new Promise(r => setTimeout(r, 200));
    if (hold && !req.sort) await hold.promise;
    await route.fulfill({response: reply, body});
  });
  const rows = () => page.locator('.browse-results .result');
  const names = () => page.$$eval('.browse-results .result .name', els => els.map(e => e.firstChild.textContent));
  await page.goto(base);
  await page.getByRole('button', {name: '🎨 Resource packs', exact: true}).click();
  await rows().nth(19).waitFor();
  assert.equal(await rows().count(), 20);
  await rows().nth(4).locator('input[type=checkbox]').check();
  let at = null;
  for (let n = 6; n <= 20 && at === null; n++) {
    await rows().nth(n - 1).evaluate(row => {
      const list = row.closest('.browse-results');
      list.scrollTop += row.getBoundingClientRect().bottom - list.getBoundingClientRect().bottom;
    });
    await page.waitForTimeout(120);
    if (asked.length > 1) at = n;
  }
  assert.ok(at !== null && at >= 10 && at <= 13, `the second request started at row ${at}`);
  await page.waitForFunction(() => document.querySelectorAll('.browse-results .result').length === 40);
  assert.equal(await rows().nth(4).locator('input[type=checkbox]').isChecked(), true);
  await page.locator('.browse-results').evaluate(el => { el.scrollTop = el.scrollHeight; });
  await page.getByText("That's everything", {exact: true}).waitFor();
  for (let i = 0; i < 2; i++) {
    await page.locator('.browse-results').evaluate(el => { el.scrollTop = 0; });
    await page.waitForTimeout(100);
    await page.locator('.browse-results').evaluate(el => { el.scrollTop = el.scrollHeight; });
    await page.waitForTimeout(300);
  }
  const all = await names();
  assert.equal(all.length, 45);
  assert.equal(new Set(all).size, 45);
  assert.deepEqual(asked.map(a => a.offset), [0, 20, 40], 'nothing asked for after the last page');
  // A new sort while a batch is on its way: the old answer is dropped.
  await page.locator('.browse-results').evaluate(el => { el.scrollTop = 0; });
  await page.getByLabel('Search resource packs', {exact: true}).fill('pack');
  await page.waitForFunction(() => document.querySelectorAll('.browse-results .result').length === 20);
  let release;
  hold = {promise: new Promise(r => { release = r; })};
  const before = asked.length;
  await rows().nth(13).scrollIntoViewIfNeeded();
  await page.waitForFunction(() => document.querySelector('.pager-foot.busy'));
  assert.equal(asked.length, before + 1);
  await page.getByLabel('Sort by', {exact: true}).selectOption('downloads');
  await page.waitForFunction(() => document.querySelectorAll('.browse-results .result').length === 20 &&
    document.querySelector('.browse-results .result .name').firstChild.textContent.startsWith('Top'));
  release();
  await page.waitForTimeout(600);
  const after = await names();
  assert.ok(after.length === 20 && after.every(n => n.startsWith('Top ')), after.join(', '));
}
