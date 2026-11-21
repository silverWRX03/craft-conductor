# Craft Conductor Ping

Tiny server-side helpers (a Paper/Purpur plugin, a Fabric/Quilt mod, a NeoForge mod and a Forge mod)
that every 5 seconds write each online player's ping to `.craft-conductor/ping.json` in the server's
folder:

```json
{"version": 1, "time": 1700000000000, "players": {"Steve": 42}}
```

They write nothing else, open no port and add no command. Craft Conductor reads the file and shows
the ping on the Dashboard; it copies the jar into `plugins/` (or `mods/`) when the owner turns
"Show players' ping" on. Players install nothing.

| Jar | Runs on |
| --- | --- |
| `craft_conductor_ping-paper-<version>.jar` | Paper and Purpur 1.17 and newer |
| `craft_conductor_ping-fabric-<version>.jar` | Fabric and Quilt, Minecraft 1.20.2 to 1.21.11 (`>=1.20.2 <26`) |
| `craft_conductor_ping-fabric26-<version>.jar` | Fabric and Quilt, Minecraft 26.1 and newer (`>=26`) |
| `craft_conductor_ping-neoforge-<version>.jar` | NeoForge, Minecraft 1.20.2 to 1.20.4 (`[1.20.2,1.20.5)`) |
| `craft_conductor_ping-neoforge1.20.5-<version>.jar` | NeoForge, Minecraft 1.20.5 and newer (`[1.20.5,)`) |
| `craft_conductor_ping-forge-<version>.jar` | Forge 47 (any build), Minecraft 1.20.1 (`[1.20.1,1.20.2)`) |
| `craft_conductor_ping-forge1.20.2-<version>.jar` | Forge 48 and 49, Minecraft 1.20.2 to 1.20.4 (`[1.20.2,1.20.6)`) |
| `craft_conductor_ping-forge1.20.6-<version>.jar` | Forge 50 and newer, Minecraft 1.20.6 and newer, 26.x too (`[1.20.6,)`) |

