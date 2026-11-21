// The Router card says "open to the internet" only once a port is open (see test_ui_router.py).
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
  const login = await page.request.post(base + '/api/login', { data: { password: 'PASSWORD' }, headers: H });
  if (login.status() !== 200) {  // (a later run: the first one set the PIN)
    assert.equal((await page.request.post(base + '/api/login', { data: { password: '2468' }, headers: H })).status(), 200);
  } else {
    assert.equal((await page.request.post(base + '/api/auth/change', { data: { mode: 'pin', secret: '2468' }, headers: H })).status(), 200);
  }
  await page.addInitScript(() => { localStorage.setItem('craft-conductor-sounds', 'off'); });

  await page.goto(base + '/#craft-conductor');
  await page.getByRole('button', { name: 'Connections', exact: true }).click();
  const card = page.locator('#sharing');
  await card.getByText('Open the ports on my router by itself (UPnP)').waitFor({ timeout: 20000 });
  await card.getByRole('button', { name: 'Check again' }).waitFor();
  const text = await card.innerText();
  console.log(JSON.stringify({
    open: text.includes('Your server is open to the internet'),
    nothing: text.includes('Nothing is open on your router now. If it works, this makes your Minecraft server reachable'),
    text,
  }));
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
