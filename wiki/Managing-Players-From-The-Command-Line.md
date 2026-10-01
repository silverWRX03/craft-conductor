# Managing players from the command line

From the web UI's **Players** page, or the command line:

```sh
craft-conductor player list
craft-conductor player op Steve
craft-conductor player deop Steve
craft-conductor player kick Griefer --reason "cool it"
craft-conductor player ban Griefer --reason "griefing spawn"
craft-conductor player pardon Griefer
craft-conductor player ban-ip 203.0.113.9
craft-conductor player whitelist-on
craft-conductor player whitelist-add Alex
```

While the server runs, these are sent as the normal console commands (from the
command line this goes over RCON; the web UI doesn't need it). While it's stopped,
Craft Conductor edits `ops.json`, `banned-players.json`, `banned-ips.json`, `whitelist.json`
and `server.properties` directly, and the changes apply when the server starts. For
that it looks up player UUIDs from `usercache.json` or Mojang, or computes the
offline UUID when `online-mode=false`. Kicking, and IP-banning by player name, need
the server running.

---
[← Power users](Power-Users)
