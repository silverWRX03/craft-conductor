# To do

Two lists: things only you can do (outside the code: accounts, testing on real hardware,
files), and what Claude works on next. Anything in **For you** that a feature depends on
comes first; it says which.

## For you (outside tasks)

Before continuing or starting a feature, check this list: some features wait on one of these.

- [x] **Refresh wiki screenshots for the naming cleanup:** every page is retaken by
      `tests/test_screenshots.py` with example servers, the friend's setup page included.

- [x] **New icon:** put the stone-and-lava "Craft Conductor" picture in the repository (for example
      `packaging/icon-source.png`) or attach it as a file. The copy pasted in the chat didn't
      come through as a file. *Needed before:* the new icon (white background removed).
- [ ] **Try the map preview for real** (New server → World → World generation & map preview):
      one map on Fabric with Terralith, and one on Paper if you use it. Check the map matches the
      world in game, then drag and zoom out and press **Make this area**. It couldn't be run where
      it was built (no Minecraft downloads there).
      *Needed before:* the seed gallery.
- [ ] **Try an update rehearsal for real** (a server → Updates → **Rehearse it on a copy first**, when an
      update is ready): check the report matches what you see when you update for real. It was only
      tried with a pretend server.
- [ ] **Try the new 0.15 features for real:** Find what's causing lag on a busy server, Compare 10 seeds,
      Roll back to a snapshot, the guided setup, and a modded single-player game in your launcher
      (Install…, then Check for updates after a mod updates). They were tried with pretend servers.
- [ ] **Try the phone app for real** (Craft Conductor settings → Phone app): install Tailscale on the
      computer and your phone, press Use Tailscale for the phone app, open the address on the phone, add
      it to the home screen and turn notifications on; then Send a test, and stop a server by hand to see
      one arrive. It was only tried in a desktop browser here.
