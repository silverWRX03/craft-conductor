# Players' ping (roadmap 47) — design

Approach chosen by the owner on 2026-11-20: **our own small server-side mod and plugin** (option B),
in their words "Go with B build it". The order (Paper/Purpur and Fabric first, then NeoForge and
Forge; vanilla keeps "—") was Claude's recommendation in the same message, which the owner accepted
by picking B. Everything else below is Claude's proposal unless marked as the owner's.

## Intent

The Dashboard's **Connected Players** card (roadmap 34, shipped in 0.23.0) has a ping column with
good / fair / poor colours, but shows "—" for everyone: no server type prints each player's ping to
the console, which is all Craft Conductor can read. Every server already measures it (the number
behind the tab list's signal bars); it just keeps it inside. A tiny helper of our own, running on
the server, hands that number to Craft Conductor so the card can show it.

The owner is fine with Craft Conductor putting its own mod on Fabric and Forge servers. Their
earlier brief for 47 also said "don't add it to a server without asking".

## Goals, non-goals, anti-goals

- Goal: a real per-player ping on the Connected Players card for Paper, Purpur, Fabric and Quilt
  servers in this branch; NeoForge and Forge in a second step on the same design.
- Goal: nothing to download from anyone else: the helper ships inside Craft Conductor.
- Non-goal: vanilla. It keeps "—" with a reason that now says ping needs a server type that runs
  mods or plugins. (Reading the operating system's TCP round-trip times, option C1, can come later
  for Linux servers players reach directly.)
- Non-goal: ping history, graphs or alerts. Only the current value.
- Anti-goal: the helper is never put on a server the owner didn't turn it on for.
- Anti-goal: anything players have to install. The helper is server-only; a vanilla or modpack
  client joins exactly as before.
- Anti-goal: console or log spam. Nothing is typed into the console and nothing is printed per
  reading.
- Anti-goal: the helper opening a network port or reading anything but the players' ping.

## Approaches considered

- **A. spark's `/spark ping --player <name>`.** Nothing to build, but one console command per
  player every few seconds (each answer lands in the server log), a third-party output format that
  can change, and spark's docs don't say which loaders support it. Not picked.
- **B. Our own helper (picked).** Server-only, writes a small file Craft Conductor reads. Costs a
  Java build next to the Python project, and keeping up with new Minecraft versions.
- **C. Vanilla without a mod:** C1 the operating system's TCP round-trip times matched to the join
  log's `Name[/IP:port]` (needs administrator rights on Windows; reads ~0 ms behind playit.gg, a
  proxy or Docker; measures the network, not the game's number), or C2 a Java agent loaded at
  start (the game's internal names differ per loader and, before 26.1, per version). Not now.

## How it works

**The helper, "Craft Conductor Ping"** (mod id / plugin name `craft_conductor_ping`):
- Every 5 seconds, on the server's own thread, it reads each online player's latency (the value
  Minecraft sends to clients for the tab list) and writes
  `.craft-conductor/ping.json` in the server folder:
  `{"version": 1, "time": <unix ms>, "players": {"<name>": <ms>, ...}}`.
  Written to a temporary file and renamed, so Craft Conductor never reads half a file. The file
  write happens off the server thread.
- It does nothing else: no commands, no network, no config, no other files, no log lines except
  one on start ("Craft Conductor Ping: reporting players' ping to Craft Conductor") and one if the
  file can't be written (once, not every 5 seconds).
- **Paper/Purpur plugin:** `Player#getPing()` (Bukkit API since 1.17), a repeating sync task;
  `plugin.yml` `api-version: "1.17"`. One jar for every version Craft Conductor runs Paper on.
- **Fabric mod (also loads on Quilt):** server-only (`"environment": "server"`), so it is never
  offered to players. Builder's call how to reach the server and the latency (see Left to the
  builder); the preference is no dependency on Fabric API, so the helper never pulls in other mods.
- **NeoForge, Forge (step two):** same file, same behaviour, their own jars.

**Building and shipping:**
- Source in `helpers/ping/` (a Gradle project per platform, or one multi-project build).
- The built jars ship inside Craft Conductor as package data
  (`src/craft_conductor/helpers/craft_conductor_ping-<platform>-<version>.jar`).
- CI builds them from source; a check fails when the shipped jars don't match a fresh build, so
  what's in the repository is always what the source makes (builder's call how: reproducible Gradle
  builds and a hash compare, or building in the release workflow only).
