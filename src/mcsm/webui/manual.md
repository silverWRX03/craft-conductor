# mcsm user manual

mcsm (Minecraft server manager) sets up a Minecraft server on your own computer, keeps it running, keeps it and its mods up to date, and gets your friends' games ready to join. Everything happens in the **control panel**, a page in your web browser.

This manual is also inside mcsm: open **User manual** (or **Help**) in the control panel. It comes with mcsm, so it always matches the version you have and is updated with it. mcsm is in beta: back up anything you can't afford to lose.

## What mcsm can and can't do

**It can:**

- create a Fabric, NeoForge, Forge, Quilt, Paper or plain (vanilla) Minecraft server, with the right Java, mod loader and mods;
- keep it on the newest Minecraft **once every mod supports it**, making a backup before each update and rolling back by itself if the new version doesn't start;
- find mods and the mods they need, test a set of mods before you commit to it, and find which mod breaks a server;
- set up your friends' Minecraft (Minecraft Launcher, Prism Launcher, Modrinth App or CurseForge) with one invite;
- let you manage it from your phone or another computer, or run it on a Linux computer without a screen, or in Docker.

**It can't:**

- make your computer reachable from the internet by itself: friends outside your home need **port forwarding** on your router (the Help page shows how);
- make mods work together when their authors haven't; it can only tell you and wait for updates;
- download CurseForge mods whose authors block downloads by other apps (you download those yourself; mcsm gives you the link);
- run your server while your computer is off; it isn't a hosting service. Bedrock Edition isn't supported.

## Getting started

