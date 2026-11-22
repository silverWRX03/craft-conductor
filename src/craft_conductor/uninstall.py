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
calls; ``SystemRunner`` is the real one.
"""

from __future__ import annotations

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
DECLINED = 1223  # (Windows' ERROR_CANCELLED: the administrator prompt was answered No)
# The fixed order (servers are stopped before all of these, by run()'s stop_servers).
ORDER = ("tunnels", "router", "firewall", "service", "invite", "games", "exports", "backups", "servers",
         "lockbox", "state", "program")


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
    running, 0 once it has started)."""

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
    part would delete (its folders, its own backups), kept when that server didn't stop (``run``)."""
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


def _dangerous(path: Path, home: Path) -> str | None:
    """Why ``path`` is never deleted wherever it came from: a drive root, the person's home folder or
    one holding it, a system folder (None: none of those)."""
    try:
        is_dir = stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        is_dir = True
    real = Path(os.path.realpath(path))
    if real.parent == real or not os.path.splitdrive(str(real))[1].strip("\\/"):
        return "it's the top of a drive"
    if locations.inside(home, real):
        return "it's your home folder, or holds it"
    if is_dir and (locations.is_system(real) or _holds_system(real)):
        return "it's a system folder"
    return None


def refusal(path: Path, home: Path, known: Iterable[Path]) -> str | None:
    """Why ``path`` mustn't be deleted (None: it may be). ``home``: the person's home folder."""
    path, known = Path(path), list(known)
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
    if why := _dangerous(path, home):
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


def _table_dir(root: Path, data: dict, table: str, default: str) -> Path:
    """A folder a server's craft-conductor.toml names (``[server] dir``, ``[backups] dir``), as
    written (not followed through links: a link isn't deleted)."""
    t = data.get(table)
    value = t.get("dir", default) if isinstance(t, dict) else default
    return Path(os.path.abspath(root / (value if isinstance(value, str) and value else default)))


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

    def pieces_of(self, sid: str) -> list[Path]:
        """What makes up one server: its folder (the one kept in the home folder itself: its server
        folder and craft-conductor.toml), and its server folder when that's kept outside it."""
        root = self.servers[sid]
        game = _table_dir(root, self.configs[sid], "server", "server")
        if _same(root, self.home):
            return _existing([game, root / configmod.CONFIG_NAME])
        return _existing([root, *([] if _lex_inside(game, root) else [game])])

    def server_pieces(self) -> list[Path]:
        return _existing(p for sid in self.servers for p in self.pieces_of(sid))

    def backup_dir_of(self, sid: str) -> list[Path]:
        return _existing([_table_dir(self.servers[sid], self.configs[sid], "backups", "backups")])

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


def _inventory(home: Path, choices: Choices, env: Mapping[str, str], runner: Runner | None) -> Inventory:
    from . import hub as hubmod  # (heavy: only when planning)
    state_dir = home / configmod.STATE_DIR
    data = hubmod.read_hub_file(state_dir)
    places = locations.read(data, home)
    servers = hubmod.discover_servers(home, data, places["servers"])
    inv = Inventory(home=home, state_dir=state_dir, user_home=_user_home(env), choices=choices, env=env, runner=runner,
                    hub=data, places=places, servers=servers, configs={sid: _server_toml(r) for sid, r in servers.items()})
    if not choices.servers:
        inv.keep += [places["servers"], *inv.server_pieces()]
    if not choices.backups:
        inv.keep += [*([places["backups"]] if places["backups"] else []), *inv.backup_dirs(), *inv.copy_dirs()]
    if not choices.exports:
        inv.keep.append(places["exports"])
    if choices.keep_lockbox_key:
        inv.keep.append(inv.key_file())
    return inv


