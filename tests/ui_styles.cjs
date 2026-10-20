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
  const group = page.getByRole('group', { name: 'Interface style' });
  const classic = group.getByRole('radio', { name: 'Classic' }), modern = group.getByRole('radio', { name: 'Modern' });
  assert.ok(await modern.isChecked() && !(await classic.isChecked()), 'the switch says Modern');

  // The font comes from Craft Conductor itself, and is what the page's words are drawn in.
  await page.evaluate(() => document.fonts.ready);
  assert.ok(await page.evaluate(() => document.fonts.check('16px Roboto')), 'Roboto is loaded');
  assert.ok(fonts.some(([u, s, t]) => u.endsWith('/fonts/roboto-latin.woff2') && s === 200 && t === 'font/woff2'), JSON.stringify(fonts));
  assert.match(await page.evaluate(() => getComputedStyle(document.body).fontFamily), /^Roboto,/);
  assert.equal(await page.evaluate(() => getComputedStyle(document.body).fontSize), '16px');

  // A server's console: some text in it, something typed in its box, the page scrolled.
  await page.goto(base + '/#s/alpha/console');
  const consoleBox = page.locator('.console').first();
  await consoleBox.waitFor();
  const input = page.locator('.console-input input');
  await input.fill('say typed but not sent');
  const kept = await page.evaluate(() => {
    const c = document.querySelector('.console');
    c.append(Object.assign(document.createElement('div'), { textContent: 'a line already in the console' }));
    window.__console = c; window.__input = document.querySelector('.console-input input');
    return c.textContent.length;
  });
  assert.match(await consoleBox.evaluate((c) => getComputedStyle(c).fontFamily), /monospace|Consolas|Menlo/);

  // Switching by keyboard: Tab to the switch, an arrow key to Classic. Nothing is drawn again.
  await modern.focus();
  await page.keyboard.press('ArrowLeft');
  assert.equal(await style(page), 'classic');
  assert.ok(await classic.isChecked());
  assert.ok(await page.evaluate(() => window.__console === document.querySelector('.console') && window.__input === document.querySelector('.console-input input')),
    'the console and its box are the same ones');
  assert.equal(await input.inputValue(), 'say typed but not sent');
  assert.equal(await page.evaluate(() => document.querySelector('.console').textContent.length), kept);
  assert.equal(page.url().split('#')[1], 's/alpha/console', 'still on the same page');
  // the ring where the keyboard is: on the chosen choice's label
  const ring = await page.evaluate(() => { const l = document.activeElement.closest('label'); const s = getComputedStyle(l); return [s.outlineStyle, s.outlineWidth]; });
  assert.deepEqual(ring, ['solid', '3px']);
  await page.keyboard.press('ArrowRight');
  assert.equal(await style(page), 'modern');

  // Settings: an unsaved change and the page's scroll survive a switch.
  await page.goto(base + '/#s/alpha/settings');
  const motd = page.locator('input').filter({ hasNot: page.locator('[type=checkbox]') }).nth(2);
  await page.locator('.save-bar, .card').first().waitFor();
  await page.waitForTimeout(1200);
  const field = page.locator('main input:not([type=checkbox]):not([type=radio])').first();
  await field.fill('Changed but not saved');
  await page.evaluate(() => { document.querySelector('main').scrollTop = 300; });
  const scrolled = await page.evaluate(() => document.querySelector('main').scrollTop);
  await classic.check();
  assert.equal(await field.inputValue(), 'Changed but not saved', 'an unsaved change stays');
  const after = await page.evaluate(() => document.querySelector('main').scrollTop);
  assert.ok(Math.abs(after - scrolled) <= 40, `the page stays scrolled (${scrolled} -> ${after})`);
  void motd;

  // Day / night is its own setting.
  const night = await theme(page);
  await page.locator('#cc-app-theme [data-theme-toggle]').click();
  assert.notEqual(await theme(page), night);
  assert.equal(await style(page), 'classic', 'day / night leaves the style');
  await modern.check();
  assert.notEqual(await theme(page), night, 'the style leaves day / night');
  await page.locator('#cc-app-theme [data-theme-toggle]').click();
  assert.equal(await theme(page), night);

  // Classic stays Classic: square, capital letters, graph paper; Modern has 16px panels, 8px controls, ordinary words,
  // a plain background and 44-pixel buttons with a mouse too.
  const look = () => page.evaluate(() => {
    const b = document.querySelector('.actions .btn'), c = document.querySelector('main .card');
    return { caps: getComputedStyle(b).textTransform, button: getComputedStyle(b).borderTopLeftRadius, card: getComputedStyle(c).borderTopLeftRadius,
      paper: getComputedStyle(document.body).backgroundImage !== 'none', tall: b.getBoundingClientRect().height >= 44 };
  });
  await classic.check();
  assert.deepEqual(await look(), { caps: 'uppercase', button: '0px', card: '0px', paper: true, tall: false });
  await modern.check();
  assert.deepEqual(await look(), { caps: 'none', button: '8px', card: '16px', paper: false, tall: true });
  assert.ok(await page.evaluate(() => document.getElementById('skip-link').getBoundingClientRect().height >= 44), 'Skip to main content is 44 pixels too');
  // under a mouse a button lifts, and stays still when the computer asks for less motion
  const lift = () => page.locator('main .btn:visible').first().evaluate((b) => getComputedStyle(b).transform);
  await page.locator('main .btn:visible').first().hover();
  await page.waitForTimeout(250);
  assert.equal(await lift(), 'matrix(1, 0, 0, 1, 0, -2)');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.waitForTimeout(50);
  assert.equal(await lift(), 'none');
  await page.emulateMedia({ reducedMotion: null });
  await page.mouse.move(1, 1);

  // Remembered: Classic after a reload, and on the sign-in page.
  await classic.check();
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
  await modern.check();
  const starts = [];
  page.on('request', (r) => { if (/\/server\/start$/.test(r.url())) starts.push(r.url()); });
  const card = page.locator('.server-card', { hasText: 'Alpha' });
  await card.getByRole('button', { name: 'Start', exact: true }).click();
  await card.getByRole('button', { name: 'Stop', exact: true }).waitFor({ timeout: 40000 });
  assert.equal(starts.length, 1, 'Start pressed once starts once');
  await card.getByRole('button', { name: 'Stop', exact: true }).click();
  const yes = page.locator('.toast-dialog').getByRole('button', { name: /^Stop/ });
  if (await yes.count()) await yes.first().click();
  await card.getByRole('button', { name: 'Start', exact: true }).waitFor({ timeout: 40000 });
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
      for (const view of ['#servers', '#s/alpha/dashboard', '#s/alpha/console', '#s/alpha/settings']) {
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
      for (const el of document.querySelectorAll('#cc-app-menu, #bell, .cc-style-switch label, .topbar .btn')) {
        const r = box(el);
        if (r.width && (r.width < 44 || r.height < 44)) small.push([el.id || el.className || el.textContent, Math.round(r.width), Math.round(r.height)]);
      }
      // the day / night switch (in the menu) answers 44 pixels around it
      const sw = document.querySelector('#cc-app-theme .cc-theme-switch');
      const sr = box(document.querySelector('#cc-app-menu'));
      const overlaps = [];
      const top = ['#cc-app-menu', '#cc-style', '#bell', '.topbar .server-id', '.topbar .actions'].map((q) => [q, box(document.querySelector(q))]);
      for (let i = 0; i < top.length; i++) for (let j = i + 1; j < top.length; j++) {
        const [a, ra] = top[i], [b, rb] = top[j];
        if (ra.width && rb.width && ra.left < rb.right && rb.left < ra.right && ra.top < rb.bottom && rb.top < ra.bottom) overlaps.push([a, b]);
      }
      return { small, overlaps, scrollsSideways: document.documentElement.scrollWidth > innerWidth, menu: Math.round(sr.width), switchAfter: getComputedStyle(sw, '::after').inset };
    });
    assert.deepEqual(sizes.small, [], `${s}: big enough for a finger`);
    assert.deepEqual(sizes.overlaps, [], `${s}: nothing at the top overlaps`);
    assert.ok(!sizes.scrollsSideways, `${s}: no sideways scrolling`);
    // the menu: links and the day / night switch
    await phone.locator('#cc-app-menu').click();
    const menu = await phone.evaluate(() => {
      const links = [...document.querySelectorAll('#nav a')].map((a) => a.getBoundingClientRect().height);
      // nothing in the menu shows (or answers a tap) beside or under the close button, scrolled or not
      const button = document.querySelector('#cc-app-menu').getBoundingClientRect();
      const under = () => [...document.querySelectorAll('.sidebar a, .sidebar button, .sidebar .brand')].filter((el) => {
        const r = el.getBoundingClientRect();
        for (let y = Math.max(r.top + 1, 0); y < Math.min(r.bottom, button.bottom); y += 4) if (document.elementFromPoint(r.left + r.width / 2, y)?.closest('a, button, .brand') === el) return true;
        return false;
      }).map((el) => el.textContent.trim());
      const coveredAtTop = under();
      document.querySelector('#cc-app-theme').scrollIntoView({ block: 'center' });
      const coveredScrolled = under();
      if (coveredAtTop.length || coveredScrolled.length) return { coveredAtTop, coveredScrolled };
      const sw = document.querySelector('#cc-app-theme .cc-theme-switch').getBoundingClientRect();
      const at = (x, y) => document.elementFromPoint(x, y);
      const hit = (x, y) => !!at(x, y)?.closest('.cc-theme-switch') || (at(x, y)?.className || at(x, y)?.tagName || 'nothing');
      const cx = sw.left + sw.width / 2, cy = sw.top + sw.height / 2;
      return { shortest: Math.min(...links), hitTop: hit(cx, cy - 21), hitBottom: hit(cx, cy + 21), hitLeft: hit(sw.left, cy), hitRight: hit(sw.right - 1, cy) };
    });
    assert.ok(!menu.coveredAtTop, `${s}: in the menu, beside the close button: ${JSON.stringify(menu)}`);
    assert.ok(menu.shortest >= 44, `${s}: menu links ${menu.shortest}px`);
    assert.ok(menu.hitTop === true && menu.hitBottom === true && menu.hitLeft === true && menu.hitRight === true, `${s}: the day / night switch answers 44 pixels: ${JSON.stringify(menu)}`);
    if (shots) await phone.screenshot({ path: path.join(shots, `${s}-phone-menu.png`) });
    await phone.keyboard.press('Escape');
    if (shots) await phone.screenshot({ path: path.join(shots, `${s}-phone-dashboard.png`) });
  }

  assert.deepEqual(outside, [], 'nothing was fetched from another site (no font service)');
  assert.deepEqual(errors, []);
  await browser.close();
  console.log('styles ok');
})().catch((e) => { console.error(e); process.exit(1); });
