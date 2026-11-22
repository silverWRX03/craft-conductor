// The Away from home card says when the Cloudflare tunnel closed by itself (see test_ui_tunnel_closed.py).
const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');
(async () => {
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const [base, strong] = process.argv.slice(2);
  const H = { 'X-CRAFT-CONDUCTOR': '1' };
  assert.equal((await page.request.post(base + '/api/login', { data: { password: 'PASSWORD' }, headers: H })).status(), 200);
  assert.equal((await page.request.post(base + '/api/auth/change', { data: { mode: 'password', secret: strong }, headers: H })).status(), 200);
  await page.addInitScript(() => { localStorage.setItem('craft-conductor-sounds', 'off'); });

  // Craft Conductor settings → Connections → Remote access & phones → Away from home → Cloudflare.
  await page.goto(base + '/#craft-conductor');
  await page.getByRole('button', { name: 'Connections' }).click();
  await page.getByRole('button', { name: /Remote access & phones…/ }).click();
  const dialog = page.locator('#remote');
  const chooser = dialog.getByRole('group', { name: 'Reach the control panel from outside' });
  await chooser.waitFor({ timeout: 20000 });
  await chooser.locator('[data-outside="cloudflare"]').click();
  const note = dialog.getByText(/^Closed at .* after \d+ hours: the control panel is off the internet again\.$/);
  await note.waitFor({ timeout: 20000 });
  assert.equal(await dialog.getByRole('button', { name: /Open to the internet for \d+ hours/ }).count(), 1);
  console.log(await note.innerText());
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
