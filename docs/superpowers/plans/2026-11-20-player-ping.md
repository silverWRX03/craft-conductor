# Players' Ping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show each player's real ping on the Dashboard's Connected Players card for Paper, Purpur,
Fabric and Quilt servers, through a tiny server-only helper of our own that the owner turns on per
server.

**Architecture:**
- Two small Java helpers in `helpers/ping/` (a Paper plugin, a Fabric mod). Each writes
  `.craft-conductor/ping.json` in the server folder every 5 seconds. Their built jars ship inside
  Craft Conductor in `src/craft_conductor/helpers/`; CI proves the jars match the source.
- A standard-library module `pinghelper.py` picks the jar for a server, puts it in (or takes it out
  of) the mods/plugins folder just before each start, and reads the file for
  `Players.roster(pings=...)`.
- The page turns it on and off from the Connected Players card.

**Tech Stack:** Java 16 (plugin) / Java 17 (Fabric mod) with Gradle 8.x; Python 3.11 standard
library; vanilla JS under CSP; pytest; Playwright (node) for browser tests.

**Spec:** `docs/superpowers/specs/2026-11-20-player-ping-design.md`

## Global Constraints

- Runtime stays Python standard library only. Java and Gradle are needed only to build the helpers.
- Names: mod id / plugin name `craft_conductor_ping`; jar names
  `craft_conductor_ping-<platform>-<helper version>.jar` (`paper`, `fabric`); setting
  `[players] ping` in `craft-conductor.toml`, off by default, **per server, never on by default**.
- The file: `.craft-conductor/ping.json` in the server's working folder,
  `{"version": 1, "time": <unix ms>, "players": {"<name>": <ms>}}`, written every 5 seconds to a
  temporary file in the same folder and renamed over the old one.
- The helper writes nothing else, opens no port, adds no command. Log lines: one at start
  ("Craft Conductor Ping: reporting players' ping to Craft Conductor"), and one the first time the
  file can't be written.
- Reading: at most 64 KB, never through a link, `players` values whole numbers 0–60000, keys
  strings of at most 32 characters; a file whose `time` is more than 30 s old counts as no reading.
- Supported: Paper/Purpur 1.17 and newer; Fabric/Quilt 1.20.2 and newer (Task 2 may narrow or split
  this after checking real servers). Everything else keeps "—".
- Who: turning it on or off needs `mods.manage`; seeing ping is as today (`status.view`).
- Every user-visible string through `t()`, translated into all 9 catalogs
  (`webui/i18n/{es,pt,fr,de,hi,zh,vi,ar,ko}.json`, `json.dumps(ensure_ascii=False, indent=2)`).
- Manual, Help, CHANGELOG `## 0.31.0 (not released yet)`, real-world tests via
  `python tools/real_world_tests.py add-test --id <next free, from 1056>` (1049–1055 are taken on
  other branches).
- Tests: `../craft-conductor/.venv/Scripts/python.exe -m pytest -q`; browser tests with
  `CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=E:/craft-conductor/craft-conductor/node_modules/playwright`.

## Review Focus

