"""Removing Craft Conductor from this computer (roadmap 38): what it added, what will happen to each
part, and doing it.

Two steps, so nothing is removed before the person has seen what will happen:

* ``plan(home, choices)`` lists every part (``Part``): whether it's here, what will happen to it in
  plain words, the exact paths, and what the person must do themselves. Servers, backups, exports,
  games and the backup lock key are kept unless ticked (``Choices``); kept parts are listed with
  ``kept=True`` and never handed to the runner.
* ``run(parts)`` does it in the fixed order (``ORDER``; stopping the servers first, through the
  ``stop_servers`` callback), carrying on past a part that fails, and returns a ``Report``.

Each part comes from a builder in ``BUILDERS`` (key -> builder), called in ``ORDER``: later parts of
this work (router, firewall, service, tunnels, the invite handler, launcher games) add builders. A
builder gets the ``Inventory`` (everything read about this home, without starting Craft Conductor)
and returns a Part, a list of Parts, or None. A part either deletes its ``paths`` (the default) or
does its own work through ``Part.remove(runner) -> Outcome``.

Safety: a path is deleted only if it comes from the inventory, isn't a link or junction, isn't (and
doesn't hold) the person's home folder, a drive root or a system folder, and is inside one of the
part's known places (``safe_to_delete``), and nothing is deleted through a link or junction between
that place and the path, the place included (the part lists such a link for the person instead).
``run`` checks every path again right before deleting it; a path refused then is a failure in the
report, never a crash. What a kept place holds is never deleted with a folder around it: that folder
is deleted one entry at a time around it (a server's own backups folder survives deleting the
server). A chosen place (servers, backups, exports) is deleted whole only when it holds nothing but
Craft Conductor's own entries: it may be the person's Documents folder. A server that didn't stop
(``stop_servers``) is kept, with its own backups.

Everything that changes the computer goes through a ``Runner``: tests pass one that only records
calls; ``SystemRunner`` is the real one. So does everything only the computer itself can tell (Windows
Firewall's rules, the registry) and the router: a runner without those methods gets the cautious
answer (see ``Runner``), never the real thing.

The system parts are read without Craft Conductor running: router port mappings from hub.json
(``upnp.mapped``, the ports it forwarded), Tailscale Serve from hub.json (``tunnels.tailscale``), a
running Cloudflare quick tunnel from ``.craft-conductor/tools/cloudflared.pid``, the Linux services
from their unit files (``service.plan``: only units for this home's panel and servers), the invite
link handler from the registry (through the runner) or its desktop entry, and the firewall rules from
Windows Firewall (through the runner). The games it set up in launchers are read from the launchers'
own folders, where they were recorded when made (see the notes above ``GAME_PREFIX``); only those are
removed, and only when ticked.
"""

from __future__ import annotations

import base64
import json
import os
import platform
import stat
import subprocess
import sys
import tomllib
import dataclasses
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Callable, Iterable, Mapping, Protocol

from . import config as configmod, folders, locations, lockbox

README = locations.README
PLAYERS_TOLD = "Craft Conductor is being removed from this computer"  # (told in game to players on a server)
REPORT_FILE = "Craft Conductor uninstall report.txt"  # (saved in Downloads when something is left to do)
DECLINED = 1223  # (Windows' ERROR_CANCELLED: the administrator prompt was answered No)
# The fixed order (servers are stopped before all of these, by run()'s stop_servers).
ORDER = ("tunnels", "router", "firewall", "service", "invite", "games", "exports", "backups", "servers",
         "lockbox", "state", "java", "program", "listed")
LINGER = Path("/var/lib/systemd/linger")  # (systemd's record of each account with lingering on)


# ------------------------------------------------------------------ what's chosen, what's planned
@dataclass
class Choices:
    """The tick boxes: what is deleted besides the program, its settings and its system changes.
    All off: servers, backups, exports and games are kept; the backup lock key is deleted unless
    ``keep_lockbox_key``."""
    servers: bool = False
    backups: bool = False
    exports: bool = False
    games: bool = False
    keep_lockbox_key: bool = False


@dataclass
class Outcome:
    """What doing one part came to, as plain-language lines."""
    removed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    manual: list[str] = field(default_factory=list)


class Runner(Protocol):
    """Everything that changes the computer. ``run`` returns the exit code (``elevated``: with
    administrator rights, DECLINED when the prompt is answered No; ``detached``: started and left
    running, 0 once it has started).

    A runner may also have these (``SystemRunner`` does; a runner without one gets the cautious
    answer noted, never the real computer):

    * ``firewall_rules() -> list[str] | None``: the names of Craft Conductor's own Windows Firewall
      rules (None: they couldn't be read; without it, as None);
    * ``registry_has(key) -> bool``: an ``HKCU\\...`` key is there (without it: taken as there);
    * ``router_remove(ports) -> [(port, protocol, why)]``: take these port mappings back on the router
      (UPnP), returning the ones it refused; raises when no router answers (without it: the ports are
      listed for the person);
    * ``stop_process(pid, exe) -> bool``: stop that process if it's still that program (without it:
      listed for the person);
    * ``launcher_running(key) -> bool | None``: that launcher ("minecraft", "prism") is open (None:
      can't be told; without it, or None, it's taken as open, and its games are listed instead);
    * ``write_text(path, text)``: replace a launcher's file whole (a temporary file, then a swap), to
      take Craft Conductor's installations out of it (without it: listed for the person);
    * ``own_unit() -> str | None``: the systemd unit this process runs in ("craft_conductor.service"
      when the control panel runs as its background service; without it, None): that unit is
      disabled without being stopped, so the uninstall isn't stopped half-way (R15);
    * ``remove_empty_folder(path)``: remove a folder only if it's empty (without it: the empty folder
      stays).
    """

    def run(self, argv: list[str], *, elevated: bool = False, detached: bool = False) -> int: ...

    def delete_tree(self, path: Path) -> None: ...

    def delete_file(self, path: Path) -> None: ...

    def registry_delete(self, key: str) -> None: ...


@dataclass
class Part:
    """One thing Craft Conductor added. ``action``: what will happen, in plain words; ``paths``: the
    exact files and folders deleted (or kept); ``manual``: what the person must do themselves;
    ``known``: the places ``paths`` must stay inside (checked again when deleting); ``user_home``:
    the person's home folder, never deleted (None: this account's); ``remove``: the part's own work,
    instead of deleting ``paths``; ``per_server``: each server's folder -> what of that server this
    part would delete (its folders, its own backups), kept when that server didn't stop (``run``);
    ``emptied``: folders removed after ``paths`` only if that left them empty (a server folder added
    from elsewhere: never deleted whole); ``system_ok``: paths exempt from the system-folder rule (only
    this account's Java folder in ProgramData: see ``refusal``)."""
    key: str
    label: str
    present: bool
    action: str
    paths: list[Path] = field(default_factory=list)
    manual: str | None = None
    kept: bool = False
    known: list[Path] = field(default_factory=list)
    user_home: Path | None = None
    remove: Callable[[Runner], Outcome] | None = field(default=None, repr=False, compare=False)
    per_server: dict[Path, list[Path]] = field(default_factory=dict)
    emptied: list[Path] = field(default_factory=list)
    system_ok: list[Path] = field(default_factory=list)


@dataclass
class Report:
    """What was done, as plain-language lines."""
    removed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    manual: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)

    def as_text(self) -> str:
        lines = ["Craft Conductor uninstall report", ""]
        for title, items in (("Removed", self.removed), ("Kept", self.kept), ("Couldn't be removed", self.failed),
                             ("Left for you to do", self.manual)):
            if items:
                lines += [f"{title}:", *(f"  - {x}" for x in items), ""]
        if not self.removed:
            lines += ["Nothing was removed.", ""]
        return "\n".join(lines)


# ------------------------------------------------------------------ the safety rules
def _same(a: Path | str, b: Path | str) -> bool:
    return locations._norm(a) == locations._norm(b)


def _holds_system(real: Path) -> bool:
    """``real`` holds a system folder (it's above the Windows folder, Program Files, /usr...)."""
    if os.name == "nt":
        found = [os.environ[v] for v in locations._WINDOWS_SYSTEM if os.environ.get(v)]
    else:
        found = [p for p in (*locations._POSIX_SYSTEM, *locations._POSIX_SYSTEM_ITSELF) if p != "/"]
    return any(locations.inside(p, real) for p in found)


def _lex(path: Path | str) -> str:
    """``path`` as written (made full, ``..`` worked out), not followed through links."""
    return os.path.normcase(os.path.abspath(path)).rstrip("\\/") or os.sep


def _lex_inside(child: Path | str, parent: Path | str) -> bool:
    c, p = _lex(child), _lex(parent)
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


def link_on_the_way(path: Path, known: Iterable[Path]) -> Path | None:
    """The first link or junction from a known place that holds ``path`` (as written) down to
    ``path`` itself, the place included: nothing is deleted through one (ruling R10). Folders above
    the place may be links (a home folder on another drive)."""
    p = Path(os.path.abspath(path))
    for k in known:
        if not _lex_inside(p, k):
            continue
        n = len(p.parts) - len(Path(os.path.abspath(k)).parts)
        for step in (*reversed(list(p.parents)[:n]), p):
            try:
                if folders.link_stat(os.lstat(step)):
                    return step
            except OSError:
                continue
    return None


PROGRAM_DATA = r"C:\ProgramData"  # (Windows' ProgramData when the environment doesn't say: tests set their own)


def _program_data() -> Path:
    """Windows' ProgramData folder (every account's), as this process sees it."""
    return Path(os.environ.get("ProgramData") or PROGRAM_DATA)


def _system_exempt(path: Path, system_ok: Iterable[Path]) -> bool:
    """``path`` is exactly one of ``system_ok`` and sits right in the real ProgramData (as written and
    as it really is): this account's own Java folder there (``_java_part``), the only folder in a
    system folder that's ever deleted."""
    if not any(_lex(path) == _lex(ok) for ok in system_ok):
        return False
    data, parent = _program_data(), Path(os.path.abspath(path)).parent
    return _lex(parent) == _lex(data) and locations._norm(parent) == locations._norm(data)


def _dangerous(path: Path, home: Path, system_ok: Iterable[Path] = ()) -> str | None:
    """Why ``path`` is never deleted wherever it came from: a drive root, the person's home folder or
    one holding it, a system folder (None: none of those). ``system_ok``: the one folder in ProgramData
    that may be (``_system_exempt``); it still mustn't hold a system folder."""
    try:
        is_dir = stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        is_dir = True
    real = Path(os.path.realpath(path))
    if real.parent == real or not os.path.splitdrive(str(real))[1].strip("\\/"):
        return "it's the top of a drive"
    if locations.inside(home, real):
        return "it's your home folder, or holds it"
    if is_dir and ((locations.is_system(real) and not _system_exempt(path, system_ok)) or _holds_system(real)):
        return "it's a system folder"
    return None


