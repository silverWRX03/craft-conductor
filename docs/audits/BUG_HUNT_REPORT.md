# Bug hunt report (October 2026)

**Status:** in progress (this file is kept current while the investigation runs).
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
| BUG-004 | Settings in `hub.json` can be silently undone by a concurrent save (UPnP sync) | P3 | High confidence | Open |
| BUG-005 | Backups of a running server wait a fixed 5 s for the world to be saved | P2 | High confidence | Fixed |
| BUG-006 | Ticking "required" on a mod drops its early-builds channel and datapack setting | P2 | Confirmed | Fixed |

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
- **Related, not fixed here:** `craft-conductor.toml` is also read in the locale encoding. Values the
  app writes are ASCII-escaped, so only hand-edited non-ASCII text is affected (recorded as a
  follow-up, see "Remaining risks").
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

- **Severity / confidence:** P3 / High confidence.
- **Component:** `hub.py` (`_hub_file`, `_save_hub_file` and their callers).
- **Description:** `hub.json` (control panel host and allowed hosts, CurseForge key, Discord bot,
  friends' download settings, router forwarding, update channel, hidden servers) is changed by
  read-modify-write with no lock. Router forwarding (`upnp_sync`, every 30 minutes in the
  background when it's on) reads the file, talks to the router for several seconds, then writes
  its old copy back.
- **Impact:** a setting saved during that window is silently reverted, e.g. turning off access
  from other devices: the running panel follows the new setting, but the old one comes back the
  next time Craft Conductor starts.
- **Status:** Open.

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

## Security findings

Reviewed so far: the control panel's request handling (Host check, sign-in, sessions, the
`X-CRAFT-CONDUCTOR` header, paired-phone permissions, local-only routes, uploads), the friends'
download server (`share.py`), the friend side (`join.py`), the HTTP client and certificate
pinning, archive extraction (`safearchive.py`, `backup.py`), and the self-updater. No new
exploitable vulnerability has been confirmed. BUG-004 has a security side (an "off" for remote
access that doesn't last). Known gaps already recorded in `docs/security/THREAT_MODEL.md`
(checksum-only update verification, IP-literal and `.local` Host names) are not repeated as findings.

## Unresolved questions

None yet.

## Remaining risks and limitations

- Only Windows was tested locally; Linux and macOS rely on CI.
- Behaviour that needs real Minecraft, real routers or real mod sites was reviewed by reading and
  tested with the project's stand-ins only.
- `craft-conductor.toml` is read and written in the locale encoding (see BUG-001, related).
