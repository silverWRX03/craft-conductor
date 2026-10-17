# Craft Conductor project website and interactive demo

The project site is served from **`site/`** on GitHub Pages:
- `/`: the Craft Conductor project homepage (replaces the old dashboard design preview).
- `/demo/`: the real frontend's static, safely simulated demonstration.
- `/testing/`: the independent **real-world test tracker**, retaining its versioned source data.
- `/join/`: existing invitations and friend download flow.
- `/googlef2c4a8b5e575e76a.html`: search verification; must never be deleted.

The site uses the same GitHub Pages project root at
`https://silverwrx03.github.io/craft-conductor/`. **All paths above are relative to that project root.**

## Source of truth and build

- `src/craft_conductor/webui/` is the authentic application UI.
- `tools/build_public_site.py` copies the real HTML, CSS, JS, manual, translations and images into an isolated `_site/demo/` with a web-safe mock adapter.
- `site/demo/demo-runtime.js` implements simulated API responses. No Minecraft servers, external services, SSH, firewall updates, or actual mod downloads run in the demo.
- The actual application worker is removed in the demo build. The standalone phone demo uses its own worker and manifest scoped exclusively to `/craft-conductor/demo/`, without push, caching or network interception.
- The demo uses a curated fake server with fictional player activity and also supports a fresh first-server workflow. Local fake state is session-scoped; mobile and desktop demonstrations have distinct storage keys. **A physical phone never syncs with the desktop.**
- The `/testing/` data are regenerated using `tools/real_world_tests.py publish`, which excludes raw evidence, tester identities, notes and machine-specific details.
- The existing invitation page and Google verification file must always be packaged with the rest of the site.

## Publishing release policy

`site/demo-channel.json` contains `release_channel`:

- `"all"` (**current**): Latest published release, including beta and stable.
- `"stable"`: Latest published stable release only. Treat release names labeled beta as beta **even if GitHub's prerelease flag is false**.

Change the channel to `stable` **only after project owner approval**, once the first stable release is ready.

`.github/workflows/pages.yml` is the **only** GitHub Pages publisher. It fetches the latest eligible published release's source tag, packages that release's UI with the current website, runs static checks and Playwright browser tests, and only then deploys the entire site artifact. Build/test failures must leave the previous Pages deployment untouched.

The existing release workflow calls Pages after creating a published release; changes to site and tracker data on `main` can also trigger a complete re-deployment. Every deployment rebuilds the entire website, never one subdirectory by itself. This preserves `/testing/` and `/join/`.

`.github/workflows/site-demo-check.yml` validates pull requests, frontend changes on `main` and scheduled daily drift checks. It builds against both the current UI and the newest published release and attaches screenshots and route-coverage metadata for reviewer inspection.

## Local validation

From the repository root, with Python 3.12+, Node.js and npm:

```sh
python -m pip install "qrcode==8.2"
npm install --prefix .site-test --no-save "playwright@1.56.1"
.site-test/node_modules/.bin/playwright install chromium
python tools/build_public_site.py --output _site --version local-check
python -m unittest discover -s tests -p test_public_site.py
node --check _site/demo/app.js
node --check _site/demo/demo-runtime.js
node tools/smoke_public_site.cjs
```

For Windows PowerShell, use ` .site-test\\node_modules\\.bin\\playwright.cmd install chromium` if the Unix command isn't available.

The browser test uses a small local HTTP server that reproduces GitHub Pages' `/craft-conductor/` subpath and covers the website, slide-out, both demo entry paths, navigation, and mobile QR access.

## Security and known simulation limits

- The **demo is public marketing material, not a remotely hosted server manager**. The frontend's built-in API requests are intercepted by fake responses and never forwarded to a real instance. External fetches are blocked.
- Never put real API credentials, personal data, server IP addresses, console secrets or real connection tokens into the static site. All player names and metrics must be fictional.
- Authentication, permissions, real Minecraft installation, network port forwarding, remote access, OS filesystem operations, Java downloads, external mod catalogs, Discord setup, push delivery and software updates cannot run for real on GitHub Pages. They must be clearly simulated or explained, not represented as operational.
- The demonstration's `coverage.json` identifies screens with partial mock contracts. Passing the smoke test confirms that primary screens render and selected flows work; **it does not certify every nested control or advanced workflow as fully simulated**.
- If production API response shapes or UI route names change, update the adapter and test fixtures in the same change. Prefer adding Playwright assertions for representative interactions. Do not relax tests to conceal broken screens.
- A proposed demo update that fails validation must not be deployed. Review failed CI logs and the screenshot/coverage artifact before changing fixtures.

## Release checklist

1. Validate current and published-release UI with static and browser tests.
2. Check new screens and nested panels against `coverage.json`; increase functional test coverage as the product changes.
3. Confirm the dark default, light/dark toggle, desktop and mobile navigation, and the persistent left Leave Demo control.
4. Verify the fake server, player whitelist requests, console updates, backups, mods and QR/mobile demo work as advertised.
5. Confirm `/join/` and `/testing/` retain their own existing behaviors and public test history.
6. Confirm public-demo service worker scope and that no real API or external privileged action is reached.
7. Review the entire pull request, then merge only with owner approval.