def refusal(path: Path, home: Path, known: Iterable[Path], system_ok: Iterable[Path] = ()) -> str | None:
    """Why ``path`` mustn't be deleted (None: it may be). ``home``: the person's home folder;
    ``system_ok``: see ``_dangerous`` (only the system-folder rule is relaxed, only for that exact path)."""
    path, known, system_ok = Path(path), list(known), list(system_ok)
    if not path.is_absolute():
        return "it isn't a full path"
    try:
        st: os.stat_result | None = os.lstat(path)
    except FileNotFoundError:
        st = None
    except OSError as e:
        return f"it can't be looked at ({e.strerror or e})"
    if st is not None and folders.link_stat(st):
        return "it's a link or junction, so what it leads to isn't Craft Conductor's"
    if why := _dangerous(path, home, system_ok):
        return why
    holding = [k for k in known if _lex_inside(path, k)]
    real = os.path.realpath(path)
    if not any(locations.inside(real, k) for k in holding):
        return "it isn't one of Craft Conductor's places"
    if link := link_on_the_way(path, holding):
        return f"it's reached through a link or junction ({link})"
    return None


def safe_to_delete(path: Path, home: Path, known: list[Path]) -> bool:
    """``path`` may be deleted: not a link or junction, not ``home`` (the person's home folder) or a
    folder holding it, not a drive root or a system folder, and inside one of ``known``."""
    return refusal(path, home, known) is None


# ------------------------------------------------------------------ what's here (read without a Hub)
def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _executable() -> str:
    return sys.executable


def _prefix() -> str:
    return sys.prefix


def _system() -> str:
    return {"Windows": "windows", "Darwin": "darwin"}.get(platform.system(), "linux")


def _env(env: Mapping[str, str], name: str) -> str:
    """``env[name]``, ignoring case (Windows' own variables are)."""
    for key, value in env.items():
        if key.upper() == name.upper():
            return value
    return ""


def _user_home(env: Mapping[str, str]) -> Path:
    names = ("USERPROFILE", "HOME") if _system() == "windows" else ("HOME", "USERPROFILE")
    for name in names:
        if _env(env, name):
            return Path(_env(env, name))
    return Path.home()


def _server_toml(root: Path) -> dict:
    try:
        data = tomllib.loads(configmod.read_text(root / configmod.CONFIG_NAME))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _table_dir(root: Path, data: dict, table: str, default: str, key: str = "dir") -> Path:
    """A folder a server's craft-conductor.toml names (``[server] dir``, ``[backups] dir``,
    ``[downloads] manual_dir``), as written (not followed through links: a link isn't deleted)."""
    t = data.get(table)
    value = t.get(key, default) if isinstance(t, dict) else default
    return Path(os.path.abspath(root / (value if isinstance(value, str) and value else default)))


def _strictly_inside(child: Path, parent: Path) -> bool:
    """``child`` is inside ``parent`` (as written), and isn't ``parent`` itself."""
    return _lex_inside(child, parent) and _lex(child) != _lex(parent)


def _backup_files(folder: Path) -> list[Path]:
    """What Craft Conductor writes in a backups folder (backup.py, snapshots.py, areas.py): its backups,
    their notes, unfinished ones and its record of their checks. Nothing else there is its own."""
    from . import areas, backup
    try:
        entries = sorted(folder.iterdir()) if _plain_dir(folder) else []
    except OSError:
        return []
    out = []
    for e in entries:
        n = e.name
        try:
            is_dir = stat.S_ISDIR(os.lstat(e).st_mode)
        except OSError:
            continue
        if not is_dir and (n.endswith((backup.SUFFIX, backup.SUFFIX + ".json", ".part"))
                           or n in (areas.CHECKS, areas.CHECKS + ".tmp")):
            out.append(e)
    return out


def _plain_dir(path: Path) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(st.st_mode) and not folders.link_stat(st)


@dataclass
class Inventory:
    """Everything read about a Craft Conductor home, for the part builders."""
    home: Path
    state_dir: Path
    user_home: Path
    choices: Choices
    env: Mapping[str, str]
    runner: Runner | None
    hub: dict                          # hub.json (hub.read_hub_file)
    places: dict                       # where servers, backups and exports are kept (locations.read)
    servers: dict[str, Path]           # the servers Craft Conductor manages, by id
    configs: dict[str, dict]           # each server's craft-conductor.toml ({} when it can't be read)
    keep: list[Path] = field(default_factory=list)  # what nothing deleted may take with it

    def own_folder(self, sid: str) -> bool:
        """The server's folder is Craft Conductor's own: it's in the servers place (Hub.delete_server's
        rule), so it's deleted whole. Any other (the home folder, a folder added from elsewhere) may hold
        the person's own files too."""
        root = self.servers[sid]
        return _lex(root.parent) == _lex(self.places["servers"]) and not _same(root, self.home)

    def game_of(self, sid: str) -> Path:
        """The server's server folder (``[server] dir``), as written."""
        return _table_dir(self.servers[sid], self.configs[sid], "server", "server")

    def pieces_of(self, sid: str) -> list[Path]:
        """What the servers part deletes of one server (Hub.delete_server's rule): its folder when it's
        Craft Conductor's own (``own_folder``); otherwise only the server's own pieces inside its folder
        (its server folder, manual downloads folder, craft-conductor.toml, lock file and state folder,
        not the home's), and the folder itself afterwards only if that left it empty. Its backups are
        the backups part's. A server folder outside the server's folder is never deleted (``outside_of``)."""
        root = self.servers[sid]
        if self.own_folder(sid):
            return _existing([root])
        inside = [self.game_of(sid), _table_dir(root, self.configs[sid], "downloads", "manual-downloads", "manual_dir"),
                  root / configmod.CONFIG_NAME, root / "craft-conductor.lock.json"]
        if not _same(root, self.home):
            inside.append(root / configmod.STATE_DIR)
        return _existing(p for p in inside if _strictly_inside(p, root))

    def outside_of(self, sid: str) -> list[Path]:
        """The server's server folder when it isn't inside the server's own folder: listed for the
        person, never deleted (it may be their Documents folder)."""
        root, game = self.servers[sid], self.game_of(sid)
        inside = _lex_inside(game, root) if self.own_folder(sid) else _strictly_inside(game, root)
        return [] if inside else _existing([game])

    def added_roots(self) -> list[Path]:
        """The server folders that aren't Craft Conductor's own, nor the home: never deleted whole (only
        removed once empty), and kept from every other part."""
        return [r for sid, r in self.servers.items() if not self.own_folder(sid) and not _same(r, self.home)]

    def server_pieces(self) -> list[Path]:
        return _existing(p for sid in self.servers for p in self.pieces_of(sid))

    def raw_backup_dir(self, sid: str) -> Path:
        """The server's backups folder (``[backups] dir``), as written."""
        return _table_dir(self.servers[sid], self.configs[sid], "backups", "backups")

    def backup_dir_of(self, sid: str) -> list[Path]:
        """What the backups part deletes of one server's backups folder: the folder whole when it's
        inside the server's folder (and doesn't hold its server folder) or is ``<backups place>/<id>``;
        otherwise only the backups in it (``_backup_files``), as the folder may be one the person
        pointed it at with their own files in it."""
        root, folder, place = self.servers[sid], self.raw_backup_dir(sid), self.places["backups"]
        if ((_strictly_inside(folder, root) and not _lex_inside(self.game_of(sid), folder))
                or (place is not None and _lex(folder) == _lex(Path(place) / sid))):
            return _existing([folder])
        return _existing(_whole_or_each(folder, _backup_files(folder)))

    def raw_backup_dirs(self) -> list[Path]:
        return _existing(self.raw_backup_dir(sid) for sid in self.servers)

    def copy_folder_of(self, sid: str) -> Path | None:
        """The server's backup copy folder (``[backups] copy_to``), if it has one."""
        b = self.configs[sid].get("backups")
        text = str(b.get("copy_to") or "").strip() if isinstance(b, dict) else ""
        folder = Path(text).expanduser() if text else None
        return folder if folder is not None and folder.is_absolute() else None

    def copies_of(self, sid: str) -> list[Path]:
        """The server's own folders in its backup copy folder: only those whose mark says they're that
        server's (backup.copy_out), never the copy folder itself. (Found through a link too: what's
        behind one is then listed for the person, not deleted.)"""
        from . import backup
        folder = self.copy_folder_of(sid)
        try:
            entries = sorted(folder.iterdir()) if folder is not None and folder.is_dir() else []
        except OSError:
            entries = []
        me, out = backup.copy_owner(self.servers[sid]), []
        for entry in entries:
            try:
                if entry.is_dir() and (entry / backup.COPY_OWNER).read_text(encoding="utf-8").strip() == me:
                    out.append(entry)
            except (OSError, UnicodeDecodeError):
                continue
        return _existing(out)

    def backups_of(self, sid: str) -> list[Path]:
        return _existing([*self.backup_dir_of(sid), *self.copies_of(sid)])

    def backup_dirs(self) -> list[Path]:
        return _existing(p for sid in self.servers for p in self.backup_dir_of(sid))

    def copy_dirs(self) -> list[Path]:
        return _existing(p for sid in self.servers for p in self.copies_of(sid))

    def key_file(self) -> Path:
        return self.state_dir / lockbox.KEY_FILE


def _existing(paths: Iterable[Path]) -> list[Path]:
    """The ones that are there, each once."""
    out: list[Path] = []
    for p in paths:
        if os.path.lexists(p) and not any(_lex(p) == _lex(q) for q in out):
            out.append(p)
    return out


def _whole_or_each(folder: Path | None, members: list[Path], empty_too: bool = False) -> list[Path]:
    """``[folder]`` when it holds only ``members`` and its README (an empty one only when
    ``empty_too``: Craft Conductor's own default place), else ``members`` themselves: a folder the
    person chose may hold things of theirs too (their Documents folder, say)."""
    if folder is None or not _plain_dir(folder):
        return members
    try:
        entries = list(folder.iterdir())
    except OSError:
        return members
    if not entries and not empty_too:
        return members
    if all(e.name == README or any(_lex(e) == _lex(m) for m in members) for e in entries):
        return [folder, *(m for m in members if not _lex_inside(m, folder))]
    return members


