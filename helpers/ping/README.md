# Craft Conductor Ping

Two tiny server-side helpers (a Paper/Purpur plugin here, a Fabric mod later) that every 5 seconds
write each online player's ping to `.craft-conductor/ping.json` in the server's folder:

```json
{"version": 1, "time": 1700000000000, "players": {"Steve": 42}}
```

They write nothing else, open no port and add no command. Craft Conductor reads the file and shows
the ping on the Dashboard; it copies the jar into `plugins/` (or `mods/`) when the owner turns
"Show players' ping" on. Players install nothing. Supported: Paper and Purpur 1.17 and newer.

## Building

Needed only to build the helpers, not to run Craft Conductor:

- JDK 21 (the plugin is compiled for Java 16 with `--release 16`),
- Gradle 8.10.2 (`gradle` on PATH, or `GRADLE` set to its program). There is no Gradle wrapper in
  the repository.

```
python tools/build_helpers.py           # build and copy the jars into src/craft_conductor/helpers/
python tools/build_helpers.py --check   # build, and exit 1 when a shipped jar differs
```

The build is reproducible (no file timestamps, fixed file order), so the same source gives the
same jar on any computer. CI (`.github/workflows/helpers.yml`) runs `--check` and uploads the jars it
built; if a local JDK ever gives different bytes, commit the CI jar. Raise the version in
`paper/build.gradle` when the helper changes (the jar name carries it), and rebuild.
