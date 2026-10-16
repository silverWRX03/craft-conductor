# Security

## The control panel

**Signing in.** The first password is `PASSWORD`, and the panel asks you to change
it right after you sign in. You can pick a password or a 4–8 digit PIN; there's always
one. A PIN only works in a browser on the server's own computer. Change it later
under Settings → Sign-in. Forgot it? Run `craft-conductor web-password --reset` on the server
to go back to `PASSWORD`. To fix the password in the config instead, set
`[web] password` in craft-conductor.toml: Craft Conductor replaces what you typed with its hash the
first time it reads the file (to change it, type a new one there). Passwords and PINs are stored
only as salted hashes.

**Security.** By default it only listens on `127.0.0.1`, including on a computer without a
screen (reached through an SSH tunnel) and as a boot service (`craft-conductor service install
--panel`; `--network` opens it to your home network). In Docker the example publishes it on
`127.0.0.1` too. Every request needs a
login (rate limited; sessions are HttpOnly, SameSite=Strict cookies), and
changes need a CSRF header. Requests must address this machine by IP, `localhost`,
a `.local` name, or its host name, which blocks DNS-rebinding attacks. If you use a
reverse proxy with its own domain, add that domain to `[web] allowed_hosts`. The page runs under a strict Content Security Policy
with no third-party scripts. The console gives full operator control of your
server, so to reach it from elsewhere, put it behind an HTTPS reverse proxy (Caddy,
nginx) or a VPN such as Tailscale rather than exposing the port directly.

## Remote access and phones

By default only the computer Craft Conductor runs on can open the control panel. **Craft Conductor settings →
Remote access & phones** (also on the new-server screen) lets other devices in, with these
safeguards:

- **A strong password is required:** 12+ characters, with uppercase, lowercase and a special
  character. PINs only ever work on the server's own computer, and the
  password can't be weakened while remote access is on.
- **Phones are paired by scanning a QR code** (or typing its 12-character code). The code
  works once (even if two phones try it at the same moment), for five minutes, and only 5 tries
  are allowed per 5 minutes. **Cancel this code** stops it sooner, and so do turning off remote
  access, removing every phone and changing the password. Each phone gets
  its own key (only a hash of it is stored) and signs in by itself afterwards.
- **People you invite get only what you give them, per server.** Each person has their own
  username and strong password (the invite link works once, for a day), and for each server a
  role (Viewer, Moderator, Operator, Manager) or permissions ticked one by one. Risky ones
  (console commands, OP, mods, Java and launch settings, applying updates, configuration
  files, restoring or exporting, deleting the server) are never part of a role. Servers they
  weren't given look as if they didn't exist. Craft Conductor checks every request on the
  computer itself; hiding buttons on the page is only for comfort.
- **Some things are only ever yours:** inviting people and changing what they may do,
  updating Craft Conductor, remote access, the router and the firewall, new and imported
  servers, the setup check, and folders on this computer.
- **A phone belongs to a person** and can do exactly what they can, never more. Phones paired
  before this (the old helper and viewer phones) no longer sign in.
- **You stay in charge of everyone:** each person and phone is listed; editing what someone
  may do, **Remove** and **New sign-in link** count at once, everywhere. Resetting your own
  password on the server's computer signs everyone out.
- **Attempts are limited and actions are logged:** repeated wrong passwords or pairing codes
  are rate-limited, and what a person (or their phone) does appears in the server's activity feed, with their name.
- **HTTPS** is available with a certificate you provide (for example `tailscale cert`).
- **Away from home, use a private network app, not your router:** Craft Conductor recommends
  [Tailscale](https://tailscale.com) (free for personal use), which connects your phone and
  computer privately and encrypted, and shows its address in the pairing dialog. Don't
  forward the control panel's port (8765) on your router.

The panel can be added to your phone's home screen, where it opens like an app.

On a computer without a screen, or in Docker, Craft Conductor starts with a random **one-time
password** printed on its console. Signing in with it can only choose your own strong
password (or set `CRAFT_CONDUCTOR_INITIAL_PASSWORD`). See [docs/headless.md](https://github.com/silverWRX03/craft-conductor/blob/main/docs/headless.md) and
[docs/docker.md](https://github.com/silverWRX03/craft-conductor/blob/main/docs/docker.md).

## Friends' downloads

**Secure by design.** Friends' Craft Conductor talks to your computer only over HTTPS, with a
certificate your Craft Conductor makes for itself. Its fingerprint is part of the invite, and your
friends' Craft Conductor refuses anything else, so nobody in between (on café Wi-Fi, say) can read
or swap the mods. The program itself always comes from GitHub, never from your server. The invite
page lives on GitHub Pages (a real certificate, so no browser warning), and the invite
itself is after the `#` in the link, which browsers never send anywhere. Power users can
still use the raw invite code with `craft-conductor join <code>`.

**Links that stop.** An invite link is made to be shared (in a Discord channel, say), so it isn't
single-use. It stops working by itself after the time you pick on the Friends page (7 days unless
you change it; or until you replace it), and **Stop these links** or **New links** ends it at once.
After that every request with it is refused, and when no server has a working link the friends'
port closes. A link only ever gives the setup for players' computers and a way to **ask to be let
in**: it never reaches the control panel, and with the whitelist on, you decide who plays.

## The router (UPnP)

**Open the ports on my router by itself** is off until you switch it on, and asks first: it makes
your server reachable from the whole internet, and the page says so for as long as it's on. Only
each server's Minecraft port and the friends' port are forwarded, never the control panel's port
or a server's RCON port, and they're taken back when you switch it off or quit.

## Secrets on your computer

Passwords, PINs and phones' keys are kept only as salted hashes. What Craft Conductor has to hand on
can't be hashed: the CurseForge key, the Discord bot token and webhook, the push-notification and
HTTPS keys, friends' invite secrets and an RCON password. So every file that holds one is readable
by your account only: `0600` on Linux and macOS, and on Windows an access list of your account,
SYSTEM and the Administrators, with nothing inherited from the folder (which matters when Craft
Conductor's folder is on another drive). That's Craft Conductor's own settings (`.craft-conductor/`),
a server's `craft-conductor.toml` and `server.properties` once they hold one, the notes kept with
backups, and server exports.

**Backups** hold passwords, keys, IP bans and logs only if you choose so on the Backups page, and
then locked to this computer and account: encrypted (BLAKE2b in counter mode, with an HMAC-SHA256
check) with a key made once per installation, `.craft-conductor/backup.key`, which Windows seals for
your account (DPAPI) and Linux and macOS keep readable by you only. **Exports** carry passwords, keys
and IP addresses only when you tick them, locked with a random password made for that export
(WinZip AES-256, which 7-Zip opens too) and shown once; nothing else in the export is encrypted.

## Updates

Craft Conductor only updates to a newer version, on the channel you chose (stable unless you pick
beta), and only with a download that matches the checksum published with the release; anything
else leaves the running version as it is. See [Updating Craft Conductor](Updating-Craft-Conductor).

## Found a security problem?

Please report it privately, not in an issue: see
[SECURITY.md](https://github.com/silverWRX03/craft-conductor/blob/main/SECURITY.md).

---
[← Power users](Power-Users)
