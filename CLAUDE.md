# craft-conductor: how we work on it

craft-conductor is a Minecraft server manager: Python 3.11+, standard library only at runtime, and a
vanilla-JS web UI under a strict Content-Security-Policy (`src/craft_conductor/webui/`).

## Naming

- Use `craft-conductor` for the command, distribution, configuration files, service names,
  invite scheme, and data directories. Python packages and identifiers use `craft_conductor`;
  environment variables use `CRAFT_CONDUCTOR_*`.
- This testing project uses fresh installs for the naming cleanup: do not restore retired
  command aliases, download names, or automatic migration of earlier installation paths.

## Every change

- **Keep the help current.** When a feature is added, changed or removed, update in the same
  change:
  - the user manual, `src/craft_conductor/webui/manual.md` (shown in the app under Help → User manual).
    It's also the **wiki**: `packaging/wiki.py` makes a page of each `## ` section, with the
    screenshots in `wiki/images` (see `IMAGES`), and `.github/workflows/wiki.yml` publishes it on
    every change to main. Don't edit the wiki on GitHub: edit `manual.md`, or the hand-written
    pages in `wiki/` (Home, the Power users pages). A new screen or a changed look needs its
    screenshot retaken;
  - the Help page (`HELP` in `src/craft_conductor/webui/app.js`) if it covers the feature;
  - the README, only for what a newcomer needs (the details live in the wiki);
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
   `src/craft_conductor/__init__.py`.
2. Merge the pull request with the expected head SHA, then run `release.yml` on `main` with
   the new version. The release notes link the changelog. The release also publishes the invite page
   (`site/join/`, GitHub Pages), after the downloads it links to exist.
3. Comment on the issues fixed in it: "Fixed in <version>".

The in-app manual ships inside the release, so updating craft-conductor updates its help too.
