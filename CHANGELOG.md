# Changelog

What changed in each version of mcsm, newest first. Bugs are listed the way you'd have seen
them. Found a new one? [Report it](https://github.com/silverWRX03/mc-server-management/issues/new/choose);
its fix will say which version it's in.

## 0.9.3 (not released yet)

**Added**
- **Rented servers (a VPS):** **Install on a Linux computer** works for a server on the internet too, keeping its control panel private and reached through an SSH tunnel (**Open an SSH tunnel**), with a [guide](docs/rented-server.md).
- **Paper plugins from Hangar** (PaperMC's plugin site) next to Modrinth, kept updated like mods; plugins and mods you added yourself can be switched off, on or removed.
- **playit.gg tunnels** for when you can't forward ports: a tunnel address per server and for friends' downloads, and a **playit.gg tunnel** card on the Dashboard that checks it's working (through the tunnel, the way a friend's game connects) and says when it stops. playit.gg is an outside service: disruptions on its side are out of mcsm's control.
- **The friends' download** (`mcsm-join-...`): the same mcsm under its own name, opening straight into joining a server (even on a computer that runs servers). Invite links offer it.
- Windows code signing through SignPath Foundation is ready in the release workflow; it switches on once the project is accepted ([code signing policy](docs/code-signing.md)).
- **Co-admins:** pair a device as a **Helper** (everyday controls) or a **Viewer** (look only), for a friend who helps run the server; what they do shows in the activity.
- **Discord live status message** (mcsm settings → Discord): one message in a channel showing each server's state, players and version, kept up to date.
- **Saved mod lists** (Mods page): save the mods under a name, switch lists and switch back (the current list is saved first), and download or load a list as a file.
- **World tools** (Settings): game rules with what they do, a world border, and pre-generating terrain with Chunky (added in one click), with progress.
- **Bedrock players** (phones, tablets, consoles, Windows): **Let Bedrock players join** on the Friends page adds Geyser and Floodgate and says which port to use and forward.
- **Ask to be let in:** friends joining a server with a whitelist send their Minecraft name from their mcsm; it shows on the Players page with **Allow** / **Ignore** (and as a notification).
- **Servers you've joined** (friends' mcsm) marks the servers that changed since you set up, so you know when to press **Update**.
- **Performance** on the Dashboard: ticks per second and ms per tick with a graph of the last hour, what slows a server down, and (with the spark mod) a 30-second profile.
- **Notifications** from the browser (mcsm settings → Notifications): a server stopping unexpectedly, an update being ready, someone joining, a job failing, while the tab is in the background.
- **Schedules** (Settings → Schedule): restart the server every day or week, back up every few hours or daily, or any cron expression; scheduled restarts give players the countdown and can skip while people are online.
- **Backup copies** (Settings → Backup copies): every backup is also copied to a USB drive or a cloud-synced folder, keeping the newest few.
- **🩺 Check my setup** on the Dashboard: Java, memory, disk space, the port, accounts, the friends' port and public address, the firewall and mcsm updates, each with what to do. **Test from the internet** checks friends outside can connect (asks ifconfig.co, only when pressed). **Report for a bug report** downloads the logs and settings with secrets taken out.
- **Play on this computer** on a server's Dashboard: sets up this computer's Minecraft for the server (on the server's own computer), after saying what running both on one computer needs: memory and CPU with this computer's numbers, lag spikes, and heavy modpacks.

## 0.9.2 (2026-09-27)

**Added**
- **Don't ask me again** on questions you meet often (Stop the server?, Quit mcsm?, Update to Minecraft…?, beta-only mods, Aikar's flags), and **Don't show again** on notices you've read. **mcsm settings → Warnings** brings them back.
- Closing the browser tab no longer loses work silently: the browser asks first while a file is uploading, settings or a config file aren't saved, a New server form is started, picked mods aren't added, or a mod test is running.

**Changed**
- Questions ("Stop the server?", "Delete …?") appear in mcsm's own dialog in the middle of the screen, with clear button names, instead of the browser's.
- The Servers page says once that closing the tab doesn't stop mcsm (**Got it** hides it), and the New server progress says you can close the page while it installs.

**Fixed**
- Closing mcsm's page (a friend setting up their game) and then pressing **Open in mcsm** or opening mcsm again didn't bring it back. It now shows the page again, with the progress or results, and the browser asks before the tab is closed while Minecraft is being set up.
- An invite link that lost its invite on the way (some apps cut links short) ended at "This invite link isn't complete"; the invite page now has a box to paste the link or invite code.

## 0.9.1 (2026-09-27)

**Added**
- A **user manual** in the app (**User manual** in the menu, and on Help), with contents, print and "Open on GitHub".
- **One-click friend invites:** friends click a link, press Download and run the file; mcsm sets up their game. Next time, the link's **Open in mcsm** opens their mcsm directly (Windows and Linux). The raw invite codes are still there for power users.

**Changed**
- Messages that need an answer are shown in the middle of the screen with the page blurred behind; everyday messages are at the top of the screen instead of the bottom-right corner.
- Discord posts say "Click here to join".

**Fixed**
- New server kept the previous server's type and mods after a server was created, and skipped the first step (where "install on a Linux computer" was). "Or on another computer" is now at every step.

**Fixed (security review)**
- An "Open in mcsm" link could pass extra options to mcsm; it now only ever carries the invite.

## 0.9.0 (2026-09-27)

**Added**
- **Install on a Linux computer over SSH** from the New server page.
- Friends connect to your server over **HTTPS**, and only to your server (the invite carries its certificate's fingerprint). mcsm itself always comes from GitHub.

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
- Windows: installing for a friend failed with **"The process cannot access the file because it is being used by another process"**; mcsm now shows the real error and waits out antivirus scans.
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

- Fixed the setup page and the default password for folders from mcsm 0.1.

## 0.2.0 (2026-09-25)

- Set up a new server from the web page.

## 0.1.0 (2026-09-25)

- First release: a modded Minecraft server manager that keeps a server and its mods up to date, with Java management.
