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

In the control panel, a panel slides open on the right with the same links and a box at the bottom to
drag the downloaded files onto; each one is matched to its mod by CurseForge's checksum. On the New
server page they're found as soon as a modpack or mods are chosen, and loaded in **Manage Mods** before
the server is created (see "Mods you download by hand" in the manual).

While the page or the panel waits for them, Craft Conductor also looks for the files in the computer's
Downloads folder (Windows' Downloads known folder, wherever it was moved; `~/Downloads` on a Mac;
`XDG_DOWNLOAD_DIR` from `~/.config/user-dirs.dirs` on Linux) and in the folders chosen with **Always
look here** (kept in `.craft-conductor/hub.json` as `hand_folders`). Only the expected names are looked
at (and browsers' renames like `name (1).jar`); a file is copied, never moved, and kept only when the
copy's SHA-1 is CurseForge's. Craft Conductor running as a service under another account, or in
Docker, sees no Downloads folder: the page then asks where the files are, or takes them dropped on it.

---
[← Power users](Power-Users)
