# Craft Conductor Ping

Tiny server-side helpers (a Paper/Purpur plugin and a Fabric/Quilt mod) that every 5 seconds write
each online player's ping to `.craft-conductor/ping.json` in the server's folder:

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

- `paper/`: the plugin (`Player#getPing()`), compiled for Java 16 against paper-api 1.17.1.
- `fabric/`: the mod, server only (`"environment": "server"`), without Fabric API. Fabric Loom
  compiles it against Minecraft 1.20.2 (Mojang's names) and Fabric Loader 0.14.25, for Java 17.
  Up to 1.21.11 Minecraft is obfuscated and Fabric runs mods on its intermediary names: the
  `fabric` jar is Loom's remapped jar. From 26.1 Minecraft isn't obfuscated and Fabric runs mods
  on Mojang's own names: the `fabric26` jar is the same classes, not remapped. Fabric refuses to
  start a server with a mod outside its range, so Craft Conductor must pick the right jar.
- `common/`: the file writing both share (`PingFile`).

Checked on real servers by `tests/test_ping_helper_real.py` (see its docstring: it needs
`CRAFT_REAL_SERVERS=1` and mineflayer).

## Building

Needed only to build the helpers, not to run Craft Conductor:

- JDK 21,
- Gradle 8.10.2 (`gradle` on PATH, or `GRADLE` set to its program). There is no Gradle wrapper in
  the repository. The first build downloads Fabric Loom, and the Minecraft 1.20.2 server and its
  mappings, into Gradle's cache.

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

CI (`.github/workflows/helpers.yml`) runs `--check` and uploads the jars it built; if a local JDK
ever gives different bytes, commit the CI jar. Raise the version in `paper/build.gradle` or
`fabric/build.gradle` when that helper changes (the jar name carries it), and rebuild.
