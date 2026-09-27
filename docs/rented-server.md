# Running mcsm on a rented server (a VPS)

A rented Linux server (a "VPS" from any hosting company) runs your Minecraft servers around
the clock, without keeping a computer on at home. mcsm installs on it the same way as on a
spare PC at home, from **New server → Install on a Linux computer…**, with one difference: a
rented server is on the internet, so its **control panel stays private** and you reach it
through SSH.

## What to rent

- **Linux** (Ubuntu 22.04/24.04 or Debian 12 are the easy choices), 64-bit (x86-64 or ARM64).
- **Memory:** about 2 GB for the system plus what the server gets: 4 GB for a small vanilla or
  lightly modded server, 8 GB or more for a modpack. mcsm's **Check my setup** tells you if
  it's too little.
- **CPU:** Minecraft leans on one fast core; a couple of dedicated (not "shared burst") cores
  are better than many slow ones.
- **Disk:** 20 GB or more (worlds and backups grow). Set **Backup copies** to keep backups
  somewhere else too.
- **SSH access** with a normal user. Many providers give you `root` first: log in and run
  `sudo adduser minecraft && sudo usermod -aG sudo minecraft`, then use `minecraft`.

## Installing

1. In mcsm on your own computer: **New server → Or on another computer → Install on a Linux
   computer…**
2. Type the server's address and the user name. mcsm ticks **It's a rented server on the
   internet** by itself for an internet address (you can change it).
3. **Connect with SSH**: a terminal opens; type the server's password when SSH asks. mcsm
   never sees it. The installer downloads mcsm from GitHub, checks it, sets it up as a service
   that starts at boot, keeps its control panel on the server itself (`127.0.0.1`), and shows
   a one-time password.

Or by hand, on the server: `curl -fsSL https://raw.githubusercontent.com/silverWRX03/mc-server-management/main/packaging/install.sh | MCSM_PANEL_LOCAL=1 sh`

## Opening its control panel

Its control panel isn't open to the internet: nobody can reach it except through SSH, which
needs the server's password or key.

- In mcsm: **🔐 Open an SSH tunnel** (keep that window open), then **Open its control panel**
  (`http://localhost:8775/`).
- By hand: `ssh -N -L 8775:127.0.0.1:8765 minecraft@<server>` and open `http://localhost:8775/`.

Sign in with the one-time password and choose your own.

## Letting players in

Open the Minecraft port (and the friends' download port, if you use invites) in the server's
firewall, and in the provider's firewall if it has one ("security group", "firewall rules"):

```sh
sudo ufw allow OpenSSH
sudo ufw allow 25565/tcp     # Minecraft (each server's port)
sudo ufw allow 8766/tcp      # friends' downloads (invites)
sudo ufw allow 19132/udp     # only for Bedrock players (Geyser)
sudo ufw enable
```

There's no router to forward: friends join at the server's address. For friends' invites, set
**mcsm settings → Sharing with friends → Your public address** to the server's address.

## Keeping it safe

- Use SSH keys rather than passwords if you can (`ssh-copy-id minecraft@<server>`), and keep
  the system updated (`sudo apt update && sudo apt upgrade`, or unattended upgrades).
- Don't open port 8765 (the control panel) in the firewall; use the SSH tunnel.
- mcsm updates itself when you say so (a message offers it); the service restarts on the new
  version.