# ------------------------------------------------------------------ the parts
def _place_part(inv: Inventory, key: str, label: str, ticked: bool, paths: list[Path], known: list[Path],
                deleted: str, kept: str, per_server: dict[Path, list[Path]] | None = None) -> Part:
    """A part made of folders in places (servers, backups, exports). Ticked: what's kept is carved
    out, and nothing is deleted through a link or junction (R10): it's listed for the person."""
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
    home = inv.user_home
    guards = {root: [p for p in pieces if not _dangerous(p, home)] for root, pieces in (per_server or {}).items()}
    return Part(key=key, label=label, present=present, action=(deleted if ticked else kept) if present else "nothing here",
                paths=paths, manual=manual, kept=present and not ticked,
                known=[k for k in known if not _dangerous(k, home)], user_home=home, per_server=guards)


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
    return _place_part(inv, "backups", "Backups", inv.choices.backups, paths, [*dirs, *copies, *copy_folders, folder],
                       f"deleted: every server's backups{copies_too}", f"kept in {where}",
                       {root: inv.backups_of(sid) for sid, root in inv.servers.items()})


def _servers_part(inv: Inventory) -> Part:
    folder, pieces = inv.places["servers"], inv.server_pieces()
    paths = _existing(_whole_or_each(folder, pieces, empty_too=_lex(folder) == _lex(locations.defaults(inv.home)["servers"])))
    n = len(inv.servers)
    return _place_part(inv, "servers", "Servers and worlds", inv.choices.servers, paths, [folder, *pieces],
                       f"deleted: {n} server{'s' if n != 1 else ''} and their worlds",
                       f"kept in {', '.join(str(p) for p in paths) or '-'}",
                       {root: inv.pieces_of(sid) for sid, root in inv.servers.items()})


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


def _windows_delete_later(exe: Path, env: Mapping[str, str]) -> list[str] | None:
    """The command that deletes the Windows program once this process has exited (a running
    program can't delete itself): a detached cmd waits for this process id to go, then deletes the
    file (and leftovers of an update). None when cmd would change the paths (a % in them)."""
    from . import selfupdate
    system32 = PureWindowsPath(_env(env, "SystemRoot") or r"C:\Windows") / "System32"
    files = [exe, *(p for p in (selfupdate.old_binary(exe), selfupdate.failed_binary(exe)) if p.is_file())]
    if any(c in str(p) for p in (system32, *files) for c in '%"') or " " in str(system32):
        return None
    pid = os.getpid()
    wait = (f"(for /l %i in (1,1,60) do @({system32}\\tasklist.exe /nh /fi \"PID eq {pid}\" | {system32}\\find.exe "
            f"\"{pid}\" >nul && {system32}\\PING.EXE -n 2 127.0.0.1 >nul))")
    targets = " ".join(f'"{p}"' for p in files)
    return [str(system32 / "cmd.exe"), "/d", "/s", "/c", f'"{wait} & del /f /q {targets}"']


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
        return Outcome(removed=[f"{label}: {exe} is deleted a few seconds after Craft Conductor closes"])
    return Part(**base, action=f"deleted a few seconds after Craft Conductor closes: {exe}", paths=[exe], known=[exe],
                remove=remove)


Builder = Callable[[Inventory], "Part | list[Part] | None"]
BUILDERS: dict[str, Builder] = {
    "exports": _exports_part,
    "backups": _backups_part,
    "servers": _servers_part,
    "lockbox": _lockbox_part,
    "state": _state_part,
    "program": _program_part,
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
        why = refusal(path, home, part.known)
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
    return dataclasses.replace(part, paths=paths)


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
                flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                subprocess.Popen(command, creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(command, start_new_session=True, close_fds=True, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return 0
        return subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=self.timeout).returncode

    def delete_tree(self, path: Path) -> None:
        from . import removal
        removal.rmtree(path)  # (read-only files and folders too: #216)

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


def _command_line(argv: list[str]) -> list[str] | str:
    """What to start: ``argv``, except for Windows' cmd: everything after its ``/c`` goes to it as
    written (cmd reads its own quotes, not the ones Python would add)."""
    if os.name == "nt" and argv and Path(argv[0]).name.lower() in ("cmd", "cmd.exe"):
        lowered = [a.lower() for a in argv]
        if "/c" in lowered:
            i = lowered.index("/c")
            return subprocess.list2cmdline(argv[:i + 1]) + " " + " ".join(argv[i + 1:])
    return argv
