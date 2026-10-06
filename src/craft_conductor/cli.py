from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import re
import secrets
import socket
import sys
import webbrowser
from pathlib import Path

from . import __version__, backup, config as configmod, licenses, lock as lockmod, notice, selfupdate
from . import setup as setupmod
from .config import ConfigError, ModSpec
from .daemon import Daemon, request_path, request_stop, running_pid, self_update_request_path
from .manager import Manager, UpgradeError
from .planner import CREATE
from .mods import ModError, providers_for
from .http import HttpClient, HttpError
from .java import JavaError
from .java import JavaManager
from .players import ACTIONS, PlayerError, Players
from .properties import read_properties, write_properties
from .rcon import Rcon, RconError

log = logging.getLogger("craft_conductor")


def _manager(args) -> Manager:
    return Manager(configmod.load(args.root), echo=not getattr(args, "quiet", False))


def _server_port_open(manager: Manager) -> bool:
    port = int(read_properties(manager.server_dir / "server.properties").get("server-port", "25565"))
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


# ---------------------------------------------------------------- commands
EULA_NOTE = ("read https://aka.ms/MinecraftEULA, then accept it with --accept-eula "
             "or by writing eula=true to eula.txt in the server directory")


def scaffold(root: Path, loader: str, minecraft: str, server_dir: str | None = None,
             accept_eula: bool = False, force: bool = False) -> configmod.Config | None:
    """Write a fresh craft-conductor.toml (and server dir) under ``root``."""
    path = root / configmod.CONFIG_NAME
    if path.exists() and not force:
        print(f"{path} already exists (use --force to overwrite)")
        return None
    root.mkdir(parents=True, exist_ok=True)
    path.write_text(configmod.render_template(loader, minecraft))
    if server_dir:
        configmod.set_value(path, "server", "dir", json.dumps(Path(server_dir).resolve().as_posix()))
    cfg = configmod.load(root)
    cfg.server.dir.mkdir(parents=True, exist_ok=True)
    if accept_eula:
        (cfg.server.dir / "eula.txt").write_text(
            "# Accepted via craft-conductor --accept-eula (https://aka.ms/MinecraftEULA)\neula=true\n")
    print(f"wrote {path}")
    return cfg


def cmd_init(args) -> int:
    cfg = scaffold(args.root, args.loader, args.minecraft, args.server_dir, args.accept_eula, args.force)
    if cfg is None:
        return 1
    if not (cfg.server.dir / "eula.txt").exists():
        print(f"note: {EULA_NOTE}")
    print("next: add mods with `craft-conductor add <slug>` (or `craft-conductor import` for an existing server), then `craft-conductor update`")
    return 0


def _add_mods(cfg: configmod.Config, source: str, ids: list[str], optional: bool) -> bool:
    providers = providers_for(cfg, HttpClient())
    listed = list(cfg.mods)
    for mod_id in ids:
        try:
            project = providers[source].project(mod_id)
        except ModError as e:
            print(f"error: {e}")
            return False
        if project.server_side == "unsupported":
            print(f"skipping {project.name}: it is a client-side only mod")
            continue
        if any(s.source == source and s.id in (mod_id, project.id, project.slug) for s in listed):
            print(f"{project.name} is already listed")
            continue
        spec = ModSpec(source, project.slug or project.id, required=not optional)
        configmod.append_mod(cfg.path, spec)
        listed.append(spec)
        print(f"added {project.name}{' (optional)' if optional else ''}")
    return True


def cmd_create(args) -> int:
    """Build a brand-new server: config, mods, server.properties, Java, loader, first boot."""
    root: Path = args.dir.resolve()
    cfg = scaffold(root, args.loader, args.minecraft, None, args.accept_eula, args.force)
    if cfg is None:
        return 1
    configmod.set_value(cfg.path, "server", "memory", json.dumps(args.memory))
    if args.java:
        configmod.set_value(cfg.path, "java", "version", str(args.java))
    cfg = configmod.load(root)
    for source, ids, optional in (("modrinth", args.mod, False), ("modrinth", args.optional_mod, True),
                                  ("curseforge", args.curseforge, False)):
        if ids and not _add_mods(cfg, source, ids, optional):
            return 1
        cfg = configmod.load(root)

    props = {"server-port": str(args.port), "motd": args.motd, "max-players": str(args.max_players),
             "difficulty": args.difficulty, "gamemode": args.gamemode}
    if args.seed:
        props["level-seed"] = args.seed
    password = None
    if args.rcon:
        password = secrets.token_urlsafe(18)
        props.update({"enable-rcon": "true", "rcon.port": "25575", "rcon.password": password})
    write_properties(cfg.server.dir / "server.properties", props)

    m = Manager(cfg, echo=not args.quiet)
    decision, changes = m.check()
    _print_decision(m, decision, changes)
    if not decision.plan:
        print("\nconfig written, but nothing can be installed yet - fix the blockers above and run `craft-conductor update`")
        return 1
    booted = m.eula_accepted()
    result = m.apply(decision.plan, verify=booted)
    print(result.message)
    if not result.ok:
        return 1
    print(f"\nserver built in {root}")
    print(f"  Minecraft {m.lock.minecraft}, {m.lock.loader} {m.lock.loader_version}, "
          f"Java {m.lock.java_major} ({m.launch_argv()[0]})")
    if password:
        print("  RCON enabled on port 25575 (password saved in server.properties)")
    if not booted:
        print(f"  not test-booted: {EULA_NOTE}")
    print(f"start it with:  cd {root} && craft-conductor run")
    return 0


def cmd_import(args) -> int:
    m = _manager(args)
    if m.config.server.minecraft == "latest":
        print("set [server] minecraft in craft-conductor.toml to the version this server runs now, then re-run")
        return 1
    identified, unknown = m.import_existing()
    listed = {(s.source, s.id) for s in m.config.mods}
    added = 0
    for mod in identified:
        if ("modrinth", mod.project_id) in listed:
            continue
        configmod.append_mod(m.config.path, ModSpec("modrinth", mod.project_id))
        added += 1
        print(f"  + {mod.name} ({mod.version_number})")
    print(f"identified {len(identified)} mod(s) on Modrinth, added {added} to craft-conductor.toml")
    if unknown:
        print("not recognised (left in place, not managed - add them by hand if they are on CurseForge):")
        for name in unknown:
            print(f"  ? {name}")
    return 0


