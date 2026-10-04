# Updating Craft Conductor

Craft Conductor checks its GitHub releases once a day; set `[craft-conductor] update_check = false` to turn
this off. It offers **stable** releases only, unless you choose **Beta versions too** (Craft Conductor
settings → About & updates → Updates, `[craft-conductor] update_channel = "beta"`, or
`craft-conductor self-update --channel beta`). Betas are published as GitHub pre-releases, with versions
like `0.23.0b1`. When a new version is out:

- **Web UI:** a message in the middle of the screen shows the new version and a link to what's new, with **Update
  now** and **Later** buttons. **Later** hides it until the next version comes out;
  **Settings → About → Check for Craft Conductor updates** brings it back. **Update now**
  installs the release, warns players a minute ahead if anyone is online, stops the
  server cleanly, and restarts Craft Conductor (and the server) on the new version. Then you
  sign in again.
- **Command line:** `craft-conductor self-update --check` shows what's new, and `craft-conductor self-update`
  installs it after asking. If `craft-conductor run` is managing a server, it hands the update to
  the daemon, which restarts itself.
- Nothing is ever installed without you accepting it.
- pip and pipx installs get the release's wheel (`craft_conductor-<version>-py3-none-any.whl`),
  checked against `SHA256SUMS.txt`, and install it with the same Python that runs Craft Conductor
  (`pip install --no-index --no-deps <the wheel>`: pip fetches nothing else). A source checkout
  is updated with `git pull` instead.

The downloadable executables update themselves: Craft Conductor downloads the new file for your
system from the release, checks it against `SHA256SUMS.txt`, and swaps it in. If
Craft Conductor lives in a folder you can't write to, it tells you to download the new version
yourself.

**What's checked, every time.** An update is only ever to a newer version: an older one (or the
same one again) is refused, and a stable copy never goes back from a beta it's running. The
download goes to a private folder next to the program and is refused, leaving the running version
untouched, if `SHA256SUMS.txt` is missing, has no entry for it or two different ones, if it's bigger
than GitHub says, cut short, or doesn't match its checksum, or if it changed between the check
and the swap. A checksum from the same release page shows the download wasn't damaged or swapped
on the way; it can't prove the release itself is genuine (see the
[threat model](https://github.com/silverWRX03/craft-conductor/blob/main/docs/security/THREAT_MODEL.md),
section 5, for signed releases).

---
[← Power users](Power-Users)
