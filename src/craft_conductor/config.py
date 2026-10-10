"""Loading and editing ``craft-conductor.toml``."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

STATE_DIR = ".craft-conductor"
CONFIG_NAME = "craft-conductor.toml"
LOADERS = ("fabric", "quilt", "neoforge", "forge", "paper", "purpur", "vanilla")
MOD_SOURCES = ("modrinth", "curseforge", "hangar")  # Hangar: Paper plugins
STRATEGIES = ("latest-compatible", "latest", "mods-only")
CHANNELS = ("release", "beta", "alpha")
UPDATE_CHANNELS = ("stable", "beta")   # Craft Conductor's own releases (selfupdate.CHANNELS)
LINK_DAYS = (1, 7, 30, 0)              # how long a new friends' invite link works; 0 = until a new one is made
DEFAULT_LINK_DAYS = 7


class ConfigError(Exception):
    pass


# A mod for players (``[client] mods``): a Modrinth slug or id, or ``curseforge:<project id>``
# (a CurseForge modpack's mods that only run on players' computers).
CLIENT_MOD = re.compile(r"[A-Za-z0-9_.-]{1,100}|curseforge:\d{1,10}")


@dataclass
class ModSpec:
    source: str
    id: str
    required: bool = True
    # Set on specs created automatically for a mod's dependencies.
    dependency_of: str | None = None
    # This mod's own lowest release channel (a mod with only alpha/beta builds), else the server's.
    channel: str | None = None
    # Its datapack build (Modrinth's "datapack" loader) instead of a mod: for a mod with no build
    # for the server type (Terralith on Forge 26.x). It goes in the world's datapacks folder.
    datapack: bool = False

    @property
    def label(self) -> str:
        return f"{self.source}:{self.id}"


@dataclass(frozen=True)
class Pin:
    """A mod held at one build: Modrinth's version id or CurseForge's file id, and the Minecraft
    version it was picked on (a build made for another one is allowed there, since the person
    chose it; a different Minecraft waits for another pick)."""
    version: str
    minecraft: str = ""


PIN_KEY = re.compile(r"(modrinth|curseforge):[A-Za-z0-9]{1,40}")
PIN_VERSION = re.compile(r"(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9._-]{0,39}")  # (it goes in a web address: never "..")


def _pins(raw) -> dict[str, Pin]:
    out = {}
    for key, value in (raw.items() if isinstance(raw, dict) else ()):
        if not PIN_KEY.fullmatch(str(key)) or not isinstance(value, dict):
            raise ConfigError(f"pins: {key!r} isn't a held mod (\"modrinth:<id>\" = {{ version = \"...\" }})")
        version, minecraft = str(value.get("version", "")), str(value.get("minecraft", ""))
        if not PIN_VERSION.fullmatch(version) or not re.fullmatch(r"[A-Za-z0-9.+_-]{0,40}", minecraft):
            raise ConfigError(f"pins: {key} has no valid version")
        out[str(key)] = Pin(version, minecraft)
    return out


def pin_literal(pin: Pin) -> str:
    return f'{{ version = "{pin.version}", minecraft = "{pin.minecraft}" }}'


def set_pin(path: Path, key: str, pin: Pin | None) -> None:
    """Hold a mod at a build (``None``: back to the newest build by itself)."""
    if not PIN_KEY.fullmatch(key) or (pin is not None and not PIN_VERSION.fullmatch(pin.version)):
        raise ConfigError(f"{key!r} can't be held at that version")
    if pin is None:
        unset_value(path, "pins", f'"{key}"')
    else:
        if not re.fullmatch(r"[A-Za-z0-9.+_-]{0,40}", pin.minecraft):
            raise ConfigError("that isn't a Minecraft version")
        set_value(path, "pins", f'"{key}"', pin_literal(pin))


@dataclass
class ServerConfig:
    dir: Path
    loader: str
    minecraft: str
    memory: str = "4G"
    jvm_args: list[str] = field(default_factory=list)
    aikar_flags: bool = False       # Aikar's garbage-collection flags (see jvmflags.py)
    startup_timeout: int = 600
    stop_timeout: int = 120
    find_lag: bool = True           # when it lags with players on, find out why by itself (lagfinder.py)
    cpu_cores: int = 0              # CPU cores it may use; 0: all (limits.py; not on macOS)
    priority: str = "normal"        # "low": the rest of the computer comes first


@dataclass
class UpdateConfig:
    strategy: str = "latest-compatible"
    mod_channel: str = "release"
    auto_upgrade: bool = True
    check_interval: int = 6 * 3600
    warn_minutes: list[int] = field(default_factory=lambda: [10, 5, 1])
    wait_for_empty: bool = False
    verify_boot: bool = True
    wait_for_all_mods: bool = True   # upgrade Minecraft only once every mod (optional ones too) supports it
    remind_days: int = 30            # then remind about mods still not updated, this often
    rehearse: bool = False           # try a new Minecraft on a copy of the server before updating by itself


@dataclass
class BackupConfig:
    dir: Path
    keep: int = 10
    exclude: list[str] = field(default_factory=lambda: ["logs", "crash-reports"])
    copy_to: Path | None = None      # also copy each backup here (a USB drive, a synced folder)
    copy_keep: int = 10              # how many copies to keep there


@dataclass
class ScheduleConfig:
    """Cron expressions (minute hour day-of-month month day-of-week), "" = off."""
    restart: str = ""
    backup: str = ""
    restart_when_empty: bool = False  # skip a scheduled restart while players are online


@dataclass
class WebConfig:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
    password: str = ""   # empty = chosen in the web UI (starts as PASSWORD); set here to lock it
    allowed_hosts: list[str] = field(default_factory=list)  # extra host names, e.g. behind a proxy
    tls_cert: str = ""   # HTTPS: a certificate and its key (PEM files), e.g. from `tailscale cert`
    tls_key: str = ""


@dataclass
class ClientConfig:
    """The download friends use to set up Minecraft for this server (see clientpack.py)."""
    enabled: bool = False
    token: str = ""                 # secret part of the invite link
    mods: list[str] = field(default_factory=list)   # extra client-only mods: Modrinth slugs, or curseforge:<id>
    memory_gb: int = 4              # memory the friends' Minecraft gets
    expires: int = 0                # when the invite link stops working (Unix time); 0 = never
    link_days: int = DEFAULT_LINK_DAYS  # how long new links work (one of LINK_DAYS; 0 = until replaced)

    def link_works(self, now: float) -> bool:
        return bool(self.enabled and self.token) and (not self.expires or now < self.expires)


@dataclass
class Config:
    root: Path
    server: ServerConfig
    updates: UpdateConfig
    backups: BackupConfig
    mods: list[ModSpec]
    java_default: str = "java"
    java_versions: dict[int, str] = field(default_factory=dict)
    java_version: int | None = None     # force a Java major version; None = what Minecraft needs
    java_auto_install: bool = True      # download Temurin when the needed version isn't available
    java_image: str = "jre"
    manual_dir: Path | None = None      # where to drop mods that must be downloaded by hand
    web: WebConfig = field(default_factory=lambda: WebConfig())
    self_update_check: bool = True      # look for new craft-conductor releases (installing always asks first)
    self_update_channel: str = "stable"  # stable releases only, or betas too (UPDATE_CHANNELS)
    discord_webhook: str = ""
    curseforge_api_key: str = ""
    restart_on_crash: bool = True
    client: ClientConfig = field(default_factory=ClientConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    tunnel_address: str = ""   # a playit.gg tunnel friends join through ("host" or "host:port")
    #: mods held at one version (Manage Mods → Change version): "source:project id" -> Pin
    pins: dict[str, "Pin"] = field(default_factory=dict)

    @property
    def path(self) -> Path:
        return self.root / CONFIG_NAME

    @property
    def state_dir(self) -> Path:
        return self.root / STATE_DIR


_DURATION = re.compile(r"^\s*(\d+)\s*([smhd]?)\s*$")


def parse_duration(value: str | int) -> int:
    """Parse ``"30m"``, ``"6h"``, ``"1d"`` or plain seconds into seconds."""
    if isinstance(value, int):
        return value
    m = _DURATION.match(value)
    if not m:
        raise ConfigError(f"invalid duration: {value!r} (use e.g. 30m, 6h, 1d)")
    n, unit = int(m.group(1)), m.group(2) or "s"
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def _choice(value: str, choices: tuple[str, ...], name: str) -> str:
    if value not in choices:
        raise ConfigError(f"{name} must be one of {', '.join(choices)} (got {value!r})")
    return value


def load(root: Path) -> Config:
    path = root / CONFIG_NAME
    if not path.exists():
        raise ConfigError(f"{path} not found - run `craft-conductor init` first")
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    return parse(root, data)


def _limits(s: dict) -> tuple[int, str]:
    """server.cpu_cores and server.priority, checked (limits.py)."""
    from . import limits
    try:
        return limits.check(s.get("cpu_cores", 0), str(s.get("priority", "normal")))
    except ValueError as e:
        raise ConfigError(f"server.{e}") from None


def _memory(value) -> str:
    """Java heap size: a number with M or G (``4G``, ``4096M``), or ``auto``."""
    text = str(value).strip()
    if text.lower() == "auto":
        return "auto"
    if re.fullmatch(r"\d+[MmGg]", text) and int(text[:-1]) > 0:
        return text.upper()
    raise ConfigError(f"server.memory is {value!r}; use something like 4G, 4096M, or auto")


def _copy_folder(value) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise ConfigError("backups.copy_to must be a full path, e.g. D:\\craft-conductor-backups or /media/usb/craft-conductor")
    return path


def _tunnel(value) -> str:
    from .tunnel import TunnelError, parse_address
    try:
        parse_address(str(value or ""))
    except TunnelError as e:
        raise ConfigError(f"tunnel.address: {e}") from None
    return str(value or "").strip()


def _schedule(c: dict) -> ScheduleConfig:
    from .schedule import CronError, parse
    out = ScheduleConfig(restart=str(c.get("restart", "")).strip(), backup=str(c.get("backup", "")).strip(),
                         restart_when_empty=bool(c.get("restart_when_empty", False)))
    for name in ("restart", "backup"):
        try:
            parse(getattr(out, name))
        except CronError as e:
            raise ConfigError(f"schedule.{name}: {e}") from None
    return out


def _client(c: dict) -> ClientConfig:
    mods = c.get("mods", [])
    if not isinstance(mods, list) or not all(isinstance(m, str) and CLIENT_MOD.fullmatch(m) for m in mods):
        raise ConfigError("client.mods must be a list of Modrinth project ids or slugs, or curseforge:<project id>")
    token = str(c.get("token", ""))
    if token and not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", token):
        raise ConfigError("client.token looks wrong; delete it and Craft Conductor makes a new one")
    memory = int(c.get("memory_gb", 4))
    if not 1 <= memory <= 32:
        raise ConfigError("client.memory_gb must be between 1 and 32")
    try:
        expires, days = int(c.get("expires", 0)), int(c.get("link_days", DEFAULT_LINK_DAYS))
    except (TypeError, ValueError):
        raise ConfigError("client.expires and client.link_days must be whole numbers") from None
    if expires < 0:
        raise ConfigError("client.expires must be a time (or 0 for never)")
    if days not in LINK_DAYS:
        raise ConfigError("client.link_days must be one of " + ", ".join(map(str, LINK_DAYS)) + " (0 = until replaced)")
    return ClientConfig(enabled=bool(c.get("enabled", False)), token=token, mods=list(mods), memory_gb=memory,
                        expires=expires, link_days=days)


def parse(root: Path, data: dict) -> Config:
    s = data.get("server", {})
    if "loader" not in s:
        raise ConfigError("[server] loader is required")
    server = ServerConfig(
        dir=(root / s.get("dir", "server")).resolve(),
        loader=_choice(s["loader"], LOADERS, "server.loader"),
        minecraft=str(s.get("minecraft", "latest")),
        memory=_memory(s.get("memory", "4G")),
        jvm_args=list(s.get("jvm_args", [])),
        aikar_flags=bool(s.get("aikar_flags", False)),
        find_lag=bool(s.get("find_lag", True)),
        cpu_cores=_limits(s)[0], priority=_limits(s)[1],
        startup_timeout=parse_duration(s.get("startup_timeout", 600)),
        stop_timeout=parse_duration(s.get("stop_timeout", 120)),
    )

    u = data.get("updates", {})
    updates = UpdateConfig(
        strategy=_choice(u.get("strategy", "latest-compatible"), STRATEGIES, "updates.strategy"),
        mod_channel=_choice(u.get("mod_channel", "release"), CHANNELS, "updates.mod_channel"),
        auto_upgrade=bool(u.get("auto_upgrade", True)),
        check_interval=parse_duration(u.get("check_interval", "6h")),
        warn_minutes=sorted((int(x) for x in u.get("warn_minutes", [10, 5, 1])), reverse=True),
        wait_for_empty=bool(u.get("wait_for_empty", False)),
        verify_boot=bool(u.get("verify_boot", True)),
        wait_for_all_mods=bool(u.get("wait_for_all_mods", True)),
        remind_days=max(1, int(u.get("remind_days", 30))),
        rehearse=bool(u.get("rehearse", False)),
    )

    b = data.get("backups", {})
    backups = BackupConfig(
        dir=(root / b.get("dir", "backups")).resolve(),
        keep=int(b.get("keep", 10)),
        exclude=list(b.get("exclude", ["logs", "crash-reports"])),
        copy_to=_copy_folder(b.get("copy_to", "")),
        copy_keep=max(1, int(b.get("copy_keep", 10))),
    )

    mods = []
    for i, m in enumerate(data.get("mods", [])):
        if "id" not in m:
            raise ConfigError(f"mods[{i}] is missing `id`")
        mods.append(ModSpec(
            source=_choice(m.get("source", "modrinth"), MOD_SOURCES, f"mods[{i}].source"),
            id=str(m["id"]),
            required=bool(m.get("required", True)),
            channel=_choice(m["channel"], CHANNELS, f"mods[{i}].channel") if "channel" in m else None,
            datapack=bool(m.get("datapack", False)),
        ))
    if any(m.datapack and m.source != "modrinth" for m in mods):
        raise ConfigError("datapack = true works for Modrinth mods only")
    if mods and server.loader == "vanilla":
        raise ConfigError("the vanilla loader cannot run mods; set [server] loader or remove [[mods]]")

    j = data.get("java", {})
    java_versions = {}
    for k, v in j.get("versions", {}).items():
        try:
            java_versions[int(k)] = v
        except ValueError:
            raise ConfigError(f"java.versions keys must be Java major versions (got {k!r})") from None

    forced = j.get("version", "auto")
    if forced != "auto" and not (isinstance(forced, int) or str(forced).isdigit()):
        raise ConfigError(f'[java] version must be "auto" or a major version like 21 (got {forced!r})')

    return Config(
        root=root.resolve(),
        server=server,
        updates=updates,
        backups=backups,
        mods=mods,
        java_default=j.get("default", "java"),
        java_versions=java_versions,
        java_version=None if forced == "auto" else int(forced),
        java_auto_install=bool(j.get("auto_install", True)),
        java_image=_choice(j.get("image", "jre"), ("jre", "jdk"), "java.image"),
        manual_dir=(root / data.get("downloads", {}).get("manual_dir", "manual-downloads")).resolve(),
        self_update_check=bool(data.get("craft-conductor", {}).get("update_check", True)),
        self_update_channel=_choice(data.get("craft-conductor", {}).get("update_channel", "stable"),
                                    UPDATE_CHANNELS, "craft-conductor.update_channel"),
        web=WebConfig(
            enabled=bool(data.get("web", {}).get("enabled", False)),
            host=str(data.get("web", {}).get("host", "127.0.0.1")),
            port=int(data.get("web", {}).get("port", 8765)),
            password=str(data.get("web", {}).get("password", "")),
            allowed_hosts=[str(x).lower() for x in data.get("web", {}).get("allowed_hosts", [])],
            tls_cert=str(data.get("web", {}).get("tls_cert", "")),
            tls_key=str(data.get("web", {}).get("tls_key", "")),
        ),
        discord_webhook=data.get("notify", {}).get("discord_webhook", ""),
        curseforge_api_key=(data.get("curseforge", {}).get("api_key", "")
                            or os.environ.get("CRAFT_CONDUCTOR_CURSEFORGE_API_KEY", "")),
        restart_on_crash=bool(s.get("restart_on_crash", True)),
        client=_client(data.get("client", {})),
        schedule=_schedule(data.get("schedule", {})),
        tunnel_address=_tunnel(data.get("tunnel", {}).get("address", "")),
        pins=_pins(data.get("pins", {})),
    )


TEMPLATE = """\
# Craft Conductor configuration - https://github.com/silverWRX03/craft-conductor

