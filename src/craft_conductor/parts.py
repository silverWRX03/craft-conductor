"""What a server is made of, for choosing what goes into a backup or an export.

A server folder's files fall into parts the page lets you leave out (the world, mods and plugins,
their settings, player lists, web map files), two sensitive parts (logs, and passwords, keys and
players' IP addresses: a backup locks them to this computer, an export to a password), and the
rest, always kept: Minecraft, the loader and their libraries, server.properties without its
secrets, eula.txt...
"""

from __future__ import annotations

from pathlib import PurePosixPath

from .properties import SECRET_KEYS

CHOICES = ("world", "mods", "configs", "players", "maps")   # offered for backups and exports
LOCKED = ("logs", "secrets")                               # backups: locked to this computer
COMPLETE = CHOICES + ("secrets",)                          # a backup a roll back relies on (logs aren't needed)
MIXED = ("plugins", "dynmap", "plugins/dynmap", "plugins/BlueMap")  # folders whose contents are in different parts
PLAYER_FILES = frozenset({"ops.json", "whitelist.json", "banned-players.json", "usercache.json"})
IP_FILES = frozenset({"banned-ips.json"})                  # players' IP addresses
LOG_FOLDERS = frozenset({"logs", "crash-reports", "debug"})  # (logs show players' IP addresses too)
CONFIG_FOLDERS = frozenset({"config", "defaultconfigs"})
MAP_FOLDERS = tuple(PurePosixPath(p) for p in ("bluemap", "dynmap/web", "plugins/dynmap/web", "plugins/BlueMap/web"))

# The secrets an export can carry, locked with a password (each its own choice), and where each is.
SENSITIVE = {
    "discord_webhook": "the Discord webhook URL",
    "curseforge_api_key": "the CurseForge key",
    "invite_secret": "the friends' invite secret",
    "panel_password": "the control panel password",
    "rcon": "the RCON password and Minecraft's management secret",
    "ip_bans": "the IP bans (players' IP addresses)",
}
TOML_SECRETS = {  # item: (table, key) in craft-conductor.toml
    "panel_password": ("web", "password"), "invite_secret": ("client", "token"),
    "discord_webhook": ("notify", "discord_webhook"), "curseforge_api_key": ("curseforge", "api_key"),
}


def part_of(rel: str, level: str = "world") -> str | None:
    """The part a path in the server folder (``world/region/r.0.0.mca``) belongs to, or None for
    what's always kept. A folder that holds several parts (``plugins``) is None itself."""
    p = PurePosixPath(rel)
    parts = p.parts
    if not parts:
        return None
    top = parts[0]
    if top in (level, f"{level}_nether", f"{level}_the_end"):
        return "world"
    if top in LOG_FOLDERS:
        return "logs"
    if len(parts) == 1 and top in IP_FILES:
        return "secrets"
    if len(parts) == 1 and top in PLAYER_FILES:
        return "players"
    if any(p == m or m in p.parents for m in MAP_FOLDERS):
        return "maps"
    if top == "mods":
        return "mods"
    if top == "plugins" and len(parts) >= 2:  # plugin jars, and a folder of settings per plugin
        return "mods" if (len(parts) == 2 and parts[1].lower().endswith(".jar")) or parts[1] == ".paper-remapped" \
            else "configs"
    if top in CONFIG_FOLDERS or (top == "dynmap" and len(parts) >= 2):  # (Dynmap keeps its settings beside its map)
        return "configs"
    return None


def split(server_dir, level: str = "world"):
    """(path, part) for what's in a server folder: each top-level file and folder, and inside the
    folders that hold several parts (MIXED), what's in them."""
    def walk(folder, prefix: str):
        try:
            entries = sorted(folder.iterdir(), key=lambda p: p.name)
        except OSError:
            return
        for entry in entries:
            rel = f"{prefix}{entry.name}"
            if rel in MIXED and entry.is_dir() and not entry.is_symlink():
                yield from walk(entry, rel + "/")
            else:
                yield rel, part_of(rel, level)
    yield from walk(server_dir, "")


def properties_without_secrets(text: str) -> tuple[str, dict[str, str]]:
    """server.properties' text with the secrets' values emptied, and the secrets (as written there)."""
    out, found = [], {}
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        key, sep, value = body.partition("=")
        if sep and not body.lstrip().startswith(("#", "!")) and key.strip() in SECRET_KEYS and value.strip():
            found[key.strip()] = value.strip()
            line = f"{key}={line[len(body):]}"
        out.append(line)
    return "".join(out), found


def properties_with_secrets(text: str, found: dict[str, str]) -> str:
    """``text`` with ``found`` (from properties_without_secrets) put back."""
    lines, left = text.splitlines(keepends=True), dict(found)
    ending = next((line[len(line.rstrip("\r\n")):] for line in lines if line.endswith("\n")), "\n")
    for i, line in enumerate(lines):
        body = line.rstrip("\r\n")
        key, sep, _ = body.partition("=")
        if sep and not body.lstrip().startswith(("#", "!")) and key.strip() in left:
            lines[i] = f"{key.strip()}={left.pop(key.strip())}{line[len(body):]}"
    if lines and not lines[-1].endswith("\n") and left:
        lines[-1] += ending
    return "".join(lines) + "".join(f"{k}={v}{ending}" for k, v in left.items())