def cmd_add(args) -> int:
    if not _add_mods(configmod.load(args.root), args.source, args.ids, args.optional):
        return 1
    print("run `craft-conductor check` to see what would be installed")
    return 0


def cmd_remove(args) -> int:
    cfg = configmod.load(args.root)
    ok = configmod.remove_mod(cfg.path, args.source, args.id)
    print(f"removed {args.id}" if ok else f"{args.id} is not listed in craft-conductor.toml")
    return 0 if ok else 1


def _print_decision(m: Manager, decision, changes) -> None:
    print(f"installed: Minecraft {m.lock.minecraft or '(nothing)'}"
          f"{f' / {m.lock.loader} {m.lock.loader_version}' if m.lock.loader_version else ''}"
          f" - latest release is {decision.latest}")
    for plan in decision.blocked:
        why = [b.explain(plan.minecraft, plan.loader) for b in plan.blockers]
        if plan.loader_version is None:
            why.insert(0, plan.loader_problem)
        print(f"\nMinecraft {plan.minecraft} is blocked by:")
        for line in why:
            print(f"  x {line}")
    if decision.plan:
        p = decision.plan
        for b in p.dropped:
            print(f"  (leaving out {b.name}: {b.reason})")
        if changes is None or changes.empty:
            print(f"\nup to date (Minecraft {p.minecraft})")
        else:
            print(f"\nready to update to Minecraft {p.minecraft} with {p.loader} {p.loader_version}:")
            for line in changes.summary():
                print(f"  {line}")
        missing = m.missing_manual(p)
        if missing:
            print("\nmanual download needed - these authors block automatic downloads.")
            print(f"download each file and put it in {m.config.manual_dir}:")
            for mod in missing:
                print(f"  -> {mod.name}: {mod.filename}\n     {mod.manual_url}")
    elif decision.policy == CREATE:
        print("\nnothing installed: the Minecraft version and server type in craft-conductor.toml are kept as they are;"
              " change [server] minecraft, or the mods, to try another combination")
        try:  # (other versions are only suggested, never used by themselves)
            others = m.planner().alternatives(decision.blocked[0].minecraft) if decision.blocked else []
        except Exception:
            others = []
        if others:
            print(f"these choices appear to work on Minecraft {', '.join(others)}")
    else:
        print("\nno installable combination found")
    unmanaged = m.unmanaged_jars()
    if unmanaged:
        print(f"\nwarning: {len(unmanaged)} jar(s) in mods/ are not managed by Craft Conductor and will not be updated:")
        for name in unmanaged:
            print(f"  ! {name}")


def cmd_check(args) -> int:
    m = _manager(args)
    decision, changes = m.check(args.to)
    if args.json:
        out = {
            "installed": m.lock.minecraft,
            "latest": decision.latest,
            "target": decision.plan.minecraft if decision.plan else None,
            "changes": changes.summary() if changes else [],
            "blocked": {p.minecraft: [b.name for b in p.blockers] or [f"{p.loader} loader"]
                        for p in decision.blocked},
        }
        print(json.dumps(out, indent=2))
    else:
        _print_decision(m, decision, changes)
    return 0


def cmd_update(args) -> int:
    m = _manager(args)
    if running_pid(m):
        request_path(m).parent.mkdir(parents=True, exist_ok=True)
        request_path(m).write_text(args.to or "")
        print("craft-conductor run is managing this server; it will check for updates now and apply them")
        return 0
    if _server_port_open(m):
        print("the server port is in use - stop the server first (or let `craft-conductor run` manage it)")
        return 1
    decision, changes = m.check(args.to, retry_failed=True)
    _print_decision(m, decision, changes)
    if not decision.plan or not changes or changes.empty or args.dry_run:
        return 0 if decision.plan else 1
    if not args.yes and interactive():
        if input("\napply? [y/N] ").strip().lower() not in ("y", "yes"):
            return 1
    result = m.apply(decision.plan, restart=False)
    print(result.message)
    if result.backup:
        print(f"backup: {result.backup}")
    return 0 if result.ok else 1


def _run_daemon(d: Daemon, web: bool) -> int:
    code = d.run(web=web)
    if d.restart_requested:
        selfupdate.restart()
    return code


def cmd_run(args) -> int:
    m = _manager(args)
    if args.web_port:
        m.config.web.port = args.web_port
    if args.web_host:
        m.config.web.host = args.web_host
    return _run_daemon(Daemon(m), web=args.web or m.config.web.enabled)


def default_home() -> Path:
    """Where `craft-conductor start` keeps its server when no craft-conductor.toml is in the current folder."""
    return Path(os.environ.get("CRAFT_CONDUCTOR_HOME") or Path.home() / "craft-conductor").resolve()


def _ask(question: str, default: str, choices: tuple[str, ...] | None = None) -> str:
    hint = f" [{default}]" if default else ""
    while True:
        answer = input(f"{question}{hint}: ").strip() or default
        if choices is None or answer in choices:
            return answer
        print(f"  please answer one of: {', '.join(choices)}")


def _wizard(root: Path) -> bool:
    print(f"\nWelcome to Craft Conductor! Let's set up your Minecraft server in {root}\n"
          "(Press Enter to take the suggestion in [brackets].)\n")
    loader = _ask("Mod loader: fabric, neoforge, forge, quilt, paper, purpur or vanilla", "fabric", configmod.LOADERS)
    minecraft = _ask("Minecraft version ('latest' = the newest release for this server type)", "latest")
    memory = _ask("Memory for the server, e.g. 4G or 8G", "4G")
    mods = []
    if loader != "vanilla":
        answer = _ask("Mods to install from Modrinth, separated by commas (e.g. lithium, ferrite-core), "
                      "or leave empty", "")
        mods = [x.strip() for x in answer.split(",") if x.strip()]
        if loader in ("fabric", "quilt") and mods and "fabric-api" not in mods:
            mods.insert(0, "fabric-api")
    # (Off unless answered yes: the control panel only listens on this computer by default.)
    remote = _ask("Open the control panel from other devices on your network too, like your phone or "
                  "another PC? (yes/no)", "no", ("yes", "no", "y", "n")) in ("yes", "y")
    print("\nMinecraft servers require accepting Mojang's EULA: https://aka.ms/MinecraftEULA")
    if _ask("Do you accept the Minecraft EULA? (yes/no)", "no", ("yes", "no", "y", "n")) not in ("yes", "y"):
        print("The server can't run without accepting the EULA. Nothing was set up.")
        return False
    print("\nDownloading and building your server. This can take a few minutes...\n")
    ns = argparse.Namespace(
        root=root, dir=root, loader=loader, minecraft=minecraft, mod=mods, optional_mod=[], curseforge=[],
        memory=memory, java=None, port=25565, motd="A Minecraft server managed by Craft Conductor", max_players=20,
        difficulty="normal", gamemode="survival", seed=None, rcon=False, accept_eula=True,
        force=setupmod.is_pending(root), quiet=True)  # replace a placeholder left by `craft-conductor start`
    if cmd_create(ns) != 0:
        return False
    if remote:
        configmod.set_value(root / configmod.CONFIG_NAME, "web", "host", '"0.0.0.0"')
    return True