- `paper/`: the plugin (`Player#getPing()`), compiled for Java 16 against paper-api 1.17.1.
- `fabric/`: the mod, server only (`"environment": "server"`), without Fabric API. Fabric Loom
  compiles it against Minecraft 1.20.2 (Mojang's names) and Fabric Loader 0.14.25, for Java 17.
  Up to 1.21.11 Minecraft is obfuscated and Fabric runs mods on its intermediary names: the
  `fabric` jar is Loom's remapped jar. From 26.1 Minecraft isn't obfuscated and Fabric runs mods
  on Mojang's own names: the `fabric26` jar is the same classes, not remapped. Fabric refuses to
  start a server with a mod outside its range, so Craft Conductor must pick the right jar.
- `neoforge/`: the mod, server only: it registers no network payload, so players without it join
  (and, for NeoForge 20.2 to 20.4, `displayTest = "IGNORE_ALL_VERSION"`, so the server list doesn't
  show it as missing either). ModDevGradle compiles it against NeoForge 20.4.253 (Minecraft 1.20.4),
  for Java 17; ModDevGradle doesn't support NeoForge 20.2, but what the mod uses
  (`ServerLifecycleHooks.getCurrentServer()` and Minecraft's player list and latency) has the same
  names and types there, so the classes are the same (checked on real 1.20.2 servers). NeoForge runs
  Minecraft on Mojang's names from 1.20.2, so neither jar is remapped and both hold the same classes;
  only the metadata differs: NeoForge 20.2 to 20.4 read `META-INF/mods.toml`, NeoForge 20.5 (Minecraft
  1.20.5) and newer read `META-INF/neoforge.mods.toml`. Both need NeoForge 20.2 or newer, and
  NeoForge refuses to start a server with a mod outside its Minecraft range.
- `forge/`: the mod for Forge 1.20.1, server only: it registers no network channel, and
  `displayTest = "IGNORE_ALL_VERSION"`, so players without it join and the server list doesn't show it
  as missing. Forge 1.20.1 runs Minecraft on its own names for fields and methods (SRG, such as
  `f_8943_` for `ServerPlayer.latency`, where 1.20.1 keeps a player's ping), not Mojang's: ModDevGradle's
  legacyforge plugin compiles the mod against Forge 47.1.3 on Mojang's names, for Java 17, and its
  `reobfJar` (Forge's AutoRenamingTool) renames it to SRG; that reobfuscated jar is the one shipped.
  It declares Minecraft `[1.20.1,1.20.2)` and Forge `[47,)`, so a modpack's server on any Forge 47
  build (packs pin their own) loads it (checked on real servers with 47.0.0, 47.1.0 and the recommended
  build).
- `forge1.20.2/`: the mod for Forge on Minecraft 1.20.2 and newer, server only as the one for 1.20.1.
  From 1.20.2 a player's ping is on its connection (`player.connection.latency()`), as on NeoForge.
  One compile, against plain Minecraft 1.20.2 on Mojang's names (ModDevGradle without a loader, from
  NeoForm 1.20.2) and Forge 48.1.0's own jars for `@Mod` and `ServerLifecycleHooks`, for Java 17, gives
  two jars:
  - `forge1.20.2`: Forge 48 and 49 (Minecraft 1.20.2 to 1.20.4) still run Minecraft on SRG names, the
    same ones on all three versions (`f_8906_` for `ServerPlayer.connection`, `m_293018_` for its
    `latency()`). ModDevGradle's legacyforge plugin can't rename to them (the NeoForm runtime under it
    knows SRG names only up to 1.20.1), so the build does what legacyforge does, with the same tools:
    NeoForged's installertools 3.0.4 makes the mappings from Forge's MCPConfig for 1.20.2 and Mojang's
    1.20.2 server mappings (fetched from Mojang by their SHA-1, which the build checks), and
    AutoRenamingTool 2.0.4 renames the compiled jar with them.
  - `forge1.20.6`: from Forge 50 (Minecraft 1.20.6; Forge has no 1.20.5) Forge runs Minecraft on
    Mojang's names, and 26.x isn't obfuscated at all: the compile as it is.

  What the mod uses of Forge and its `mods.toml` (`mandatory`, `displayTest = "IGNORE_ALL_VERSION"`) are
  the same from Forge 48 to 66 (26.3). Each declares its Minecraft range and the Forge from the first one
  it runs on (`[48,)`, `[50,)`), and Forge refuses to start a server with a mod outside its Minecraft range.
  Checked on real servers with Forge 48.0.0 and 48.1.0 (1.20.2), 49.2.13 (1.20.4), 50.1.0 and 50.2.14
  (1.20.6), and the builds Craft Conductor installs for 1.21.1, 1.21.11, 26.1 and 26.3; the names the jar
  uses were also checked against the server Forge 49.0.2 (1.20.3) installs.
- `common/`: the file writing they all share (`PingFile`). Windows refuses to rename over a file that is
  open, as `ping.json` is for a moment while Craft Conductor reads it: the rename is tried once more 50 ms
  later, and the server's log gets one warning only when 3 readings in a row couldn't be written.

Checked on real servers by `tests/test_ping_helper_real.py` (see its docstring: it needs
`CRAFT_REAL_SERVERS=1` and mineflayer).

## Building

Needed only to build the helpers, not to run Craft Conductor:

- JDK 21,
- Gradle 8.10.2 (`gradle` on PATH, or `GRADLE` set to its program). There is no Gradle wrapper in
  the repository. The first build downloads Fabric Loom, and the Minecraft 1.20.2 server and its
  mappings, and ModDevGradle with NeoForge 20.4.253 and Minecraft 1.20.4, and Forge 47.1.3 with
  Minecraft 1.20.1 and their mappings, and Minecraft 1.20.2 with Forge 48.1.0's jars, Forge's MCPConfig
  and Mojang's mappings for it, into Gradle's cache (ModDevGradle's tools are told to run on the same
  Java 21, not to look for a Java 17).

```
python tools/build_helpers.py           # build and copy the jars into src/craft_conductor/helpers/
python tools/build_helpers.py --check   # build, and exit 1 when a shipped jar differs
```

The build is reproducible (no file timestamps, fixed file order, text resources with LF line
endings whatever the checkout has), so the same source gives the same jars on any computer. Checked
to give byte-identical jars for 1.0.0 on Windows with JDK 21.0.10 and Gradle 8.10.2, and on Linux
with Temurin 21.0.5 (the `gradle:8.10.2-jdk21` Docker image):

| Jar | SHA-256 |
| --- | --- |
| `craft_conductor_ping-paper-1.0.0.jar` | `e61b39a2...56ba733c` |
| `craft_conductor_ping-fabric-1.0.0.jar` | `5fc5715b...56738bb7` |
| `craft_conductor_ping-fabric26-1.0.0.jar` | `2aa4bfef...8a2e8ae0` |
| `craft_conductor_ping-neoforge-1.0.0.jar` | `32d13a2f...8c1faae3` |
| `craft_conductor_ping-neoforge1.20.5-1.0.0.jar` | `587e45b2...f625cee8` |
| `craft_conductor_ping-forge-1.0.0.jar` | `b934a025...ad2233e1` |
| `craft_conductor_ping-forge1.20.2-1.0.0.jar` | `d653aa83...2fc6747f` |
| `craft_conductor_ping-forge1.20.6-1.0.0.jar` | `fa7ee80d...03a9b2f7` |

Every tool and dependency Gradle downloads for the build (the plugins, ModDevGradle's tools, Forge's
and NeoForge's data, the libraries) must match a SHA-256 in `gradle/verification-metadata.xml`, or the
build stops. To regenerate it after updating a tool or dependency, run `gradle -p helpers/ping
--write-verification-metadata sha256 assemble` on Windows and again on Linux (the `gradle:8.10.2-jdk21`
Docker image) on top of the Windows file, so it lists what either platform resolves, and check the diff
with `python tools/build_helpers.py --check` on both. Gradle 8.10.2 can't write the Paper API's SNAPSHOT
("Multiple entries with same key"), so take `include 'paper'` out of `settings.gradle` while you
generate, and add what `:paper:assemble` then reports missing by hand; the two files Fabric Loom
makes itself (different bytes every build) are `trusted-artifacts` in the file, not hashed.
`--write-verification-metadata` only adds entries, never removes stale ones, and trusts whatever is
downloaded at that moment: review the diff of `verification-metadata.xml` for unexpected hash changes
before committing it (and the Paper entries added by hand the same way).

What it doesn't cover: Gradle's own download, the JDK, what Fabric Loom, ModDevGradle and the NeoForm
runtime fetch outside Gradle's dependency resolution (Mojang's jars and mappings, which they check by
the SHA-1 Mojang publishes), and the two files Loom makes itself (trusted, as above).

CI (`.github/workflows/helpers.yml`) runs `--check` and uploads the jars it built; if a local JDK
ever gives different bytes, commit the CI jar. Raise the version in `paper/build.gradle`,
`fabric/build.gradle`, `neoforge/build.gradle`, `forge/build.gradle` or `forge1.20.2/build.gradle` when
that helper changes (the jar name carries it), and rebuild.
