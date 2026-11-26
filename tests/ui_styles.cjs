// Classic and Modern in a real browser (see test_ui_styles.py): the default, the switch by keyboard, what a switch
// keeps, each person's own choice, day / night apart, Modern's rules kept to Modern, the font, the keyboard ring,
// touch sizes on a phone, and live updates that don't pile up listeners or press a button twice.
// CRAFT_UI_SHOTS=<folder> also saves a picture of each style and theme, for a person to look at.
const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');
const path = require('node:path');
(async () => {
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  const base = process.argv[2];
  const H = { 'X-CRAFT-CONDUCTOR': '1' };
  const shots = process.env.CRAFT_UI_SHOTS;
  const errors = [];
  const outside = [];
  const open = async (options = {}) => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, ...options });
    await context.addInitScript(() => {
      localStorage.setItem('craft-conductor-sounds', 'off');
      localStorage.setItem('craft-conductor-skip-warnings', JSON.stringify(['closing-tip']));
      // (how many listeners each element was given: a part rebuilt every few seconds mustn't collect them)
      const counts = new WeakMap();
      window.__listeners = (el, type) => (counts.get(el) || {})[type] || 0;
      const add = EventTarget.prototype.addEventListener;
      EventTarget.prototype.addEventListener = function (type, fn, opts) {
        const c = counts.get(this) || {};
        c[type] = (c[type] || 0) + 1;
        counts.set(this, c);
        return add.call(this, type, fn, opts);
      };
    });
    const page = await context.newPage();
    page.on('pageerror', (e) => errors.push(e.message));
    page.on('request', (r) => { if (!r.url().startsWith(base)) outside.push(r.url()); });
    return page;
  };
  const style = (page) => page.evaluate(() => document.documentElement.dataset.style);
  const theme = (page) => page.evaluate(() => document.documentElement.dataset.theme);

  // The owner, the first time in this browser: Modern.
  const page = await open();
  assert.equal((await page.request.post(base + '/api/login', { data: { password: 'PASSWORD' }, headers: H })).status(), 200);
  assert.equal((await page.request.post(base + '/api/auth/change', { data: { mode: 'pin', secret: '2468' }, headers: H })).status(), 200);
  const fonts = [];
  page.on('response', (r) => { if (r.url().includes('/fonts/')) fonts.push([r.url(), r.status(), r.headers()['content-type']]); });
  await page.goto(base + '/#servers');
  await page.locator('.server-card', { hasText: 'Alpha' }).waitFor();
  assert.equal(await style(page), 'modern', 'Modern is the default');
  // The top bar is the server, Start / Restart / Stop and the bell: the switches are in Craft Conductor settings → Appearance.
  assert.equal(await page.locator('.topbar [data-theme-toggle], .topbar input[data-style-choice], .sidebar [data-theme-toggle]').count(), 0,
    'no Light / Dark or Classic / Modern in the top bar or the menu');
  const appearance = async () => {
    await page.goto(base + '/#craft-conductor');
    await page.getByRole('button', { name: 'Appearance', exact: true }).click();
    await page.locator('.look-rows').waitFor();
  };
  const group = page.getByRole('group', { name: 'Interface style' });
  const classic = group.getByRole('radio', { name: 'Classic' }), modern = group.getByRole('radio', { name: 'Modern' });
  const themeSwitch = page.locator('main [data-theme-toggle]');
  // (choose a style in Appearance, then go to a page to look at it)
  const choose = async (radio, view) => {
    await appearance();
    await radio.check();
    if (view) { await page.goto(base + '/' + view); await page.locator('#nav a').first().waitFor(); }
  };
  await appearance();
  assert.ok(await modern.isChecked() && !(await classic.isChecked()), 'the switch says Modern');

  // The font comes from Craft Conductor itself, and is what the page's words are drawn in.
  await page.evaluate(() => document.fonts.ready);
  assert.ok(await page.evaluate(() => document.fonts.check('16px Roboto')), 'Roboto is loaded');
  assert.ok(fonts.some(([u, s, t]) => u.endsWith('/fonts/roboto-latin.woff2') && s === 200 && t === 'font/woff2'), JSON.stringify(fonts));
  assert.match(await page.evaluate(() => getComputedStyle(document.body).fontFamily), /^Roboto,/);
  assert.equal(await page.evaluate(() => getComputedStyle(document.body).fontSize), '16px');

  // Switching by keyboard: Tab to the switch, an arrow key to Classic. Nothing is drawn again: the page stays.
  await page.evaluate(() => { window.__card = document.querySelector('.look-rows'); });
  await modern.focus();
  await page.keyboard.press('ArrowLeft');
  assert.equal(await style(page), 'classic');
  assert.ok(await classic.isChecked());
  assert.ok(await page.evaluate(() => window.__card === document.querySelector('.look-rows')), 'the Look card is the same one');
  assert.equal(page.url().split('#')[1], 'craft-conductor', 'still on the same page');
  // the ring where the keyboard is: on the chosen choice's label
  const ring = await page.evaluate(() => { const l = document.activeElement.closest('label'); const s = getComputedStyle(l); return [s.outlineStyle, s.outlineWidth]; });
  assert.deepEqual(ring, ['solid', '3px']);
  await page.keyboard.press('ArrowRight');
  assert.equal(await style(page), 'modern');

  // Day / night is its own setting, beside it.
  await classic.check();
  const night = await theme(page);
  await themeSwitch.click();
  assert.notEqual(await theme(page), night);
  assert.equal(await themeSwitch.getAttribute('aria-checked'), String(night !== 'night'), 'the switch says which');
  assert.equal(await style(page), 'classic', 'day / night leaves the style');
  await modern.check();
  assert.notEqual(await theme(page), night, 'the style leaves day / night');
  await themeSwitch.click();
  assert.equal(await theme(page), night);

  // Classic stays Classic: square, capital letters, graph paper; Modern has 16px panels, 8px controls, ordinary words,
  // a plain background and 44-pixel buttons with a mouse too.
  const look = () => page.evaluate(() => {
    const b = document.querySelector('.actions .btn'), c = document.querySelector('main .card');
    return { caps: getComputedStyle(b).textTransform, button: getComputedStyle(b).borderTopLeftRadius, card: getComputedStyle(c).borderTopLeftRadius,
      paper: getComputedStyle(document.body).backgroundImage !== 'none', tall: b.getBoundingClientRect().height >= 44 };
  });
  await choose(classic, '#s/alpha/settings');
  await page.locator('main .card').first().waitFor();
  assert.deepEqual(await look(), { caps: 'uppercase', button: '0px', card: '0px', paper: true, tall: false });
  await choose(modern, '#s/alpha/settings');
  await page.locator('main .card').first().waitFor();
  assert.deepEqual(await look(), { caps: 'none', button: '8px', card: '16px', paper: false, tall: true });
  assert.ok(await page.evaluate(() => document.getElementById('skip-link').getBoundingClientRect().height >= 44), 'Skip to main content is 44 pixels too');
  // under a mouse a button changes its background and stays where it is
  const hovered = () => page.locator('main .btn:visible').first().evaluate((b) => [getComputedStyle(b).transform, getComputedStyle(b).backgroundColor]);
  const [, rest] = await hovered();
  await page.locator('main .btn:visible').first().hover();
  await page.waitForTimeout(250);
  const [moved, bg] = await hovered();
  assert.equal(moved, 'none');
  assert.notEqual(bg, rest, 'the background changes under a mouse');
  await page.mouse.move(1, 1);

  // Remembered: Classic after a reload, and on the sign-in page.
  await choose(classic, '#servers');
  await page.reload();
  await page.locator('#nav a').first().waitFor();
  assert.equal(await style(page), 'classic', 'kept after a reload');
  await page.locator('#logout').click();
  await page.locator('#login-form').waitFor();
  assert.equal(await style(page), 'classic', 'the sign-in page shows the style last used here');

  // Someone else signs in on this browser: their own (Modern, they never chose), not the owner's.
  assert.equal((await page.request.post(base + '/api/login', { data: { username: 'morgan', password: 'Morgan-Strong-Pass-3' }, headers: H })).status(), 200);
  await page.goto(base + '/#servers');
  await page.reload();  // (the same address: only a reload starts the page again)
  await page.locator('.server-card', { hasText: 'Alpha' }).waitFor();
  assert.equal(await style(page), 'modern', "another person doesn't get the owner's choice");
  await page.locator('#logout').click();
  await page.locator('#login-form').waitFor();
  // the owner again: Classic
  assert.equal((await page.request.post(base + '/api/login', { data: { password: '2468' }, headers: H })).status(), 200);
  await page.goto(base + '/#servers');
  await page.reload();
  await page.locator('.server-card', { hasText: 'Alpha' }).waitFor();
  assert.equal(await style(page), 'classic', "the owner's own choice is back");
  // a value nobody could have chosen counts as no choice (Modern), and a bad 'last used' never wins over a person's own
  await page.evaluate(() => localStorage.setItem('craft-conductor-style:owner', 'neon'));
  await page.reload();
  await page.locator('.server-card', { hasText: 'Alpha' }).waitFor();
  assert.equal(await style(page), 'modern', 'an unknown value means Modern');
  await page.evaluate(() => { localStorage.setItem('craft-conductor-style:owner', 'classic'); localStorage.setItem('craft-conductor-style', 'neon'); });
  await page.reload();
  await page.locator('.server-card', { hasText: 'Alpha' }).waitFor();
  assert.equal(await style(page), 'classic');

  // Live updates: the server list is rebuilt when Alpha starts and stops, without giving its buttons listeners,
  // and one press of Start starts it once.
  await choose(modern, '#servers');
  await page.locator('.server-card', { hasText: 'Alpha' }).waitFor();
  const starts = [];
  page.on('request', (r) => { if (/\/server\/start$/.test(r.url())) starts.push(r.url()); });
  const card = page.locator('.server-card', { hasText: 'Alpha' });
  await card.getByRole('button', { name: 'Start Alpha', exact: true }).click();
  await card.getByRole('button', { name: 'Stop Alpha', exact: true }).waitFor({ timeout: 40000 });
  assert.equal(starts.length, 1, 'Start pressed once starts once');
  await card.getByRole('button', { name: 'Stop Alpha', exact: true }).click();
  const yes = page.locator('.toast-dialog').getByRole('button', { name: /^Stop/ });
  if (await yes.count()) await yes.first().click();
  await card.getByRole('button', { name: 'Start Alpha', exact: true }).waitFor({ timeout: 40000 });
  const listeners = await page.evaluate(() => ({
    list: window.__listeners(document.querySelector('.server-list'), 'click'),
    buttons: [...document.querySelectorAll('.server-list button[data-act]')].map((b) => window.__listeners(b, 'click')),
  }));
  assert.equal(listeners.list, 1, 'one listener for the whole list');
  assert.ok(listeners.buttons.length && listeners.buttons.every((n) => n === 0), JSON.stringify(listeners));

  // Pictures of the four, for a person to look at.
  if (shots) {
    for (const [s, th] of [['classic', 'day'], ['classic', 'night'], ['modern', 'day'], ['modern', 'night']]) {
      await page.evaluate(([s, th]) => { localStorage.setItem('craft-conductor-style:owner', s); localStorage.setItem('craft-conductor-style', s); localStorage.setItem('craft-conductor-theme', th); }, [s, th]);
      for (const view of ['#servers', '#s/alpha/dashboard', '#s/alpha/settings']) {
        await page.goto(base + '/' + view);
        await page.reload();
        await page.locator('#nav a').first().waitFor();
        await page.waitForTimeout(900);
        await page.screenshot({ path: path.join(shots, `${s}-${th}-${view.replace(/[#/]/g, '_')}.png`) });
      }
    }
  }

  // A phone: fingers need 44 pixels, and nothing at the top covers anything else.
  const phone = await open({ viewport: { width: 360, height: 780 }, hasTouch: true, isMobile: true });
  assert.equal((await phone.request.post(base + '/api/login', { data: { password: '2468' }, headers: H })).status(), 200);
  await phone.goto(base + '/#s/alpha/dashboard');
  await phone.locator('#btn-start').waitFor();
  assert.ok(await phone.evaluate(() => matchMedia('(pointer: coarse)').matches));
  for (const s of ['classic', 'modern']) {
    await phone.evaluate((s) => { localStorage.setItem('craft-conductor-style:owner', s); }, s);
    await phone.reload();
    await phone.locator('#btn-start').waitFor();
    assert.equal(await style(phone), s);
    const sizes = await phone.evaluate(() => {
      const box = (el) => el.getBoundingClientRect();
      const small = [];
      for (const el of document.querySelectorAll('#cc-app-menu, #bell, .topbar .btn')) {
        const r = box(el);
        if (r.width && (r.width < 44 || r.height < 44)) small.push([el.id || el.className || el.textContent, Math.round(r.width), Math.round(r.height)]);
      }
      const sr = box(document.querySelector('#cc-app-menu'));
      const overlaps = [];
      const top = ['#cc-app-menu', '#bell', '.topbar .server-id', '.topbar .actions'].map((q) => [q, box(document.querySelector(q))]);
      for (let i = 0; i < top.length; i++) for (let j = i + 1; j < top.length; j++) {
        const [a, ra] = top[i], [b, rb] = top[j];
        if (ra.width && rb.width && ra.left < rb.right && rb.left < ra.right && ra.top < rb.bottom && rb.top < ra.bottom) overlaps.push([a, b]);
      }
      return { small, overlaps, scrollsSideways: document.documentElement.scrollWidth > innerWidth, menu: Math.round(sr.width) };
    });
    assert.deepEqual(sizes.small, [], `${s}: big enough for a finger`);
    assert.deepEqual(sizes.overlaps, [], `${s}: nothing at the top overlaps`);
    assert.ok(!sizes.scrollsSideways, `${s}: no sideways scrolling`);
    // the menu: its links
    await phone.locator('#cc-app-menu').click();
    const menu = await phone.evaluate(() => {
      const links = [...document.querySelectorAll('#nav a, #nav .nav-group')].map((a) => a.getBoundingClientRect().height).filter((x) => x > 0);  // (not what Maintenance folds away)
      // nothing in the menu shows (or answers a tap) beside or under the close button, scrolled or not
      const button = document.querySelector('#cc-app-menu').getBoundingClientRect();
      const under = () => [...document.querySelectorAll('.sidebar a, .sidebar button, .sidebar .brand')].filter((el) => {
        const r = el.getBoundingClientRect();
        for (let y = Math.max(r.top + 1, 0); y < Math.min(r.bottom, button.bottom); y += 4) if (document.elementFromPoint(r.left + r.width / 2, y)?.closest('a, button, .brand') === el) return true;
        return false;
      }).map((el) => el.textContent.trim());
      const coveredAtTop = under();
      document.querySelector('.sidebar-foot').scrollIntoView({ block: 'center' });
      const coveredScrolled = under();
      if (coveredAtTop.length || coveredScrolled.length) return { coveredAtTop, coveredScrolled };
      return { shortest: Math.min(...links) };
    });
    assert.ok(!menu.coveredAtTop, `${s}: in the menu, beside the close button: ${JSON.stringify(menu)}`);
    assert.ok(menu.shortest >= 44, `${s}: menu links ${menu.shortest}px`);
    if (shots) await phone.screenshot({ path: path.join(shots, `${s}-phone-menu.png`) });
    await phone.keyboard.press('Escape');
    if (shots) await phone.screenshot({ path: path.join(shots, `${s}-phone-dashboard.png`) });
  }

  // One main heading on each page, its title: the top bar's on Your servers, the page's own elsewhere.
  for (const [view, name] of [['#servers', 'Your servers'], ['#s/alpha/dashboard', 'Dashboard'], ['#help', 'Help'], ['#manual', 'User manual'],
    ['#craft-conductor', 'Craft Conductor settings'], ['#new', 'Create a new server']]) {
    await page.goto(base + '/' + view);
    await page.getByRole('heading', { level: 1, name }).waitFor();
    assert.deepEqual(await page.getByRole('heading', { level: 1 }).allTextContents(), [name], `${view}: one main heading`);
  }

  assert.deepEqual(outside, [], 'nothing was fetched from another site (no font service)');
  assert.deepEqual(errors, []);
  await browser.close();
  console.log('styles ok');
})().catch((e) => { console.error(e); process.exit(1); });