def _carve(paths: Iterable[Path], keep: list[Path], home: Path) -> list[Path]:
    """``paths`` without what's kept: a path holding a kept one is replaced by its entries (again
    around the kept one), and a kept path itself is left out. A path that's never deleted (a drive
    root, the home folder, a system folder) is never opened up either: it stays as it is, and is
    refused when its turn comes."""
    out: list[Path] = []
    for p in paths:
        if any(_same(p, k) for k in keep):
            continue
        if _dangerous(p, home) or not any(locations.inside(k, p) for k in keep):
            out.append(p)
        elif _plain_dir(p):
            try:
                entries = sorted(p.iterdir())
            except OSError:
                continue  # (can't be opened up: kept whole)
            out += _carve(entries, keep, home)
    return out


def _found(home: Path) -> tuple[dict, dict, dict[str, Path]]:
    """hub.json, the places, and the servers Craft Conductor manages in this home (by id)."""
    from . import hub as hubmod  # (heavy: only when planning)
    data = hubmod.read_hub_file(home / configmod.STATE_DIR)
    places = locations.read(data, home)
    return data, places, hubmod.discover_servers(home, data, places["servers"])


def servers_of(home: Path) -> dict[str, Path]:
    """The servers ``plan(home, ...)`` sees, by id: their folders are what ``stop_servers`` returns
    for the ones still running."""
    return _found(Path(home))[2]


def game_dir(root: Path) -> Path:
    """A server's own server folder (``[server] dir`` in its craft-conductor.toml, read only)."""
    return _table_dir(root, _server_toml(root), "server", "server")


def _inventory(home: Path, choices: Choices, env: Mapping[str, str], runner: Runner | None) -> Inventory:
    state_dir = home / configmod.STATE_DIR
    data, places, servers = _found(home)
    inv = Inventory(home=home, state_dir=state_dir, user_home=_user_home(env), choices=choices, env=env, runner=runner,
                    hub=data, places=places, servers=servers, configs={sid: _server_toml(r) for sid, r in servers.items()})
    # (never taken with a folder around them: a server folder added from elsewhere, which may hold the
    # person's own files, and a server's server folder outside its folder, which may be their Documents)
    inv.keep += [*inv.added_roots(), *(p for sid in servers for p in inv.outside_of(sid))]
    if not choices.servers:
        inv.keep += [places["servers"], *inv.server_pieces()]
    if not choices.backups:
        inv.keep += [*([places["backups"]] if places["backups"] else []), *inv.raw_backup_dirs(), *inv.backup_dirs(),
                     *inv.copy_dirs()]
    if not choices.exports:
        inv.keep.append(places["exports"])
    if choices.keep_lockbox_key:
        inv.keep.append(inv.key_file())
    return inv


# ------------------------------------------------------------------ the parts
def _place_part(inv: Inventory, key: str, label: str, ticked: bool, paths: list[Path], known: list[Path],
                deleted: str, kept: str, per_server: dict[Path, list[Path]] | None = None,
                notes: list[str] | None = None, emptied: list[Path] | None = None) -> Part:
    """A part made of folders in places (servers, backups, exports). Ticked: what's kept is carved
    out, and nothing is deleted through a link or junction (R10): it's listed for the person, with
    ``notes`` (what else is left for them); ``emptied``: folders removed afterwards if that left them empty."""
    present = bool(paths)
    known = [k for k in known if k is not None]
    manual = None
    if ticked:
        carved, paths, links = _carve(paths, inv.keep, inv.user_home), [], []
        for p in carved:
            link = link_on_the_way(p, known)
            if link is None:
                paths.append(p)
            elif not any(_lex(link) == _lex(x) for x in links):
                links.append(link)
        if links:
            these = ", ".join(str(x) for x in links)
            one = len(links) == 1
            manual = (f"{label}: {these} {'is a link or junction' if one else 'are links or junctions'}, so nothing was "
                      f"deleted through {'it' if one else 'them'}; delete what's in {'it' if one else 'them'} yourself "
                      "if you don't want it any more")
            deleted += " (not what's behind a link or junction: see what's left for you to do)"
        if present and notes:
            manual = "; ".join([manual, *notes] if manual else [f"{label}: {notes[0]}", *notes[1:]])
    home = inv.user_home
    guards = {root: [p for p in pieces if not _dangerous(p, home)] for root, pieces in (per_server or {}).items()}
    return Part(key=key, label=label, present=present, action=(deleted if ticked else kept) if present else "nothing here",
                paths=paths, manual=manual, kept=present and not ticked,
                known=[k for k in known if not _dangerous(k, home)], user_home=home, per_server=guards,
                emptied=[e for e in (emptied or []) if ticked and present and not _dangerous(e, home)])


def _export_members(folder: Path) -> list[Path]:
    """What in the exports folder is Craft Conductor's (as hub._exports_plan moves them): each
    server's folder of exports, and exports kept at the top."""
    try:
        entries = sorted(folder.iterdir()) if folder.is_dir() else []
    except OSError:
        return []
    out = []
    for x in entries:
        try:
            if (x.is_dir() and any(x.glob("*.craft-conductor.zip"))) or (
                    x.name.endswith(".craft-conductor.zip") and not x.is_dir()):
                out.append(x)
        except OSError:
            continue
    return out


def _exports_part(inv: Inventory) -> Part:
    folder = inv.places["exports"]
    members = _export_members(folder)
    paths = _existing(_whole_or_each(folder, members, empty_too=_lex(folder) == _lex(locations.defaults(inv.home)["exports"])))
    whole = len(paths) == 1 and _lex(paths[0]) == _lex(folder)
    return _place_part(inv, "exports", "Exports", inv.choices.exports, paths, [folder],
                       "deleted: the exports folder and every export in it" if whole
                       else f"deleted: every export in {folder} (your other files there stay)",
                       f"kept in {folder}")


def _backups_part(inv: Inventory) -> Part:
    dirs, copies, folder = inv.backup_dirs(), inv.copy_dirs(), inv.places["backups"]
    paths = _existing(_whole_or_each(folder, dirs) + copies)
    where = ", ".join(str(p) for p in paths) or "-"
    copies_too = " (and their copies in the backup copy folder)" if copies else ""
    copy_folders = [f for sid in inv.servers if (f := inv.copy_folder_of(sid)) is not None]
    return _place_part(inv, "backups", "Backups", inv.choices.backups, paths,
                       [*inv.raw_backup_dirs(), *dirs, *copies, *copy_folders, folder],
                       f"deleted: every server's backups{copies_too} (your other files in a backups folder stay)",
                       f"kept in {where}", {root: inv.backups_of(sid) for sid, root in inv.servers.items()})


def _servers_part(inv: Inventory) -> Part:
    folder, pieces = inv.places["servers"], inv.server_pieces()
    paths = _existing(_whole_or_each(folder, pieces, empty_too=_lex(folder) == _lex(locations.defaults(inv.home)["servers"])))
    n = len(inv.servers)
    added = inv.added_roots()
    notes = [f"{game} is the server folder of the server in {root} but isn't inside that server's own folder, so it "
             "wasn't deleted (it may hold your own files); delete it yourself if you don't want it"
             for sid, root in inv.servers.items() for game in inv.outside_of(sid)]
    deleted = f"deleted: {n} server{'s' if n != 1 else ''} and their worlds"
    if added or any(_same(r, inv.home) for r in inv.servers.values()):
        deleted += (" (in a server folder Craft Conductor didn't make, only its own files: your other files there "
                    "stay)")
    return _place_part(inv, "servers", "Servers and worlds", inv.choices.servers, paths,
                       [folder, *inv.servers.values(), *pieces], deleted,
                       f"kept in {', '.join(str(p) for p in paths) or '-'}",
                       {root: inv.pieces_of(sid) for sid, root in inv.servers.items()}, notes=notes, emptied=added)


def _lockbox_part(inv: Inventory) -> Part:
    key = inv.key_file()
    present = os.path.lexists(key)
    keep = inv.choices.keep_lockbox_key
    return Part(key="lockbox", label="Backup lock key", present=present,
                action=("nothing here" if not present else
                        f"kept in {key}, so Craft Conductor installed here again can open your kept backups' locked parts" if keep
                        else "deleted: the locked parts of backups you keep (passwords, keys, IP bans, logs) won't open "
                             "anywhere afterwards; the rest of each backup still restores"),
                paths=[key] if present else [], kept=present and keep, known=[key], user_home=inv.user_home)


def _state_part(inv: Inventory) -> Part:
    state = inv.state_dir
    present = os.path.lexists(state)
    extras = []
    if (state / "java").is_dir():
        extras.append("the shared Java")
    if any((state / "tools" / n).exists() for n in ("cloudflared", "cloudflared.exe")):
        extras.append("the downloaded cloudflared")
    what = "Craft Conductor's settings (hub.json), passwords and sessions, phones, passkeys, people, logs and caches"
    if extras:
        what += ", " + ", ".join(extras)
    if inv.choices.keep_lockbox_key:
        what += " (not the backup lock key)"
    return Part(key="state", label="Settings and state", present=present,
                action=f"deleted: {what}" if present else "nothing here",
                paths=_carve([state], inv.keep, inv.user_home) if present else [], known=[state], user_home=inv.user_home)


def _java_part(inv: Inventory) -> Part:
    """Windows: the shared Java Craft Conductor downloaded into ProgramData for this account (java.py's
    ``_plain_store``, when its own folder's name had letters Java can't use). Only that exact folder, and
    only when it's a plain folder this account owns: never another account's of that name, never one
    found by a pattern. Read only (private.own_folder would make it, and change its permissions)."""
    label = "Shared Java"
    if _system() != "windows":
        return _absent("java", label, inv)
    from . import private
    try:
        me = private.account_sid()
        folder = Path(_env(inv.env, "ProgramData") or PROGRAM_DATA) / f"craft-conductor-java-{me}"
        mine = bool(me) and _plain_dir(folder) and private._owner_sid(str(folder)) == me
    except Exception:  # (this account or the folder's owner can't be told: it isn't taken as this account's)
        mine = False
    if not mine:
        return _absent("java", label, inv)
    return Part(key="java", label=label, present=True,
                action=f"deleted: the Java Craft Conductor downloaded for this account ({folder})", paths=[folder],
                known=[folder], user_home=inv.user_home, system_ok=[folder],
                per_server={root: [folder] for root in inv.servers.values()})  # (a server still running may use it)