1. A Bedrock player through Floodgate (name starts with the server's prefix, e.g. `.Steve`): their
   ping shows like anyone's. (Test in Task 3: a `.Steve` key is kept.)
2. The setting is on, then the server is switched to vanilla or to Minecraft 1.20.1: the jar is taken
   out at the next start, and the card says why there's no ping. (Task 3.)
3. A server restarted within seconds: no player shows the previous run's numbers. `sync` deletes the
   old file before start. (Task 3.)
4. An update (`Manager.apply`) rebuilds the mods folder: the helper is back at the next start, and
   it's never reported as a mod "added by hand" or a load-check problem. (Task 3.)
5. `ping.json` replaced by a link, a 10 MB file, or `{"players": {"x": "fast"}}`: no crash, no ping,
   nothing read outside the server folder. (Task 3.)

---

### Task 1: The Paper/Purpur plugin, its build, and the CI check

**Files:**
- Create: `helpers/ping/settings.gradle`, `helpers/ping/paper/build.gradle`,
  `helpers/ping/paper/src/main/java/craft_conductor/ping/PingPlugin.java`,
  `helpers/ping/paper/src/main/resources/plugin.yml`, `helpers/ping/README.md` (how to build, which
  Gradle and JDK)
- Create: `tools/build_helpers.py` (runs Gradle, copies the jars into `src/craft_conductor/helpers/`)
- Create: `.github/workflows/helpers.yml`
- Create: `src/craft_conductor/helpers/craft_conductor_ping-paper-1.0.0.jar` (built)
- Modify: `pyproject.toml` package-data (`"helpers/*.jar"`), `packaging/craft-conductor.spec` datas
- Test: `tests/test_ping_helper_jars.py`

**Interfaces:**
- Produces: the jar above; `tools/build_helpers.py` with `--check` (build into a temporary folder
  and exit 1 when a shipped jar's SHA-256 differs).

- [ ] **Step 1: Write the failing test** `test_the_paper_helper_is_shipped`: open the jar as a zip;
  `plugin.yml` has `name: craft_conductor_ping`, `api-version: "1.17"`, `main:
  craft_conductor.ping.PingPlugin`; the jar holds no file outside `plugin.yml`, `META-INF/` and
  `craft_conductor/ping/`.
- [ ] **Step 2: Run it to see it fail.** `python -m pytest tests/test_ping_helper_jars.py -q`:
  FAIL (no jar).
- [ ] **Step 3: Write the plugin.** `onEnable`: log the start line; `runTaskTimer(this, collect,
  100L, 100L)` where `collect` builds a `name → Player#getPing()` map on the main thread and hands
  it to `runTaskAsynchronously` to write the file (Global Constraints). Compile against
  `io.papermc.paper:paper-api:1.17.1-R0.1-SNAPSHOT` (`compileOnly`, repo
  `https://repo.papermc.io/repository/maven-public/`), Java 16 release. Jar tasks set
  `preserveFileTimestamps = false` and `reproducibleFileOrder = true`.
- [ ] **Step 4: `tools/build_helpers.py`** (no Gradle wrapper jar in the repository: it runs the
  `gradle` on PATH, or `GRADLE` from the environment) and **`helpers.yml`**: on changes to
  `helpers/**` or `src/craft_conductor/helpers/**`, set up Temurin 21 and Gradle 8.10.2
  (`gradle/actions/setup-gradle`), run `python tools/build_helpers.py --check`, and upload the
  built jars as an artifact (so a jar built in CI can be committed when a local JDK differs).
- [ ] **Step 5: Build, then run the test.** PASS. `python tools/build_helpers.py --check` exits 0
  twice in a row (the build is reproducible on this computer).
- [ ] **Step 6: Commit** `feat: Craft Conductor Ping, the Paper and Purpur plugin (47)`

### Task 2: The Fabric/Quilt mod

**Files:**
- Create: `helpers/ping/fabric/build.gradle`, `.../fabric/src/main/java/craft_conductor/ping/PingMod.java`,
  `.../fabric/src/main/resources/fabric.mod.json`
- Create: `src/craft_conductor/helpers/craft_conductor_ping-fabric-1.0.0.jar` (built)
- Modify: `tools/build_helpers.py` (builds both), `tests/test_ping_helper_jars.py`
- Test: `tests/test_ping_helper_real.py` (new, optional: skipped unless `CRAFT_REAL_SERVERS=1` and
  `CRAFT_MINEFLAYER=<path to the mineflayer package>`)

**Interfaces:**
- Produces: the jar; `fabric.mod.json` `"id": "craft_conductor_ping"`, `"environment": "server"`,
  `"depends": {"fabricloader": ">=0.14", "minecraft": ">=1.20.2"}` (the upper bound decided in Step 5).

- [ ] **Step 1: Failing test** `test_the_fabric_helper_is_shipped`: `fabric.mod.json` as above;
  no `fabric-api` dependency; entry point `server` only.
- [ ] **Step 2: Run it.** FAIL (no jar).
- [ ] **Step 3: Write the mod.** Fabric Loom, Mojang mappings, compiled against Minecraft 1.20.2
  and fabric-loader only (no Fabric API). A `DedicatedServerModInitializer` starts one daemon
  `ScheduledExecutorService` thread: every 5 s it takes `FabricLoader.getInstance().getGameInstance()`
  (the `MinecraftServer`, null until it exists), and `server.execute(...)` collects
  `player.getScoreboardName() → player.connection.latency()` on the server thread, then writes
  the file from the scheduler thread. The working folder is `FabricLoader.getInstance().getGameDir()`.
  Reproducible jar settings as in Task 1 (on `remapJar` too).
- [ ] **Step 4: Run the jar test.** PASS; `build_helpers.py --check` exits 0.
- [ ] **Step 5: Check real servers** with `tests/test_ping_helper_real.py`
  `test_fabric_ping_on_real_servers`: for Minecraft 1.20.2, 1.20.4, 1.21.1 and the newest release
  Fabric supports, make a Fabric server with `online-mode=false` through Craft Conductor's own
  `setup`/`Manager`, turn `[players] ping` on, start it, join with a mineflayer bot, and wait up to
  20 s for `ping.json` to list the bot with a whole number. Where a version fails to load the jar
  (for example Minecraft 26.x if Fabric no longer remaps there), either add a second build compiled
  for that range (`craft_conductor_ping-fabric26-…`) or set the upper bound in `fabric.mod.json`
  and in `pinghelper.SUPPORT` (Task 3) so those servers keep "—" with a reason. Record which.
- [ ] **Step 6: Commit** `feat: Craft Conductor Ping, the Fabric and Quilt mod (47)`

### Task 3: Craft Conductor's side: setting, install, read

**Files:**
- Create: `src/craft_conductor/pinghelper.py`
- Modify: `src/craft_conductor/config.py` (`Config.player_ping: bool = False`, read from
  `[players] ping`; the default config text gets a commented line), `src/craft_conductor/manager.py`
  (`start_server` calls `pinghelper.sync(self)` before `proc.start()`; `unmanaged_jars` and
  `disabled_jars` leave out helper files), `src/craft_conductor/players.py` (reasons),
  `src/craft_conductor/web.py` (`players_online` passes `pings=`)
- Test: `tests/test_pinghelper.py`

**Interfaces:**
- Produces:
  - `pinghelper.PING_FILE = Path(".craft-conductor") / "ping.json"`, `MAX_BYTES = 65536`,
    `FRESH_SECONDS = 30`, `MAX_MS = 60000`, `PREFIX = "craft_conductor_ping-"`.
  - `pinghelper.SUPPORT: dict[str, tuple[str, str | None, str]]`: loader → (lowest Minecraft,
    highest or None, platform): `paper`/`purpur` → ("1.17", None, "paper"); `fabric`/`quilt` →
    ("1.20.2", <from Task 2>, "fabric").
  - `helper_jar(loader: str, minecraft: str) -> Path | None`
  - `unsupported_reason(loader: str, minecraft: str) -> str | None`: None when supported, else one of
    (exact): `"Minecraft doesn't share each player's ping without a mod or plugin, and plain Minecraft runs neither."`
    (vanilla), `"Craft Conductor's ping helper needs Minecraft {version} or newer on this server type."`,
    `"Craft Conductor's ping helper doesn't run on {loader} yet."` (NeoForge, Forge until step two).
  - `is_helper(filename: str) -> bool` (`PREFIX` and `.jar` or `.jar.disabled`).
  - `sync(m) -> None`: never raises (logs a warning). Deletes `PING_FILE`; with `m.config.player_ping`
    and a jar for the server, copies it into `m.mods_dir` (skipping the copy when the same file is
    there) and removes any other helper file; otherwise removes every helper file.
  - `read(server_dir: Path, now: float) -> dict[str, int] | None`: opened with `O_NOFOLLOW` (as
    `servericon.read`), `MAX_BYTES + 1` read and refused when over; `version == 1`; fresh by
    `time`; values filtered as in Global Constraints. None for anything else.
  - `players.Players.roster(online, pings=None, whitelist=False, why_no_ping: str = NO_PING_REASON)`;
    `players_online` returns `ping: {available, reason, can_turn_on: bool, on: bool}` where
    `can_turn_on` is supported and off, and the reason is `unsupported_reason(...)`,
    `"Ping is off for this server."`, `"Ping shows after the next restart."` (on, no fresh file,
    the jar not yet in the folder), or `"Waiting for the server to report ping…"` (on, jar in place,
    no fresh file).
- Consumes: Tasks 1–2's jars (tests use a fake jar written into a temporary `helpers` folder through
  a `monkeypatch` of `pinghelper.JARS_DIR`).

- [ ] **Step 1: Failing tests** in `tests/test_pinghelper.py`:
  - `test_support`: `helper_jar("paper", "1.21.1")` and `("fabric", "1.20.2")` exist;
    `("fabric", "1.20.1")`, `("vanilla", "1.21.1")`, `("neoforge", "1.21.1")` are None with the exact
    reasons; `is_helper("craft_conductor_ping-fabric-1.0.0.jar")` True, `is_helper("sodium.jar")` False.
  - `test_sync_puts_it_in_and_takes_it_out(make_config, http, modrinth)`: a Fabric 1.21.1 server;
    with `player_ping` on, after `sync` the jar is in `mods/` and not in `unmanaged_jars()`; an older
    helper version there is removed; a stale `ping.json` is deleted; switched off, the jar is gone;
    switched to vanilla with it on, the jar is gone.
  - `test_sync_never_stops_a_start`: `mods_dir` unwritable (monkeypatch `shutil.copyfile` to raise
    `OSError`): `start_server` still starts.
  - `test_read`: a fresh file gives `{"Alex": 42, ".Steve": 80}`; values `"fast"`, `-1`, `True`,
    `70000` and a 40-character key are dropped; a file 16 s old, a `version: 2` file, a 70 000-byte
    file, invalid JSON and (where the OS allows links) a link to a file outside give None.
  - `test_roster_reasons(hub_env)`: GET `/api/servers/alpha/players/online` (the route the card polls)
    on the Fabric server `alpha`: off → `available False`, `can_turn_on True`, reason
    "Ping is off for this server."; with `[players] ping = true` and a fresh file for an online
    player → `ping_ms` shown and `ping_state` "good".
- [ ] **Step 2: Run them.** FAIL (no module).
- [ ] **Step 3: Implement** as in Interfaces. Version order: `preview._version_key`.
- [ ] **Step 4: Run them.** PASS. Also `python -m pytest tests/test_players*.py tests/test_manager*.py -q`.
- [ ] **Step 5: Commit** `feat: put the ping helper in, take it out, and read it (47)`

### Task 4: Turning it on and off, and Manage Mods

**Files:**
- Modify: `src/craft_conductor/web.py` (`SETTINGS["player_ping"] = ("players", "ping", bool)`,
  shown in `settings()`; `/api/mods` adds `"helper": {"name": "Craft Conductor Ping", "filename": …}`
  when a helper file is in the folder), `src/craft_conductor/access.py`
  (`SETTING_NEEDS["player_ping"] = ("mods.manage",)`), `src/craft_conductor/webui/app.js`,
  `src/craft_conductor/webui/style.css`
- Test: `tests/test_pinghelper.py` (API), `tests/ui_player_ping.cjs` + `tests/test_ui_player_ping.py`

**Interfaces:**
- Consumes: Task 3's `ping` block (`available`, `reason`, `can_turn_on`, `on`).
- The card:
  - With `can_turn_on` and `can("mods.manage")`: **Show players' ping…** under the ping note. It asks
    (`ask(...)`, exact): "Show players' ping? Craft Conductor adds its own small helper (a mod or
    plugin that only runs on the server) at the next restart. Players don't install anything."
    with ok **Turn on**; then POSTs the setting and toasts "Ping shows after the next restart."
  - With `on` and `can("mods.manage")`: a small **Stop showing ping** link-button (asks: "Stop
    showing players' ping? The helper is taken off the server at the next restart." ok **Stop**).
- Manage Mods: one row "Craft Conductor Ping" with the tag "Craft Conductor's own: shows players'
  ping", no Change version, no Remove.

- [ ] **Step 1: Failing tests:** `test_turning_ping_on_needs_mods_manage(hub_env)`: a person with
  `settings.safe` only gets 403 on `{"player_ping": true}`; the owner gets 200 and the config says
  `ping = true`. In `ui_player_ping.cjs` (login as in `ui_mods_and_packs.cjs`): on
  `#s/alpha/dashboard`, **Show players' ping…** → the question → **Turn on** → the toast; the button
  is replaced by **Stop showing ping**; no page errors.
- [ ] **Step 2: Run them.** FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them.** PASS (the browser test with the env above).
- [ ] **Step 5: Commit** `feat: Show players' ping on the Connected Players card (47)`

### Task 5: Help, translations, changelog, demo, real-world tests, screenshot, TODO

**Files:**
- Modify: `src/craft_conductor/webui/manual.md` (`## Dashboard` Connected Players: how to turn ping
  on, what's added, which servers; `## Mods`: the Craft Conductor Ping row), `HELP` in app.js (where
  it mentions the Connected Players card), `webui/i18n/*.json`, `CHANGELOG.md` (`## 0.31.0 (not
  released yet)`, Added), `TODO.md` (47 `[x]`, "Paper, Purpur, Fabric and Quilt; NeoForge and Forge
  next"), `testing/catalog.json`, `site/demo/app/sim/*.js` (the `ping` block and the setting),
  `src/craft_conductor/webui/screenshots/connected-players.png`
- Test: `tests/test_website_demo_contract.py`, `tests/test_i18n.py`, the full suite

- [ ] **Step 1:** The manual, Help and changelog in plain words with the app's button names.
- [ ] **Step 2:** Translations of every new `t()` string and reason text, all 9 catalogs, with a
  script in the scratchpad.
- [ ] **Step 3:** Demo: the simulated `players/online` gives a Fabric example server ping numbers
  when its `player_ping` setting is on. `python -m pytest tests/test_website_demo_contract.py -q`:
  PASS.
- [ ] **Step 4:** Real-world tests (Extra), from id 1056: Paper ping shown after turning on and a
  restart; Fabric the same; turning off takes the helper out; a vanilla server shows the reason;
  a friend joining from a vanilla client is unaffected. `python tools/real_world_tests.py verify`.
- [ ] **Step 5:** Retake `connected-players.png` (`tests/test_screenshots.py`, keep only the files
  this change affects).
- [ ] **Step 6:** `python -m pytest -q`: all pass (skips allowed).
- [ ] **Step 7: Commit** `docs: manual, help, translations, changelog and tests for players' ping`

### Task 6: Review, then after the mods branch merges

- [ ] **Step 1:** Security then efficiency review (CLAUDE.md): the file read (links, size, shape),
  the jar copy (only into the server's own folder, only our file names), the setting's permission;
  the card's poll reads at most one small file per poll. Fix what's found.
- [ ] **Step 2:** Once `feature/mods-and-modpacks` is in `main`: merge `main` in, and in
  `makepack._mods` name the helper under `left_out` with the why
  `"Craft Conductor's own helper: only for the server"`; a test in `tests/test_make_modpack.py`
  (`test_the_ping_helper_is_named_not_packed`). Resolve the CHANGELOG and TODO sections.
- [ ] **Step 3:** Push, open the pull request, CI green (including `helpers.yml`).

Step two of the design (NeoForge, then Forge) gets its own plan once this one ships.
