"""The upgrade pipeline.

    plan -> stage (download + verify, install loader into .craft-conductor/staging)
         -> warn players, stop -> back up -> swap files in -> boot and verify
         -> on any failure: restore the backup and start the old version again

Nothing in the server directory changes until every download has been fetched
and hash-checked, so a network hiccup or a missing file can never leave the
server half-upgraded.

If Craft Conductor itself is stopped half-way (the computer turns off, the process is
killed), ``.craft-conductor/update-in-progress.json`` says which backup to put back: the
next start does that before anything else (:meth:`Manager.recover`). The update counts
as finished once the new craft-conductor.lock.json is on disk.
"""

from __future__ import annotations

import copy
import errno
import hashlib
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import backup, java as javamod, lock as lockmod
from .config import Config
from .http import HttpClient, sha1_file
from .java import JavaManager
from .loaders import Loader, Runtime, get_loader
from .lock import Lock
from .minecraft import Mojang
from .mods import ModFile, ModProvider, providers_for
from .notify import Notifier
from .planner import Changes, Decision, Plan, Planner
from .process import ServerProcess

log = logging.getLogger(__name__)

JOURNAL = "update-in-progress.json"
INTERRUPTED = "Craft Conductor stopped in the middle of this update"


class UpgradeError(Exception):
    pass


class ManualDownloadRequired(UpgradeError):
    def __init__(self, mods: list[ModFile], folder: Path):
        self.mods = mods
        self.folder = folder
        lines = [f"  {m.name} ({m.filename}): {m.manual_url}" for m in mods]
        super().__init__(
            f"{len(mods)} mod(s) can't be downloaded automatically because their authors block it. "
            f"Download them from these links, put the files in {folder}, then update again:\n" + "\n".join(lines))


@dataclass
class Staged:
    dir: Path
    java: str
    java_major: int
    runtime: Runtime | None


@dataclass
class Result:
    ok: bool
    message: str
    process: ServerProcess | None = None
    backup: Path | None = None