- Each jar declares the Minecraft and loader range it supports. A server outside the range gets no
  helper and the card says why.

**Craft Conductor's side:**
- **Turning it on:** per server, never by default (the owner's decision on 2026-11-20: "per
  server"). A server setting, `[players] ping = true` in `craft-conductor.toml` (off by default). The Connected Players card shows **Show players' ping…** where ping is "—" and the
  server type can run the helper. It explains in one short paragraph what gets added (a small
  Craft Conductor mod or plugin on the server only; players install nothing) and asks; **Turn on**
  sets the setting. Needs `mods.manage`. Settings → Players has the same switch to turn it off.
- **Installing:** the helper's jar is copied into `mods/` (or `plugins/`) when the server next
  starts (mods load only at start), and taken out when the setting is off. The card says
  "Ping shows after the next restart" until the file appears. It is recorded as Craft Conductor's
  own file, not as a mod the owner added:
  - not listed as "added by hand" (`unmanaged_jars`), not in update readiness, not in the setup or
    Mods page load check problems as the owner's mod;
  - **Manage Mods** shows it as one row, "Craft Conductor Ping (Craft Conductor's own: shows
    players' ping)", with no Change version or Remove (the switch does that);
  - left out of the friends' download and of **Make a modpack…** (named under Not included:
    "Craft Conductor's own helper: only for the server");
  - updated by itself when a newer Craft Conductor ships a newer jar (replaced at the next start).
- **Reading:** `roster(pings=...)` gets its source from `ping.json`:
  - read only while the card is polled and the server runs; at most once per poll;
  - opened without following links (like `servericon.read`), at most 64 KB, JSON checked: names are
    Minecraft names (3–16 of `A-Za-z0-9_`), values whole numbers 0–60000, anything else dropped;
  - a file older than 15 seconds, or from before the server's current start, counts as no reading
    (the card says "waiting for the server" rather than showing old numbers).
- **The card:** the existing good / fair / poor colours and words. Viewers who can see the card see
  the ping (`status.view`, as today).
- **The reason text** (`NO_PING_REASON`) changes: vanilla says ping needs a server type that runs
  mods or plugins; a supported server with it off says it's off, with the button for those who may
  turn it on.

## Security

- The file is written by the server process inside the server folder; Craft Conductor treats it as
  untrusted input (size cap, no links, strict JSON shape) because a mod or a person with file access
  could write anything there.
- The helper only reads ping and writes one file: no network, no commands, no reflection into other
  mods.
- The shipped jars are built from the repository's source, checked in CI.

## Constraints

- Craft Conductor's runtime stays Python standard library only; Java and Gradle are needed only to
  build the helper (CI and anyone changing it), not to run Craft Conductor.
- House rules from CLAUDE.md: manual (Dashboard / Players sections), Help, translations in 9
  languages, CHANGELOG under 0.31.0 (not released yet), real-world tests via
  `tools/real_world_tests.py add-test`, the website demo's simulated routes, screenshots for the
  changed card, and a security then efficiency review before the merge.
- `feature/servers-and-players` and `feature/mods-and-modpacks` also add a 0.31.0 changelog section
  and TODO ticks; whichever merges later resolves those files.

## Left to the builder

- How the Fabric mod reaches the server and each player's latency across Minecraft versions (the
  connection classes changed in 1.20.2), and whether one jar can cover the whole supported range or
  it needs one per range. Verify against the real versions Craft Conductor creates.
- The Gradle layout, Java target (the oldest Java the supported servers run on), and how CI
  proves the shipped jars match the source.
- Where in the lock (or beside it) Craft Conductor records its own file, and the exact wording of
  the card's texts.
- Roadmap 306 (a friend renaming a server) is on this branch too but is designed separately.
