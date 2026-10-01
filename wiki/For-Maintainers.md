# For maintainers

## Development

```sh
pip install -e ".[dev]"
pytest
```

The test suite runs the full install → upgrade → crash → rollback cycle against a fake
`java` and a fake server, so it needs no network and no Minecraft.

## Testing a build before a release

- **Test builds:** every CI run builds the Windows, macOS and Linux executables. Open
  the run under the repository's **Actions** tab (workflow **test**), scroll to
  **Artifacts**, and download `test-build-…` for your system. It's a zip containing the
  executable; you need to be signed in to GitHub.
- **CurseForge key in releases (optional):** like Prism Launcher, release builds can carry
  the project's own CurseForge API key so people don't need one. Add it as the repository
  secret `CURSEFORGE_API_KEY` (Settings → Secrets and variables → Actions); the release
  workflow writes it into the executables at build time
  ([`packaging/write_build_keys.py`](https://github.com/silverWRX03/craft-conductor/blob/main/packaging/write_build_keys.py)) and it never goes in the
  source. A key someone enters in Craft Conductor settings always takes priority. Use a key CurseForge
  issued for Craft Conductor as an app, since anything inside a program can be dug out of it.
- **Real end-to-end test:** the **e2e** workflow ([`packaging/e2e_test.py`](https://github.com/silverWRX03/craft-conductor/blob/main/packaging/e2e_test.py))
  uses a built executable against the real services:
  - it creates real Fabric, NeoForge, Forge, Paper and vanilla servers with real Modrinth
    mods, downloads Java, and boots Minecraft;
  - it upgrades the Fabric server to the newest version its mods support;
  - it drives the web UI, RCON and player commands, then stops cleanly.

  It runs on Linux, plus Fabric on Windows and macOS, on every pull request and every
  Monday. You can also start it by hand under **Actions → e2e → Run workflow**.

## Releasing

1. Set `__version__` in `src/craft_conductor/__init__.py`, e.g. `"0.2.0"`, and merge it to `main`.
2. Go to **Actions → release → Run workflow**, enter `0.2.0`, and run it. This creates
   the `v0.2.0` tag for you. Pushing the tag yourself works too:
   `git tag v0.2.0 && git push origin v0.2.0`.
3. The [release workflow](https://github.com/silverWRX03/craft-conductor/blob/main/.github/workflows/release.yml) tests the code and builds the
   Windows, macOS and Linux executables with [PyInstaller](https://pyinstaller.org). It
   smoke-tests each one on its own OS, then publishes a GitHub release with the
   executables, the friends' `craft-conductor-join-...` copies of them, the Python wheel, and
   `SHA256SUMS.txt`, then publishes the invite page (it links to those downloads).
4. Running copies of craft-conductor notice the release within a day and offer to update.

To build an executable yourself:

- **Linux:** `packaging/build_linux.sh`. It uses a portable Python from
  [python-build-standalone](https://github.com/astral-sh/python-build-standalone), so
  the result runs on glibc 2.17+ and not just on your own distribution.
  `packaging/check_linux_compat.sh dist/craft-conductor` proves it in a CentOS 7 container.
- **Windows or macOS:** `pip install pyinstaller && pyinstaller packaging/craft-conductor.spec`.
- Then run `python packaging/smoke_test.py dist/craft-conductor` (or `dist/craft-conductor.exe`).

The executables aren't code-signed yet, which is why Windows and macOS show warnings.
Windows signing through SignPath Foundation (free for open source) is ready in the release
workflow and switches on once the project is accepted: see [docs/code-signing.md](https://github.com/silverWRX03/craft-conductor/blob/main/docs/code-signing.md).
macOS needs an Apple Developer ID ($99/year) and notarization.

---
[← Power users](Power-Users)
