# Java in detail

By default (`[java] version = "auto"`) the server runs on the Java version that its
Minecraft version asks for. Craft Conductor looks for exactly that version, in this order:

1. that version in the server's `[java.versions]`,
2. the shared Java folder (`<home>/.craft-conductor/java/`, one copy per version for every
   server on this computer; `/data/.craft-conductor/java/` in Docker),
3. `[java] default` (your system `java`), if it's exactly that version,
4. Java already installed on this computer: `JAVA_HOME` and the usual install folders
   (Eclipse Adoptium, Microsoft, Oracle, Zulu, Corretto, BellSoft on Windows; `/Library/Java/JavaVirtualMachines`
   and Homebrew on macOS; `/usr/lib/jvm`, `/usr/java`, `/opt/java` on Linux). Each is run once with
   `-XshowSettings:properties -version` (nothing else) to read its version and architecture, and the
   answer is remembered by the file's size and date. A build for another architecture (an x64 Java on
   an Apple silicon Mac) is skipped. The one picked is written into `[java.versions]`, so the server's
   choice stays explicit,
5. a download of Eclipse Temurin into the shared folder, checksum-checked (turn this off with
   `auto_install = false`).

A newer major version is never picked by itself (some loaders and older mods break on one): the
Java page offers it, or set `[java] version = 25`.

| Command | What it does |
|---|---|
| `craft-conductor java list` | the shared Java (and which servers use it), Java found on this computer, and which one the server uses |
| `craft-conductor java install 21 17` | download Temurin runtimes into the shared folder |
| `craft-conductor java update` | bring the shared Java to its newest patch releases |
| `craft-conductor java use 21` | always run on Java 21 (must be at least what Minecraft needs) |
| `craft-conductor java use auto` | go back to following the Minecraft version |
| `craft-conductor java remove 17` | delete a shared version (refused while a server uses it) |

## The shared folder

```
.craft-conductor/java/
  21/jdk-21.0.4+7/        a release (craft-conductor-java.json says what it is)
  21/jdk-21.0.5+11/       a newer patch release, installed next to it
  servers/                which server last started on which Java (one small file each)
  checked.json            what each Java found on the computer turned out to be
```

- An update installs the new release next to the old one; servers move to it at their next start.
- Each server start leaves its process id in `<release>/.in-use/`. An older release is deleted only
  when no process listed there is running (and, on Windows, when no program has its files open), and
  not within five minutes of being replaced (a server may be starting on it that moment).
- Deleting a server never deletes a Java another server uses. A shared version that only the deleted
  server used is removed with it.
- Backups, snapshots and server exports never include Java.

Servers from before 0.23 kept their own copy in `<server>/.craft-conductor/java/`. Nothing moves it:
it's no longer used, and can be deleted by hand.

When a Minecraft upgrade needs a newer Java, it's found or downloaded during staging, before
the server is stopped.

---
[← Power users](Power-Users)