1. Download mcsm for your computer from the [releases page](https://github.com/silverWRX03/mc-server-management/releases/latest): Windows, Mac (Apple silicon) or Linux.
2. Open it. On Windows, if SmartScreen says it "protected your PC", choose **More info → Run anyway** (mcsm isn't code-signed). On a Mac, right-click it and choose **Open** the first time.
3. The control panel opens in your browser. Read and accept the notice (what mcsm does and doesn't do).
4. Sign in with the password `PASSWORD` (in capitals). mcsm asks you to choose your own right away: a password, or a 4–8 digit PIN. A PIN only works in a browser on the server's own computer.

Servers run while mcsm runs. **Closing the browser tab doesn't stop mcsm**: your servers keep running, and anything mcsm is doing (creating a server, an update) carries on. Open mcsm again from its icon to come back to the control panel. **Quit** (at the bottom of the menu) stops everything cleanly.

If closing the tab would lose something that only lives in the page (an upload on its way, settings or a config file you haven't saved, a New server form you've started, mods picked but not added, a mod test's report), your browser asks first ("Leave site?").

> Joining a friend's server rather than running your own? See **For friends: joining a server** below.

## Creating a server

Go to **New server**. One step at a time:

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

**5. Settings.** The server's name (shown in the multiplayer list), max players, difficulty, game mode, memory and port. Above 16 GB of memory, mcsm offers **Aikar's flags** (tuned garbage collection that avoids lag spikes). **Advanced settings** has the rest of Minecraft's server settings. The whitelist starts **off** (anyone with the address can join) until you turn it on.

**Friends (optional).** Tick "Make a download for my friends" to get an invite for them. **Set up now** opens the mod browser for mods for players' computers (a minimap, JEI...), and **Local files** adds your own. Mods your server's mods need on players' computers are added by themselves.

**Almost done.** Accept the Minecraft EULA and press **Create my server**. mcsm downloads Java, the loader, Minecraft and the mods, then checks the server starts. The progress stays on the page, and the lower part of the screen shows how to open your router for friends outside your home. When it's ready, the server's Dashboard (or its Friends page) opens.

If setup fails, the page says why and where the detailed report is saved; change your choices and try again.

### On another computer (Linux, over SSH)

A spare PC, a home server or a Raspberry Pi 4/5 (64-bit) can run your servers without a screen. On **New server**, under **Or on another computer** (at the bottom of the page, at any step), choose **Install on a Linux computer**, type its address (e.g. `192.168.1.50`) and a normal user name on it (not root), and press **Connect with SSH**. A terminal opens: type that computer's password when SSH asks (the first time, answer `yes` to trust it). mcsm never sees the password. When it finishes, it shows that computer's control panel address and a one-time password; open it and choose your own password. See also the [headless guide](https://github.com/silverWRX03/mc-server-management/blob/main/docs/headless.md) and [Docker](https://github.com/silverWRX03/mc-server-management/blob/main/docs/docker.md).

## Messages

Everyday messages ("Saved", or what went wrong) appear at the **top of the screen** for a few seconds; click one to dismiss it. When mcsm needs an answer (use Aikar's flags? install an mcsm update? a mod test finished), it asks in the **middle of the screen** with the page blurred behind, and waits until you choose. A long mod test shows its progress at the top while you keep working.

Questions you'll meet again and again ("Stop the server?", "Quit mcsm?", "Update to Minecraft …?", mods with only beta builds, Aikar's flags) have a **Don't ask me again** box, and notices you've read (online-mode is off, a mod test takes a while, closing the tab doesn't stop mcsm) have **Don't show again** or **Got it**. mcsm remembers that in this browser; **mcsm settings → Warnings → Show all warnings again** brings them all back. Questions about deleting or replacing things always ask.

## Your servers

**Servers** lists every server with its state, version, players and port: **Start**, **Open**, **Delete**, and **Folder** (on the server's own computer). **Import a server...** adds one exported from another computer.

## Dashboard

**Start**, **Restart** and **Stop** are at the top of every server page. The Dashboard shows CPU and memory use, who's online, the console, the server's details and whether an update is ready. Stopping warns players and saves the world first.

### Check my setup

**🩺 Check my setup** (in the Server box on the Dashboard) checks what most often stops a server or keeps friends out, and says what to do about each: the server is installed and the EULA accepted, Java is there, the server's memory fits this computer, there's disk space, the port is free (or another program has it), accounts (online-mode), the friends' download port and public address, Windows Firewall, and whether mcsm has an update.

- **Test from the internet** (with the server running) asks ifconfig.co, an outside service, to connect to your public address on the server's port: the surest way to know friends outside your home can join. It runs only when you press it.
- **Report for a bug report** downloads a zip with the checks, versions, the server's settings and the ends of the logs, with passwords, keys, webhooks, invite secrets and players' IP addresses taken out. Look through it, then attach it to a [bug report](https://github.com/silverWRX03/mc-server-management/issues/new/choose).

### Playing on the same computer

**Play on this computer** (on the Dashboard, in a browser on the server's own computer) sets up this computer's Minecraft for the server, the same way friends' mcsm does: the right version, mod loader and mods, added to the launchers you pick, joining at `localhost`. Press it again after the server updates.

Before it starts, mcsm says what running both on one computer means, with this computer's numbers:

- **Resource heavy:** the game and the server both take a lot of memory (RAM) and CPU. mcsm adds up the server's memory, Minecraft's and about 3 GB for everything else; if that's more than the computer has, it says so, and both would lag or crash. Give the server less memory (Settings), choose less for Minecraft, or play on another computer.
- **Lag spikes:** when players join or the server loads new terrain while you're in an intense moment, the game can drop frames and the server can lag (TPS).
- **Heavy modpacks:** a heavy modpack (100+ mods) or a large public server (15+ players) strains a personal computer heavily and isn't recommended; mcsm says how many mods the server has and how many players it allows, and flags 100+ mods.

The general warning has **Don't ask me again**; a memory shortage or a heavy server is always pointed out.

## Console

Minecraft's live output. Type a server command (without the `/`, e.g. `say hello`) and press **Send**; the up/down arrows recall earlier commands. **Logs folder** and **Crash reports** open those folders (on the server's own computer).

## Players

Players online and players who have joined before, with **Op/De-op**, **Kick**, **Ban/Pardon** and **Whitelist**. The **Whitelist** card turns it on (only listed players can join) or off. **Add or manage a player** works for people who haven't joined yet.

## Mods

Installed mods with their versions: **Download mods** (the mod browser), **Local files**, mark a mod required or optional, **Remove** it (with the mods it needed, if nothing else needs them), and **Mod config files** to edit a mod's settings in the page (with colours for TOML, JSON, YAML and more). **Test these mods** checks a set of mods in a throwaway server, so your world is never touched; if they don't start together, **Find the culprits** adds them back a group at a time until it knows which ones clash. Changes apply at the next restart.

## Updates

mcsm checks for updates by itself and applies them when it's safe:

- **Mod updates** for your Minecraft version are applied at the next restart.
- **A new Minecraft version** is only used once every mod supports it. Until then, **Show why** lists every mod in green (ready), yellow (ready, but only with an alpha/beta build) or red (no build yet), and the loader.
- Before every update mcsm makes a backup; if the new version doesn't start, it rolls back by itself. Players get an in-game countdown first.
- Once a month, mcsm reminds you which mods are holding the server back, so you can decide to drop them.
- **Test a beta version** tries a snapshot or pre-release on a copy of the server.

## Backups

**Create backup** saves the server (worlds, mods, configs) as a `.tar.gz`, even while it runs. mcsm also backs up before every update. **Restore** puts a backup back (the server stops first). The newest 10 are kept.

## Java

mcsm downloads the right Java (Eclipse Temurin) for each Minecraft version and keeps it updated. You can force a version on this page if a modpack needs it; "auto" follows Minecraft.

## Settings

The server's version and upgrade choices, memory (with Aikar's flags above 16 GB), port, name and Minecraft's settings. **Export server** saves everything (worlds, mods, configs, settings, player lists, and optionally backups) in one `.zip` to move to another computer: install mcsm there, then **Servers → Import a server...**.

## Friends: playing with friends

On the server's **Friends** page, switch on "Make a download for friends". Then:

1. Copy an invite link and send it (by Discord, text or email). There's a **local link** for friends on your Wi-Fi and an **internet link** for everyone else. **Post to Discord** posts it for you.
2. Your friend clicks it, presses **Download**, and runs the file. mcsm sets up their game (see the next section). Next time, the link opens their mcsm directly.

For power users, **Advanced: invite codes and security** shows the raw invite codes (for `mcsm join <code>`).

**For friends outside your home:** press **Use my public IP** (or type your address under mcsm settings → Sharing with friends), and forward two TCP ports on your router to this computer: the Minecraft port (25565 for the first server) and the friends' port (8766 unless you changed it). The Help page has pictures; every router is different, so check its manual if you get stuck.

**What friends get:** the Minecraft version, mod loader and every mod that runs on players' computers (server-only mods are left out), plus the mods you add under **Mods for players**, and the memory you choose for their Minecraft. Mods that server mods need on players' computers are added by themselves (a message says which and why).

**New links** makes new ones; the old ones stop working. Friends who already set up keep playing, but need a new link to update.

**Security:** the link opens mcsm's invite page on GitHub, and the invite itself is after the `#`, which browsers never send anywhere. Friends' mcsm connects to your computer only over HTTPS, and only to your computer: the invite carries the fingerprint of your mcsm's certificate, and anything else is refused. The mcsm program itself always comes from GitHub, never from your server. The friends' port never gives access to the control panel.

## For friends: joining a server

1. Click the invite link you were sent. It opens a page that says you're invited: press the big **Download mcsm** button (it picks your computer's version). It downloads the friends' mcsm (`mcsm-join-...`): the same mcsm, which always opens into joining a server, even on a computer that runs servers too.
2. Open the file you downloaded. (On Windows, if it says it "protected your PC", choose **More info → Run anyway**; on a Mac, right-click it and choose **Open** the first time.) mcsm finds your invite by itself and checks it's really your friend's server. If it asks, press **Copy the invite** on the invite page and paste it into mcsm.
3. Tick your launchers: the Minecraft Launcher, Prism Launcher, the Modrinth App and/or CurseForge (ones found on your computer are already ticked), and choose how much memory Minecraft gets.
4. **Make it yours (optional):** add **shaders**, **resource packs** or **more mods** that only run on your computer. Each opens a browser like the server's (search, sort, categories, the item's page on the right); tick what you want and press **Add selected**. Shaders bring their shader loader (Iris, or Oculus on Forge); mods bring what they need, listed under them.
5. Press the button to set it up. Each launcher gets its own copy, in a folder of its own: your other worlds and installations aren't touched. The Modrinth App gets a `.mrpack` to import, and CurseForge a `.zip` (Create Custom Profile → Import).
6. In your launcher, pick the server's name and press Play. On Minecraft 1.20 and newer it joins straight away; otherwise it's in your multiplayer list.

**The page says "Paste your invite" or "This invite link isn't complete"?** The app you opened the link in cut it short (the invite is the long part after the `#`). Copy the whole link again (in Discord: right-click it → **Copy Link**) or the invite code, paste it into the box and press **Open invite**.

**Closed mcsm's page by mistake?** mcsm keeps going. Open mcsm again (or press **Open in mcsm** on the invite page) and its page comes back, with the progress or results. While it's setting Minecraft up, your browser asks before closing the tab.

**Already have mcsm?** On the invite page, press **Open in mcsm** (Windows and Linux; on a Mac, press **Copy the invite** and open mcsm).

**When the server updates**, click the invite link again and press **Open in mcsm**, or open mcsm and press **Update** next to it under **Servers you've joined**. If some of your extras don't work on the new Minecraft yet, mcsm tells you first: **Continue** removes those mods and switches those shaders/resource packs off (you can switch them back on, but the game may crash), or **Cancel** keeps everything as it is (you can't join the updated server until you continue).

mcsm never asks for your Microsoft password: your launcher signs you in.

## Remote access and phones

By default only the server's own computer can open the control panel. **mcsm settings → Remote access & phones** (also a button on the New server page) lets other devices in:

- It needs a **strong password**: 12+ characters with an uppercase letter, a lowercase letter and a special character. PINs don't work from other devices.
- **Pair a phone** by scanning the QR code with its camera. The code works once, for five minutes. The phone signs in by itself afterwards, with its own key.
- A paired phone gets the everyday controls: start, stop, restart, backups, updates and players. It can't change settings, mods or files, use the console or change the password.
- Each paired phone is listed with when it was last used, and can be signed out on its own; changing the password signs out every phone.
- Away from home, use **Tailscale** (free) rather than opening the control panel's port on your router. For HTTPS, give mcsm a certificate (for example from `tailscale cert`).

## mcsm settings

- **Sign-in:** change your password or PIN. There's always one.
- **Remote access & phones:** see above.
- **Sharing with friends:** the friends' port and your public address.
- **CurseForge:** searching CurseForge needs an API key (free, from console.curseforge.com); release builds of mcsm can include one.
- **Discord:** add a bot to post invites to a channel.
- **Warnings:** how many warnings you've hidden with "Don't ask me again", and **Show all warnings again**.
- **About mcsm:** the version, **Check for mcsm updates**, the mcsm folder, the notice and open-source licenses. mcsm also checks by itself: when a new version is out, a message offers to install it (it stops your servers cleanly and restarts).
- The sun/moon button in the top corner switches between day and night.

## Troubleshooting

**The server won't start or setup failed.** The message says where the failure report is (in the server folder, under `.mcsm/logs`). It has the error, what mcsm was doing and the server's last output; Minecraft's own log is `logs/latest.log` in the server folder. If a mod is to blame, mcsm names it: remove it or wait for an update.

**"Port ... is busy."** Another program (or another server) uses that port. Pick another on the server's Settings page, or for the friends' port under mcsm settings → Sharing.

**Friends can't connect from outside.** Check both ports are forwarded to this computer's local address, that you pressed **Use my public IP** again (home addresses change), and that your internet provider allows it (some don't; Tailscale or a VPN works then).

**"That invite is from an older mcsm."** Invites changed in mcsm 0.9 (to HTTPS). Update mcsm on the server, then send friends the new invite from the Friends page.

**"The server's security certificate doesn't match the invite."** mcsm refused to connect because the server isn't the one the invite is for. Ask for a new invite; if it happens again, someone may be interfering with the connection (on public Wi-Fi, say).

**Something's wrong and I don't know what.** Open the server's Dashboard and press **🩺 Check my setup**: it goes through the usual causes and says what to do. For friends who can't connect from outside, press **Test from the internet** there.

**I closed the browser tab.** mcsm and your servers are still running. Open mcsm again from its icon (or go to the same address in your browser): you're back where you were, and a server being created shows **See progress** on the Servers page.

**Forgot the password.** In a browser on the server's own computer, choose "Reset it to PASSWORD" on the sign-in page, or run `mcsm web-password --reset` there.

**A CurseForge mod can't be downloaded.** Its author blocks downloads by other apps. The Updates page lists it under "Manual downloads needed" with a link: download it and upload it there; mcsm checks it's the right file.

**The day theme stays dark.** Your browser is forcing dark mode on pages (Chrome's "Auto Dark Mode for Web Contents", or a dark-mode extension). mcsm 0.8.1 and newer keep the day theme light anyway.

**Windows: "The process cannot access the file because it is being used by another process".** Usually antivirus scanning a new download. mcsm 0.8.2 and newer wait and retry, and show the real reason if a download fails.

## Where mcsm keeps things

- **Your servers:** the `mcsm` folder in your home folder (for example `C:\Users\you\mcsm\servers\...`), one folder per server. Each has `mcsm.toml` (its settings), `server/` (Minecraft, the world and mods) and `backups/`.
- **mcsm's own settings:** `mcsm/.mcsm/` (sign-in, paired phones, friends' certificate, CurseForge key and Discord token; readable only by you).
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

Found a bug or have an idea? [Report it on GitHub](https://github.com/silverWRX03/mc-server-management/issues/new/choose): a short form asks what happened and your mcsm version (shown at the bottom of the menu). Attach the failure report if there is one (it doesn't contain passwords). What changed in each version, and which version fixed what, is in the [changelog](https://github.com/silverWRX03/mc-server-management/blob/main/CHANGELOG.md).
