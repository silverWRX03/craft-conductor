# Bug hunt report (October 2026)

**Status:** first pass complete; Q1-Q3 decided and done, Q4-Q5 open.
**Branch:** `audit/comprehensive-bug-hunt-2026-10`, from `main` at `11f9721` (0.26.0 + the 26.x player fix).
**Scope:** the whole application: server lifecycle, mods and modpacks, backups and restores, the
control panel and its API, friends' downloads, self-updates, and the web page.

This report records what was looked at, what was found, what was fixed, and what is still open.
It is not a claim that every bug was found. Security findings are described at the level needed to
fix them, without step-by-step exploit details.

## Summary

| ID | Title | Severity | Confidence | Status |
|---|---|---|---|---|
| BUG-001 | Server names outside the computer's code page break server creation and settings on Windows | P2 | Confirmed | Fixed |
| BUG-002 | A scheduled restart is dropped when a scheduled backup is due in the same minute | P2 | Confirmed | Fixed |
| BUG-003 | Scheduled backups and restarts are skipped after a job longer than 10 minutes | P3 | High confidence | Fixed |
| BUG-004 | Settings in `hub.json` can be silently undone by a concurrent save (UPnP sync) | P3 | Confirmed | Fixed |
| BUG-005 | Backups of a running server wait a fixed 5 s for the world to be saved | P2 | High confidence | Fixed |
| BUG-006 | Ticking "required" on a mod drops its early-builds channel and datapack setting | P2 | Confirmed | Fixed |
| BUG-007 | Ban lists with non-ASCII reasons read as empty on Windows, then wiped by the next edit | P2 | Confirmed | Fixed |
| BUG-008 | Saved mod lists forget which mods are datapack builds | P3 | Confirmed | Fixed |
| BUG-009 | A hand-edited `craft-conductor.toml` in another language breaks on Windows | P3 | Confirmed | Fixed |
| BUG-010 | Double-clicking Create my server shows a false "port already used" error | P3 | Confirmed | Fixed |
| BUG-011 | Double-clicking Start, Restart or Stop shows a false "busy" error | P3 | Confirmed | Fixed |
| BUG-012 | A server can be given Craft Conductor's own port (and the reverse) | P4 | Confirmed | Fixed |
| BUG-013 | A busy control panel port ends in "stopped unexpectedly" with a socket error | P3 | Confirmed | Fixed |

Severity: P0 critical … P4 informational. Confidence: Confirmed (reproduced), High confidence (code
and test evidence, no full reproduction), Suspected, Not reproducible.

## Testing environment and baseline

- Windows 11 Pro 23H2 (10.0.22631), Python 3.12.6 (project `.venv`), Node 24.21.0. Locale encoding cp1252.
- Linux and macOS: **not tested locally**; CI (`test.yml`) runs Linux 3.11–3.13, Windows and macOS 3.12.
- Baseline on `11f9721`: `pytest -q`: **743 passed, 30 skipped, 0 failed** (6 min 12 s).
  Skipped: browser tests (opt-in, "optional browser verification"), symlink tests (Windows needs a
  privilege), Unix permission-bit tests, Linux-only CPU affinity, shell-script Java stand-ins,
  Web Push vectors (no `cryptography`), documentation screenshots (on request).
- No build was made locally: test builds come from CI (`test.yml` → `package`).

## Findings

### BUG-001: server names outside the computer's code page break server creation and settings on Windows

- **Severity / confidence:** P2 / Confirmed (reproduced on Windows, cp1252).
- **Component:** `properties.py` (`server.properties` reading and writing).
- **Description:** `server.properties` was read and written in the computer's own text encoding
  (cp1252 on most Windows computers), not as the Java properties file it is.
- **Impact:** on Windows, **Create my server** fails with "'charmap' codec can't encode characters"
  for a name in Chinese, Korean, Hindi, Arabic, Vietnamese, or with an emoji (the app is translated
  into these languages). The failure happens after `craft-conductor.toml` is written, leaving a
  half-made server folder. A name with accents shows up garbled ("CafÃ©") once Minecraft has
  rewritten the file in UTF-8, and some (like "Á") then make every later change to
  `server.properties` (port, settings) fail.
