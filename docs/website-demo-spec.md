# Craft Conductor website and public interactive demo

Status: implementation in progress. Do not merge the website until the production-front-end simulator and checks below are complete.

## Product decisions
- Project homepage at /craft-conductor/ with left navigation and default Obsidian dark theme, plus a light-mode toggle.
- Launch demo from the homepage; blur website; slide application from the right; persistent Leave Demo rail on left.
- Start with two options: Create My First Server and Explore an Existing Server.
- Reuse actual source in `src/craft_conductor/webui/` wherever feasible; simulated API only. No real privileged operations, live backend, downloads, uploads, QR pairing, telemetry or network setup.
- Standalone mobile demo with an independent browser-local state, not synchronized between devices. Click desktop QR for mobile preview; scan on physical phone to visit the demo URL.
- Public demo follows published releases, beta and stable for now; change to stable-only when owner elects to transition.
- Video is a future feature, not phase-one.
- Keep `site/testing/`, generated `_site/testing/data/`, `site/join/` and Google ownership verification at their existing paths.

## Actual navigation (from production app.js)
Global views: servers, new/setup, help, manual, craft-conductor. Separate mod browser: browse.
Server views: dashboard, console, players, updates, mods, friends, backups, java, settings.
Nested: mod browser and manager, world/map, single-player, friend setup, update rehearsals, connected players, QR/phone, permissions, notifications, setup guide and application updates.

## Screen-to-simulation matrix
| Production screen | Required fixture state | Supported demo actions |
|---|---|---|
| Servers | 0 or 1+ fictional servers, memory budget, fictional single-player games | Create, open, start, delete, import demo record, switch |
| New server / setup | loader/version catalog, simulated dependencies, fake ports and memory | Choose quick start, version, mods, options, test, create, progress |
| Dashboard | server state, clock, fake metrics, connected players, logs | Start, stop, restart, inspect metrics, whitelist, diagnosis |
| Console | event log and supported commands | help, list, say, whitelist, stop/restart transitions; unsupported commands explain |
| Players | online/known/requested/banned/op lists | Allow/ignore, whitelist toggle, kick, ban/pardon, op/deop |
| Updates | compatibility statuses, pending mod/Minecraft releases, backups | Check, explain blockers, rehearse, update, fail/rollback |
| Mods | local fixture catalog and modpack contents | Browse, filter, select, dependencies, remove, pin/change versions, configs |
| Friends | fake invitation, firewall/router state, friend mod selection | Generate demo invite, demonstrate join and connection diagnostics |
| Backups | records, retention and schedule | Create, restore, delete, edit schedule |
| Java | installed Java runtimes and required version | Choose runtime, simulate install/update |
| Settings | persisted per-server properties and validation | Save, cancel, unsaved changes, version policy |
| Craft Conductor settings | appearance, notifications, identity, connections, about | Changes to local demo settings, dialogs for unsafe/external actions |
| Help / manual | production help and manual | Navigate, search, open images, close without losing form state |
| Single-player | fake modded game records | Create, edit, change mods, simulate launcher install |
| World/map | representative map image/data and overlays | Navigate, toggle points-of-interest with the proper disclosure |
| Phone/PWA | browser-only demo state; genuine QR URL to website demo | View responsive app, simulated alerts; no real push subscription |

## Consistency and safety invariants
- Offline/stopped server has zero online players and cannot accept new connections.
- Whitelist approval changes eligibility; it does not silently grant OP.
- Ban disconnects a connected player; pardon does not automatically reconnect.
- Restart disconnects active players, writes lifecycle events and then permits new joins.
- Compatible mods and dependencies are required before creating/updating a server; never change selected Minecraft version to hide an incompatible mod.
- Update makes a simulated backup before any change; failed update restores previous state.
- Alerts, console, dashboard and Players panel describe the same events.
- Unsafe actions never reach real `/api/*` or privileged browser capabilities.
- Invalid or unhandled fixture API endpoints must fail loudly in CI and be clearly handled in demo UI.
- Screens rendered in demo must be generated from or reconciled with production code, not independently designed replicas.
- Stored state is versioned with a Reset Demo action; separate devices are independent.
- Every enabled visible control must have an effect or an explicit explanation.

## Automation deployment policy
1. Pull requests touching app UI, demo or site assets: build a candidate static site, discover source routes and endpoints, verify coverage, run Playwright desktop/mobile keyboard tests, run safety and link checks.
2. On pushes to main: run compatibility validation, produce report and flag missing fixture contracts before release.
3. After a published beta or stable release: pin exact tag/commit, build demo candidate from tagged frontend and mock backend; test and deploy only if all checks pass.
4. At any failure, retain existing published site and exact previous demo version; surface failure via Actions and a repair issue.
5. A Pages artifact always contains the entire site tree including `join/`, `testing/` and verification file. Deployment workflow remains single-owner so separate workflows cannot overwrite one another.
6. Live website displays exact represented application version and whether it is beta.
7. Stable-only policy change is explicit in version selector; beta releases no longer update public demo.

## Merge gates
- Full production route inventory rendered and checked.
- Two demo entry modes produce meaningfully different initial state.
- Full local simulated backend contract validated by end-to-end tests.
- Clickable and scannable QR opens standalone mobile demo with independent state.
- Responsive, accessible, focus-trapped slideout with Escape / Leave Demo.
- Regression snapshots and security controls validated.
- Existing public testing tracker, invitation page and site verification tested on assembled artifact.
- No actual deployment or release publishing attempted from a draft PR.

## Current implementation status
### Implemented on the draft branch
- Production HTML/CSS/JavaScript builds into `/demo/` using a browser-only simulated API; no genuine Minecraft/backend requests.
- Homepage with actual app screenshot, persistent left navigation, dark default theme, two demo entries, a right-side drawer and Leave Demo control.
- Fictional server creation, lifecycle, dashboard, console commands, player/whitelist operations, mod browse fixtures, backup records, and friends' invitations.
- PWA-only manifest and service worker scoped to `/demo/`; independently stateful standalone phone route and real scannable QR.
- Release selector (`both` beta+stable initially, explicit `stable` switch later), exact tagged frontend packaging and gated **single** Pages publisher.
- Playwright browser smoke tests of global and server routes, server creation, whitelist requests, backup records, Friends controls, keyboard/mobile, original invite/testing paths and Help/manual assets, on both development and tagged-release frontends.

### Remaining review work / do not merge
- Add comprehensive fine-grained mock API and UI tests for advanced modpack workflows, world preview/maps, updates and rehearsals, Java configuration, permissions, and third-party integration panels.
- Audit every enabled control for useful responses, and reject unsupported API contracts before calling the demo complete.
- Perform full visual screenshot/keyboard/accessibility review across devices and production release tags.
- Verify that a simulated update makes and restores backups as claimed in the invariant list.
- Review release build and GitHub Pages deployment conditions; **do not merge or publish before these gates pass**.
The original dashboard-only preview remains independently available at `/preview/`, but is no longer the interactive site's primary demo.
