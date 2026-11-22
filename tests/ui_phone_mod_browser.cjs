// The mod browser on a phone (see test_ui_phone_mod_browser.py).
const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');
(async () => {
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  const H = { 'X-CRAFT-CONDUCTOR': '1' };
  const base = process.argv[2];
  const errors = [];
  // A phone: about the S23's screen in Chrome.
  const context = await browser.newContext({ viewport: { width: 390, height: 760 }, isMobile: true, hasTouch: true, reducedMotion: 'reduce' });
  await context.addInitScript(() => { localStorage.setItem('craft-conductor-sounds', 'off'); localStorage.setItem('craft-conductor-phone-banner-plain', String(Date.now() + 1e9)); });
  const page = await context.newPage();
  page.on('pageerror', (e) => errors.push(e.message));
  assert.equal((await page.request.post(base + '/api/login', { data: { password: 'PASSWORD' }, headers: H })).status(), 200);
  assert.equal((await page.request.post(base + '/api/auth/change', { data: { mode: 'pin', secret: '2468' }, headers: H })).status(), 200);

  await page.goto(base + '/#s/alpha/mods');
  await page.getByRole('button', { name: /Download mods/ }).first().click();
  const browse = page.locator('.browse.mod-browser');
  await browse.locator('.browse-results .result').nth(9).waitFor({ timeout: 20000 });
  const box = async (sel) => browse.locator(sel).first().boundingBox();
  const vh = 760;

  // The results get most of the screen (they had about an inch).
  const results = await box('.browse-results');
  assert.ok(results.height > vh * 0.5, `the results are ${Math.round(results.height)} px of ${vh}`);
  // The filters other than the search are folded into Filters.
  await browse.getByText('Filters', { exact: true }).waitFor();
  assert.equal(await browse.getByRole('combobox', { name: 'Sort by' }).isVisible(), false);
  assert.equal(await browse.getByRole('searchbox', { name: 'Search' }).isVisible(), true);
  // The Add selected bar is on the screen, and stays there while the results scroll.
  const footer = await box('.browse-footer');
  assert.ok(footer.y + footer.height <= vh + 1, `the bar ends at ${Math.round(footer.y + footer.height)} of ${vh}`);
  await browse.locator('.browse-results').evaluate((el) => { el.scrollTop = el.scrollHeight; });
  await page.waitForTimeout(300);
  const after = await box('.browse-footer');
  assert.ok(Math.abs(after.y - footer.y) < 2, 'the bar stays at the bottom while the list scrolls');
  // Filters opens them.
  await browse.getByText('Filters', { exact: true }).click();
  await browse.getByRole('combobox', { name: 'Sort by' }).waitFor();
  await browse.getByText('Filters', { exact: true }).click();
  // A mod's page opens over the list, and Back to the list goes back.
  await browse.locator('.browse-results').evaluate((el) => { el.scrollTop = 0; });
  await browse.locator('.browse-results .result', { hasText: 'Mod 1' }).first().locator('.name').click();
  await page.getByRole('heading', { name: 'Mod 1', exact: true }).waitFor({ timeout: 20000 });
  assert.equal(await browse.locator('.browse-results').isVisible(), false);
  const heading = await page.getByRole('heading', { name: 'Mod 1', exact: true }).boundingBox();
  assert.ok(heading.y < vh, 'the mod page is on the screen, not below the list');
  await browse.getByRole('button', { name: '← Back to the list' }).click();
  await browse.locator('.browse-results').waitFor({ state: 'visible' });
  assert.equal(await page.getByRole('heading', { name: 'Mod 1', exact: true }).isVisible(), false);

  // A wide window: no Filters to unfold, the mod's page beside the list (as before).
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.waitForTimeout(300);
  assert.equal(await browse.getByRole('combobox', { name: 'Sort by' }).isVisible(), true);
  assert.equal(await browse.getByRole('button', { name: '← Back to the list' }).count() === 0
    || !(await browse.getByRole('button', { name: '← Back to the list' }).first().isVisible()), true);
  assert.deepEqual(errors, []);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