def has_display() -> bool:
    """Whether a browser can be opened here (not an SSH session on a headless server)."""
    if sys.platform.startswith("linux") or "bsd" in sys.platform:
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return True


def lan_ip() -> str | None:
    """This machine's address on the local network (no traffic is sent). In a container, set
    CRAFT_CONDUCTOR_LAN_IP to the host computer's address so links and QR codes point there."""
    if os.environ.get("CRAFT_CONDUCTOR_LAN_IP"):
        return os.environ["CRAFT_CONDUCTOR_LAN_IP"].strip()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # a documentation-only address; nothing is sent
            ip = s.getsockname()[0]
            return None if ip.startswith("127.") else ip
    except OSError:
        return None


def cmd_setup(args) -> int:
    """Set up a new server by answering questions in the terminal (the web UI does the same)."""
    root = args.root if (args.root / configmod.CONFIG_NAME).exists() else default_home()
    if lockmod.load(root).installed:
        print(f"a server is already set up in {root}")
        return 1
    if not interactive():
        print("`craft-conductor setup` asks questions, so it needs a terminal; `craft-conductor start` sets up in the browser instead")
        return 1
    if not _wizard(root):
        return 1
    setupmod.clear_pending(root)
    print("done - start it with `craft-conductor start`")
    return 0


def cmd_start(args) -> int:
    """The double-click entry point: open the control panel, which lists your servers.

    Nothing starts by itself: each server waits for its Start button in the web UI.
    """
    from . import webauth
    from .hub import Hub, running_hub

    home = default_home()
    home.mkdir(parents=True, exist_ok=True)
    here = args.root.resolve() if (args.root / configmod.CONFIG_NAME).exists() else None
    hub = Hub(home)
    if here and here != home:
        hub.add_folder(here)  # list the server in this folder too
    # The control panel only listens on this computer (127.0.0.1) unless it's been asked to do
    # otherwise: --web-host, or Remote access in the panel. A computer without a screen is no
    # exception: it's reached through an SSH tunnel until network access is turned on.
    if args.web_host:
        hub.web.host = args.web_host
    if args.web_port:
        hub.web.port = args.web_port
    first_password = None
    if not has_display() or hub.web.host not in ("127.0.0.1", "localhost", "::1"):
        # Nobody at this computer's screen (or reachable from others): a random one-time password
        # rather than the built-in one, which only works in a browser on this computer anyway.
        from .webauth import AuthStore
        first_password = AuthStore(hub).first_run_password()
    browser = not args.no_browser and has_display()
    port = hub.web.port
    url = f"http://localhost:{port}/"
    if pid := running_hub(home):
        print(f"Craft Conductor is already running (pid {pid}): {url}")
        if browser:
            webbrowser.open(url)
        return 0
    # A server kept in the home folder by craft-conductor 0.1-0.3 that never finished installing
    # goes back to its setup page instead of trying (and failing) to install again.
    if (home / configmod.CONFIG_NAME).exists() and not lockmod.load(home).installed \
            and not setupmod.is_pending(home):
        setupmod.mark_pending(home)
    servers = hub.discover()
    lines = [f"  Your servers:   {len(servers) or 'none yet - create one in the browser'}"
             if servers else "  Welcome to Craft Conductor! Create your first server in the browser.",
             f"  Control panel:  {url}"]
    if hub.web.host in ("0.0.0.0", "::") and (ip := lan_ip()):
        lines.append(f"  From other devices on your network:  http://{ip}:{port}/")
    elif not has_display():
        lines.append(f"  From your own PC, tunnel over SSH:  ssh -L {port}:localhost:{port} "
                     f"{getpass.getuser()}@<this server>  then open http://localhost:{port}/")
    lines += [f"  Password:       {first_password or webauth.describe(webauth.AuthStore(hub).get())}"
              + ("   <- one-time; you'll choose your own at the first sign-in" if first_password else ""), "",
              "  Servers only start when you press Start in the control panel.",
              "  Keep this window open while they run, and press Ctrl+C to stop everything."]
    print("\n" + "\n".join(lines) + "\n", flush=True)
    _tag_log_lines()
    hub.open_browser = browser
    code = hub.run()
    if hub.restart_requested:
        selfupdate.restart()
    return code


def _auth_target(args):
    """Whose sign-in `craft-conductor web-password` changes: a server folder run with `craft-conductor run`, or the
    control panel that `craft-conductor start` opens (kept in the craft-conductor home folder)."""
    from .hub import Hub
    home = default_home()
    root = args.root.resolve()
    if (root / configmod.CONFIG_NAME).exists() and root != home:
        return configmod.load(root)
    return Hub(home)


def _tag_log_lines() -> None:
    """With several servers in one window, say which server each message is about."""
    from .daemon import current_server

    class Tag(logging.Filter):
        def filter(self, record):
            sid = current_server()
            record.server_tag = f"{sid}: " if sid else ""
            return True
    for handler in logging.getLogger().handlers:
        handler.addFilter(Tag())
        handler.setFormatter(logging.Formatter("[craft-conductor] %(server_tag)s%(message)s"))


