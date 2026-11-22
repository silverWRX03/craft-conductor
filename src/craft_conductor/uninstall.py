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
part's known places (``safe_to_delete``). ``run`` checks every path again right before deleting it;
a path refused then is a failure in the report, never a crash. What a kept place holds is never
deleted with a folder around it: that folder is deleted one entry at a time around it (a server's
own backups folder survives deleting the server).

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
    instead of deleting ``paths``."""
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


def refusal(path: Path, home: Path, known: Iterable[Path]) -> str | None:
    """Why ``path`` mustn't be deleted (None: it may be). ``home``: the person's home folder."""
    path = Path(path)
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
    real = Path(os.path.realpath(path))
    if real.parent == real or not os.path.splitdrive(str(real))[1].strip("\\/"):
        return "it's the top of a drive"
    if locations.inside(home, real):
        return "it's your home folder, or holds it"
    if (st is None or stat.S_ISDIR(st.st_mode)) and (locations.is_system(real) or _holds_system(real)):
        return "it's a system folder"
    if not any(locations.inside(real, k) for k in known):
        return "it isn't one of Craft Conductor's places"
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

    def server_pieces(self) -> list[Path]:
        """What makes up the servers: each server's folder (the one kept in the home folder itself:
        its server folder and craft-conductor.toml), and a server folder kept outside it."""
        out: list[Path] = []
        for sid, root in self.servers.items():
            game = _table_dir(root, self.configs[sid], "server", "server")
            if _same(root, self.home):
                out += [game, root / configmod.CONFIG_NAME]
                continue
            out.append(root)
            if not locations.inside(game, root):
                out.append(game)
        return _existing(out)

    def backup_dirs(self) -> list[Path]:
        return _existing(_table_dir(root, self.configs[sid], "backups", "backups") for sid, root in self.servers.items())

    def copy_dirs(self) -> list[Path]:
        """Each server's own folder in its backup copy folder (``[backups] copy_to``): only those whose
        mark says they're that server's (backup.copy_out), never the copy folder itself."""
        from . import backup
        out: list[Path] = []
        for sid, root in self.servers.items():
            b = self.configs[sid].get("backups")
            text = str(b.get("copy_to") or "").strip() if isinstance(b, dict) else ""
            folder = Path(text).expanduser() if text else None
            if folder is None or not folder.is_absolute() or not _plain_dir(folder):
                continue
            me = backup.copy_owner(root)
            for entry in sorted(folder.iterdir()):
                try:
                    mine = _plain_dir(entry) and (entry / backup.COPY_OWNER).read_text(encoding="utf-8").strip() == me
                except (OSError, UnicodeDecodeError):
                    mine = False
                if mine:
                    out.append(entry)
        return _existing(out)

    def key_file(self) -> Path:
        return self.state_dir / lockbox.KEY_FILE


def _existing(paths: Iterable[Path]) -> list[Path]:
    """The ones that are there, each once."""
    out: list[Path] = []
    for p in paths:
        if os.path.lexists(p) and not any(_same(p, q) for q in out):
            out.append(p)
    return out


def _whole_or_each(folder: Path | None, members: list[Path]) -> list[Path]:
    """``[folder]`` when it holds only ``members`` (and its README), else ``members`` themselves: a
    folder the person chose may hold things of theirs too."""
    if folder is None or not _plain_dir(folder):
        return members
    try:
        entries = list(folder.iterdir())
    except OSError:
        return members
    if all(e.name == README or any(_same(e, m) for m in members) for e in entries):
        return [folder, *(m for m in members if not locations.inside(m, folder))]
    return members


def _carve(paths: Iterable[Path], keep: list[Path]) -> list[Path]:
    """``paths`` without what's kept: a path holding a kept one is replaced by its entries (again
    around the kept one), and a kept path itself is left out."""
    out: list[Path] = []
    for p in paths:
        if any(_same(p, k) for k in keep):
            continue
        if not any(locations.inside(k, p) for k in keep):
            out.append(p)
        elif _plain_dir(p):
            out += _carve(sorted(p.iterdir()), keep)
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
                deleted: str, kept: str) -> Part:
    present = bool(paths)
    return Part(key=key, label=label, present=present, action=(deleted if ticked else kept) if present else "nothing here",
                paths=_carve(paths, inv.keep) if ticked else paths, kept=present and not ticked,
                known=known, user_home=inv.user_home)


def _exports_part(inv: Inventory) -> Part:
    folder = inv.places["exports"]
    paths = _existing([folder])
    return _place_part(inv, "exports", "Exports", inv.choices.exports, paths, [folder],
                       "deleted: the exports folder and every export in it",
                       f"kept in {folder}")


def _backups_part(inv: Inventory) -> Part:
    dirs, copies, folder = inv.backup_dirs(), inv.copy_dirs(), inv.places["backups"]
    paths = _existing(_whole_or_each(folder, dirs) + copies)
    where = ", ".join(str(p) for p in paths) or "-"
    copies_too = " (and their copies in the backup copy folder)" if copies else ""
    return _place_part(inv, "backups", "Backups", inv.choices.backups, paths, [*dirs, *copies, *([folder] if folder else [])],
                       f"deleted: every server's backups{copies_too}", f"kept in {where}")


def _servers_part(inv: Inventory) -> Part:
    folder, pieces = inv.places["servers"], inv.server_pieces()
    paths = _existing(_whole_or_each(folder, pieces))
    n = len(inv.servers)
    return _place_part(inv, "servers", "Servers and worlds", inv.choices.servers, paths, [folder, *pieces],
                       f"deleted: {n} server{'s' if n != 1 else ''} and their worlds",
                       f"kept in {', '.join(str(p) for p in paths) or '-'}")


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
    present = _plain_dir(state) or os.path.lexists(state)
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
                paths=_carve([state], inv.keep) if present else [], known=[state], user_home=inv.user_home)


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


def run(parts: list[Part], *, runner: Runner | None = None, progress: Progress | None = None,
        stop_servers: Callable[[], Iterable[str] | None] | None = None) -> Report:
    """Do the plan, in its order: first ``stop_servers`` (it returns lines saying what didn't stop,
    or raises), then each part that's here and not kept. A part that fails goes in the report and the
    rest goes on."""
    runner = runner if runner is not None else SystemRunner()
    tell = progress or (lambda key, label, status: None)
    report = Report()
    if stop_servers is not None:
        tell("stop", "Stopping the servers", "working")
        try:
            problems = list(stop_servers() or [])
        except Exception as e:
            problems = [f"Stopping the servers: {e}"]
        report.failed += problems
        tell("stop", "Stopping the servers", "failed" if problems else "done")
    for part in parts:
        if part.kept:
            report.kept.append(f"{part.label}: {part.action}")
            tell(part.key, part.label, "kept")
            continue
        if not part.present:
            continue
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
