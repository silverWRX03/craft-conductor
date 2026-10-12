# Updating Craft Conductor

Craft Conductor checks its GitHub releases once a day; set `[craft-conductor] update_check = false` to turn
this off. It offers **stable** releases only, unless you choose **Beta versions too** (Craft Conductor
settings → About & updates → Updates, `[craft-conductor] update_channel = "beta"`, or
`craft-conductor self-update --channel beta`). Betas are published as GitHub pre-releases, with versions
like `0.23.0b1`. When a new version is out:

- **Web UI:** a message in the middle of the screen shows the version you have, the new one and a link
  to what's new, with **Update now** and **Later** buttons. **Update now** closes it and shows an
  **Updating Craft Conductor…** screen with the step it's on; the release is installed, players are
  warned a minute ahead if anyone is online, the servers stop cleanly, and Craft Conductor restarts on
  the new version; the servers that were running start again once the new version has proven itself
  (if the update is rolled back, they start on the previous version instead). The same browser tab
  reconnects and reloads once the new version answers (no new tab),
  and then you sign in again. It's started once, however often the button is pressed. If it fails, the
  screen says why and offers **Try again** (or **Retry connection**, **View update log** and how to
  restart by hand when the old version couldn't be put back).
  **Later** stops the message appearing by itself until Craft Conductor is restarted (then it's offered
  again if the update is still there). It doesn't hide the update: a red dot stays on **Craft Conductor
  settings → About & updates → Check for Craft Conductor updates**, and that button offers the update
  again straight away. The dots go once Craft Conductor is updated or a check finds nothing newer.
- **Other browsers and phones:** only the browser that pressed **Update now** reloads by itself. Any other
  open page says the update is under way and, once the new version is running, asks **Launch the new
  version** (it reloads only when you press it). Phones with notifications on hear when an update is
  available, when it was installed and when it didn't work; updating is only done in the control panel.
- **If it doesn't work, the old version comes back.** The version you have is kept aside before anything is
  replaced (`update-backup/` in the `.craft-conductor` folder). After installing, the new version is started
  once (`--version`) before Craft Conductor restarts; if that fails the old one is put back at once and
  keeps running. After the restart, a watcher process run from the *old* version gives the new one 3
  minutes to confirm it's up and 15 seconds to stay up; otherwise it stops it, puts the old version back
  (the executable, or the installed package with its metadata), starts it again and records the outcome,
  which the page and phones then report. The checks before installing (checksum, size, newer version
  only) are unchanged.
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
