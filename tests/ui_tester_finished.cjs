// "Mod test finished" is a message in the middle with the whole page blurred behind it, not a 380-pixel
// strip at the left (#140); "Testing mods" stays a small message at the top. See test_ui_styles.py.
const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');
(async () => {
  const [base] = process.argv.slice(2);
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  const page = await browser.newPage({ viewport: { width: 2560, height: 1200 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const H = { 'X-CRAFT-CONDUCTOR': '1' };
  assert.equal((await page.request.post(base + '/api/login', { data: { password: 'PASSWORD' }, headers: H })).status(), 200);
  await page.goto(base + '/#servers');
  await page.waitForLoadState('networkidle');
  // The small one, at the top.
  await page.evaluate(() => stickyToast('tester-toast', [h('strong', {}, 'Testing mods'), h('span', {}, 'A test boot takes a few minutes.')], { blocking: false }));
  const small = await page.locator('#tester-toast').boundingBox();
  assert.ok(small.width < 640 && small.y < 120, `the small message is ${small.width} px wide, at ${small.y} px`);
  assert.equal(await page.locator('#tester-toast').evaluate((e) => getComputedStyle(e).maxWidth), '380px');
  await page.evaluate(() => closeToast('tester-toast'));
  // The one that needs an answer: the whole page behind it, the message in the middle.
  await page.evaluate(() => stickyToast('tester-toast', [h('strong', {}, 'Mod test finished'), h('span', {}, 'The server started with these mods.'),
    h('div', { class: 'row mt-s' }, h('button', { class: 'btn small primary' }, 'See the results'))]));
  const backdrop = await page.locator('#tester-toast').boundingBox();
  assert.ok(backdrop.width >= 2500 && backdrop.height >= 1100, `the backdrop is ${backdrop.width} × ${backdrop.height}`);
  const box = await page.locator('#tester-toast .toast-dialog').boundingBox();
  const middle = box.x + box.width / 2;
  assert.ok(Math.abs(middle - 1280) < 40, `the message's middle is at ${middle} px`);
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
