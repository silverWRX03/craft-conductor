// Reaching the control panel from outside, a safety rule, and the reset code (see test_ui_outside.py).
const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');
const fs = require('node:fs');
(async () => {
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const [base, strong, cfName, tsName] = process.argv.slice(2);
  const H = { 'X-CRAFT-CONDUCTOR': '1' };
  assert.equal((await page.request.post(base + '/api/login', { data: { password: 'PASSWORD' }, headers: H })).status(), 200);
  assert.equal((await page.request.post(base + '/api/auth/change', { data: { mode: 'password', secret: strong }, headers: H })).status(), 200);
  await page.addInitScript(() => { localStorage.setItem('craft-conductor-sounds', 'off'); });

  // Craft Conductor settings → Connections → Remote access & phones → Away from home.
  await page.goto(base + '/#craft-conductor');
  await page.getByRole('button', { name: 'Connections' }).click();
  await page.getByRole('button', { name: /Remote access & phones…/ }).click();
  const dialog = page.locator('#remote');
  const chooser = dialog.getByRole('group', { name: 'Reach the control panel from outside' });
  await chooser.waitFor({ timeout: 20000 });
  assert.equal(await chooser.locator('[data-outside="tailscale"]').getAttribute('aria-pressed'), 'true');   // (pre-selected: private)
  await dialog.getByText('Never:').waitFor();
  assert.match(await dialog.innerText(), /never point a playit\.gg tunnel at it/);
  await dialog.getByRole('button', { name: 'Use Tailscale', exact: true }).click();
  await page.locator('.toast', { hasText: 'Ready: your devices can open https://' + tsName }).waitFor();
  await dialog.getByText('Let the people you invited in, too').click();
  await dialog.getByText('Share just this computer (simplest):').waitFor();

  // Cloudflare: its downsides, then open for 4 hours (asked first), its address, and stop.
  await chooser.locator('[data-outside="cloudflare"]').click();
  assert.equal(await chooser.locator('[data-outside="cloudflare"]').getAttribute('aria-pressed'), 'true');
  await dialog.getByText(/Cloudflare, another company, sits in the middle/).waitFor();
  await dialog.getByText(/cloudflared is Cloudflare's program/).waitFor();
  await dialog.getByRole('button', { name: 'Open to the internet for 4 hours' }).click();
  const q = page.getByRole('alertdialog').filter({ hasText: 'Open the control panel to the internet for 4 hours?' });
  await q.waitFor();
  assert.match(await q.innerText(), /Anyone on the internet who has the address/);
  await q.getByRole('button', { name: 'Open it' }).click();
  await dialog.getByText('https://' + cfName).waitFor({ timeout: 20000 });
  await dialog.getByText(/On the internet until/).waitFor();
  await dialog.getByRole('button', { name: 'Stop now' }).click();
  await page.locator('.toast', { hasText: 'The control panel is off the internet again' }).waitFor();
  await dialog.getByRole('button', { name: 'Close' }).first().click();

  // Advanced: switching a safety rule off asks, then an alert to dismiss; the top of the page says so.
  await page.getByRole('button', { name: 'Advanced' }).click();
  const rule = page.getByLabel(/No limit on wrong passwords and codes/);
  await rule.check();
  const sure = page.getByRole('alertdialog').filter({ hasText: 'Switch this safety rule off?' });
  await sure.waitFor();
  await sure.getByRole('button', { name: 'Switch it off' }).click();
  const alert = page.getByRole('alertdialog').filter({ hasText: 'A safety rule is switched off now' });
  await alert.waitFor();
  await alert.getByRole('button', { name: 'I understand' }).click();
  await page.locator('#health', { hasText: 'A safety rule is switched off:' }).waitFor({ timeout: 20000 });
  await page.reload();   // (the same tab: not asked again once understood)
  await page.locator('#health', { hasText: 'A safety rule is switched off:' }).waitFor({ timeout: 20000 });
  assert.equal(await page.getByRole('alertdialog').filter({ hasText: 'Safety rules are switched off' }).count(), 0);
  await page.getByRole('button', { name: 'Advanced' }).click();
  await page.getByLabel(/No limit on wrong passwords and codes/).uncheck();
  await page.waitForFunction(() => !document.querySelector('#health') || !/safety rule/.test(document.querySelector('#health').innerText), null, { timeout: 20000 });

  // Forgot the password: the code from the file in Craft Conductor's folder.
  await page.context().clearCookies();
  await page.goto(base + '/');
  await page.getByRole('button', { name: 'Reset it to PASSWORD' }).click();
  await page.getByRole('alertdialog').filter({ hasText: 'Go back to the default password' }).getByRole('button', { name: 'Reset' }).click();
  const ask = page.getByRole('alertdialog').filter({ hasText: 'Open this file on this computer' });
  await ask.waitFor();
  const file = (await ask.innerText()).match(/\S*craft-conductor-reset-code\.txt/)[0];
  const code = fs.readFileSync(file, 'utf8').match(/[A-Z0-9]{4}-[A-Z0-9]{4}/)[0];
  await ask.locator('input').fill(code);
  await ask.getByRole('button', { name: 'Reset' }).click();
  await page.locator('.toast', { hasText: 'The password is PASSWORD again' }).waitFor();
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
