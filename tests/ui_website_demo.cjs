// The real control panel in the website's demo (see test_website_browser.py), going through it the way
// a visitor would: making a first server with the real New server page, starting it, a friend joining
// and another asking to join, moderating players, the console, mods (and a mod that can't be added),
// backups and rolling back, updates that work and one that fails and is rolled back, the friends'
// invite, the map preview, settings that stay, people, the phone's notifications, Help and the manual.
// Every page's answers come from the simulation: nothing reaches a network (ui_website_lib.watch).
const { assert, browsers, launch, watch, demoFrame, suite, shot, until } = require('./ui_website_lib.cjs');
const base = process.argv[2];

// Some of the panel's own questions ("Stop the server?"): answered with the button named so.
async function answer(f, label) {
  const button = f.locator('.modal-backdrop button', { hasText: label }).last();
  await button.waitFor({ timeout: 10000 });
  await button.click();
}
async function dismissOffers(f) {  // (the guided setup's offer and the like, when they show)
  await f.waitForTimeout(600);
  for (const label of ['Not now', 'No thanks', 'Skip']) {
    const b = f.locator('.modal-backdrop button, #toasts .sticky button', { hasText: label });
    if (await b.count()) await b.first().click().catch(() => null);
  }
}
// Leftover questions from a step that failed are closed first, so one failure doesn't hide the rest.
async function settle(f) {
  for (let i = 0; i < 4 && await f.locator('.modal-backdrop').count(); i++) await f.locator('.modal-backdrop').last().press('Escape').catch(() => null);
}
// Stop: the panel asks only when players are connected.
async function stopServer(f) {
  await f.locator('#btn-stop').click();
  await f.waitForTimeout(700);
  if (await f.locator('.modal-backdrop button', { hasText: 'Stop' }).count()) await answer(f, 'Stop');
}
const go = async (f, hash) => {
  if (await f.evaluate((h) => location.hash === h, hash)) { await f.evaluate(() => { location.hash = '#servers'; }); await f.waitForTimeout(300); }  // (to draw it again)
  await f.evaluate((h) => { location.hash = h; }, hash); await f.locator('#main').waitFor(); await f.waitForTimeout(500); };
const text = (f, sel = '#main') => f.locator(sel).first().innerText();
const statusOf = (f, sid) => f.evaluate(async (sid) => (await fetch(`/api/servers/${sid}/status`)).json(), sid);
const hub = (f) => f.evaluate(async () => (await fetch('/api/hub')).json());

async function open(browser, scenario, problems, label, viewport = { width: 1440, height: 900 }) {
  const ctx = await browser.newContext({ viewport });
  const page = await ctx.newPage();
  watch(page, base, problems, label);
  await page.goto(`${base}demo/?mode=${scenario}`);
  const f = await demoFrame(page);
  return { ctx, page, f };
}

