// Start, Stop and Restart in a real browser (see test_ui_power_buttons.py): a double-click counts
// once, with no "busy" error beside the result, and the Stop question is asked once.
const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');
(async () => {
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const base = process.argv[2];
  const H = { 'X-CRAFT-CONDUCTOR': '1' };
  assert.equal((await page.request.post(base + '/api/login', { data: { password: 'PASSWORD' }, headers: H })).status(), 200);
  assert.equal((await page.request.post(base + '/api/auth/change', { data: { mode: 'pin', secret: '2468' }, headers: H })).status(), 200);
  await page.addInitScript(() => { localStorage.setItem('craft-conductor-sounds', 'off'); });
  const presses = [];
  page.on('request', (r) => { const m = /\/server\/(start|stop|restart)$/.exec(r.url()); if (m && r.method() === 'POST') presses.push(m[1]); });
  const state = async () => (await (await page.request.get(base + '/api/servers/alpha/status')).json()).state;
  const until = async (want) => { for (let i = 0; i < 150 && (await state()) !== want; i++) await page.waitForTimeout(200); assert.equal(await state(), want); };
  const busyErrors = () => page.locator('.toast.bad').filter({ hasText: 'busy' }).count();
  const enabled = (name) => page.waitForFunction((n) => { const b = document.querySelector(n); return b && !b.disabled; }, name, { timeout: 30000 });

  await page.goto(base + '/#s/alpha/dashboard');
  await page.locator('#app').waitFor({ state: 'visible' });
  await enabled('#btn-start');
  await page.locator('#btn-start').dblclick();
  await until('running');
  await enabled('#btn-restart');
  await page.locator('#btn-restart').dblclick();
  await page.waitForTimeout(1500);
  await until('running');
  await enabled('#btn-stop');
  await page.locator('#btn-stop').dblclick();
  const question = page.getByRole('alertdialog').filter({ hasText: 'Stop the server?' });
  await question.first().waitFor();
  await page.waitForTimeout(500);
  assert.equal(await question.count(), 1);  // asked once
  await question.getByRole('button', { name: 'Stop', exact: true }).click();
  await until('stopped');
  await page.waitForTimeout(1000);
  assert.deepEqual(presses, ['start', 'restart', 'stop']);
  assert.equal(await busyErrors(), 0);
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
