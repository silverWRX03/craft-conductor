# How an upgrade works

`craft-conductor` runs your modded Minecraft server and **keeps it on the newest Minecraft
release once your mods support it**. It watches for new releases and checks
whether your loader and every mod you depend on (plus their dependencies) have
builds for them. When they do, it counts down in-game, backs up, swaps
everything over, boots the new version to make sure it works, and
**rolls back automatically** if it doesn't.

Each candidate file must list the target Minecraft version and a compatible loader. Required
dependencies are checked too; a failed lookup does not mean ready. Local JARs that Craft
Conductor cannot identify block a Minecraft-version change until you identify or disable them
on **Mods**. They remain untouched. Explicitly selecting a version still respects the
`wait_for_all_mods` setting, and local files are checked again before an update is applied.

It's one tool for both jobs: running the server (like autoMCS) and doing the
fragile upgrade pipeline you'd otherwise do by hand.

```
$ craft-conductor check
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
   everything into `.craft-conductor/staging/`, verify hashes, and run the loader installer. If anything fails here, the live server hasn't been touched.
3. **Warn and stop:** in-game countdown, then a graceful `stop`.
4. **Back up** the server directory to `backups/` (old backups are pruned). If the backup
   can't be made (a full disk), the update stops here and the old version is started again.
   Then Craft Conductor writes `.craft-conductor/update-in-progress.json`, naming that backup.
5. **Swap:** remove the old managed mod jars and loader files, then move the new ones in.
6. **Verify:** boot the server and wait for `Done (…)!`.
7. **Commit or roll back:** on success, record the new state in `craft-conductor.lock.json`
   (written to disk before anything else) and remove the note. On failure, restore the
   backup, restart the old version, and remember the failed combination.

If Craft Conductor is stopped anywhere in steps 4–7 (the power goes, the process is
killed), the note is still there on the next start. If `craft-conductor.lock.json` still
matches the note, the update never finished: the backup is put back before the server
runs, and the combination is remembered as failed (`craft-conductor update` tries it again).
If the lock file has changed, the update had finished and only the note is removed. A
restore or world swap cut off half-way is put right the same way (the old folder is kept
until the new one is in place). If the backup can't be put back (a full disk, a damaged
file), the server isn't started on half-updated files: free some space, or restore another
backup.

> World upgrades are one-way: once a world has been opened in a newer Minecraft
> version, older versions can't load it. That's why every upgrade makes a full backup
> first. `craft-conductor restore` puts back the latest one (or a named one).

---
[← Power users](Power-Users)
