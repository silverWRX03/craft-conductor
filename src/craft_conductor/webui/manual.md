# Craft Conductor user manual

Craft Conductor (Minecraft server manager) sets up a Minecraft server on your own computer, keeps it running, keeps it and its mods up to date, and gets your friends' games ready to join. Everything happens in the **control panel**, a page in your web browser.

This manual is also inside Craft Conductor: open **User manual** (or **Help**) in the control panel. It comes with Craft Conductor, so it always matches the version you have and is updated with it. Craft Conductor is in beta: back up anything you can't afford to lose.

Help and User manual slide over the current page. Their contents appear on the left in place of the control menu. **Close Help** or **Escape** returns to the same page and scroll position, with unsaved entries intact. On a phone, the contents appear above the help text.

Help shows a picture of the screen with each topic, and in the User manual, **See this screen** under a heading opens its pictures; press a picture to see it full size. They come with Craft Conductor, so they work offline, and they show example servers.


## What Craft Conductor can and can't do

**It can:**

- create a Fabric, NeoForge, Forge, Quilt, Paper, Purpur or plain (vanilla) Minecraft server, with the right Java, mod loader and mods;
- keep it on the newest Minecraft **once every mod supports it**, making a backup before each update and rolling back by itself if the new version doesn't start;
- find mods and the mods they need, test a set of mods before you commit to it, and find which mod breaks a server;
- set up your friends' Minecraft (Minecraft Launcher, Prism Launcher, Modrinth App or CurseForge) with one invite;
- let you manage it from your phone or another computer, or run it on a Linux computer without a screen, or in Docker.

**It can't:**

- make your computer reachable from the internet on every network: friends outside your home need **port forwarding** on your router. Craft Conductor can ask the router to do it (UPnP) when the router allows it; otherwise the Help page shows how;
- make mods work together when their authors haven't; it can only tell you and wait for updates;
- download CurseForge mods whose authors block downloads by other apps (you download those yourself; Craft Conductor gives you the link);
- run your server while your computer is off; it isn't a hosting service. Bedrock players can join supported Java servers through Geyser (see Friends).

## Getting started

