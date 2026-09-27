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

## Releasing

Merge the pull request with the expected head SHA, then run `release.yml` on `main` with the
new version (bump `src/mcsm/__init__.py` first). The in-app manual ships inside the release,
so updating mcsm updates its help too.
