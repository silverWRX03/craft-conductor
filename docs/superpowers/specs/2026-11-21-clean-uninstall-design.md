# Clean uninstall (roadmap 38) — design

The owner's request on 2026-11-21: "i want to do 38 next plan it all out". The roadmap brief (TODO.md,
38) is the owner's. Everything else here is Claude's proposal, marked **[call]** where Claude decided
for the owner, and **[owner]** where the owner should confirm; the defaults below apply until they
say otherwise.

## Intent

Someone who stops using Craft Conductor can remove everything it added to their computer, router and
accounts in one go, without hunting for firewall rules, port mappings or hidden folders, and without
losing their worlds by accident. Whatever it can't remove by itself it lists, with how.

## Goals, non-goals, anti-goals

- Goal: one action removes the program, its settings and state, and every system change it made.
- Goal: servers (worlds), backups, exports and the games it set up in launchers are each kept unless
  the person ticks them, separately.
- Goal: a full list before anything happens (what goes, what stays, what needs the person), and a
  report after (what was removed, what failed, what's left to do by hand).
- Non-goal: removing other people's programs the person installed themselves (Tailscale, playit.gg,
  Java they had already). They're listed, with where to remove them.
- Non-goal: reaching other computers (friends' computers, Linux computers set up over SSH, phones):
  listed with what to do there.
- Anti-goal: deleting anything outside what Craft Conductor made or was told about. A path is only
  deleted if it is one of the known places, isn't a link, and isn't a drive root, the user's home
  folder or a system folder.
- Anti-goal: a world lost because a box was ticked by default or a server was still running.
- Anti-goal: an uninstall reachable from the network or by an invited person.

## What Craft Conductor adds (the inventory)

Each is a **part** with: what it is, whether it's present, how to remove it, and what to tell the
person if it can't. From the code on 2026-11-21:

| Part | Where | Removal |
|---|---|---|
| Program | the Windows/macOS/Linux executable (frozen), or a pip/pipx install, or a Docker image | executable: deleted (Windows: after it exits); pip/pipx and Docker: listed (`pipx uninstall craft-conductor`, `docker rm`/`rmi`) |
| Settings and state | `<home>/.craft-conductor` (home = `CRAFT_CONDUCTOR_HOME` or `~/craft-conductor`): hub.json, passwords and sessions, phones, passkeys, people, push registrations, logs, caches, the lockbox key, the downloaded `cloudflared` | deleted (see the lockbox question) |
| Shared Java | `<home>/.craft-conductor/java/…` | deleted with the state |
| Router port mappings | UPnP mappings labelled `craft-conductor` | removed through the router; ports the router didn't answer for are listed |
| Windows Firewall rules | group "Craft Conductor" | removed with one administrator prompt; if declined, listed with the command (`craft-conductor firewall remove`) |
| Tailscale Serve / Funnel | `tailscale serve` / `funnel` set by Craft Conductor | `tailscale.unserve`; the Tailscale app itself is listed, not removed |
| Cloudflare quick tunnel | a running `cloudflared` started by Craft Conductor | stopped; the program file goes with the state |
| Background service (Linux) | systemd user or system unit(s), lingering | `service.uninstall` for each (panel and per-server); lingering left as it was if other units use it |
| Invite link handler | Windows `HKCU\Software\Classes\craft-conductor`; Linux `craft-conductor-invite.desktop` | removed |
| Servers and worlds | the servers folder (locations.py; may be elsewhere) and each server Craft Conductor manages | only if ticked |
| Backups | the backups folder (and a copy folder, `[backups] copy_to`, if set) | only if ticked |
| Exports | the exports folder | only if ticked |
| Games in launchers | Minecraft Launcher installations, Prism/MultiMC instances, Modrinth App profiles Craft Conductor made (Play on this computer, single-player games, a friend's joined servers) | only if ticked; the builder finds how each was recorded when made, and only removes what was recorded |

Listed for the person (never touched): Tailscale and playit.gg apps, phones (the installed app and
passkeys), browsers (the installed control panel app and site data), friends' computers and other
computers set up over SSH (each has its own Craft Conductor: uninstall there), Docker containers,
router ports the router didn't confirm, anything that failed.

## How it works

- **One module** (`uninstall.py`) holds the inventory and does the work; the command and the page both
  use it. It works in two steps: `plan(home, choices)` lists every part with present/absent, what will
  happen and the exact paths; `run(plan)` does it in a fixed order and returns a report. Nothing is
  removed before the person has seen the plan.
- **Order:** stop every server cleanly (players get the usual warning; a server with players online
  is asked about first) → stop tunnels and Tailscale Serve → router mappings → firewall → service →
  invite handler → games (if ticked) → exports, backups, servers (if ticked) → settings and state →
  the program. A failed part doesn't stop the rest; it goes in the report.
- **Safety:** every path comes from the inventory, is resolved, mustn't be a link, mustn't be (or
  contain) the user's home folder, a drive root or a system folder, and must be one of the known
  places. Deleting servers needs a second confirmation that names how many servers and worlds.
- **The lockbox key [owner]:** backups' locked parts (passwords, keys, IP bans, logs) open only with
  this computer's key, which lives in the state. Default: delete it like the rest, and say plainly
  before uninstalling that kept backups' locked parts won't open anywhere afterwards (the rest of
  each backup still restores). Alternative: keep the key file so a reinstall here can open them
  (then the uninstall isn't fully clean). The page and command offer this as a tick box, off.
- **Where it's started [owner]:**
  - **`craft-conductor uninstall`** (all platforms, including a computer without a screen): shows the
    plan; `--yes` does it; `--delete-servers`, `--delete-backups`, `--delete-exports`,
    `--delete-games`, `--keep-lockbox-key` choose the rest. It refuses while another Craft Conductor
    is running on the same home unless that one is stopped first (it says how).
  - **A button** in Craft Conductor settings → About & updates: **Uninstall Craft Conductor…**. The
    owner only, only from a browser on this computer (like the other on-this-computer actions), with
    the password typed again. It shows the same plan with the tick boxes (all off), then a progress
    list, then the final report, which stays on the page after Craft Conductor has exited.
  - **No entry in Windows' Apps list [call]:** the Windows program is a single file without an
    installer, so there's no Apps entry today; adding one would be one more thing to clean up.
- **The program removing itself [call]:** a running Windows executable can't delete itself, so a
  small detached command deletes it a few seconds after Craft Conductor exits. On Linux and macOS the
  file is deleted directly. pip/pipx and Docker installs get the command to run.
- **The report** is printed by the command and shown on the page; it's also saved as
  `Craft Conductor uninstall report.txt` in the person's Downloads folder when anything is left to
  do by hand **[call]**, since the home folder may be gone.

## Security

- Not reachable from the network: the page action is owner-only and on-this-computer-only, with the
  password re-typed; a paired phone, an invited person or anyone through a tunnel can't start it.
- No path from user input: the inventory builds every path; requests only carry the tick boxes.
- The firewall and service removals run fixed commands with fixed names (as today's
  `craft-conductor firewall remove` / `service uninstall`).

## Constraints

- Standard library only; Windows, macOS, Linux and Docker all handled (Docker and pip as listed parts).
- House rules (CLAUDE.md): manual (a new "Removing Craft Conductor" section), README one line, Help if it
  covers settings, `docs/headless.md` (its "Remove the service" row), translations for every page
  string in 9 languages, CHANGELOG under `## 0.31.0 (not released yet)` (Added), real-world tests via
  `tools/real_world_tests.py add-test` (next free id; 1049–1065 are taken on open branches), the
  website demo (a simulated dialog that removes nothing), screenshots for the new dialog, and a
  security then efficiency review before the merge.
- Testing must never touch the real computer: every system change goes through an injected runner in
  tests; real runs only in disposable places (a pytest temporary home, a WSL Docker container, a
  disposable Windows account or VM), never the owner's own Craft Conductor.
- This is a draft PR waiting for the release candidate, like #336–#338 and #343.

## Left to the builder

- How each launcher game Craft Conductor made is recorded (join.py, singleplayer.py, launchers.py),
  and whether old installs recorded enough to remove only what it made; anything unrecorded is listed,
  not guessed.
- Where the UPnP mappings, Tailscale state and service units are recorded today, and reading them
  without the panel running (for the command).
- macOS specifics (no service, no URL handler today).
- The exact page layout and wording.