def cmd_web_password(args) -> int:
    from . import webauth

    cfg = _auth_target(args)
    store = webauth.AuthStore(cfg)
    if cfg.web.password:
        print("the web UI password is set in craft-conductor.toml under [web] password; change it there")
        return 0 if not (args.reset or args.set or args.pin or args.none) else 1
    try:
        if args.reset:
            store.reset()
            print(f"the web UI password is back to {webauth.DEFAULT_PASSWORD}; "
                  "you'll be asked to choose a new one when you sign in")
        elif args.set or args.pin:
            mode, what = ("pin", "PIN") if args.pin else ("password", "password")
            secret = getpass.getpass(f"New {what}: ")
            webauth.validate(mode, secret)
            if getpass.getpass(f"Type the {what} again: ") != secret:
                print(f"the two {what}s don't match; nothing changed")
                return 1
            store.set(mode, secret)
            print(f"{what} changed")
        else:
            print(f"web UI sign-in: {webauth.describe(store.get())}")
            print("change it with --set (password), --pin, or --reset (back to PASSWORD)")
    except ConfigError as e:
        print(f"error: {e}")
        return 1
    return 0


def cmd_join(args) -> int:
    """Set up this computer's Minecraft to play on a friend's craft-conductor server."""
    from . import join
    mc_dir = args.minecraft_dir.resolve() if args.minecraft_dir else None
    if args.from_server:
        # A server on this computer: build its pack directly (e.g. to play on it yourself).
        from .clientpack import PackBuilder
        m = Manager(configmod.load(args.from_server.resolve()), echo=False)
        port = read_properties(m.server_dir / "server.properties").get("server-port", "25565")
        pack = PackBuilder(m).build("localhost" if port == "25565" else f"localhost:{port}")
        return _join(args, None, pack, mc_dir)
    from . import clipboard, desktop
    if args.invite:
        text = args.invite
    elif invite := join.invite_from_name(sys.executable if selfupdate.frozen() else sys.argv[0]) or clipboard.invite():
        text = invite.code
    elif desktop.windowless() or (interactive() and not args.console and not args.yes):
        return _join(args, None, None, mc_dir)  # the page asks for the invite
    elif interactive():
        text = input("Paste the invite from the server's owner: ")
    else:
        print("usage: craft-conductor join <invite>")
        return 2
    try:
        invite = join.parse_invite(text)
    except join.JoinError as e:
        print(f"error: {e}")
        return 2
    return _join(args, invite, None, mc_dir)


def _join(args, invite, pack, mc_dir) -> int:
    """The page in the browser when someone's there to use it; otherwise the console."""
    from . import join, launchers, urlhandler
    urlhandler.register()  # later invites' "Open in craft-conductor" opens this craft-conductor (standalone builds)
    targets = [t.strip() for t in (args.launcher or "").split(",") if t.strip()]
    if any(t not in launchers.KEYS for t in targets):
        print(f"error: --launcher takes {', '.join(launchers.KEYS)}")
        return 2
    from . import desktop
    if not (args.yes or args.console or targets or args.no_launcher) and (interactive() or desktop.windowless()):
        from . import joinui
        code = joinui.run(invite, pack=pack, mc_dir=mc_dir)
        if code == joinui.START_SERVER:  # they'd rather run a server of their own
            return _main(build_parser().parse_args(["start"]))
        if code is not None:
            return code
        print("Couldn't open a browser; continuing here.\n")
    return join.run_interactive(invite, confirm=not args.yes and interactive(), open_launcher=not args.no_launcher,
                                pack=pack, mc_dir=mc_dir, targets=targets or ["minecraft"])


def cmd_stop(args) -> int:
    from .hub import hub_stop_path, running_hub
    home = default_home()
    if not (args.root / configmod.CONFIG_NAME).exists() or args.root.resolve() == home:
        if pid := running_hub(home):
            hub_stop_path(home).write_text("stop")
            print(f"asked Craft Conductor (pid {pid}) to stop its servers and exit")
            return 0
    m = _manager(args)
    pid = running_pid(m)
    if not pid:
        print("craft-conductor run is not running")
        return 1
    request_stop(m)
    print(f"asked Craft Conductor (pid {pid}) to stop the server")
    return 0


def cmd_status(args) -> int:
    m = _manager(args)
    lk = m.lock
    pid = running_pid(m)
    print(f"server dir: {m.server_dir}")
    print(f"daemon:     {'running (pid %s)' % pid if pid else 'not running'}")
    print(f"minecraft:  {lk.minecraft or '(not installed)'}")
    print(f"loader:     {lk.loader or m.config.server.loader} {lk.loader_version or ''}")
    print(f"java:       {lk.java_major and f'Java {lk.java_major} required' or '-'}"
          f"{f' (forced to Java {m.config.java_version})' if m.config.java_version else ''}")
    print(f"updated:    {lk.updated_at or '-'}")
    print(f"mods ({len(lk.mods)}):")
    for mod in lk.mods:
        dep = f"  [dependency of {mod.dependency_of}]" if mod.dependency_of else ""
        print(f"  {mod.name:30} {mod.version_number}{dep}")
    for key, reason in lk.skipped.items():
        print(f"  (not installed) {key}: {reason}")
    if lk.failed_plans:
        print("failed updates (will not be retried until something changes):")
        for fp, err in lk.failed_plans.items():
            print(f"  {fp}: {err}")
    return 0


