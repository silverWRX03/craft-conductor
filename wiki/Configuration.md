# Configuration (craft-conductor.toml)

Every server has an `craft-conductor.toml` in its folder. The control panel's Settings page changes the common parts for you; this page is for editing it by hand. Craft Conductor reads it again when you save in the control panel, or at the next start.

`craft-conductor init` writes a commented `craft-conductor.toml`. The important parts:

```toml
[server]
loader = "fabric"
memory = "6G"
find_lag = true                  # when it keeps lagging with players on, find out why by itself

[updates]
strategy = "latest-compatible"   # or "latest" (wait for the newest release) or "mods-only"
mod_channel = "release"          # accept "beta"/"alpha" mod builds too
check_interval = "6h"
warn_minutes = [10, 5, 1]
wait_for_empty = false
verify_boot = true
wait_for_all_mods = true         # a new Minecraft only once every mod supports it
remind_days = 30                 # then remind you monthly about the mods still behind
rehearse = false                 # try a new Minecraft on a copy of the server before updating by itself

[backups]
keep = 10
copy_to = "/media/usb/craft-conductor-backups"   # also copy every backup here (optional)

[schedule]                       # cron: minute hour day month weekday (local time); "" = off
restart = "0 4 * * *"            # every day at 4:00, after the in-game countdown
backup = "0 */6 * * *"           # every 6 hours
restart_when_empty = false       # skip a scheduled restart while players are online

[java]
version = "auto"                 # or force a major version, e.g. 21
auto_install = true              # download Temurin when the needed version is missing

[downloads]
manual_dir = "manual-downloads"  # drop blocked CurseForge files here

[notify]
discord_webhook = "https://discord.com/api/webhooks/..."

[craft-conductor]
update_check = true              # look for new Craft Conductor versions (installing always asks first)
update_channel = "stable"        # or "beta": early versions too

[web]
host = "127.0.0.1"               # this computer only (the default); "0.0.0.0" opens it to your network

[client]                         # the friends' download (the Friends page sets these)
link_days = 7                    # how long a new invite link works: 1, 7, 30, or 0 = until replaced
expires = 0                      # when the current link stops (Unix time; written for you)

[[mods]]
source = "modrinth"
id = "lithium"
required = true
```

### Strategies

- **`latest-compatible`** (default): move to the newest release that everything supports,
  even if it isn't the very latest. For example, you might go 1.21.1 → 1.21.3 while
  a mod still lacks 1.21.4.
- **`latest`**: only ever jump straight to the newest release, once everything supports it.
- **`mods-only`**: pin the Minecraft version and just keep mods and the loader updated.

## Strategies

- **`latest-compatible`** (default): move to the newest release that everything supports,
  even if it isn't the very latest. For example, you might go 1.21.1 → 1.21.3 while
  a mod still lacks 1.21.4.
- **`latest`**: only ever jump straight to the newest release, once everything supports it.
- **`mods-only`**: pin the Minecraft version and just keep mods and the loader updated.

---
[← Power users](Power-Users)
