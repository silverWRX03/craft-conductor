// When the server answers slower than the page asks (the console every second, a test boot's log
// every 1.5 s): each line once, and a test's result once, not again for each question still
// waiting. See test_ui_styles.py.
const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');
(async () => {
  const [base] = process.argv.slice(2);
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const H = { 'X-CRAFT-CONDUCTOR': '1' };
  assert.equal((await page.request.post(base + '/api/login', { data: { password: 'PASSWORD' }, headers: H })).status(), 200);
  // The quick check and the test boot, answered here: the boot's log slowly.
  const json = (route, body) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  const slowly = () => new Promise((ok) => setTimeout(ok, 4000));

  // The console: its lines, slowly; and a command sent meanwhile.
  await page.route('**/api/servers/alpha/console?*', async (route) => {
    const since = Number(new URL(route.request().url()).searchParams.get('since'));
    await slowly();
    json(route, since === 0 ? { lines: [{ text: '[12:00:00] [Server thread/INFO]: Done (3.2s)!' }], last: 1 } : { lines: [], last: 1 });
  });
  await page.route('**/api/servers/alpha/command', (route) => json(route, { ok: true }));
  await page.goto(base + '/#s/alpha/console');
  await page.locator('.cc-log-line').first().waitFor({ timeout: 30000 });
  await page.fill('input[aria-label="Server command"]', 'list');
  await page.press('input[aria-label="Server command"]', 'Enter');
  await page.waitForTimeout(9000);  // (the questions still on their way arrive)
  assert.equal(await page.locator('.cc-log-line', { hasText: 'Done (3.2s)!' }).count(), 1, 'each console line once');

  // A test boot.
  await page.route('**/api/test-check', (route) => json(route, { id: 'c' }));
  await page.route('**/api/hub/mods/check?*', (route) => json(route, { state: 'done', elapsed: 1,
    result: { conflicts: [], problems: [], mods: [], minecraft: '1.21.1' } }));
  let asked = 0;
  await page.route('**/api/hub/trial*', async (route) => {
    if (route.request().method() === 'POST') return json(route, { id: 't' });
    asked += 1;
    const since = Number(new URL(route.request().url()).searchParams.get('since'));
    await slowly();
    json(route, since === 0
      ? { state: 'running', log: ['Test 1: all the mods'], next: 1, elapsed: 4, tests: 1 }
      : { state: 'done', log: ['It started.'], next: 2, elapsed: 8, tests: 1, result: { ok: true, working: [], minecraft: '1.21.1' } });
  });
  await page.goto(base + '/#servers');
  await page.waitForLoadState('networkidle');
  await page.evaluate(() => openTester({ check: ['/api/test-check', {}], trial: { mods: [] } }));
  await page.locator('#tester button', { hasText: 'Start a test boot' }).click();
  await page.locator('#tester .notice.ok', { hasText: 'It works' }).waitFor({ timeout: 30000 });
  await page.waitForTimeout(5000);  // (any answer still on its way arrives)
  const log = await page.locator('#tester details pre.log').textContent();
  assert.equal(log, 'Test 1: all the mods\nIt started.\n', 'each line of the log once');
  assert.equal(await page.locator('#tester .notice.ok').count(), 1);
  assert.ok(asked <= 3, `asked ${asked} times for 2 answers`);
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