def cmd_java(args) -> int:
    cfg = configmod.load(args.root)
    jm = JavaManager(cfg)
    action = args.java_command
    if action == "list":
        users = jm.store.users()
        print(f"shared Java, for every server on this computer ({jm.dir}):")
        releases = jm.store.releases()
        for major, rels in releases.items():
            used = [u.get("name") or u["root"] for u in users if u.get("shared") and u.get("major") == major]
            for i, j in enumerate(rels):
                state = "newest" if i == 0 else ("still running a server" if jm.store.running(j) else "old")
                print(f"  Java {major:<3} {j.release:24} {state:8} {j.binary}")
            print(f"           used by: {', '.join(used) or 'no server'}")
        if not releases:
            print("  (none)")
        if cfg.java_versions:
            print("configured in [java.versions]:")
            for major, path in sorted(cfg.java_versions.items()):
                print(f"  Java {major:<3} {path}")
        print("found on this computer:")
        found = [f for f in jm.found() if f.source in ("JAVA_HOME", "installed", "default") and f.info]
        for f in found:
            why = f"  (not usable: {f.problem})" if f.problem else ""
            print(f"  Java {f.info.major:<3} {f.info.arch or '?':8} {f.path}{why}")
        if not found:
            print("  (none)")
        forced = cfg.java_version
        print(f"server uses: {f'Java {forced} (forced)' if forced else 'the version Minecraft needs (auto)'}"
              f"{', downloading it if missing' if cfg.java_auto_install else ''}")
        lk = lockmod.load(cfg.root)
        if lk.java_major:
            try:
                c = jm.choose(lk.java_major, offers=True)
                print(f"current server: Minecraft {lk.minecraft} needs Java {lk.java_major} -> {c.note}")
                for f in c.newer:
                    print(f"  also here: Java {f.info.major} ({f.path}); some loaders and older mods break on a newer "
                          f"Java: `craft-conductor java use {f.info.major}` to use it anyway")
            except JavaError as e:
                print(f"current server: {e}")
    elif action == "install":
        for major in args.major:
            j = jm.install(major)
            print(f"Java {major} ({j.release}) is in the shared Java folder: {j.binary}")
    elif action == "update":
        changed = jm.update()
        for major, old, new in changed:
            print(f"Java {major}: {old} -> {new} (servers move to it at their next start; "
                  f"{old} is removed once no server runs on it)")
        if not changed:
            print("the shared Java is up to date")
    elif action == "remove":
        try:
            print(f"removed Java {args.major}" if jm.remove(args.major) else f"there's no shared Java {args.major}")
        except JavaError as e:
            print(f"Java {args.major} stays: {e}")
            return 1
    elif action == "use":
        value = args.version
        if value != "auto":
            if not value.isdigit():
                print('use a major version such as 21, or "auto"')
                return 1
            required = lockmod.load(cfg.root).java_major
            if required and int(value) < required:
                print(f"Minecraft {lockmod.load(cfg.root).minecraft} needs Java {required}+")
                return 1
        configmod.set_value(cfg.path, "java", "version", json.dumps(value) if value == "auto" else value)
        print(f"server will use {'the Java version Minecraft needs' if value == 'auto' else f'Java {value}'}"
              " (applies at the next start)")
    return 0


def cmd_player(args) -> int:
    m = _manager(args)
    running = bool(running_pid(m)) or _server_port_open(m)
    rcon = None

    def send(command: str) -> None:
        reply = rcon.command(command)
        if reply and re.search(r"does not exist|no player was found|unknown player", reply, re.I):
            # The server looks names up with Mojang itself; it says this when that fails.
            raise PlayerError(f"the server says: {reply.strip()}. Check the spelling; if it's right, "
                              "Mojang's lookup service may be busy, so try again in a minute")
        if reply:
            print(reply)
    if running:
        try:
            rcon = Rcon.from_server_dir(m.server_dir).__enter__()
        except (RconError, OSError) as e:
            print(f"the server is running but Craft Conductor can't reach its console: {e}\n"
                  "enable RCON in server.properties, or use the web UI's Players page")
            return 1
    try:
        players = Players(m.server_dir, m.http, send if running else None)
        if args.action == "list":
            s = players.summary()
            ops = ", ".join(f"{o['name']} (level {o['level']})" for o in s["ops"])
            print(f"operators:  {ops or '-'}")
            print(f"whitelist:  {'on' if s['whitelist_enabled'] else 'off'} - "
                  f"{', '.join(w['name'] for w in s['whitelist']) or 'nobody'}")
            print(f"banned:     {', '.join(b['name'] for b in s['bans']) or '-'}")
            print(f"banned IPs: {', '.join(b['ip'] for b in s['ip_bans']) or '-'}")
            if running:
                print(rcon.command("list"))
            return 0
        print(players.act(args.action, args.name or "", args.reason))
        return 0
    except PlayerError as e:
        print(f"error: {e}")
        return 1
    finally:
        if rcon:
            rcon.__exit__(None, None, None)


def cmd_notice(args) -> int:
    print(notice.as_text())
    root = args.root if (args.root / configmod.CONFIG_NAME).exists() else None
    if args.accept:
        notice.accept(root, by="cli")
        print("\naccepted")
    else:
        print(f"\n{'accepted' if notice.accepted(root) else 'not accepted yet (run `craft-conductor notice --accept`)'}")
    return 0


def cmd_licenses(args) -> int:
    if args.full:
        texts = licenses.full_texts()
        if not texts:
            print("full license texts are bundled only in the downloadable executables; see "
                  "https://github.com/silverWRX03/craft-conductor/blob/main/THIRD_PARTY_NOTICES.md")
            return 0
        for name, text in texts:
            print(f"{'=' * 78}\n{name}\n{'=' * 78}\n{text}\n")
        return 0
    print(licenses.as_text())
    print("\nFull details: THIRD_PARTY_NOTICES.md, or `craft-conductor licenses --full` in the downloadable executables")
    return 0


def _update_channel(args) -> str:
    """The channel to look on: --channel, else this server's [craft-conductor] update_channel,
    else the control panel's setting (Craft Conductor settings → About)."""
    if getattr(args, "channel", None):
        return args.channel
    if (args.root / configmod.CONFIG_NAME).exists():
        return configmod.load(args.root).self_update_channel
    from .hub import Hub
    return Hub(default_home()).update_channel()


def cmd_self_update(args) -> int:
    channel = _update_channel(args)
    release = selfupdate.check(HttpClient(), channel=channel)
    if release is None:
        print(f"Craft Conductor {__version__} is the latest version ({channel} channel)")
        return 0
    print(f"Craft Conductor {release.version}{' (beta)' if release.prerelease else ''} is available "
          f"(you have {__version__}): {release.url}")
    if release.notes:
        print("\n" + release.notes.strip()[:1500] + "\n")
    if args.check:
        return 0
    ok, why = selfupdate.install_method(release)
    if not ok:
        print(why)
        return 1
    root_cfg = args.root / configmod.CONFIG_NAME
    if root_cfg.exists():
        m = Manager(configmod.load(args.root))
        if running_pid(m):
            path = self_update_request_path(m)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(release.version)
            print("`craft-conductor run` is managing a server; it will install the update and restart itself now")
            return 0
    if not args.yes and (not interactive() or input("install it? [y/N] ").strip().lower() not in ("y", "yes")):
        return 1
    print(selfupdate.install(release))
    return 0


