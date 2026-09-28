# How an upgrade works

`mcsm` runs your modded Minecraft server and **keeps it on the newest Minecraft
release once your mods support it**. It watches for new releases and checks
whether your loader and every mod you depend on (plus their dependencies) have
builds for them. When they do, it counts down in-game, backs up, swaps
everything over, boots the new version to make sure it works, and
**rolls back automatically** if it doesn't.

It's one tool for both jobs: running the server (like autoMCS) and doing the
fragile upgrade pipeline you'd otherwise do by hand.

```
$ mcsm check
installed: Minecraft 1.21.4 / fabric 0.16.10 - latest release is 1.21.5

Minecraft 1.21.5 is blocked by:
  x Create Fabric: Create Fabric has no fabric build for 1.21.5

ready to update to Minecraft 1.21.4 with fabric 0.16.14:
  loader 0.16.10 -> 0.16.14
  ~ Lithium mc1.21.4-0.14.7 -> mc1.21.4-0.14.8
```

## Step by step

1. **Plan:** for each candidate release, find the newest loader build and the newest
   acceptable file for every mod and dependency.
2. **Stage:** make sure any manual downloads are present, get the right Java, download
   everything into `.mcsm/staging/`, verify hashes, and run the loader installer. If anything fails here, the live server hasn't been touched.
3. **Warn and stop:** in-game countdown, then a graceful `stop`.
4. **Back up** the server directory to `backups/` (old backups are pruned).
5. **Swap:** remove the old managed mod jars and loader files, then move the new ones in.
6. **Verify:** boot the server and wait for `Done (…)!`.
7. **Commit or roll back:** on success, record the new state in `mcsm.lock.json`. On
   failure, restore the backup, restart the old version, and remember the failed
   combination.

> World upgrades are one-way: once a world has been opened in a newer Minecraft
> version, older versions can't load it. That's why every upgrade makes a full backup
> first. `mcsm restore` puts back the latest one (or a named one).

---
[← Power users](Power-Users)
