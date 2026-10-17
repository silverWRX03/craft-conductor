// The phone demo, what the homepage's QR code opens (see test_website_browser.py): the real control
// panel's phone layout and menu at phone and tablet sizes, each device with its own made-up data, and
// the installable app: its manifest, and a service worker that only ever covers demo/ (never the
// website, the invite page or the testing dashboard).
const { assert, browsers, launch, watch, demoFrame, suite, shot, noSidewaysScroll, until } = require('./ui_website_lib.cjs');
const base = process.argv[2];

(async () => {
  const problems = [];
  const t = suite('ui_website_phone');
  for (const name of browsers) {
    const browser = await launch(name);
    const phone = { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: name === 'chromium', deviceScaleFactor: 2 };

    await t.step(`${name}: the phone demo, with the real app's phone menu`, async () => {
      const ctx = await browser.newContext(phone);
      const page = await ctx.newPage();
      t.page = page;
      watch(page, base, problems, `${name} phone`);
      await page.goto(base + 'demo/?mode=existing&mobile=1');
      const f = await demoFrame(page);
      await noSidewaysScroll(page, 'the phone demo');
      assert.ok(await f.locator('#cc-app-menu').isVisible(), 'the hamburger menu');
      assert.ok(!(await f.locator('#cc-app-sidebar').isVisible()) || (await f.locator('#cc-app-sidebar').boundingBox()).x < 0, 'the menu is put away');
      await f.locator('#cc-app-menu').click();
      await f.locator('#nav a', { hasText: 'Players' }).click();
      await until(async () => /#s\/family-survival\/players$/.test(await f.evaluate(() => location.hash)), 'the Players page');
      await f.locator('#main').waitFor();
      await shot(page, `${name}-phone-players`);
      const box = await f.locator('#main').boundingBox();
      assert.ok(box.width <= 390, `the page fits the phone (${box.width}px)`);
      // A friend asks, and is let in, from the phone.
      await page.evaluate(() => window.craftDemo.command('join-request'));
      await until(async () => (await f.locator('button', { hasText: 'Allow' }).count()) > 0 || (await f.evaluate(async () => (await (await fetch('/api/servers/family-survival/join-requests')).json()).requests.length)) > 0, 'the request');
      await f.evaluate(() => { location.hash = '#s/family-survival/dashboard'; });
      await f.waitForTimeout(400);
      await f.evaluate(() => { location.hash = '#s/family-survival/players'; });
      await f.locator('button', { hasText: 'Allow' }).first().click();
      await until(async () => (await f.evaluate(async () => (await (await fetch('/api/servers/family-survival/status')).json()).players)).includes('Steve_the_Brave'), 'they join');
      await ctx.close();
    });

    await t.step(`${name}: each device keeps its own made-up data`, async () => {
      const a = await browser.newContext(phone), b = await browser.newContext(phone);
      const pa = await a.newPage(), pb = await b.newPage();
      await pa.goto(base + 'demo/?mode=existing&mobile=1');
      await pb.goto(base + 'demo/?mode=existing&mobile=1');
      const fa = await demoFrame(pa), fb = await demoFrame(pb);
      await fa.evaluate(async () => { await fetch('/api/servers/family-survival/backups/create', { method: 'POST', body: JSON.stringify({ label: 'only on phone A' }) }); });
      await until(async () => (await fa.evaluate(async () => (await (await fetch('/api/servers/family-survival/backups')).json()).backups[0].name)).includes('only-on-phone-a'), 'phone A has its backup', 10000);
      const other = await fb.evaluate(async () => (await (await fetch('/api/servers/family-survival/backups')).json()).backups.map((x) => x.name));
      assert.ok(!other.some((n) => n.includes('only-on-phone-a')), "phone B doesn't have it (nothing is shared between devices)");
      // Reset starts this device's demo again.
      await fa.evaluate(() => { window.beforeReset = true; });
      await pa.click('#shell-reset');
      await until(async () => { try { return await fa.evaluate(() => !window.beforeReset && !document.getElementById('app').classList.contains('hidden')); } catch (_) { return false; } }, 'the demo starts again');
      const fa2 = await demoFrame(pa);
      const after = await fa2.evaluate(async () => (await (await fetch('/api/servers/family-survival/backups')).json()).backups.map((x) => x.name));
      assert.ok(!after.some((n) => n.includes('only-on-phone-a')), 'Reset clears it');
      await a.close(); await b.close();
    });

    await t.step(`${name}: on a tablet, and turned sideways`, async () => {
      for (const viewport of [{ width: 820, height: 1180 }, { width: 844, height: 390 }]) {
        const ctx = await browser.newContext({ viewport, hasTouch: true });
        const page = await ctx.newPage();
        watch(page, base, problems, `${name} ${viewport.width}x${viewport.height}`);
        await page.goto(base + 'demo/?mode=new');
        const f = await demoFrame(page);
        await noSidewaysScroll(page, `the demo at ${viewport.width}x${viewport.height}`);
        assert.ok(await f.locator('main#main').isVisible());
        await shot(page, `${name}-demo-${viewport.width}x${viewport.height}`);
        await ctx.close();
      }
    });

    await t.step(`${name}: installable, with a service worker for demo/ only`, async () => {
      const ctx = await browser.newContext(phone);
      const page = await ctx.newPage();
      const manifest = await (await page.request.get(base + 'demo/manifest.webmanifest')).json();
      assert.equal(manifest.scope, './');
      assert.equal(manifest.display, 'standalone');
      assert.match(manifest.start_url, /^\.\/\?mode=existing&mobile=1$/);
      for (const icon of manifest.icons) assert.ok((await page.request.get(base + 'demo/' + icon.src)).ok(), icon.src);
      assert.ok(manifest.icons.some((i) => i.sizes === '192x192') && manifest.icons.some((i) => i.sizes === '512x512'));
      await page.goto(base + 'demo/?mode=existing&mobile=1');
      await demoFrame(page);
      if (name !== 'webkit' || process.platform !== 'win32') {  // (WebKit on Windows has no service workers)
        const scope = await until(() => page.evaluate(async () => { const r = await navigator.serviceWorker.getRegistration(); return r && r.active ? r.scope : null; }), 'the service worker', 15000);
        assert.equal(new URL(scope).pathname, new URL(base).pathname + 'demo/');
        for (const other of ['', 'join/', 'testing/']) {
          const p = await ctx.newPage();
          await p.goto(base + other);
          assert.equal(await p.evaluate(() => !!navigator.serviceWorker && !!navigator.serviceWorker.controller), false, `no service worker controls /${other}`);
          await p.close();
        }
      }
      const shell = await page.evaluate(() => [...document.scripts].map((s) => s.src).filter(Boolean));
      assert.ok(shell.every((s) => s.includes('/demo/')), 'the phone demo only loads its own scripts');
      await ctx.close();
    });
    await browser.close();
  }
  t.done(problems);
})();
