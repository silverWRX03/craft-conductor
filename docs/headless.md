# Craft Conductor on a computer without a screen

Run your servers on a spare PC, a home server or a Raspberry Pi 4/5 (64-bit OS) that sits
in a cupboard, and manage everything from a browser on your own computer. After the first
command, you never need to touch that machine again.

**You need:**

- a Linux computer on your home network, x86-64 or 64-bit ARM, with SSH turned on;
- its address, e.g. `192.168.1.50` (your router's list of connected devices shows it, or run
  `hostname -I` on it);
- a user on it that isn't root, e.g. `minecraft` (`sudo adduser minecraft`).

## 1. Install it

**The easy way:** in Craft Conductor on your own computer, go to **New server → Or on another computer →
Install on a Linux computer**, type its address and user name, and press **Connect with SSH**.
A terminal window opens; type that computer's password when SSH asks (the first time, answer
`yes` to trust it). Craft Conductor never sees the password. When it finishes, the window shows the
control panel's address and a one-time password.

**Or type the command yourself** (it's what that button runs):

The command connects to the Linux computer over SSH and runs Craft Conductor's installer there. The
installer:

- downloads the newest Craft Conductor for that computer;
- checks it against the release's checksums;
- sets it to start at boot (a systemd service);
- prints the address to open and a one-time password.

**Windows 10/11:** open **PowerShell** (Start menu → type "PowerShell") and run:

```powershell
ssh minecraft@192.168.1.50 "curl -fsSL https://raw.githubusercontent.com/silverWRX03/craft-conductor/main/packaging/install.sh | sh"
```

**macOS:** open **Terminal** (Applications → Utilities) and run:

```sh
ssh minecraft@192.168.1.50 "curl -fsSL https://raw.githubusercontent.com/silverWRX03/craft-conductor/main/packaging/install.sh | sh"
```

**Linux:** the same command, in a terminal.

Use your user name and the computer's address instead of `minecraft@192.168.1.50`. The first
time, SSH asks whether you trust the computer (type `yes`) and asks for that user's password.

The last lines look like this:

```
control panel: http://192.168.1.50:8765/  (open it on your own computer)
first sign-in password: Craft-Conductor-1a2b3c-4d5e6f-7a8b9c!   (one-time: you'll choose your own; ...)
```

## 2. Open the control panel

Open that address in a browser on your computer and sign in with the one-time password.
Craft Conductor asks you to choose your own. It must be strong (12+ characters, upper and lower case,
and a special character), because the panel is reachable from your network. From then on
everything happens in the browser: creating servers, mods, updates, backups and friends.

On your phone, open **Remote access & phones** in Craft Conductor settings to pair it with a QR code.

## Firewall

If the Linux computer runs a firewall, allow the control panel and Minecraft:

```sh
sudo ufw allow 8765/tcp      # the control panel (your network only; don't forward it on your router)
sudo ufw allow 25565/tcp     # Minecraft (one port per server)
sudo ufw allow 8798/tcp      # friends' downloads, if you use them
```

## Looking after it

| | |
|---|---|
| Status | `ssh minecraft@192.168.1.50 craft-conductor service status --panel` (or `~/.local/bin/craft-conductor ...`) |
| Logs | `ssh minecraft@192.168.1.50 journalctl --user -u craft-conductor -f` |
| Update Craft Conductor | from the control panel (Craft Conductor settings → Check for updates), or run the install command again |
| Remove the service | `ssh minecraft@192.168.1.50 craft-conductor service uninstall --panel` (your servers stay in `~/craft-conductor`) |
| Forgot the password | `ssh` in, delete `~/craft-conductor/.craft-conductor/web-auth.json`, then `systemctl --user restart craft-conductor` for a new one-time password |

The service runs as your user and keeps running after you log out ("lingering"). If Craft Conductor
can't turn that on by itself, it prints the `sudo loginctl enable-linger ...` command to run
once.

## Prefer Docker?

See [docker.md](docker.md).
