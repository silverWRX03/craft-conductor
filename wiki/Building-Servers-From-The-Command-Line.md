# Building servers from the command line

The control panel's **New server** does all of this with buttons. From a terminal:

## Build a new server in one command

One command downloads and builds everything: config, mods and their dependencies,
the loader, Java and `server.properties`. It then test-boots the server:

```sh
mcsm create ~/minecraft --loader fabric \
    --mod fabric-api --mod lithium --mod ferrite-core \
    --optional-mod create-fabric \
    --memory 6G --motd "Forever server" --rcon --accept-eula   # read https://aka.ms/MinecraftEULA first
cd ~/minecraft && mcsm run
```

`--minecraft` defaults to the newest release your mods support. Other options:
`--port`, `--max-players`, `--difficulty`, `--gamemode`, `--seed`, `--java`, `--curseforge ID`.

Or do the same thing step by step:

```sh
mkdir ~/minecraft && cd ~/minecraft
mcsm init --loader fabric --accept-eula     # read https://aka.ms/MinecraftEULA first
mcsm add fabric-api lithium ferrite-core    # Modrinth slugs
mcsm add create-fabric --optional           # don't hold upgrades back for this one
mcsm check                                  # what would be installed, what's blocking newer versions
mcsm update                                 # install it (and test-boot it)
mcsm run                                    # run it forever
```

## Bring in an existing server (e.g. from autoMCS)

Stop the server, then point Craft Conductor at the existing directory and tell it which Minecraft
version the server currently runs:

```sh
cd ~/mcsm
mcsm init --server-dir /path/to/existing/server --loader fabric --minecraft 1.21.1
mcsm import        # identifies the jars in mods/ via Modrinth and adds them to mcsm.toml
mcsm check
mcsm update        # re-installs the loader through mcsm so it can manage it from now on
```

Jars that Modrinth doesn't recognise stay where they are and are reported as
*unmanaged*. Add CurseForge mods with `mcsm add --source curseforge <id>` and then
delete the old jar, or leave it unmanaged if the mod never needs updating.

---
[← Power users](Power-Users)
