"""Moving a server to another computer: export it to one .zip, import it there.

The export holds everything the server is: ``craft-conductor.toml``, ``craft-conductor.lock.json`` and the
server folder (worlds, mods, configs, server.properties, ops and whitelist, the
installed Minecraft and loader), your own mod files for players, plus backups if asked; the
parts chosen when it's made (parts.py). Left out: logs, crash reports, craft-conductor's own
``.craft-conductor`` folder (the Java it downloaded suits only this computer; the new one downloads
its own on first start), and the passwords, keys and IP bans (parts.SENSITIVE), except those
chosen to go along: they're locked with a password made for the export (secretzip.py), which the
import asks for.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import time
import tomllib
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import __version__, config as configmod, lock as lockmod, parts, private, safearchive, secretzip
from .properties import SECRET_KEYS
from .config import ConfigError

log = logging.getLogger(__name__)

FORMAT = 1
MANIFEST = "craft-conductor-export.json"
SKIP_IN_SERVER = {"logs", "crash-reports", "debug", ".craft-conductor"}
LOCKED_ZIP = "craft-conductor-locked.zip"  # the secrets chosen to go along, locked with a password (secretzip.py)
CLIENT_MODS = "client-mods"                 # (clientpack.CLIENT_DIR: your own mod files for players)
SKIP_NAMES = {"session.lock"}  # the running world's lock; Minecraft makes a new one
MAX_IMPORT = 1 << 40          # unpacked (worlds and backups included); the disk's free space decides first
MAX_IMPORT_FILES = 500_000


class TransferError(ValueError):
    pass


class NeedsPassword(TransferError):
    """The export holds a locked part: its password, or importing without it."""

    def __init__(self, locked: list[str]):
        super().__init__("this export's passwords and keys are locked: type the password it was made with")
        self.locked = locked


def _walk(base: Path):
    for dirpath, dirnames, filenames in os.walk(base):
        rel = Path(dirpath).relative_to(base)
        if rel == Path("."):
            dirnames[:] = [d for d in dirnames if d not in SKIP_IN_SERVER]
        dirnames[:] = [d for d in dirnames if not (Path(dirpath) / d).is_symlink()]
        for f in filenames:
            p = Path(dirpath) / f
            if f not in SKIP_NAMES and not p.is_symlink() and p.is_file():
                yield p, (rel / f).as_posix()


def export_name(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9 _'.()-]+", "", name).strip(" .")[:50] or "server"
    return f"{safe} {datetime.now().strftime('%Y-%m-%d %H%M')}.craft-conductor.zip"


def sensitive_present(manager) -> set[str]:
    """Which secrets (parts.SENSITIVE) this server has, so the page only offers those."""
    found = set()
    try:
        data = tomllib.loads(configmod.read_text(manager.config.path))
    except (OSError, tomllib.TOMLDecodeError):
        data = {}
    for item, (table, key) in parts.TOML_SECRETS.items():
        if isinstance(data.get(table), dict) and str(data[table].get(key) or "").strip():
            found.add(item)
    props = manager.server_dir / "server.properties"
    if props.is_file() and parts.properties_without_secrets(props.read_bytes().decode("latin-1"))[1]:
        found.add("rcon")
    bans = manager.server_dir / "banned-ips.json"
    try:
        if json.loads(bans.read_text(encoding="utf-8-sig")):
            found.add("ip_bans")
    except (OSError, ValueError):
        pass
    return found


def parts_present(manager) -> list[str]:
    """Which of parts.CHOICES this server has anything of (a map only once one is added)."""
    from .properties import read_properties
    level = read_properties(manager.server_dir / "server.properties").get("level-name") or "world"
    have = {part for _, part in parts.split(manager.server_dir, level)}
    if "mods" not in have and clientpack_dir(manager.config).is_dir():
        have.add("mods")
    return [p for p in parts.CHOICES if p in have]


def clientpack_dir(config) -> Path:
    from .clientpack import client_dir
    return client_dir(config)


def export(manager, dest: Path, include_backups: bool = False, say: Callable[[str], None] = log.info,
           keep_secrets: bool = False, holds=None, secrets=(), password: str | None = None) -> Path:
    """Write the server to ``dest`` (a .zip). The server should be stopped (or saving paused).

    ``holds``: the parts (parts.CHOICES) it carries; all of them when None. Passwords, keys and
    IP bans are left out, except the ``secrets`` chosen (parts.SENSITIVE), which go in locked with
    ``password`` (secretzip.py); logs never go. ``keep_secrets``: everything as it is (a copy made
    on this computer, to try a beta)."""
    cfg, lk = manager.config, manager.lock
    from .properties import read_properties, server_name
    server_dir = manager.server_dir
    props_path = server_dir / "server.properties"
    props = read_properties(props_path)
    level = props.get("level-name") or "world"
    holds = set(parts.CHOICES) if holds is None or keep_secrets else set(holds) & set(parts.CHOICES)
    chosen = set() if keep_secrets else set(secrets)
    if chosen - set(parts.SENSITIVE):
        raise ValueError(f"unknown secrets: {sorted(chosen - set(parts.SENSITIVE))}")
    settings = configmod.read_text(cfg.path)
    props_text = props_path.read_bytes().decode("latin-1") if props_path.is_file() else None
    present = sensitive_present(manager)
    locked_files: dict[str, bytes] = {}
    if not keep_secrets:
        toml_secrets = {}
        data = tomllib.loads(settings)
        for item, (table, key) in parts.TOML_SECRETS.items():
            value = data.get(table, {}).get(key) if isinstance(data.get(table), dict) else None
            if isinstance(value, str) and value.strip():
                settings = configmod.with_value(settings, table, key, '""')
                if item in chosen:
                    toml_secrets[f"{table}.{key}"] = value
        prop_secrets = {}
        if props_text is not None:
            props_text, prop_secrets = parts.properties_without_secrets(props_text)
        if toml_secrets or ("rcon" in chosen and prop_secrets):
            locked_files["secrets.json"] = json.dumps(
                {"toml": toml_secrets, "properties": prop_secrets if "rcon" in chosen else {}}, indent=1).encode()
        if "ip_bans" in chosen and "ip_bans" in present:
            locked_files["server/banned-ips.json"] = (server_dir / "banned-ips.json").read_bytes()
    locked = sorted(present & chosen) if locked_files else []
    if locked and not password:
        raise ValueError("locking secrets in an export takes a password")
    left_out = [] if keep_secrets else sorted(present - set(locked))
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.part")
    files = 0
    try:
        # This account's only, as long as it's here (a copy elsewhere gets that place's permissions).
        os.close(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600))
        private.protect(tmp)
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=5, allowZip64=True) as z:
            z.writestr(MANIFEST, json.dumps({
                "format": FORMAT, "name": server_name(props, cfg.root.name), "folder": cfg.root.name,
                "minecraft": lk.minecraft, "loader": lk.loader, "craft-conductor": __version__,
                "exported": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "backups": include_backups, "holds": sorted(holds), "left_out": left_out, "locked": locked}, indent=2))
            z.writestr(configmod.CONFIG_NAME, settings)
            if (cfg.root / lockmod.LOCK_NAME).exists():
                z.write(cfg.root / lockmod.LOCK_NAME, lockmod.LOCK_NAME)
            if locked:
                z.writestr(LOCKED_ZIP, secretzip.encrypt(locked_files, password))
            last = time.monotonic()

            def add(path: Path, name: str) -> None:
                nonlocal files, last
                z.write(path, name)
                files += 1
                if time.monotonic() - last > 5:
                    say(f"exporting: {files} files so far")
                    last = time.monotonic()
            if server_dir.is_dir():
                for path, rel in _walk(server_dir):
                    if path.is_relative_to(cfg.backups.dir):
                        continue
                    if not keep_secrets:
                        if rel == "server.properties":
                            continue  # (below, without its secrets)
                        part = parts.part_of(rel, level)
                        if part in parts.LOCKED or (part in parts.CHOICES and part not in holds):
                            continue
                    add(path, f"server/{rel}")
                if props_text is not None and not keep_secrets:
                    z.writestr("server/server.properties", props_text.encode("latin-1"))
            client = clientpack_dir(cfg)
            if "mods" in holds and client.is_dir():  # (your own mod files for players)
                for path, rel in _walk(client):
                    add(path, f"{CLIENT_MODS}/{rel}")
            if include_backups and cfg.backups.dir.is_dir():
                for path, rel in _walk(cfg.backups.dir):
                    add(path, f"backups/{rel}")
        dest = _put_in_place(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    say(f"exported {files} files to {dest} ({dest.stat().st_size / 1e6:.0f} MB)")
    return dest


def _put_in_place(tmp: Path, dest: Path) -> Path:
    """Give the finished export its name, never replacing another file: one by that name already
    (two exports in the same minute: #137) makes this ``<name> (2).craft-conductor.zip``, and so on."""
    suffix = ".craft-conductor.zip" if dest.name.endswith(".craft-conductor.zip") else dest.suffix
    stem = dest.name[:len(dest.name) - len(suffix)]
    for n in range(1, 1000):
        candidate = dest if n == 1 else dest.with_name(f"{stem} ({n}){suffix}")
        try:
            os.link(tmp, candidate)  # (fails when there's a file by that name: nothing is replaced)
            return candidate
        except FileExistsError:
            continue
        except OSError:  # (a drive without links)
            if candidate.exists():
                continue
            os.replace(tmp, candidate)
            return candidate
    raise OSError(f"there are too many exports named {dest.name} in {dest.parent}")


def read_manifest(archive: Path) -> dict:
    safearchive.check_zip(archive, MAX_IMPORT_FILES, TransferError)
    try:
        with zipfile.ZipFile(archive) as z:
            names = set(z.namelist())
            raw = z.read(MANIFEST) if MANIFEST in names and configmod.CONFIG_NAME in names else None
    except zipfile.BadZipFile as e:
        raise TransferError("that file isn't a .zip, or it's damaged") from e
    if raw is None:
        raise TransferError("that file isn't an Craft Conductor server export (made with Export on a server's Settings page)")
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise TransferError("the export's details are damaged") from e
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise TransferError("that export was made by a newer Craft Conductor; update Craft Conductor first")
    return data


def _member_parts(name: str) -> tuple[str, ...]:
    """Where a member of an export goes, relative to the new server's folder; raises
    safearchive.UnsafeName for anything outside the places an export holds."""
    found = safearchive.parts(name)
    if found[0] not in ("server", "backups", CLIENT_MODS) and name not in (configmod.CONFIG_NAME, lockmod.LOCK_NAME):
        raise safearchive.UnsafeName("it isn't a place Craft Conductor writes to")
    return found


def import_into(archive: Path, root: Path, say: Callable[[str], None] = log.info,
                password: str | None = None, skip_locked: bool = False) -> dict:
    """Unpack an export into ``root`` (a new, empty folder). An export with a locked part (the
    passwords, keys and IP bans chosen when it was made) needs its ``password``
    (NeedsPassword, before anything is written), unless ``skip_locked``: then those are left out."""
    manifest = read_manifest(archive)
    locked = [x for x in manifest.get("locked") or [] if x in parts.SENSITIVE]
    opened = None
    if locked and not skip_locked:
        if not password or not password.strip():
            raise NeedsPassword(locked)
        try:
            with zipfile.ZipFile(archive) as z:
                data = z.read(LOCKED_ZIP)
        except KeyError:
            raise TransferError("the export's locked part is missing") from None
        try:
            opened = secretzip.decrypt(data, password.strip())
        except secretzip.BadPassword:
            raise TransferError("that password isn't the one this export was locked with") from None
        except ValueError as e:
            raise TransferError(f"the export's locked part can't be read: {e}") from None
    if root.exists() and any(root.iterdir()):
        raise TransferError(f"{root} isn't empty")
    with zipfile.ZipFile(archive) as z:
        infos = [i for i in z.infolist() if not i.is_dir() and i.filename not in (MANIFEST, LOCKED_ZIP)]
    if len(infos) > MAX_IMPORT_FILES:  # (the end record understated it)
        raise TransferError(f"that export holds too many files ({len(infos):,}; at most {MAX_IMPORT_FILES:,})")
    total = sum(i.file_size for i in infos)
    if total > MAX_IMPORT:
        raise TransferError(f"that export is too big to import (it unpacks to {safearchive.size_words(total)})")
    safearchive.ensure_space(root, total, TransferError, "that server")
    root.mkdir(parents=True, exist_ok=True)
    count = 0
    skipped = safearchive.Skipped(f"the export {safearchive.printable(archive.name)}")
    try:
        with zipfile.ZipFile(archive) as z:
            for member in infos:
                try:
                    with safearchive.open_new(root, _member_parts(member.filename)) as out, z.open(member) as src:
                        shutil.copyfileobj(src, out, 1 << 20)
                except safearchive.UnsafeName as e:
                    skipped.add(member.filename, str(e))
                    continue
                count += 1
        skipped.log()
        path = root / configmod.CONFIG_NAME
        # The export's folders, wherever they were on the old computer, are now inside root.
        configmod.set_value(path, "server", "dir", '"server"')
        configmod.set_value(path, "backups", "dir", '"backups"')
        if opened is not None:
            _apply_locked(root, opened)
        _new_rcon_password(root / "server" / "server.properties")
        configmod.load(root)  # it must still make sense
        _fix_launch(root)
    except (ConfigError, OSError, zipfile.BadZipFile, ValueError) as e:
        shutil.rmtree(root, ignore_errors=True)
        raise TransferError(f"couldn't import it: {e}") from e
    say(f"imported {manifest.get('name')} ({count} files)")
    left_out = [x for x in manifest.get("left_out") or [] if x in parts.SENSITIVE]
    return {**manifest, "opened": locked if opened is not None else [],
            "left_out": sorted(set(left_out) | (set(locked) if opened is None else set()))}


def _apply_locked(root: Path, files: dict[str, bytes]) -> None:
    """Put an export's locked passwords, keys and IP bans into the new server. Only those: the
    settings it may set are the known secrets."""
    try:
        data = json.loads(files.get("secrets.json", b"{}"))
    except ValueError:
        raise TransferError("the export's locked part is damaged") from None
    allowed = {f"{table}.{key}" for table, key in parts.TOML_SECRETS.values()}
    for dotted, value in (data.get("toml") or {}).items():
        if dotted in allowed and isinstance(value, str):
            table, key = dotted.split(".", 1)
            configmod.set_value(root / configmod.CONFIG_NAME, table, key, json.dumps(value))
    secrets_found = {k: v for k, v in (data.get("properties") or {}).items() if k in SECRET_KEYS and isinstance(v, str)}
    props = root / "server" / "server.properties"
    if secrets_found and props.is_file():
        text = props.read_bytes().decode("latin-1")
        private.write_bytes(props, parts.properties_with_secrets(text, secrets_found).encode("latin-1"))
    if "server/banned-ips.json" in files:
        private.write_bytes(root / "server" / "banned-ips.json", files["server/banned-ips.json"])


def _new_rcon_password(props: Path) -> None:
    """RCON switched on without its password (it stayed on the other computer): a new one, so
    Craft Conductor's console commands from the command line keep working."""
    from .properties import read_properties, write_properties
    if not props.is_file():
        return
    values = read_properties(props)
    if values.get("enable-rcon", "").strip().lower() == "true" and not values.get("rcon.password", "").strip():
        write_properties(props, {"rcon.password": secrets.token_urlsafe(18)})
        log.info("the imported server's RCON password stayed on the other computer: it has a new one")


def _fix_launch(root: Path) -> None:
    """Forge/NeoForge start from win_args.txt on Windows and unix_args.txt elsewhere."""
    from .loaders.base import args_file_name
    lk = lockmod.load(root)
    want = args_file_name()
    changed = False
    for i, arg in enumerate(lk.launch):
        for other in ("win_args.txt", "unix_args.txt"):
            if arg.startswith("@") and arg.endswith(other) and other != want:
                lk.launch[i] = arg[: -len(other)] + want
                changed = True
    if changed:
        lockmod.save(root, lk, touch=False)
