# Mods and modpacks (roadmap 48, 49, 53, 54) — design

Approved in conversation on 2026-11-20. The owner's words: "No game just a progress bar is fine".
Everything else below is Claude's proposal from the same conversation, which the owner did not change.

## Intent

The roadmap's "Mods and modpacks" items, on one branch (`feature/mods-and-modpacks`):

- **48. Manual CurseForge downloads picked up by themselves.** Already shipped in 0.29.0
  (`handdownload.look`, the Downloads folder and chosen folders). Only the TODO line is ticked.
- **54. No load check for a modpack's own mods.** A big modpack makes New server download every file
  in the pack before **Create my server** can be pressed, and the pack's author already checked
  them. Mods added on top are still checked.
- **49. Modpack download screen.** Creating a server shows its steps and a real progress bar. No game:
  the dinosaur game is dropped.
- **53. Make a modpack from a server's mods,** in Modrinth (`.mrpack`) or CurseForge (`.zip`) format,
  chosen when making it.

## Goals, non-goals, anti-goals

- Goal: creating a server from a big modpack is no longer held up by a check of the pack's own mods,
  at setup or at install.
- Goal: while a server is being made, people see where it's at (which step, how many files of how
  many) rather than only a spinner.
- Goal: a server's mods can be handed to players or another launcher as a standard modpack file.
- Non-goal: a game on the progress screen.
- Non-goal: putting config files in a made modpack. Some mods keep passwords or tokens in them.
- Anti-goal: a made modpack that quietly lacks mods. Each mod that can't go in is named.
- Anti-goal: handing out other people's files. A made modpack only links to the mod sites' own
  downloads and never holds a jar.

## 54. The load check skips the pack's own mods

**Today:**
- The setup page's check (`filecheck.for_setup`, through `POST /api/hub/mods/filecheck`) unpacks
  the pack and downloads all its files.
- `POST /api/hub/create` refuses when the cached check of the same choices found problems.
- The install (`Manager.apply` → `mod_problems`) runs the loader's check again on the staged files
  and refuses to install when there are problems.

**Change:**
- **A modpack with nothing added on top** (no `mods`, `optional_mods` or `client_mods`): the setup
  check answers right away, with `{"ok": true, "problems": [], "unreadable": [], "pack_only": true}`.
  Nothing is unpacked or downloaded. The page says "The modpack's own mods aren't checked: its maker
  did that."
- **With mods added on top:** the check runs as today, but a problem is dropped when it is the pack's
  own:
  - the mod that complains is one of the pack's files, and
  - the mod it's about (`needs`), when another mod provides it, is one of the pack's files too.
- **Problems about Minecraft, the loader or Java** (`kind` `minecraft`, `loader` or `java`) from a
  pack mod are the pack's own too.
- **A "missing" problem from a pack mod is kept when the person left mods out of the pack**
  (`modpack_exclude` not empty). Taking a mod out can be what made something else miss it.
- **The same rule at install** (`mod_problems`), for a server made from a modpack:
  - The pack's files are the lock's files the pack holds: `packupdate` state `mods`, where the key's
    file is the same version as the plan's.
  - The pack's own jars count too: state `files`, under `mods/`, still with the same SHA-1.
  - Problems among those alone don't stop the install. If the loader really refuses, the test boot
    says so, as for any server.
- **The Mods page's own check** (`for_server`) is unchanged. It's information there, and nothing
  waits on it.

## 49. Progress while the server is made

- The daemon's running job gets a `progress` dict, shown in `/api/status` as `job.progress`:
  - `steps`: the list of step keys for this setup.
  - `step`: the current step's key.
  - `done` / `total`: files within the step, when it has a count.
- **The steps, in order** (only those that apply):
  1. `pack`: "Downloading the modpack". Only when there's a pack.
  2. `plan`: "Choosing the mods' files".
  3. `manual`: "Waiting for mods you download by hand". Only while waiting.
  4. `java`: "Getting Java". `Manager.stage` picks Java first, and downloads it when it's missing.
  5. `mods`: "Downloading the mods", n of N, counted in `Manager.stage`'s loop (copied, already
     downloaded, or downloaded: each counts).
  6. `runtime`: "Downloading Minecraft and the mod loader".
  7. `boot`: "Starting the server once to check it works". Reported in `Manager.apply` just before
     the test boot.