[server]
dir = "server"                 # server directory (world, config/, mods/, server.properties)
loader = "{loader}"            # fabric | quilt | neoforge | forge | paper | purpur | vanilla
minecraft = "{minecraft}"      # version a new server is made on, whatever its mods ("latest" = newest release the loader runs)
memory = "4G"
jvm_args = []                  # extra JVM flags, e.g. ["-XX:+UseZGC"]
aikar_flags = false            # Aikar's GC flags: fewer lag spikes with lots of memory (16 GB+)
find_lag = true                # when it lags with players on, find out why by itself
cpu_cores = 0                  # CPU cores it may use (0 = all; Linux and Windows)
priority = "normal"            # "low": other programs on this computer come first
startup_timeout = "10m"        # how long a boot may take before it counts as failed
stop_timeout = "2m"
restart_on_crash = true

[updates]
# latest-compatible: move to the newest release that the loader and every required mod support
# latest:            only ever move to the newest release, waiting until everything supports it
# mods-only:         never change the Minecraft version, just keep mods updated
strategy = "latest-compatible"
mod_channel = "release"        # lowest mod release channel to accept: release | beta | alpha
auto_upgrade = true            # let `craft-conductor run` apply upgrades on its own
check_interval = "6h"
warn_minutes = [10, 5, 1]      # in-game countdown before a restart
wait_for_empty = false         # postpone upgrades until nobody is online
verify_boot = true             # boot the upgraded server and roll back if it fails to start
wait_for_all_mods = true       # upgrade Minecraft only when every mod (optional ones too) supports it
remind_days = 30               # a month after a new version is out (and every month after), list the mods holding it back
rehearse = false               # before updating Minecraft by itself, try the update on a copy of the server first

