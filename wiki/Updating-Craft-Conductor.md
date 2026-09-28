# Updating Craft Conductor

Craft Conductor checks its GitHub releases once a day; set `[mcsm] update_check = false` to turn
this off. When a new version is out:

- **Web UI:** a message in the middle of the screen shows the new version and a link to what's new, with **Update
  now** and **Later** buttons. **Later** hides it until the next version comes out;
  **Settings → About → Check for Craft Conductor updates** brings it back. **Update now**
  installs the release, warns players a minute ahead if anyone is online, stops the
  server cleanly, and restarts Craft Conductor (and the server) on the new version. Then you
  sign in again.
- **Command line:** `mcsm self-update --check` shows what's new, and `mcsm self-update`
  installs it after asking. If `mcsm run` is managing a server, it hands the update to
  the daemon, which restarts itself.
- Nothing is ever installed without you accepting it.
- It installs with the same Python that runs Craft Conductor (`pip install --upgrade
  git+https://github.com/silverWRX03/craft-conductor@<tag>`), so pip and pipx
  installs both work. A source checkout is updated with `git pull` instead.

The downloadable executables update themselves: Craft Conductor downloads the new file for your
system from the release, checks it against `SHA256SUMS.txt`, and swaps it in. If
Craft Conductor lives in a folder you can't write to, it tells you to download the new version
yourself.

---
[← Power users](Power-Users)
