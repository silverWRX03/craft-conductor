---
name: real-world-test
description: Carry out craft-conductor's manual real-world tests (testing/catalog.json and a run in testing/runs/) together with the user, recording only results that were actually performed.
argument-hint: "[run id, e.g. v0.28.0-win11 | new <version> | part N]"
disable-model-invocation: true
---

You're running craft-conductor's **real-world tests** with the user, on this Windows PC. Arguments: `$ARGUMENTS`

## First

1. Read `testing/README.md` and `docs/real-world-testing.md` (sections 2 and 3). The tracker is
   `python tools/real_world_tests.py` (standard library only; run it from the repository root).
2. Work out what to run from the arguments:
   - a **run id** (`v0.28.0-win11`): `python tools/real_world_tests.py report --run <id> --missing`
     lists what is left in it;
   - `new <version>`: the run doesn't exist yet. Read `CHANGELOG.md` for that version, propose the
     run id, `--kind` and the `--features`/`--fixes` test IDs (add missing tests with `add-test`),
     and create it with `new-run` only after the user agrees;
   - `part N`: Part N of `docs/real-world-testing.md`, results in `C:\cc\results\part-N.md`;
   - nothing: show `python tools/real_world_tests.py summary` and ask which run to work on.
3. Before touching anything, tell the user in a few lines: which build you'll test (and how you
   checked its `--version`), where its data will live, and which tests you can do alone versus the
   ones that need them. Wait for their yes.

## How to test

- **The build:** test the exe the user names: a release download, or the CI test build
  (artifact `test-build-craft-conductor-windows-x64.exe` of a pull request's `test.yml` run). Don't
  build it locally, and don't test the source checkout unless the user asks.
- **Isolation:** every test server lives under a disposable folder (`C:\cc\servers\<run id>`, or one
  the user names) with `CRAFT_CONDUCTOR_HOME` set to it. Use a control-panel port that isn't 8765 or
  8766 and isn't one of the user's own instances (ask which ports those use). Never touch the user's
  real servers or `%APPDATA%`.
- **Do it yourself when you can:** commands (`create`, `check`, `run --web`, `backup`, `restore`,
  `cmd` …), the control panel's API the way `packaging/e2e_test.py` drives it (its `Web` class),
  and reading the activity log `<home>\.craft-conductor\craft-conductor.log` and files.
- **Ask the user** for what needs hands: clicking in the panel, native file choosers, the game
  client, a phone, a second player, a VM power-off. Say exactly what to do, then wait until they say
  it's done and what they saw.
- **Ask first, every time**, before: accepting any agreement other than the Minecraft EULA on test
  servers, firewall or router changes, public access or the friends download, downloads beyond
  what the test needs, deleting anything, or touching a device or server that isn't disposable.

## Recording

- Record each result right after the test, only for tests that were really performed:
  `python tools/real_world_tests.py record --run <id> --id <N> --status pass|fail|blocked|na --tester "<who>" --notes "<what happened>"`.
  `--tester` is "Claude Code" when you did it alone, the user's choice of name when they did it.
  A test that wasn't done stays `not-tested`; never carry a pass over from an earlier version.
  Correcting a result needs `--replace`.
- The repository is public. Notes and `--evidence` stay sanitized: no IP addresses, passwords,
  tokens, user names, personal paths or raw logs. Keep raw evidence outside the repository
  (`C:\cc\results`).
- For a failure, write a bug report ready for GitHub's **Report a bug** form (what happened, the
  steps, what was expected) and check https://github.com/silverWRX03/craft-conductor/issues for an
  existing one. Don't file it or change any code until the user says so.

## At the end

1. Stop every test server and craft-conductor instance you started; check `netstat -ano` for
   anything you left listening.
2. `python tools/real_world_tests.py verify` and `report --run <id>`; summarize passed, failed,
   and not tested (and why).
3. Show `git diff --stat testing/`. Offer to commit the results on a branch and open a pull
   request; don't commit or push until the user says so.

If you do not understand something, ask the user and do not assume. If there are design choices,
ask the user; never assume.
