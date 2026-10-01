# Mods that block third-party downloads

Some CurseForge authors don't allow tools to download their files. Craft Conductor still finds
the right file for each Minecraft version, but a person has to download it:

```
$ craft-conductor check
...
manual download needed - these authors block automatic downloads.
download each file and put it in /home/me/minecraft/manual-downloads:
  -> Some Mod: somemod-1.21.4-2.3.jar
     https://www.curseforge.com/minecraft/mc-mods/some-mod/files/5550001
```

Open the link, download the file, drop it into `manual-downloads/` (or straight into
the server's `mods/`), and run `craft-conductor update` again. The file's hash is checked against
CurseForge, so a wrong or outdated file isn't used. The update never starts until
every file is present, so the server is never left half-upgraded. With `craft-conductor run`, the
same links go to your Discord notifications when a new version needs them.

---
[← Power users](Power-Users)
