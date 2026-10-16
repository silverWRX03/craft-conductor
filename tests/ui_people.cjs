// Inviting someone, and what they see once signed in (see test_ui_people.py).
const { chromium } = require(process.env.CRAFT_UI_PLAYWRIGHT);
const assert = require('node:assert/strict');
(async () => {
  const channel = process.env.CRAFT_UI_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
  const browser = await chromium.launch({ headless: true, ...(channel ? { channel } : {}) });
  const base = process.argv[2];
  const H = { 'X-CRAFT-CONDUCTOR': '1' };
  const errors = [];
  const open = async () => {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await context.addInitScript(() => { localStorage.setItem('craft-conductor-sounds', 'off'); });
    const page = await context.newPage();
    page.on('pageerror', (e) => errors.push(e.message));
    return page;
  };

  // The owner: a strong password, then People… → Invite someone.
  const owner = await open();
  assert.equal((await owner.request.post(base + '/api/login', { data: { password: 'PASSWORD' }, headers: H })).status(), 200);
  assert.equal((await owner.request.post(base + '/api/auth/change', { data: { mode: 'password', secret: 'Owner-Strong-Pass-1' }, headers: H })).status(), 200);
  await owner.goto(base + '/#craft-conductor');
  await owner.getByRole('button', { name: 'Sign-in & security' }).click();
  await owner.getByRole('button', { name: 'People…' }).click();
  await owner.locator('#people li', { hasText: 'Morgan' }).waitFor();
  await owner.getByRole('button', { name: 'Invite someone' }).click();
  const form = owner.locator('#person');
  await form.getByRole('textbox', { name: 'Their name' }).fill('Riley');
  const alpha = form.locator('.grant-row', { hasText: 'Alpha' });
  await alpha.getByRole('checkbox', { name: 'Give access to Alpha' }).check();
  assert.equal(await alpha.getByRole('combobox').inputValue(), 'viewer', 'a new person starts as a Viewer');
  await alpha.getByRole('combobox').selectOption('moderator');
  assert.match(await alpha.locator('.grant-summary').innerText(), /manages players/);
  // A risky permission says why once ticked, and the role becomes Custom; unticking puts it back.
  await alpha.getByText('Customize permissions').click();
  const consoleBox = alpha.locator('label.cap', { hasText: 'Type console commands' }).getByRole('checkbox');
  await consoleBox.check();
  assert.equal(await alpha.getByRole('combobox').inputValue(), 'custom');
  await alpha.locator('.notice.warn', { hasText: 'reach files on this computer' }).waitFor();
  assert.ok(await alpha.locator('label.cap', { hasText: 'Read the console' }).getByRole('checkbox').isChecked(), 'typing commands needs the console');
  await consoleBox.uncheck();
  await alpha.locator('label.cap', { hasText: 'Read the console' }).getByRole('checkbox').uncheck();
  assert.equal(await alpha.getByRole('combobox').inputValue(), 'moderator');
  assert.equal(await alpha.locator('.notice.warn').count(), 0);
  await form.getByRole('button', { name: 'Make the invite link' }).click();
  const linkBox = owner.locator('#person-link');
  await linkBox.waitFor();
  const link = await linkBox.getByLabel('The link').inputValue();
  assert.match(link, /#invite=/);
  await linkBox.getByRole('button', { name: 'Close' }).click();
  await owner.locator('#people li', { hasText: 'Riley' }).getByText('invite not used yet').waitFor();

  // Riley opens the link in their own browser, and chooses a username and password.
  const riley = await open();
  await riley.goto(base + '/#invite=' + link.split('#invite=')[1]);
  const welcome = riley.locator('#pairing');
  await welcome.getByRole('heading', { name: 'Welcome, Riley' }).waitFor();
  await welcome.getByRole('textbox', { name: 'Username' }).fill('riley');
  await welcome.getByRole('textbox', { name: 'Password', exact: true }).fill('Riley-Strong-Pass-2');
  await welcome.getByRole('textbox', { name: 'Repeat it' }).fill('Riley-Strong-Pass-2');
  await welcome.getByRole('button', { name: 'Create my sign-in' }).click();
  // Only their server, without folders or buttons they can't use; the menu has only their pages.
  const card = riley.locator('.server-card', { hasText: 'Alpha' });
  await card.waitFor();
  assert.equal(await riley.locator('.server-card').count(), 1, 'only the servers they were given');
  assert.equal(await card.getByRole('button', { name: 'Start' }).count(), 0, 'a moderator has no Start');
  assert.equal(await card.locator('.folder').count(), 0);
  assert.equal(await riley.locator('#nav').getByText('New server').count(), 0);
  await card.getByRole('link', { name: 'Open' }).click();
  await riley.locator('#nav').getByText('Players', { exact: true }).waitFor();
  const nav = await riley.locator('#nav').innerText();
  for (const page of ['Console', 'Mods', 'Backups', 'Java', 'Settings', 'Friends']) assert.ok(!nav.includes(page), page);
  assert.match(nav, /Riley/);
  assert.ok(!(await riley.locator('#btn-start').isVisible()), 'no Start for a moderator');
  await riley.waitForTimeout(2500);   // (a few rounds of the Dashboard's polling: none of it refused, see test_ui_people.py)
  await riley.locator('#nav').getByText('Players', { exact: true }).click();
  await riley.getByRole('heading', { name: 'Players' }).first().waitFor();
  await riley.waitForTimeout(1500);
  // A page they can't use, typed in: the Dashboard instead (and the server refuses it anyway).
  await riley.goto(base + '/#s/alpha/console');
  await riley.waitForFunction(() => location.hash === '#s/alpha/console' && document.title.startsWith('Dashboard'));
  assert.equal((await riley.request.get(base + '/api/servers/alpha/console?since=0')).status(), 403);
  assert.equal((await riley.request.get(base + '/api/servers/main/status')).status(), 404);
  // Their own settings: Your account, and nothing of the owner's.
  await riley.goto(base + '/#craft-conductor');
  await riley.getByRole('heading', { name: 'Your account' }).first().waitFor();
  assert.equal(await riley.getByText('Remote access & phones').count(), 0);

  // The owner's list now shows their username and what they may do. (Removing someone: test_access.py.)
  await owner.locator('#people').getByRole('button', { name: 'Close' }).click();
  await owner.getByRole('button', { name: 'People…' }).click();
  const row = owner.locator('#people li', { hasText: '(riley)' });
  await row.waitFor();
  assert.match(await row.innerText(), /Alpha: Moderator/);
  assert.equal((await riley.request.get(base + '/api/hub')).status(), 200);
  // Morgan, a Manager, signs in with the form (username and password), and opens every page in the menu.
  const morgan = await open();
  await morgan.goto(base + '/');
  await morgan.getByRole('button', { name: 'Invited? Sign in with your username' }).click();
  await morgan.locator('#login-username').fill('morgan');
  await morgan.locator('#login-password').fill('Morgan-Strong-Pass-3');
  await morgan.getByRole('button', { name: 'Sign in', exact: true }).click();
  await morgan.locator('.server-card', { hasText: 'Alpha' }).getByRole('link', { name: 'Open' }).click();
  await morgan.locator('#nav').getByText('Settings', { exact: true }).waitFor();
  const pages = await morgan.locator('#nav a[href^="#s/alpha/"]').evaluateAll((as) => as.map((a) => a.getAttribute('href')));
  assert.deepEqual(pages.map((x) => x.split('/').pop()).sort(), ['console', 'dashboard', 'mods', 'players', 'settings', 'updates', 'backups'].sort());
  for (const href of pages) {
    await morgan.goto(base + '/' + href);
    await morgan.waitForTimeout(1500);
  }
  assert.equal(await morgan.locator('.console-input').count(), 0, 'no command box without "Type console commands"');
  // The next time, this device remembers to ask for the username.
  await morgan.request.post(base + '/api/logout', { headers: H });
  await morgan.goto(base + '/');
  await morgan.locator('#login-username').waitFor({ state: 'visible' });
  assert.deepEqual(errors, []);
  await browser.close();
  console.log('OK');
})().catch((e) => { console.error(e); process.exit(1); });
