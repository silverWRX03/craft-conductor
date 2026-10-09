# Contributing to Craft Conductor

Thanks for helping! Bug reports, ideas, translations and code are all welcome.

- **A bug, or an idea:** use the [issue forms](https://github.com/silverWRX03/craft-conductor/issues/new/choose)
  ("Report a bug" / "Suggest an idea").
- **A security problem:** not in an issue, please: see [SECURITY.md](SECURITY.md).

## What Craft Conductor is (and stays)

- **Free and open source** (GPL-3.0-or-later), with no paid dependencies, **no telemetry**, and no
  accounts. It only talks to the services it needs (Mojang, Java's and the loaders' download
  sites, the mod sites, GitHub for its own updates, and its shared list of mod conflicts) and
  sends nothing about the person using it. Anything more, they turn on themselves.
- **Safe by default, easy through its defaults.** Anything risky (remote access, opening ports
  with UPnP) is opt-in, with a plain-language warning before it's on.
- **Python 3.11+ and the standard library only** at runtime: no new runtime dependencies. The
  web page is plain JavaScript under a strict Content-Security-Policy
  (`src/craft_conductor/webui/`): no inline scripts or styles, and scripts and styles only from
  the app itself.
- Written for people who have never run a server: plain words, no jargon, in the app and
  the docs.

## Getting set up

```sh
pip install -e ".[dev]"
pytest -q
```

The tests run the whole install → upgrade → crash → rollback cycle against a fake `java` and a
fake server, so they need no network and no Minecraft. They also syntax-check the page's
scripts (that needs `node`). The end-to-end check (`packaging/e2e_test.py`, the **e2e**
workflow) uses the real services; it runs on pull requests.

## Every change

1. **Tests.** A fix comes with a test that fails without it. `pytest -q` must pass. Fake
   tokens and keys in tests must not look like real ones.
2. **Keep the help current**, in the same change:
   - the user manual, `src/craft_conductor/webui/manual.md` (Help → User manual in the app, and
     the [wiki](https://github.com/silverWRX03/craft-conductor/wiki): edit the manual or `wiki/`,
     never the wiki itself). A new screen or a changed look needs its screenshot retaken: run
     `tests/test_screenshots.py` (its docstring says how), and look at the pictures before committing;
   - the Help page (`HELP` in `src/craft_conductor/webui/app.js`) if it covers the feature;
   - the README, only for what a newcomer needs;
   - any `docs/*.md` page that describes it.

   Use the button and page names as they appear in the app.
3. **Translations.** The page's words are translated in `src/craft_conductor/webui/i18n/<language>.json`,
   keyed by the English text. New or changed words need entries in every language there
   (`tests/test_i18n.py` checks they're complete).
4. **The changelog.** Anything people will notice gets a line in [CHANGELOG.md](CHANGELOG.md)
   under the version that's "not released yet": Added / Changed / Fixed, in plain words, with
   bugs described the way people saw them (and the issue number when there is one).
5. **Names.** `craft-conductor` for the command, files, services and folders; `craft_conductor`
   in Python; `CRAFT_CONDUCTOR_*` for environment variables.

## Before it's merged

Every pull request is reviewed for:

- **Security:** anything reachable from the network, files and paths (names from mod sites,
  friends or uploads never decide where something is written), secrets (never logged, never
  in reports, never passed to programs Craft Conductor starts), and input that ends up in
  commands (argument lists, never a shell).
- **Efficiency:** polling, work done on every request, and caching.

The pull request template has the checklist. A fix refers to its issue ("Fixes #12") so
merging closes it. CI runs the tests on Linux, Windows and macOS, builds the downloads, and
checks the code (CodeQL) and the build tools' dependencies (pip-audit).

**Never commit secrets** (API keys, tokens, passwords). Release builds get the CurseForge key
from a repository secret at build time ([packaging/write_build_keys.py](packaging/write_build_keys.py)).

## Releases

Maintainers release from `main` with the **release** workflow; the steps are in
[CLAUDE.md](CLAUDE.md) and on the wiki's
[For maintainers](https://github.com/silverWRX03/craft-conductor/wiki/For-Maintainers) page.

## License

Craft Conductor is GPL-3.0-or-later ([LICENSE](LICENSE)). What you contribute is under the same
license. Anything new it uses or downloads goes in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