- [ ] **Try the 0.18 features for real:** turn on Whitelist through Discord (Craft Conductor settings →
      Discord; add the bot again with the card's link first) and type `/whitelist <name>` in Discord; add
      BlueMap or Dynmap (Settings → Web map) and open the map; look at Player activity after a few days;
      try High contrast and a screen reader (NVDA on Windows, VoiceOver on a Mac).
- [ ] **Try automatic port forwarding at home** (craft-conductor settings → Sharing with friends → Router):
      switch it on, look at what it says, then **Test from the internet** in Check my setup. It
      was only tested against a pretend router.
- [ ] **Check the Windows certificate fix for real** (#64): on a *new* Windows 11 VM (a fresh one, not the
      one where the bug happened: that one may have the missing certificate by now), install the test
      build from the pull request (Actions → the PR's **test** run → Summary → `test-build-craft-conductor-windows-x64.exe`),
      then **New server** → Fabric, latest Minecraft, a few mods → set it up. It should download Java and
      finish instead of failing with "certificate verify failed". Then make a vanilla 1.20.1 server (Java 17)
      the same way. If it still fails, attach the new failure report: its activity lines now say whether Windows was asked about the certificate.
- [ ] **Try the 0.22.3 safety checks on real computers** (the full plan, with prompts for Claude Code
      on your PC: [docs/real-world-testing.md](docs/real-world-testing.md); they were only tested on Linux, with a
      pretend Minecraft): on a clean Windows VM, install the download and make a Fabric server,
      back it up, **Restore** it while File Explorer has the server folder open (it should say a
      program is using a file and leave the server as it was), and pull the power (or end the
      task in Task Manager) during an update, then start Craft Conductor again: the server should
      be back on its old version. Repeat with the servers under a OneDrive-synced folder and a
      folder with a non-English name (e.g. `C:\Users\José\Документы\Майнкрафт`), and with
      Windows Defender (and any other antivirus) watching. Note any "being used by another
      process" errors or downloads flagged as viruses.
- [ ] **Try the friends' mods and web map buttons for real** (0.23.0): on the Friends page, **Set up now**
      under Mods for players, tick a mod that says "server + client" and one that says "client-side"
      only, then **Add selected mods**: the first should say it was also added to the server, the second
      not; **Remove** the first (it asks about the server). On the World page's Web map card, only the
      map that has a build for your Minecraft version should have an Add button. On a friend's setup
      page, **More mods** should list only client-side mods. They were tried with a pretend Modrinth.
- [ ] **Try the Connected Players card for real** (0.23.0; a server's Dashboard): with several friends
      online (20 or more if you can), check the list scrolls inside the card, press a row for
      Message, Make op and Ban, and **Kick** one friend (it asks first). Open **Whitelist** (switch
      it on and off, add and remove a name) and **Broadcast** a message: friends should see it in
      the game's chat, and it shows in the Dashboard's console. Have a friend join and leave while
      you watch (rows stay put, the open actions stay open), and try it with a screen reader. Then
      do the same from a paired phone (a helper's phone has them all; a viewer's has no buttons).
      Look at an operator's badge (OP, or OP 2 for a level-2 op in `ops.json`) and at the ping,
      which should show "—" with a tooltip. It was tried with pretend players only.
- [ ] **Try continuous mod browsing for real** (0.23.0): in the mod browser (**Download mods**), scroll
      down a search and check the list keeps going without jumping, and what you ticked stays ticked.
      Try it on a slow connection (a phone hotspot, or the browser's developer tools set to "Slow 4G"):
      **Loading more…** should show at the bottom, then the rows. Search with a Minecraft version that
      few mods support yet (many "result(s) hidden"): the list should keep going, or offer **Keep
      looking**. And the friend's setup page on a phone: **Resource packs** or **More mods**, scrolled
      with a thumb. It was tried with a pretend Modrinth.
- [ ] **Windows code signing (optional):** apply to the SignPath Foundation (see
      [docs/code-signing.md](docs/code-signing.md)). Once accepted, add the repository variable
      `SIGNPATH_ORGANIZATION_ID` and the secret `SIGNPATH_API_TOKEN`; releases are then signed
      and Windows stops warning about craft-conductor.
- [ ] **Merged pull requests:** comment "Fixed in <version>" on any issues a release fixed
      (none so far).
- [x] **Set up the mod-conflict relay:** live at `https://craft-conductor.kyle-r-nordick.workers.dev`
      (in `RELAY` in `src/craft_conductor/conflicts.py` from 0.22.1). Keep the `SALT` secret to
      yourself; to update the relay, paste a new `relay/worker.js` under Edit code and Deploy.
- [ ] **Try the 0.20 features for real:** a Purpur server with a plugin; the sounds on a phone
      (including an iPhone's silent switch, and vibration on Android); adding fingerprint or face
      sign-in on the phone at the Tailscale address and signing in with it. They were only tried
      in a desktop browser and with a software "phone".
- [x] **NeoForge 1.21.1:** on 2026-09-28 NeoForge's own servers listed only one version
      (`26.3.0.33-beta`), so no NeoForge 1.21.1 server could be created (the e2e check was red on
      main too). It worked again the same evening (every e2e run since is green) and the e2e check
      on main was re-run green on 2026-10-04. Since 0.22.2 Craft Conductor says when NeoForge's
      list is incomplete, and servers already on NeoForge keep updating their mods meanwhile.
- [ ] **Switch on the repository's security settings** (Settings → Code security), for
      SECURITY.md and the new workflows: **Private vulnerability reporting** (SECURITY.md's
      "Report a vulnerability" link needs it), **Dependabot alerts** and **Dependabot security
      updates** (`.github/dependabot.yml` does the version updates). If CodeQL's **Default
      setup** is on, switch it off: `.github/workflows/codeql.yml` replaces it, and GitHub
      refuses its results while both are on.

## For Claude (next work)

In priority order: the top one is next.

Done:
- [x] Renamed to Craft Conductor, with the new "CC" icon (0.16.0).
- [x] Release 0.12.0 (router set up by itself, fix buttons, what went wrong, Quick start,
      checked backups and putting back an area).
- [x] New icon from your picture, without the white around it.
- [x] Release 0.13.0: explore the map preview (drag, zoom, make more land as you go).

Next:
1. [x] **Update rehearsal:** before a Minecraft update, copy the server, update the copy and run
       it for a few minutes; report whether it started, how laggy it was and which mods
       complained, then offer "Update for real".
2. [x] **Lag finder:** when the server slows down, run spark by itself and say what's wrong in
       plain words ("chunk loading around x 1200, z −400: a farm with 400 animals").
3. [x] **Seed gallery:** one button makes maps of 10 seeds side by side to pick from, with a
       warning first about the time and the load on the computer (waits on **Try the map preview
       for real**).
4. [x] **Snapshots** of a whole server (config, mods, world) with a list of what changed, and
       rollback.
5. [x] **Guided first server:** a short walkthrough for complete beginners, with a checklist that
       ends at "your friend joined".
6. [x] **Modded single-player worlds:** set up and keep a modded single-player game up to date,
       then load it into the launcher of your choice (no launcher of our own).
7. [x] **Mobile app (first):** Craft Conductor as an app on the phone's home screen (an installable web
       app, not a store app) with notifications when it's closed: a crash, a friend asking to join, an update
       held back, lag. Includes a guided way to reach it over trusted HTTPS (Tailscale, a Cloudflare Tunnel or
       a domain), which phones need for this. A store app only if this falls short.
8. [x] **Accessibility:** everything works with the keyboard, labels for screen readers, and a
       high-contrast theme.
9. [x] **Player activity:** who played when, the busiest times, and a suggested restart time when
       nobody is usually on.
10. [x] Whitelist through Discord (friends ask with a command, the owner approves).
11. [x] Web map of the world (BlueMap or Dynmap) with a link to share.
12. [x] **Map landmarks:** villages, structures and players' bases pinned on the map preview (and
        on the web map). Done: the structures Minecraft and mods place, on the map preview. Not yet:
        players' bases, and pins on the web map (BlueMap and Dynmap show their own).
13. [x] Limits per server (memory, CPU) and a warning when too many run at once. Also warnings
        about the computer (disk space, CPU, memory) on the page and on phones.
14. [x] **World generation preview loads the mods' dependencies:** when mods are picked for the
        map preview (New server → World generation & map preview), the mods they require are
        installed in the preview's throwaway server too, so the map matches the real server.
        Investigate first: a preview with Terralith, Lithostitched, Cristel Lib and Towns and
        Towers ticked failed with "the world has no region files to draw: the server didn't save
        any land", while the footer said "made with all 2 of the server's mods" (0.20.0, Fabric,
        seed 43, 512 × 512, structures on). Done: the dependencies were installed all along (the
        planner adds them); Minecraft 26.x keeps the land in `dimensions/minecraft/overworld/region`
        and writes block palettes differently, which the preview didn't read. The footer now counts
        the needed mods, the download step names them, and a crash names the mod.
15. [ ] Other tunnel services next to playit.gg (Cloudflare Tunnel, Tailscale Funnel).
16. [x] Purpur servers.
17. [ ] Scripting hooks (a script on start, stop, a player joining, before an update) and API tokens.
18. [x] **Mod conflict memory:** mod combinations that failed together in "Find which mods break
        it", shared anonymously if you opt in, so craft-conductor can warn others before they install them
        (needs somewhere to keep the shared list). Done: a Cloudflare Worker (relay/); it's live
        once its address is in conflicts.RELAY.
19. [ ] Proxy networks (Velocity) with several servers behind them.
20. [ ] Translated user manual for the most used languages; a way for people to fix translations.
21. [ ] **Servers on hosting sites:** look into controlling servers that run elsewhere. Hosting
        panels with an official API (Pterodactyl, used by many paid hosts) are the realistic
        target. Free hosts (Aternos, Minehut, Minefort) only if they have an official API and their
        terms allow it: Aternos's terms don't allow automating its site.
22. [x] **Fingerprint or face sign-in** on the phone app (passkeys, WebAuthn), instead of typing
        the password.
23. [x] **Sounds:** subtle cues, the same in the web page and the phone app (made in the browser,
        no sound files; our own sounds, Minecraft-like but not Mojang's): a tap for ordinary buttons,
        rising notes for Start/Save/Install, a falling note for Stop/Delete, a soft thud when
        something fails, and chimes while the page is open (a server is up, a friend asks to join).
        On at a quiet volume for new users. Each kind can be turned off on its own, plus a volume
        (Off / Quiet / Normal) and **Vibrate on button presses** (Android; iPhones don't allow it).
        Each device keeps its own settings, like Display. Never for moving with the keyboard, no
        stacking on quick presses, and never the only sign something happened. Check the iPhone
        silent switch on real phones.
24. [ ] **One dashboard for several computers** (low priority): link other computers' Craft
        Conductors to one (paired like a phone, with a key they can revoke, limited to Helper or
        Viewer if wanted), list every server on every linked computer on one Servers page, and
        get all their warnings and phone notifications in one place. Easier after 16 (API
        tokens); shares the "servers on another machine" groundwork with 20.
25. [x] **Friends' mods land on the right side:** in server setup's "Play with friends" part,
        a mod picked for players that runs on both sides (client and server) is added to the
        server too, with the mods it requires. When a friend sets up their own copy and opens
        Download mods (Modrinth), they only see client-side-only mods. Shipped in 0.23.0;
        the Friends page does the same, and removing asks about the server too.
26. [x] **Investigate: Windows Firewall exceptions alongside UPnP:** when Router (UPnP) opens the
        ports on the router, also let them through Windows Firewall, so friends can connect
        without Windows' own prompt being missed or answered "Cancel". Done as Check my setup's
        Windows Firewall check (rules read without admin rights, `firewall.py`) and its **Let them
        through Windows Firewall** button (one administrator prompt; port rules for private and
        public networks, Windows' block rules for our Java removed).
27. [x] **Web map buttons only when the map mod exists for that version:** show Add BlueMap and
        Add Dynmap (Web map, on the World page) only when the mod has a build for the server's
        Minecraft version and loader; otherwise say it isn't available for that version yet.
        Shipped in 0.23.0.

28. [x] **Reuse compatible Java installations:** detect and reuse Java already on the computer
        (or a shared managed runtime) when it matches the selected Minecraft version and loader.
        Download another runtime only when needed, including when container isolation requires it.
        Shipped in 0.23.0.
29. [ ] **Granular roles for external server managers:** give external users individual access
        with permissions scoped to specific servers and management actions (RBAC).
30. [ ] **Native Bedrock servers:** support creating and managing Minecraft Bedrock Dedicated
        Servers, alongside the existing Java server types.
31. [x] **Continuous mod browsing:** load 20 results initially and prefetch the next 20 around
        result 12, then repeat as the user scrolls, preserving position and avoiding duplicates.
        Shipped in 0.23.0.
32. [x] **Investigate Maps still not working:** the report is closed: Maps works now (checked on
        the user's real setup).
33. [ ] **Contextual help drawer:** Help opens the relevant section in a panel that slides in
        from the right; users can collapse it back to the right without leaving their work.
34. [x] **Dashboard Connected Players widget:** compact player management on the Dashboard,
        with connected count / maximum capacity, player status, names, role badges, live ping,
        per-player KICK, and Whitelist Control and Broadcast footer actions; update without
        a full Dashboard refresh. Shipped in 0.23.0. Ping shows "—" on every
        server type (none shares it without adding a mod or plugin), and there is no MOD/group
        or "you" badge: see the pull request for why and the options.
35. [x] **Size limits when unpacking archives** (security): a modpack's overrides and a backup
        being restored are unpacked without a limit on their total unpacked size, so a small
        crafted file could fill the disk. Shipped in 0.22.3; the two `xfail`s in
        `tests/security/test_archive_security.py` are gone.

## Plans for the items left (details to start from)

Written down so the work can start without re-deriving it. The house rules in CLAUDE.md apply to
all of them: manual (and wiki screenshots when a screen changes), CHANGELOG, translations
(`tr/*.txt` style: English¦es¦pt¦fr¦de¦hi¦zh¦vi¦ar¦ko, built into `webui/i18n/*.json`), tests,
a security then efficiency review, then PR, CI, merge, release. Small items are grouped into one
release to pay those costs once.

**14. World generation preview loads the mods' dependencies** — small. Next.
- The preview (`preview.py`, `Preview`; started by `start_preview` in `web.py`) builds a
  throwaway server from the mods the page sends: `ModSpec`s written to its `craft-conductor.toml`, plus
  Chunky and Fabric API. Check first whether the planner already pulls in each mod's required
  dependencies there (the real server's update does) or whether the page only sends the
  world-generation mods and their dependencies get dropped.
- Fix: resolve required dependencies (Modrinth `dependency_type: required`) for every picked mod
  before the preview installs, the same way New server does (it already selects a mod's
  dependencies with it), and show them in the preview's "Downloading…" step. The preview's
  cache key (`_key`) should include them, so a different dependency set makes a new server.
- Tests: a picked mod with a required dependency ends up in the preview server's mods; the
  error message names a dependency that has no build for that Minecraft version.
- The reported failure (investigate first): Terralith + Lithostitched + Cristel Lib + Towns and
  Towers ticked, footer "The map is made with all 2 of the server's mods", result "the world has
  no region files to draw: the server didn't save any land". Questions: why the footer counts 2
  (the page's `worldgen` list vs the mods sent; `start_preview` takes `b["mods"]`); whether the
  preview server started at all or crashed on a missing dependency (Towns and Towers needs
  Cristel Lib; others need Lithostitched); what its log says (the preview keeps its server under
  the hub's state folder: read its `logs/latest.log`); and whether "no region files" should
  instead say the server crashed and why (surface the preview server's crash reason, with
  `diagnose` naming the mod, like a real start does).

**15. Other tunnel services (Cloudflare Tunnel, Tailscale Funnel)** — medium.
- Today: playit.gg only (`tunnel.py`: parse an address, detect the agent running, show status on
  the Dashboard; Settings → per-server tunnel address; hub share tunnel for friends' downloads).
- Minecraft is TCP. Cloudflare Tunnel doesn't carry raw TCP for players without their own
  `cloudflared`, so it suits the **control panel and friends' downloads (HTTPS)**, not the game
  port; say so plainly. Tailscale Funnel exposes a local port on the internet over TLS (ports
  443/8443/10000), again good for the panel/downloads, not for Minecraft players.
- Plan: a "Reach it from outside" chooser: playit.gg (game), Cloudflare Tunnel (panel and friend
  downloads: guide + `cloudflared tunnel --url` quick tunnel, detect it and show the address),
  Tailscale Funnel (`tailscale funnel` like the existing `tailscale serve` in `tailscale.py`).
  Anything on the internet requires the strong password (remote_ready) and keeps passkeys and
  rate limits; add the host to `[web] allowed_hosts` automatically.

**17. Scripting hooks and API tokens** — medium.
- Hooks: per server in `craft-conductor.toml` `[hooks]` (on_start, on_stop, on_join, on_leave, before_update,
  after_update, on_crash) = a script path inside the server folder (no shell strings; run with
  `subprocess.run([path], env=...)`, the event as environment variables such as CRAFT_CONDUCTOR_EVENT,
  CRAFT_CONDUCTOR_PLAYER; a timeout; output to the log). Owner-only to set (Settings → Hooks), never from a
  paired phone. Players' names must be validated before they go into env (they already are, by
  NAME_RE).
- API tokens: Craft Conductor settings → API tokens: make/revoke named tokens with a role
  (viewer/helper/owner-lite), stored hashed like paired devices (`webauth.Devices` pattern), sent
  as `Authorization: Bearer`. Same `device_allowed` rules; rate limit; list last used. Document
  the API (a Power users wiki page). Needed first by 24.

**19. Proxy networks (Velocity)** — large.
- A new server type "Velocity proxy" (loader: Velocity from PaperMC's Fill API, like
  `loaders/paper.py`), with backend servers chosen from the Servers list; write
  `velocity.toml` (servers, try order, forced hosts) and the modern forwarding secret; set the
  backends to `online-mode=false` and Paper's `proxies.velocity` (Fabric needs FabricProxy-Lite).
  Ports: backends on localhost only. Start order: backends then proxy. Players page shows the
  whole network. Keep the forwarding secret out of logs and the diagnostic report.

**20. Translated user manual** — large (mostly text).
- `manual.md` split by `## ` sections already (wiki). Add `manual.<lang>.md` for es, pt, fr, de,
  hi, zh, vi, ar, ko (machine-made, marked as such), served by language like `i18n/*.json`; the
  in-app manual picks the page language; the wiki gets per-language pages
  (`packaging/wiki.py`). "A way for people to fix translations": a "Suggest a better
  translation" link to a GitHub issue form with the section and language filled in.

**21. Servers on hosting sites (Pterodactyl)** — large.
- Pterodactyl's client API (`/api/client`, a user API key): list servers, power (start/stop/
  restart), console via its websocket, files for mods. Add "a server on a hosting panel" as a
  server kind whose actions go through that API instead of a local process; many pages
  (mods, backups) map to its file API. The key is a secret: keep it like the CurseForge key
  (hub file, 0600), never in logs or reports. Free hosts (Aternos etc.) only with an official
  API and terms that allow it (Aternos's don't).

**24. One dashboard for several computers** — large, low priority. After 17.
- Link: on the other computer, make an API token (17) or a pairing code; the main computer
  stores it (hashed on the other side, secret on this side) with that computer's address (the
  secure Tailscale one preferred; HTTPS required off the home network).
- The main panel lists the other computer's servers (merged into the Servers page, with the
  computer's name) and proxies that server's pages' API calls with the token; the other computer
  applies its own role rules. Health warnings and phone notifications from linked computers are
  forwarded to the main one. Unlink = revoke the token on either side.

**25. Friends' mods land on the right side** — small/medium. Done (0.23.0).
- Today: the mod browser already knows each Modrinth mod's sides (`browse.py`: `side`
  "server"/"client" picks mods that run there; `env` "only"/"both"/"" narrows further;
  `environment()` gives "server", "client" or "both" per result), and friends' mods live in the
  client pack (`clientpack.py`; "Mods for players" on the Friends page, and setup's friends part).
- Owner side (setup's Play with friends, and the Friends page's "Mods for players"): when a
  picked mod's environment is "both" (client_side and server_side required/optional), also add
  it to the server's mods (`ModSpec` in `craft-conductor.toml`) and resolve its required dependencies the
  way the server's own mods are (planner/providers). Say so in a toast ("X also runs on the
  server, so it was added there too, with Y"). Removing it from the players' list asks whether
  to remove it from the server too.
- Friend side (the friend's page, `webui/join.js` + `joinui.py` extras): the Download mods search
  asks with `side=client` and `env=only`, so only client-side-only mods (server_side
  unsupported) show. Modpacks and resource packs/shaders keep their own filters.
- Tests: the side/env facets for the friend search; a "both" mod picked for players ends up in
  `craft-conductor.toml` with its required dependency; a client-only one doesn't.

**Smaller leftovers**
- Map landmarks (12): players' bases, and pins on the web map (BlueMap/Dynmap markers).
- Sounds (23): check the iPhone silent switch on a real phone.
- Store phone app: only if the installable web app falls short.

**26. Investigate: Windows Firewall exceptions alongside UPnP** — small/medium.
- Today: `doctor.py` only explains the firewall (Windows asks the first time Java accepts
  connections; "Allow an app through firewall → Java"); `upnp.py` opens router ports only.
- Look into: a "Let it through Windows Firewall" action (in Router and in Check my setup) that
  adds inbound rules for exactly Craft Conductor's ports (each server's Minecraft TCP port, the
  friends' download port, Geyser's UDP port) with `netsh advfirewall firewall add rule
  name="Craft Conductor <port>" dir=in action=allow protocol=TCP localport=<port>
  profile=private`, which needs administrator rights: one UAC prompt (ShellExecute "runas" on
  netsh), never a silent change. Remove the rules when UPnP is switched off or the port changes.
  Check whether a rule already exists (`netsh advfirewall firewall show rule name=...`), prefer
  the Private profile (public only if the user chooses), and never open anything else.
  macOS and Linux: explain only (macOS asks per app; Linux firewalls vary: ufw/firewalld hints).

**27. Web map buttons only when the map mod exists for that version** — small. Done (0.23.0).
- Today: `webMapCard()` in `webui/app.js` always shows Add BlueMap and Add Dynmap;
  `webmap.py` (`MAPS`: Modrinth projects `bluemap`, `dynmap`) adds the mod to `craft-conductor.toml`, and
  only the next update finds out there's no build (the mod is then skipped or holds the update).
- Fix: `GET /api/webmap` also returns, per map, whether Modrinth has a version for the server's
  loader (Paper/Purpur use the plugin loaders) and Minecraft version (the installed one, or the
  target of a new install). Use the providers' existing version lookup and HTTP cache, so it's one
  cached request per map, not one per page view. The page shows only the available buttons; with
  none, a line like "BlueMap and Dynmap don't support Minecraft X yet". `POST /api/webmap/add`
  refuses one that isn't available (the page isn't the only check).
- Also re-check after a Minecraft update: a map already added that has no build for the new
  version is part of the update's readiness ("Show why") like any other mod.
- Tests: with a fake Modrinth answer, only the map with a build is offered; adding the other is
  refused with a clear message; the lookup is cached.

## Additional requests (2026-10-01): implementation briefs

These five items are pending requirements, not implemented features. Their numbering preserves
the existing roadmap and does not establish a new priority order. Inspect the current code
before choosing an implementation. Apply CLAUDE.md when implementing; keep related help,
translations, documentation, and changelog entries current.

**29. Granular role-based access (RBAC) for external users**
- Goal: let the owner delegate server management without giving every external user full
  administrator access. Inspect existing viewer/helper/device permissions before extending them.
- Support identifiable users with roles/permissions scoped to selected servers and individual
  capabilities, such as viewing status/logs, power controls, console commands, managing
  mods/settings, and creating/restoring backups. Define the exact permission matrix before coding.
- Enforce authorization on the backend for every affected request, including live connections,
  with deny-by-default behavior. UI visibility alone is not authorization. Keep account/role
  administration and global secrets owner-only; treat console and file/config access as
  powerful capabilities that can undermine narrower permissions.
- Allow access changes and revocation to take effect for existing sessions. Reuse the same
  authorization model for API tokens (17) and linked computers (24) where applicable.
- Acceptance: an external user can perform only granted actions on assigned servers;
  direct API requests cannot bypass permissions or reach other servers; revocation removes
  access. Test allowed and denied actions, server scope, and privilege escalation attempts.

**30. Native Minecraft Bedrock server support**
- Goal: create and manage Bedrock Dedicated Servers as a first-class server type. This means
  native Bedrock hosting; cross-play through a Java server bridge alone does not satisfy it.
- First assess supported operating systems/architectures, official distribution/update
  mechanisms, and license acceptance. Explain unsupported combinations in the UI.
- Plan installation, version selection/updates, start/stop/restart, logs/console, Bedrock
  configuration, world storage, backups/restores, and player access controls according to
  Bedrock's actual capabilities.
- Treat Java-specific loaders, mods, runtime installation, and tooling as inapplicable unless
  explicitly supported. Account for Bedrock's UDP networking in connection guidance, port
  conflict checks, firewall/router setup, and diagnostics.
- Acceptance: a supported machine can create, start, join from a Bedrock client, stop, back up,
  restore, and update a Bedrock server; existing Java servers continue to work. Record any
  features that are unavailable for Bedrock rather than exposing broken Java-only controls.

**31. Continuous mod results with early prefetch**
- Goal: replace batches of 10 with a smooth, continuously scrolling list.
- Fetch 20 results initially. As the user reaches approximately the 12th result in that batch,
  prefetch the next 20; repeat at the equivalent point in subsequent batches (about eight
  loaded results remaining). Append results without resetting scroll position or selections.
- Use each provider's supported pagination; prevent duplicate results and overlapping fetches.
  Reset pagination when search text, filters, provider, Minecraft version, or loader changes;
  ignore/cancel stale responses so old searches cannot populate the new list.
- Keep loading nonblocking, show an unobtrusive indicator if the network falls behind, allow
  retry after failure, and stop requests at the end of results. Respect provider limits.
- Acceptance: the first batch has up to 20 results, the next request starts around item 12,
  later batches append smoothly, and rapid scrolling/filter changes cause no duplicates,
  stale results, lost selections, or repeated requests after the final page.

**33. Contextual help in a collapsible right-side drawer**
- Goal: pressing Help in a page/section opens that specific section's help in a drawer
  sliding in from the right, keeping the current task visible.
- Map each Help entry point to the corresponding manual section. Reuse the maintained help
  content instead of duplicating it; provide general help as a fallback where needed.
- Add an obvious control to collapse the drawer back to the right. Opening/closing it must
  preserve the current page, unsaved form values, selections, and scroll position.
- Make the drawer usable on small screens and with a keyboard/screen reader: meaningful
  labels, appropriate focus handling, Escape to close, focus returned to its trigger, and
  reduced-motion support.
- Acceptance: Help opens the correct section from each supported context; collapse returns
  to the same work state; keyboard and mobile users can open, read, and close it reliably.
