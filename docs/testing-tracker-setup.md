# Real-world testing tracker — setup branch

The tracking implementation was generated and validated outside GitHub against the user's Excel workbook. This branch is reserved for the import and review; it must not be merged or deployed before the imported notes have been checked for private information.

## Intended contents to add on this branch

- `testing/catalog.json`: 881 stable-ID test definitions across 89 sections
- `testing/runs/legacy-spreadsheet-0.27.0.json`: historical Excel snapshot with 405 Pass, 14 Fail, 35 Blocked, 10 N/A and 417 Not Tested
- `testing/imports/`: old handoff and bug-prompt context
- `tools/real_world_tests.py`: standard-library Claude Code/VS Code CLI for new-run, record, add-test, list, report, validate and public exports
- `site/testing/`: read-only public dashboard; raw tester names, notes and evidence excluded from export
- GitHub Actions validation and updates to `AGENTS.md`, `CLAUDE.md`, and the existing Pages workflow

The generated ZIP and installer are supplied in the related ChatGPT conversation and are **not yet committed to this branch**. Open the ZIP's `START_HERE.md` and run `INSTALL_TEST_TRACKER.ps1` locally in the repository checkout. Then validate, review/redact notes and commit the files on this branch.

## Rules

- Never overwrite a historical run or carry its Pass results into a new version.
- Normal release = 20 current Gate cases + each new-feature and fixed-bug regression case; Minecraft version change = broadened loader, Java, mod, worlds and Geyser scope.
- Preserve all automated `pytest`, packaged smoke and E2E GitHub Actions.
- A code fix does not automatically become a real-world Pass.
- No automated merge or release publishing, until reviewed and separately authorized.
- This repository is public: source JSON containing evidence also becomes public when pushed, even when the dashboard conceals it.

The native GitHub Projects board is optional. Creating a project requires GitHub Projects API permissions that were not available in this connection.