def _windows_delete_later(exe: Path, env: Mapping[str, str]) -> list[str] | None:
    """The command that deletes the Windows program once it has closed (a running program can't delete
    itself, and Windows refuses to delete a program file while any process runs it): a cmd started
    without a window tries to delete it every 2 seconds for up to 10 minutes, and stops as soon as it's
    gone. Trying the file, not waiting for a process id: a one-file build's file is held by its
    bootloader (this process's parent), and the control panel's exit can take minutes (a server that
    doesn't stop is given its stop time). Then the leftovers of an update. None when cmd would change
    the paths (a % in them)."""
    from . import selfupdate
    system32 = PureWindowsPath(_env(env, "SystemRoot") or r"C:\Windows") / "System32"
    files = [exe, *(p for p in (selfupdate.old_binary(exe), selfupdate.failed_binary(exe)) if p.is_file())]
    if any(c in str(p) for p in (system32, *files) for c in '%"') or " " in str(system32):
        return None
    tries = (f'(for /l %i in (1,1,{DELETE_TRIES}) do @if exist "{exe}" (del /f /q "{exe}" >nul 2>&1 & '
             f'if exist "{exe}" {system32}\\PING.EXE -n 3 127.0.0.1 >nul))')
    targets = " ".join(f'"{p}"' for p in files)
    return [str(system32 / "cmd.exe"), "/d", "/s", "/c", f'"{tries} & del /f /q {targets} >nul 2>&1"']


DELETE_TRIES = 300  # (every 2 seconds: 10 minutes)


def _program_part(inv: Inventory) -> Part:
    label = "The program"
    base = dict(key="program", label=label, present=True, user_home=inv.user_home)
    if _env(inv.env, "CRAFT_CONDUCTOR_CONTAINER"):
        return Part(**base, action="listed: it runs in Docker, which this can't remove from inside",
                    manual="On the computer running Docker: docker rm -f craft-conductor, then "
                           "docker rmi ghcr.io/silverwrx03/craft-conductor (and docker volume rm for its /data volume, "
                           "if you don't want to keep it)")
    if not _frozen():
        pipx = any(part.lower() == "pipx" for part in Path(_prefix()).parts)
        command = "pipx uninstall craft-conductor" if pipx else "python -m pip uninstall craft-conductor"
        return Part(**base, action="listed: it was installed with " + ("pipx" if pipx else "pip"),
                    manual=f"Remove the program: {command}")
    exe = Path(_executable())
    if _system() != "windows":
        return Part(**base, action=f"deleted: {exe}", paths=[exe], known=[exe])
    argv = _windows_delete_later(exe, inv.env)
    if argv is None:
        return Part(**base, action=f"listed: delete {exe} yourself once Craft Conductor has closed",
                    manual=f"Delete {exe} once Craft Conductor has closed")

    def remove(runner: Runner) -> Outcome:
        why = refusal(exe, inv.user_home, [exe])
        if why:
            return Outcome(failed=[f"{label}: {exe} wasn't deleted ({why})"])
        code = runner.run(argv, detached=True)
        if code != 0:
            return Outcome(failed=[f"{label}: the command to delete {exe} didn't start (error {code})"],
                           manual=[f"Delete {exe} once Craft Conductor has closed"])
        return Outcome(removed=[f"{label}: {exe} is deleted once Craft Conductor has closed"],
                       manual=[f"{label}: if {exe} is still there 10 minutes after Craft Conductor has closed, "
                               "delete it yourself"])
    return Part(**base, action=f"deleted once Craft Conductor has closed: {exe}", paths=[exe], known=[exe],
                remove=remove)


# ------------------------------------------------------------------ the system parts
def _ask(inv: Inventory, question: str, *args, default=None):
    """The runner's answer to something only the computer can tell (it changes nothing); ``default``
    when there's no runner, it can't answer, or answering failed."""
    fn = getattr(inv.runner, question, None)
    if not callable(fn):
        return default
    try:
        return fn(*args)
    except Exception:  # (can't tell: the cautious default)
        return default


def _absent(key: str, label: str, inv: Inventory) -> Part:
    return Part(key=key, label=label, present=False, action="nothing here", user_home=inv.user_home)


def _tailscale_part(inv: Inventory) -> Part:
    from . import tailscale
    label = "Tailscale Serve"
    tunnels = inv.hub.get("tunnels")
    saved = tunnels.get("tailscale") if isinstance(tunnels, dict) else None
    exe = tailscale.exe() if isinstance(saved, dict) else None
    if not exe:
        return _absent("tunnels", label, inv)  # (never set up, or Tailscale isn't installed any more)
    funnel = bool(saved.get("funnel"))
    *first, last = tailscale.unserve_commands(funnel)
    by_hand = "; ".join("tailscale " + " ".join(args) for args in (*first, last))
    where = "your devices and the internet (Funnel)" if funnel else "your devices on Tailscale"

    def remove(runner: Runner) -> Outcome:
        for args in first:
            runner.run([exe, *args])
        code = runner.run([exe, *last])
        if code != 0:
            return Outcome(failed=[f"{label}: Tailscale didn't switch it off (error {code})"],
                           manual=[f"Switch off Tailscale Serve: {by_hand}"])
        return Outcome(removed=[f"{label}: switched off the control panel's address for {where}"])
    return Part(key="tunnels", label=label, present=True,
                action=f"switched off: the control panel's address for {where} (the Tailscale app itself stays)",
                user_home=inv.user_home, remove=remove)


def _cloudflare_part(inv: Inventory) -> Part:
    from . import tunnels
    label = "Cloudflare quick tunnel"
    found = tunnels.recorded_cloudflared(inv.state_dir / "tools")
    if found is None:
        return _absent("tunnels", label, inv)
    pid, exe = found
    by_hand = f"If cloudflared (process {pid}) is still running, end it (Windows: Task Manager; elsewhere: kill {pid})"

    def remove(runner: Runner) -> Outcome:
        stop = getattr(runner, "stop_process", None)
        if not callable(stop):
            return Outcome(manual=[by_hand])
        if stop(pid, exe):
            return Outcome(removed=[f"{label}: stopped (the control panel is off the internet)"])
        return Outcome()  # (it had closed already)
    return Part(key="tunnels", label=label, present=True,
                action="stopped, if it's still running (the downloaded cloudflared goes with the settings)",
                user_home=inv.user_home, remove=remove)


def _tunnels_parts(inv: Inventory) -> list[Part]:
    return [_tailscale_part(inv), _cloudflare_part(inv)]


def _recorded_mappings(inv: Inventory) -> list[tuple[int, str]]:
    """The port mappings Craft Conductor made on the router, as hub.json recorded them (``upnp.mapped``)."""
    u = inv.hub.get("upnp")
    mapped = u.get("mapped") if isinstance(u, dict) else None
    out: list[tuple[int, str]] = []
    for x in mapped if isinstance(mapped, list) else []:
        if (isinstance(x, list) and len(x) == 2 and type(x[0]) is int and 1 <= x[0] <= 65535
                and x[1] in ("TCP", "UDP") and (x[0], x[1]) not in out):
            out.append((x[0], x[1]))
    return out


def _ports(ports: Iterable[tuple]) -> str:
    return ", ".join(f"{p[1]} {p[0]}" for p in ports)


def _router_part(inv: Inventory) -> Part:
    label = "Router port forwarding"
    mapped = _recorded_mappings(inv)
    if not mapped:
        return _absent("router", label, inv)

    def left(ports: list[tuple], why: str) -> str:
        return (f"{label}: your router may still forward {_ports(ports)} to this computer ({why}); remove "
                f"{'it' if len(ports) == 1 else 'them'} in the router's settings (port forwarding, or UPnP)")

    def remove(runner: Runner) -> Outcome:
        ask = getattr(runner, "router_remove", None)
        if not callable(ask):
            return Outcome(manual=[left(mapped, "the router wasn't asked")])
        try:
            refused = list(ask(mapped))
        except Exception as e:  # (no router answered, or the network failed)
            return Outcome(manual=[left(mapped, str(e) or "no router answered")])
        no = {(r[0], r[1]) for r in refused}
        out = Outcome()
        done = [m for m in mapped if m not in no]
        if done:
            out.removed.append(f"{label}: took back {_ports(done)}")
        if refused:
            why = "; ".join(sorted({str(r[2]) for r in refused if len(r) > 2 and r[2]})) or "the router refused"
            out.manual.append(left(refused, why))
        return out
    return Part(key="router", label=label, present=True,
                action=f"taken back through the router (UPnP): {_ports(mapped)}", user_home=inv.user_home, remove=remove)


FIREWALL_BY_HAND = ("run `craft-conductor firewall remove` while Craft Conductor is still installed, or later, in "
                    "PowerShell as administrator: Remove-NetFirewallRule -Group 'Craft Conductor'")


def _firewall_part(inv: Inventory) -> Part:
    from . import firewall
    label = "Windows Firewall rules"
    if _system() != "windows":
        return _absent("firewall", label, inv)
    rules = _ask(inv, "firewall_rules")
    if isinstance(rules, list) and not rules:
        return _absent("firewall", label, inv)
    names = [str(r) for r in rules] if isinstance(rules, list) else None
    script = firewall.remove_script(names) if names else firewall.remove_group_script()
    argv = ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand",
            base64.b64encode(script.encode("utf-16-le")).decode("ascii")]
    what = ", ".join(names) if names else 'Craft Conductor\'s rules (the group "Craft Conductor"), if there are any'

    def remove(runner: Runner) -> Outcome:
        try:
            code = runner.run(argv, elevated=True)
        except Exception as e:
            return Outcome(failed=[f"{label}: {e}"], manual=[f"{label}: {FIREWALL_BY_HAND}"])
        if code == DECLINED:
            return Outcome(manual=[f"{label}: still there (Windows' administrator prompt was answered No): "
                                   f"{FIREWALL_BY_HAND}"])
        if code != 0:
            return Outcome(failed=[f"{label}: Windows couldn't remove them (error {code})"],
                           manual=[f"{label}: {FIREWALL_BY_HAND}"])
        return Outcome(removed=[f"{label}: removed {what}"])
    return Part(key="firewall", label=label, present=True,
                action=f"removed, with one Windows administrator prompt: {what}", user_home=inv.user_home, remove=remove)


def _euid() -> int:
    return getattr(os, "geteuid", lambda: -1)()


def subprocess_runner(runner: Runner) -> Callable[..., subprocess.CompletedProcess]:
    """``runner`` shaped like ``subprocess.run``, for service.py (ruling R1): the exit code only."""
    def run(args, **_ignored) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(list(args), runner.run(list(args)), "", "")
    return run


def _our_unit(p) -> bool:
    """The unit file is there and is this home's (its folder, and for the panel its home): a unit of the
    same name for another folder is someone else's."""
    try:
        if not p.path.is_file():
            return False
        have = set(p.path.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeDecodeError):
        return False
    need = [x for x in p.text.splitlines() if x.startswith(("WorkingDirectory=", "Environment=CRAFT_CONDUCTOR_HOME="))]
    return bool(need) and all(x in have for x in need)