def _panel_service(args) -> int:
    """`craft-conductor service install --panel`: the control panel at boot, for a computer without a screen
    that you manage from another one (see docs/headless.md)."""
    from . import service, webauth
    from .hub import Hub, running_hub
    home = default_home()
    try:
        if args.action == "install":
            if running_hub(home):
                print("Craft Conductor is already running; stop it first (Quit in the control panel, or Ctrl+C), then install the service")
                return 1
            home.mkdir(parents=True, exist_ok=True)
            hub = Hub(home)
            if getattr(args, "network", False) and getattr(args, "local_only", False):
                print("pick one: --network (open to your network) or --local-only (this machine only)")
                return 1
            if getattr(args, "local_only", False):
                hub.save_web(host="127.0.0.1")  # a rented server: the panel is reached through SSH, never the internet
            elif getattr(args, "network", False):
                hub.save_web(host="0.0.0.0")  # asked for: managed from other computers on the network
            # (otherwise what's saved: this machine only, unless network access was turned on before)
            local_only = hub.web.host in ("127.0.0.1", "localhost", "::1")
            first = webauth.AuthStore(hub).first_run_password()
            for line in service.install(home, panel=True):
                print(line)
            if local_only:
                from .remoteinstall import LOCAL_PORT
                print("\nThe control panel only listens on this server itself (not on the internet).")
                print(f"On your own computer, reach it through SSH:  ssh -N -L {LOCAL_PORT}:127.0.0.1:{hub.web.port} <you>@<this server>")
                print(f"then open http://localhost:{LOCAL_PORT}/  (Craft Conductor's \"Open the control panel\" button does both)")
                if not getattr(args, "local_only", False):
                    print("To open it to your home network instead: craft-conductor service install --panel --network")
            else:
                ip = lan_ip()
                print(f"\ncontrol panel: http://{ip or '<this computer>'}:{hub.web.port}/  (open it on your own computer)")
            if first:
                print(f"first sign-in password: {first}   (one-time: you'll choose your own; also in {home / '.craft-conductor' / 'first-password.txt'})")
            if local_only:
                print("let players in through the firewall, e.g.: sudo ufw allow OpenSSH && sudo ufw allow 25565/tcp && sudo ufw allow 8766/tcp && sudo ufw enable")
            else:
                print(f"allow it through the firewall if you use one, e.g.: sudo ufw allow {hub.web.port}/tcp && sudo ufw allow 25565/tcp")
        elif args.action == "uninstall":
            print(service.uninstall(home, panel=True))
        else:
            print(service.status(home, panel=True))
    except service.ServiceError as e:
        print(f"error: {e}")
        return 1
    return 0


def cmd_service(args) -> int:
    from . import service

    if args.panel:
        return _panel_service(args)
    cfg = configmod.load(args.root)
    try:
        if args.action == "install":
            if running_pid(Manager(cfg)):
                print("Craft Conductor is already running this server; stop it first (`craft-conductor stop`), then install the service")
                return 1
            for line in service.install(cfg.root):
                print(line)
            print(f"control panel: http://localhost:{cfg.web.port}/  (first sign-in: PASSWORD)")
        elif args.action == "uninstall":
            print(service.uninstall(cfg.root))
        else:
            print(service.status(cfg.root))
    except service.ServiceError as e:
        print(f"error: {e}")
        return 1
    return 0


def cmd_cmd(args) -> int:
    m = _manager(args)
    try:
        with Rcon.from_server_dir(m.server_dir) as rcon:
            print(rcon.command(" ".join(args.words)))
    except (RconError, OSError) as e:
        print(f"error: {e}")
        return 1
    return 0


def cmd_backup(args) -> int:
    m = _manager(args)
    if args.list:
        for path in backup.list_backups(m.config.backups.dir):
            print(f"{path.name}  ({path.stat().st_size / 1e6:.1f} MB)")
        return 0
    if running_pid(m) or _server_port_open(m):
        print("warning: the server is running; the backup may catch the world mid-save")
    path = backup.create(m.server_dir, m.config.backups.dir, args.label, m.config.backups.exclude)
    backup.prune(m.config.backups.dir, m.config.backups.keep)
    print(f"created {path}")
    return 0


def cmd_restore(args) -> int:
    m = _manager(args)
    if running_pid(m) or _server_port_open(m):
        print("stop the server first")
        return 1
    backups = backup.list_backups(m.config.backups.dir)
    archive = Path(args.archive) if args.archive else (backups[-1] if backups else None)
    if archive and not archive.exists():
        archive = m.config.backups.dir / args.archive
    if not archive or not archive.exists():
        print("no backup found")
        return 1
    if not args.yes and input(f"replace {m.server_dir} with {archive.name}? [y/N] ").strip().lower() != "y":
        return 1
    try:
        backup.restore(archive, m.server_dir)
    except backup.RestoreError as e:
        print(e)
        return 1
    m.forget_interrupted_update()
    print(f"restored {archive.name}")
    print("note: craft-conductor.lock.json was not changed; run `craft-conductor update` to re-sync mods with craft-conductor.toml")
    return 0


# ------------------------------------------------------------------- main
NOTICE_EXEMPT = {"notice", "licenses", "stop", "status", "web-password", "join"}  # never blocked by the notice


def interactive() -> bool:
    """True only when a person can answer prompts.

    Both ends must be a terminal: on Windows the null device (a service's stdin)
    claims to be one.
    """
    try:
        return sys.stdin is not None and sys.stdin.isatty() and sys.stdout is not None and sys.stdout.isatty()
    except (ValueError, OSError):
        return False


