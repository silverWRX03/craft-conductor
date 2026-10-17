# Real-world testing (human + Claude Code)

This is the authoritative record of **manual real-hardware tests**. It complements, not replaces, `pytest`, `test.yml`, packaged smoke tests and real Minecraft CI (`e2e.yml`). Historical results are never silently reused as passes for a newer Craft Conductor version.

## Source files

- `catalog.json` — one definition per test, with stable numeric IDs.
- `runs/*.json` — immutable-by-default per-release / per-environment testing runs. Record results explicitly; a new release starts with **no passes**.
- `runs/legacy-spreadsheet-0.27.0.json` — import of the provided Excel snapshot; preserved separately as historical evidence. Its notes sometimes mention earlier runs, but the workbook does not constitute individually structured historic run records.
- `imports/` — additional handoff/context imported from the workbook. Review before making public.

## Claude Code / VS Code commands

Run these from the repository root in a VS Code terminal (Windows PowerShell is supported):

```powershell
python tools/real_world_tests.py summary
python tools/real_world_tests.py list --search Geyser
python tools/real_world_tests.py new-run --run v0.28.1-win11 --version 0.28.1 --kind patch --os "Windows 11" --fixes 877
python tools/real_world_tests.py list --run v0.28.1-win11
python tools/real_world_tests.py record --run v0.28.1-win11 --id 877 --status pass --tester "local manual tester" --notes "Started real Forge 26.x and joined client"
python tools/real_world_tests.py report --run v0.28.1-win11 --missing
python tools/real_world_tests.py verify
```

For a release with no feature or fix changes, use `--confirm-no-changes` explicitly. Test result status values: `pass`, `fail`, `blocked`, `na`, `not-tested`. For a correction to an existing result pass `--replace` (the previous result is retained in `supersedes`); otherwise edits refuse to overwrite recorded results. `--evidence` should contain an issue link or **sanitized** artifact reference; never paste secret logs into this public repository.

## New tests required on changes

For each user-visible feature: add at least one applicable real-world acceptance case to the catalog and include its ID with `--features N` on that release run. For each bug fix: add or identify a reproducing regression test and include its ID with `--fixes N`.

```powershell
python tools/real_world_tests.py add-test --section "Feature: Bedrock" --step "On a Paper server, enable Geyser and connect a Bedrock client" --tag minecraft-version
python tools/real_world_tests.py new-run --run v0.29.0-win11 --version 0.29.0 --kind feature --os "Windows 11" --features 882 --fixes 877
```

A `--kind minecraft` run includes the 20 existing release-gate tests plus tests tagged `minecraft-version`. A `--kind high-risk` run additionally includes `security`-tagged cases. A `--kind full` run selects all tests. The default `patch`/`feature` run selects the 20 existing release-gate cases plus `--features`, `--fixes` and `--extra` cases. Select other tests by risk, not only by category. No test automatically passes based on a prior version.

## Release safety

The initial integration reports readiness only. It does **not** block `release.yml`, publish a new release, or merge anything automatically. A later PR can add mandatory human approval once this workflow is validated on live releases.

To produce the **public** Pages data (without any notes, tester names, hardware, addresses or evidence):

```powershell
python tools/real_world_tests.py publish --output site/testing/data
```

The Pages workflow builds that data directly into the deployment artifact. The dashboard is read-only; Claude Code records and commits test results through the CLI. A native GitHub Project board is optional and is not required to use the tracker.

## Safe workflows

1. Run tests against an isolated Craft Conductor installation. Claude must never run a destructive real-world test without the owner identifying the disposable target and approving the action.
2. Ask for human participation for actions requiring physical devices, admin access, firewalls, routers, accounts or live game clients. Never fabricate Pass results.
3. Run the CLI and inspect `git diff`; commit test changes on a branch and submit them for review.
4. Avoid inserting private IPs, passwords, tokens, physical-machine usernames, personal paths or raw log files into the public repo.
5. Re-run fixed regressions. Closing an issue does not automatically mark any manual test as Pass.
