# Players' Ping, Step Two (NeoForge and Forge) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show players' ping on NeoForge (1.20.2+) and Forge (1.20.1+) servers with the same
server-only helper, so every modded server type Craft Conductor runs has it.

**Architecture:** One more Gradle subproject per loader in `helpers/ping/` (`neoforge/`, `forge/`),
sharing `common/` (`PingFile`). Each produces one jar per Minecraft range whose game names or loader
API differ. `pinghelper.SUPPORT` gets a row per jar; `sync`, `read`, `card` and the page are
unchanged.

**Tech Stack:** Java 17/21, Gradle 8.10.2 with the loaders' own Gradle plugins (NeoForge's
ModDevGradle, Forge's ForgeGradle); Python 3.11 standard library; pytest.

**Spec:** `docs/superpowers/specs/2026-11-20-player-ping-design.md` (the "Step two" section, and
everything before it that it reuses).

## Global Constraints

- Floors: Forge from Minecraft 1.20.1; NeoForge from 1.20.2. Older keeps "—" with the existing
  reason "Craft Conductor's ping helper needs Minecraft {version} or newer on this server type."
- Same file and behaviour as step one: `.craft-conductor/ping.json`,
  `{"version": 1, "time": <unix ms>, "players": {"<name>": <ms>}}`, every 5 s, through the shared
  `helpers/ping/common` `PingFile` (temporary file, atomic rename, one start log line
  "Craft Conductor Ping: reporting players' ping to Craft Conductor", one warning on the first
  failure). No network channel or payload, no command, no config, no other file.
- Server-only: a vanilla client must be able to join a server holding the helper.
- Names: mod id `craft_conductor_ping`; jars `craft_conductor_ping-<platform>-1.0.0.jar` with
  platforms `neoforge…`/`forge…` (a suffix per range when there is more than one, as `fabric26`).
- Exactly one helper jar per server folder; each jar declares its Minecraft range in its own
  metadata, matching its `SUPPORT` row.
- Byte-identical jars on Windows (JDK 21.0.10) and Linux (`gradle:8.10.2-jdk21` in WSL Docker), and
  `python tools/build_helpers.py --check` exits 0. If a loader's tools can't do that, stop and report.
- Tools: JDK 21 `C:/Program Files/Java/jdk-21.0.10`; Gradle 8.10.2 via `GRADLE`; Python
  `E:/craft-conductor/craft-conductor/.venv/Scripts/python.exe`; mineflayer
  `E:/craft-conductor/bots/node_modules/mineflayer` (it joins up to Minecraft 26.1).
- Real-world tests from id 1061; CHANGELOG under the existing `## 0.31.0 (not released yet)` Added
  line for ping; translations in all 9 catalogs for any new or changed text.

## Review Focus

1. A vanilla client (the mineflayer bot) joining a NeoForge or Forge server with the helper: it
   joins, and shows in `ping.json`. (Real-server test in Tasks 1–3.)
2. Forge 1.20.1 modpack servers often run hundreds of mods: the helper must not slow the start
   or log anything per tick. (Read the log tail in the real test: one start line only.)
3. A server switched between Forge and NeoForge, or across a range boundary: `sync` swaps to the
   right jar and never leaves two. (Unit test in each task's `SUPPORT` change.)
4. A loader version older than the helper's declared loader minimum (for example an old Forge
   47.0.x build on 1.20.1): either the range admits it or the jar's metadata says so and
   `SUPPORT`/the card treat it as unsupported. (Check the loader version range in the metadata.)
5. The new jars contain only our classes plus metadata (no shaded libraries).
   (Jar test in each task.)

---

### Task 1: NeoForge (1.20.2 and newer)

**Files:**
- Create: `helpers/ping/neoforge/build.gradle`, `.../neoforge/src/main/java/craft_conductor/ping/PingNeoForge.java`,
  the metadata file(s) NeoForge needs (`META-INF/neoforge.mods.toml` from 1.20.5, `META-INF/mods.toml` before)
- Create: `src/craft_conductor/helpers/craft_conductor_ping-neoforge*-1.0.0.jar` (built)
- Modify: `helpers/ping/settings.gradle`, `tools/build_helpers.py`, `helpers/ping/README.md`,
  `src/craft_conductor/pinghelper.py` (`SUPPORT` rows), `tests/test_ping_helper_jars.py`,
  `tests/test_pinghelper.py` (`test_support`, `test_support_matches_the_ranges_the_jars_declare`),
  `tests/test_ping_helper_real.py`

**Interfaces:**
- Consumes: `PingFile` from `helpers/ping/common`; `pinghelper.SUPPORT` rows
  `(loaders, lowest, below-or-None, platform)`.
- Produces: NeoForge rows in `SUPPORT`, lowest `"1.20.2"`; the range split decided in Step 4.

- [ ] **Step 1: Failing tests.** `test_the_neoforge_helper_is_shipped`: each NeoForge jar holds only
  `craft_conductor/ping/*`, `META-INF/*` and its metadata; the metadata has `modId="craft_conductor_ping"`,
  a `minecraft` dependency range and a `neoforge` dependency range, and declares the mod not
  required on clients. `test_support`: `helper_jar("neoforge", "1.21.1")` exists;
  `("neoforge", "1.20.1")` is None with the "needs Minecraft 1.20.2" reason.