(async () => {
  const problems = [];
  const t = suite('ui_website_demo');
  for (const name of browsers) {
    const browser = await launch(name);

    // ------------------------------------------------------------ a first server, from nothing
    await t.step(`${name}: Create my first server, start it, and let a friend in`, async () => {
      const { ctx, page, f } = await open(browser, 'new', problems, `${name} first server`);
      t.page = page;
      assert.deepEqual((await hub(f)).servers, [], 'no servers yet');
      assert.match(await f.evaluate(() => location.hash), /^#new$/);
      await dismissOffers(f);
      await f.locator('button.choice', { hasText: 'Lightweight and quick to update' }).click();
      await f.locator('#setup-version').selectOption('1.21.1');
      await f.getByLabel('Server name (shown in the server list)').fill('Family Survival');
      // A mod, through the real mod browser.
      await f.evaluate(() => openBrowser({ target: 'setup', loader: 'fabric', version: '1.21.1' }));
      await f.locator('.result').first().waitFor();
      await until(async () => /sample catalog/i.test(await text(f, 'body')), 'the demo says the catalog is a sample');
      await f.getByRole('checkbox', { name: 'Select Lithium' }).check();
      await f.getByRole('button', { name: 'Add selected mods' }).click();
      await until(async () => /1 mods added/.test(await text(f)), 'Lithium on the setup page');
      assert.deepEqual(await f.evaluate(() => [...setupState.mods.keys()]), ['lithium']);
      await f.getByRole('checkbox', { name: /EULA/ }).check();
      await shot(page, `${name}-new-server-form`);
      await f.getByRole('button', { name: 'Create my server', exact: true }).click();
      await until(async () => /#s\/family-survival\/(setup|dashboard|friends)/.test(await f.evaluate(() => location.hash)), 'the new server');
      await until(async () => !(await statusOf(f, 'family-survival')).setup_pending, 'the server is set up', 20000);
      await go(f, '#s/family-survival/dashboard');
      await shot(page, `${name}-new-server-made`);
      assert.equal((await statusOf(f, 'family-survival')).state, 'stopped');
      await f.locator('#btn-start').click();
      await until(async () => (await statusOf(f, 'family-survival')).state === 'running', 'it starts', 20000);
      await until(async () => /Done \(/.test(await text(f, '.console')), 'the console says it started');
      await until(async () => (await statusOf(f, 'family-survival')).players.includes('Alex'), 'a friend joins', 20000);
      await until(async () => (await hub(f)).servers[0].join_requests === 1, 'a friend asks to join', 25000);
      await until(async () => (await f.locator('.cc-demo-note.push').count()) > 0, 'the phone notification (simulated)');
      await go(f, '#s/family-survival/console');
      await go(f, '#s/family-survival/dashboard');  // (the Dashboard says so when it opens, as in the real app)
      await until(async () => /friend asks to be let in/.test(await text(f)), 'the Dashboard says a friend asks');
      await shot(page, `${name}-join-request`);
      await f.locator('a', { hasText: 'See who' }).click();
      await f.locator('button', { hasText: 'Allow' }).first().click();
      await until(async () => (await statusOf(f, 'family-survival')).players.includes('Sam_Builds'), 'Sam_Builds joins', 15000);
      const h = await hub(f);
      const s = await statusOf(f, 'family-survival');
      assert.equal(h.servers[0].players, s.players.length, 'the server list and the Dashboard agree');
      assert.equal(h.servers[0].join_requests, 0);
      const players = await f.evaluate(async () => (await fetch('/api/servers/family-survival/players')).json());
      assert.ok(players.whitelist.some((x) => x.name === 'Sam_Builds'), 'on the whitelist');
      assert.ok(!players.ops.some((x) => x.name === 'Sam_Builds'), 'letting them in doesn\'t make them an operator');
      await go(f, '#s/family-survival/console');
      await until(async () => /Sam_Builds joined the game/.test(await text(f, '.console')), 'the console shows it');
      // Stop: everyone is disconnected and the counts go to zero.
      await stopServer(f);
      await until(async () => (await statusOf(f, 'family-survival')).state === 'stopped', 'it stops', 15000);
      assert.equal((await hub(f)).servers[0].players, 0, 'nobody is online on a stopped server');
      await ctx.close();
    });


    // ------------------------------------------------------------ an existing server
    const existing = await open(browser, 'existing', problems, `${name} existing server`);
    const { page } = existing;
    t.page = page;
    let f = existing.f;
    const S = 'family-survival';
    const players = () => f.evaluate(async () => (await fetch('/api/servers/family-survival/players')).json());
    const api = (path, body) => f.evaluate(async ([path, body]) => {
      const r = await fetch(path, body === undefined ? {} : { method: 'POST', body: JSON.stringify(body) });
      return { status: r.status, body: await r.json() };
    }, [path, body]);

    await t.step(`${name}: the existing server's Dashboard, and a server that won't start`, async () => {
      await settle(f);
      const s = await statusOf(f, S);
      assert.equal(s.state, 'running');
      assert.deepEqual(s.players, ['Alex', 'KaiCrafts', 'Mia']);
      await until(async () => /3 \/ 20/.test(await text(f, '.cc-telemetry-grid')), 'the resource cards show the players');
      assert.match(await text(f, '.console'), /Done \(/);
      await go(f, '#s/modded-adventure/dashboard');
      await until(async () => /needs BCLib, which isn't installed/.test(await text(f)), 'the problem in plain words');
      await f.getByRole('button', { name: 'Add BCLib' }).click();
      await until(async () => /Added BCLib/.test(await text(f, 'body')), 'the fix');
      await f.locator('#btn-start').click();
      await f.waitForTimeout(400);
      assert.equal(await f.locator('.modal-backdrop').count(), 0, 'both servers fit in memory: no question');
      await until(async () => (await statusOf(f, 'modded-adventure')).state === 'running', 'it starts once BCLib is there', 20000);
      await stopServer(f);
      await until(async () => (await statusOf(f, 'modded-adventure')).state === 'stopped', 'stopped again', 15000);
      await go(f, `#s/${S}/dashboard`);
    });

    await t.step(`${name}: a join request, from the website's demo button`, async () => {
      await settle(f);
      await page.evaluate(() => window.craftDemo.command('join-request'));
      await until(async () => (await hub(f)).servers.find((x) => x.id === S).join_requests === 1, 'the request');
      await go(f, `#s/${S}/players`);
      await until(async () => /Steve_the_Brave/.test(await text(f)), 'the Players page shows it');
      await f.locator('button', { hasText: 'Allow' }).first().click();
      await until(async () => (await statusOf(f, S)).players.includes('Steve_the_Brave'), 'they join', 15000);
      assert.equal((await hub(f)).servers.find((x) => x.id === S).players, (await statusOf(f, S)).players.length);
    });

    await t.step(`${name}: kick, ban, pardon, OP and de-OP`, async () => {
      await settle(f);
      await go(f, `#s/${S}/players`);
      const nameBox = f.locator('input[placeholder="Player name"]').last();
      const act = async (button, who) => {
        await nameBox.fill(who);
        await f.locator('#main button', { hasText: new RegExp(`^${button}$`, 'i') }).first().click();
        if (await f.locator('.modal-backdrop').count()) await f.locator('.modal-backdrop button.primary, .modal-backdrop button.danger').first().click();
        await f.waitForTimeout(700);
      };
      await act('OP', 'Mia');
      await until(async () => (await players()).ops.some((o) => o.name === 'Mia'), 'Mia is an operator');
      await act('DE-OP', 'Mia');
      await until(async () => !(await players()).ops.some((o) => o.name === 'Mia'), 'not any more');
      await act('KICK', 'KaiCrafts');
      await until(async () => !(await statusOf(f, S)).players.includes('KaiCrafts'), 'KaiCrafts is kicked');
      await act('BAN', 'Mia');
      await until(async () => (await players()).bans.some((b) => b.name === 'Mia'), 'Mia is banned');
      assert.ok(!(await statusOf(f, S)).players.includes('Mia'), 'a ban disconnects them');
      await act('PARDON', 'Mia');
      await until(async () => !(await players()).bans.some((b) => b.name === 'Mia'), 'pardoned');
      assert.ok(!(await statusOf(f, S)).players.includes('Mia'), "pardoning doesn't bring them back by itself");
      await go(f, `#s/${S}/console`);
      const log = await text(f, '.console');
      for (const line of ['Made Mia a server operator', 'Kicked KaiCrafts', 'Banned Mia', 'Unbanned Mia']) assert.ok(log.includes(line), line);
      await go(f, `#s/${S}/players`);
      await f.locator('button[data-fkey="wl-toggle"]').click();
      if (await f.evaluate(() => !!(window.CC_DEMO_RELEASE || {}).whitelist_warning)) {
        // (since 0.29: on a server friends reach from outside, the panel asks first)
        await f.locator('.modal-backdrop', { hasText: 'Turn the whitelist off?' }).waitFor();
        await answer(f, 'Keep it on');
        assert.ok((await players()).whitelist_enabled, 'the whitelist is still on');
      } else {
        // (a release from before asks nothing: the whitelist goes off, as it did then; and back on)
        await until(async () => !(await players()).whitelist_enabled, 'the whitelist goes off');
        await f.locator('button[data-fkey="wl-toggle"]', { hasText: /^Turn on$/i }).click();
        await until(async () => (await players()).whitelist_enabled, 'and on again');
      }
    });

    await t.step(`${name}: console commands`, async () => {
      await settle(f);
      await go(f, `#s/${S}/console`);
      const input = f.locator('.console-input input');
      const send = async (cmd, expect) => {
        await input.fill(cmd);
        await input.press('Enter');
        await until(async () => expect.test(await text(f, '.console')), `the answer to ${cmd}`);
      };
      await send('list', /There are \d+ of a max of 20 players online: Alex/);
      await send('say Dinner in 10 minutes!', /\[Server\] Dinner in 10 minutes!/);
      await send('gamerule keepInventory', /Gamerule keepInventory is currently set to: true/);
      await send('whitelist add Steve', /Added Steve to the whitelist/);
      await send('time set night', /Set the time to 13000/);
      await send('fly me to the moon', /Unknown or incomplete command/);
      await shot(page, `${name}-console`);
    });

    await t.step(`${name}: mods: what a mod needs comes along; a mod with no build is refused`, async () => {
      await settle(f);
      await go(f, `#s/${S}/mods`);
      await f.getByRole('button', { name: /Download mods/i }).first().click();
      await f.locator('.result').first().waitFor();
      await shot(page, `${name}-mod-browser`);
      await f.getByRole('checkbox', { name: "Select Biomes O' Plenty" }).check();
      await f.getByRole('button', { name: 'Add selected mods' }).click();
      await until(async () => (await api('/api/servers/family-survival/mods')).body.configured.some((m) => m.name === "Biomes O' Plenty"), 'added');
      const bop = (await api('/api/servers/family-survival/mods')).body.configured.find((m) => m.name === "Biomes O' Plenty");
      assert.deepEqual(bop.deps.map((d) => d.name).sort(), ['GlitchCore', 'TerraBlender'], 'its dependencies come along');
      const refused = await api('/api/servers/family-survival/mods/add', { source: 'modrinth', id: 'create' });
      assert.equal(refused.status, 400);
      assert.match(refused.body.error, /can't add Create/);
      assert.equal((await statusOf(f, S)).minecraft, '1.21.1', 'Minecraft stays on the version chosen');
      await api('/api/servers/family-survival/updates/check', {});
      await until(async () => { const s = await statusOf(f, S); return s.update && !s.update.up_to_date && !s.job; }, 'an update is ready to install them', 15000);
    });

    await t.step(`${name}: Biomes O' Plenty on NeoForge 1.21.4: GlitchCore has no build, and the version stays`, async () => {
      await settle(f);
      const r = await api('/api/hub/mods/requires?id=biomes-o-plenty&loader=neoforge&version=1.21.4');
      assert.equal(r.status, 200);
      assert.equal(r.body.compatible, false);
      assert.match(r.body.reason, /Biomes O' Plenty requires GlitchCore, but no compatible GlitchCore release was found for Minecraft 1\.21\.4 using NeoForge\. Craft Conductor checked Modrinth and CurseForge\./);
      assert.equal(r.body.suggestions[0], '1.21.1', 'it says which version would work');
      await go(f, '#new');
      await f.locator('button.choice', { hasText: 'The modern Forge' }).click();
      await f.locator('#setup-version').selectOption('1.21.4');
      await f.getByRole('button', { name: /Download mods/i }).first().click();
      await f.locator('.result').first().waitFor();
      await f.getByRole('checkbox', { name: "Select Biomes O' Plenty" }).check();
      await until(async () => /GlitchCore/.test(await text(f, 'body')), 'the browser says why');
      await shot(page, `${name}-bop-glitchcore`);
      await page.keyboard.press('Escape');
      assert.equal(await f.locator('#setup-version').inputValue(), '1.21.4', 'the Minecraft version picked is never changed');
    });

    await t.step(`${name}: an update that works`, async () => {
      await settle(f);
      await go(f, `#s/${S}/updates`);
      await until(async () => (await f.locator('button', { hasText: /^Apply update/ }).count()) > 0, 'Apply update');
      await f.locator('button', { hasText: /^Apply update/ }).first().click();
      await f.waitForTimeout(500);
      if (await f.locator('.modal-backdrop').count()) await f.locator('.modal-backdrop button.primary').first().click();
      await until(async () => { const s = await statusOf(f, S); return s.last_job && s.last_job.name === 'update' && !s.job; }, 'the update finishes', 30000);
      const s = await statusOf(f, S);
      assert.ok(s.last_job.ok, s.last_job.message);
      await until(async () => (await statusOf(f, S)).state === 'running', 'running again after the restart', 10000);
      assert.ok((await api('/api/servers/family-survival/mods')).body.installed.some((m) => m.name === 'GlitchCore'), 'the new mods are installed');
      assert.ok((await api('/api/servers/family-survival/backups')).body.backups.some((b) => /before-mod-updates/.test(b.name)), 'a backup was made first');
    });

    await t.step(`${name}: an update that fails is rolled back`, async () => {
      await settle(f);
      assert.equal((await statusOf(f, 'creative-builds')).minecraft, '1.21.1');
      await page.evaluate(() => window.craftDemo.command('fail-next-update', { on: true }));
      await go(f, '#s/creative-builds/updates');
      await until(async () => (await f.locator('button', { hasText: /^Apply update/ }).count()) > 0, 'the update to 1.21.4 is offered');
      await f.locator('button', { hasText: /^Apply update/ }).first().click();
      await f.waitForTimeout(500);
      if (await f.locator('.modal-backdrop').count()) await f.locator('.modal-backdrop button.primary').first().click();
      await until(async () => { const s = await statusOf(f, 'creative-builds'); return s.last_job && s.last_job.name === 'update' && !s.job; }, 'the update finishes', 30000);
      const after = await statusOf(f, 'creative-builds');
      assert.equal(after.last_job.ok, false);
      assert.match(after.last_job.message, /rolled back/);
      assert.equal(after.minecraft, '1.21.1', 'back on the version it was on');
      await shot(page, `${name}-update-failed`);
      await api('/api/servers/creative-builds/updates/apply', {});
      await until(async () => { const s = await statusOf(f, 'creative-builds'); return !s.job && s.minecraft === '1.21.4'; }, 'the next try updates it', 30000);
    });

    await t.step(`${name}: a rehearsal on a copy`, async () => {
      await settle(f);
      await api('/api/servers/family-survival/settings', { mod_channel: 'beta' });  // (Krypton's beta build for 1.21.4 is allowed)
      const lag = (await api('/api/servers/family-survival/updates')).body.check.lagging;
      assert.ok(lag && lag.mods.some((m) => m.name === 'Terralith'), 'Terralith holds 1.21.4 back');
      for (const id of ['terralith', 'biomes-o-plenty']) await api('/api/servers/family-survival/mods/remove', { source: 'modrinth', id });  // (no 1.21.4 build: Terralith, and GlitchCore for Biomes O' Plenty)
      const r = await api('/api/servers/family-survival/updates/rehearsal', { minutes: 1, target: '1.21.4' });
      assert.equal(r.status, 200, JSON.stringify(r.body));
      await go(f, `#s/${S}/updates`);
      await until(async () => { const x = (await api('/api/servers/family-survival/updates/rehearsal')).body; return x.rehearsal && x.rehearsal.state === 'done'; }, 'the rehearsal finishes', 20000);
      const report = (await api('/api/servers/family-survival/updates/rehearsal')).body.report;
      assert.equal(report.verdict, 'bad', "Krypton's beta build doesn't start on the copy");
      assert.equal((await statusOf(f, S)).minecraft, '1.21.1', 'the server itself was never touched');
      await api('/api/servers/family-survival/settings', { mod_channel: 'release' });
    });

    await t.step(`${name}: backups, and rolling back`, async () => {
      await settle(f);
      await go(f, `#s/${S}/backups`);
      await f.locator('#main input').first().fill('before the castle raid');
      await f.getByRole('button', { name: 'Back up now' }).click();
      await until(async () => /before-the-castle-raid/.test(await text(f)), 'the new backup is listed', 15000);
      const listed = (await api('/api/servers/family-survival/backups')).body.backups;
      assert.match(listed[0].name, /before-the-castle-raid\.tar\.gz$/);
      const tooSoon = await api('/api/servers/family-survival/backups/restore', { name: listed[0].name });
      assert.equal(tooSoon.status, 409, 'rolling back needs the server stopped');
      await stopServer(f);
      await until(async () => (await statusOf(f, S)).state === 'stopped', 'stopped', 15000);
      const oldest = listed[listed.length - 1].name;
      await go(f, `#s/${S}/backups`);
      const row = f.locator('#main tr, #main li', { hasText: oldest.slice(0, 15) }).first();
      await row.getByRole('button', { name: 'Roll back to this' }).click();
      await answer(f, 'Roll back');
      await until(async () => { const s = await statusOf(f, S); return s.last_job && s.last_job.name === 'roll back' && !s.job; }, 'rolled back', 15000);
      const mods = (await api('/api/servers/family-survival/mods')).body;
      assert.ok(mods.installed.some((m) => m.name === 'Terralith'), 'Terralith, removed since, is back');
      assert.ok(!mods.installed.some((m) => m.name === 'GlitchCore'), 'the mods added since are gone');
      assert.ok((await api('/api/servers/family-survival/backups')).body.backups.some((b) => /before-rollback/.test(b.name)), 'what was there is kept in a backup');
      await f.locator('#btn-start').click();
      await until(async () => (await statusOf(f, S)).state === 'running', 'started again', 20000);
    });

    await t.step(`${name}: the friends' invite: made-up links, expiry, new links`, async () => {
      await settle(f);
      await go(f, `#s/${S}/friends`);
      const shownLinks = () => f.evaluate(() => [...document.querySelectorAll('#main input')].map((i) => i.value).filter((v) => v.includes('demo.invalid')));
      await until(async () => (await shownLinks()).length > 0, 'the invite links');
      const c = (await api('/api/servers/family-survival/client')).body;
      for (const url of Object.values(c.links)) assert.match(url, /^https:\/\/craft-conductor\.demo\.invalid\/join\/#demo-not-a-real-invite/, 'never a working invite');
      assert.ok(c.expires > Date.now() / 1000, 'they expire');
      await api('/api/servers/family-survival/client', { link_days: 1 });
      assert.ok((await api('/api/servers/family-survival/client')).body.expires - Date.now() / 1000 < 86400 + 60, 'a day from now');
      await api('/api/servers/family-survival/client/stop-link', {});
      const stopped = (await api('/api/servers/family-survival/client')).body;
      assert.ok(stopped.expired && !Object.keys(stopped.links).length, 'stopped links are gone');
      await go(f, `#s/${S}/friends`);
      await until(async () => (await f.locator('button', { hasText: 'Make new links' }).count()) > 0, 'Make new links');
      await f.locator('button', { hasText: 'Make new links' }).first().click();
      await until(async () => (await shownLinks()).length > 0, 'new links');
      await shot(page, `${name}-friends`);
    });

    await t.step(`${name}: the map preview, and points of interest only when asked`, async () => {
      await settle(f);
      await go(f, '#new');
      await f.locator('button.choice', { hasText: 'Lightweight and quick to update' }).click();
      await f.evaluate(() => openWorldPanel());
      await f.getByRole('textbox', { name: 'Seed', exact: true }).fill('8675309');  // (a seed with villages near the spawn)
      await f.locator('button', { hasText: 'Preview map' }).first().click();
      await until(async () => (await f.locator('img.world-map, img.map-tile').count()) > 0 && await f.locator('img.world-map, img.map-tile').first().evaluate((i) => i.complete && i.naturalWidth > 0), 'the map', 25000);
      await shot(page, `${name}-map-preview`);
      assert.equal(await f.locator('.map-mark').count(), 0, 'no landmarks until asked');
      await f.locator('label', { hasText: /Points of Interest/i }).first().click();
      await f.locator('.modal-backdrop', { hasText: 'Show points of interest on the map?' }).waitFor();
      await answer(f, 'Show Points of Interest');
      await until(async () => (await f.locator('.map-mark').count()) > 0, 'landmarks on the map');
      await shot(page, `${name}-map-landmarks`);
      await page.keyboard.press('Escape');
    });

    await t.step(`${name}: settings are kept, in the demo's own storage`, async () => {
      await settle(f);
      await go(f, `#s/${S}/settings`);
      await f.getByLabel('Check every (e.g. 6h, 30m)').fill('12h');
      await f.getByRole('button', { name: 'Save settings' }).first().click();
      await until(async () => (await api('/api/servers/family-survival/settings')).body.check_interval === '12h', 'saved');
      await f.locator('#cc-app-theme [data-theme-toggle]').click();
      const theme = await f.evaluate(() => document.documentElement.dataset.theme);
      await page.waitForTimeout(1200);  // (the demo is saved by the page a moment after a change)
      await page.reload();
      f = await demoFrame(page);
      assert.equal((await api('/api/servers/family-survival/settings')).body.check_interval, '12h', 'still 12h after a reload');
      assert.equal(await f.evaluate(() => document.documentElement.dataset.theme), theme, "the panel's own choice is kept too");
      const stored = await page.evaluate(() => Object.keys(localStorage).filter((k) => k.startsWith('craft-conductor-demo:')));
      assert.ok(stored.length >= 2, "kept under the demo's own names: " + stored);
    });

    await t.step(`${name}: people, phones and notifications`, async () => {
      await settle(f);
      const invite = await api('/api/hub/users/invite', { name: 'Grandpa', grants: { 'family-survival': ['status.view'] } });
      assert.match(invite.body.url, /^https:\/\/craft-conductor\.demo\.invalid\/#invite=DEMO-NOT-A-REAL-INVITE$/);
      assert.match(invite.body.qr, /^<svg/);
      await go(f, '#craft-conductor');
      await f.evaluate(() => openPeople());
      await until(async () => /Grandpa/.test(await text(f, 'body')), 'listed with the others');
      await page.keyboard.press('Escape');
      const sub = await f.evaluate(async () => {
        await Notification.requestPermission();
        const reg = await navigator.serviceWorker.register('/sw.js');
        const s = await reg.pushManager.subscribe({ userVisibleOnly: true });
        const j = s.toJSON();
        await fetch('/api/hub/phone/subscribe', { method: 'POST', body: JSON.stringify({ endpoint: j.endpoint, keys: j.keys, name: 'Test phone' }) });
        const t = await fetch('/api/hub/phone/test', { method: 'POST', body: JSON.stringify({ endpoint: j.endpoint }) });
        return [Notification.permission, t.status, j.endpoint];
      });
      assert.equal(sub[0], 'granted', 'the demo pretends (the browser is never asked)');
      assert.equal(sub[1], 200);
      assert.match(sub[2], /^https:\/\/push\.demo\.invalid\//);
      await until(async () => /Notifications work on this device/.test(await text(f, 'body')), 'the made-up notification shows');
    });

    await t.step(`${name}: Help, the user manual and their pictures`, async () => {
      await settle(f);
      await go(f, '#help');
      await until(async () => (await f.locator('#main img').count()) > 0, 'Help has pictures');
      await f.waitForTimeout(800);
      for (const img of await f.$$('#main img')) await img.scrollIntoViewIfNeeded();
      await f.waitForTimeout(600);
      for (const [src, ok] of await f.$$eval('#main img', (els) => els.map((i) => [i.getAttribute('src'), i.complete && i.naturalWidth > 0]))) assert.ok(ok, `${src} shows`);
      await go(f, '#manual');
      await until(async () => (await f.locator('#main h2, #main h3').count()) > 10, 'the manual is there');
      await shot(page, `${name}-manual`);
      await go(f, `#s/${S}/dashboard`);
      await f.evaluate(() => openHelp('manual'));
      await until(async () => (await f.locator('.help-overlay h2, .help-overlay h3').count()) > 5, 'Help over a page');
      await page.keyboard.press('Escape');
    });

    await t.step(`${name}: what the demo can't do, it explains`, async () => {
      await settle(f);
      const before = await f.locator('.cc-demo-note').count();
      const r = await api('/api/hub/quit', {});
      assert.equal(r.status, 400);
      assert.match(r.body.error, /^Demo: /);
      await until(async () => (await f.locator('.cc-demo-note').count()) > before, 'a note says what would happen');
      await f.evaluate(() => { const a = document.createElement('a'); a.href = '/api/servers/family-survival/doctor/report'; a.download = ''; a.textContent = 'x'; document.body.append(a); a.click(); a.remove(); });
      await until(async () => /has no files to download/.test(await text(f, 'body')), 'the download is explained');
    });
    await existing.ctx.close();
    await browser.close();
  }
  t.done(problems);
})();
