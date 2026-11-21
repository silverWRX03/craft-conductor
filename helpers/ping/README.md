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
- `common/`: the file writing they all share (`PingFile`).

Checked on real servers by `tests/test_ping_helper_real.py` (see its docstring: it needs
`CRAFT_REAL_SERVERS=1` and mineflayer).

## Building

Needed only to build the helpers, not to run Craft Conductor:

- JDK 21,
- Gradle 8.10.2 (`gradle` on PATH, or `GRADLE` set to its program). There is no Gradle wrapper in
  the repository. The first build downloads Fabric Loom, and the Minecraft 1.20.2 server and its
  mappings, and ModDevGradle with NeoForge 20.4.253 and Minecraft 1.20.4, and Forge 47.1.3 with
  Minecraft 1.20.1 and their mappings, into Gradle's cache (ModDevGradle's tools are told to run on
  the same Java 21, not to look for a Java 17).

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
| `craft_conductor_ping-paper-1.0.0.jar` | `6ab15467...b9becabc` |
| `craft_conductor_ping-fabric-1.0.0.jar` | `78c48350...b874f8e1` |
| `craft_conductor_ping-fabric26-1.0.0.jar` | `b12eb495...b8f59ed9` |
| `craft_conductor_ping-neoforge-1.0.0.jar` | `b82786a4...14808d3d` |
| `craft_conductor_ping-neoforge1.20.5-1.0.0.jar` | `f8541039...1ad53602` |
| `craft_conductor_ping-forge-1.0.0.jar` | `02bad2ea...657a50a4` |

CI (`.github/workflows/helpers.yml`) runs `--check` and uploads the jars it built; if a local JDK
ever gives different bytes, commit the CI jar. Raise the version in `paper/build.gradle`,
`fabric/build.gradle`, `neoforge/build.gradle` or `forge/build.gradle` when that helper changes (the jar
name carries it), and rebuild.