def _other_units(folder: Path, ours: set[str]) -> bool:
    """Another unit is in the person's systemd user folder (or it can't be told), so lingering stays."""
    try:
        for entry in folder.iterdir():
            if entry.name in ours:
                continue
            if entry.is_dir():
                if entry.name.endswith((".wants", ".requires")) and any(x.name not in ours for x in entry.iterdir()):
                    return True
            elif entry.suffix in (".service", ".timer", ".socket", ".path", ".target", ".mount"):
                return True
    except OSError:
        return True
    return False


def _service_part(inv: Inventory) -> Part:
    from . import service
    label = "Background service"
    if _system() != "linux":
        return _absent("service", label, inv)
    units, seen = [], set()
    for root, panel in [*((r, False) for r in inv.servers.values()), (inv.home, True)]:  # (the panel last)
        for system in (False, True):
            try:
                p = service.plan(root, system, panel=panel)
            except Exception:
                continue
            if _lex(p.path) not in seen and _our_unit(p):
                seen.add(_lex(p.path))
                units.append((root, panel, p))
    if not units:
        return _absent("service", label, inv)
    root_now = _euid() == 0
    own = _ask(inv, "own_unit", default=None)  # (R15: this process runs as one of them)
    user = _env(inv.env, "USER") or _env(inv.env, "LOGNAME")
    if not user:
        import getpass
        user = getpass.getuser()

    def by_hand(p) -> str:
        return (f"{label}: {p.name} is a system service, which only root can remove: sudo systemctl disable --now "
                f"{p.name} && sudo rm {p.path} && sudo systemctl daemon-reload")

    def remove(runner: Runner) -> Outcome:
        out, gone, inside = Outcome(), [], False
        for root, panel, p in units:
            if p.system and not root_now:
                out.manual.append(by_hand(p))
                continue
            itself = panel and own == p.name  # (stopping it now would stop this uninstall half-way)
            try:
                service.uninstall(root, subprocess_runner(_without_stopping(runner) if itself else runner),
                                  system=p.system, panel=panel)
            except Exception as e:
                out.failed.append(f"{label}: {p.name} couldn't be removed ({getattr(e, 'strerror', None) or e})")
                if p.system:
                    out.manual.append(by_hand(p))
                continue
            out.removed.append(f"{label}: removed {p.name} ({p.path})" + (
                "; it stops when Craft Conductor closes, at the end of this" if itself else ""))
            inside = inside or (itself and not p.system)
            if not p.system:
                gone.append(p)
        if gone and (LINGER / user).exists() and not _other_units(gone[0].path.parent, {p.name for p in gone}):
            if inside:  # (switching lingering off can end this account's services at once: this one too)
                out.manual.append(f"{label}: lingering is still on for {user}; nothing of Craft Conductor's needs it any "
                                  f"more: loginctl disable-linger {user}")
            elif runner.run(["loginctl", "disable-linger", user]) == 0:
                out.removed.append(f"{label}: switched off lingering for {user} (nothing else of yours needed it)")
            else:
                out.manual.append(f"{label}: lingering is still on for {user}; if nothing else needs it: "
                                  f"sudo loginctl disable-linger {user}")
        return out
    names = ", ".join(p.name for _, _, p in units)
    needs_root = [p.name for _, _, p in units if p.system and not root_now]
    action = f"removed: {names}; lingering is switched off too unless other services of yours use it"
    if needs_root:
        action += f" (listed for you: {', '.join(needs_root)} needs root)"
    return Part(key="service", label=label, present=True, action=action, user_home=inv.user_home, remove=remove)


def _without_stopping(runner: Runner) -> Runner:
    """``runner``, with `systemctl disable --now` made a plain `disable` (R15): for the control panel's
    own unit while it runs this uninstall. The rest goes through as it is."""
    class Disable:
        def __getattr__(self, name):
            return getattr(runner, name)

        def run(self, argv, **kw):
            if "disable" in argv and "--now" in argv:
                argv = [a for a in argv if a != "--now"]
            return runner.run(argv, **kw)
    return Disable()  # type: ignore[return-value]


def _invite_part(inv: Inventory) -> Part:
    from . import urlhandler
    label = "Invite link handler"
    system = _system()
    if system == "windows":
        present = bool(_ask(inv, "registry_has", urlhandler.REGISTRY_KEY, default=True))
        where = urlhandler.REGISTRY_KEY
    elif system == "linux":
        entry = urlhandler.desktop_file(inv.env)
        present = os.path.lexists(entry)
        where = str(entry)
    else:
        present = False  # (macOS: there isn't one)
    if not present:
        return _absent("invite", label, inv)

    def remove(runner: Runner) -> Outcome:
        if system == "linux" and (why := refusal(entry, inv.user_home, [entry])):
            return Outcome(failed=[f"{label}: {entry} wasn't deleted ({why})"])
        done = urlhandler.unregister(runner, system=system, env=inv.env)
        return Outcome(removed=[f"{label}: {done}"] if done else [])
    return Part(key="invite", label=label, present=True,
                action=f"removed: craft-conductor:// links stop opening Craft Conductor ({where})",
                user_home=inv.user_home, remove=remove)


# ------------------------------------------------------------------ games in launchers
# How Craft Conductor records what it sets up in a launcher (join.py, launchers.py). Play on this
# computer and single-player games go through the same page as a friend joining a server, so they're
# recorded the same way, in the launchers' own folders:
# * the Minecraft Launcher: an installation keyed "craft-conductor-<name>" in launcher_profiles.json
#   (and the Microsoft Store launcher's file), whose game folder is <.minecraft>/craft-conductor/<name>
#   with Craft Conductor's record of the files it put there (join.MANIFEST), and its own version,
#   versions/craft-conductor-<name>. Its notes are in that craft-conductor folder too: servers.json,
#   invites.json, join-running.json, the friend's extras, a Java of its own;
# * Prism Launcher: the instance "craft-conductor-<name>" in Prism's instances folder, with that
#   record in its .minecraft folder;
# * the Modrinth App and CurseForge: only a modpack file to import; the app makes the profile itself,
#   so there's no record of it, and it's listed for the person.
# Anything else (named like Craft Conductor's but not as it made it, or from before the rename) is
# listed for the person, never guessed.
GAME_PREFIX = "craft-conductor-"
OLD_PREFIX = "mcsm-"  # (Craft Conductor's name before 2026-10-01: those setups aren't recorded the same way)
GAME_NOTES = ("servers.json", "invites.json", "join-running.json", "extras", ".craft-conductor")
PROFILE_BACKUP = ".craft-conductor-backup"  # (join.write_profiles' copy of the launcher's file)
LAUNCHER_PROCESSES = {  # (a launcher's program, as the process list names it, lower case; a wrong yes only lists)
    # (minecraft.exe: the Microsoft Store edition may run under that name; Bedrock's is Minecraft.Windows.exe)
    "minecraft": ("minecraftlauncher.exe", "minecraft.exe", "minecraft-launc", "minecraft.app/contents/macos/"),
    "prism": ("prismlauncher", "prism launcher.app/contents/macos/"),
}


@dataclass
class _Games:
    """What one launcher holds of Craft Conductor's games."""
    names: list[str] = field(default_factory=list)       # the recorded games, by name
    paths: list[Path] = field(default_factory=list)      # what's deleted with them
    known: list[Path] = field(default_factory=list)      # the places those are in
    keep: list[Path] = field(default_factory=list)       # the recorded games' folders (kept unless ticked)
    listed: list[str] = field(default_factory=list)      # for the person: unrecorded, unclear, or older
    worlds: int = 0
    # the launcher's file -> Craft Conductor's installations in it (key -> (their game folder as written, name))
    edits: dict[Path, dict[str, tuple[str, str]]] = field(default_factory=dict)
    held: dict[str, list[Path]] = field(default_factory=dict)  # key -> what goes only once it's out of the file
    backups: list[Path] = field(default_factory=list)


def _in(path: str, folder: Path, exact: bool = False) -> bool:
    """``path`` (as a launcher's file wrote it) is ``folder`` (``exact``) or inside it; a path that
    isn't one (a NUL in it, say) is neither."""
    try:
        return _lex(path) == _lex(folder) if exact else _lex_inside(path, folder)
    except (ValueError, OSError):
        return False


def _names(names: Iterable[str]) -> str:
    quoted = [f'"{n}"' for n in dict.fromkeys(names)]
    return quoted[0] if len(quoted) == 1 else ", ".join(quoted[:-1]) + " and " + quoted[-1] if quoted else ""


def _marked(game: Path) -> bool:
    """Craft Conductor made this game folder: its record of the files it put there is in it."""
    from .join import MANIFEST
    return _plain_dir(game) and (game / MANIFEST).is_file()


def _worlds(game: Path) -> int:
    try:
        return sum(1 for e in (game / "saves").iterdir() if e.is_dir())
    except OSError:
        return 0


def _entries(folder: Path) -> list[Path]:
    try:
        return sorted(folder.iterdir()) if folder.is_dir() else []
    except OSError:
        return []


