# Craft Conductor user manual

Craft Conductor (Minecraft server manager) sets up a Minecraft server on your own computer, keeps it running, keeps it and its mods up to date, and gets your friends' games ready to join. Everything happens in the **control panel**, a page in your web browser.

This manual is also inside Craft Conductor: open **User manual** (or **Help**) in the control panel. It comes with Craft Conductor, so it always matches the version you have and is updated with it. Craft Conductor is in beta: back up anything you can't afford to lose.

> Craft Conductor was called **mcsm** until version 0.16. Nothing changes for you: the command is still `mcsm`, and your servers, settings (`mcsm.toml`) and backups carry on as they are.

## What Craft Conductor can and can't do

**It can:**

- create a Fabric, NeoForge, Forge, Quilt, Paper or plain (vanilla) Minecraft server, with the right Java, mod loader and mods;
- keep it on the newest Minecraft **once every mod supports it**, making a backup before each update and rolling back by itself if the new version doesn't start;
- find mods and the mods they need, test a set of mods before you commit to it, and find which mod breaks a server;
- set up your friends' Minecraft (Minecraft Launcher, Prism Launcher, Modrinth App or CurseForge) with one invite;
- let you manage it from your phone or another computer, or run it on a Linux computer without a screen, or in Docker.

**It can't:**

- make your computer reachable from the internet on every network: friends outside your home need **port forwarding** on your router. Craft Conductor can ask the router to do it (UPnP) when the router allows it; otherwise the Help page shows how;
- make mods work together when their authors haven't; it can only tell you and wait for updates;
- download CurseForge mods whose authors block downloads by other apps (you download those yourself; Craft Conductor gives you the link);
- run your server while your computer is off; it isn't a hosting service. Bedrock Edition isn't supported.

## Getting started