- **How it's reported:** `Manager` gets an optional `progress` callback `(step, done=None,
  total=None)`. `Daemon.run_setup` sets it for the length of the setup and clears it after, and
  only setup uses it. A plain server (no mods) skips `mods`, and its step list says so.
- **The page:** the **Creating your server…** panel keeps its notice and event list, and gets an
  ordered list of the steps (done ✓, current, later) and a `<progress>` bar.
  - **The bar's value:** steps completed plus the current step's `done/total`, over the number of
    steps.
  - **Accessible:** `aria-valuetext`, for example "Downloading the mods: 37 of 212".
  - **Less motion:** the bar doesn't animate.
- It applies to every new server, not only modpacks (Claude's call: the same screen, and it helps
  everyone).

## 53. Make a modpack

- **Where:** the Mods page gets **Make a modpack…** (needs `mods.view`; the pack holds only names
  and links). It isn't offered on Vanilla, Paper or Purpur servers, or before the first install.
- **The dialog:**
  - A format choice: **Modrinth (.mrpack)** or **CurseForge (.zip)**.
  - What goes in: N mods on the server, M for players only.
  - **Not included**, with why, for each mod that can't go in.
  - **Download**.
- **Routes:**
  - `GET /api/modpack/make?format=mrpack|curseforge` returns
    `{"name", "included": [...], "left_out": [{"name", "why"}]}`.
  - `GET /api/modpack/make/download?format=…` sends the file (`Content-Disposition: attachment`),
    sent by the request handler like `/api/modsets/export`.
  - Both need `mods.view`.
- **Contents:** the installed server mods (the lock), plus players' mods
  (`clientpack.players_mods` on the lock's mods: its entries carry `side`).
- **`.mrpack` (Modrinth format 1):**
  - `modrinth.index.json`: `formatVersion` 1, `game` "minecraft", `versionId` (the date),
    `name` (the server's name), `summary`.
  - `files`: `path` `mods/<filename>`, `hashes` sha1 and sha512, `env`, `downloads` [url],
    `fileSize`.
  - `dependencies`: `minecraft` and `fabric-loader` / `quilt-loader` / `forge` / `neoforge` at the
    lock's versions.
  - **`env`:**
    - server mods that players also get: `{client: required, server: required}`;
    - server-only mods: `{client: unsupported, server: required}`;
    - players-only mods: `{client: required, server: unsupported}`;
    - an optional server mod (`required` false): `server: optional`.
  - **Hashes and sizes** come from Modrinth's `GET /v2/versions?ids=[…]`, one call for all of them,
    so they're the site's own.
  - **Only Modrinth files can go in** (`cdn.modrinth.com`). Left out and named: CurseForge mods
    ("only on CurseForge: a Modrinth pack can't link to it"), files added by hand ("added by hand:
    not on a mod site"), and datapacks ("a datapack for the world, not a mod").
  - The `summary` names what's left out.
- **CurseForge `.zip`:**
  - `manifest.json`: `minecraft.version`, `modLoaders` [{`id`: "<loader>-<version>", `primary`:
    true}], `manifestType` "minecraftModpack", `manifestVersion` 1, `name`, `version`, `author`
    "Craft Conductor", `files` [{`projectID`, `fileID`, `required`}], `overrides` "overrides".
  - `modlist.html` lists the mods, then a **Not included** section.
  - No overrides folder content.
  - **Only CurseForge files can go in.** Left out and named: Modrinth mods ("only on Modrinth: a
    CurseForge pack can't link to it"), hand-added files and datapacks, as above.
  - CurseForge has no sides: players-only mods simply go in.
- **The file's name:** `<server name>-<date>.mrpack` / `.zip`, made safe the way the modset export
  does.
- **Quilt:** an `.mrpack` names `quilt-loader`. The CurseForge manifest uses `quilt-<version>`.

## Constraints

- Standard library only at runtime, and the strict CSP (no inline scripts).
- The house rules in CLAUDE.md: manual, Help, translations (9 languages), CHANGELOG under 0.31.0
  (not released yet), screenshots for changed screens, real-world tests via
  `tools/real_world_tests.py add-test`, website demo contract, and a security then efficiency review.
- `feature/servers-and-players` is a separate branch also adding a 0.31.0 section and TODO ticks.
  Whichever merges second resolves those two files.

## Left to the builder

Copy wording, CSS, how the dialog is laid out, the exact test names, and caching of the Modrinth
lookup (keyed by the lock's mods for a few minutes).