[backups]
dir = "backups"
keep = 10
exclude = ["logs", "crash-reports"]
# copy_to = "/media/usb/craft-conductor-backups"   # also copy every backup here (a USB drive, a synced folder)
# copy_keep = 10

[schedule]                     # cron: minute hour day-of-month month day-of-week, local time; "" = off
restart = ""                   # e.g. "0 4 * * *" = every day at 4:00 (players get the countdown first)
backup = ""                    # e.g. "0 */6 * * *" = every 6 hours
restart_when_empty = false     # skip a scheduled restart while players are online

[java]
version = "auto"               # "auto" = whatever the Minecraft version needs, or force one, e.g. 21
auto_install = true            # download Eclipse Temurin into the shared Java folder when no Java on this computer fits
image = "jre"                  # jre | jdk
default = "java"               # a system Java to use if it is exactly the right version
# Java you installed yourself, by major version (used before downloading; Java found on this
# computer is added here when a server starts using it):
# [java.versions]
# 17 = "/usr/lib/jvm/java-17-openjdk/bin/java"
# 21 = "/usr/lib/jvm/java-21-openjdk/bin/java"

[notify]
discord_webhook = ""

[craft-conductor]
update_check = true            # tell you when a new version of Craft Conductor is out (it never installs without asking)
update_channel = "stable"      # stable | beta (early versions: newer, less tested)

