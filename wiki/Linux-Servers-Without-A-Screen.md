# Linux servers without a screen

The easiest way: one command from your own computer installs Craft Conductor on the Linux computer and
starts it at boot. See **[docs/headless.md](https://github.com/silverWRX03/craft-conductor/blob/main/docs/headless.md)** (Windows, macOS and Linux
steps). For containers, see **[docs/docker.md](https://github.com/silverWRX03/craft-conductor/blob/main/docs/docker.md)**. The details below are for
doing it by hand.

- **Reaching the control panel from your own PC.** The setup wizard asks whether to
  allow other devices on your network; on a machine with no desktop the suggested
  answer is yes. Craft Conductor then prints the address to open, such as
  `http://192.168.1.50:8765/`. If you'd rather keep it private to the server, answer
  no and use an SSH tunnel: `ssh -L 8765:localhost:8765 you@server`, then open
  <http://localhost:8765> on your PC. Craft Conductor prints this command too.
- **Keeping it running after you log out, and after reboots:**

  ```sh
  craft-conductor service install      # sets up a systemd service for this server and starts it
  craft-conductor service status
  journalctl --user -u craft-conductor-<folder> -f    # the server console (`craft-conductor service install` prints the exact command)
  craft-conductor service uninstall
  ```

  As a normal user this creates a user service and enables "lingering" so it runs
  without anyone logged in (if that needs admin rights, Craft Conductor prints the
  `sudo loginctl enable-linger` command). As root it creates a system service. A good
  setup is a dedicated `minecraft` user: `sudo -u minecraft craft-conductor service install`.
  [`examples/craft_conductor.service`](https://github.com/silverWRX03/craft-conductor/blob/main/examples/craft_conductor.service) shows a hand-written unit if you prefer.
- **Firewall:** open the Minecraft port for players (`sudo ufw allow 25565/tcp`, or
  `sudo firewall-cmd --add-port=25565/tcp --permanent && sudo firewall-cmd --reload`),
  and port 8765 only if you use the control panel from other devices.

On a rented server (a VPS), see the [rented server guide](https://github.com/silverWRX03/craft-conductor/blob/main/docs/rented-server.md).

---
[← Power users](Power-Users)