def _notice_ok(args) -> bool:
    """Show the first-run notice and require acceptance before anything else runs."""
    root = getattr(args, "dir", None) or args.root
    root = root.resolve() if (root / configmod.CONFIG_NAME).exists() else None
    if args.command in NOTICE_EXEMPT or notice.accepted(root):
        return True
    if args.command == "start" or (args.command == "service" and getattr(args, "panel", False)):
        return True  # the web UI shows the notice before anything is set up or downloaded
    if args.accept_notice:
        notice.accept(root, by="cli")
        return True
    if interactive():
        print(notice.as_text() + "\n")
        try:
            answer = input("Type 'yes' to accept and continue: ")
        except EOFError:
            answer = ""
        if answer.strip().lower() in ("y", "yes"):
            notice.accept(root, by="cli")
            print()
            return True
        print("not accepted; nothing was changed")
        return False
    if args.command in ("run", "start") and root is not None:
        try:
            web = args.command == "start" or args.web or configmod.load(root).web.enabled
        except ConfigError:
            web = False
        if web:
            return True  # the web UI shows the notice; the server waits until it is accepted
    print(notice.as_text() + "\n", file=sys.stderr)
    print("Accept it first: run `craft-conductor notice --accept`, pass --accept-notice, or accept it in the web UI "
          "(`craft-conductor run --web`).", file=sys.stderr)
    return False



def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="craft-conductor", description="A forever Minecraft server: runs your modded server "
                                "and upgrades it to the newest release once your mods support it.")
    p.add_argument("--version", action="version", version=f"Craft Conductor {__version__}")
    p.add_argument("-C", "--root", type=Path, default=Path("."), help="directory containing craft-conductor.toml")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--accept-notice", action="store_true",
                   help="accept the first-run notice without a prompt (for scripts and services)")
    sub = p.add_subparsers(dest="command")
    p.set_defaults(fn=None)

    s = sub.add_parser("start", help="open the control panel with your servers (the default); "
                                     "servers only start when you press Start")
    s.add_argument("--no-browser", action="store_true", help="don't open the web UI in a browser")
    s.add_argument("--web-host", help='web UI address; "0.0.0.0" to allow other devices on your network')
    s.add_argument("--web-port", type=int, help="web UI port (default 8765)")
    s.set_defaults(fn=cmd_start)

    s = sub.add_parser("join", help="set up this computer's Minecraft to play on a friend's Craft Conductor server")
    s.add_argument("invite", nargs="?", help="the invite link or code (craft-conductor-...)")
    s.add_argument("-y", "--yes", action="store_true", help="don't ask before setting things up")
    s.add_argument("--no-launcher", action="store_true", help="don't open the Minecraft Launcher afterwards")
    s.add_argument("--from-server", type=Path, metavar="DIR",
                   help="set up for a server on this computer (its folder), instead of an invite")
    s.add_argument("--minecraft-dir", type=Path, metavar="DIR", help="the Minecraft Launcher's folder, if not the usual one")
    s.add_argument("--launcher", metavar="LIST",
                   help="launchers to add the server to, comma-separated: minecraft, prism, modrinth, curseforge "
                        "(default: ask in the browser, or minecraft)")
    s.add_argument("--console", action="store_true", help="ask in this window instead of opening a page in the browser")
    s.set_defaults(fn=cmd_join)

    s = sub.add_parser("setup", help="set up a new server by answering questions in the terminal")
    s.set_defaults(fn=cmd_setup)

    s = sub.add_parser("init", help="create craft-conductor.toml")
    s.add_argument("--loader", choices=configmod.LOADERS, default="fabric")
    s.add_argument("--minecraft", default="latest", help="initial version, kept whatever the mods (default: the newest release the loader runs)")
    s.add_argument("--server-dir", help="use an existing server directory")
    s.add_argument("--accept-eula", action="store_true", help="accept the Minecraft EULA")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("create", help="download and build a complete new server in a new directory")
    s.add_argument("dir", type=Path, help="directory to create the server in")
    s.add_argument("--loader", choices=configmod.LOADERS, default="fabric")
    s.add_argument("--minecraft", default="latest", help="version, kept whatever the mods (default: the newest release the loader runs)")
    s.add_argument("--mod", action="append", default=[], metavar="SLUG", help="Modrinth mod (repeatable)")
    s.add_argument("--optional-mod", action="append", default=[], metavar="SLUG",
                   help="Modrinth mod that shouldn't block upgrades (repeatable)")
    s.add_argument("--curseforge", action="append", default=[], metavar="ID", help="CurseForge mod (repeatable)")
    s.add_argument("--memory", default="4G")
    s.add_argument("--java", type=int, help="force a Java major version (default: whatever Minecraft needs)")
    s.add_argument("--port", type=int, default=25565)
    s.add_argument("--motd", default="A forever Minecraft server")
    s.add_argument("--max-players", type=int, default=20)
    s.add_argument("--difficulty", choices=["peaceful", "easy", "normal", "hard"], default="normal")
    s.add_argument("--gamemode", choices=["survival", "creative", "adventure", "spectator"], default="survival")
    s.add_argument("--seed")
    s.add_argument("--rcon", action="store_true", help="enable RCON with a random password (for `craft-conductor cmd`)")
    s.add_argument("--accept-eula", action="store_true", help="accept the Minecraft EULA (needed for the test boot)")
    s.add_argument("--force", action="store_true")
    s.add_argument("-q", "--quiet", action="store_true")
    s.set_defaults(fn=cmd_create)

    s = sub.add_parser("import", help="adopt the mods already in an existing server's mods/ folder")
    s.set_defaults(fn=cmd_import)

    s = sub.add_parser("add", help="add mods to craft-conductor.toml")
    s.add_argument("ids", nargs="+", help="Modrinth slug/id, or CurseForge id/slug with --source curseforge")
    s.add_argument("--source", choices=configmod.MOD_SOURCES, default="modrinth")
    s.add_argument("--optional", action="store_true", help="don't hold back Minecraft upgrades for this mod")
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("remove", help="remove a mod from craft-conductor.toml")
    s.add_argument("id")
    s.add_argument("--source", choices=configmod.MOD_SOURCES, default="modrinth")
    s.set_defaults(fn=cmd_remove)

    s = sub.add_parser("check", help="show available updates and what is blocking newer versions")
    s.add_argument("--to", help="check a specific Minecraft version")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("update", help="apply available updates now (server must be stopped, or use `run`)")
    s.add_argument("--to", help="upgrade to a specific Minecraft version")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("-y", "--yes", action="store_true")
    s.add_argument("-q", "--quiet", action="store_true", help="don't echo server output during the test boot")
    s.set_defaults(fn=cmd_update)

    s = sub.add_parser("run", help="run the server, restart it on crashes and keep it updated")
    s.add_argument("--web", action="store_true", help="also serve the web UI (see [web] in craft-conductor.toml)")
    s.add_argument("--web-port", type=int, help="web UI port (default 8765)")
    s.add_argument("--web-host", help="web UI address (default 127.0.0.1)")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("web-password", help="show or change how the web UI is protected")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--set", action="store_true", help="choose a new password")
    g.add_argument("--pin", action="store_true", help="use a 4-8 digit PIN instead")
    g.add_argument("--reset", action="store_true", help="go back to the default password, PASSWORD")
    s.set_defaults(fn=cmd_web_password)

    s = sub.add_parser("stop", help="stop a server started with `craft-conductor run`")
    s.set_defaults(fn=cmd_stop)

    s = sub.add_parser("status", help="show what is installed")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("java", help="download and manage the Java runtime the server uses")
    jsub = s.add_subparsers(dest="java_command", required=True)
    jsub.add_parser("list", help="show the shared Java, Java found on this computer, and which one the server uses")
    j = jsub.add_parser("install", help="download Eclipse Temurin into the shared Java folder")
    j.add_argument("major", type=int, nargs="+")
    jsub.add_parser("update", help="bring the shared Java to its newest patch releases (servers move at their next start)")
    j = jsub.add_parser("remove", help="delete a shared Java version no server uses")
    j.add_argument("major", type=int)
    j = jsub.add_parser("use", help='force a Java major version, or "auto" to follow Minecraft')
    j.add_argument("version")
    s.set_defaults(fn=cmd_java)

    s = sub.add_parser("player", help="kick, ban/pardon, op/deop and whitelist players")
    s.add_argument("action", choices=["list", *ACTIONS], help="what to do")
    s.add_argument("name", nargs="?", help="player name (or IP address for ban-ip/pardon-ip)")
    s.add_argument("--reason", help="shown to the player when kicked or banned")
    s.set_defaults(fn=cmd_player)

    s = sub.add_parser("notice", help="show the first-run notice (what Craft Conductor does and doesn't do)")
    s.add_argument("--accept", action="store_true", help="accept it (for scripts and services)")
    s.set_defaults(fn=cmd_notice)

    s = sub.add_parser("licenses", help="list the open-source licenses of everything Craft Conductor uses")
    s.add_argument("--full", action="store_true", help="print the full license texts bundled in the executable")
    s.set_defaults(fn=cmd_licenses)

    s = sub.add_parser("self-update", help="update Craft Conductor itself to the newest release")
    s.add_argument("--check", action="store_true", help="only check, don't install")
    s.add_argument("--channel", choices=selfupdate.CHANNELS,
                   help="stable (the default) or beta (early versions); otherwise the one chosen in settings")
    s.add_argument("-y", "--yes", action="store_true")
    s.set_defaults(fn=cmd_self_update)

    s = sub.add_parser("service", help="Linux: run Craft Conductor in the background at boot with systemd")
    s.add_argument("action", choices=["install", "uninstall", "status"])
    s.add_argument("--local-only", action="store_true",
                   help="with --panel: keep the control panel on this machine (127.0.0.1, the default), for a rented "
                        "server you reach over SSH (ssh -L), even if network access was turned on before")
    s.add_argument("--network", action="store_true",
                   help="with --panel: open the control panel to other computers on your network (0.0.0.0); "
                        "it needs a strong password. Never forward its port on your router")
    s.add_argument("--panel", action="store_true",
                   help="the whole control panel with all your servers (craft-conductor start); without it, just the "
                        "server in this folder")
    s.set_defaults(fn=cmd_service)

    s = sub.add_parser("cmd", help="send a console command over RCON")
    # Not "command": that name holds which subcommand was chosen.
    s.add_argument("words", nargs="+", metavar="command", help="the console command, e.g. say hello")
    s.set_defaults(fn=cmd_cmd)

    s = sub.add_parser("backup", help="back up the server directory")
    s.add_argument("--label", default="manual")
    s.add_argument("--list", action="store_true")
    s.set_defaults(fn=cmd_backup)

    s = sub.add_parser("restore", help="restore a backup (latest by default)")
    s.add_argument("archive", nargs="?")
    s.add_argument("-y", "--yes", action="store_true")
    s.set_defaults(fn=cmd_restore)
    return p