[web]
enabled = false                # or start with `craft-conductor run --web`
host = "127.0.0.1"             # only this machine (the safe default); "0.0.0.0" opens it to your network
port = 8765
password = ""                  # empty = starts as PASSWORD and you choose your own when you sign in
# allowed_hosts = ["mc.example.com"]  # host names used to reach the panel through a reverse proxy

[downloads]
# Some CurseForge authors block third-party downloads. Craft Conductor prints a link for each;
# download the file and drop it in this folder (or straight into mods/), then update again.
manual_dir = "manual-downloads"

[curseforge]
api_key = ""                   # or set CRAFT_CONDUCTOR_CURSEFORGE_API_KEY; only needed for curseforge mods

# One [[mods]] block per mod. Dependencies are resolved automatically.
# required = true  -> Minecraft upgrades wait for this mod
# required = false -> the mod is left out of an upgrade if it isn't ready, and comes back when it is
"""


def render_template(loader: str, minecraft: str) -> str:
    return TEMPLATE.format(loader=loader, minecraft=minecraft)


def mod_block(spec: ModSpec) -> str:
    ident = spec.id if spec.id.isdigit() and spec.source == "curseforge" else f'"{spec.id}"'
    channel = f'channel = "{spec.channel}"  # accepts early (unstable) builds\n' if spec.channel in CHANNELS else ""
    datapack = "datapack = true  # its datapack build, in the world's datapacks folder\n" if spec.datapack else ""
    return f'\n[[mods]]\nsource = "{spec.source}"\nid = {ident}\nrequired = {str(spec.required).lower()}\n{channel}{datapack}'


def append_mod(path: Path, spec: ModSpec) -> None:
    text = path.read_text()
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text + mod_block(spec))


def remove_mod(path: Path, source: str, mod_id: str) -> bool:
    """Remove a ``[[mods]]`` block, leaving the rest of the file (and its comments) intact."""
    lines = path.read_text().splitlines(keepends=True)
    # Split into chunks that each start at a table header.
    chunks: list[list[str]] = [[]]
    for line in lines:
        if re.match(r"^\s*\[", line):
            chunks.append([])
        chunks[-1].append(line)
    kept, removed = [], False
    for chunk in chunks:
        if chunk and chunk[0].strip() == "[[mods]]":
            body = tomllib.loads("".join(chunk[1:]))
            if str(body.get("id")) == mod_id and body.get("source", "modrinth") == source:
                removed = True
                continue
        kept.append(chunk)
    if removed:
        path.write_text("".join(line for chunk in kept for line in chunk))
    return removed


def set_mod_required(path: Path, source: str, mod_id: str, required: bool) -> bool:
    """Set ``required`` in a ``[[mods]]`` block in place: the rest of the block (its channel, its
    datapack, comments) and its place in the list stay as they are. False if it isn't listed."""
    lines = path.read_text().splitlines(keepends=True)
    chunks: list[list[str]] = [[]]
    for line in lines:
        if re.match(r"^\s*\[", line):
            chunks.append([])
        chunks[-1].append(line)
    literal = "true" if required else "false"
    for chunk in chunks:
        if not (chunk and chunk[0].strip() == "[[mods]]"):
            continue
        body = tomllib.loads("".join(chunk[1:]))
        if str(body.get("id")) != mod_id or body.get("source", "modrinth") != source:
            continue
        for i, line in enumerate(chunk):
            if i and re.match(r"^\s*required\s*=", line):
                chunk[i] = re.sub(r"^(\s*required\s*=\s*)[^#\s]+", lambda m: m.group(1) + literal, line, count=1)
                break
        else:  # (written by hand without it: it was required)
            at = max(i for i, line in enumerate(chunk) if line.strip())
            chunk.insert(at + 1, f"required = {literal}\n" if chunk[at].endswith("\n") else f"\nrequired = {literal}\n")
        path.write_text("".join(line for c in chunks for line in c))
        return True
    return False


