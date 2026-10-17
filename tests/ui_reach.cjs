// The "Friends outside your home" chooser and the whitelist question (see test_ui_reach.py).
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

  // New server: playit.gg is pre-selected, its downsides are said, and the whitelist will be on.
  await page.goto(base + '/#new');
  await page.getByRole('button', { name: /^Vanilla:/ }).click();  // (the rest of the form comes with a server type)
  const playitNew = page.locator('[data-reach="playit"]');
  await playitNew.waitFor({ timeout: 20000 });
  assert.equal(await playitNew.getAttribute('aria-pressed'), 'true');
  await page.getByText('About playit.gg:').first().waitFor();
  await page.getByText('The whitelist will be on').waitFor();
  await page.getByLabel(/Your Minecraft name/).waitFor();
  await page.locator('[data-reach="forward"]').click();
  await page.getByText('Before you open a port:').first().waitFor();
  assert.match(await page.locator('main').innerText(), /Forward TCP port 3\d{4}/);
  await page.locator('[data-reach="home"]').click();
  assert.equal(await page.getByText('The whitelist will be on').count(), 0);

  // A server's Friends page: nothing chosen yet (made before), then playit.gg: its steps, nothing downloaded.
  await page.goto(base + '/#s/alpha/friends');
  const card = page.locator('.card', { hasText: 'Friends outside your home' });
  await card.waitFor({ timeout: 20000 });
  await card.getByText('Not chosen yet').waitFor();
  await card.locator('[data-reach="playit"]').click();
  await page.locator('.toast', { hasText: 'Friends outside join through playit.gg' }).waitFor();
  await card.getByText("Get playit.gg's program.").waitFor();
  await card.getByText('Connect it to a playit.gg account.').waitFor();
  await card.getByText('The whitelist is on').waitFor();  // (reachable now: turned on by itself)

  // Port forwarding: the risks are asked about first, then Craft Conductor picks the port.
  await card.locator('[data-reach="forward"]').click();
  const risks = page.getByRole('alertdialog').filter({ hasText: 'Open a port on your router?' });
  await risks.waitFor();
  assert.match(await risks.innerText(), /griefed/);
  assert.match(await risks.innerText(), /internet address becomes public/);
  await risks.getByRole('button', { name: 'Pick a port' }).click();
  await card.getByText(/Forward TCP port 3\d{4}/).waitFor({ timeout: 20000 });
  assert.equal(await card.locator('[data-reach="forward"]').getAttribute('aria-pressed'), 'true');

  // Turning the whitelist off asks every time: kept on the first time, off the second.
  await page.goto(base + '/#s/alpha/players');
  const toggle = page.locator('[data-fkey="wl-toggle"]');
  await toggle.waitFor({ timeout: 20000 });
  for (const answer of ['Keep it on', 'Turn it off anyway']) {
    await page.locator('[data-fkey="wl-toggle"]', { hasText: 'Turn off' }).click();
    const q = page.getByRole('alertdialog').filter({ hasText: 'Turn the whitelist off?' });
    await q.waitFor();
    assert.match(await q.innerText(), /bots look for Minecraft servers all day/);
    await q.getByRole('button', { name: answer }).click();
    await q.waitFor({ state: 'detached' });
  }
  await page.locator('[data-fkey="wl-toggle"]', { hasText: 'Turn on' }).waitFor({ timeout: 20000 });
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
