# To do

Two lists: things only you can do (outside the code: accounts, testing on real hardware,
files), and what Claude works on next. Anything in **For you** that a feature depends on
comes first; it says which.

## For you (outside tasks)

Before continuing or starting a feature, check this list: some features wait on one of these.

- [x] **New icon:** put the stone-and-lava "MCSM" picture in the repository (for example
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
- [ ] **Try automatic port forwarding at home** (mcsm settings → Sharing with friends → Router):
      switch it on, look at what it says, then **Test from the internet** in Check my setup. It
      was only tested against a pretend router.
- [ ] **Windows code signing (optional):** apply to the SignPath Foundation (see
      [docs/code-signing.md](docs/code-signing.md)). Once accepted, add the repository variable
      `SIGNPATH_ORGANIZATION_ID` and the secret `SIGNPATH_API_TOKEN`; releases are then signed
      and Windows stops warning about mcsm.
- [ ] **Merged pull requests:** comment "Fixed in <version>" on any issues a release fixed
      (none so far).

## For Claude (next work)

In priority order: the top one is next.

Done:
- [x] Release 0.12.0 (router set up by itself, fix buttons, what went wrong, Quick start,
      checked backups and putting back an area).
- [x] New icon from your picture, without the white around it.
- [x] Release 0.13.0: explore the map preview (drag, zoom, make more land as you go).

Next:
1. [x] **Update rehearsal:** before a Minecraft update, copy the server, update the copy and run
       it for a few minutes; report whether it started, how laggy it was and which mods
       complained, then offer "Update for real".
2. [ ] **Lag finder:** when the server slows down, run spark by itself and say what's wrong in
       plain words ("chunk loading around x 1200, z −400: a farm with 400 animals").
3. [ ] **Seed gallery:** one button makes maps of 10 seeds side by side to pick from, with a
       warning first about the time and the load on the computer (waits on **Try the map preview
       for real**).
4. [ ] **Snapshots** of a whole server (config, mods, world) with a list of what changed, and
       rollback.
5. [ ] **Guided first server:** a short walkthrough for complete beginners, with a checklist that
       ends at "your friend joined".
6. [ ] **Modded single-player worlds:** set up and keep a modded single-player game up to date,
       then load it into the launcher of your choice (no launcher of our own).
7. [ ] **Accessibility:** everything works with the keyboard, labels for screen readers, and a
       high-contrast theme.
8. [ ] **Player activity:** who played when, the busiest times, and a suggested restart time when
       nobody is usually on.
9. [ ] Whitelist through Discord (friends ask with a command, the owner approves).
10. [ ] Web map of the world (BlueMap or Dynmap) with a link to share.
11. [ ] **Map landmarks:** villages, structures and players' bases pinned on the map preview (and
        on the web map).
12. [ ] Notifications on phones with the tab closed (installable web app).
13. [ ] Limits per server (memory, CPU) and a warning when too many run at once.
14. [ ] Other tunnel services next to playit.gg (Cloudflare Tunnel, Tailscale Funnel).
15. [ ] Purpur servers.
16. [ ] Scripting hooks (a script on start, stop, a player joining, before an update) and API tokens.
17. [ ] **Mod conflict memory:** mod combinations that failed together in "Find which mods break
        it", shared anonymously if you opt in, so mcsm can warn others before they install them
        (needs somewhere to keep the shared list).
18. [ ] Proxy networks (Velocity) with several servers behind them.
19. [ ] Translated user manual for the most used languages; a way for people to fix translations.
20. [ ] **Servers on hosting sites:** look into controlling servers that run elsewhere. Hosting
        panels with an official API (Pterodactyl, used by many paid hosts) are the realistic
        target. Free hosts (Aternos, Minehut, Minefort) only if they have an official API and their
        terms allow it: Aternos's terms don't allow automating its site.