1. Download Craft Conductor for your computer from the [releases page](https://github.com/silverWRX03/craft-conductor/releases/latest): Windows, Mac (Apple silicon) or Linux.
2. Open it. On Windows, if SmartScreen says it "protected your PC", choose **More info → Run anyway** (Craft Conductor isn't code-signed). On a Mac, right-click it and choose **Open** the first time.
3. The control panel opens in your browser. Read and accept the notice (what Craft Conductor does and doesn't do).
4. Sign in with the password `PASSWORD` (in capitals). Craft Conductor asks you to choose your own right away: a password, or a 4–8 digit PIN. A PIN only works in a browser on the server's own computer.

Servers run while Craft Conductor runs. **Closing the browser tab doesn't stop Craft Conductor**: your servers keep running, and anything Craft Conductor is doing (creating a server, an update) carries on. Open Craft Conductor again from its icon to come back to the control panel. **Quit** (at the bottom of the menu) stops everything cleanly.

If closing the tab would lose something that only lives in the page (an upload on its way, settings or a config file you haven't saved, a New server form you've started, mods picked but not added, a mod test's report), your browser asks first ("Leave site?").

> Joining a friend's server rather than running your own? See **For friends: joining a server** below.

### The guided setup

The first time you use Craft Conductor, a message asks whether you'd like the **guided setup**: **Guide me**, or **Skip** (it isn't asked again). It's a checklist in a corner of the page, from making your first server to a friend joining it:

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

**1. Server type.** Fabric, NeoForge, Forge and Quilt run mods; Paper runs plugins (Spigot/Bukkit ones too); Vanilla is plain Minecraft.

**2. Minecraft version.** "Newest version your mods support" is recommended: the server upgrades only once every mod supports the next Minecraft (a "forever server"). Picking a specific version keeps it on that version (mods still update). Tick "Show beta versions" to try snapshots and pre-releases (worlds opened in them can't go back).

**3. Mods** (or plugins):

- **Download mods** opens the mod browser beside the form: search Modrinth (and CurseForge, with an API key), read a mod's page on the right, tick the ones you want, and press **Add selected mods**. Mods that need other mods bring them along.
- **Runs on** narrows Modrinth mods by where they run: server-side and both (the default for a server), server-side only, or both. Tags show where each one runs.
- "Also show mods with only alpha/beta builds" includes less stable mods, with a warning.
- **Local files** adds `.jar` files from your computer. **Modpacks** builds the whole server from a Modrinth modpack.
- **Required** mods decide which Minecraft version the server starts on; every mod holds back upgrades until it supports the new version.
- **Test these mods** checks they work together before you create the server.

**4. World.** A new world (seed, type, structures, hardcore), or **Import a world**: a singleplayer save or a world `.zip` from any Java version.

**World generation & map preview** (under the new world's settings) slides open beside the form:

- **World generation mods** lists Modrinth's world-generation mods (or plugins) that work with your server type and Minecraft version. Ticking one adds it to the server's mods (with what it needs); unticking removes it.
- Type a **seed** (or press 🎲 for a random one), pick the world type and a map size, and press **Preview map**. Craft Conductor makes the world in a private server on this computer (nobody can join it), with all the mods you've picked and the Chunky mod to generate the area, then draws it from above: north is up, one pixel is one block, and ★ is the spawn point. Point at the map to see the coordinates and the biome there.
- **Move around the map:** drag it to move, and scroll (or press **+** and **−**) to zoom, from 4 pixels a block out to 32 blocks a pixel. **⌖ Back to spawn** brings you back. Where the land hasn't been made yet the map is checkered; press **Make this area** and the private server makes the land in view (it asks first when that takes more than a minute), or tick **Keep making the map as I move** and it makes the land as you go. The private server stays on while you explore, and stops by itself after five minutes of not being needed.
- It takes a minute or two the first time (Minecraft and the mods are downloaded) and less for the next seeds with the same mods. Bigger maps and heavy mods take longer; **Stop** cancels it. You can close the panel and carry on: the map is there when you come back.
- **Earlier maps** keeps the seeds you've looked at; **Use this seed** makes one the server's seed.
- **Compare 10 seeds** makes maps of 10 random seeds one after another, with the same mods, so you can pick the one you like (lots of ocean, a big mountain range, a biome you're after). It asks first: it takes a while (each map is a new world) and the computer works hard meanwhile. The maps appear side by side as they're made; press one to look closer and **Use this seed**. **Stop comparing** keeps the maps made so far, and **← Back to the seeds compared** returns to them.
- Maps need Minecraft 1.18 or newer, and aren't available for modpacks or imported worlds. Vanilla servers are previewed with Fabric, which makes exactly the same worlds.

**5. Settings.** The server's name (shown in the multiplayer list), max players, difficulty, game mode, memory and port. Above 16 GB of memory, Craft Conductor offers **Aikar's flags** (tuned garbage collection that avoids lag spikes). **Advanced settings** has the rest of Minecraft's server settings. The whitelist starts **off** (anyone with the address can join) until you turn it on.

**Friends (optional).** Tick "Make a download for my friends" to get an invite for them. **Set up now** opens the mod browser for mods for players' computers (a minimap, JEI...), and **Local files** adds your own. Mods your server's mods need on players' computers are added by themselves.

**Almost done.** Accept the Minecraft EULA and press **Create my server**. Craft Conductor downloads Java, the loader, Minecraft and the mods, then checks the server starts. The progress stays on the page, and the lower part of the screen shows how to open your router for friends outside your home. When it's ready, the server's Dashboard (or its Friends page) opens.

If setup fails, the page says why and where the detailed report is saved; change your choices and try again.

### On another computer (Linux, over SSH)

A spare PC, a home server or a Raspberry Pi 4/5 (64-bit) can run your servers without a screen. On **New server**, under **Or on another computer** (at the bottom of the page, at any step), choose **Install on a Linux computer**, type its address (e.g. `192.168.1.50`) and a normal user name on it (not root), and press **Connect with SSH**. A terminal opens: type that computer's password when SSH asks (the first time, answer `yes` to trust it). Craft Conductor never sees the password. When it finishes, it shows that computer's control panel address and a one-time password; open it and choose your own password. See also the [headless guide](https://github.com/silverWRX03/craft-conductor/blob/main/docs/headless.md) and [Docker](https://github.com/silverWRX03/craft-conductor/blob/main/docs/docker.md).

**A rented server (a VPS)** works the same way: type its internet address, and Craft Conductor ticks **It's a rented server on the internet**. Its control panel then stays private (on the server only) and you reach it through SSH: **🔐 Open an SSH tunnel** (keep the window open), then **Open its control panel** (`http://localhost:8775/`). Open the Minecraft port in the server's firewall (the page shows the command). The [rented servers guide](https://github.com/silverWRX03/craft-conductor/blob/main/docs/rented-server.md) covers what to rent, firewalls and keeping it safe.

## Messages

Everyday messages ("Saved", or what went wrong) appear at the **top of the screen** for a few seconds; click one to dismiss it. When Craft Conductor needs an answer (use Aikar's flags? install an mcsm update? a mod test finished), it asks in the **middle of the screen** with the page blurred behind, and waits until you choose. A long mod test shows its progress at the top while you keep working.

Questions you'll meet again and again ("Stop the server?", "Quit Craft Conductor?", "Update to Minecraft …?", mods with only beta builds, Aikar's flags) have a **Don't ask me again** box, and notices you've read (online-mode is off, a mod test takes a while, closing the tab doesn't stop Craft Conductor) have **Don't show again** or **Got it**. Craft Conductor remembers that in this browser; **Craft Conductor settings → Warnings → Show all warnings again** brings them all back. Questions about deleting or replacing things always ask.

## Your servers

**Servers** lists every server with its state, version, players and port: **Start**, **Open**, **Delete**, and **Folder** (on the server's own computer). **Import a server...** adds one exported from another computer.

### Modded single-player games

Below the servers, **Modded single-player games** sets up modded Minecraft for playing on your own, and keeps it up to date. Craft Conductor isn't a launcher: the game goes into the one you use (the Minecraft Launcher, Prism Launcher, the Modrinth App or CurseForge).

- **+ New single-player game:** a name, the mod loader (Fabric, NeoForge, Forge or Quilt), the memory for the game, and the Minecraft version: a fixed one, or **The newest one all the mods support**. Search Modrinth and **Add** mods (only mods that run on players' computers are listed); mods they need are added by themselves. **Make the game**.
- **Install…** shows what goes in, then **Put it in my launcher** opens the same page friends use to join a server (in a new tab, on this computer): pick your launchers, and add shaders or resource packs if you like.
- **Check for updates** lists what an update changes (Minecraft, the loader, each mod), and **Update it in my launcher** brings it in. With **the newest one all the mods support**, the game moves to a new Minecraft once every mod is ready for it; until then it stays where it is and the mods still get their updates. Your worlds are kept: only the mods change.
- **Edit** changes the name, mods, memory or Minecraft version (the mod loader stays once it's installed); **Delete** makes Craft Conductor forget the game. The game and its worlds stay in your launcher.

## Dashboard

**Start**, **Restart** and **Stop** are at the top of every server page. The Dashboard shows CPU and memory use, who's online, the console, the server's details and whether an update is ready. Stopping warns players and saves the world first.

**When something goes wrong** (the server crashed, or didn't start), the Dashboard says what happened in plain words, shows what Minecraft said, and offers the fixes Craft Conductor can do: **Remove** or **Switch off** the mod to blame, **Add** a mod that another one needs, **Give it more memory** when it ran out, **Let Craft Conductor pick the Java version**, **Use a free port**, **Accept the EULA**, or **Open Backups** when the world looks damaged. After a fix, **Start the server**; **Dismiss** hides the message.

### Performance

While the server runs, **Performance** on the Dashboard shows how well it keeps up: **TPS** (ticks per second; 20 is smooth, under about 17 players feel lag) and, where the server reports it, **ms per tick** (under 50 keeps up), with a small graph of the last hour. Craft Conductor asks the server now and then while the Dashboard is open (Minecraft 1.20.3 and newer, Paper, Forge and NeoForge can tell). When it's behind, **What slows a server down** lists the usual causes. With the **spark** mod installed, **Profile 30 s with spark** makes a detailed report of what the server spends its time on, and a link to it appears there.

**Find what's causing lag** (while the server runs) watches the server for 30 seconds with Minecraft's own profiler, then looks through the saved world. The report says, in plain words, where each tick's time goes (mobs and other entities, machines like hoppers and furnaces, loading and making land, ...), which kinds cost most (cows, hoppers, a mod's machine; mods are named), and the busiest places by their coordinates ("around x 1208, z -392 in the Overworld: 410 in all (380 cow, ...)"), each with what to do about it. Craft Conductor also does this by itself when the server keeps falling behind while people play (at most once an hour), and tells you (on Discord too, if set up); switch that off under Settings → Updates.

### Check my setup

**🩺 Check my setup** (in the Server box on the Dashboard) checks what most often stops a server or keeps friends out, and says what to do about each: the server is installed and the EULA accepted, Java is there, the server's memory fits this computer, there's disk space, the port is free (or another program has it), accounts (online-mode), the friends' download port and public address, the router's port forwarding, Windows Firewall, and whether Craft Conductor has an update.

- **Fix buttons:** where Craft Conductor can put something right itself, the check has a button: **Read and accept the EULA**, **Download Java now**, **Use N GB** (memory that fits this computer), **Delete old backups** (keeps the newest 3) when the disk is nearly full, **Use a free port** when another program has the server's, **Turn it on** for account checks, **Use my public IP** for friends' downloads and **Ask my router (UPnP)** to forward the port. Changes to memory, the port and accounts apply at the server's next start. The checks run again afterwards.
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

Minecraft's live output. Type a server command (without the `/`, e.g. `say hello`) and press **Send**; the up/down arrows recall earlier commands. **Logs folder** and **Crash reports** open those folders (on the server's own computer).

## Players

Players online and players who have joined before, with **Op/De-op**, **Kick**, **Ban/Pardon** and **Whitelist**. The **Whitelist** card turns it on (only listed players can join) or off. **Add or manage a player** works for people who haven't joined yet.

**Asking to join:** when the whitelist is on, friends setting up with your invite can send their Minecraft name. They appear at the top of the Players page (and the Dashboard says so): **Allow** adds them to the whitelist, **Ignore** drops the request. A browser notification can tell you too (Craft Conductor settings → Notifications). Only someone with your invite can ask, and requests are limited.

## Mods

Installed mods with their versions: **Download mods** (the mod browser), **Local files**, mark a mod required or optional, **Remove** it (with the mods it needed, if nothing else needs them), and **Mod config files** to edit a mod's settings in the page (with colours for TOML, JSON, YAML and more). **Test these mods** checks a set of mods in a throwaway server, so your world is never touched; if they don't start together, **Find the culprits** adds them back a group at a time until it knows which ones clash. Changes apply at the next restart.

**Paper servers (plugins):** the page is called **Plugins**. **Download plugins** searches **Modrinth** and **Hangar** (PaperMC's own plugin site; pick it as the source): tick plugins and press **Add selected**, and Craft Conductor keeps them updated with Minecraft like mods, checking each file (Hangar's SHA-256). A plugin Hangar only links to elsewhere is listed to download yourself. **Plugins you added yourself** (jars dropped into the plugins folder, or uploaded with **Local files**) can be **switched off** (kept as `.jar.disabled`), switched back on, or removed. Plugin settings are under **Mod config files** (the `plugins/<plugin>/` folders).

**Saved mod lists:** **Save the current mods** under a name, and **Switch to it** later: the mods you had are saved first as "Before …", so you can always switch back. Craft Conductor offers to install the switched list right away (the server restarts after the countdown). **⬇** downloads a list as a file, and **Load a list from a file…** adds one, say from another server. The friends' extra mods are part of each list.

## Updates

Craft Conductor checks for updates by itself and applies them when it's safe:

- **Mod updates** for your Minecraft version are applied at the next restart.
- **A new Minecraft version** is only used once every mod supports it. Until then, **Show why** lists every mod in green (ready), yellow (ready, but only with an alpha/beta build) or red (no build yet), and the loader.
- Before every update Craft Conductor makes a backup; if the new version doesn't start, it rolls back by itself. Players get an in-game countdown first.
- Once a month, Craft Conductor reminds you which mods are holding the server back, so you can decide to drop them.
- **Rehearse it on a copy first** (when an update is ready) tries the update before it touches your server. Craft Conductor copies the server and its world (saving is paused for a moment while it copies), installs the update on the copy and runs it for the time you pick under **Watch it for**, on a private port nobody can join. The report says whether it started and how long that took, how well it kept up (TPS: 20 is perfect), how often it fell behind, and which mods wrote warnings or errors in the log (open a mod to see its lines). Then **Update for real** does the real update (with its backup, as always). If the copy didn't start or stopped by itself, the report names the mod it blames; the button becomes **Update anyway**, but it's better to update or remove that mod first. **Apply update ✓** means this exact update has worked on a copy.
- A rehearsal needs free disk space for a copy of the server, and makes the computer work harder while it runs. While the real server runs, the copy gets less memory if the computer is short of it (the report says so, and the copy may seem slower than the real update will be). The copy is deleted afterwards.
- **Settings → Before a new Minecraft goes in by itself, try it on a copy of the server first:** automatic updates to a new Minecraft version are rehearsed first. If the rehearsal fails, the update is held back and you're told (on Discord too, if it's set up); rehearse again or update from the Updates page when you've looked. Mod updates for the same Minecraft aren't rehearsed.
- **Test a beta version** tries a snapshot or pre-release on a copy of the server.

## Backups

**Create backup** saves the server (worlds, mods, configs) as a `.tar.gz`, even while it runs. Craft Conductor also backs up before every update. The newest 10 are kept (change it in Settings).

Each backup is a **snapshot** of the whole server: besides the files, Craft Conductor notes the Minecraft version, the mods, the server's settings, its mod config files and Craft Conductor's own settings for it. So the list says, for each backup, **what changed since the one before** (mods added, removed or updated, a new Minecraft, settings, config files, the world's size), and **Roll back to this** (with the server stopped) first lists exactly what it will undo, then puts all of it back: the world, the mods, the configs, and Craft Conductor's settings and mod list. Backups made by Craft Conductor before 0.15 only hold the files: **Restore** puts those back, and an update check then puts the mod list right.

- **Can be restored:** each backup is read back right after it's made (every file, and the world's `level.dat`), and marked **✓ checked**, or says what's wrong with it (a message tells you too). **Check** reads an older one.
- **Put back an area…** (with the server stopped) undoes damage in one place, like griefing or a creeper crater, and keeps everything else in the world as it is now. Type two opposite corners (the x and z numbers F3 shows in the game) and pick the Overworld, the Nether or the End. The chunks there go back to how they were in that backup: blocks, chests, animals and villagers; players' inventories don't change. Craft Conductor backs up the world first, so you can undo it.

To back up by itself, set **Make a backup** under Settings → Schedule. To keep backups safe from a broken disk, set **Also copy every backup to** under Settings → Backup copies: a USB drive, or a folder OneDrive, Dropbox or Google Drive syncs. Each backup is copied there too, in a folder named after the server, keeping the newest few. If the drive isn't plugged in, the backup is still made and the copy is skipped.

## Java

Craft Conductor downloads the right Java (Eclipse Temurin) for each Minecraft version and keeps it updated. You can force a version on this page if a modpack needs it; "auto" follows Minecraft.

## Settings

The server's version and upgrade choices, memory (with Aikar's flags above 16 GB), port, name and Minecraft's settings.

**Schedule:** restart the server and make backups at set times: **Every day at…**, **Every week on…**, **Every few hours** (backups), or **Custom (cron)** for anything else (five parts: minute, hour, day of the month, month, day of the week; for example `30 5 * * 1-5` is 5:30 on weekdays). Times are this computer's; the next run is shown. A scheduled restart gives players the in-game countdown first, and **Skip a scheduled restart while players are online** leaves them be. The same settings are `[schedule]` in `mcsm.toml`.

**Backup copies:** see Backups.

**World tools** (while the server runs; they use its own commands):

- **Game rules:** keep inventory, the day and weather cycle, mob griefing, fire spread, phantoms, how many players must sleep, and more, each with what it does. **Another game rule** sets any rule by name, for power users.
- **World border:** keep the world to a size (blocks wide) around a centre, so it stays manageable and players can find each other.
- **Pre-generate terrain:** making new terrain is the heaviest thing a server does; generating it ahead of time avoids lag spikes when people explore. It uses the free **Chunky** mod: **Add Chunky** installs it, then pick a radius and **Start** (with **Pause**, **Continue** and **Cancel**) and watch the progress. **Export server** saves everything (worlds, mods, configs, settings, player lists, and optionally backups) in one `.zip` to move to another computer: install Craft Conductor there, then **Servers → Import a server...**.

## Friends: playing with friends

On the server's **Friends** page, switch on "Make a download for friends". Then:

1. Copy an invite link and send it (by Discord, text or email). There's a **local link** for friends on your Wi-Fi and an **internet link** for everyone else. **Post to Discord** posts it for you.
2. Your friend clicks it, presses **Download**, and runs the file. Craft Conductor sets up their game (see the next section). Next time, the link opens their Craft Conductor directly.

For power users, **Advanced: invite codes and security** shows the raw invite codes (for `mcsm join <code>`).

**For friends outside your home:** press **Use my public IP** (or type your address under Craft Conductor settings → Sharing with friends), and forward two TCP ports on your router to this computer: the Minecraft port (25565 for the first server) and the friends' port (8766 unless you changed it).

- **Let Craft Conductor do it:** **Craft Conductor settings → Sharing with friends → Open the ports on my router by itself (UPnP)**. Craft Conductor asks the router to forward each server's Minecraft port and the friends' port to this computer, renews that while it runs, and takes the ports back when you switch it off or quit Craft Conductor. It shows which ports worked, your router's internet address, and warns when forwarding can't help (your provider shares one address between homes, called CGNAT, or there are two routers). **Check my setup** shows it too.
- **By hand:** many routers have UPnP switched off. The Help page has pictures; every router is different, so check its manual if you get stuck.

**What friends get:** the Minecraft version, mod loader and every mod that runs on players' computers (server-only mods are left out), plus the mods you add under **Mods for players**, and the memory you choose for their Minecraft. Mods that server mods need on players' computers are added by themselves (a message says which and why).

**New links** makes new ones; the old ones stop working. Friends who already set up keep playing, but need a new link to update.

**Security:** the link opens Craft Conductor's invite page on GitHub, and the invite itself is after the `#`, which browsers never send anywhere. Friends' Craft Conductor connects to your computer only over HTTPS, and only to your computer: the invite carries the fingerprint of your Craft Conductor's certificate, and anything else is refused. The Craft Conductor program itself always comes from GitHub, never from your server. The friends' port never gives access to the control panel.

### No port forwarding? playit.gg

If your router or internet provider doesn't let you forward ports, [playit.gg](https://playit.gg) can: its program runs on this computer and gives your server an address on the internet that friends join through.

**playit.gg is an outside service**, run by its own company, not by Craft Conductor. When playit.gg has problems, or its program isn't running on this computer, friends can't connect through it, however healthy your server is, and Craft Conductor can't fix that. Friends on your own network can still join with the Local link.

1. Download playit from playit.gg, run it, and claim it in your playit.gg account (it shows a link).
2. In playit.gg, add a **Minecraft Java** tunnel to this server's port (25565 unless you changed it). Put the address it gives you in the server's **Settings → playit.gg tunnel**.
3. For friends' downloads (the invite) from outside, add a **TCP** tunnel to the friends' download port (8766 unless changed) and put its address, with the port, in **Craft Conductor settings → Sharing with friends → No port forwarding? Use playit.gg**. Internet invites then use it.

With a tunnel set, the Dashboard shows **playit.gg tunnel**: Craft Conductor asks the server for its status through the tunnel, the way a friend's game does, and says whether it's **working**, whether it answers with a **different server** (point the tunnel at this server's port), or can't be reached. It also says if the playit program isn't running here, and links to playit.gg's status page. Craft Conductor checks every 5 minutes and notes in the activity (and on Discord, if set up) when the tunnel stops or starts working. **Check my setup** includes it too.

### Bedrock players (phones, tablets, consoles)

Friends playing Minecraft on a phone, a tablet, Windows (the Microsoft Store version) or a console can join a Fabric, Quilt, NeoForge or Paper server through [Geyser](https://geysermc.org). On the Friends page, press **Let Bedrock players join**: Craft Conductor adds the Geyser and Floodgate mods from Modrinth and offers to install them now (the server restarts after the countdown). Bedrock players then use **Play → Servers → Add Server** with your address and the Bedrock port (19132 unless Geyser's config says otherwise), and sign in with their own Microsoft account; they don't need Java Edition.

- For friends outside your home, also forward **UDP** port 19132 on your router (Bedrock uses UDP).
- Xbox, PlayStation and Switch can't add servers by themselves; GeyserMC's guide shows the workarounds.
- With the whitelist on, add a Bedrock player with the console command `fwhitelist add <name>`. Their names start with a dot (.) in game.
- Remove Geyser and Floodgate on the Mods page to turn it off.

## For friends: joining a server

1. Click the invite link you were sent. It opens a page that says you're invited: press the big **Download Craft Conductor** button (it picks your computer's version). It downloads the friends' Craft Conductor (`craft-conductor-join-...`): the same Craft Conductor, which always opens into joining a server, even on a computer that runs servers too.
2. Open the file you downloaded. (On Windows, if it says it "protected your PC", choose **More info → Run anyway**; on a Mac, right-click it and choose **Open** the first time.) Craft Conductor finds your invite by itself and checks it's really your friend's server. If it asks, press **Copy the invite** on the invite page and paste it into Craft Conductor.
3. Tick your launchers: the Minecraft Launcher, Prism Launcher, the Modrinth App and/or CurseForge (ones found on your computer are already ticked), and choose how much memory Minecraft gets.
4. **Make it yours (optional):** add **shaders**, **resource packs** or **more mods** that only run on your computer. Each opens a browser like the server's (search, sort, categories, the item's page on the right); tick what you want and press **Add selected**. Shaders bring their shader loader (Iris, or Oculus on Forge); mods bring what they need, listed under them.
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

By default only the server's own computer can open the control panel. **Craft Conductor settings → Remote access & phones** (also a button on the New server page) lets other devices in:

- It needs a **strong password**: 12+ characters with an uppercase letter, a lowercase letter and a special character. PINs don't work from other devices.
- **Pair a phone** by scanning the QR code with its camera. The code works once, for five minutes. The phone signs in by itself afterwards, with its own key.
- Before making the code, choose what the device may do: **Helper** gets the everyday controls (start, stop, restart, backups, updates, players, and letting in friends who ask); **Viewer** can only look. Neither can change settings, mods or files, use the console or change the password.
- **Co-admins:** pair the phone or computer of a friend who helps run the server the same way, as a helper or a viewer. What each device does shows in the activity with its name.
- Each paired phone is listed with when it was last used, and can be signed out on its own; changing the password signs out every phone.
- Away from home, use **Tailscale** (free) rather than opening the control panel's port on your router. For HTTPS, give Craft Conductor a certificate (for example from `tailscale cert`).

### The phone app

Craft Conductor can live on your phone's home screen like an app, and send **notifications** even when it's closed: when a server crashes or won't start, a friend asks to join, an update is held back, the lag finder finds something, and everything else Craft Conductor would post to Discord. It's set up under **Craft Conductor settings → Phone app**:

1. **A secure address.** Phones only install web apps and deliver their notifications for a page with a real certificate. The easy way is **Tailscale** (free for personal use): install it on this computer and your phone, signed in to the same account, then press **Check for Tailscale** and **Use Tailscale for the phone app**. The control panel gets an address like `https://your-computer.your-tailnet.ts.net` that only your own devices can reach; it isn't on the internet. (The first time, Tailscale may ask you to switch HTTPS on for your account: follow the link, then press the button again.) It needs a strong password first, because the phone signs in as another device. A Cloudflare Tunnel or your own domain with a real certificate works too (add its name to `[web] allowed_hosts`).
2. **Put it on your phone.** Open the secure address on the phone (with Tailscale on) and sign in, or pair the phone under **Remote access & phones** and pick the **Tailscale, secure** address. Then: **iPhone or iPad**: in Safari press **Share → Add to Home Screen**, and open Craft Conductor from the Home Screen (iPhones only allow notifications for apps added this way). **Android**: in Chrome press **⋮ → Install app** (or **Add to Home screen**); some browsers show **Install the app** in the card itself.
3. **Turn on notifications here**, in the app, under **Craft Conductor settings → Phone app**. **Send a test** checks it works. Each device with notifications on is listed; **Remove** stops them for that device, and **Turn off** does it on the device itself.

Notifications go through your phone's own push service (Apple's, Google's, Mozilla's or Microsoft's), encrypted so that only your phone can read them. A paired phone can turn its own notifications on and off, even as a viewer.

## Craft Conductor settings

- **Sign-in:** change your password or PIN. There's always one.
- **Remote access & phones:** see above.
- **Sharing with friends:** the friends' port and your public address, a playit.gg tunnel, and **Router**: open the ports on your router by itself (UPnP).
- **CurseForge:** searching CurseForge needs an API key (free, from console.curseforge.com); release builds of Craft Conductor can include one.
- **Discord:** add a bot to post invites to a channel. **Live status message:** pick a Discord server and channel, and **Keep a status message there**: one message that always shows whether each server is online, how many are playing and its Minecraft version (and your public address, if set). Craft Conductor edits it as things change and says when Craft Conductor is closed; **Stop** ends it. The bot never reads the channel.
- **Notifications:** **Notify me in this browser** shows a notification when a server stops unexpectedly, an update is ready, someone joins (off by default) or something Craft Conductor was doing fails, while Craft Conductor's tab is in the background. The browser asks first. It works when the address is localhost (or HTTPS).
- **Size:** how big text and buttons are in this browser: **Automatic** (bigger on big screens), Smaller, Normal, Larger or Largest.
- **Language:** Craft Conductor's pages in English, Español, Português, Français, Deutsch, हिन्दी, 中文, Tiếng Việt, العربية (right to left) or 한국어. **Automatic** follows your browser's language. The choice is kept in this browser; the buttons, menus and short messages are translated by machine (so they may have mistakes), and this manual stays in English.
- **Warnings:** how many warnings you've hidden with "Don't ask me again", and **Show all warnings again**.
- **About Craft Conductor:** the version, **Check for Craft Conductor updates**, the Craft Conductor folder, the notice and open-source licenses. Craft Conductor also checks by itself: when a new version is out, a message offers to install it (it stops your servers cleanly and restarts).
- The sun/moon button in the top corner switches between day and night.

## Troubleshooting

**The server won't start or setup failed.** The message says where the failure report is (in the server folder, under `.mcsm/logs`). It has the error, what Craft Conductor was doing and the server's last output; Minecraft's own log is `logs/latest.log` in the server folder. If a mod is to blame, Craft Conductor names it: remove it or wait for an update.

**"Port ... is busy."** Another program (or another server) uses that port. Pick another on the server's Settings page, or for the friends' port under Craft Conductor settings → Sharing.

**Friends can't connect from outside.** Check both ports are forwarded to this computer's local address, that you pressed **Use my public IP** again (home addresses change), and that your internet provider allows it (some don't; Tailscale or a VPN works then).

**"That invite is from an older Craft Conductor."** Invites changed in Craft Conductor 0.9 (to HTTPS). Update Craft Conductor on the server, then send friends the new invite from the Friends page.

**"The server's security certificate doesn't match the invite."** Craft Conductor refused to connect because the server isn't the one the invite is for. Ask for a new invite; if it happens again, someone may be interfering with the connection (on public Wi-Fi, say).

**Something's wrong and I don't know what.** Open the server's Dashboard and press **🩺 Check my setup**: it goes through the usual causes and says what to do. For friends who can't connect from outside, press **Test from the internet** there.

**I closed the browser tab.** Craft Conductor and your servers are still running. Open Craft Conductor again from its icon (or go to the same address in your browser): you're back where you were, and a server being created shows **See progress** on the Servers page.

**Forgot the password.** In a browser on the server's own computer, choose "Reset it to PASSWORD" on the sign-in page, or run `mcsm web-password --reset` there.

**A CurseForge mod can't be downloaded.** Its author blocks downloads by other apps. The Updates page lists it under "Manual downloads needed" with a link: download it and upload it there; Craft Conductor checks it's the right file.

**The day theme stays dark.** Your browser is forcing dark mode on pages (Chrome's "Auto Dark Mode for Web Contents", or a dark-mode extension). Craft Conductor 0.8.1 and newer keep the day theme light anyway.

**Windows: "The process cannot access the file because it is being used by another process".** Usually antivirus scanning a new download. Craft Conductor 0.8.2 and newer wait and retry, and show the real reason if a download fails.

## Where Craft Conductor keeps things

- **Your servers:** the `mcsm` folder in your home folder (for example `C:\Users\you\mcsm\servers\...`), one folder per server. Each has `mcsm.toml` (its settings), `server/` (Minecraft, the world and mods) and `backups/`.
- **Craft Conductor's own settings:** `mcsm/.mcsm/` (sign-in, paired phones, friends' certificate, CurseForge key and Discord token; readable only by you).
- **Friends' setups:** a folder of their own per launcher; their extras and joined servers are remembered in `.minecraft/mcsm/`.

## Command line

Everything also works in a terminal:

```
mcsm start              # the control panel with your servers (what double-clicking does)
mcsm join <invite>      # set up this computer's Minecraft for a friend's server
mcsm status             # what's installed
mcsm check / update     # see and apply updates
mcsm backup / restore   # back up or restore a server
mcsm player ...         # kick, ban/pardon, op/deop and whitelist
mcsm web-password       # show or change the sign-in (--set, --pin, --reset)
mcsm service install --panel   # Linux: run mcsm at boot
mcsm self-update        # update mcsm itself
```

Run `mcsm --help` (or `mcsm <command> --help`) for everything.

## Getting help

Found a bug or have an idea? [Report it on GitHub](https://github.com/silverWRX03/craft-conductor/issues/new/choose): a short form asks what happened and your Craft Conductor version (shown at the bottom of the menu). Attach the failure report if there is one (it doesn't contain passwords). What changed in each version, and which version fixed what, is in the [changelog](https://github.com/silverWRX03/craft-conductor/blob/main/CHANGELOG.md).