1. Download Craft Conductor for your computer from the [releases page](https://github.com/silverWRX03/craft-conductor/releases/latest): Windows, Mac (Apple silicon) or Linux.
2. Open it. On Windows, if SmartScreen says it "protected your PC", choose **More info → Run anyway** (Craft Conductor isn't code-signed). On a Mac, the first time, see **On a Mac** just below.
3. The control panel opens in your browser. Read and accept the notice (what Craft Conductor does and doesn't do).
4. Sign in with the password `PASSWORD` (in capitals). Craft Conductor asks you to choose your own right away: a password, or a 4–8 digit PIN. A PIN only works in a browser on the server's own computer. Under the boxes, **Your password needs** lists what it must have and ticks each one off as you type: a password needs 4 or more characters (and can't be `PASSWORD`), a PIN 4 to 8 digits, and both boxes must match. To use Craft Conductor from your phone or another computer, the password must be **strong**: 12 or more characters, with an uppercase letter, a lowercase letter and a special character (like ! ? # %). With remote access on, that's what the list asks for.

**On a Mac:** macOS blocks apps from the internet that aren't notarized, so the first time, open **Terminal** and run:

```sh
cd ~/Downloads
chmod +x craft-conductor-macos-arm64
xattr -d com.apple.quarantine craft-conductor-macos-arm64
./craft-conductor-macos-arm64
```

After that, double-clicking it works.

Servers run while Craft Conductor runs. **Closing the browser tab doesn't stop Craft Conductor**: your servers keep running, and anything Craft Conductor is doing (creating a server, an update) carries on. Open Craft Conductor again from its icon to come back to the control panel. **Quit** (at the bottom of the menu) stops everything cleanly.

If closing the tab would lose something that only lives in the page (an upload on its way, settings or a config file you haven't saved, a New server form you've started, mods picked but not added, a mod test's report), your browser asks first ("Leave site?").

> Joining a friend's server rather than running your own? See **For friends: joining a server** below.

### The guided setup

The first time you use Craft Conductor, before you have a server, a message asks whether you'd like the **guided setup**: **Guide me**, or **Skip** (it isn't asked again). Once you have a server it isn't offered. It's a checklist in a corner of the page, from making your first server to a friend joining it:

1. **Make your server**, 2. **Start it**, 3. **Join it yourself**, 4. **Let friends reach it**, 5. **Invite a friend**, 6. **A friend joined**.

Each step ticks itself as it happens (Craft Conductor sees the server running, who has joined, the router or tunnel set up, the friends' download switched on). **Show me** opens the page for the next step; **I've done this** ticks the two steps Craft Conductor can't always see. **–** hides it to a small button (press it to open it again), and **×** stops it. Start it again any time: **Help → Start the guided setup**, or **🧭 Guided setup** on the Servers page.

## Creating a server

Go to **New server**. One step at a time:

**Quick start (optional).** Ready-made starting points fill the form in for you; change anything afterwards:

- **Vanilla Minecraft with friends:** Vanilla, the newest version, and a download for your friends.
- **Smooth survival:** Fabric with performance mods (Lithium, FerriteCore, Krypton): less lag, the same game.
- **New lands to explore:** Fabric with Terralith (new biomes made of vanilla blocks) and performance mods.
- **Plugins (Paper):** a Paper server to add plugins to.
- **A modpack:** opens Modrinth's modpacks.

The mods in these run on the server only, so friends join with plain Minecraft. Memory is set for the kind of server, within what this computer has.

**1. Server type.** Fabric, NeoForge, Forge and Quilt run mods; Paper runs plugins (Spigot/Bukkit ones too); Purpur is Paper with many more gameplay settings and runs the same plugins; Vanilla is plain Minecraft.

**2. Minecraft version.** "Newest version your mods support" is recommended: the server upgrades only once every mod supports the next Minecraft (a "forever server"). Picking a specific version keeps it on that version (mods still update). Tick "Show beta versions" to try snapshots and pre-releases (worlds opened in them can't go back).

**3. Mods** (or plugins):

- **Download mods** opens the mod browser beside the form: search Modrinth and CurseForge, read a mod's page on the right, tick the ones you want, and press **Add selected mods**. Mods that need other mods bring them along.
- **Runs on** narrows Modrinth mods by where they run: server-side and both (the default for a server), server-side only, or both. Tags show where each one runs.
- "Also show mods with only alpha/beta builds" includes less stable mods, with a warning.
- **Local files** adds `.jar` files from your computer. **Modpacks** builds the whole server from a Modrinth modpack.
- **Required** mods decide which Minecraft version the server starts on; every mod holds back upgrades until it supports the new version.
- **Test these mods** checks they work together before you create the server.

**4. World.** A new world (seed, type, structures, hardcore), or **Import a world**: a singleplayer save or a world `.zip` from any Java version. Files in a `.zip` that would land outside the world's folder, or that Windows can't have (like `NUL` or a name with `:`), are left out, and so are links (shortcuts) in a singleplayer save; the activity log says which. A world bigger than the free disk space is refused before anything is written.

**World generation & map preview** (under the new world's settings) slides open beside the form:

- **World generation mods** lists Modrinth's world-generation mods (or plugins) that work with your server type and Minecraft version. Ticking one adds it to the server's mods (with what it needs); unticking removes it.
- A release mod may need a library that only publishes beta or alpha builds. Craft Conductor names those required libraries and asks before allowing early builds for that mod and its dependencies. Declining leaves the incompatibility visible; it does not silently omit the required library.
- Type a **seed** (or press 🎲 for a random one), pick the world type and a map size, and press **Preview map**. Craft Conductor makes the world in a private server on this computer (nobody can join it), with all the mods you've picked, the mods they need, and the Chunky mod to generate the area (the line under the list counts them, and the progress names them), then draws it from above: north is up, one pixel is one block, and ★ is the spawn point. Point at the map to see the coordinates and the biome there.
- **Landmarks:** villages, pillager outposts, temples, woodland mansions, ocean monuments, igloos, witch huts, shipwrecks, ruined portals, ancient cities, trail ruins, trial chambers and the like are marked on the map with a symbol (point at one for its name and coordinates), including a world-generation mod's own structures. The **Landmarks** list under the map counts them and gives each one's coordinates; on the map you can move around, pick one to go there. **Show them on the map** hides or shows the symbols. Mineshafts and buried treasure (underground, and everywhere) aren't shown; strongholds are.
- **Move around the map:** drag it to move, and scroll (or press **+** and **−**) to zoom, from 4 pixels a block out to 32 blocks a pixel. **⌖ Back to spawn** brings you back. Where the land hasn't been made yet the map is checkered; press **Make this area** and the private server makes the land in view (it asks first when that takes more than a minute), or tick **Keep making the map as I move** and it makes the land as you go. The private server stays on while you explore, and stops by itself after five minutes of not being needed.
- It takes a minute or two the first time (Minecraft and the mods are downloaded) and less for the next seeds with the same mods. Bigger maps and heavy mods take longer; **Stop** cancels it. You can close the panel and carry on: the map is there when you come back.
- **Earlier maps** keeps the seeds you've looked at; **Use this seed** makes one the server's seed.
- **Compare 10 seeds** makes maps of 10 random seeds one after another, with the same mods, so you can pick the one you like (lots of ocean, a big mountain range, a biome you're after). It asks first: it takes a while (each map is a new world) and the computer works hard meanwhile. The maps appear side by side as they're made; press one to look closer and **Use this seed**. **Stop comparing** keeps the maps made so far, and **← Back to the seeds compared** returns to them.
- Maps need Minecraft 1.18 or newer, and aren't available for modpacks or imported worlds. Vanilla servers are previewed with Fabric, which makes exactly the same worlds.
- If a map can't be made, it says why (when the private server crashed, which mod it blames). Its server's log is kept as `last-failed.log` in the `previews` folder of Craft Conductor's own folder (`.craft-conductor`) until Craft Conductor restarts.

**5. Settings.** The server's name (shown in the multiplayer list), max players, difficulty, game mode, memory and port. Above 16 GB of memory, Craft Conductor offers **Aikar's flags** (tuned garbage collection that avoids lag spikes). **Advanced settings** has the rest of Minecraft's server settings. The whitelist starts **off** (anyone with the address can join) until you turn it on.

**Friends (optional).** Tick "Make a download for my friends" to get an invite for them. **Set up now** opens the mod browser for mods for players' computers (a minimap, JEI...), and **Local files** adds your own. Mods your server's mods need on players' computers are added by themselves. A mod that runs on both sides ("server + client" in the browser) is also added to the server's mods, with the mods it needs, and a message says so ("X also runs on the server, so it was added there too, with Y"); the list shows it as **also on the server**. Removing it from the list asks whether to remove it from the server too. Mods that only run on players' computers stay with the players.

**Almost done.** Accept the Minecraft EULA and press **Create my server**. Craft Conductor downloads Java, the loader, Minecraft and the mods, then checks the server starts. The progress stays on the page, and the lower part of the screen shows how to open your router for friends outside your home. When it's ready, the server's Dashboard (or its Friends page) opens.

If setup fails, the page says why and where the detailed report is saved; change your choices and try again.

### On another computer (Linux, over SSH)

A spare PC, a home server or a Raspberry Pi 4/5 (64-bit) can run your servers without a screen. On **New server**, under **Or on another computer** (at the bottom of the page, at any step), choose **Install on a Linux computer**, type its address (e.g. `192.168.1.50`) and a normal user name on it (not root), and press **Connect with SSH**. A terminal opens: type that computer's password when SSH asks (the first time, answer `yes` to trust it). Craft Conductor never sees the password. When it finishes, it shows that computer's control panel address and a one-time password; open it and choose your own password. See also the [headless guide](https://github.com/silverWRX03/craft-conductor/blob/main/docs/headless.md) and [Docker](https://github.com/silverWRX03/craft-conductor/blob/main/docs/docker.md).

**A rented server (a VPS)** works the same way: type its internet address, and Craft Conductor ticks **It's a rented server on the internet**. Its control panel then stays private (on the server only) and you reach it through SSH: **🔐 Open an SSH tunnel** (keep the window open), then **Open its control panel** (`http://localhost:8775/`). Open the Minecraft port in the server's firewall (the page shows the command). The [rented servers guide](https://github.com/silverWRX03/craft-conductor/blob/main/docs/rented-server.md) covers what to rent, firewalls and keeping it safe.

## Messages

Everyday messages ("Saved", or what went wrong) appear at the **top of the screen** for a few seconds; click one to dismiss it. When Craft Conductor needs an answer (use Aikar's flags? install an craft-conductor update? a mod test finished), it asks in the **middle of the screen** with the page blurred behind, and waits until you choose. A long mod test shows its progress at the top while you keep working.

Questions you'll meet again and again ("Stop the server?", "Quit Craft Conductor?", "Update to Minecraft …?", mods with only beta builds, Aikar's flags) have a **Don't ask me again** box, and notices you've read (online-mode is off, a mod test takes a while, closing the tab doesn't stop Craft Conductor) have **Don't show again** or **Got it**. Craft Conductor remembers that in this browser; **Craft Conductor settings → Sounds & notifications → Warnings → Show all warnings again** brings them all back. Questions about deleting or replacing things always ask.

**Warnings about this computer** show in a strip at the top of every page while they last: little disk space left on the drive with a server or its backups (under 10 GB, and in red under 3 GB), the CPU busy (90% or more) for five minutes, the computer almost out of memory, or the running servers given more memory than the computer has. Each says what to do. Craft Conductor looks every minute; each warning is also written to the log and sent to phones with notifications on, once when it starts (and again only after it has gone away, at most every six hours). **Hide** hides it on this page until it changes.

## Your servers

**Servers** lists every server with its state, version, players and port: **Start**, **Open**, **Delete**, and **Folder** (on the server's own computer). **Import a server...** adds one exported from another computer.

Under the list: how much memory the running servers are given, out of this computer's. Starting a server that would take more than the computer can spare (keeping 1.5 GB for everything else) asks first, with **Start anyway**: servers that together are given more memory than the computer has slow right down or crash.

### Modded single-player games

Below the servers, **Modded single-player games** sets up modded Minecraft for playing on your own, and keeps it up to date. Craft Conductor isn't a launcher: the game goes into the one you use (the Minecraft Launcher, Prism Launcher, the Modrinth App or CurseForge).

- **+ New single-player game:** a name, the mod loader (Fabric, NeoForge, Forge or Quilt), the memory for the game, and the Minecraft version: a fixed one, or **The newest one all the mods support**. Search Modrinth and **Add** mods (only mods that run on players' computers are listed); mods they need are added by themselves. **Make the game**.
- **Install…** shows what goes in, then **Put it in my launcher** opens the same page friends use to join a server (in a new tab, on this computer): pick your launchers, and add shaders or resource packs if you like.
- **Check for updates** lists what an update changes (Minecraft, the loader, each mod), and **Update it in my launcher** brings it in. With **the newest one all the mods support**, the game moves to a new Minecraft once every mod is ready for it; until then it stays where it is and the mods still get their updates. Your worlds are kept: only the mods change.
- **Edit** changes the name, mods, memory or Minecraft version (the mod loader stays once it's installed); **Delete** makes Craft Conductor forget the game. The game and its worlds stay in your launcher.

## Dashboard

**Start**, **Restart** and **Stop** are at the top of every server page. The Dashboard shows four resource cards: **CPU**, **RAM**, **Disk** (space used and free on the server's filesystem), and **Players**. On a phone these form a 2×2 grid. The boxed **Live console** sits alongside **Connected Players** and **Runtime Parameters** on a wide screen, with those details below it on a phone. Performance, updates and activity remain underneath. Stopping warns players and saves the world first.

**When something goes wrong** (the server crashed, or didn't start), the Dashboard says what happened in plain words, shows what Minecraft said, and offers the fixes Craft Conductor can do: **Remove** or **Switch off** the mod to blame, **Add** a mod that another one needs, **Give it more memory** when it ran out, **Let Craft Conductor pick the Java version**, **Use a free port**, **Accept the EULA**, or **Open Backups** when the world looks damaged. After a fix, **Start the server**; **Dismiss** hides the message.

### Performance

While the server runs, **Performance** on the Dashboard shows how well it keeps up: **TPS** (ticks per second; 20 is smooth, under about 17 players feel lag) and, where the server reports it, **ms per tick** (under 50 keeps up), with a small graph of the last hour. Craft Conductor asks the server now and then while the Dashboard is open (Minecraft 1.20.3 and newer, Paper, Purpur, Forge and NeoForge can tell). When it's behind, **What slows a server down** lists the usual causes. With the **spark** mod installed, **Profile 30 s with spark** makes a detailed report of what the server spends its time on, and a link to it appears there.

**Find what's causing lag** (while the server runs) watches the server for 30 seconds with Minecraft's own profiler, then looks through the saved world. The report says, in plain words, where each tick's time goes (mobs and other entities, machines like hoppers and furnaces, loading and making land, ...), which kinds cost most (cows, hoppers, a mod's machine; mods are named), and the busiest places by their coordinates ("around x 1208, z -392 in the Overworld: 410 in all (380 cow, ...)"), each with what to do about it. Craft Conductor also does this by itself when the server keeps falling behind while people play (at most once an hour), and tells you (on Discord too, if set up); switch that off under Settings → Updates.

### Check my setup

**🩺 Check my setup** (in the Server box on the Dashboard) checks what most often stops a server or keeps friends out, and says what to do about each: the server is installed and the EULA accepted, Java is there, the server's memory fits this computer, there's disk space, the port is free (or another program has it), accounts (online-mode), the friends' download port and public address, the router's port forwarding, Windows Firewall, and whether Craft Conductor has an update.

- **Fix buttons:** where Craft Conductor can put something right itself, the check has a button: **Read and accept the EULA**, **Download Java now**, **Use N GB** (memory that fits this computer), **Delete old backups** (keeps the newest 3) when the disk is nearly full, **Use a free port** when another program has the server's, **Turn it on** for account checks, **Use my public IP** for friends' downloads, **Ask my router (UPnP)** to forward the port, and **Let them through Windows Firewall**. Changes to memory, the port and accounts apply at the server's next start. The checks run again afterwards.
- **Windows Firewall:** it reads the firewall's rules (no administrator rights needed) and says whether the server's port and the friends' download port get through on the network you're on. Windows calls many home networks "public", and its own "allow Java?" prompt only ticks private networks, so friends on your Wi-Fi can be blocked even after Allow; answering Cancel there blocks Java altogether. **Let them through Windows Firewall** asks for permission once (Windows' administrator prompt, on this computer only), then adds rules named "Craft Conductor: …" for those ports on private and public networks, and removes Windows' block rules for Craft Conductor's own Java. You can see or delete the rules under Windows Security → Firewall → Advanced settings → Inbound Rules.
- **Test from the internet** (with the server running) asks ifconfig.co, an outside service, to connect to your public address on the server's port: the surest way to know friends outside your home can join. It runs only when you press it.
- **Report for a bug report** downloads a zip with the checks, versions, the server's settings and the ends of the logs, with passwords, keys, webhooks, invite secrets and players' IP addresses taken out. Look through it, then attach it to a [bug report](https://github.com/silverWRX03/craft-conductor/issues/new/choose).

### Playing on the same computer

**Play on this computer** (on the Dashboard, in a browser on the server's own computer) sets up this computer's Minecraft for the server, the same way friends' Craft Conductor does: the right version, mod loader and mods, added to the launchers you pick, joining at `localhost`. Press it again after the server updates.

Before it starts, Craft Conductor says what running both on one computer means, with this computer's numbers:

- **Resource heavy:** the game and the server both take a lot of memory (RAM) and CPU. Craft Conductor adds up the server's memory, Minecraft's and about 3 GB for everything else; if that's more than the computer has, it says so, and both would lag or crash. Give the server less memory (Settings), choose less for Minecraft, or play on another computer.
- **Lag spikes:** when players join or the server loads new terrain while you're in an intense moment, the game can drop frames and the server can lag (TPS).
- **Heavy modpacks:** a heavy modpack (100+ mods) or a large public server (15+ players) strains a personal computer heavily and isn't recommended; Craft Conductor says how many mods the server has and how many players it allows, and flags 100+ mods.

The general warning has **Don't ask me again**; a memory shortage or a heavy server is always pointed out.

## Console

Minecraft's live output. Type a server command (without the `/`, e.g. `say hello`) and press **Send**; the up/down arrows recall earlier commands. One command at a time: a command with a line break or other control characters is refused (a line break would sneak in a second command). **Logs folder** and **Crash reports** open those folders (on the server's own computer).

## Players

Players online and players who have joined before, with **Op/De-op**, **Kick**, **Ban/Pardon** and **Whitelist**. The **Whitelist** card turns it on (only listed players can join) or off. **Add or manage a player** works for people who haven't joined yet.

**Asking to join:** when the whitelist is on, friends setting up with your invite can send their Minecraft name. They appear at the top of the Players page (and the Dashboard says so): **Allow** adds them to the whitelist, **Ignore** drops the request. A browser notification can tell you too (Craft Conductor settings → Sounds & notifications → Notifications). Only someone with your invite can ask, and requests are limited.

**Player activity** (at the bottom of the Players page): who played over the **Last 7, 30 or 90 days**, with their time played, visits and when they were last seen, and a grid of the week, one square per hour, darker when more people are usually on (your computer's time). After a few days of play it names the **quietest time** (usually nobody on, preferring the early morning) and the busiest, and **Restart every day at this time** makes that the scheduled restart (Settings → Schedule). Craft Conductor notes each visit as players join and leave (in `.craft-conductor/activity.jsonl`, kept for 90 days); nothing is sent anywhere.

## Mods

Installed mods with their versions: **Download mods** (the mod browser), **Local files**, mark a mod required or optional, **Remove** it (with the mods it needed, if nothing else needs them), and **Mod config files** to edit a mod's settings in the page (with colours for TOML, JSON, YAML and more; files reached through a link, such as a config folder shared between servers, are left out, so the editor never changes a file outside the server). **Test these mods** checks a set of mods in a throwaway server, so your world is never touched; if they don't start together, **Find the culprits** adds them back a group at a time until it knows which ones clash. Changes apply at the next restart.

**Known conflicts:** when other people found that mods on this page don't work together (on the same loader and Minecraft version), a warning says which, and how many people reported it. It comes from Craft Conductor's shared list of mod conflicts (see Craft Conductor settings → Connections → Mod conflicts). If your server starts fine, you can ignore it.

**Paper and Purpur servers (plugins):** the page is called **Plugins**. **Download plugins** searches **Modrinth** and **Hangar** (PaperMC's own plugin site; pick it as the source): tick plugins and press **Add selected**, and Craft Conductor keeps them updated with Minecraft like mods, checking each file (Hangar's SHA-256). A plugin Hangar only links to elsewhere is listed to download yourself. **Plugins you added yourself** (jars dropped into the plugins folder, or uploaded with **Local files**) can be **switched off** (kept as `.jar.disabled`), switched back on, or removed. Plugin settings are under **Mod config files** (the `plugins/<plugin>/` folders), with `purpur.yml`, `bukkit.yml` and `spigot.yml` from the server folder (Purpur's own settings are in `purpur.yml`).

**Saved mod lists:** **Save the current mods** under a name, and **Switch to it** later: the mods you had are saved first as "Before …", so you can always switch back. Craft Conductor offers to install the switched list right away (the server restarts after the countdown). **⬇** downloads a list as a file, and **Load a list from a file…** adds one, say from another server. The friends' extra mods are part of each list.

## Updates

**Show why** checks builds for the selected Minecraft version and server type. Green means a release build is available, yellow means only early builds, red means none, and gray means compatibility could not be checked. A failed lookup never means ready. Local JAR files appear as unknown: identify them on **Mods**, or disable them before changing Minecraft versions. Updates to managed mods on the current Minecraft version remain available. Explicitly choosing a Minecraft version still respects the setting to wait for every mod.

Craft Conductor checks for updates by itself and applies them when it's safe:

- **Mod updates** for your Minecraft version are applied at the next restart.
- **A new Minecraft version** is only used once every mod supports it. Until then, **Show why** lists every mod in green (ready), yellow (ready, but only with an alpha/beta build) or red (no build yet), and the loader.
- Before every update Craft Conductor makes a backup; if the new version doesn't start, it rolls back by itself. Players get an in-game countdown first.
- If that backup can't be made (the disk is full, say), the update isn't done: the server keeps the version it has and is started again, and you're told why.
- If Craft Conductor is stopped in the middle of an update (the computer turns off or crashes), the next start puts the backup back before the server runs, so it never runs half-updated, and you're told. That update isn't tried again by itself: update from this page to try it again.
- Once a month, Craft Conductor reminds you which mods are holding the server back, so you can decide to drop them.
- **Rehearse it on a copy first** (when an update is ready) tries the update before it touches your server. Craft Conductor copies the server and its world (saving is paused for a moment while it copies), installs the update on the copy and runs it for the time you pick under **Watch it for**, on a private port nobody can join. The report says whether it started and how long that took, how well it kept up (TPS: 20 is perfect), how often it fell behind, and which mods wrote warnings or errors in the log (open a mod to see its lines). Then **Update for real** does the real update (with its backup, as always). If the copy didn't start or stopped by itself, the report names the mod it blames; the button becomes **Update anyway**, but it's better to update or remove that mod first. **Apply update ✓** means this exact update has worked on a copy.
- A rehearsal needs free disk space for a copy of the server, and makes the computer work harder while it runs. While the real server runs, the copy gets less memory if the computer is short of it (the report says so, and the copy may seem slower than the real update will be). The copy is deleted afterwards.
- **Settings → Before a new Minecraft goes in by itself, try it on a copy of the server first:** automatic updates to a new Minecraft version are rehearsed first. If the rehearsal fails, the update is held back and you're told (on Discord too, if it's set up); rehearse again or update from the Updates page when you've looked. Mod updates for the same Minecraft aren't rehearsed.
- **Test a beta version** tries a snapshot or pre-release on a copy of the server.

## Backups

**Create backup** saves the server (worlds, mods, configs) as a `.tar.gz`, even while it runs. Craft Conductor also backs up before every update. The newest 10 are kept (change it in Settings).

Each backup is a **snapshot** of the whole server: besides the files, Craft Conductor notes the Minecraft version, the mods, the server's settings, its mod config files and Craft Conductor's own settings for it. So the list says, for each backup, **what changed since the one before** (mods added, removed or updated, a new Minecraft, settings, config files, the world's size), and **Roll back to this** (with the server stopped) first lists exactly what it will undo, then puts all of it back: the world, the mods, the configs, and Craft Conductor's settings and mod list. Backups made by Craft Conductor before 0.15 only hold the files: **Restore** puts those back, and an update check then puts the mod list right.

**Restoring safely:** a backup is unpacked next to the server first, and the server is only replaced once that worked. A backup that's damaged or cut short, one holding a file or link that would end up outside the server's folder, or one bigger than the free disk space is refused, and the server is left exactly as it was. A backup cut short (the disk filled up, or Craft Conductor was stopped while making it) is never listed, and its unfinished file is removed.

- **Can be restored:** each backup is read back right after it's made (every file, and the world's `level.dat`), and marked **✓ checked**, or says what's wrong with it (a message tells you too). **Check** reads an older one.
- **Put back an area…** (with the server stopped) undoes damage in one place, like griefing or a creeper crater, and keeps everything else in the world as it is now. Type two opposite corners (the x and z numbers F3 shows in the game) and pick the Overworld, the Nether or the End. The chunks there go back to how they were in that backup: blocks, chests, animals and villagers; players' inventories don't change. Craft Conductor backs up the world first, so you can undo it.

To back up by itself, set **Make a backup** under Settings → Schedule. To keep backups safe from a broken disk, set **Also copy every backup to** under Settings → Backup copies: a USB drive, or a folder OneDrive, Dropbox or Google Drive syncs. Each backup is copied there too, in a folder named after the server, keeping the newest few. If the drive isn't plugged in, the backup is still made and the copy is skipped.

## Java

Craft Conductor downloads the right Java (Eclipse Temurin) for each Minecraft version and keeps it updated. You can force a version on this page if a modpack needs it; "auto" follows Minecraft.

## Settings

The server's version and upgrade choices, memory (with Aikar's flags above 16 GB), port, name and Minecraft's settings.

**Minecraft version:** **Newest version your mods support** (recommended: it moves up once every mod works on the next one), **Only the newest version** (waits until every mod supports the very newest), or **Stay on this version** (mods still update). **Mod builds to use:** releases only, or betas and alphas too (less stable).

**Limits** (for several servers on one computer), from the next start:

- **CPU cores it may use:** **All** (the default), or a number: the server then only uses that many of the computer's cores, leaving the others for other servers and everything else. Not on Macs (macOS doesn't allow it).
- **Lower priority:** the computer serves this server after everything else when it's busy. Good for a server friends use now and then, next to your main one.

**Schedule:** restart the server and make backups at set times: **Every day at…**, **Every week on…**, **Every few hours** (backups), or **Custom (cron)** for anything else (five parts: minute, hour, day of the month, month, day of the week; for example `30 5 * * 1-5` is 5:30 on weekdays). Times are this computer's; the next run is shown. A scheduled restart gives players the in-game countdown first, and **Skip a scheduled restart while players are online** leaves them be. The same settings are `[schedule]` in `craft-conductor.toml`.

**Backup copies:** see Backups.

**Web map:** a live map of the world that you and your friends open in a browser. **Add BlueMap** (3D, looks like the game; it needs more disk space and a while to draw the first time) or **Add Dynmap** (flat, like a road map; lighter). Only the maps that have a build for your server's Minecraft version and server type are offered (Craft Conductor asks Modrinth, and remembers the answer for a while); when neither has one yet, the card says "BlueMap and Dynmap don't support Minecraft X yet", and it offers them again once they do. A map you added that has no build for a newer Minecraft counts in **Show why** on the Updates page, like any other mod. Craft Conductor adds it from Modrinth and offers to install it now (the server restarts after the countdown). The first time the server starts with it, the map sets itself up. BlueMap draws with Minecraft's own textures, which it downloads from Mojang, so it waits for **OK, download them**. Then **Open the map** (BlueMap uses port 8100, Dynmap 8123; **Change port** picks another, from the next restart). The Dashboard shows **See where everyone is on the map** while it runs. The address on your network is shown too; for friends outside your home, forward the map's port on your router like the game's. Anyone with the address can see the map. Remove it on the Mods page to stop it.

**World tools** (while the server runs; they use its own commands):

- **Game rules:** keep inventory, the day and weather cycle, mob griefing, fire spread, phantoms, how many players must sleep, and more, each with what it does. **Another game rule** sets any rule by name, for power users.
- **World border:** keep the world to a size (blocks wide) around a centre, so it stays manageable and players can find each other.
- **Pre-generate terrain:** making new terrain is the heaviest thing a server does; generating it ahead of time avoids lag spikes when people explore. It uses the free **Chunky** mod: **Add Chunky** installs it, then pick a radius and **Start** (with **Pause**, **Continue** and **Cancel**) and watch the progress. **Export server** saves everything (worlds, mods, configs, settings, player lists, and optionally backups) in one `.zip` to move to another computer: install Craft Conductor there, then **Servers → Import a server...**.

## Friends: playing with friends

On the server's **Friends** page, switch on "Make a download for friends". Then:

1. Copy an invite link and send it (by Discord, text or email). There's a **local link** for friends on your Wi-Fi and an **internet link** for everyone else. **Post to Discord** posts it for you.
2. Your friend clicks it, presses **Download**, and runs the file. Craft Conductor sets up their game (see the next section). Next time, the link opens their Craft Conductor directly.

For power users, **Advanced: invite codes and security** shows the raw invite codes (for `craft-conductor join <code>`).

**For friends outside your home:** press **Use my public IP** (or type your address under Craft Conductor settings → Connections → Sharing with friends), and forward two TCP ports on your router to this computer: the Minecraft port (25565 for the first server) and the friends' port (8766 unless you changed it).

- **Let Craft Conductor do it:** **Craft Conductor settings → Connections → Sharing with friends → Open the ports on my router by itself (UPnP)**. It's off until you switch it on, and it asks you first, because it makes your server reachable from the whole internet, not just your friends: anyone can try to connect, and a weakness in Minecraft or in a mod could put this computer at risk. While it's on, the page says so. Craft Conductor asks the router to forward each server's Minecraft port and the friends' port to this computer (never the control panel's port, or a server's RCON port), renews that while it runs, and takes the ports back when you switch it off or quit Craft Conductor. It shows which ports worked, your router's internet address, and warns when forwarding can't help (your provider shares one address between homes, called CGNAT, or there are two routers). **Check my setup** shows it too. Keep the whitelist on while it's on.
- **By hand:** many routers have UPnP switched off. The Help page has pictures; every router is different, so check its manual if you get stuck.

**What friends get:** the Minecraft version, mod loader and every mod that runs on players' computers (server-only mods are left out), plus the mods you add under **Mods for players**, and the memory you choose for their Minecraft. Mods that server mods need on players' computers are added by themselves (a message says which and why).

**Mods for players** land on the right side. A mod that only runs on players' computers (a minimap, say) stays in the friends' download. A mod that runs on both sides (a recipe viewer, for example) is also added to the server's own mods, with the mods it needs, resolved the same way as any server mod: a message says "X also runs on the server, so it was added there too, with Y", and the list marks it **also on the server**. If the server has no build of it for its Minecraft version, the message says why, and players still get it. When you **Remove** one from the list, Craft Conductor asks whether to remove it from the server too (**Cancel** keeps it there).

**How long links work.** Invite links are made to be shared (in a Discord channel, say), so they aren't single-use: everyone with the link can use it. Instead, a link stops working by itself after the time picked under **Links work for**: 1 day, 7 days (the usual), 30 days, or **Until I make new ones**. The page shows when the links stop, and **Post to Discord** says it in the message. Changing it starts the time again from now, and new links use it too. **Stop these links** stops them at once; **New links** makes new ones, and the old ones stop working. Once a link has stopped, nobody can set up with it any more; friends who already set up keep playing, but need a new link to update their game. Want only the people you know to play? Keep the whitelist on: a link lets friends download the setup and **ask to be let in**, and you decide.

**Security:** the link opens Craft Conductor's invite page on GitHub, and the invite itself is after the `#`, which browsers never send anywhere. Friends' Craft Conductor connects to your computer only over HTTPS, and only to your computer: the invite carries the fingerprint of your Craft Conductor's certificate, and anything else is refused. The Craft Conductor program itself always comes from GitHub, never from your server. The friends' port never gives access to the control panel.

### No port forwarding? playit.gg

If your router or internet provider doesn't let you forward ports, [playit.gg](https://playit.gg) can: its program runs on this computer and gives your server an address on the internet that friends join through.

**playit.gg is an outside service**, run by its own company, not by Craft Conductor. When playit.gg has problems, or its program isn't running on this computer, friends can't connect through it, however healthy your server is, and Craft Conductor can't fix that. Friends on your own network can still join with the Local link.

1. Download playit from playit.gg, run it, and claim it in your playit.gg account (it shows a link).
2. In playit.gg, add a **Minecraft Java** tunnel to this server's port (25565 unless you changed it). Put the address it gives you in the server's **Settings → playit.gg tunnel**.
3. For friends' downloads (the invite) from outside, add a **TCP** tunnel to the friends' download port (8766 unless changed) and put its address, with the port, in **Craft Conductor settings → Connections → Sharing with friends → No port forwarding? Use playit.gg**. Internet invites then use it.

With a tunnel set, the Dashboard shows **playit.gg tunnel**: Craft Conductor asks the server for its status through the tunnel, the way a friend's game does, and says whether it's **working**, whether it answers with a **different server** (point the tunnel at this server's port), or can't be reached. It also says if the playit program isn't running here, and links to playit.gg's status page. Craft Conductor checks every 5 minutes and notes in the activity (and on Discord, if set up) when the tunnel stops or starts working. **Check my setup** includes it too.

### Bedrock players (phones, tablets, consoles)

Friends playing Minecraft on a phone, a tablet, Windows (the Microsoft Store version) or a console can join a Fabric, Quilt, NeoForge, Paper or Purpur server through [Geyser](https://geysermc.org). On the Friends page, press **Let Bedrock players join**: Craft Conductor adds the Geyser and Floodgate mods from Modrinth and offers to install them now (the server restarts after the countdown). Bedrock players then use **Play → Servers → Add Server** with your address and the Bedrock port (19132 unless Geyser's config says otherwise), and sign in with their own Microsoft account; they don't need Java Edition.

The setup checks both mods first. When a compatible Geyser build is labeled beta or alpha, it offers that build with an early-build confirmation. Accepting applies to the bridge mod and its dependencies; other mods keep their existing release policy.

- For friends outside your home, also forward **UDP** port 19132 on your router (Bedrock uses UDP).
- Xbox, PlayStation and Switch can't add servers by themselves; GeyserMC's guide shows the workarounds.
- With the whitelist on, add a Bedrock player with the console command `fwhitelist add <name>`. Their names start with a dot (.) in game.
- Remove Geyser and Floodgate on the Mods page to turn it off.

## For friends: joining a server

1. Click the invite link you were sent. It opens a page that says you're invited: press the big **Download Craft Conductor** button (it picks your computer's version). It downloads the friends' Craft Conductor (`craft-conductor-join-...`): the same Craft Conductor, which always opens into joining a server, even on a computer that runs servers too.
2. Open the file you downloaded. (On Windows, if it says it "protected your PC", choose **More info → Run anyway**; on a Mac, right-click it and choose **Open** the first time.) Craft Conductor finds your invite by itself and checks it's really your friend's server. If it asks, press **Copy the invite** on the invite page and paste it into Craft Conductor.
3. Tick your launchers: the Minecraft Launcher, Prism Launcher, the Modrinth App and/or CurseForge (ones found on your computer are already ticked), and choose how much memory Minecraft gets.
4. **Make it yours (optional):** add **shaders**, **resource packs** or **more mods** that only run on your computer. Each opens a browser like the server's (search, sort, categories, the item's page on the right); tick what you want and press **Add selected**. Shaders bring their shader loader (Iris, or Oculus on Forge); mods bring what they need, listed under them. **More mods** lists only mods that run on your computer alone: the server's own mods come with the download already.
5. Press the button to set it up. Each launcher gets its own copy, in a folder of its own: your other worlds and installations aren't touched. The Modrinth App gets a `.mrpack` to import, and CurseForge a `.zip` (Create Custom Profile → Import).
6. In your launcher, pick the server's name and press Play. On Minecraft 1.20 and newer it joins straight away; otherwise it's in your multiplayer list.

**The page says "Paste your invite" or "This invite link isn't complete"?** The app you opened the link in cut it short (the invite is the long part after the `#`). Copy the whole link again (in Discord: right-click it → **Copy Link**) or the invite code, paste it into the box and press **Open invite**.

**Closed Craft Conductor's page by mistake?** Craft Conductor keeps going. Open Craft Conductor again (or press **Open in Craft Conductor** on the invite page) and its page comes back, with the progress or results. While it's setting Minecraft up, your browser asks before closing the tab.

**Already have Craft Conductor?** On the invite page, press **Open in Craft Conductor** (Windows and Linux; on a Mac, press **Copy the invite** and open Craft Conductor).

**When the server updates**, click the invite link again and press **Open in Craft Conductor**, or open Craft Conductor and press **Update** next to it under **Servers you've joined**. Craft Conductor checks each one when it opens and marks those that **changed** since you set up (a new Minecraft or different mods), so you know when to update.

**The server has a whitelist?** The setup page shows **Ask to be let in**: type your Minecraft name (the one you play with) and press it. The owner lets you in with one click. If some of your extras don't work on the new Minecraft yet, Craft Conductor tells you first: **Continue** removes those mods and switches those shaders/resource packs off (you can switch them back on, but the game may crash), or **Cancel** keeps everything as it is (you can't join the updated server until you continue).

Craft Conductor never asks for your Microsoft password: your launcher signs you in.

**Another language?** The invite page and Craft Conductor's joining page follow your browser's language; pick another at the bottom of either page (English, Español, Português, Français, Deutsch, हिन्दी, 中文, Tiếng Việt, العربية, 한국어).

## Remote access and phones

By default only the server's own computer can open the control panel: it listens on `127.0.0.1` (this computer only), even on a computer without a screen, until you turn on access from other devices. **Craft Conductor settings → Connections → Remote access & phones** (also a button on the New server page) lets other devices in:

- It needs a **strong password**: 12+ characters with an uppercase letter, a lowercase letter and a special character. PINs don't work from other devices.
- **Pair a phone** by scanning the QR code with its camera and opening the link. The code works once, for five minutes; **Cancel this code** stops it sooner (so does turning off access from other devices, removing every phone or changing the password). The phone signs in by itself afterwards, with its own key. At the **Tailscale, secure** address, the phone then offers to install the app (see The phone app); at other addresses Craft Conductor opens in the phone's browser, and the dialog says so. No secure address yet? **Set up the secure Tailscale address** is right there.
- **Pair with a code:** the code is also shown under the QR code (like `ABCD-EFGH-JKLM`). On the phone's sign-in page, choose **Pair with a code** and type it. That's how an iPhone's Home Screen app is paired: it doesn't share Safari's sign-in.
- Before making the code, choose what the device may do: **Helper** gets the everyday controls (start, stop, restart, backups, updates, players, and letting in friends who ask); **Viewer** can only look. Neither can change settings, mods or files, use the console or change the password.
- **Co-admins:** pair the phone or computer of a friend who helps run the server the same way, as a helper or a viewer. What each device does shows in the activity with its name.
- Each paired phone is listed with when it was last used, and can be signed out on its own; changing the password signs out every phone.
- Away from home, use **Tailscale** (free) rather than opening the control panel's port on your router. For HTTPS, give Craft Conductor a certificate (for example from `tailscale cert`).

### The phone app

Craft Conductor can live on your phone's home screen like an app, and send **notifications** even when it's closed: when a server crashes or won't start, a friend asks to join, an update is held back, the lag finder finds something, and everything else Craft Conductor would post to Discord. It's set up under **Craft Conductor settings → Connections → Phone app**:

1. **A secure address.** Phones only install web apps and deliver their notifications for a page with a real certificate. The easy way is **Tailscale** (free for personal use): install it on this computer and your phone, signed in to the same account, then press **Check for Tailscale** and **Use Tailscale for the phone app**. The control panel gets an address like `https://your-computer.your-tailnet.ts.net` that only your own devices can reach; it isn't on the internet. (The first time, Tailscale may ask you to switch HTTPS on for your account: follow the link, then press the button again.) It needs a strong password first, because the phone signs in as another device. A Cloudflare Tunnel or your own domain with a real certificate works too (add its name to `[web] allowed_hosts`).
2. **Put it on your phone.** Pair the phone under **Remote access & phones** with the **Tailscale, secure** address (Tailscale on on the phone), or open the secure address on the phone and sign in. After scanning the pairing QR code:
   - **Android:** the phone is paired, then **Install the app** puts Craft Conductor on the home screen (or, in Chrome's menu, **⋮ → Install app** or **Add to Home screen**). If there's no such option, the QR code opened inside the camera app: open the page in Chrome first.
   - **iPhone or iPad:** the page says **Get the app first**: press **Share → Add to Home Screen**, open Craft Conductor from the Home Screen, choose **Pair with a code** and type the code the page shows. iPhones only allow notifications for apps added this way, and the Home Screen app doesn't share Safari's sign-in, which is why it's paired there. (**Just use it in Safari** pairs Safari instead.)
3. **Turn on notifications here**, in the app, under **Craft Conductor settings → Connections → Phone app**. **Send a test** checks it works. Each device with notifications on is listed; **Remove** stops them for that device, and **Turn off** does it on the device itself.
4. **Choose what you hear about.** Under **Notify this device about**, tick what this device should get: a server crashed or wouldn't start, friends asking to join, updates, lag, backups, the playit.gg tunnel, this computer (disk space, CPU, memory), a server started (off at first) and everything else. Each device has its own choices, kept when notifications are turned off and on again.

The app follows the phone's light or dark setting (unless you pick Light or Dark with the theme slider), and the phone's status bar matches.

**On the phone, the top of the page says where you are.** Opened at a plain address (like `http://192.168.1.50:8765`, the home network address, or a pairing code made for it), Craft Conductor is a web page in the browser: phones won't install it as an app from there, and "Add to Home Screen" only makes a bookmark that opens a browser tab. The message says so, and links to the secure Tailscale address when there is one. At the secure address it offers **Install the app** (or says how: Share → Add to Home Screen on an iPhone), and once it's installed, **Turn on notifications**. **Not now** hides it for two weeks. A paired phone, which can't open Craft Conductor settings, turns its notifications on here. When pairing a phone, the **Tailscale, secure** address is picked first, and the dialog says when another address will only open in the browser.

Notifications go through your phone's own push service (Apple's, Google's, Mozilla's or Microsoft's), encrypted so that only your phone can read them. A paired phone can turn its own notifications on and off, even as a viewer.

## Craft Conductor settings

Choose a section from the menu: **Appearance** (Language and Display), **Sounds & notifications** (Sounds, Notifications and Warnings), **Sign-in & security**, **Connections** (Remote access & phones, Phone app, Sharing with friends, CurseForge, Discord and Mod conflicts), or **About & updates**. Switching sections preserves what you typed. Settings that need saving have a Save button.

- **Sign-in:** change your password or PIN. There's always one.
- **Remote access & phones:** see above.
- **Sharing with friends:** the friends' port and your public address, a playit.gg tunnel, and **Router**: open the ports on your router by itself (UPnP).
- **CurseForge:** the downloads of Craft Conductor come with Craft Conductor's own CurseForge API key, so CurseForge works without one of your own. If you prefer your own (free, from console.curseforge.com), enter it here; it's used instead.
- **Discord:** add a bot to post invites to a channel. **Live status message:** pick a Discord server and channel, and **Keep a status message there**: one message that always shows whether each server is online, how many are playing and its Minecraft version (and your public address, if set). Craft Conductor edits it as things change and says when Craft Conductor is closed; **Stop** ends it. The bot never reads the channel.
  - **Whitelist through Discord:** friends type `/whitelist` and their Minecraft name in your Discord server (with several Minecraft servers, they pick one too). Only they see the answer. Pick what happens: **Ask me first** puts them on the Players page to **Allow** or **Ignore** (and tells you, like any request to join), or **Let them in straight away** adds them to the whitelist at once, optionally **only members with a role** you pick (others are asked for instead). **Turn on** starts it; the card shows whether Craft Conductor is listening. It works while Craft Conductor is open. If `/whitelist` doesn't show up in Discord, add the bot again with **Add it to another Discord server** (bots added before Craft Conductor 0.18 lack the permission for commands) and restart Discord. The bot still never reads messages: Discord only sends it the command.
- **Notifications:** **Notify me in this browser** shows a notification when a server stops unexpectedly, an update is ready, someone joins (off by default) or something Craft Conductor was doing fails, while Craft Conductor's tab is in the background. The browser asks first. It works when the address is localhost (or HTTPS).
- **Display:** kept in this browser.
  - **Size:** how big text and buttons are: **Automatic** (bigger on big screens), Smaller, Normal, Larger or Largest.
  - **Contrast:** **High contrast** gives black or white backgrounds, stronger text, borders on every button, underlined links and a thick outline around what the keyboard is on. **Automatic** turns it on when your computer asks for more contrast.
  - **Motion:** **Less motion** stops the animations (sliding panes, the spinning and drifting). **Automatic** follows your computer's "reduce motion" setting.
- **Language:** Craft Conductor's pages in English, Español, Português, Français, Deutsch, हिन्दी, 中文, Tiếng Việt, العربية (right to left) or 한국어. **Automatic** follows your browser's language. The choice is kept in this browser; the buttons, menus and short messages are translated by machine (so they may have mistakes), and this manual stays in English.
- **Sounds:** short sounds when you press a button (a soft click; rising notes for Start, Save and Install; falling notes for Stop and Delete), when something goes wrong, and a chime while Craft Conductor is open when a server finishes starting or a friend asks to join. They're on at **Quiet** at first: **Volume** (**Off**, **Quiet**, **Normal**), and a tick for each kind of sound. On an Android phone, **Vibrate on button presses** buzzes too (iPhones don't let web apps vibrate; on an iPhone the silent switch keeps them quiet). Kept on this device: each phone and computer has its own choice. Moving around with the keyboard never makes a sound, and a sound is never the only sign something happened.
- **Fingerprint or face sign-in:** sign in with this device's fingerprint, face or screen lock (a passkey) instead of typing the password. On the device, sign in with the password, then press **Add fingerprint or face sign-in on this device**; next time the sign-in page shows **Sign in with fingerprint or face**. It needs a secure address (on a phone, the Tailscale one; see The phone app) or `localhost` on the server's computer, and it only works at the address where it was added. Each one is listed with **Remove**; choosing a new password removes them all (like paired phones). You need your own password first. Not available when the password is set in `craft-conductor.toml`.
- **Mod conflicts:** **Share mod conflicts anonymously** (off until you switch it on). When **Find which mods break it** finds a mod that doesn't work, Craft Conductor sends only the mod loader, the Minecraft version and the ids of the mods involved to Craft Conductor's relay, nothing about you or your server. Once three different people report the same conflict, it's on the shared list, and the Mods page warns anyone who has those mods together (everyone gets the warnings, whether they share or not). The list is fetched at most once a day.
- **Warnings:** how many warnings you've hidden with "Don't ask me again", and **Show all warnings again**.
- **About Craft Conductor:** the version, **Check for Craft Conductor updates**, the Craft Conductor folder, the notice and open-source licenses. Craft Conductor also checks by itself: when a new version is out, a message offers to install it (it stops your servers cleanly and restarts).
  - **Updates:** **Stable versions only (recommended)**, the default, or **Beta versions too (early, less tested)**: betas come out before a version is released, for people who like to try things first.
  - Every update is downloaded completely and checked against the checksum published with it (the release's `SHA256SUMS.txt`) before anything is replaced. If it doesn't match (a damaged, cut-short or tampered download), nothing changes and the version you have keeps running. Craft Conductor never installs an older version than the one you have, so after leaving beta, the next update is the next stable version.
- The **Light / Dark** slider switches the whole app between themes and remembers your choice. On desktop it is in the top bar; on phones and tablets it is inside the hamburger navigation menu at the top left. Escape or tapping outside closes the menu.
- Panels, dialogs, settings, mods, backups and the invite pages share the Industrial Silver, Obsidian and Magma theme, with square edges, raised widgets and a recessed console.

### Keyboard and screen readers

Everything in Craft Conductor works with the keyboard and a screen reader (NVDA, JAWS, VoiceOver, TalkBack, Narrator).

- **Tab** and **Shift+Tab** move between buttons, links and fields; **Enter** or **Space** presses a button. A clear outline shows where you are.
- The first **Tab** on a page reaches **Skip to main content**, which jumps past the menu. After you pick a page in the menu, the keyboard starts at the top of that page, and the browser tab's title names the page and the server.
- A window that opens (a question, Check my setup, a mod's config files…) keeps **Tab** inside it until it closes. **Escape** closes it (the same as its Close or Cancel button), and the keyboard goes back to where you were.
- In the config file editor, **Tab** indents. To leave the editor, press **Escape**, then **Tab**. **Ctrl+S** saves.
- On the map preview, the arrow keys move the map, and **+** and **-** zoom.
- Messages (Saved, errors, a server starting or stopping) are read out by screen readers as they appear.

## Troubleshooting

**The server won't start or setup failed.** The message says where the failure report is (in the server folder, under `.craft-conductor/logs`). It has the error, what Craft Conductor was doing and the server's last output; Minecraft's own log is `logs/latest.log` in the server folder. If a mod is to blame, Craft Conductor names it: remove it or wait for an update.

**"Port ... is busy."** Another program (or another server) uses that port. Pick another on the server's Settings page, or for the friends' port under Craft Conductor settings → Connections → Sharing with friends.

**Friends can't connect from outside.** Check both ports are forwarded to this computer's local address, that you pressed **Use my public IP** again (home addresses change), and that your internet provider allows it (some don't; Tailscale or a VPN works then).

**"That invite is from an older Craft Conductor."** Invites changed in Craft Conductor 0.9 (to HTTPS). Update Craft Conductor on the server, then send friends the new invite from the Friends page.

**"This invite has expired."** The invite link's time ran out, or the server's owner stopped it. Ask them for a new link (on their Friends page: **New links**). You can still play on the server; the new link is only needed to set up or update your game.

**"The server's security certificate doesn't match the invite."** Craft Conductor refused to connect because the server isn't the one the invite is for. Ask for a new invite; if it happens again, someone may be interfering with the connection (on public Wi-Fi, say).

**Something's wrong and I don't know what.** Open the server's Dashboard and press **🩺 Check my setup**: it goes through the usual causes and says what to do. For friends who can't connect from outside, press **Test from the internet** there.

**I closed the browser tab.** Craft Conductor and your servers are still running. Open Craft Conductor again from its icon (or go to the same address in your browser): you're back where you were, and a server being created shows **See progress** on the Servers page.

**Forgot the password.** In a browser on the server's own computer, choose "Reset it to PASSWORD" on the sign-in page, or run `craft-conductor web-password --reset` there.

**A CurseForge mod can't be downloaded.** Its author blocks downloads by other apps. The Updates page lists it under "Manual downloads needed" with a link: download it and upload it there; Craft Conductor checks it's the right file.

**"NeoForge's download site lists only … right now".** NeoForge's own site sometimes has an incomplete list of its builds for a few hours. A new NeoForge server can't be made until NeoForge fixes it: try again later. Servers that already run NeoForge keep the NeoForge they have, and still get their mod updates.

**"Its file has a name that isn't safe to save".** The mod's author gave that build's file a name that would put it outside the mods folder, or one Windows can't use. Craft Conductor leaves it out (or waits, if the mod is required) until the author fixes it.

**"The world's folder name (level-name in server.properties) must be a plain folder name".** The world folder setting points outside the server's folder (it can come with a modpack, an imported server or a backup). Pick a plain name, like `world`, under the server's Settings → World folder name.

**"Left … file(s) out of …" in the activity log.** A world, modpack, server export or backup held files with names that could have been written outside their folder, or that Windows can't have (such as `NUL`, or a name with `:`). Those files were skipped and everything else was brought in. If something you need is missing, look at where the file came from.

**"There isn't enough free disk space for …".** Importing, restoring or unpacking it would have filled the disk (Craft Conductor keeps 256 MB free for Minecraft to save the world). Free some space, or delete old backups or exports, and try again.

**"Craft Conductor was stopped in the middle of something".** The computer turned off, or Craft Conductor was closed, during an update, a restore or a world swap. On the next start Craft Conductor put things back the way they were before (from the backup made before the update). If it says the backup couldn't be put back, free some disk space and start the server again, or pick an earlier backup on the Backups page.

**The day theme stays dark.** Your browser is forcing dark mode on pages (Chrome's "Auto Dark Mode for Web Contents", or a dark-mode extension). Craft Conductor 0.8.1 and newer keep the day theme light anyway.

**Windows: "The process cannot access the file because it is being used by another process".** Usually antivirus scanning a new download. Craft Conductor 0.8.2 and newer wait and retry, and show the real reason if a download fails.

## Where Craft Conductor keeps things

- **Your servers:** the `craft-conductor` folder in your home folder (for example `C:\Users\you\craft-conductor\servers\...`), one folder per server. Each has `craft-conductor.toml` (its settings), `server/` (Minecraft, the world and mods) and `backups/`.
- **Craft Conductor's own settings:** `craft-conductor/.craft-conductor/` (sign-in, paired phones, friends' certificate, CurseForge key and Discord token; readable only by you).
- **Friends' setups:** a folder of their own per launcher; their extras and joined servers are remembered in `.minecraft/craft-conductor/`.

## Command line

Everything also works in a terminal:

```
craft-conductor start              # the control panel with your servers (what double-clicking does)
craft-conductor join <invite>      # set up this computer's Minecraft for a friend's server
craft-conductor status             # what's installed
craft-conductor check / update     # see and apply updates
craft-conductor backup / restore   # back up or restore a server
craft-conductor player ...         # kick, ban/pardon, op/deop and whitelist
craft-conductor web-password       # show or change the sign-in (--set, --pin, --reset)
craft-conductor service install --panel   # Linux: run craft-conductor at boot (this machine only;
                                          #   add --network to open the panel to your home network)
craft-conductor self-update        # update craft-conductor itself (--channel beta for early versions)
```

Run `craft-conductor --help` (or `craft-conductor <command> --help`) for everything.

## Getting help

Found a bug or have an idea? [Report it on GitHub](https://github.com/silverWRX03/craft-conductor/issues/new/choose): a short form asks what happened and your Craft Conductor version (shown at the bottom of the menu). Attach the failure report if there is one (it doesn't contain passwords). What changed in each version, and which version fixed what, is in the [changelog](https://github.com/silverWRX03/craft-conductor/blob/main/CHANGELOG.md).
