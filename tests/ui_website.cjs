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
    t.page = page;

    await t.step(`${name}: the homepage on a computer`, async () => {
      await page.goto(base);
      assert.match(await page.title(), /Craft Conductor/);
      assert.equal(await page.getAttribute('html', 'data-theme'), 'night', 'dark by default');
      assert.ok(await page.locator('#site-nav').isVisible(), 'the navigation is on the left');
      const box = await page.locator('#site-nav').boundingBox();
      assert.ok(box.x === 0 && box.width > 180, 'the navigation is a left sidebar');
      for (const id of ['home', 'features', 'demo', 'download', 'start', 'help', 'safety']) assert.equal(await page.locator(`section#${id}`).count(), 1, id);
      assert.equal(await page.locator('#home .launch-demo, #home a[href="#download"]').count(), 0, 'the hero has no duplicate actions');
      const video = await page.locator('#home .video-placeholder').boundingBox();
      assert.ok(video && Math.abs(video.width / video.height - 16 / 9) < 0.02, 'the video placeholder keeps its 16:9 shape');
      assert.equal(await page.locator('#home iframe, #home video').count(), 0, 'no invented video or external player is loaded');
      await page.evaluate(() => document.fonts.ready);
      await until(async () => page.evaluate(() => document.getElementById('home').style.getPropertyValue('--hero-min-height')), 'the desktop section proportions settle');
      const layout = await page.evaluate(() => {
        const hero = document.getElementById('home'), style = getComputedStyle(hero);
        const available = hero.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) - parseFloat(style.columnGap);
        const video = hero.querySelector('.video-placeholder').getBoundingClientRect();
        const contentHeight = Math.max(hero.querySelector('.hero-text').offsetHeight, hero.querySelector('.video-placeholder').offsetHeight);
        return { videoWidth: video.width, originalVideoWidth: available / 2.15,
          heroHeight: hero.offsetHeight, expectedHeroHeight: contentHeight + parseFloat(style.paddingTop) + parseFloat(style.paddingBottom) + 1,
          headingAlign: getComputedStyle(document.getElementById('features-title')).textAlign };
      });
      assert.ok(Math.abs(layout.videoWidth / layout.originalVideoWidth - 1.5) < .01, 'the desktop video is 1.5 times wider and taller');
      assert.ok(Math.abs(layout.heroHeight - layout.expectedHeroHeight) <= 1, 'the larger carousel does not stretch the approved Home layout');
      assert.equal(layout.headingAlign, 'center', 'What it does stays centered');
      const fonts = await page.evaluate(() => ({
        body: getComputedStyle(document.body).fontFamily,
        controls: [...document.querySelectorAll('button, .nav-link')].map((el) => getComputedStyle(el).fontFamily),
        loaded: [...document.fonts].some((font) => /Roboto/.test(font.family) && font.status === 'loaded'),
      }));
      assert.match(fonts.body, /Roboto/);
      assert.ok(fonts.loaded, 'the bundled Roboto font actually loaded');
      assert.ok(fonts.controls.every((font) => /Roboto/.test(font)), 'controls and navigation also use Roboto');
      await until(async () => /Demo: \S+ · \S+/.test(await page.textContent('#represented-version')), 'the demo version label');
      await shot(page, `${name}-home-dark`);
    });

    await t.step(`${name}: feature carousel, captions and keyboard navigation`, async () => {
      const carousel = page.locator('#feature-carousel');
      const slides = carousel.locator('.feature');
      const dots = carousel.locator('[data-carousel-dot]');
      const next = carousel.locator('[data-carousel-next]');
      const previous = carousel.locator('[data-carousel-prev]');
      assert.equal(await slides.count(), 6, 'all six original features remain');
      assert.equal(await dots.count(), 6);
      assert.equal(await carousel.getAttribute('aria-roledescription'), 'carousel');
      assert.equal(await page.getAttribute('#carousel-status', 'aria-live'), 'polite');
      const titles = await slides.locator('h3').allTextContents();
      const check = async (index, announced = true) => {
        await until(async () => (await slides.nth(index).getAttribute('class')).split(/\s+/).includes('active'), `feature ${index + 1}`);
        assert.equal(await carousel.locator('.feature.active').count(), 1, 'exactly one active feature');
        assert.equal(await carousel.locator('[data-carousel-dot][aria-current="true"]').count(), 1);
        assert.equal(await dots.nth(index).getAttribute('aria-current'), 'true');
        if (announced) assert.match(await page.textContent('#carousel-status'), new RegExp(`${index + 1}.*6`));
        for (let i = 0; i < 6; i++) {
          assert.equal((await slides.nth(i).getAttribute('aria-hidden')) === 'true', i !== index, 'only the active slide is read');
        }
        const active = slides.nth(index);
        await until(async () => carousel.evaluate((el) => el.getAnimations({ subtree: true }).length === 0), 'the slide transition finishes');
        await until(async () => active.locator('img').evaluate((img) => img.complete && img.naturalWidth > 0), `feature ${index + 1} screenshot loaded`);
        assert.ok((await active.locator('img').getAttribute('alt')).trim(), 'the image has alternative text');
        const image = await active.locator('img').boundingBox();
        const title = await active.locator('h3').boundingBox();
        const description = await active.locator('p').boundingBox();
        assert.ok(image && title && description && title.y >= image.y + image.height - 1 && description.y > title.y, 'the title and description are below the image');
        assert.equal((await active.locator('h3').textContent()).trim(), titles[index].trim());
      };
      await carousel.scrollIntoViewIfNeeded();
      await check(0, false);
      const picture = await slides.nth(0).locator('img').boundingBox();
      const carouselBox = await carousel.boundingBox();
      assert.ok(Math.abs(picture.width / carouselBox.width - .7) < .01, 'the desktop carousel keeps its original large screenshot width');
      assert.ok(Math.abs(picture.width / picture.height - 8 / 5) < .02, 'the screenshot keeps its original full-image proportions');
      assert.equal(await slides.nth(0).locator('img').evaluate((img) => getComputedStyle(img).objectFit), 'contain', 'the full screenshot stays visible');
      const movement = await carousel.evaluate(async (el) => {
        const first = el.querySelectorAll('.feature')[0], second = el.querySelectorAll('.feature')[1];
        const start = first.getBoundingClientRect().x;
        el.querySelector('[data-carousel-next]').click();
        const animations = el.getAnimations({ subtree: true });
        // Freeze at the midpoint, so the assertion measures movement without depending on timing.
        for (const animation of animations) { animation.pause(); animation.currentTime = 210; }
        const incoming = second.getBoundingClientRect().x, outgoing = first.getBoundingClientRect().x;
        for (const animation of animations) animation.finish();
        await Promise.all(animations.map((animation) => animation.finished));
        return { start, incoming, outgoing, end: second.getBoundingClientRect().x, count: animations.length };
      });
      assert.ok(movement.count > 0 && movement.incoming > movement.end + 1 && movement.outgoing < movement.start - 1,
        'the incoming and outgoing screenshots slide horizontally');
      await check(1);
      await previous.click();
      await check(0);
      await previous.click();
      await check(5);
      await next.focus();
      await page.keyboard.press('Enter');
      await check(0);
      assert.ok(await next.evaluate((el) => document.activeElement === el), 'moving a slide keeps the button focused');
      for (let i = 1; i < 6; i++) { await next.click(); await check(i); }
      await next.focus();
      await page.keyboard.press('Home');
      await check(0);
      await page.keyboard.press('ArrowRight');
      await check(1);
      await page.keyboard.press('ArrowLeft');
      await check(0);
      await page.keyboard.press('End');
      await check(5);
      await dots.nth(2).focus();
      await page.keyboard.press('Enter');
      await check(2);
      assert.ok(await dots.nth(2).evaluate((el) => document.activeElement === el), 'choosing a feature keeps focus on its selector');
      const neighbors = await carousel.locator('.feature.previous, .feature.next').evaluateAll((els) => els.map((el) => ({
        hidden: el.getAttribute('aria-hidden'), filter: getComputedStyle(el).filter + ' ' + getComputedStyle(el.querySelector('img')).filter,
      })));
      assert.equal(neighbors.length, 2, 'both neighboring screenshot previews are present');
      assert.ok(neighbors.every((el) => el.hidden === 'true' && /blur\(/.test(el.filter)), 'decorative neighboring previews are blurred and hidden from screen readers');
      await page.locator('#features-title').click();
      await page.waitForTimeout(6500);
      await check(2);
      await shot(page, `${name}-features-dark`);
      await dots.nth(0).click();
      await page.locator('#home').scrollIntoViewIfNeeded();
    });

    await t.step(`${name}: features stay readable without JavaScript`, async () => {
      const plain = await browser.newContext({ viewport: { width: 1280, height: 900 }, javaScriptEnabled: false });
      const p = await plain.newPage();
      await p.goto(base);
      const features = p.locator('#feature-carousel .feature');
      assert.equal(await features.count(), 6);
      for (let i = 0; i < 6; i++) {
        await features.nth(i).scrollIntoViewIfNeeded();
        assert.ok(await features.nth(i).isVisible());
        assert.notEqual(await features.nth(i).getAttribute('aria-hidden'), 'true');
        assert.ok(await features.nth(i).locator('h3').isVisible());
        assert.ok(await features.nth(i).locator('p').isVisible());
      }
      assert.ok(!(await p.locator('[data-carousel-next]').isVisible()), 'nonworking carousel controls are hidden without JavaScript');
      await noSidewaysScroll(p, 'the homepage without JavaScript');
      await plain.close();
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
      const nightBackground = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
      await page.click('#theme-toggle');
      assert.equal(await page.getAttribute('html', 'data-theme'), 'day');
      assert.equal(await page.getAttribute('#theme-toggle', 'aria-checked'), 'false');
      const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
      assert.notEqual(bg, nightBackground, 'Light changes the page background');
      await shot(page, `${name}-home-light`);
      await page.reload();
      assert.equal(await page.getAttribute('html', 'data-theme'), 'day', 'remembered');
      const testing = await ctx.newPage();
      await testing.goto(base + 'testing/');
      assert.equal(await testing.getAttribute('html', 'data-theme'), 'day', 'the testing dashboard has the same theme');
      assert.equal(await testing.evaluate(() => getComputedStyle(document.body).backgroundColor), bg, 'the dashboard shares the Light palette');
      await until(async () => (await testing.locator('#tests tr').count()) > 10, 'the testing dashboard lists its tests');
      await shot(testing, `${name}-testing-light`);
      await testing.close();
      await page.click('#theme-toggle');
      assert.equal(await page.getAttribute('html', 'data-theme'), 'night');
    });

    await t.step(`${name}: open the demo, choose, leave with Escape and the bar`, async () => {
      const launcher = page.locator('.choice-card.launch-demo[data-scenario="existing"]');
      await launcher.focus();
      await page.keyboard.press('Enter');
      await page.locator('#demo-overlay').waitFor({ state: 'visible' });
      assert.ok(await page.evaluate(() => document.getElementById('website').inert), 'the website behind is inactive');
      await demoFrame(page);
      await page.click('#demo-choices');
      assert.equal(await page.evaluate(() => document.activeElement.id), 'demo-heading', 'Change demo moves focus to the choices');
      assert.ok(await page.locator('#leave-demo').isVisible());
      const rail = await page.locator('#leave-demo').boundingBox(), drawer = await page.locator('#demo-drawer').boundingBox();
      assert.ok(rail.x < drawer.x && drawer.x + drawer.width >= 1430, 'the bar is on the left of the demo, which comes in from the right');
      assert.equal(await page.locator('[data-start]').count(), 2, 'two ways to start');
      await shot(page, `${name}-demo-choices`);
      await page.keyboard.press('Escape');
      await page.locator('#demo-overlay').waitFor({ state: 'hidden' });
      assert.ok(!(await page.evaluate(() => document.getElementById('website').inert)));
      assert.ok(await launcher.evaluate((el) => document.activeElement === el), 'the focus returns to the button that opened the demo');
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
      await p.locator('[data-carousel-next]').click();
      const movement = await p.locator('#feature-carousel .feature').evaluateAll((els) => els.map((el) => ({
        animation: getComputedStyle(el).animationName,
        durations: getComputedStyle(el).transitionDuration.split(',').map((value) => parseFloat(value)),
      })));
      assert.equal(await p.locator('#feature-carousel').evaluate((el) => el.getAnimations({ subtree: true }).length), 0, 'reduced motion also disables scripted sliding');
      assert.ok(movement.every((el) => el.animation === 'none' && el.durations.every((duration) => duration <= 0.01)), 'reduced motion stops carousel animation');
      assert.equal(await p.locator('#feature-carousel .feature.active').count(), 1, 'navigation still works with less motion');
      await p.click('.choice-card.launch-demo[data-scenario="existing"]');
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
        const video = await p.locator('#home .video-placeholder').boundingBox();
        assert.ok(video && Math.abs(video.width / video.height - 16 / 9) < 0.02, `${label}: the video stays 16:9`);
        await shot(p, `${name}-home-${label}`);
        await p.locator('#feature-carousel').scrollIntoViewIfNeeded();
        await p.click('[data-carousel-next]');
        assert.equal(await p.locator('#feature-carousel .feature.active').count(), 1);
        for (const control of await p.locator('[data-carousel-prev], [data-carousel-next], [data-carousel-dot]').all()) {
          const box = await control.boundingBox();
          assert.ok(box && box.width >= 43.99 && box.height >= 43.99, `${label}: carousel controls have 44px touch targets (allowing subpixel rounding): ${JSON.stringify(box)}`);
        }
        await noSidewaysScroll(p, `${label} feature carousel`);
        await shot(p, `${name}-features-${label}`);
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
        await p.click('.choice-card.launch-demo[data-scenario="existing"]');
        await demoFrame(p);
        await p.click('#demo-choices');
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
