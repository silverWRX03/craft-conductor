# The website and its demo

<https://silverwrx03.github.io/craft-conductor/> is published from `site/` by **one** workflow,
`.github/workflows/pages.yml`. It holds:

| Address | What | Source |
|---|---|---|
| `/` | the homepage | `site/index.html`, `site/website.js`, `site/nav.js`, `site/css/website.css` |
| `/demo/` | the phone demo (the QR code opens it; installable) | `site/demo/index.html`, `shell.js`, `shell.css`, `sw.js`, `manifest.webmanifest` |
| `/demo/app/` | the real control panel of a release, with the simulation in front of it | built from the release's `src/craft_conductor/webui/` + `site/demo/app/sim/` |
| `/join/` | the friends' invite page (kept out of search: `noindex`) | `site/join/` |
| `/testing/` | the real-world testing dashboard, with the homepage's sidebar and look, and its data | `site/testing/` (+ `site/nav.js`, `site/css/website.css`) + `tools/real_world_tests.py publish` |
| `/googlef2c4a8b5e575e76a.html` | Google's site verification (unchanged) | `site/` |
| `/sitemap.xml` | the pages for search engines: the homepage and the testing dashboard | `site/sitemap.xml` |

`tools/build_website.py` puts it all together (`_site/`); `tests/test_website.py` checks the result.

**The sidebar** is the same on the homepage and the testing dashboard (`tests/test_website.py` checks
the links match): `site/nav.js` runs it on both, with the Light/Dark switch (remembered for the whole
site) and the ☰ Menu on phones. A link added to one page's sidebar goes in the other's too.

## Homepage appearance and controls

The homepage and testing dashboard use the app's Modern colours: a dark slate background, cyan for
the selected sidebar link, and orange branding. Roboto is served from the website itself, with no
font-service requests. The Light/Dark switch still applies to both pages.

**Download** and **Try the demo** in the sidebar jump to their sections. The homepage no longer
duplicates these controls beside its introduction. The demo's two starting choices and phone QR
code remain in **Try the demo**.

On desktop, Home keeps its approved height and a video window 1.5 times its earlier width and
height. What it does is at least 1.5 times as tall and grows to fit the full-size screenshots.
Narrow screens stack naturally.

The introduction's responsive 16:9 **Product walkthrough** shows the owner's approved video:
https://youtu.be/7facGOmax5M. Press **Watch video · Loads YouTube** to load and play it in place.
Until that press, no player or YouTube requests are made. With JavaScript disabled, a link opens
it on YouTube. The player uses youtube-nocookie.com and supports fullscreen; the homepage's CSP
allows that exact frame origin while scripts, styles and connections remain local. To replace
the video, update the video ID in site/website.js, the fallback link in site/index.html, and the
matching website checks. Browser tests intercept the approved embed to verify activation and CSP
without depending on YouTube availability; actual playback still needs a real-world check.

**What it does** has a centered heading and introduction. It presents the six existing screenshots
in a large carousel, with part of the previous and next pictures blurred beside the current one.
Each title and description stays below its picture.
Previous/next arrows wrap at the ends; dots select a picture directly. With focus inside the
carousel, Left/Right move one picture and Home/End select the first/last. Changes are announced to
screen readers, and inactive pictures are hidden from them. The carousel never advances by itself,
slides pictures in and out when navigating, skips that motion when reduced motion is requested,
and keeps every feature readable as a list when JavaScript is unavailable. Phone controls remain
reachable without sideways page scrolling.

When creating the next release's manual test run, include the website redesign acceptance cases
with `--features 953,954`; automated browser checks and real-device/screen-reader results remain
separate. Record manual results only after performing the cases.

**Search engines:** `sitemap.xml` lists the pages worth finding (the homepage and the testing
dashboard). The demo and the invite page are `noindex`: the invite page is only useful from an invite link. A site
under `/craft-conductor/` can't have the `robots.txt` that would point to it (that would be
`silverwrx03.github.io/robots.txt`), so it's submitted in Google Search Console (Sitemaps), where the
site is verified by `googlef2c4a8b5e575e76a.html`. A page added to the sitemap must exist and not be
`noindex` (the tests check).

