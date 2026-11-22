// A device's notifications follow whoever is signed in (see test_ui_push_sync.py).
const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');
(async () => {
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  const [base, endpoint, p256dh, auth] = process.argv.slice(2);
  const H = { 'X-CRAFT-CONDUCTOR': '1' };
  const errors = [];
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  // The browser's push service, as a stand-in: notifications allowed, and a subscription it kept.
  await context.addInitScript(({ endpoint, p256dh, auth }) => {
    localStorage.setItem('craft-conductor-sounds', 'off');
    Object.defineProperty(Notification, 'permission', { get: () => 'granted' });
    Notification.requestPermission = async () => 'granted';
    const sub = { endpoint, options: { applicationServerKey: null }, toJSON: () => ({ endpoint, keys: { p256dh, auth } }),
      unsubscribe: async () => true };
    const reg = { pushManager: { getSubscription: async () => sub, subscribe: async () => sub } };
    navigator.serviceWorker.getRegistration = async () => reg;
    navigator.serviceWorker.register = async () => reg;
    Object.defineProperty(navigator.serviceWorker, 'ready', { get: () => Promise.resolve(reg) });
  }, { endpoint, p256dh, auth });
  const page = await context.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  const subscribed = [];
  page.on('request', (r) => { if (r.url().endsWith('/api/hub/phone/subscribe')) subscribed.push(r.url()); });

  // The owner signs in on the device that was Sam's: it's turned on for them, by itself.
  assert.equal((await page.request.post(base + '/api/login', { data: { password: 'PASSWORD' }, headers: H })).status(), 200);
  assert.equal((await page.request.post(base + '/api/auth/change', { data: { mode: 'password', secret: 'Owner-Strong-Pass-1' }, headers: H })).status(), 200);
  await page.goto(base + '/#craft-conductor');
  const deadline = Date.now() + 20000;
  while (!subscribed.length && Date.now() < deadline) await page.waitForTimeout(200);
  assert.equal(subscribed.length, 1, 'the device was turned on again for the owner');
  await page.waitForTimeout(500);
  const who = await page.evaluate(async () => (await (await fetch('/api/hub/phone', { headers: { 'X-CRAFT-CONDUCTOR': '1' } })).json()).devices.length);
  console.log(`turned on: owner (${who} device)`);
  // The Phone app card says it's on (it's the owner's now).
  await page.getByRole('button', { name: 'Connections', exact: true }).click();
  const card = page.locator('.card', { has: page.getByRole('heading', { name: 'Phone app', exact: true }) });
  await card.getByText('✓ Notifications are on for this device.').waitFor({ timeout: 20000 }).catch(async (e) => {
    throw new Error(e.message + ' | ' + await card.innerText().catch(() => 'no Phone app card'));
  });
  // Sign out: the device stops getting the owner's notifications.
  await page.locator('#logout').click();
  await page.locator('#login').waitFor({ state: 'visible', timeout: 20000 });
  await page.waitForTimeout(500);
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