def set_mods(path: Path, specs: list[ModSpec]) -> None:
    """Replace every ``[[mods]]`` block with ``specs``, keeping the rest of the file as it is."""
    lines = path.read_text().splitlines(keepends=True)
    chunks: list[list[str]] = [[]]
    for line in lines:
        if re.match(r"^\s*\[", line):
            chunks.append([])
        chunks[-1].append(line)
    kept = "".join(line for chunk in chunks if not (chunk and chunk[0].strip() == "[[mods]]") for line in chunk)
    if kept and not kept.endswith("\n"):
        kept += "\n"
    path.write_text(kept + "".join(mod_block(spec) for spec in specs))


def set_value(path: Path, table: str, key: str, literal: str) -> None:
    """Set ``key = literal`` inside ``[table]``, keeping every other line (and comment) as is."""
    lines = path.read_text().splitlines(keepends=True)
    header = re.compile(rf"^\s*\[{re.escape(table)}\]\s*(#.*)?$")
    start = next((i for i, line in enumerate(lines) if header.match(line)), None)
    if start is None:
        suffix = "" if not lines or lines[-1].endswith("\n") else "\n"
        path.write_text("".join(lines) + f"{suffix}\n[{table}]\n{key} = {literal}\n")
        return
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^\s*\[", lines[i])), len(lines))
    assign = re.compile(rf"^(\s*{re.escape(key)}\s*=\s*)([^#\n]*?)(\s*#.*)?$")
    for i in range(start + 1, end):
        m = assign.match(lines[i].rstrip("\n"))
        if m:
            comment = m.group(3) or ""
            lines[i] = f"{m.group(1)}{literal}{comment}\n"
            break
    else:
        lines.insert(start + 1, f"{key} = {literal}\n")
    path.write_text("".join(lines))


def unset_value(path: Path, table: str, key: str) -> bool:
    """Remove ``key = ...`` from ``[table]`` (every other line, and comment, stays). False if it wasn't there."""
    lines = path.read_text().splitlines(keepends=True)
    header = re.compile(rf"^\s*\[{re.escape(table)}\]\s*(#.*)?$")
    start = next((i for i, line in enumerate(lines) if header.match(line)), None)
    if start is None:
        return False
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^\s*\[", lines[i])), len(lines))
    assign = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for i in range(start + 1, end):
        if assign.match(lines[i]):
            del lines[i]
            path.write_text("".join(lines))
            return True
    return False