## The demo: the real control panel, with made-up data

The demo is Craft Conductor's own control panel, **unchanged**: the release's `index.html`, `app.js`,
`style.css`, `i18n.js`, `rich.js`, `pager.js`, translations, the user manual and its pictures. The build
only rewrites `index.html` so the files are found next to it, adds a Content-Security-Policy, drops the
manifest (the phone demo is the installable one), adds a note on the sign-in page ("no password is
needed"), and loads `site/demo/app/sim/` first. `sim/boot.js` then loads the panel's scripts.

`site/demo/app/sim/` is the simulated backend (all JavaScript, in the visitor's browser):

| File | What |
|---|---|
| `boot.js` | Runs first. Refuses to start outside the website's sandboxed frame. Replaces `fetch`/`XMLHttpRequest` (`/api/...` goes to the simulation; the manual and translations are loaded as scripts made by the build; anything else is refused), `WebSocket`, `EventSource`, `sendBeacon` and the file picker (not available), `<img src="/api/...">` (drawn here: players' faces, maps), links and downloads (explained; outside `https` links open in a new tab), `localStorage` (kept by the website, see below), and the service worker, push, notifications and passkeys (pretend versions that never ask the browser). |
| `core.js` | Routes (`"GET /api/hub"` → a function), errors (`ApiError`, with web.py's `confirm`), the console and events, saving. |
| `catalog.js` | The demo's sample catalog: Minecraft versions, server types, ~25 real mod names with made-up numbers, three made-up modpacks. Clearly a sample: the demo says so wherever mods are browsed. |
| `catalog-release.js` | Made by the build from the release's own Python: setup choices, server settings, permissions, the notice, licenses, guide steps, game rules, safety rules, warnings. |
| `engine.js` | The two starts, a server's life (setting up, starting, running, stopping), jobs (updates, backups, checks), players joining, chatting and asking to join, and the website's demo buttons. |
| `world.js` | Map previews and the explorable map (smooth noise from the seed, landmarks placed from it), single-player games. |
| `routes-hub.js`, `routes-server.js`, `routes-mods.js` | The answers, shaped as `web.py` answers (checked by `tests/test_website_demo_contract.py`). |
| `ui.js`, `demo.css` | The demo's own corner: "Demo · made-up data", a hint for the page on show, explanations, and simulated notifications. |

### The two starts

- **Create my first server**: no servers. The New server page opens; the guided setup is offered.
  Making a server "sets it up" for a few seconds; started, a friend (Alex) joins and another
  (Sam_Builds) asks to join.
- **Explore an existing server**: **Family Survival** (Fabric 1.21.1, 9 friends, 3 online, two mod
  updates ready, Minecraft 1.21.4 waiting on Terralith and Krypton, four backups, an invite link),
  **Creative builds** (stopped; follows new Minecraft, so an update to 1.21.4 is ready) and **Modded
  adventure** (won't start: Better End needs BCLib; the Dashboard offers to add it). People Alex,
  Jordan and Sam are invited, and there's a modded single-player game. A friend asks to join about
  45 seconds in.

**Reset demo** (the website and the phone demo) forgets both demos and starts again.

### What happens, and stays consistent

One state drives every page: the Dashboard's counts, the Players page, the console, the events, the
server list and the notifications all show the same thing. Examples the browser tests go through:
starting writes the console and lets friends in; a stopped server has nobody online; letting someone
in whitelists them (never OP) and they join; a ban disconnects; a pardon doesn't bring them back;
adding a mod brings what it needs, and is installed by an update that backs up first and restarts the
server; an update that fails to start is rolled back from that backup; rolling back needs the server
stopped and keeps what was there in a new backup; invite links expire, stop and are made again.

**Mods that can't be added are refused with the reason, and the server's Minecraft never changes to
make one fit.** Biomes O' Plenty on NeoForge 1.21.4: "Biomes O' Plenty requires GlitchCore, but no
compatible GlitchCore release was found for Minecraft 1.21.4 using NeoForge. Craft Conductor checked
Modrinth and CurseForge.", with the version that would work (1.21.1) suggested, never chosen.

Failures to see: a server that won't start (Modded adventure), a mod with no build (Create on
Fabric), early (alpha/beta) builds (Krypton, Distant Horizons), an update that fails (the website's
**Next update fails** switch, or an early build on a new Minecraft), a rehearsal on a copy that
fails, a missing dependency found by the file check (Better End without BCLib).

### Screen by screen

"Simulated" = it does what the real one does, with made-up data. "Explained" = the visitor is told
what the real app would do, because the demo can't (it would need their computer, network or an
outside service). Every address the panel calls is answered: an unknown one says "isn't simulated"
(never silently), and fails the tests.

| Page | Simulated | Explained |
|---|---|---|
| Servers | the list, start/stop/open/delete, memory given to running servers, single-player games (make, edit, check, delete), import (the file's name only) | unpacking an imported server, Install into a launcher |
| New server | quick starts, server types, Minecraft versions (betas too), mods and modpacks through the real mod browser, dependencies, compatibility, the file check, friends' mods, the world settings, map preview, seed gallery, the port and memory checks, Create my server, the set-up progress | Run on another computer (SSH) |
| Dashboard | resources, live console, connected players (kick, whitelist, broadcast), runtime, update status, events, performance and its graph, the lag finder (a made-up report), a failed start with its fix, Check my setup | spark's upload, Test from the internet (nothing is sent) |
| Console | the console, and a stand-in Minecraft that answers list, say, tell, whitelist, op/deop, kick, ban/pardon, gamerule, time, weather, difficulty, gamemode, tp, give, seed, worldborder, tick query, save-all, stop, chunky; anything else gets Minecraft's "Unknown or incomplete command" | |
| Players | online, operators, whitelist, bans, IP bans, join requests (Allow/Ignore), activity over 30 days, the whitelist-off warning | |
| Updates | update checks, readiness per mod (green/yellow/red), mod updates, a new Minecraft, Remove and update, rehearsals on a copy, updates that fail and roll back, betas on a copy | manual downloads (CurseForge files) |
| Mods | the list, dependencies, required/optional, Change version (held builds), remove, the mod browser, quick add, the file check, config files (made-up, editable), saved mod lists, local `.jar` files (the name only: the file isn't read) | loading a mod list from a file |
| Friends | how friends outside join (playit.gg, a port on the router, only at home), the invite links (made up: `https://craft-conductor.demo.invalid/...`), their duration, Stop / New links, friends' mods, Bedrock (Geyser) | installing playit.gg, posting to Discord |
| Backups | back up now (with a label), check, roll back, put an area back, what changed, what backups hold, how many to keep | Backups folder, export/download files |
| Java | the server's Java, shared Java, install/update/remove a version, "Run the server on", Java found on the computer (made up) | |
| Settings | every setting saved and kept (validated like the real one), server properties, schedules, Aikar's flags, world tools (game rules, border, Chunky), web map (BlueMap) | Discord webhook (never kept) |
| Craft Conductor settings | appearance (kept), sounds & notifications (simulated notifications, the phone app with a made-up push address), sign-in & security (password and PIN, passkeys: no real ones are made, people and what they may do, invite links made up), connections (remote access, pairing a phone with a made-up code, Tailscale, Router UPnP, CurseForge key, safety rules), about & updates (the version the demo shows) | Cloudflare tunnel, installing an HTTPS certificate, Discord bot, Quit, Craft Conductor's own update |
| Help, User manual | the release's own, with its pictures | |

### Where the state is kept

The panel's frame can't keep anything (its origin is its own, with no storage). It sends its state to
the website, which keeps it in this browser's `localStorage` under `craft-conductor-demo:v1:` (one
for each start, and the panel's own settings like day/night). Nothing leaves the device: two devices
(or browsers) each have their own demo, and there's no server to synchronise them. A saved demo from
an older version of the simulation starts afresh. Reset demo forgets it.

## Security

The site is public, and shares its origin (`silverwrx03.github.io`) with the invite page, the testing
dashboard and the owner's other Pages sites. Decisions:

- **The control panel runs in a sandboxed frame WITHOUT `allow-same-origin`** (`sandbox="allow-scripts
  allow-forms allow-popups allow-popups-to-escape-sandbox"`). With `allow-same-origin` it would run
  with the site's origin: a bug in the panel's 9,000 lines, or in the simulation, could read or change
  the website, the invite page or their storage. Without it, the frame's origin is opaque: it can't
  reach the website's pages, storage or cookies, and can only send messages. `allow-popups(-to-escape-sandbox)`
  lets the real app's outside links (Modrinth, playit.gg, the wiki) open in a new tab; there is no
  `allow-top-navigation`, `allow-modals` or `allow-downloads`.
- **The panel's page has a Content-Security-Policy that allows no connections at all**
  (`connect-src 'none'`, `default-src 'none'`, scripts, styles and pictures from the site only). So
  even code that went around the simulation couldn't reach the network: no `fetch`, XHR, WebSocket,
  EventSource or beacon. The manual and translations are delivered as scripts for this reason.
- **The panel refuses to start outside that frame** (`self.origin` must be `"null"` and it must be
  framed): opened on its own at `/demo/app/`, the real scripts never load.
- **Messages:** the website only listens to its own frame's window, from an opaque origin, carrying
  this load's random session token (a frame it replaced can't write a saved state back after a
  reset); the frame only talks to its parent at the site's origin, and ignores messages from anyone
  else. Saved data is checked (only strings, size-limited) and only ever shown as text.
- **Clipboard:** the frame may write to the clipboard (`allow="clipboard-write"`), so the panel's Copy
  buttons work; what they copy is the demo's made-up text. Reading the clipboard isn't allowed.
- **What remains:** a sandboxed frame can still load another address into itself. The demo's links
  never do that (outside links open in a new tab, the site's own are explained), but a page that got
  there would only see and change the visitor's own made-up demo, never the website or its storage.
  GitHub Pages can't send headers, so the site can't forbid being framed by another site
  (`frame-ancestors`); nothing on it acts on the visitor's behalf, so that only matters for appearances.
- **No real credentials:** the demo is signed in as the owner; the sign-in page (after Sign out) says
  no password is needed. Passwords, PINs, keys and tokens typed into the demo are never kept or
  sent (`/api/login`, `/api/auth/change`, CurseForge, Discord, webhooks). Passkeys are made up (the
  browser's own prompt never shows), notifications are shown inside the page (the browser is never
  asked for permission), and push addresses are `https://push.demo.invalid/...`.
- **Made-up links can't be mistaken for real ones:** invites, people's invite links and pairing codes
  are `https://craft-conductor.demo.invalid/...` (`.invalid` never resolves) and say
  "demo-not-a-real-invite"; addresses are 192.168.1.50 and 203.0.113.25 (a documentation address).
  An address with `#invite=` or `#pair=` is cleared before the panel starts.
- **Files:** an uploaded `.jar` or `.zip` never leaves the browser and isn't read (only its name and
  size). Downloads are explained, not served.
- **No analytics:** the homepage and demo load only the site's own files until a visitor chooses
  the YouTube walkthrough. That player can contact YouTube and its media services after activation.
  The demo remains isolated with no outside requests. Tests fail on unexpected outside requests
  or any `/api/` request that reaches the network; the video activation check permits only the
  exact approved embed and intercepts it locally.
- **Service worker:** only the phone demo registers one, `demo/sw.js`, with scope `demo/`: it can't
  see the homepage, the invite page or the testing dashboard (it also leaves `demo/app/` alone).
  Network first, so a new release shows as soon as it's online.

## Publishing: the newest published release, checked first

Before installing browser-test dependencies, the Ubuntu runner replaces its slow Azure HTTP
package mirror with Ubuntu's official HTTPS archive when the mirror-list file exists. Package
signature verification and every website/browser test still run; no validation is skipped.

`pages.yml` runs after each release (release.yml calls it once the downloads exist; a release
published by hand sends `release: published`), on main when the website or testing records change,
and by hand. It calls `website-build.yml`, which:

1. checks the real-world testing records, the website, the release policy and the simulation
   against the real API (`tests/test_website*.py`, `tests/test_website_demo_contract.py`);
2. runs the browser tests (Chromium, Firefox, WebKit) on this checkout's control panel;
3. picks the release (`tools/select_website_release.py`, the policy below), fetches its tag and
   extracts its `src/` exactly as tagged;
4. checks the simulation answers every address that release's panel calls (`tools/check_demo_contract.py`);
5. runs the browser tests again with that release's control panel;
6. builds `_site/` from it, checks every homepage download link is a file of that release, and
   uploads it (and the screenshots, as artifacts).

Only then does `pages.yml`'s deploy job publish. Any failure stops it: the live site, demo and all,
stays as it was, the run fails (GitHub emails the owner), its summary says it wasn't published, and
an issue **"Website not published"** is opened with the run's link (a later failure comments on the
same issue; the next run that publishes closes it). release.yml's call to pages.yml grants
`issues: write` for this.
`website-preview-validation.yml` does the same for pull requests, without publishing (the
`website-candidate` artifact is the site as it would be).

The homepage shows the release the demo follows ("Demo: 0.28.0 · beta") from `demo/version.json`.

### Beta and stable, and switching to stable only

A release is a **beta** when GitHub marks it as a pre-release **or** its title says "(beta)" (release.yml
titles every release "Craft Conductor vX.Y.Z (beta)" for now). `.github/demo-release-policy.json`:

- `"channel": "beta-and-stable"` (now): the newest published release, whichever it is.
- `"channel": "stable"`: only releases that are neither; a newer beta never replaces the stable one.

To switch, when the first stable release is out: change release.yml's release title so a stable
release isn't titled "(beta)", set `"channel": "stable"`, and merge. If no stable release exists yet,
the build fails with "every release so far is a beta" and nothing is published (the site stays as it was).

## When the control panel changes

- **A new page or API route:** `tests/test_website_demo_contract.py` fails (an address isn't simulated,
  or a real route has no simulated one). Add it to `site/demo/app/sim/routes-*.js`, shaped like web.py's
  answer, with state in `engine.js` if it changes something. Things the demo can't do: `throw
  sim.explain("what Craft Conductor would do")`.
- **A new field in an answer:** the same test lists it ("missing in the demo's answer").
- **New words on a page:** nothing to do (the panel is the release's own).
- **A release's panel calls something new before main's simulation knows it:** the Pages build stops
  at step 4 and the live site keeps the previous release's demo until the simulation catches up.
- **The browser tests** (`tests/ui_website*.cjs`) go through the pages by their buttons; a renamed
  button fails them with the step and a screenshot (artifact `website-screenshots`).

Run the tests locally (Node and Playwright, like the other UI tests):

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> pytest tests/test_website*.py
    CRAFT_UI_BROWSERS=chromium,firefox,webkit ...   # (Chromium only by default)

## What the demo can't show

- Anything that needs the visitor's computer, network or an outside service is explained instead:
  the files on the computer, Java and Minecraft actually running, routers, firewalls, tunnels,
  Discord, Craft Conductor's own updates, installing into a launcher, downloads.
- The mod catalog is a fixed sample (real mod names, made-up numbers and builds), not Modrinth or
  CurseForge today; maps are made-up worlds, not Minecraft's generator.
- One computer's demo isn't seen on another (no backend; by design).
- The walkthrough is a recorded video, separate from the interactive demo.