def _our_version(folder: Path) -> bool:
    """A version Craft Conductor wrote (join.write_version): its json names it."""
    try:
        data = json.loads((folder / f"{folder.name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return _plain_dir(folder) and isinstance(data, dict) and data.get("id") == folder.name


def _not_through_links(found: _Games) -> None:
    """Nothing is deleted through a link or junction (R10): such a path is listed for the person."""
    ok = []
    for p in found.paths:
        link = link_on_the_way(p, found.known)
        if link is None:
            ok.append(p)
        else:
            found.listed.append(f"{p} is reached through a link or junction ({link}), so it wasn't deleted; "
                                "delete it yourself if you don't want it")
    found.paths = ok


def _minecraft_games(mc: Path) -> _Games:
    """Craft Conductor's installations in the Minecraft Launcher (``mc``: its folder), as recorded."""
    from .join import PROFILE_FILES, _SLUG
    found = _Games()
    ours, versions = mc / "craft-conductor", mc / "versions"
    files: dict[Path, dict[str, dict]] = {}
    unreadable = False
    for name in PROFILE_FILES:
        f = mc / name
        if not os.path.lexists(f):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            profiles = data.get("profiles") if isinstance(data, dict) else None
            if not isinstance(profiles, dict):
                raise ValueError("it has no list of installations")
        except (OSError, ValueError) as e:
            unreadable = True
            found.listed.append(f"{f} couldn't be read ({getattr(e, 'strerror', None) or e}), so it wasn't changed and "
                                f"the games in {ours} stay; delete Craft Conductor's installations (named after its "
                                "servers and games) in the launcher yourself if you don't want them")
            continue
        files[f] = {k: v for k, v in profiles.items() if isinstance(v, dict)}
        if os.path.lexists(backup := f.with_name(f.name + PROFILE_BACKUP)):
            found.backups.append(backup)
    recorded: set[str] = set()
    staying: list[tuple[str, str]] = []           # (name, game folder) of every installation that stays
    staying_versions: dict[str, list[str]] = {}   # version -> the installations that stay using it
    old: list[str] = []
    for f, profiles in files.items():
        for key, p in profiles.items():
            game_dir, name = p.get("gameDir"), str(p.get("name") or key)
            slug = key[len(GAME_PREFIX):] if key.startswith(GAME_PREFIX) else None
            if (slug is not None and _SLUG.fullmatch(slug) and isinstance(game_dir, str) and _in(game_dir, ours / slug, exact=True)
                    and (not os.path.lexists(ours / slug) or _marked(ours / slug))):
                found.edits.setdefault(f, {})[key] = (game_dir, name)
                found.held[key] = [ours / slug, versions / key, *found.backups]
                found.names.append(name)
                recorded.add(slug)
                continue
            if slug is not None:
                found.listed.append(f'the installation "{name}" ({key}) doesn\'t use the folder Craft Conductor made for it '
                                    f"({game_dir or 'it uses the launcher folder itself'}), so it stays; delete it in the "
                                    "launcher yourself if you don't want it")
            elif key.startswith(OLD_PREFIX):
                old.append(name)
            if isinstance(game_dir, str) and game_dir:
                staying.append((name, game_dir))
            if isinstance(p.get("lastVersionId"), str):
                staying_versions.setdefault(p["lastVersionId"], []).append(name)
    named = {k[len(GAME_PREFIX):] for profiles in files.values() for k in profiles if k.startswith(GAME_PREFIX)}

    def ours_to_delete(slug: str) -> bool:
        """Recorded, or Craft Conductor's own with no installation left that could be using it."""
        return slug in recorded or (slug not in named and not unreadable)

    members = []
    for e in _entries(ours):
        if e.name in GAME_NOTES:
            members.append(e)
        elif not _marked(e):
            found.listed.append(f"{e} isn't something Craft Conductor has a record of making, so it stays")
        elif ours_to_delete(e.name):
            users = [n for n, d in staying if _in(d, e)]
            if users:
                found.listed.append(f"{e} is also the game folder of the installation {_names(users)}, so it stays "
                                    "with its worlds")
                continue
            members.append(e)
            found.keep.append(e)
            found.worlds += _worlds(e)
            if e.name not in recorded:
                found.names.append(e.name)  # (its installation was removed already)
    found.paths += _whole_or_each(ours, members, empty_too=True)
    for e in _entries(versions):
        if e.name.startswith(OLD_PREFIX) and _plain_dir(e):
            old.append(f"versions/{e.name}")
        if not e.name.startswith(GAME_PREFIX) or not _our_version(e) or not ours_to_delete(e.name[len(GAME_PREFIX):]):
            continue
        if users := staying_versions.get(e.name):
            if e.name[len(GAME_PREFIX):] in recorded:
                found.listed.append(f"{e} is also used by the installation {_names(users)}, so it stays")
            continue
        found.paths.append(e)
    found.paths += found.backups
    if os.path.lexists(mc / "mcsm"):
        old.append(str(mc / "mcsm"))
    if old:
        found.listed.append(f"older setups from before Craft Conductor's rename ({_names(old)}) weren't recorded the way "
                            "today's are, so they stay; delete them in the launcher (and their folders) yourself if you "
                            "don't want them")
    found.known = [ours, versions, *found.backups]
    _not_through_links(found)
    return found


def _drop_profiles(f: Path, keys: dict[str, tuple[str, str]], runner: Runner) -> tuple[list[str], list[str], list[str], list[str]]:
    """Take Craft Conductor's installations ``keys`` (key -> (game folder, name) as planned) out of the launcher's
    file ``f``: only those still as planned; everything else in it stays as it was. Written whole, the way
    join.py wrote them in (a temporary file, then a swap), through the runner. Returns (the names
    removed, the keys left in, failure lines, lines for the person)."""
    by_hand = (f"delete the installations {_names(n for _, n in keys.values())} in the launcher yourself (their "
               "folders were kept)")
    try:
        if folders.link_stat(os.lstat(f)):
            raise ValueError("it's a link, so what it leads to isn't changed")
        data = json.loads(f.read_text(encoding="utf-8"))
        profiles = data.get("profiles") if isinstance(data, dict) else None
        if not isinstance(profiles, dict):
            raise ValueError("it has no list of installations")
    except FileNotFoundError:
        return [], [], [], []  # (gone, with everything in it)
    except (OSError, ValueError) as e:
        why = getattr(e, "strerror", None) or e
        return [], list(keys), [f"{f} couldn't be read ({why})"], [by_hand]
    gone, left, later = [], [], []
    for key, (game_dir, _name) in keys.items():
        p = profiles.get(key)
        if p is None:
            continue  # (removed already)
        name = str(p.get("name") or key) if isinstance(p, dict) else key
        if not isinstance(p, dict) or p.get("gameDir") != game_dir:
            left.append(key)
            later.append(f'the installation "{name}" changed after the list was made, so it stays; delete it in the '
                         "launcher yourself if you don't want it")
            continue
        gone.append(name)
        del profiles[key]
    if not gone:
        return [], left, [], later
    write = getattr(runner, "write_text", None)
    if not callable(write):
        return [], list(keys), [], [*later, f"{f} can't be changed from here", by_hand]
    try:
        write(f, json.dumps(data, indent=2) + "\n")
    except Exception as e:
        return [], list(keys), [f"{f} couldn't be written ({getattr(e, 'strerror', None) or e})"], [*later, by_hand]
    return gone, left, [], later


def _launcher_open(runner: Runner, key: str) -> bool | None:
    """Whether that launcher is open (None: the runner can't tell, which is taken as open)."""
    fn = getattr(runner, "launcher_running", None)
    if not callable(fn):
        return None
    try:
        return fn(key)
    except Exception:
        return None


def _game_words(found: _Games, kind: str) -> str:
    what = f"the {kind}{'s' if len(found.names) != 1 else ''} {_names(found.names)}" if found.names else ""
    if found.worlds:
        what += f" with the {found.worlds} world{'s' if found.worlds != 1 else ''} in {'them' if len(found.names) != 1 else 'it'}"
    return what


def _minecraft_part(inv: Inventory, mc: Path) -> Part | None:
    label = "Minecraft Launcher games"
    found = _minecraft_games(mc)
    ticked = inv.choices.games
    if not ticked:
        inv.keep += found.keep
    if not (found.names or found.paths) and not (ticked and found.listed):
        return None
    games = _game_words(found, "installation")
    if not ticked:
        return Part(key="games", label=label, present=True, kept=True, user_home=inv.user_home,
                    action=f"kept: {games or 'what Craft Conductor set up'} in the Minecraft Launcher")
    ours = mc / "craft-conductor"
    notes = any(_lex(p) == _lex(ours) or p.name in GAME_NOTES for p in found.paths)
    pieces = [x for x in (games, f"Craft Conductor's notes in {ours}" if notes else "") if x]
    action = (f"deleted: {' and '.join(pieces) or 'what Craft Conductor set up'}, from the launcher's list and its "
              "folders; your other installations stay"
              if found.names or found.paths else "listed for you: installations Craft Conductor has no record of making")
    if found.listed and (found.names or found.paths):
        action += " (some are listed for you: see what's left to do)"
    part = Part(key="games", label=label, present=True, action=action, paths=list(found.paths), known=found.known,
                user_home=inv.user_home)

    def remove(runner: Runner) -> Outcome:
        out = Outcome(manual=[f"{label}: {x}" for x in found.listed])
        if found.edits and _launcher_open(runner, "minecraft") is not False:
            where = ", ".join(str(p) for p in found.paths)
            out.manual.insert(0, f"{label}: the Minecraft Launcher is open (or that couldn't be checked), so nothing was "
                                 f"changed in it. Close it, then delete the installations {_names(found.names)} in it "
                                 f"(Installations, the ... button, Delete)" + (f", and these folders: {where}" if where else ""))
            return out
        left: list[str] = []
        for f, keys in found.edits.items():
            gone, kept, failed, later = _drop_profiles(f, keys, runner)
            left += kept
            out.failed += [f"{label}: {x}" for x in failed]
            out.manual += [f"{label}: {x}" for x in later]
            if gone:
                out.removed.append(f"{label}: took the installations {_names(gone)} out of {f.name}")
        # (what belongs to an installation still in the launcher stays: its folder, its version, the backups)
        hold = [p for k in left for p in found.held.get(k, [])]
        paths = found.paths
        if hold:
            paths = [p for p in _carve(paths, hold, inv.user_home) if not any(locations.inside(p, k) for k in hold)]
        done = delete_paths(dataclasses.replace(part, paths=paths), runner)
        out.removed += done.removed
        out.failed += done.failed
        return out
    part.remove = remove
    return part


def _instance_name(folder: Path) -> str:
    try:
        for line in (folder / "instance.cfg").read_text(encoding="utf-8", errors="replace").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == "name" and value.strip():
                return value.strip()
    except OSError:
        pass
    return folder.name


def _prism_games(dirs: Iterable[Path]) -> _Games:
    """Craft Conductor's instances in Prism (each of its data folders ``dirs``), as recorded."""
    from . import launchers
    found = _Games()
    old: list[str] = []
    for d in dirs:
        if not d.is_dir():
            continue
        instances = launchers.prism_instances(d)
        entries = _entries(instances)
        if entries:
            found.known.append(instances)
        for e in entries:
            if e.name.startswith(OLD_PREFIX):
                old.append(e.name)
            elif not e.name.startswith(GAME_PREFIX):
                continue
            elif _plain_dir(e) and _marked(e / ".minecraft"):
                found.paths.append(e)
                found.keep.append(e)
                found.names.append(_instance_name(e))
                found.worlds += _worlds(e / ".minecraft")
            else:
                found.listed.append(f"{e} has no record that Craft Conductor made it, so it stays; delete it in Prism "
                                    "yourself if you don't want it")
    if old:
        found.listed.append(f"older instances from before Craft Conductor's rename ({_names(old)}) weren't recorded the "
                            "way today's are, so they stay; delete them in Prism yourself if you don't want them")
    _not_through_links(found)
    return found


def _prism_part(inv: Inventory, dirs: list[Path]) -> Part | None:
    label = "Prism Launcher games"
    found = _prism_games(dirs)
    ticked = inv.choices.games
    if not ticked:
        inv.keep += found.keep
    if not found.paths and not (ticked and found.listed):
        return None
    games = _game_words(found, "instance")
    if not ticked:
        return Part(key="games", label=label, present=True, kept=True, user_home=inv.user_home,
                    action=f"kept: {games} in Prism Launcher")
    action = (f"deleted: {games}; your other instances stay" if found.paths
              else "listed for you: instances Craft Conductor has no record of making")
    if found.listed and found.paths:
        action += " (some are listed for you: see what's left to do)"
    part = Part(key="games", label=label, present=True, action=action, paths=list(found.paths), known=found.known,
                user_home=inv.user_home)

    def remove(runner: Runner) -> Outcome:
        out = Outcome(manual=[f"{label}: {x}" for x in found.listed])
        if found.paths and _launcher_open(runner, "prism") is not False:
            out.manual.insert(0, f"{label}: Prism Launcher is open (or that couldn't be checked), so nothing was deleted "
                                 f"in it. Close it, then delete the instances {_names(found.names)} in it (right-click, "
                                 f"Delete), or these folders: {', '.join(str(p) for p in found.paths)}")
            return out
        done = delete_paths(part, runner)
        out.removed += done.removed
        out.failed += done.failed
        return out
    part.remove = remove
    return part


def _imported_part(inv: Inventory, apps: list[tuple[str, list[str]]]) -> Part | None:
    """The Modrinth App and CurseForge: Craft Conductor only gave them a modpack file to import, and the
    app made the profile itself, so there's no record of which profiles came from it: listed."""
    from . import launchers
    if not apps:
        return None
    label = "Modrinth App and CurseForge games"
    which = " and ".join(launchers.LABELS[k] for k, _ in apps)
    if not inv.choices.games:
        return Part(key="games", label=label, present=True, kept=True, user_home=inv.user_home,
                    action=f"kept: the profiles in the {which}")
    lines = []
    for key, made in apps:
        app = launchers.LABELS[key]
        lines.append(f"{app}: Craft Conductor only gave it modpack files to import, and the app made the profiles "
                     "itself, so Craft Conductor has no record of them and nothing was removed there; delete the ones "
                     f"you don't want in the {app}" + (f" (single-player games Craft Conductor put there: {_names(made)})"
                                                         if made else "")
                     + ". The modpack files it saved are in your Downloads folder unless you moved them.")
    return Part(key="games", label=label, present=True,
                action=f"listed for you: the {which} made their profiles themselves, so there's no record of them",
                user_home=inv.user_home, remove=lambda runner: Outcome(manual=list(lines)))


def _games_parts(inv: Inventory) -> list[Part]:
    """Games Craft Conductor set up in launchers (Play on this computer, single-player games, a friend's
    joined servers): only what was recorded, and only when ticked (see the notes above GAME_PREFIX)."""
    from types import SimpleNamespace
    from . import join, launchers, singleplayer
    env = {k.upper(): v for k, v in inv.env.items()}  # (the person's own folders, never this process's)
    home = inv.user_home
    made: list[dict] = []
    try:
        made = singleplayer.games(SimpleNamespace(state_dir=inv.state_dir))
    except Exception:
        made = []
    apps = []
    for key, dirs in (("modrinth", launchers.modrinth_dirs(env, home)), ("curseforge", launchers.curseforge_dirs(env, home))):
        names = [str(g.get("name")) for g in made if isinstance(g, dict) and key in (g.get("launchers") or [])]
        if names or any(d.is_dir() for d in dirs):
            apps.append((key, names))
    parts = [_minecraft_part(inv, join.minecraft_dir(env, home)),
             _prism_part(inv, [d for d in launchers.prism_dirs(env, home) if d.is_dir()]),
             _imported_part(inv, apps)]
    parts = [p for p in parts if p is not None]
    return parts or [_absent("games", "Games in launchers", inv)]


LISTED = (
    "Tailscale and playit.gg: Craft Conductor didn't install these apps, so they stay; remove them the usual way "
    "(Windows: Settings > Apps; Mac: the Applications folder; Linux: your package manager) if you don't use them any more",
    "Paired phones: remove the control panel app from the home screen, and delete Craft Conductor's passkey in the "
    "phone's password manager",
    "Browsers: uninstall the control panel app if you installed it (the browser's apps page), and clear the control "
    "panel's site data in the browser's settings",
    "Friends' computers and computers you set up over SSH have their own Craft Conductor: uninstall it on each of them "
    "(craft-conductor uninstall)",
    "Docker: remove containers running Craft Conductor with docker rm -f, and its image with docker rmi, on the "
    "computer running Docker",
)


def _listed_part(inv: Inventory) -> Part:
    """What Craft Conductor can't reach from here: listed for the person, never touched."""
    return Part(key="listed", label="Left for you", present=True,
                action="listed for you: the Tailscale and playit.gg apps, phones, browsers, friends' and SSH "
                       "computers, Docker",
                user_home=inv.user_home, remove=lambda runner: Outcome(manual=list(LISTED)))


Builder = Callable[[Inventory], "Part | list[Part] | None"]
BUILDERS: dict[str, Builder] = {
    "tunnels": _tunnels_parts,
    "router": _router_part,
    "firewall": _firewall_part,
    "service": _service_part,
    "invite": _invite_part,
    "games": _games_parts,
    "exports": _exports_part,
    "backups": _backups_part,
    "servers": _servers_part,
    "lockbox": _lockbox_part,
    "state": _state_part,
    "java": _java_part,
    "program": _program_part,
    "listed": _listed_part,
}


def plan(home: Path, choices: Choices, *, env: Mapping[str, str] | None = None, runner: Runner | None = None) -> list[Part]:
    """Every part, in ``ORDER``: here or not, what will happen, the exact paths. Reads the home
    (hub.json, each server's craft-conductor.toml) without starting Craft Conductor; changes nothing.
    ``runner``: for builders that ask the computer what's there (it changes nothing while planning)."""
    inv = _inventory(Path(home), choices, os.environ if env is None else env, runner)
    parts: list[Part] = []
    for key in ORDER:
        builder = BUILDERS.get(key)
        got = builder(inv) if builder else None
        parts += [] if got is None else [got] if isinstance(got, Part) else list(got)
    return parts


# ------------------------------------------------------------------ doing it
def delete_paths(part: Part, runner: Runner) -> Outcome:
    """Delete a part's paths, each checked again first (``refusal``); one that fails doesn't stop the others."""
    out = Outcome()
    home = part.user_home or Path.home()
    for path in part.paths:
        try:
            st = os.lstat(path)
        except FileNotFoundError:
            continue  # (gone already)
        except OSError as e:
            out.failed.append(f"{part.label}: {path} couldn't be looked at ({e.strerror or e})")
            continue
        why = refusal(path, home, part.known, part.system_ok)
        if why:
            out.failed.append(f"{part.label}: {path} wasn't deleted ({why})")
            continue
        try:
            if stat.S_ISDIR(st.st_mode):
                runner.delete_tree(path)
            else:
                runner.delete_file(path)
        except Exception as e:  # (anything: the report says so and the rest goes on)
            out.failed.append(f"{part.label}: {path} couldn't be deleted ({getattr(e, 'strerror', None) or e})")
            continue
        out.removed.append(f"{part.label}: deleted {path}")
    remove_empty = getattr(runner, "remove_empty_folder", None)
    for folder in part.emptied if callable(remove_empty) else []:
        try:
            if not _plain_dir(folder) or any(folder.iterdir()) or refusal(folder, home, part.known):
                continue  # (something is left in it, or it's not one to remove: it stays)
            remove_empty(folder)
        except Exception:  # (it stays, which is fine: only an empty folder)
            continue
        out.removed.append(f"{part.label}: deleted the empty folder {folder}")
    return out


Progress = Callable[[str, str, str], None]  # (part key, label, "working" | "done" | "failed" | "kept")


StopServers = Callable[[], "Iterable[Path | str] | None"]


def _hold_running(part: Part, running: list[Path], everyone: bool, report: Report) -> Part:
    """``part`` without what belongs to a server that's still running (R13): that server's folders and
    its own backups are kept, and the report says why."""
    held = {root: pieces for root, pieces in part.per_server.items()
            if pieces and (everyone or any(_same(root, r) for r in running))}
    if not held:
        return part
    hold = [p for pieces in held.values() for p in pieces]
    paths = [p for p in _carve(part.paths, hold, part.user_home or Path.home())
             if not any(locations.inside(p, k) for k in hold)]
    for root, pieces in held.items():
        report.kept.append(f"{part.label}: {', '.join(str(p) for p in pieces)} kept, because the server in {root} "
                           "may still be running")
    return dataclasses.replace(part, paths=paths, emptied=[e for e in part.emptied if not any(_same(e, r) for r in held)])


def run(parts: list[Part], *, runner: Runner | None = None, progress: Progress | None = None,
        stop_servers: StopServers | None = None) -> Report:
    """Do the plan, in its order: first ``stop_servers``, then each part that's here and not kept. A
    part that fails goes in the report and the rest goes on.

    ``stop_servers()`` stops every server cleanly and returns the folders (roots) of the servers that
    are still running (empty or None: all stopped). If it raises, which servers stopped isn't known,
    so every server is treated as still running. A server still running is never deleted: its
    folders and its own backups are kept, and the report says so."""
    runner = runner if runner is not None else SystemRunner()
    tell = progress or (lambda key, label, status: None)
    report = Report()
    running: list[Path] = []
    everyone = False
    if stop_servers is not None:
        tell("stop", "Stopping the servers", "working")
        try:
            running = [Path(p) for p in (stop_servers() or [])]
        except Exception as e:
            everyone = True
            report.failed.append(f"Stopping the servers: {e} (so every server and its backups are kept)")
        for root in running:
            report.failed.append(f"Stopping the servers: the server in {root} is still running, so it's kept with its "
                                 "own backups")
        tell("stop", "Stopping the servers", "failed" if everyone or running else "done")
    for part in parts:
        if part.kept:
            report.kept.append(f"{part.label}: {part.action}")
            tell(part.key, part.label, "kept")
            continue
        if not part.present:
            continue
        if part.per_server and (everyone or running):
            part = _hold_running(part, running, everyone, report)
        tell(part.key, part.label, "working")
        try:
            out = part.remove(runner) if part.remove is not None else delete_paths(part, runner)
        except Exception as e:
            out = Outcome(failed=[f"{part.label}: {e}"])
        report.removed += out.removed
        report.failed += out.failed
        report.manual += out.manual + ([part.manual] if part.manual else [])
        tell(part.key, part.label, "failed" if out.failed else "done")
    return report


STOP_UNANSWERED = 20.0  # seconds: a stop request nothing has taken by then has nobody to take it
STOP_POLL = 0.2


def server_status(root: Path) -> dict | None:
    """What the server in ``root`` answers on its port on this computer (``online``: players on), or
    None when nothing answers there like a Minecraft server."""
    from . import tunnel
    from .properties import number, read_properties
    port = number(read_properties(game_dir(root) / "server.properties"), "server-port", 25565)
    try:
        return tunnel.ping("127.0.0.1", port, timeout=2)
    except (OSError, ValueError):
        return None


def stop_timeout(root: Path) -> int:
    """How long the server in ``root`` is given to stop (``[server] stop_timeout``, read only)."""
    try:
        data = tomllib.loads(configmod.read_text(root / configmod.CONFIG_NAME))
        return configmod.parse_duration(data["server"]["stop_timeout"])
    except (OSError, ValueError, KeyError, TypeError, configmod.ConfigError):
        return 120


def stop_others(roots: Iterable[Path], *, check_ports: bool = True, unanswered: float = STOP_UNANSWERED,
                poll: float = STOP_POLL, status: Callable[[Path], dict | None] | None = None,
                say: Callable[[str], None] | None = None, own_pid: int | None = None) -> list[Path]:
    """Stop every server in ``roots`` that a `craft-conductor run` or another Craft Conductor looks after
    (a pid other than ``own_pid`` in its state folder), the usual way (its stop request, as
    `craft-conductor stop`): cleanly, with players on told in game and given a minute. Returns the
    folders (as given) of those still running: one that didn't stop in time, one whose request nothing
    took, and (``check_ports``) one answering on its port (``status``) with nothing looking after it.
    Used by the command and by the control panel (after it has stopped its own servers)."""
    import time
    from .daemon import STOP_REQUEST, STOP_WARNING, request_stop_in, running_pid_in
    status = status or server_status
    roots = list(roots)

    def other(state: Path) -> bool:
        try:
            pid = running_pid_in(state)
        except OSError:
            return True  # (its pid file can't be read: taken as running, so it's kept, never deleted)
        return bool(pid) and pid != own_pid
    started = time.monotonic()
    asked: dict[Path, float] = {}
    still: list[Path] = []
    for root in roots:
        state = root / configmod.STATE_DIR
        if other(state):
            if say:
                say(f"  Stopping the server in {root}...")
            try:
                request_stop_in(state, PLAYERS_TOLD)
            except OSError:
                still.append(root)  # (it couldn't be asked to stop: kept)
                continue
            asked[root] = started + STOP_WARNING + stop_timeout(root) + 30
    while asked:
        time.sleep(poll)
        now = time.monotonic()
        for root, deadline in list(asked.items()):
            state = root / configmod.STATE_DIR
            if not other(state):
                del asked[root]
            elif (state / STOP_REQUEST).exists() and now - started > unanswered:
                try:
                    (state / STOP_REQUEST).unlink(missing_ok=True)  # (whatever runs there isn't looking after the server)
                except OSError:
                    pass
                still.append(root)
                del asked[root]
            elif now > deadline:
                still.append(root)
                del asked[root]
    if check_ports:
        still += [root for root in roots if root not in still and status(root) is not None]
    return still


def run_elsewhere(root: Path, own_pid: int | None = None) -> bool:
    """The server in ``root`` is looked after by another process (`craft-conductor run`, another Craft
    Conductor window): a live pid other than ``own_pid`` in its state folder, or a pid file that's
    there but can't be read (taken as running: such a server is kept)."""
    from .daemon import running_pid_in
    try:
        pid = running_pid_in(root / configmod.STATE_DIR)
    except OSError:
        return True
    return bool(pid) and pid != own_pid


def count_worlds(roots: Iterable[Path]) -> int:
    """How many of these servers have a world: said in the second confirmation before deleting them."""
    from . import world
    n = 0
    for root in roots:
        try:
            n += world.level_dir(game_dir(Path(root))).is_dir()
        except (world.WorldError, OSError):
            continue
    return n


def remove_empty_home(home: Path) -> str | None:
    """Craft Conductor's own folder (~/craft-conductor), when everything in it went: a report line."""
    if home != (Path.home() / "craft-conductor").resolve():
        return None  # (a home set with CRAFT_CONDUCTOR_HOME may be a folder that's there for more than this)
    try:
        if folders.link_stat(os.lstat(home)) or any(home.iterdir()):
            return None
        os.rmdir(home)  # (only ever an empty folder)
    except OSError:
        return None
    return f"The Craft Conductor folder: deleted the empty folder {home}"


def save_report(text: str) -> Path:
    """Keep the report in the person's Downloads folder (the home folder may be gone): where it went.
    Raises OSError when it can't be saved."""
    folder = folders.downloads_dir()
    if folder is None:
        raise OSError("there's no Downloads folder here")
    saved = folder / REPORT_FILE
    saved.write_text(text, encoding="utf-8")
    return saved


# ------------------------------------------------------------------ the real runner
class SystemRunner:
    """The Runner that changes this computer. Never used by the tests."""

    timeout = 300.0

    def run(self, argv: list[str], *, elevated: bool = False, detached: bool = False) -> int:
        if os.name == "nt" and elevated:
            from . import firewall
            code = firewall.elevate(argv[0], subprocess.list2cmdline(argv[1:]), self.timeout)
            return DECLINED if code is None else code
        # (elsewhere ``elevated`` is the caller's: it passes sudo or pkexec in argv when it needs them)
        command = _command_line(argv)
        if detached:
            if os.name == "nt":
                # (a console of its own with no window, so what it runs opens none either; not
                # DETACHED_PROCESS: a console-less cmd gives every command it starts a window)
                flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
                subprocess.Popen(command, creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(command, start_new_session=True, close_fds=True, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return 0
        from .desktop import NO_WINDOW
        return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=self.timeout,
                              **NO_WINDOW).returncode

    def delete_tree(self, path: Path) -> None:
        from . import removal
        removal.rmtree(path)  # (read-only files and folders too: #216)

    def remove_empty_folder(self, path: Path) -> None:
        os.rmdir(path)  # (only ever an empty folder: fails otherwise)

    def delete_file(self, path: Path) -> None:
        try:
            os.unlink(path)
        except PermissionError:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)  # (a read-only file: Windows won't delete it otherwise)
            os.unlink(path)

    def registry_delete(self, key: str) -> None:
        """Delete a key of this account's (``HKCU\\...``) with everything under it; one that isn't there is fine."""
        import winreg
        top, _, sub = key.partition("\\")
        if top.upper() not in ("HKCU", "HKEY_CURRENT_USER") or not sub.strip("\\"):
            raise ValueError(f"only this account's own keys are deleted, not {key}")

        def delete(path: str) -> None:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as k:
                    while True:
                        try:
                            child = winreg.EnumKey(k, 0)
                        except OSError:
                            break
                        delete(f"{path}\\{child}")
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            except FileNotFoundError:
                pass
        delete(sub.strip("\\"))

    # (the optional questions and jobs a Runner may have: see Runner)
    def firewall_rules(self) -> list[str] | None:
        """The names of Craft Conductor's own Windows Firewall rules (one PowerShell read, no
        administrator rights); None when they couldn't be read."""
        from . import firewall
        if not firewall.available():
            return []
        state = firewall.read(fresh=True)
        return None if state is None else [r["name"] for r in firewall.own_rules(state)]

    def registry_has(self, key: str) -> bool:
        """An ``HKCU\\...`` key of this account's is there."""
        import winreg
        top, _, sub = key.partition("\\")
        if top.upper() not in ("HKCU", "HKEY_CURRENT_USER") or not sub.strip("\\"):
            raise ValueError(f"only this account's own keys are looked at, not {key}")
        try:
            winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub.strip("\\")).Close()
        except FileNotFoundError:
            return False
        return True

    def router_remove(self, ports: list[tuple[int, str]]) -> list[tuple[int, str, str]]:
        """Take these mappings back on the router (UPnP); the ones it refused, with why. Raises
        upnp.UpnpError (or OSError) when no router answers."""
        from . import upnp
        gw = upnp.find(timeout=3.0)
        refused = []
        for port, proto in ports:
            try:
                upnp.remove(gw, port, proto)
            except upnp.UpnpError as e:
                refused.append((port, proto, str(e)))
        return refused

    def stop_process(self, pid: int, exe: str) -> bool:
        """Stop the cloudflared Craft Conductor started, only if that process is still it."""
        from . import tunnels
        return tunnels.stop_cloudflared(pid, exe)

    def launcher_running(self, key: str) -> bool | None:
        """Whether that launcher ("minecraft", "prism") is open; None when it can't be told."""
        names = _process_names()
        if names is None:
            return None
        return any(want in name for name in names for want in LAUNCHER_PROCESSES[key])

    def write_text(self, path: Path, text: str) -> None:
        """Replace a launcher's file whole, the way join.py writes it: a temporary file next to it,
        then a swap, so the launcher never reads half a file."""
        path = Path(path)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

    def own_unit(self) -> str | None:
        """The systemd unit this process runs in (Linux: the last part of its cgroup), or None."""
        if _system() != "linux":
            return None
        try:
            lines = Path("/proc/self/cgroup").read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        # (systemd's own line: "0::/..." with cgroup v2, ":name=systemd:/..." with v1)
        for line in [x for x in lines if x.startswith("0::")] or [x for x in lines if ":name=systemd:" in x]:
            last = line.rpartition(":")[2].rstrip("/").rpartition("/")[2]
            if last.endswith(".service"):
                return last
        return None


def _process_names() -> list[str] | None:
    """The running programs' names (Windows), short names (Linux) or paths (macOS), in lower case;
    None when they can't be read."""
    try:
        if os.name == "nt":
            from .desktop import NO_WINDOW
            done = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=15,
                                  stdin=subprocess.DEVNULL, **NO_WINDOW)
            if done.returncode != 0:
                return None
            return [line.split('","')[0].strip('"').lower() for line in done.stdout.splitlines() if line.startswith('"')]
        if os.path.isdir("/proc") and sys.platform != "darwin":
            out = []
            for pid in os.listdir("/proc"):
                if pid.isdigit():
                    try:
                        with open(f"/proc/{pid}/comm", encoding="utf-8", errors="replace") as f:
                            out.append(f.read().strip().lower())
                    except OSError:
                        continue
            return out
        done = subprocess.run(["ps", "-A", "-o", "comm="], capture_output=True, text=True, timeout=15,
                              stdin=subprocess.DEVNULL)
        return [line.strip().lower() for line in done.stdout.splitlines()] if done.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _command_line(argv: list[str]) -> list[str] | str:
    """What to start: ``argv``, except for Windows' cmd: everything after its ``/c`` goes to it as
    written (cmd reads its own quotes, not the ones Python would add)."""
    if os.name == "nt" and argv and Path(argv[0]).name.lower() in ("cmd", "cmd.exe"):
        lowered = [a.lower() for a in argv]
        if "/c" in lowered:
            i = lowered.index("/c")
            return subprocess.list2cmdline(argv[:i + 1]) + " " + " ".join(argv[i + 1:])
    return argv