- **Reproduction:** on Windows, `write_properties(path, {"motd": "我的服务器"})` raises
  `UnicodeEncodeError`; a UTF-8 file containing `motd=Ángel's Café` reads back as `Ã�ngel's CafÃ©`,
  and `write_properties(path, {"server-port": "25566"})` then raises `UnicodeEncodeError`.
- **Root cause:** `Path.read_text()` / `write_text()` without an encoding, and no Java escaping.
  Minecraft reads the file as UTF-8, falling back to ISO-8859-1, and understands `\uXXXX` escapes.
- **Fix:** read the file the way Minecraft does (UTF-8, else ISO-8859-1), unescape Java escapes
  (`\uXXXX`, `\:` …) when reading, write changed values as plain-ASCII Java escapes, and write the
  file back in the encoding it was read in, so untouched lines stay byte for byte.
- **Tests:** `tests/test_units.py`: `test_a_server_name_in_any_language` (5 names),
  `test_server_properties_as_minecraft_writes_them`, `test_a_new_server_named_in_any_language`.
  They failed before the fix (6 failures) and pass after it.
- **Related:** `craft-conductor.toml` had the same problem for hand-edited text (BUG-009).
- **Status:** Fixed.

### BUG-002: a scheduled restart is dropped when a scheduled backup is due in the same minute

- **Severity / confidence:** P2 / Confirmed (failing test).
- **Component:** `daemon.py` (`Daemon._run_schedules`).
- **Description:** when the backup and the restart schedules name the same minute, only the backup
  runs (`if backup_due … elif restart`). The restart's minute has passed by the next look, so it
  never happens.
- **Impact:** with **Make a backup: every hour** (or every 2 hours) and **Restart the server: every
  day at 4:00**, the nightly restart never happens.
- **Reproduction:** `tests/test_schedule.py::test_a_restart_and_a_backup_due_together_both_happen`
  (before the fix: only `["scheduled backup"]` was started, never the restart).
- **Root cause:** no "owed" restart, unlike the owed backup.
- **Fix:** see BUG-003 (one change): a due restart is remembered until it's done; with a backup due
  too, the backup goes first and the restart right after it.
- **Status:** Fixed.

### BUG-003: scheduled backups and restarts are skipped after a job longer than 10 minutes