def main(argv: list[str] | None = None) -> int:
    from . import desktop
    desktop.setup()  # the Windows executable has no command window of its own
    from .mods.curseforge import use_bundled_key
    use_bundled_key()  # release builds may carry craft-conductor's own CurseForge key
    try:
        return _entry(argv)
    except Exception as e:  # pragma: no cover - last resort, so a windowless failure isn't silent
        logging.getLogger(__name__).exception("Craft Conductor stopped unexpectedly")
        desktop.show_error(f"Craft Conductor stopped unexpectedly: {e}\n\nDetails are in {desktop.log_path()}")
        return 1


def _entry(argv: list[str] | None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:  # e.g. a Windows console code page that lacks "•"
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    argv = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.fn is None:  # no command, e.g. the executable was double-clicked
        args = parser.parse_args([*argv, "join" if _first_run_joining() else "start"])
    selfupdate.cleanup_after_update()
    try:
        return _main(args)
    finally:
        from . import desktop
        if selfupdate.frozen() and os.name == "nt" and args.command in ("start", "join") and not argv \
                and interactive() and not desktop.windowless():
            # Double-clicked on Windows: keep the console open so messages can be read.
            try:
                input("\nPress Enter to close this window...")
            except EOFError:
                pass


def _first_run_joining() -> bool:
    """Double-clicked with no command: set up Minecraft to join a friend's server when an
    invite was copied (or is in the file's name), or when craft-conductor has never run a server here."""
    from .join import invite_from_name
    if not selfupdate.frozen():
        return False
    if selfupdate.friend_build() or invite_from_name(sys.executable) is not None:
        return True
    home = default_home()  # someone who runs servers here gets their control panel
    return not (home / "servers").exists() and not (home / configmod.CONFIG_NAME).exists()


def _main(args) -> int:
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="[craft-conductor] %(message)s")
    args.root = args.root.resolve()
    if not _notice_ok(args):
        return 2
    try:
        return args.fn(args)
    except (ConfigError, UpgradeError, ModError, HttpError, JavaError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