class Manager:
    def __init__(self, config: Config, http: HttpClient | None = None, mojang: Mojang | None = None,
                 loader: Loader | None = None, providers: dict[str, ModProvider] | None = None,
                 java_probe: Callable[[str], int | None] = javamod.probe, notifier: Notifier | None = None,
                 echo: bool = True, sleep: Callable[[float], None] = time.sleep):
        self.config = config
        self.last_diagnosis = None  # why the last boot failed (diagnose.Diagnosis), if it did
        self.http = http or HttpClient()
        self.mojang = mojang or Mojang(self.http)
        self.loader = loader or get_loader(config.server.loader, self.http, self.mojang)
        self.providers = providers or providers_for(config, self.http)
        self.java = JavaManager(config, self.http, java_probe)
        self.notifier = notifier or Notifier(self.http, config.discord_webhook)
        self.echo = echo
        self.sleep = sleep
        self.lock = lockmod.load(config.root)
        #: called with every line of server output (the web UI's console uses this)
        self.on_line: Callable[[str], None] | None = None
        #: called with each server process as soon as it has been launched
        self.on_process: Callable[[ServerProcess], None] | None = None

    # ----------------------------------------------------------------- paths
    @property
    def server_dir(self) -> Path:
        return self.config.server.dir

    @property
    def staging_dir(self) -> Path:
        return self.config.state_dir / "staging"

    # ------------------------------------------------------ interrupted work
    @property
    def journal_path(self) -> Path:
        return self.config.state_dir / JOURNAL

    def _lock_stamp(self) -> str:
        """craft-conductor.lock.json as it is on disk, in short."""
        try:
            return hashlib.sha256((self.config.root / lockmod.LOCK_NAME).read_bytes()).hexdigest()
        except OSError:
            return ""

    def _journal_write(self, data: dict) -> None:
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.journal_path.with_name(JOURNAL + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.journal_path)

    def _journal_begin(self, title: str, archive: Path | None, plan: Plan) -> None:
        """Note, before the first server file changes, what to put back if this run is cut off."""
        self._journal_write({"title": title, "archive": str(archive) if archive else None, "lock": self._lock_stamp(),
                             "plan": plan.fingerprint, "started": time.time()})

    def _journal_end(self) -> None:
        try:
            self.journal_path.unlink(missing_ok=True)
        except OSError as e:  # (harmless: a note older than the lock file counts as finished)
            log.warning("couldn't remove %s: %s", self.journal_path.name, e)

    def forget_interrupted_update(self) -> None:
        """The server was restored by hand (after its lock file was): an interrupted update must not
        put another backup back, and isn't tried again by itself either."""
        try:
            journal = json.loads(self.journal_path.read_text(encoding="utf-8"))
            plan = str(journal.get("plan") or "")
        except (OSError, ValueError, TypeError, AttributeError):
            plan = ""
        if plan:
            self.lock = lockmod.load(self.config.root)
            self.lock.failed_plans[plan] = str(journal.get("error") or INTERRUPTED)[:300]
            lockmod.save(self.config.root, self.lock, touch=False)
        self._journal_end()

    def recover(self) -> str | None:
        """Finish safely whatever a Craft Conductor that was stopped half-way left undone: an
        update (its backup is put back), a restore or a world swap (the old folder is put back).
        Run before starting the server or updating it. Returns what was done, if anything."""
        from . import world
        done = []
        if backup.recover(self.server_dir):
            done.append("the server folder was put back (a restore had been interrupted)")
        try:
            if world.recover(world.level_dir(self.server_dir)):
                done.append("the world was put back (replacing it had been interrupted)")
        except world.WorldError:
            pass
        if self.journal_path.exists():
            done.append(self._recover_update())
        message = "; ".join(done) or None
        if message:
            self.notifier.send(f"Craft Conductor was stopped in the middle of something: {message}.")
        return message

    def _recover_update(self) -> str:
        try:
            journal = json.loads(self.journal_path.read_text(encoding="utf-8"))
            title, plan = str(journal.get("title") or "an update"), str(journal.get("plan") or "")
            archive = Path(journal["archive"]) if journal.get("archive") else None
            if archive is not None and archive.resolve().parent != self.config.backups.dir.resolve():
                raise ValueError("its backup isn't in the server's backups folder")
        except (OSError, ValueError, TypeError, AttributeError, KeyError):
            log.warning("the note about an interrupted update is damaged; removing it")
            self._journal_end()
            return "a damaged note about an interrupted update was removed"
        shutil.rmtree(self.staging_dir, ignore_errors=True)  # (its downloads, no longer needed either way)
        if journal.get("lock") != self._lock_stamp():
            # The new craft-conductor.lock.json was saved: the update had finished, only the note was left.
            self._journal_end()
            return f"the update ({title}) had finished"
        if archive is None:  # (a first install into an empty folder: there was nothing to keep)
            self._journal_end()
            log.warning("an install (%s) was interrupted; it starts again from the beginning", title)
            return f"the interrupted install ({title}) starts again"
        if not archive.is_file():
            self._journal_end()
            log.error("an update (%s) was interrupted, and the backup made before it (%s) is gone: the server may be "
                      "half-updated; restore a backup on the Backups page", title, archive.name)
            return (f"the update ({title}) was interrupted and its backup {archive.name} is gone, so the server may be "
                    "half-updated: restore a backup on the Backups page")
        log.warning("the update (%s) was interrupted; putting the backup %s back", title, archive.name)
        try:
            backup.restore(archive, self.server_dir)
        except Exception as e:  # (the note stays: the next start tries again)
            raise UpgradeError(f"Craft Conductor was stopped in the middle of an update ({title}), and putting the "
                               f"backup {archive.name} back failed: {e}") from e
        self.lock = lockmod.load(self.config.root)
        if plan:  # (not tried again by itself; a manual update still can)
            self.lock.failed_plans[plan] = str(journal.get("error") or INTERRUPTED)[:300]
            lockmod.save(self.config.root, self.lock, touch=False)
        self._journal_end()
        return f"the update ({title}) was interrupted, so the backup {archive.name} was put back"

    def reload_config(self) -> None:
        """Re-read craft-conductor.toml (after it was edited, e.g. from the web UI)."""
        from . import config as configmod

        new = configmod.load(self.config.root)
        if new.server.loader != self.config.server.loader:
            if self.lock.installed:
                raise UpgradeError("changing the loader of an installed server isn't supported")
            # Nothing installed yet (first-time setup): just switch.
            self.loader = get_loader(new.server.loader, self.http, self.mojang)
        self.config = new
        self.java.config = new
        self.notifier.discord_webhook = new.discord_webhook
        cf = self.providers.get("curseforge")
        if cf is not None and hasattr(cf, "api_key"):
            cf.api_key = new.curseforge_api_key

    # ------------------------------------------------------------- planning
    def planner(self) -> Planner:
        return Planner(self.config, self.lock, self.mojang, self.loader, self.providers, self.unmanaged_jars())

    def check(self, target: str | None = None, retry_failed: bool = False) -> tuple[Decision, Changes | None]:
        if hasattr(self.http, "clear_cache"):
            self.http.clear_cache()  # always look at fresh release data
        decision = self.planner().decide(target, retry_failed=retry_failed)
        changes = decision.plan.changes(self.lock) if decision.plan else None
        return decision, changes

    @property
    def mods_dir(self) -> Path:
        """Where the server loads mods from (plugins/ for Paper)."""
        return self.server_dir / self.loader.mods_folder

    def unmanaged_jars(self) -> list[str]:
        mods_dir = self.mods_dir
        if not mods_dir.is_dir():
            return []
        managed = {m.filename for m in self.lock.mods}
        return sorted(p.name for p in mods_dir.glob("*.jar") if p.name not in managed)

    def disabled_jars(self) -> list[str]:
        """Jars switched off by hand (``.jar.disabled``): the server doesn't load them."""
        mods_dir = self.mods_dir
        return sorted(p.name[:-len(".disabled")] for p in mods_dir.glob("*.jar.disabled")) if mods_dir.is_dir() else []

    def set_jar(self, name: str, action: str) -> str:
        """Switch a jar added by hand off (renamed to .jar.disabled) or on, or remove it. Only
        jars actually in the folder, and not ones craft-conductor manages, can be named."""
        managed = {m.filename for m in self.lock.mods}
        on, off = set(self.unmanaged_jars()), set(self.disabled_jars())
        if name in managed:
            raise UpgradeError(f"{name} is managed by Craft Conductor: remove it from the list instead")
        if name not in on | off:
            raise UpgradeError(f"there's no {name} in the {self.mods_dir.name} folder")
        path, disabled = self.mods_dir / name, self.mods_dir / (name + ".disabled")
        if action == "disable" and name in on:
            path.rename(disabled)
            return f"{name} switched off (from the next restart)"
        if action == "enable" and name in off:
            disabled.rename(path)
            return f"{name} switched on (from the next restart)"
        if action == "remove":
            (path if name in on else disabled).unlink()
            return f"{name} removed"
        raise UpgradeError("nothing to do")

    # --------------------------------------------------------------- running
    def eula_accepted(self) -> bool:
        eula = self.server_dir / "eula.txt"
        return eula.exists() and "eula=true" in eula.read_text().replace(" ", "").lower()

    def launch_argv(self, lock: Lock | None = None, java: str | None = None) -> list[str]:
        lock = lock or self.lock
        if not lock.installed:
            raise UpgradeError("nothing is installed yet - run `craft-conductor update` first")
        java = java or self.java.select(lock.java_major or 8)
        mem = self.config.server.memory
        if mem == "auto":
            from .setup import suggested_memory_gb
            mem = f"{suggested_memory_gb()}G"
        gc = []
        if self.config.server.aikar_flags:
            from .jvmflags import aikar
            from .stats import heap_bytes
            gc = aikar(heap_bytes(mem, 4))
        return [java, f"-Xms{mem}", f"-Xmx{mem}", *gc, *self.config.server.jvm_args, *lock.launch]

    def new_process(self, lock: Lock | None = None) -> ServerProcess:
        s = self.config.server
        return ServerProcess(self.launch_argv(lock), self.server_dir, echo=self.echo, on_line=self.on_line,
                             cpu_cores=s.cpu_cores, priority=s.priority)

    def start_server(self, lock: Lock | None = None) -> ServerProcess:
        if not self.eula_accepted():
            raise UpgradeError(f"the Minecraft EULA has not been accepted ({self.server_dir / 'eula.txt'}); "
                               "run `craft-conductor init --accept-eula` or set eula=true yourself")
        proc = self.new_process(lock)
        started = time.time()
        proc.start()
        if self.on_process:
            self.on_process(proc)
        if not proc.wait_ready(self.config.server.startup_timeout):
            lines = proc.tail(400)
            self.last_start_lines = lines  # (the Dashboard explains what went wrong from these)
            proc.stop(self.config.server.stop_timeout)
            from .diagnose import diagnose
            self.last_diagnosis = diagnose(lines, self.server_dir, (lock or self.lock).mods, since=started)
            blame = self.last_diagnosis.summary
            if blame:
                log.error("%s", blame)
            tail = "\n".join(lines[-20:])
            raise UpgradeError(f"server did not finish starting{('. ' + blame) if blame else ''}:\n{tail}")
        self.last_diagnosis = None
        return proc

    def countdown(self, proc: ServerProcess, reason: str) -> None:
        steps = self.config.updates.warn_minutes
        for i, minutes in enumerate(steps):
            if not proc.running:
                return
            proc.say(f"Server restarting in {minutes} minute{'s' if minutes != 1 else ''}: {reason}")
            nxt = steps[i + 1] if i + 1 < len(steps) else 0
            self.sleep((minutes - nxt) * 60)
        proc.say("Restarting now!")

    # --------------------------------------------------------------- staging
    def _local_copy(self, mod: ModFile) -> Path | None:
        """A verified copy of ``mod`` already on disk (installed, or dropped in by hand)."""
        places = [self.mods_dir / mod.filename]
        if mod.manual and self.config.manual_dir:
            places.append(self.config.manual_dir / mod.filename)
        installed = next((m for m in self.lock.mods if m.key == mod.key), None)
        for path in places:
            if not path.is_file():
                continue
            if mod.sha1:
                if sha1_file(path) == mod.sha1.lower():
                    return path
            elif mod.manual or (installed and installed.version_id == mod.version_id):
                return path
        return None

    def missing_manual(self, plan: Plan) -> list[ModFile]:
        """Mods in ``plan`` that must be downloaded by hand and haven't been yet."""
        return [m for m in plan.mods if m.manual and self._local_copy(m) is None]

    def stage(self, plan: Plan, changes: Changes) -> Staged:
        missing = self.missing_manual(plan)
        if missing:
            if self.config.manual_dir:
                self.config.manual_dir.mkdir(parents=True, exist_ok=True)
            raise ManualDownloadRequired(missing, self.config.manual_dir)
        info = self.mojang.info(plan.minecraft)
        java = self.java.select(info.java_major)
        if self.staging_dir.exists():
            shutil.rmtree(self.staging_dir)
        mods_out = self.staging_dir / "mods"
        mods_out.mkdir(parents=True)

        for mod in plan.mods:
            local = self._local_copy(mod)
            if local:
                shutil.copy2(local, mods_out / mod.filename)
            else:
                log.info("downloading %s %s", mod.name, mod.version_number)
                self.http.download(mod.url, mods_out / mod.filename, sha1=mod.sha1, sha512=mod.sha512, sha256=mod.sha256)

        runtime = None
        if changes.runtime:
            rt_dir = self.staging_dir / "runtime"
            rt_dir.mkdir()
            log.info("installing %s %s for Minecraft %s", self.loader.name, plan.loader_version, plan.minecraft)
            runtime = self.loader.install(plan.minecraft, plan.loader_version, rt_dir, java)
        return Staged(self.staging_dir, java, info.java_major, runtime)

    def _swap(self, staged: Staged, plan: Plan) -> Lock:
        server = self.server_dir
        mods_dir = self.mods_dir
        mods_dir.mkdir(parents=True, exist_ok=True)
        for old in self.lock.mods:
            (mods_dir / old.filename).unlink(missing_ok=True)
        for mod in plan.mods:
            shutil.copy2(staged.dir / "mods" / mod.filename, mods_dir / mod.filename)

        new = copy.deepcopy(self.lock)
        if staged.runtime:
            rt_dir = staged.dir / "runtime"
            for name in set(self.lock.runtime_files) | set(staged.runtime.files):
                _remove(server / name)
            for name in staged.runtime.files:
                shutil.move(str(rt_dir / name), str(server / name))
            # Forge/NeoForge generate this for the user to edit; never overwrite theirs.
            jvm_args = rt_dir / "user_jvm_args.txt"
            if jvm_args.exists() and not (server / "user_jvm_args.txt").exists():
                shutil.copy2(jvm_args, server / "user_jvm_args.txt")
            new.launch = staged.runtime.launch
            new.runtime_files = staged.runtime.files
        new.minecraft = plan.minecraft
        new.loader = plan.loader
        new.loader_version = plan.loader_version
        new.java_major = staged.java_major
        new.mods = [copy.copy(m) for m in plan.mods]
        new.skipped = {b.key: b.reason for b in plan.dropped}
        return new

    # --------------------------------------------------------------- upgrade
    def apply(self, plan: Plan, server: ServerProcess | None = None, restart: bool = False,
              verify: bool | None = None, make_backup: bool = True) -> Result:
        """Apply ``plan``. If ``server`` is running it is stopped first.

        Without ``make_backup`` (a throwaway copy of a server, see rehearsal.py) no backup is made, and
        a failed update isn't put back.

        With ``restart`` the upgraded (or rolled back) server is left running and
        returned in :attr:`Result.process`.
        """
        if make_backup and not (server is not None and server.running):
            try:
                self.recover()  # (an earlier update cut off half-way is put right first)
            except UpgradeError as e:
                return Result(False, str(e), server)
        changes = plan.changes(self.lock)
        if changes.minecraft and self.lock.installed and plan.minecraft != self.lock.minecraft:
            local = self.unmanaged_jars()
            if local:
                return Result(False, "Minecraft compatibility is unverified for local files: " + ", ".join(local)
                              + ". Identify or disable them on the Mods page before upgrading.", server)
        if changes.empty:
            return Result(True, "already up to date", server)
        old_mc = self.lock.minecraft
        title = (f"Minecraft {old_mc or '(new install)'} -> {plan.minecraft}" if changes.minecraft
                 else f"mod updates for Minecraft {plan.minecraft}")
        will_boot = restart or (self.config.updates.verify_boot if verify is None else verify)
        if will_boot and not self.eula_accepted():
            return Result(False, "the Minecraft EULA has not been accepted; run `craft-conductor init --accept-eula`", server)

        try:
            staged = self.stage(plan, changes)
        except Exception as e:
            # Nothing has been touched yet; the running server keeps running.
            return Result(False, f"could not prepare update ({title}): {e}", server)

        was_running = server is not None and server.running
        if was_running:
            self.countdown(server, title)
            server.stop(self.config.server.stop_timeout)

        archive = None
        # A first install with no world yet has only the setup's own files: its backup is only for
        # putting them back if the install fails, and goes once it worked (not listed as a backup).
        worth_keeping = self.lock.installed or any(self.server_dir.glob("*/level.dat"))
        try:
            if make_backup and self.server_dir.exists() and any(self.server_dir.iterdir()):
                label = (f"before-install-{plan.minecraft}" if not old_mc else f"before-mod-updates-{plan.minecraft}"
                         if old_mc == plan.minecraft else f"before-{old_mc}-to-{plan.minecraft}")
                archive = backup.create(self.server_dir, self.config.backups.dir, label, self.config.backups.exclude)
                from . import snapshots
                snapshots.record(archive, self)
                if worth_keeping:
                    backup.copy_out(archive, self.config.backups.copy_to, self.config.root.name,
                                    self.config.backups.copy_keep)
            if make_backup:
                self._journal_begin(title, archive, plan)
        except Exception as e:
            # Nothing in the server folder has changed: start the old version again.
            shutil.rmtree(self.staging_dir, ignore_errors=True)
            full = isinstance(e, OSError) and e.errno == errno.ENOSPC
            message = (f"Update not done ({title}): the backup before it couldn't be made"
                       + (" because the disk is full; free some space, or keep fewer backups" if full else f": {e}")
                       + ". Nothing was changed.")
            log.error("%s", message)
            proc = None
            if (restart or was_running) and self.lock.installed:
                try:
                    proc = self.start_server()
                except Exception as e2:
                    message += f"\nThe server also failed to start again: {e2}"
            self.notifier.send(message)
            return Result(False, message, proc)

        proc = None
        try:
            self.server_dir.mkdir(parents=True, exist_ok=True)
            new_lock = self._swap(staged, plan)
            if will_boot:
                proc = self.start_server(new_lock)
                if not restart:
                    proc.stop(self.config.server.stop_timeout)
                    proc = None
            new_lock.failed_plans.pop(plan.fingerprint, None)
            self.lock = new_lock
            lockmod.save(self.config.root, self.lock)
        except Exception as e:
            log.exception("update failed; rolling back")
            if proc is not None and proc.running:
                proc.stop(self.config.server.stop_timeout)
            return self._rollback(plan, title, e, archive, (restart or was_running) and make_backup)
        finally:
            shutil.rmtree(self.staging_dir, ignore_errors=True)
        self._journal_end()  # (the new lock file is saved: the update is done)

        if archive is not None and not worth_keeping:
            from . import snapshots
            archive.unlink(missing_ok=True)
            snapshots.note_path(archive).unlink(missing_ok=True)
            archive = None
        backup.prune(self.config.backups.dir, self.config.backups.keep)
        lines = "\n".join(changes.summary())
        self.notifier.send(f"Updated: {title}\n{lines}")
        return Result(True, f"updated: {title}", proc, archive)

    def _rollback(self, plan: Plan, title: str, error: Exception, archive: Path | None,
                  restart: bool) -> Result:
        reason = str(error).splitlines()[0][:300] if str(error) else repr(error)
        if archive:
            try:
                backup.restore(archive, self.server_dir)
            except Exception as e:
                # The note about this update stays, so the next start puts the backup back first.
                message = (f"Update failed ({title}): {error}\nPutting the backup {archive.name} back failed too: {e}\n"
                           "The server wasn't started. If the disk is full, free some space; then start the server: "
                           "Craft Conductor puts the backup back first.")
                log.error("%s", message)
                try:  # (the reason goes into the lock file once the backup is back)
                    self._journal_write({**json.loads(self.journal_path.read_text(encoding="utf-8")), "error": reason})
                except (OSError, ValueError, TypeError):
                    pass
                self.notifier.send(message)
                return Result(False, message, None, archive)
        # Remember this exact combination so it is not retried until something changes.
        self.lock.failed_plans[plan.fingerprint] = reason
        lockmod.save(self.config.root, self.lock, touch=False)
        self._journal_end()
        message = f"Update failed and was rolled back ({title}): {error}"
        proc = None
        if restart and self.lock.installed:
            try:
                proc = self.start_server()
            except Exception as e:
                message += f"\nThe previous version also failed to start: {e}"
        self.notifier.send(message)
        return Result(False, message, proc, archive)

    # ---------------------------------------------------------------- import
    def import_existing(self) -> tuple[list[ModFile], list[str]]:
        """Identify jars already in ``mods/`` on Modrinth so craft-conductor can manage them.

        Returns the identified mods (now recorded in the lock) and the unrecognised file names.
        """
        from .mods.modrinth import ModrinthProvider

        modrinth = self.providers.get("modrinth") or ModrinthProvider(self.http)
        mods_dir = self.mods_dir
        jars = {sha1_file(p): p for p in sorted(mods_dir.glob("*.jar"))} if mods_dir.is_dir() else {}
        found = modrinth.identify(list(jars))
        identified, unknown = [], []
        for sha1, path in jars.items():
            version = found.get(sha1)
            if not version:
                unknown.append(path.name)
                continue
            project = modrinth.project(version["project_id"])
            identified.append(ModFile(
                key=project.key, source="modrinth", project_id=project.id, name=project.name,
                version_id=version["id"], version_number=version["version_number"],
                filename=path.name, url="", sha1=sha1,
            ))
        known = {m.key for m in self.lock.mods}
        self.lock.mods += [m for m in identified if m.key not in known]
        if self.lock.minecraft is None and self.config.server.minecraft != "latest":
            self.lock.minecraft = self.config.server.minecraft
        self.lock.loader = self.lock.loader or self.config.server.loader
        lockmod.save(self.config.root, self.lock)
        return identified, unknown


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()
