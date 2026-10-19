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
      do the same from a phone paired for an invited person (a Moderator's phone has them all but
      Make op; a Viewer's has no buttons).
      Look at an operator's badge (OP, or OP 2 for a level-2 op in `ops.json`) and at the ping,
      which should show "—" with a tooltip. It was tried with pretend players only.
- [ ] **Try continuous mod browsing for real** (0.23.0): in the mod browser (**Download mods**), scroll
      down a search and check the list keeps going without jumping, and what you ticked stays ticked.
      Try it on a slow connection (a phone hotspot, or the browser's developer tools set to "Slow 4G"):
      **Loading more…** should show at the bottom, then the rows. Search with a Minecraft version that
      few mods support yet (many "result(s) hidden"): the list should keep going, or offer **Keep
      looking**. And the friend's setup page on a phone: **Resource packs** or **More mods**, scrolled
      with a thumb. It was tried with a pretend Modrinth.
- [ ] **Try the new-server version fix for real** (B6, 0.24.0): **New server** → NeoForge, a specific Minecraft
      version that Biomes O' Plenty supports but GlitchCore doesn't on one of the two sites, then add Biomes O' Plenty
      from CurseForge. GlitchCore should come along from the other site, and the server should be made on the version
      you picked. Then pick a version GlitchCore has no NeoForge build for anywhere: the mod's row should say
      **Dependency unavailable**, name CurseForge and Modrinth, and offer **Use Minecraft …** without changing the
      version by itself; **Create my server** anyway should fail with the same explanation. It was tried with a
      pretend CurseForge and Modrinth only.
- [ ] **Windows code signing (optional):** apply to the SignPath Foundation (see
      [docs/code-signing.md](docs/code-signing.md)). Once accepted, add the repository variable
      `SIGNPATH_ORGANIZATION_ID` and the secret `SIGNPATH_API_TOKEN`; releases are then signed
      and Windows stops warning about craft-conductor.
- [ ] **Merged pull requests:** comment "Fixed in <version>" on any issues a release fixed
      (done for 0.28.0). A pull request that says "Fixes #N" for each issue closes them when merged.
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
15. [x] Other tunnel services next to playit.gg (Cloudflare Tunnel, Tailscale Funnel). Merged in
        #121, in the next release: the control panel away from home through Tailscale (private)
        or Cloudflare's free quick tunnel for 4 hours; Funnel only as a safety rule switched off
        (Craft Conductor settings → Advanced). Not playit.gg for the control panel: its HTTPS
        tunnels need a paid plan. See THREAT_MODEL.md section 1.6; real-world tests 892–901.
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
29. [x] **Granular roles for external server managers:** give external users individual access
        with permissions scoped to specific servers and management actions (RBAC). Shipped in
        0.28.0 (People: invited people with their own sign-in, a role or custom permissions per
        server; phones belong to a person). What's left is listed in THREAT_MODEL.md section 1.4.
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

Added 2026-10-16 (briefs in "Additional requests (2026-10-16)" below; numbering is not a priority order):

36. [x] **Reaching the server from outside:** playit.gg first (pre-selected, guided download and
        setup), its downsides and the risks of an open router port explained, a non-default port
        picked when a port is opened, and the whitelist on by default whenever the server can be
        reached from the internet. Merged in #121, in the next release. playit.gg's tunnel for
        friends' downloads was removed (it now needs a paid plan); invite links work 1, 3 or 7
        days instead. See THREAT_MODEL.md section 1.5; real-world tests 882–891.
37. [ ] **Discord webhook help link** in a server's Settings, next to the Discord webhook URL.
38. [ ] **Clean uninstall:** remove everything Craft Conductor added; ask separately about servers,
        worlds, backups and exports.
39. [ ] **Choose where files are kept:** on first use, choose the folders for servers, backups and
        exports separately; a clear folder structure; Import a server opens the exports folder.
40. [ ] **Backups to Google Drive, Dropbox, OneDrive and iCloud Drive** (later, after 39), if the user
        chooses.
41. [x] **Notification bell:** a log of every on-screen message, to find one that was missed.
        Merged in #118, in the next release (the last 100, kept in this browser for the person
        signed in).
42. [ ] **Readability review:** the app's text and the websites checked for plain words and for
        basic operation.
43. [ ] **First server, reworked:** the first server is vanilla only, with each step explained
        (what and why). Reworks 5 (guided first server).
44. [ ] **Modded server helper:** after the first server, a helper for building a server with mods.
45. [ ] **Easier server scheduling.**
46. [ ] **Research: wake on request:** a stopped server starts when a player tries to join.
47. [ ] **Ping:** a mod or plugin of our own that reports players' ping, or a suggested one
        (follows up 34).
48. [ ] **Manual CurseForge downloads picked up by themselves:** found where the browser saved them
        and added to the pack; if they aren't there, ask where they are.
49. [ ] **Modpack download screen:** a progress bar that holds the page while a modpack downloads,
        with Chrome's dinosaur game to play meanwhile.
50. [ ] **Custom server icon:** choose the picture players see in Minecraft's server list.
51. [ ] **Recent servers in the left panel:** the last 3 run.
52. [ ] **Craft Conductor's website** on GitHub Pages.
53. [ ] **Make a modpack from a server's mods:** Modrinth (.mrpack) or CurseForge format.
54. [ ] **No load check for a modpack's own mods** during setup (mods added on top still checked).
55. [ ] **Report a bug and GitHub links** at the bottom of the left panel.

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

## Additional requests (2026-10-16): implementation briefs

From the owner's list of 2026-10-16, with the answers to the questions asked about it. The
list's "phone notification screen" item is a bug: issue #117. Its "research user based roles"
item is 29, shipped in 0.28.0. Numbering is not a priority order. Inspect the current code
before choosing an implementation; CLAUDE.md applies (manual, Help, translations, CHANGELOG,
tests, security then efficiency review). "To decide" marks details not settled yet: ask, don't
assume.

**36. Reaching the server from outside: playit.gg first, open ports explained** (list items:
highly recommend playit.gg; should whitelisting be required; playit.gg on by default; whitelist
on by default without playit.gg). Extends 15 (other tunnels) and the Router (UPnP) setting.
- When a server is shared with friends outside the home, playit.gg is the **pre-selected** way,
  with a guided download and setup. Nothing is downloaded or installed until the user presses
  the button. Download the agent only from playit.gg's official releases and check it
  (checksum or signature) before running it; say what it is and that it runs as its own program.
- Explain playit.gg's downsides plainly (a third-party service in the middle, its account, extra
  latency, the free plan's limits; check the current terms and limits before writing them).
- Explain the risks of opening a port on the router (bots scan for Minecraft servers all day,
  griefing, the home IP address becomes public) next to the port-forwarding choice.
- If the user chooses port forwarding, Craft Conductor **picks a free non-default port by itself**
  (not 25565) and says which port to forward; Router (UPnP) and the Windows Firewall rule use it.
- **Whitelist on by default whenever the server can be reached from the internet**, through an
  open router port or playit.gg. Turning it off is allowed but shows a strong warning (not a hard
  requirement).
- Tests: the default choice, the port picked (free, not 25565, not another server's), the
  whitelist default for both ways, and the warning when it's turned off.

**37. Discord webhook help link** — small.
- A server's Settings → Discord webhook URL gets a link to Discord's own instructions for making
  a webhook (Discord's support article; check the address before adding it), opening in a new tab.

**38. Clean uninstall.**
- Removes everything Craft Conductor added to the computer: the program, its settings and state,
  Windows Firewall rules it made, router port mappings (UPnP), Tailscale Serve it set up,
  shortcuts and the start-up entry or service, the URL handler, the friends' download share.
- Asks separately whether to also delete servers, worlds, backups and exports (default: keep).
- To decide: where it's started (a button in Craft Conductor settings, a `craft-conductor
  uninstall` command, the Windows "Apps" list) and what each platform supports (Windows, macOS,
  Linux, Docker). Anything it can't remove by itself is listed for the user to do.

**39. Choose where files are kept** (list items: importing opens the exports and backups place, a
clear folder structure; on first use choose where saved files are stored).
- On first use, the user chooses **separately** where servers, backups and exports are kept
  (defaults offered). Each can be changed later in Craft Conductor settings, moving what's there.
- A clear, documented folder structure inside each (servers, backups, exports, ...).
- **Import a server…** opens its file picker in the exports folder.
- Separate locations are on purpose: they let 40 put backups in a synced cloud folder.
- Check first how `backups.copy_to` and the home folder (`hub.home`) work today, and the
  `craft-conductor` rule in AGENTS.md about not migrating earlier installation paths.

**40. Backups to Google Drive, Dropbox, OneDrive and iCloud Drive** — later, after 39.
- If the user chooses, backups go to (or are copied to) Google Drive, Dropbox, OneDrive or iCloud
  Drive, so a server is always backed up off the computer. To decide: the synced folder of each
  app on the computer (no API, nothing to sign in to) or each service's API (sign-in, tokens to
  keep safe).
- iCloud Drive has no API for other apps' files, so it works only through its synced folder (the
  iCloud app on Windows, Finder on a Mac; nothing official on Linux). Free plans only (each
  service's free storage; check the current sizes): a big world can be larger than that.

**41. Notification bell** — small/medium.
- Keep today's on-screen message timing (5 s, errors 12 s).
- A bell in the page holds **every** message as a log, so one that was missed can be found:
  newest first, with its time and server, and a dot for unread ones. To decide: how many are
  kept, and whether the log survives a page reload or a restart.

**42. Readability and basic-operation review.**
- Go through the app's text and the websites (the invite page, the wiki, 52's site): plain words,
  short sentences, names that match the buttons, and that each page's main task works.

**43. First server, reworked** (reworks 5, the guided first server).
- The **first** server a user makes is vanilla only (no mods), and the walkthrough explains each
  step: what it does and why. Mods come with 44.

**44. Modded server helper.**
- After the first server: a helper for building a server with mods. To decide: what it walks
  through (picking a loader, a modpack or single mods, dependencies, players' mods) and how it
  differs from today's New server.

**45. Easier server scheduling.**
- Scheduled restarts and backups (Settings → Schedule) should be easier and more intuitive to set
  up. To decide: what's confusing today (watch someone set one up first).

**46. Research: wake on request.**
- Can a stopped server start when a player tries to join (a small listener on the server's port
  that shows "starting, join again in a minute" in the server list, then hands the port over)?
  Look at how existing tools do it, the Minecraft status/handshake protocol, Bedrock, and the
  start time of big modpacks. Report before building.

**47. Ping** (follows up 34: no server type shares players' ping by itself).
- Make a small mod or plugin that reports each player's ping to Craft Conductor, or suggest an
  existing one. Don't add it to a server without asking.

**48. Manual CurseForge downloads picked up by themselves.**
- Today the user drops the files they downloaded by hand on the setup page (`handdownload.py`).
- After the user downloads them (still by hand, following CurseForge's terms), Craft Conductor
  finds them where the browser saved them (the Downloads folder), checks each by CurseForge's
  SHA-1 as today, and adds them to the pack. If they aren't there, it asks where they are,
  because the modpack can't start without them.

**49. Modpack download screen with Chrome's dinosaur game.**
- When a modpack is chosen, a progress screen holds the page (the page is paused) while it
  downloads, with the steps and a progress bar.
- Meanwhile, Chrome's dinosaur game: Chromium's T-Rex runner (BSD license), credited in
  THIRD_PARTY_NOTICES.md and the app's licenses. It must run under the page's
  Content-Security-Policy (`script-src 'self'`: the game's code and pictures ship with Craft
  Conductor; nothing loaded from elsewhere, no inline scripts). Keyboard and touch to play;
  Less motion respected.

**50. Custom server icon.**
- Choose the picture players see in Minecraft's multiplayer server list (`server-icon.png`,
  64×64 PNG); the server's card in Craft Conductor shows it too.
- Resize in the browser (canvas) before upload; the server checks it's a real 64×64 PNG (the
  standard library only at runtime: no image library).

**51. Recent servers in the left panel.**
- The left panel shows the **last 3 servers run**. When one to three are running, they're sorted
  by which last had players online.

**52. Craft Conductor's website on GitHub Pages.**
- A website for Craft Conductor on GitHub Pages, next to the invite page (`site/join/`) already
  published there. To decide: what's on it (what it is, screenshots, downloads, the manual).

**53. Make a modpack from a server's mods.**
- Export a server's mods as a modpack, in **either format**, chosen when exporting: Modrinth
  (`.mrpack`) or CurseForge (zip with `manifest.json`).
- Check each format's rules: a `.mrpack` may only link files from allowed hosts (Modrinth's, and
  others it lists), and a CurseForge manifest names CurseForge projects and files; a mod that
  can't go in the chosen format is listed, not left out silently. To decide: whether players'
  mods (the friends' download) go in too.

**54. No load check for a modpack's own mods.**
- When a server is made from a modpack, the "will the server start" check is skipped for the
  mods the pack lists (the pack's author checked them); mods the user adds on top are still checked.

**55. Report a bug and GitHub links at the bottom of the left panel** — small.
- "Report a bug" (the issue form) and a link to the GitHub repository, at the bottom of the
  left panel.
