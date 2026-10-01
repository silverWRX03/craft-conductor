# Running it forever

## The supervisor: `craft-conductor run`

`craft-conductor run` is a foreground supervisor, so run it under systemd (see
[`examples/craft_conductor.service`](https://github.com/silverWRX03/craft-conductor/blob/main/examples/craft_conductor.service)), tmux or screen. While it's running:

| Command | What it does |
|---|---|
| `craft-conductor update` | ask the running daemon to check and apply updates right now |
| `craft-conductor update --to 1.21.4` | ask it to move to one specific version |
| `craft-conductor cmd say hello` | send a console command over RCON (enable RCON in `server.properties`) |
| `craft-conductor status` | installed versions, mods, anything skipped, failed attempts |
| `craft-conductor stop` | stop the server gracefully and exit the daemon |
| `craft-conductor run --web` | same, plus the [web UI](Security) |

When the server isn't running, `craft-conductor update` does the upgrade and a test boot itself.

## Windows and macOS in the background

Craft Conductor runs until you press **Quit** in the control panel. To start it automatically, add
`craft-conductor-windows-x64.exe` to Task Scheduler with the trigger *At log on*. On a Mac, add
it to *System Settings → General → Login Items*.

---
[← Power users](Power-Users)
