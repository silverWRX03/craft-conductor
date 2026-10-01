# Java in detail

By default (`[java] version = "auto"`) the server runs on the Java version that its
Minecraft version asks for. Craft Conductor looks for it in this order:

1. that exact version in `[java.versions]`,
2. an craft-conductor-managed runtime in `.craft-conductor/java/`,
3. your system `java`, if it's exactly that version,
4. a fresh download of Eclipse Temurin (turn this off with `auto_install = false`).

| Command | What it does |
|---|---|
| `craft-conductor java list` | managed and configured runtimes, and which one the server uses |
| `craft-conductor java install 21 17` | download Temurin runtimes |
| `craft-conductor java update` | move managed runtimes to their newest patch release (server stopped) |
| `craft-conductor java use 21` | always run on Java 21 (must be at least what Minecraft needs) |
| `craft-conductor java use auto` | go back to following the Minecraft version |
| `craft-conductor java remove 17` | delete a managed runtime |

When a Minecraft upgrade needs a newer Java, it's downloaded during staging, before
the server is stopped.

---
[← Power users](Power-Users)
