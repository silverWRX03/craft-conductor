// Someone invited with Manage mods reaches the hand-download box while setup waits (see test_ui_invited_hand_downloads.py).
const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');
(async () => {
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  const base = process.argv[2];
  const errors = [];
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await context.addInitScript(() => { localStorage.setItem('craft-conductor-sounds', 'off'); });
  const page = await context.newPage();
  page.on('pageerror', (e) => errors.push(e.message));

  await page.goto(base + '/');
  await page.getByRole('button', { name: 'Invited? Sign in with your username' }).click();
  await page.locator('#login-username').fill('sam');
  await page.locator('#login-password').fill('Sam-Strong-Pass-4');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  // Your servers: the server being set up offers See progress.
  const card = page.locator('.server-card').filter({ has: page.getByRole('link', { name: 'See progress' }) });
  await card.waitFor({ timeout: 20000 });
  await card.getByRole('link', { name: 'See progress' }).click();
  // The setup's progress, with the hand-download panel open by itself.
  await page.getByRole('heading', { name: 'Creating your server…' }).waitFor({ timeout: 20000 });
  await page.getByText('Waiting for 1 mod(s) to be downloaded by hand.').waitFor();
  const drop = page.getByRole('button', { name: /Drag mods that were downloaded here/ });
  await drop.waitFor({ timeout: 20000 });
  await page.getByText('Player Animation Library').first().waitFor();
  // The owner's parts aren't there: no Downloads line, no Choose the folder….
  assert.equal(await page.getByRole('button', { name: 'Choose the folder…' }).count(), 0);
  // Any page of that server comes back here while setup waits (not the Dashboard without the box).
  await page.goto(base + '/#s/main/dashboard');
  await page.getByRole('heading', { name: 'Creating your server…' }).waitFor({ timeout: 20000 });
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