- [ ] **Step 2: Run them.** FAIL (no jar).
- [ ] **Step 3: Write the mod.** Same shape as `PingMod` (Fabric): the mod's constructor starts one
  daemon scheduled thread; every 5 s it takes the current server (`ServerLifecycleHooks.getCurrentServer()`),
  collects `getScoreboardName() → latency` on the server thread with `CompletableFuture.supplyAsync(…, server)`,
  and writes through `PingFile` from the scheduler thread; a `pending` flag stops pile-ups; every
  Throwable in a tick is caught. The folder is the server's working folder. Reproducible jar settings
  as in the other subprojects.
- [ ] **Step 4: Real servers.** Extend `test_ping_helper_real.py` with NeoForge 1.20.2, 1.20.4,
  1.20.6, 1.21.1, the newest 1.21.x and 26.1 (whichever exist): `[players] ping = true`, start,
  bot joins, `ping.json` lists it. Where the game's names or NeoForge's API differ across the range
  (expected around 1.20.5, when NeoForge moved to Mojang's names at runtime), add a second jar for
  that range and its `SUPPORT` row. Record which jar covers what at the top of the report.
- [ ] **Step 5: Run** the jar tests, `test_pinghelper.py`, `build_helpers.py --check` (Windows) and the
  Linux Docker build of every jar (all byte-identical, Paper and Fabric jars unchanged).
- [ ] **Step 6: Commit** `feat: Craft Conductor Ping on NeoForge (47)`

### Task 2: Forge 1.20.1

**Files:**
- Create: `helpers/ping/forge/…` (Gradle subproject, `PingForge.java`, `META-INF/mods.toml`)
- Create: `src/craft_conductor/helpers/craft_conductor_ping-forge*-1.0.0.jar` (built)
- Modify: as Task 1 (settings.gradle, build_helpers.py, README, `SUPPORT`, the three test files)

**Interfaces:**
- Consumes: Task 1's layout and `SUPPORT` shape.
- Produces: a Forge row with lowest `"1.20.1"`.

- [ ] **Step 1: Failing tests.** `test_the_forge_helper_is_shipped` (as Task 1's, for `mods.toml`);
  `test_support`: `helper_jar("forge", "1.20.1")` exists; `("forge", "1.19.2")` is None with the
  "needs Minecraft 1.20.1" reason.
- [ ] **Step 2: Run them.** FAIL.
- [ ] **Step 3: Write the mod** like Task 1's, with Forge's API (`ServerLifecycleHooks` is in
  `net.minecraftforge.server`). Forge 1.20.1 runs with its own (SRG) names: build with ForgeGradle so
  the jar is reobfuscated to them; on 1.20.1 the latency is a field on the player
  (`ServerPlayer.latency`), not on the connection. Declare the mod server-only so vanilla clients
  join (`displayTest`).
- [ ] **Step 4: Real servers:** Forge 1.20.1 (two Forge builds: the recommended one and the oldest
  47.x Craft Conductor would install), bot joins, `ping.json` lists it.
- [ ] **Step 5: Run** as Task 1 Step 5. ForgeGradle's first build is slow (it rebuilds Minecraft);
  byte-identical output is required (Global Constraints).
- [ ] **Step 6: Commit** `feat: Craft Conductor Ping on Forge 1.20.1 (47)`

### Task 3: Forge 1.20.2 and newer

**Files:** as Task 2 (more `forge…` jars and `SUPPORT` rows as needed).

- [ ] **Step 1: Find out** on real Forge servers (1.20.2, 1.20.4, 1.20.6, 1.21.1, the newest 1.21.x,
  and 26.x if Forge has it) which runtime names Forge uses and where its API changed. Write the
  findings at the top of the report before building.
- [ ] **Step 2: Failing tests** for each new jar and row (as Task 2 Step 1).
- [ ] **Step 3: Build** the fewest jars that cover 1.20.2 to the newest Forge, one per range that
  differs.
- [ ] **Step 4: Real servers** for each range (bot joins, `ping.json` lists it).
- [ ] **Step 5: Run** as Task 1 Step 5.
- [ ] **Step 6: Commit** `feat: Craft Conductor Ping on newer Forge (47)`

### Task 4: Docs, translations, demo, real-world tests

**Files:** `src/craft_conductor/webui/manual.md`, `HELP` in app.js, `CHANGELOG.md` (the existing ping
line: add NeoForge and Forge), `TODO.md` (47: drop "NeoForge and Forge next"), `testing/catalog.json`,
`site/demo/app/sim/*.js` (support rules: NeoForge and Forge), the 9 catalogs if any text changed,
`src/craft_conductor/pinghelper.py` (the NOT_YET reason stays for anything still unsupported).

- [ ] **Step 1:** Manual, Help, changelog and TODO in plain words: which server types and versions
  show ping now.
- [ ] **Step 2:** Demo: a NeoForge or Forge example server can turn ping on. Run
  `tests/test_website_demo_contract.py`: PASS.
- [ ] **Step 3:** Real-world tests (Extra) from id 1061: NeoForge ping shown after turning on and a
  restart; Forge 1.20.1 the same on a modpack server; a vanilla client joins each.
  `python tools/real_world_tests.py verify`: 0 errors.
- [ ] **Step 4:** Full suite `python -m pytest -q`: all pass (the known test_reach port 8766 failure
  aside).
- [ ] **Step 5: Commit** `docs: ping on NeoForge and Forge in the manual, help and tests`
