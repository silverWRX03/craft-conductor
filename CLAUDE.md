# mcsm: how we work on it

mcsm is a Minecraft server manager: Python 3.11+, standard library only at runtime, and a
vanilla-JS web UI under a strict Content-Security-Policy (`src/mcsm/webui/`).

## Every change

- **Keep the help current.** When a feature is added, changed or removed, update in the same
  change:
  - the user manual, `src/mcsm/webui/manual.md` (shown in the app under Help → User manual,
    and linked from the README);
  - the Help page (`HELP` in `src/mcsm/webui/app.js`) if it covers the feature;
  - the README;
  - any `docs/*.md` page that describes it.
  Use the button and page names as they appear in the app. A test
  (`test_the_manual_covers_every_page`) fails when a page in the app has no manual section.
- **Tests:** `pytest -q` must pass (it also syntax-checks the web page scripts).
- **Before merging:** review the change for **security** (anything reachable from the
  network, files and paths, secrets, input that ends up in commands), then for **efficiency**
  (polling, per-request work, caching). Fix what's found before the merge.
- Never commit secrets (API keys, tokens). Fake tokens in tests must not look like real ones.

## Bugs and the changelog

- Bugs and ideas are GitHub issues (the "Report a bug" / "Suggest an idea" forms). A fix
  refers to its issue in the pull request ("Fixes #12"), so merging closes it.
- Every change that users notice gets a line in `CHANGELOG.md` under the upcoming version
  ("not released yet"): Added / Changed / Fixed, in plain words, bugs described the way
  users saw them (with the issue number when there is one).

## Releasing

1. In `CHANGELOG.md`, turn "(not released yet)" into the release date; bump
   `src/mcsm/__init__.py`.
2. Merge the pull request with the expected head SHA, then run `release.yml` on `main` with
   the new version. The release notes link the changelog.
3. Comment on the issues fixed in it: "Fixed in <version>".

The in-app manual ships inside the release, so updating mcsm updates its help too.