- **Severity / confidence:** P3 / High confidence.
- **Component:** `daemon.py` (`_loop`, `_run_schedules`), `schedule.due`.
- **Description:** schedules are only looked at while no job runs. `schedule.due` treats a gap of
  more than 10 minutes since the last look as "the computer was asleep" and only checks the
  current minute. A backup or update that takes longer than 10 minutes over a scheduled time
  makes that backup or restart silently not happen, though the code (and its test) intend
  "made as soon as that's done, not skipped". (The existing test simulated "busy" with a refused
  `submit`, which the real loop never reaches, so it didn't catch this.)
- **Fix:** the loop looks at the schedules on every turn, busy or not, and only *starts* jobs when
  idle: a due backup or restart is remembered (`_backup_owed`, `_restart_owed`) and done as soon
  as the job finishes. "Asleep" (no look for 10 minutes) now only means the computer really slept.
  An owed restart is dropped when the server restarted after it came due (an update did it), when
  the server was stopped meanwhile, or (as before) when players are on with "Skip a scheduled
  restart while players are online". The manual's Schedule paragraph says so.
- **Tests:** `test_a_time_that_comes_during_a_long_job_isnt_skipped`,
  `test_an_owed_restart_isnt_done_twice_or_for_nothing` (`tests/test_schedule.py`).
- **Status:** Fixed.

### BUG-004: settings in `hub.json` can be silently undone by a concurrent save

- **Severity / confidence:** P3 / Confirmed (failing test).
- **Component:** `hub.py` (`_hub_file`, `_save_hub_file` and their callers).
- **Description:** `hub.json` (control panel host and allowed hosts, CurseForge key, Discord bot,
  friends' download settings, router forwarding, update channel, hidden servers) is changed by
  read-modify-write with no lock. Router forwarding (`upnp_sync`, every 30 minutes in the
  background when it's on) reads the file, talks to the router for several seconds, then writes
  its old copy back.
- **Impact:** a setting saved during that window is silently reverted, e.g. turning off access
  from other devices: the running panel follows the new setting, but the old one comes back the
  next time Craft Conductor starts. Remote access still needs the strong password, so this is a
  "the off switch didn't stick" problem rather than an open door.
- **Reproduction:** `tests/test_upnp.py::test_a_setting_saved_while_the_router_is_slow_stays_saved`:
  a router that takes a moment to answer, and the panel's host set to `127.0.0.1` meanwhile; before
  the fix hub.json ended with `0.0.0.0` again.
- **Root cause:** each writer read hub.json, changed its copy and wrote the whole file back, with no
  lock; `upnp_sync` held its copy across the router calls.
- **Fix:** `Hub._update_hub_file(change)` reads, changes and writes hub.json under one lock; every
  writer (control panel settings, CurseForge key, Discord bot and status message, friends'
  downloads, mod conflict sharing, extra and hidden server folders, router forwarding, update
  channel, the guided setup) goes through it, and network calls happen outside it. `upnp_sync`
  only writes its own part, from the file as it is at that moment.
- **Status:** Fixed.

### BUG-005: backups of a running server wait a fixed 5 seconds for the world to be saved

- **Severity / confidence:** P2 / High confidence (not reproducible without a large real world).
- **Component:** `daemon.py` (`backup_now`), `web.py` (export, beta test copy).
- **Description:** before copying a running server, Craft Conductor sends `save-off` and
  `save-all flush`, then sleeps 5 seconds, whether or not Minecraft has finished saving. A large
  modded world on a slow disk can take longer.
- **Impact:** the backup can hold region files Minecraft was still writing; the backup check reads
  the archive but can't tell a half-written chunk.
- **Root cause:** a fixed `time.sleep(5)` after `save-all flush`, copied into four places (backup,
  export, beta test copy, update rehearsal), while the map preview already waited for the answer.
- **Fix:** `ServerProcess.pause_saving()` sends `save-off`, then `save-all flush`, and waits for the
  server's "Saved the game" ("Saved the world" before 1.13) for up to 60 s; without the answer the
  copy still goes ahead (the old behaviour), with a warning. `resume_saving()` is in a `finally`,
  so `save-on` follows even when the save step itself fails. The four copies use it; the preview
  uses the same `save_all()`. The tests' stand-in servers now answer `save-all` as Minecraft does.
- **Tests:** `tests/test_units.py`: `test_a_running_server_is_copied_once_it_says_the_world_is_saved`
  (both wordings, a 1.5 s save), `test_a_server_that_never_says_its_saved_is_still_copied`; the
  flow and chaos tests still check `save-off`/`save-on` around a live backup.
- **Status:** Fixed.

### BUG-006: ticking "required" on a mod drops its early-builds channel and datapack setting

- **Severity / confidence:** P2 / Confirmed (failing test).
- **Component:** `web.py` (`Api.set_required`), also `Api.test_beta`'s copy.
- **Description:** the Mods page's **required** checkbox removes the mod's `[[mods]]` entry and
  writes a new one with only `source`, `id` and `required`, losing `channel` (early builds
  allowed) and `datapack` (installed as its datapack build).
- **Impact:** a mod that only has beta builds stops being installable at the next update (dropped,
  or holding the update back); a mod used as its datapack is switched to the mod build, which the
  server type may not have, and its datapack is taken out of the world.
- **Reproduction:** add a beta-only mod with its early builds (mod browser), untick **required**:
  `craft-conductor.toml` no longer has `channel = "beta"` for it (test below: `channel` became `None`).
- **Root cause:** `set_required` re-created the block from three fields instead of editing it.
- **Fix:** `config.set_mod_required` changes the `required` line inside the mod's own block (adding
  it when a hand-written block has none); everything else in the block, and its place in the list,
  stays. The beta test copy (`test_beta`) uses it too, so its mods keep their channel and datapack.
- **Tests:** `tests/test_early_builds.py::test_the_required_box_keeps_a_mods_channel_and_datapack`
  (failed before: `(False, None) != (False, 'beta')`), `tests/test_units.py::test_setting_required_changes_only_that`.
- **Status:** Fixed.

### BUG-007: ban lists with non-ASCII reasons read as empty on Windows, then wiped by the next edit

- **Severity / confidence:** P2 / Confirmed (reproduced on Windows; failing tests).
- **Component:** `players.py` (`Players._read`, `_offline`).
- **Description:** `ops.json`, `whitelist.json`, `banned-players.json` and `banned-ips.json` were
  read in the computer's own encoding, and any file that couldn't be read was treated as empty.
  When the server is stopped, Craft Conductor edits these files directly: it read the list,
  changed it and wrote it back.
- **Impact:** a ban reason in Chinese or Russian, or with letters like "Á" (UTF-8 bytes that
  cp1252 can't decode), made the Players page show no bans, and the next ban, unban, op or
  whitelist change made while the server was stopped wrote back a list with only that change:
  every earlier ban was wiped, so banned players could join again. The same happened for any
  damaged or half-written list. A hand-typed odd entry (`"Steve"` instead of an object) made those
  changes fail with an internal error.
- **Reproduction:** a `banned-players.json` with bans for Alex (reason "破坏建筑") and Steve, then
  `Players(server_dir).act("ban", "Kit")` with the server stopped: the file then held only Kit.
- **Root cause:** `json.loads(path.read_text())` (locale encoding) inside
  `except (FileNotFoundError, ValueError): return []`, used both for showing and for changing.
- **Fix:** the lists are read as UTF-8 (a byte-order mark is tolerated) and written as UTF-8, as
  Minecraft does. For a change, a file that's there but can't be read (or isn't a list) is refused
  with a message naming it, and left untouched; for showing, it still reads as empty. Odd entries
  are kept as they are and skipped when matching names.
- **Tests:** `tests/test_players.py::test_bans_in_any_language_survive_an_edit`,
  `test_a_list_that_cant_be_read_isnt_replaced` (both failed before the fix).
- **Status:** Fixed.

### BUG-008: saved mod lists forget which mods are datapack builds

- **Severity / confidence:** P3 / Confirmed (failing test).
- **Component:** `modsets.py` (Saved mod lists: save, restore, import).
- **Description:** a saved list kept each mod's source, id, required and channel, but not
  `datapack` (added in 0.26.0). Restoring a list, including the automatic "Before …" list used to
  undo a switch, wrote every mod back as a regular mod.
- **Impact:** as BUG-006 for each datapack mod: it's looked for as a mod for the server type,
  which it has no build for, and its datapack leaves the world at the next update.
- **Fix:** lists record `datapack`; a loaded list accepts it for Modrinth mods only; restore writes it back.
- **Tests:** `tests/test_modsets.py::test_a_saved_list_keeps_each_mods_settings` (failed before:
  `('terralith', True, None, False) != ('terralith', True, None, True)`).
- **Status:** Fixed.

### BUG-009: a hand-edited `craft-conductor.toml` in another language breaks on Windows

- **Severity / confidence:** P3 / Confirmed (reproduced on Windows; failing test).
- **Component:** `config.py` (`load` and the editing helpers), `snapshots.py`, `modsets.py`,
  `web.py` (`save_settings`).
- **Description:** TOML files are UTF-8, but `craft-conductor.toml` was read and written in the
  computer's own encoding. Values the app writes are ASCII-escaped, so only text edited by hand
  (the wiki's Power users pages describe doing so) is affected.
- **Impact:** on Windows, a UTF-8 comment or value with some characters (Chinese, "Á" …) made the
  server "unavailable" with "'charmap' codec can't decode byte 0x8f"; others were misread, e.g.
  `copy_to = "D:\Música"` became "MÃºsica", so backup copies quietly stopped (the folder "isn't there").
- **Fix:** `config.read_text` reads UTF-8 (a byte-order mark tolerated; a file saved by an old
  editor in the computer's own encoding still read), `config.write_text` writes UTF-8; every
  reader and writer of the file uses them, and the "put it back if saving fails" copies are kept
  as bytes, so they're restored exactly.
- **Tests:** `tests/test_units.py::test_a_hand_edited_config_in_any_language` (failed before with
  the `UnicodeDecodeError`).
- **Status:** Fixed.

### BUG-010: double-clicking Create my server shows a false "port already used" error

- **Severity / confidence:** P3 / Confirmed (reproduced in a real browser, Edge, with Playwright).
- **Component:** `webui/app.js` (the New server form's submit handler).
- **Description:** the form's submit handler had no in-flight guard and the button stayed
  enabled, so a double-click (or Enter pressed twice) sent `POST /api/hub/create` twice.
- **Impact:** the server is made once (the second request is refused because the first one just
  took the port), but a red "port 25566 is already used by another server here (…); pick another"
  appears next to "your server is ready", inviting a beginner to change the port and try again.
  For a server set up from `craft-conductor run`, the second request answered "busy" the same way.
- **Root cause:** `submit` started the request without marking the form busy.
- **Fix:** `submit` marks the form busy before its first `await`, ignores further submissions while
  busy, and keeps **Create my server** disabled until the request has finished.
- **Tests:** `tests/ui_browser.cjs` (run by `tests/test_ui_browser.py` with `CRAFT_UI_NODE` and
  `CRAFT_UI_PLAYWRIGHT` set) now double-clicks the button and checks for exactly one create request
  and no error: it failed before the fix (`['POST', 'POST']`). All 20 opt-in browser tests pass.
- **Status:** Fixed.

### BUG-011: double-clicking Start, Restart or Stop shows a false "busy" error

- **Severity / confidence:** P3 / Confirmed (reproduced in a real browser).
- **Component:** `webui/app.js` (the header's `#btn-start`, `#btn-restart`, `#btn-stop`).
- **Description:** the buttons were only disabled when the next status came back, so a
  double-click sent a second request, which the server refused as busy.
- **Impact:** a red "⚠ busy: start is running" next to "✓ start: started" on the most-used
  buttons; Stop's "Stop the server?" question could be asked twice.
- **Fix:** `pressOnce` disables the pressed button at once (a disabled button gets no second click);
  the status, refreshed after the press and every 2 seconds anyway, then sets what can be pressed.
- **Tests:** new opt-in browser test `tests/test_ui_power_buttons.py` (`ui_power_buttons.cjs`):
  double-clicks each button and expects exactly `['start', 'restart', 'stop']`, no "busy" error,
  one Stop question. It failed before the fix (`start` and `restart` each sent twice).
- **Status:** Fixed.

### BUG-012: a server can be given Craft Conductor's own port (and the reverse)

- **Severity / confidence:** P4 / Confirmed (failing tests).
- **Component:** `web.py` (`Api.save_settings`, `HubApi.save_share`), `hub.py` (`Hub.create`).
- **Description:** a server's Minecraft port was only checked against other servers' ports. The
  setup page shows "craft-conductor itself uses this port" in red but still creates the server, and
  a server's Settings accepted the control panel's or the friends' download port without a word;
  the friends' download port could be set to a server's port.
- **Impact:** the server (or the friends' download) can't start: the port is taken. Unlikely, but
  confusing when it happens.
- **Fix:** both are refused with a message naming the port's use; a port the person didn't pick
  moves to a free one, as for other servers' ports.
- **Tests:** `tests/test_hub.py::test_create_a_server_from_the_web`, `tests/test_friends.py`
  (both failed before).
- **Status:** Fixed.

### BUG-013: a busy control panel port ends in "stopped unexpectedly" with a socket error

- **Severity / confidence:** P3 / Confirmed (reproduced on Windows).
- **Component:** `web.py` (`WebUI.start`), `cli.py` (`cmd_start`).
- **Description:** when the control panel's port (8765) can't be used, because another program has
  it or Windows keeps it (Hyper-V and WSL set port ranges aside, which can include 8765), Craft
  Conductor printed the address (and would open the browser there, on the other program) and then
  stopped with "Craft Conductor stopped unexpectedly: [WinError 10013] An attempt was made to access
  a socket in a way forbidden by its access permissions".
- **Fix:** the failed bind becomes `PortBusy` with a message saying the port is taken or kept by
  Windows and what to do (close the other program, or `--web-port`); `craft-conductor start` shows it
  through `desktop.show_error` (a message box when there's no console window). The manual's
  Troubleshooting has the same.
- **Fallback (the owner's decision, Q2):** when the port wasn't chosen by hand (`--web-port`, or a
  port saved in `hub.json`), the control panel uses the next free port after it that time (skipping
  the friends' download port and the SSH tunnel port), logs a warning, opens that address, and
  notes it in `.craft-conductor/panel-url`, so opening Craft Conductor again goes to the right
  address. The share and web map port checks compare with the real panel port. Caveat (accepted):
  a phone set up through Tailscale only reaches the usual port. `craft-conductor run` (its port is
  in `craft-conductor.toml`) keeps the message only.
- **Tests:** `tests/test_hub.py::test_start_when_the_control_panels_port_is_taken` (a chosen port:
  the message; failed before), `test_a_taken_usual_port_moves_the_control_panel` (the fallback,
  the recorded address, and a second start opening it).
- **Status:** Fixed.

## Security findings

**No new exploitable vulnerability was confirmed.** Reviewed by reading, with the existing
security tests (`tests/security/`) passing:

- **Control panel** (`web.py`, `webauth.py`): Host check against DNS rebinding, session cookies
  (HttpOnly, SameSite=Strict), the `X-CRAFT-CONDUCTOR` header on every POST, sign-in throttling,
  the first-password and PIN rules, paired-phone roles and hidden routes, local-only routes,
  upload names and sizes, the console's one-line rule. Nothing found beyond the known gaps.
- **Passkeys** (`passkeys.py`, `webpush.verify`): single-use challenges bound to the address,
  origin check, user-verification flag, counter; ECDSA verification checks `r`/`s` ranges and the
  point at infinity; RSA builds and compares the whole expected encoding.
- **Friends' downloads** (`share.py`, `join.py`, `joinui.py`, `clientpack.py`): 144-bit invite
  secrets with expiry, certificate pinning, mods only from the mod sites' CDNs over HTTPS and
  hash-checked, file names checked; the friend's local page checks Host, a secret in every URL
  and the custom header.
- **Archives** (`safearchive.py`, `backup.py`, `world.py`, `transfer.py`, `modpack.py`): one name
  rule set, no links, bomb and disk-space limits, staged restores.
- **Self-update** (`selfupdate.py`, `rollback.py`): never a downgrade, size and checksum checks,
  the old version kept and put back by a guard process.
- **Commands** (`firewall.py`, `remoteinstall.py`, `process.py`): argument lists, strict host and
  user names (no leading `-`), base64-encoded PowerShell with escaped labels.
- **Web pages** (`app.js`, `rich.js`, `site/join/`): DOM built from text nodes, an allowlist
  sanitizer for mod descriptions, links and pictures limited to web addresses, strict CSP.
- **CI** (`.github/workflows/`): no `pull_request_target`; write tokens only on `main` or release
  runs; the release version reaches scripts through an environment variable.

Security-relevant items: BUG-004 (turning remote access off could be undone at the next start);
BUG-007 (wiped ban lists let banned players back). Hardening notes (not vulnerabilities): N7, N8,
N12, N13, N14 below. Gaps already recorded in `docs/security/THREAT_MODEL.md` (checksum-only
update verification, IP-literal and `.local` Host names, per-server authorization) aren't repeated.

## Notes not fixed (P4 / informational)

| ID | Note | Why it isn't fixed here |
|---|---|---|
| N1 | `POST /api/java/install` with a non-number `major` answers 500 "internal error" (API only; the page always sends a number) | Cosmetic |
| N2 | **Restore** accepts any file in the backups folder by name (a non-backup is then refused as damaged), unlike the other backup actions | Harmless |
| N3 | Deleting a server can race with its daemon starting a job in the same 2-second tick | Rare; the server is being deleted anyway |
| N4 | A crash restart is dropped if a job is started from the page in the second the crash is handled (the server stays stopped; Start works) | Rare |
| N5 | A legacy server kept directly in the home folder shares its update staging folder with the hub's upload staging, which every update empties | Legacy layout (0.1-0.3) only |
| N6 | An uploaded world `.zip` stays in the staging folder after setup until the 1-day cleanup | Disk space only |
| N7 | A server export includes `craft-conductor.toml` as it is (a Discord webhook or CurseForge key travels with it); the diagnostic report removes them | Needs a decision (Q5) |
| N8 | Windows Firewall rules added by **Let them through Windows Firewall** aren't removed when a server is deleted or its port changes | Removing needs another administrator prompt: a UX decision |
| N9 | A single-player world that's open in Minecraft isn't detected before it's copied to a server (the copy may be inconsistent) | Suspected; needs real Minecraft to verify (Q4) |
| N10 | When a mod is dropped because one of its dependencies is unavailable, its other (available) dependencies are still installed | Unneeded library mods only |
| N11 | Other job buttons (Backups, Updates: Apply update ...) can still show a "busy" error on a double-click, like BUG-011 | Same remedy if wanted; not changed without looking at each |
| N12 | CI and release use third-party actions by major tag (not commit SHA) and install PyInstaller/`build` by version range | Supply-chain hardening (threat model UPD-05) |
| N13 | Self-updates are verified against `SHA256SUMS.txt` from the same release | Known (threat model UPD-01) |
| N14 | The mod-conflict relay can be fed fake conflicts by someone with three or more addresses (shown as warnings only) | Design limit |
| N15 | The opt-in browser regression failed once in about nine runs (passed 5/5 when repeated) | Intermittent; not traced |
| N16 | Installing Java renames the unpacked folder once; on Windows an antivirus scan holding a file could make that fail (downloads retry, this doesn't) | Suspected; not reproduced |
| N17 | Every server's update check clears the HTTP cache shared with the page's mod browser | Efficiency only |
| N18 | A dependency missing on one site is replaced by "the same mod" on the other, matched by name/slug, which could match a different mod with the same name | Design trade-off |

## Unresolved questions (decisions for the owner)

- **Q1. First double-click on a new computer.** The standalone download opens the friend's page
  ("Join a friend's Minecraft server", with "Run my own server" further down) until a server
  exists (`cli._first_run_joining`), while the README and the manual's Getting started said the
  control panel opens. Decided: keep the behaviour; the README and the manual now say to press
  **Run my own server**. Done.
- **Q2. Busy control panel port (BUG-013).** Decided: fall back to a free port when the port wasn't
  chosen by hand. Done.
- **Q3. Servers after a Craft Conductor update.** An update stopped every server and they stayed
  stopped until Start was pressed. Decided: start again the ones that were running. Done: the
  running servers are noted in `hub.json` before the restart; the new copy (or the previous one, if
  the update guard puts it back) starts them once the guard has let go (at most 10 minutes later),
  and a note older than an hour starts nothing. Test:
  `tests/test_self_update_flow.py::test_servers_that_ran_start_again_after_an_update`.
- **Q4. Single-player world in use (N9).** Refuse to copy a world that's open in Minecraft, with a
  message? Needs testing with real Minecraft on each platform.
- **Q5. Secrets in exports (N7).** Leave the Discord webhook and CurseForge key out of exports
  (to be entered again on the new computer), or keep exports complete?

## Testing results

- **Final full run** (this branch at `667c6a3`, Windows, Python 3.12.6): `pytest -q`: **766 passed,
  31 skipped, 0 failed** (baseline 743 / 30 / 0: 23 new regression tests; the new opt-in browser
  test counts as skipped without `CRAFT_UI_NODE`).
- **Browser tests** (opt-in, Playwright with Edge): all 21 pass, including the new
  `test_ui_power_buttons.py`; see N15.
- **Not run:** the end-to-end check with real Minecraft, Java and mod sites (`e2e.yml`, CI on pull
  requests); Linux and macOS (CI); builds (CI only, by the project's rule).
- **CI:** not run yet: the branch hasn't been pushed (waiting for the owner's go-ahead).

## Coverage and limitations

Read in full or in depth: `web.py`, `daemon.py`, `manager.py`, `hub.py`, `backup.py`,
`process.py`, `properties.py`, `config.py` (editing), `players.py`, `modsets.py`, `planner.py`,
`mods/modrinth.py`, `mods/base.py`, `share.py`, `join.py`, `joinui.py` (request handling),
`http.py`, `selfupdate.py`, `rollback.py`, `safearchive.py`, `world.py`, `transfer.py`,
`webauth.py`, `passkeys.py`, `upnp.py` (discovery), `remoteinstall.py`, `java.py` (installing),
`schedule.py`, `setup.py`, `cli.py` (start, join), `desktop.py`, the workflows, `site/join/`,
`relay/worker.js`, and in `app.js` the element helper, sign-in, power buttons and New server.

Skimmed or not reviewed in depth: `curseforge.py`, `curseforgepack.py`, `handdownload.py`,
`launchers.py`, `friendextras.py`, `singleplayer.py`, `preview.py`, `trial.py`, `rehearsal.py`,
`lagfinder.py`, `filecheck.py`, `modcheck.py`, the loaders, `discordbot.py`, `push.py`,
`tunnel.py`, `tailscale.py`, `service.py`, `health.py`, `limits.py`, and most of `app.js`
(8,300 lines). Their existing tests pass.

Limits: only Windows was tested here; nothing ran against real Minecraft, routers, Discord or
the mod sites (the project's stand-ins only); the threat model's target architecture (per-server
authorization, signed updates, node agents) is a roadmap, not a defect list.
