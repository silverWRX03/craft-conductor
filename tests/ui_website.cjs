// The homepage (see test_website_browser.py): how it looks on a computer and a phone, its menu and
// themes, opening and leaving the demo with the mouse and the keyboard, the QR code, the pages it must
// keep (the invite page, the testing dashboard, with the homepage's sidebar and theme), and that the demo is
// kept apart from the website.
const { assert, browsers, launch, watch, demoFrame, suite, shot, noSidewaysScroll, until } = require('./ui_website_lib.cjs');
const base = process.argv[2];

(async () => {
  const problems = [];
  const t = suite('ui_website');
  for (const name of browsers) {
    const browser = await launch(name);
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    watch(page, base, problems, `${name} homepage`);

    await t.step(`${name}: the homepage on a computer`, async () => {
      await page.goto(base);
      assert.match(await page.title(), /Craft Conductor/);
      assert.equal(await page.getAttribute('html', 'data-theme'), 'night', 'dark by default');
      assert.ok(await page.locator('#site-nav').isVisible(), 'the navigation is on the left');
      const box = await page.locator('#site-nav').boundingBox();
      assert.ok(box.x === 0 && box.width > 180, 'the navigation is a left sidebar');
      for (const id of ['home', 'features', 'demo', 'download', 'start', 'help', 'safety']) assert.equal(await page.locator(`section#${id}`).count(), 1, id);
      const imgs = await page.$$eval('main img', (els) => els.map((i) => [i.getAttribute('src'), i.complete && i.naturalWidth > 0, i.alt]));
      for (const el of await page.$$('main img')) await el.scrollIntoViewIfNeeded();
      await page.waitForTimeout(300);
      const loaded = await page.$$eval('main img', (els) => els.map((i) => [i.getAttribute('src'), i.naturalWidth > 0, !!i.alt]));
      assert.ok(loaded.length >= 7, 'real screenshots are shown');
      for (const [src, ok, alt] of loaded) { assert.ok(ok, `${src} loaded`); assert.ok(alt, `${src} has words for screen readers`); }
      void imgs;
      await until(async () => /Demo: \S+ · \S+/.test(await page.textContent('#represented-version')), 'the demo version label');
      await shot(page, `${name}-home-dark`);
    });

    await t.step(`${name}: downloads, the invite page and the testing dashboard`, async () => {
      const hrefs = await page.$$eval('.download-option', (as) => as.map((a) => a.getAttribute('href')));
      assert.deepEqual(hrefs.map((h) => h.split('/').pop()), ['craft-conductor-windows-x64.exe', 'craft-conductor-macos-arm64', 'craft-conductor-linux-x64', 'craft-conductor-linux-arm64']);
      for (const h of hrefs) assert.match(h, /^https:\/\/github\.com\/silverWRX03\/craft-conductor\/releases\/latest\/download\//);
      for (const p of ['testing/', 'testing/data/', 'join/', 'googlef2c4a8b5e575e76a.html', 'demo/phone-qr.svg', 'demo/manifest.webmanifest']) {
        const r = await page.request.get(base + p);
        assert.ok(r.ok() || (p === 'testing/data/' && r.status() === 404), `${p}: ${r.status()}`);
      }
      const testing = await ctx.newPage();
      watch(testing, base, problems, `${name} testing dashboard`);
      await testing.goto(base + 'testing/');
      await until(async () => (await testing.locator('#tests tr').count()) > 10, 'the testing dashboard lists its tests');
      const nav = await testing.locator('#site-nav').boundingBox();
      assert.ok(nav.x === 0 && nav.width > 180, "the testing dashboard has the homepage's sidebar");
      assert.equal(await testing.locator('#site-nav .nav-link').count(), await page.locator('#site-nav .nav-link').count(), 'the same links');
      assert.match(await testing.textContent('#site-nav [aria-current="page"]'), /Real-world testing$/, 'Real-world testing is the page on show');
      assert.ok((await testing.locator('#stats .card').count()) === 5, 'the counts');
      await shot(testing, `${name}-testing-dark`);
      await testing.click('#site-nav a[href="../#download"]');
      await testing.waitForURL(/#download$/);
      assert.ok(await testing.locator('section#download').isVisible(), 'its links go back to the homepage');
      await testing.close();
      const join = await ctx.newPage();
      await join.goto(base + 'join/');
      assert.ok((await join.textContent('body')).length > 50, 'the invite page shows');
      await join.close();
    });

    await t.step(`${name}: day and night`, async () => {
      await page.click('#theme-toggle');
      assert.equal(await page.getAttribute('html', 'data-theme'), 'day');
      assert.equal(await page.getAttribute('#theme-toggle', 'aria-checked'), 'false');
      const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
      assert.equal(bg, 'rgb(244, 244, 244)');
      await shot(page, `${name}-home-light`);
      await page.reload();
      assert.equal(await page.getAttribute('html', 'data-theme'), 'day', 'remembered');
      const testing = await ctx.newPage();
      await testing.goto(base + 'testing/');
      assert.equal(await testing.getAttribute('html', 'data-theme'), 'day', 'the testing dashboard has the same theme');
      assert.equal(await testing.evaluate(() => getComputedStyle(document.body).backgroundColor), 'rgb(244, 244, 244)');
      await until(async () => (await testing.locator('#tests tr').count()) > 10, 'the testing dashboard lists its tests');
      await shot(testing, `${name}-testing-light`);
      await testing.close();
      await page.click('#theme-toggle');
      assert.equal(await page.getAttribute('html', 'data-theme'), 'night');
    });

    await t.step(`${name}: open the demo, choose, leave with Escape and the bar`, async () => {
      const launcher = page.locator('.hero-actions .launch-demo');
      await launcher.focus();
      await page.keyboard.press('Enter');
      await page.locator('#demo-overlay').waitFor({ state: 'visible' });
      assert.ok(await page.evaluate(() => document.getElementById('website').inert), 'the website behind is inactive');
      assert.equal(await page.evaluate(() => document.activeElement.id), 'demo-heading', 'the focus moves to the demo');
      assert.ok(await page.locator('#leave-demo').isVisible());
      const rail = await page.locator('#leave-demo').boundingBox(), drawer = await page.locator('#demo-drawer').boundingBox();
      assert.ok(rail.x < drawer.x && drawer.x + drawer.width >= 1430, 'the bar is on the left of the demo, which comes in from the right');
      assert.equal(await page.locator('[data-start]').count(), 2, 'two ways to start');
      await shot(page, `${name}-demo-choices`);
      await page.keyboard.press('Escape');
      await page.locator('#demo-overlay').waitFor({ state: 'hidden' });
      assert.ok(!(await page.evaluate(() => document.getElementById('website').inert)));
      assert.equal(await page.evaluate(() => document.activeElement.textContent.trim().slice(0, 12)), 'Try the demo', 'the focus goes back');
      await page.click('.choice-card.launch-demo[data-scenario="existing"]');
      const f = await demoFrame(page);
      await until(async () => /Family Survival/.test(await f.textContent('#server-title')), 'the server on show');
      await shot(page, `${name}-demo-existing`);
      await page.click('#leave-demo');
      await page.locator('#demo-overlay').waitFor({ state: 'hidden' });
      assert.equal(await page.evaluate(() => document.querySelector('#demo-frame, #frame-holder iframe').getAttribute('src')), null, 'the demo stops when left');
    });

    const closed = async () => { if (await page.locator('#demo-overlay').isVisible()) await page.click('#leave-demo'); };
    t.page = page;
    await t.step(`${name}: the demo is kept apart from the website`, async () => {
      await closed();
      await page.click('.choice-card.launch-demo[data-scenario="existing"]');
      const f = await demoFrame(page);
      const sandbox = await page.getAttribute('#frame-holder iframe', 'sandbox');
      assert.ok(!sandbox.includes('allow-same-origin') && sandbox.includes('allow-scripts'), sandbox);
      const inside = await f.evaluate(async () => {
        const r = { origin: self.origin };
        try { r.parent = !!window.parent.document; } catch (_) { r.parent = 'blocked'; }
        try { r.top = window.top.location.href; } catch (_) { r.top = 'blocked'; }
        try { await fetch('https://example.com/'); r.outside = 'reached'; } catch (_) { r.outside = 'refused'; }
        try { await fetch(location.origin + '/craft-conductor/index.html'); r.site = 'reached'; } catch (_) { r.site = 'refused'; }
        try { new WebSocket('wss://example.com/'); r.ws = 'made'; } catch (_) { r.ws = 'refused'; }
        r.storageIsOwn = localStorage.getItem('cc-site-theme') === null;
        const unknown = await fetch('/api/hub/no-such-thing');
        r.unknown = unknown.status;
        r.csp = document.querySelector('meta[http-equiv="Content-Security-Policy"]').content;
        return r;
      });
      assert.equal(inside.origin, 'null', 'an origin of its own');
      assert.equal(inside.parent, 'blocked', "it can't reach the website's page");
      assert.equal(inside.top, 'blocked');
      assert.equal(inside.outside, 'refused', 'no outside connections');
      assert.equal(inside.site, 'refused', "it can't read the website's files either");
      assert.equal(inside.ws, 'refused');
      assert.ok(inside.storageIsOwn, "the website's storage isn't the demo's");
      assert.equal(inside.unknown, 501, 'an address the demo doesn\'t know is refused, and nothing is sent');
      assert.match(inside.csp, /connect-src 'none'/);
      await until(async () => (await f.locator('.cc-demo-note').count()) > 0, "the visitor is told the part isn't simulated");
      // The panel's page opened on its own (not in the website's frame) doesn't start.
      const alone = await ctx.newPage();
      const requested = [];
      alone.on('request', (r) => requested.push(r.url()));
      await alone.goto(base + 'demo/app/');
      await alone.waitForTimeout(800);
      assert.match(await alone.textContent('body'), /part of the Craft Conductor website's demo/);
      assert.ok(!requested.some((u) => u.endsWith('/assets/app.js')), 'the real page\'s scripts never load outside the frame');
      await alone.close();
      await page.click('#leave-demo');
    });

    await t.step(`${name}: the QR code`, async () => {
      await closed();
      const qr = page.locator('#phone-qr');
      await qr.scrollIntoViewIfNeeded();
      const svg = (await page.request.get(base + 'demo/phone-qr.svg')).text ? await (await page.request.get(base + 'demo/phone-qr.svg')).text() : '';
      assert.match(svg, /^<svg[^>]+viewBox="0 0 \d+ \d+"/);
      assert.match(await page.getAttribute('#phone-link', 'href'), /^demo\/\?mode=existing&mobile=1$/);
      await qr.click();
      const f = await demoFrame(page);
      const holder = await page.locator('#frame-holder').boundingBox();
      assert.ok(holder.width <= 420, `a phone-sized preview (${holder.width}px)`);
      assert.ok(await page.locator('#phone-side').isVisible(), 'with the code to scan beside it');
      assert.ok(await f.locator('#cc-app-menu').isVisible(), "the real app's phone menu shows");
      await shot(page, `${name}-demo-phone-view`);
      await page.click('#demo-view');
      await demoFrame(page);
      assert.ok((await page.locator('#frame-holder').boundingBox()).width > 900, 'back to the desktop view');
      await page.click('#leave-demo');
    });

    await t.step(`${name}: less motion`, async () => {
      const calm = await browser.newContext({ viewport: { width: 1280, height: 800 }, reducedMotion: 'reduce' });
      const p = await calm.newPage();
      await p.goto(base);
      await p.click('.hero-actions .launch-demo');
      assert.equal(await p.evaluate(() => getComputedStyle(document.getElementById('demo-drawer')).animationName), 'none');
      await calm.close();
    });

    await t.step(`${name}: on a phone and a tablet`, async () => {
      for (const [w, h, label] of [[390, 844, 'phone'], [768, 1024, 'tablet'], [360, 740, 'small-phone']]) {
        const small = await browser.newContext({ viewport: { width: w, height: h }, isMobile: name === 'chromium', hasTouch: true });
        const p = await small.newPage();
        watch(p, base, problems, `${name} ${label}`);
        await p.goto(base);
        await noSidewaysScroll(p, `${label} homepage`);
        if (w <= 820) {
          assert.ok(await p.locator('#menu-toggle').isVisible(), 'a menu button');
          assert.ok(!(await p.locator('#site-nav').isVisible()) || (await p.locator('#site-nav').boundingBox()).x < 0, 'the navigation is put away');
          await p.click('#menu-toggle');
          await until(async () => (await p.locator('#site-nav').boundingBox()).x >= 0, 'the menu opens');
          assert.equal(await p.getAttribute('#menu-toggle', 'aria-expanded'), 'true');
          await p.keyboard.press('Escape');
          await until(async () => (await p.getAttribute('#menu-toggle', 'aria-expanded')) === 'false', 'the menu closes');
        }
        await shot(p, `${name}-home-${label}`);
        const testing = await small.newPage();
        watch(testing, base, problems, `${name} ${label} testing dashboard`);
        await testing.goto(base + 'testing/');
        await until(async () => (await testing.locator('#tests tr').count()) > 10, 'the testing dashboard lists its tests');
        await noSidewaysScroll(testing, `${label} testing dashboard`);
        await shot(testing, `${name}-testing-${label}`);
        if (w <= 820) {
          await testing.click('#menu-toggle');
          await until(async () => (await testing.locator('#site-nav').boundingBox()).x >= 0, 'the testing dashboard menu opens');
          await testing.keyboard.press('Escape');
          await until(async () => (await testing.getAttribute('#menu-toggle', 'aria-expanded')) === 'false', 'the testing dashboard menu closes');
        }
        await testing.close();
        await p.click('.hero-actions .launch-demo');
        await p.click('[data-start="new"]');
        const f = await demoFrame(p);
        await noSidewaysScroll(p, `${label} demo`);
        assert.ok(await f.locator('main#main').isVisible());
        await shot(p, `${name}-demo-${label}`);
        await small.close();
      }
    });
    await browser.close();
  }
  t.done(problems);
})();
