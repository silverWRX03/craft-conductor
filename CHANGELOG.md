# Changelog

What changed in each version of craft-conductor, newest first. Bugs are listed the way you'd have seen
them. Found a new one? [Report it](https://github.com/silverWRX03/craft-conductor/issues/new/choose);
its fix will say which version it's in.

## 0.22.1 (not released yet)

**Fixed**
- Translated phone setup instructions include the new Connections section and remain available after the settings reorganization.
- The world-generation preview could show only a checkerboard even though land and landmarks had been generated.
- Update readiness no longer calls failed lookups ready or leaves local mod files out. Minecraft upgrades wait for unverified local files, and explicitly chosen upgrades also respect the setting to wait for every mod.
- Release-ready indicators stay green in both themes.
- Required dependencies that cannot be looked up no longer silently disappear from the install plan.
- Selecting a world-generation mod offers required beta libraries by name, including TerraBlender for Oh The Biomes We’ve Gone, instead of leaving the dependency unresolved under a release-only selection.
- Bedrock setup offers compatible Geyser beta builds with an early-build confirmation instead of saying no build exists.
- Restored the slide animations when opening and closing side panels, while keeping the underlying page's scroll position.

**Changed**
- Craft Conductor settings are grouped into Appearance, Sounds & notifications, Sign-in & security, Connections, and About & updates.
- Help and User manual open over the current page, with contents on the left. Close Help or Escape returns to the same page and preserves unsaved entries.
- Updated the application and Windows icons from the supplied artwork, and refreshed the Help and manual screenshots.

## 0.22.0 (2026-10-02)

**Changed**
- The control panel and invite pages now use the Industrial Silver, Obsidian and Magma theme, with raised widgets, a boxed console, four dashboard resource cards, and a mobile navigation drawer with a remembered Light / Dark slider.
- The command, configuration, data folders, services, invite links, and downloads now consistently
  use `craft-conductor`. Python imports use `craft_conductor`; environment variables use
  `CRAFT_CONDUCTOR_*`. Help, the manual, wiki, translations, and build tooling use the same names.
- This is a clean-install testing release: previous installation paths, commands, environment
  variables, and invite schemes are not supported or migrated. Set up a fresh installation;
  copy any worlds you want to keep before switching.

**Fixed**
- The classic single-server control panel now initializes its navigation summary correctly instead of failing to load the dashboard.

## 0.21.1 (2026-09-29)

**Fixed**
- After Craft Conductor updated itself on Windows, it could stop being able to download anything: "couldn't load the list of Minecraft versions: request failed: … No such file or directory: …\\_MEI…\\base_library.zip". The restarted copy was still using the old copy's unpacked files, which Windows deleted when the old copy closed. This update itself is installed by the old version, so if you see that message once more, quit Craft Conductor and open it again.

## 0.21.0 (2026-09-29)

**Fixed**
- Servers made in the control panel never checked for updates by themselves, never ran their scheduled restarts and backups, and weren't restarted after a crash, unless the first-run notice had also been accepted on the command line: they waited for the notice without noticing it had been accepted in the control panel.
- **Find what's causing lag** on Minecraft 26.x said "the computer may be too slow or busy" when nothing was wrong: it didn't understand 26.x's profiler, and nobody being online (Minecraft then pauses the server) left nothing to measure. It now says so, and asks to look again while players are on.
- The world generation map preview failed on Minecraft 26.x with "the world has no region files to draw: the server didn't save any land", with or without mods: Minecraft 26.x keeps the world's land in a new folder. Once found, the map also came out full of holes (26.x saves blocks differently); both are fixed. The same new folders are now used by **Put back an area** from a backup and by the lag finder's look at the world.
- The map preview's footer said "made with all 2 of the server's mods" when the mods you picked had brought others along; it now counts those too ("and the 4 they need"), and the download step names them.
- Windows: **Rehearse the update** could fail with "The update didn't start on the copy: … server did not finish starting:" and nothing after it, when the update needed a new Java (Minecraft 26.x needs Java 25) and Craft Conductor's folder had a long path: the copy's Java went past Windows' 260-character limit. The copy now uses the server's own Java, so a Java downloaded for the rehearsal is there for the real update too. The message now gives the reason, and the copy's last lines are shown.
- A failed rehearsal said "update or remove the mod named" when no mod was named.
- Windows: **Open the ports on my router by itself (UPnP)** said "no router answered" with UPnP switched on and no firewall in the way, on computers with several network adapters (Wi-Fi Direct, Hyper-V, VPNs): the search for the router went out an adapter with no router behind it. It now goes out the one the internet goes through.
- **Use Tailscale for the phone app** said "Tailscale isn't installed on this computer" (after half a minute) when Tailscale was installed but Serve wasn't switched on for your Tailscale account yet. It now gives the link to switch it on straight away.
- Windows: **Test these mods** and the map preview downloaded Java again each time instead of using the Java that was already there.
- Windows: some refused requests (for example a phone at an address that isn't allowed) could show "connection reset" instead of the reason, in the control panel, the friends' setup page and the friends' download.

**Added**
- Windows: **Check my setup** now looks at Windows Firewall itself (no administrator rights needed): whether the server's port and the friends' download port get through on the network you're on (Windows calls many home networks "public"), and whether an old "Cancel" on Windows' own prompt blocks Java. **Let them through Windows Firewall** adds rules for Craft Conductor's own ports after one administrator prompt, and only from the server's own computer.

**Changed**
- The server's **Settings** say what the update choices mean: **Minecraft version** (Newest version your mods support, Only the newest version, Stay on this version) and **Mod builds to use**, instead of "latest-compatible" and "release".
- No more empty "before install" backup offered under **Roll back to this**: the first install's backup, of a server with no world yet, goes once the install worked. A backup before mod updates is named for them, instead of "before-26.3-to-26.3".
- The server type and world type buttons tell screen readers which one is picked.
- When a map preview's private server crashes, the message says which mod it blames (like a server's own start does), and its log is kept (`previews/last-failed.log`) instead of being deleted.

## 0.20.1 (2026-09-28)

**Fixed**
- Pairing a phone, even with the secure Tailscale address, only opened Craft Conductor as a web page: nothing offered the app. After pairing, the phone now offers **Install the app** (Android). An iPhone is shown how to add it to the Home Screen first and pair it there, because the Home Screen app doesn't share Safari's sign-in (before, it asked for the password).

**Added**
- **Pair with a code** on the phone's sign-in page: type the short code shown under the pairing QR code.
- Pairing a phone at an address that only opens in the browser now says so clearly, with **Set up the secure Tailscale address** right there.

## 0.20.0 (2026-09-28)

**Added**
- **Purpur servers:** Paper with many more gameplay settings. Pick it under New server → 1. Server type. It runs the same plugins as Paper (from Modrinth and Hangar), and `purpur.yml` can be edited under Mod config files.
- **Sounds** (Craft Conductor settings → Sounds): a soft click for buttons, rising notes for Start, Save and Install, falling notes for Stop and Delete, a sound when something goes wrong, and a chime when a server finishes starting or a friend asks to join. They're on at a quiet volume; each kind can be turned off, and Android phones can vibrate too. Each device keeps its own choice.
- **Fingerprint or face sign-in** (Craft Conductor settings → Fingerprint or face sign-in): add a passkey on your phone (at its secure address) or computer, and sign in with your fingerprint, face or screen lock instead of the password.
- **Mod conflict memory** (Craft Conductor settings → Mod conflicts): if you opt in, conflicts that "Find which mods break it" finds are shared anonymously (only the loader, the Minecraft version and mod ids). Conflicts three people have reported show as warnings on everyone's Mods page. The warnings start once Craft Conductor's shared list is online.

## 0.19.1 (2026-09-28)

A security and speed check of the whole of Craft Conductor.

**Fixed**
- With HTTPS on (your own certificate), one connection that never finished saying hello could freeze the control panel for everyone until Craft Conductor was restarted.
- A paired phone set up as a **Helper**, which may ban and unban players but not use the console, could slip a console command of its own into **Ban IP** or **Pardon IP**. Addresses are now checked strictly, and the server never takes more than one command at a time.
- A request with a broken length could make the control panel (even before signing in) or the friend's join page wait and keep reading.
- The sign-in limit (5 tries in 5 minutes) could be got round by sending many tries at once.
- The router set-up (UPnP) could be pointed elsewhere by a device on your network that redirected its answer.
- Links from mod sites are only ever web addresses.

**Changed**
- Faster, lighter polling: Craft Conductor reads the computer's memory size once instead of every few seconds (on a Mac that started a program each time), and re-reads a server's settings, the paired phones and the notice only when they change.

## 0.19.0 (2026-09-28)

**Added**
- **Limits per server** (Settings): **CPU cores it may use** keeps a server to some of the computer's cores, and **Lower priority** lets everything else go first when the computer is busy. Handy with several servers on one computer.
- **Too many servers at once:** the Servers page shows how much memory the running servers are given out of the computer's, and starting one that doesn't fit asks first (**Start anyway**).
- **Warnings about the computer:** little disk space left where the servers or backups are, the CPU busy for minutes, memory running out. They show at the top of the page, go to the log, and are sent to phones with notifications on.
- **Choose which notifications each phone gets** (Craft Conductor settings → Phone app → Notify this device about): crashes, friends asking to join, updates, lag, backups, the tunnel, this computer, a server starting, everything else.

**Changed**
- The phone app follows the phone's light or dark setting as it changes, and colours the status bar to match.

## 0.18.2 (2026-09-28)

**Fixed**
- The guided setup was offered even to people who already had a server. It's now only offered before your first one (Help still starts it).
- On a phone, Craft Conductor stayed a browser tab with no word why, and a paired phone had no way to turn on notifications. Phones only install it as an app from a secure address: the top of the page now says so on a plain address (with a link to the Tailscale one when there is one), offers **Install the app** on a secure one, and **Turn on notifications** once it's installed. Pairing a phone picks the secure Tailscale address first.

## 0.18.1 (2026-09-28)

**Changed**
- **The user manual is on the [wiki](https://github.com/silverWRX03/craft-conductor/wiki/Craft-Conductor-Manual)** too, a page a section with pictures and a sidebar, plus **Power users** pages (the command line, `craft-conductor.toml`, running it as a service, and more). **User manual → On the wiki, with pictures** opens it. The README is now short, for getting started.
- **Choosing a password** now lists what it needs under the boxes (4 or more characters, or a strong one with remote access on; 4 to 8 digits for a PIN; both boxes the same) and ticks each one off as you type, instead of saying only after you press Save.

## 0.18.0 (2026-09-28)

**Added**
- **Keyboard and screen readers:** a **Skip to main content** link, a clear outline on whatever the keyboard is on, windows that keep the keyboard inside them and close with Escape, page titles that name the page and server, and messages that screen readers read out. See the user manual's "Keyboard and screen readers".
- **Display** (Craft Conductor settings, replacing Size): **High contrast** and **Less motion**, next to the size. Both follow your computer's own settings unless you pick one.
- **Player activity** (Players page): who played and for how long, a week-by-hour grid of when people are on, and the quietest time, which **Restart every day at this time** makes the scheduled restart.
- **Whitelist through Discord** (Craft Conductor settings → Discord): friends type `/whitelist <their Minecraft name>` in your Discord server. **Ask me first** puts them on the Players page; **Let them in straight away** adds them at once, optionally only for members with a role. Bots added before this version need adding again (the link on that card) for the command to appear.
- **Landmarks on the map preview** (New server → World generation & map preview): villages, outposts, temples, mansions, monuments, shipwrecks, ruined portals, ancient cities and more (a mod's own structures too) are marked on the map, with a list of where each one is.
- **Web map** (Settings → Web map): add **BlueMap** (3D) or **Dynmap** in one click, then **Open the map** to see the world and who is where in a browser. The Dashboard links to it while it runs.

## 0.17.0 (2026-09-28)

**Added**
- **The phone app** (Craft Conductor settings → **Phone app**): put Craft Conductor on your phone's home screen like an app, and get **notifications** even when it's closed: a server crashed or won't start, a friend asks to join, an update was held back, it's lagging, and everything else that goes to Discord. **Use Tailscale for the phone app** gives the control panel the secure address phones need, reachable only from your own devices. Tap a notification to open that server.

## 0.16.0 (2026-09-28)

**Changed**
- **Craft Conductor branding**, with a new icon (the same stone-and-lava picture, now with "CC"). The project moved to [github.com/silverWRX03/craft-conductor](https://github.com/silverWRX03/craft-conductor); the old address forwards there.
  - The downloads are now `craft-conductor-windows-x64.exe`, `craft-conductor-macos-arm64`, `craft-conductor-linux-x64` and `craft-conductor-linux-arm64` (and `craft-conductor-join-...` for friends). Copies of craft-conductor update themselves as before.
  - The invite page moved to [silverwrx03.github.io/craft-conductor/join/](https://silverwrx03.github.io/craft-conductor/join/). Invite links made before this version point to the old page, which is gone: make a new invite link and send it again (an invite code pasted into the app still works).

**Fixed**
- On a phone, the sentence at the top of the Servers page was squeezed into one word per line.

## 0.15.0 (2026-09-28)

**Added**
- **Lag finder** (Dashboard → Performance → **Find what's causing lag**): 30 seconds of Minecraft's own profiler plus a look through the saved world say, in plain words, what's making the server lag (mobs, hoppers and other machines, making new land, a mod's things), where (by coordinates) and what to do. It also runs by itself when the server keeps falling behind while people play, and tells you (switch it off in Settings → Updates).
- **Compare 10 seeds** (New server → World generation & map preview): maps of 10 random seeds side by side, to pick the one you like. It asks first, since it takes a while and works the computer hard.
- **Snapshots:** every backup now notes the whole server (Minecraft version, mods, settings, mod configs, craft-conductor's settings). The Backups page says what changed since the backup before, and **Roll back to this** shows what it will undo, then puts all of it back, mod list and settings included.
- **Guided setup:** a checklist from making your first server to a friend joining it, ticking itself as you go. The first time you use craft-conductor it asks (**Guide me** or **Skip**, asked only once); start it again any time from Help or the Servers page.
- **Modded single-player games** (Servers page): pick a mod loader and mods, and craft-conductor puts the game into your launcher (Minecraft Launcher, Prism, Modrinth App or CurseForge) and keeps it up to date. Minecraft moves up once every mod supports the new version; your worlds are kept.

**Fixed**
- Backups made within the same second could be listed (and pruned) in the wrong order.

## 0.14.0 (2026-09-28)

**Added**
- **Update rehearsal** (Updates → **Rehearse it on a copy first**): an update is tried on a copy of the server and its world, which runs for a few minutes where nobody can join. The report says whether it started, how well it kept up, and which mods wrote warnings or errors; then **Update for real**. The server itself isn't touched.
- A setting to rehearse automatic updates to a new Minecraft first (Settings → Updates): if the copy doesn't work, the update is held back and you're told.

## 0.13.0 (2026-09-28)

**Added**
- **Explore the map preview:** drag the map to move and scroll to zoom out and see much more of the world. **Make this area** has the private server make the land you're looking at, and **Keep making the map as I move** does that by itself as you go. The server stops on its own after a few minutes of not being needed.

## 0.12.1 (2026-09-27)

**Added**
- **Size** (craft-conductor settings): how big text and buttons are in this browser. **Automatic** (the default) makes craft-conductor's pages bigger on big screens, so they fill a large monitor instead of sitting small in a corner.

**Changed**
- craft-conductor has a new icon: the stone "Craft Conductor" letters on lava-cracked bricks in a metal frame.

**Fixed**
- **Preview map** finished but showed an empty map ("0 biome(s) in view"): the map was drawn around 0,0 when the world's spawn couldn't be read, while the land had been made around the real spawn elsewhere. It's now drawn where the land is, and if there's nothing to draw it says why instead of showing a blank map.

## 0.12.0 (2026-09-27)

**Added**
- **Router set up by itself** (craft-conductor settings → Sharing with friends → Router): with UPnP, craft-conductor forwards each server's port and the friends' download port on your router, and takes them back when switched off or on quit. It says when forwarding can't help (CGNAT, two routers).
- **Fix buttons in Check my setup:** accept the EULA, download Java, use memory that fits, delete old backups when the disk is full, use a free port, turn account checks back on, use your public IP, ask the router to forward the port.
- **What went wrong** on the Dashboard: when a server crashes or won't start, the cause in plain words with buttons to fix it (remove or switch off the mod to blame, add a missing mod, more memory, the right Java, a free port).
- **Quick start** on New server: ready-made starting points (vanilla Minecraft with friends, smooth survival, new lands to explore, plugins, a modpack).
- **Backups are checked** right after they're made (and on request), and **Put back an area…** restores one part of the world from a backup, keeping the rest.

## 0.11.0 (2026-09-27)

**Added**
- **World generation & map preview** (New server → World): pick world-generation mods from Modrinth, and see a map of a seed before you create the server. craft-conductor makes the world in a private test server with the server's mods and draws it from above, with the biome under the pointer; earlier maps stay listed so you can compare seeds and **Use this seed**.

## 0.10.0 (2026-09-27)

**Added**
- **Languages:** craft-conductor's pages, the friends' joining page and the invite page in Spanish, Portuguese, French, German, Hindi, Chinese (Simplified), Vietnamese, Arabic (right to left) and Korean, besides English: **craft-conductor settings → Language**, or automatically in your browser's language. The translations are machine-made; the user manual stays in English.
- **Rented servers (a VPS):** **Install on a Linux computer** works for a server on the internet too, keeping its control panel private and reached through an SSH tunnel (**Open an SSH tunnel**), with a [guide](docs/rented-server.md).
- **Paper plugins from Hangar** (PaperMC's plugin site) next to Modrinth, kept updated like mods; plugins and mods you added yourself can be switched off, on or removed.
- **playit.gg tunnels** for when you can't forward ports: a tunnel address per server and for friends' downloads, and a **playit.gg tunnel** card on the Dashboard that checks it's working (through the tunnel, the way a friend's game connects) and says when it stops. playit.gg is an outside service: disruptions on its side are out of craft-conductor's control.
- **The friends' download** (`craft-conductor-join-...`): the same craft-conductor under its own name, opening straight into joining a server (even on a computer that runs servers). Invite links offer it.
- Windows code signing through SignPath Foundation is ready in the release workflow; it switches on once the project is accepted ([code signing policy](docs/code-signing.md)).
- **Co-admins:** pair a device as a **Helper** (everyday controls) or a **Viewer** (look only), for a friend who helps run the server; what they do shows in the activity.
- **Discord live status message** (craft-conductor settings → Discord): one message in a channel showing each server's state, players and version, kept up to date.
- **Saved mod lists** (Mods page): save the mods under a name, switch lists and switch back (the current list is saved first), and download or load a list as a file.
- **World tools** (Settings): game rules with what they do, a world border, and pre-generating terrain with Chunky (added in one click), with progress.
- **Bedrock players** (phones, tablets, consoles, Windows): **Let Bedrock players join** on the Friends page adds Geyser and Floodgate and says which port to use and forward.
- **Ask to be let in:** friends joining a server with a whitelist send their Minecraft name from their craft-conductor; it shows on the Players page with **Allow** / **Ignore** (and as a notification).
- **Servers you've joined** (friends' craft-conductor) marks the servers that changed since you set up, so you know when to press **Update**.
- **Performance** on the Dashboard: ticks per second and ms per tick with a graph of the last hour, what slows a server down, and (with the spark mod) a 30-second profile.
- **Notifications** from the browser (craft-conductor settings → Notifications): a server stopping unexpectedly, an update being ready, someone joining, a job failing, while the tab is in the background.
- **Schedules** (Settings → Schedule): restart the server every day or week, back up every few hours or daily, or any cron expression; scheduled restarts give players the countdown and can skip while people are online.
- **Backup copies** (Settings → Backup copies): every backup is also copied to a USB drive or a cloud-synced folder, keeping the newest few.
- **🩺 Check my setup** on the Dashboard: Java, memory, disk space, the port, accounts, the friends' port and public address, the firewall and craft-conductor updates, each with what to do. **Test from the internet** checks friends outside can connect (asks ifconfig.co, only when pressed). **Report for a bug report** downloads the logs and settings with secrets taken out.
- **Play on this computer** on a server's Dashboard: sets up this computer's Minecraft for the server (on the server's own computer), after saying what running both on one computer needs: memory and CPU with this computer's numbers, lag spikes, and heavy modpacks.

## 0.9.2 (2026-09-27)

**Added**
- **Don't ask me again** on questions you meet often (Stop the server?, Quit craft-conductor?, Update to Minecraft…?, beta-only mods, Aikar's flags), and **Don't show again** on notices you've read. **craft-conductor settings → Warnings** brings them back.
- Closing the browser tab no longer loses work silently: the browser asks first while a file is uploading, settings or a config file aren't saved, a New server form is started, picked mods aren't added, or a mod test is running.

**Changed**
- Questions ("Stop the server?", "Delete …?") appear in craft-conductor's own dialog in the middle of the screen, with clear button names, instead of the browser's.
- The Servers page says once that closing the tab doesn't stop craft-conductor (**Got it** hides it), and the New server progress says you can close the page while it installs.

**Fixed**
- Closing craft-conductor's page (a friend setting up their game) and then pressing **Open in craft-conductor** or opening craft-conductor again didn't bring it back. It now shows the page again, with the progress or results, and the browser asks before the tab is closed while Minecraft is being set up.
- An invite link that lost its invite on the way (some apps cut links short) ended at "This invite link isn't complete"; the invite page now has a box to paste the link or invite code.

## 0.9.1 (2026-09-27)

**Added**
- A **user manual** in the app (**User manual** in the menu, and on Help), with contents, print and "Open on GitHub".
- **One-click friend invites:** friends click a link, press Download and run the file; craft-conductor sets up their game. Next time, the link's **Open in craft-conductor** opens their craft-conductor directly (Windows and Linux). The raw invite codes are still there for power users.

**Changed**
- Messages that need an answer are shown in the middle of the screen with the page blurred behind; everyday messages are at the top of the screen instead of the bottom-right corner.
- Discord posts say "Click here to join".

**Fixed**
- New server kept the previous server's type and mods after a server was created, and skipped the first step (where "install on a Linux computer" was). "Or on another computer" is now at every step.

**Fixed (security review)**
- An "Open in craft-conductor" link could pass extra options to craft-conductor; it now only ever carries the invite.

## 0.9.0 (2026-09-27)

**Added**
- **Install on a Linux computer over SSH** from the New server page.
- Friends connect to your server over **HTTPS**, and only to your server (the invite carries its certificate's fingerprint). craft-conductor itself always comes from GitHub.

**Changed**
- The **"no password"** sign-in option was removed; there's always a password or PIN.
- New servers always start with the **whitelist off**, even when a modpack's settings turn it on.
- Old `http://` invites stop working; send friends a new one.

**Fixed (security review)**
- The friends' download port could be tied up by idle connections; connections are now limited and time out.
- The friends' port showed internal error details to visitors.
- A reverse proxy or tunnel on the same computer could make remote visitors count as "this computer".
- Friends' pages accepted non-HTTPS "download it yourself" links.

**Faster (efficiency review)**
- The control panel stops polling while its tab is hidden, and the browser keeps its copy of the page's files.
- Fewer repeated checks on macOS (memory size, CPU use), and friends on your network and the internet no longer invalidate each other's cached download.

## 0.8.2 (2026-09-27)

**Added**
- **"Runs on" filter** in the mod browser: Modrinth mods tagged server-side, client-side or both (server-side and both for servers, client-side and both for friends).

**Fixed**
- Windows: installing for a friend failed with **"The process cannot access the file because it is being used by another process"**; craft-conductor now shows the real error and waits out antivirus scans.
- The mod browser's **Add selected mods** button could be pushed off the screen, and the mod's details scrolled away with the list.
- Iris added without **Sodium** (and other mods whose required mods are listed by version only); a friend's extras now show what they bring along.
- The friend's shaders/resource packs/mods picker had **no thumbnails**, and now works like the mod browser.

## 0.8.1 (2026-09-26)

**Added**
- **Set up now** for friends on the New server page (mods for players, their own files, companions added automatically).

**Fixed**
- The **day theme stayed dark** in browsers that force dark mode (Chrome's Auto Dark Mode, Dark Reader).
- The New server progress shrank to the bottom of the window; it stays on the page now.

## 0.8.0 (2026-09-26)

**Added**
- **Paper** servers (plugins); **phone remote control** paired by QR code, with a strong-password rule for remote access; a **Docker** image; installing on a **Linux computer without a screen**.
- **Show why** on Updates: every mod in green, yellow or red for the newest Minecraft.
- Friends can add their own **shaders, resource packs and mods**, choose Minecraft's **memory**, and are warned before an update removes extras.
- A **Help** page with a router port-forwarding guide; **Aikar's flags** offered above 16 GB of memory; CurseForge built in to release builds.

**Fixed**
- Creating a server failed with **HTTP 408** from Modrinth.
- "What's happening" showed the previous server's messages; failures now always say where the report is saved.
- Quick add on the New server page was removed (it duplicated Download mods).

## 0.7.0 (2026-09-26)

- The in-page **mod browser** (Modrinth and CurseForge), modpacks, friend launchers (Minecraft Launcher, Prism, Modrinth App, CurseForge), **export/import** of servers, world options and world import, beta Minecraft versions, a **mod config editor**, **Test these mods** / find the culprits, and day/night themes.

## 0.6.0 (2026-09-26)

- **Friend downloads:** set up friends' Minecraft for your server.

## 0.5.0 (2026-09-26)

- Advanced server settings, popular mods, step-by-step setup, deleting servers.

## 0.4.0 (2026-09-26)

- A server list with several servers, and servers no longer start by themselves.
- Fixed the default password.

## 0.3.0 (2026-09-25)

- Dashboard with CPU and memory bars, players online with their heads, and the console.

## 0.2.1 (2026-09-25)

- Fixed the setup page and the default password for folders from craft-conductor 0.1.

## 0.2.0 (2026-09-25)

- Set up a new server from the web page.

## 0.1.0 (2026-09-25)

- First release: a modded Minecraft server manager that keeps a server and its mods up to date, with Java management.
