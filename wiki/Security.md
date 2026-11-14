# Security

## The control panel

**Signing in.** The first password is `PASSWORD`, and the panel asks you to change
it right after you sign in. You can pick a password or a 4–8 digit PIN; there's always
one. A PIN only works in a browser on the server's own computer. Change it later
under Settings → Sign-in. Forgot it? Run `craft-conductor web-password --reset` on the server
to go back to `PASSWORD`, or press **Reset it to PASSWORD** in a browser there and type the code
it writes to `craft-conductor-reset-code.txt` in Craft Conductor's folder (it works once, for 10
minutes: a request that only looks as if it came from this computer, through a tunnel that adds
nothing to say so, can't open that file). To fix the password in the config instead, set
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
  computer privately and encrypted, and shows its address in the pairing dialog. For a few hours
  on the internet, there's Cloudflare's free quick tunnel (anyone with its random address reaches the
  sign-in page, and Cloudflare can see what passes through). Don't forward the control panel's port
  (8765) on your router, and never point a playit.gg tunnel at it.
- **A tunnel is never "this computer".** A tunnel's program runs here and passes requests on, so
  they come from this computer's own address. Tailscale and Cloudflare each get a way in of their own
  (a port on 127.0.0.1 only their program is pointed at): requests through it can't use a PIN, reset
  the password or do what only works at the computer, and only that tunnel's own address is answered
  there. On the usual port, Craft Conductor also checks which program opened the connection: a tunnel's
  (playit.gg, cloudflared, Tailscale, ngrok, SSH…), another account's, or one it can't tell doesn't
  count as this computer either. Wrong passwords are counted for each visitor, from what that tunnel
  says about them (Tailscale's address for your device, Cloudflare's for the visitor), so one person
  can't lock out everyone else, or you at the computer.
- **cloudflared is checked before it runs:** downloaded only when you press the button, from
  Cloudflare's GitHub release, with GitHub's checksum and the one in Cloudflare's release notes, and
  on Windows Cloudflare's signature; checked again each time before it starts, with an argument list
  (no shell) and without Craft Conductor's secrets or `TUNNEL_…` settings. It runs as its own program
  while the tunnel is open, and stops after 4 hours, on **Stop now**, or when Craft Conductor closes.
- **Safety rules you may switch off** (Craft Conductor settings → Advanced, or `[web] accept_risks`
  in craft-conductor.toml): a PIN or weaker password from other devices (never `PASSWORD`),
  Tailscale Funnel, the reset without its code, no limit on wrong passwords, and choosing the
  forwarded port yourself. Switching one off only works at the server's computer and asks first;
  while one is off, every page says so.

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
single-use. It stops working by itself after the time you pick on the Friends page (3 days unless
you change it, a week at most), and **Stop these links** or **New links** ends it at once.
After that every request with it is refused, and when no server has a working link the friends'
port closes (and Router takes it back from your router within a minute). A link only ever gives the setup for players' computers and a way to **ask to be let
in**: it never reaches the control panel, and with the whitelist on, you decide who plays.

## Friends outside your home

Each server's Friends page picks how friends outside your home join: **playit.gg** (chosen at
first: nothing opened on your router), **Open a port on my router**, or **Only friends at home**.

**The whitelist is on whenever a server can be reached from the internet** (playit.gg or an open
port chosen, Router on, a public address set, a playit.gg address, or Check my setup reached it).
Turning it off is allowed, but Craft Conductor asks every time, and the server refuses it until
the warning has been seen.

**Port forwarding** gets a port Craft Conductor picks: not 25565 (the port bots try first), nobody
else's, between 30000 and 39999. That doesn't hide the server from a scan of every port; the
whitelist is what keeps strangers out.

**playit.gg's program** is downloaded only when you press the button, only from playit.gg's own
GitHub release, and opened only after two checks: the SHA-256 GitHub lists for the file, and a
valid Windows signature from Developed Methods LLC (playit.gg's company). A file that fails either is
deleted. It runs as its own program; Craft Conductor never sees your playit.gg account or its key.
playit.gg carries only Minecraft's game traffic to the server's port: the control panel is never
reachable through it.

## The router (UPnP)

**Open the ports on my router by itself** is off until you switch it on, and asks first: it makes
your server reachable from the whole internet, and the page says so for as long as it's on. Only
the Minecraft port (and the Bedrock port, with Geyser) of each server set to **Open a port on my
router**, and the friends' port while a link works, are forwarded (never a server set to **Only
friends at home** or playit.gg), never the control panel's port or a server's RCON port, and they're taken back
when you switch it off or quit.

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
