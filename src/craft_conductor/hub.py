"""Several Minecraft servers in one craft-conductor, run from the web UI: what `craft-conductor start` opens.

The hub never starts a server on its own; each one waits for its Start button.
Servers live in ``<home>/servers/<id>/`` (each an ordinary craft-conductor folder with its
own craft-conductor.toml), plus ``<home>`` itself if it holds a server from craft-conductor 0.1-0.3,
plus any other folder you started craft-conductor in. ``craft-conductor run`` still runs one server
the old way (and starts it); the web UI treats that as a hub with one server.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from . import config as configmod, rollback, selfupdate, setup as setupmod
from .config import ConfigError, WebConfig
from .daemon import Daemon, SELF_CHECK_INTERVAL, pid_alive, running_pid, set_current_server
from .http import HttpClient
from .clientpack import client_dir
from .loaders import mods_folder
from .manager import Manager

log = logging.getLogger(__name__)

SERVERS_DIR = "servers"
HUB_FILE = "hub.json"
HOME_ID = "main"           # the server kept directly in the home folder (craft-conductor 0.1-0.3)
SCAN_EVERY = 5.0


def hub_pid_path(home: Path) -> Path:
    return home / configmod.STATE_DIR / "hub.pid"


def hub_stop_path(home: Path) -> Path:
    return home / configmod.STATE_DIR / "hub-stop-requested"


def running_hub(home: Path) -> int | None:
    try:
        pid = int(hub_pid_path(home).read_text().strip())
    except (FileNotFoundError, ValueError):
        return None
    return pid if pid != os.getpid() and pid_alive(pid) else None


def _rmtree(path: Path) -> None:
    """Delete a folder, including read-only files (Windows marks some that way)."""
    import shutil
    import stat

    def retry(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=retry)
    else:
        shutil.rmtree(path, onerror=retry)


def receive(handler, dest: Path, max_bytes: int) -> Path:
    """Stream a request body into ``dest`` (atomically)."""
    length = int(handler.headers.get("Content-Length") or 0)
    if not 0 < length <= max_bytes:
        raise ValueError("the file is empty or too large")
    dest.parent.mkdir(parents=True, exist_ok=True)
    handler._body_read = True  # (an error now doesn't try to read it again)
    tmp = dest.with_name(f".{dest.name}.part")
    try:
        with open(tmp, "wb") as out:
            remaining = length
            while remaining:
                chunk = handler.rfile.read(min(1 << 16, remaining))
                if not chunk:
                    raise ValueError("the upload was interrupted")
                out.write(chunk)
                remaining -= len(chunk)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    return dest


def port_free(port: int) -> bool:
    """Whether nothing on this computer is listening on a TCP port."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "server"


class Hub:
    def __init__(self, home: Path, make_manager: Callable[[configmod.Config], Manager] | None = None,
                 http: HttpClient | None = None, tick: float = 2.0):
        self.home = home.resolve()
        self.http = http or HttpClient()
        self.make_manager = make_manager or (lambda cfg: Manager(cfg, http=self.http, echo=False))
        self.trials: dict = {}  # test boots (trial.Trial) by id
        self.setup_checks: dict = {}  # the setup page's file checks (filecheck.for_setup) by what was checked
        self.previews: dict = {}  # map previews (preview.Preview) by id
        self._push = None  # phone notifications (the installed app): see the push property
        self.gallery = None  # the last seed gallery (preview.Gallery)
        self.map_session = None  # the last previewed world, to explore (preview.MapSession)
        self._upnp_lock = threading.Lock()
        self._upnp_status: dict | None = None
        self._gateway, self._gateway_at = None, 0.0
        self.join_requests: dict[str, list[dict]] = {}  # friends asking to be let in, by server
        self._status_lock = threading.Lock()  # the Discord status message
        self._status_sent, self._status_at = None, 0.0
        self.discord_bot = None  # Whitelist through Discord, while it's on (discordbot.WhitelistBot)
        self._health = None      # warnings about this computer (health.Health): see the health property
        self._health_lock = threading.Lock()
        self._request_times: dict[str, float] = {}
        self._requests_lock = threading.Lock()
        self.checks: dict = {}  # quick mod checks running in the background (trial.CheckJob) by id
        self.tick = tick
        self._single: Daemon | None = None
        self.daemons: dict[str, Daemon] = {}
        self._threads: dict[str, threading.Thread] = {}
        self.problems: dict[str, dict] = {}      # servers that can't be run here, and why
        self.stop_requested = threading.Event()
        self.restart_requested = False
        self.updater = selfupdate.Updater()  # where this copy stands with its own update (one source for everything)
        self.open_browser = False
        self.ui = None
        self.share = None           # the share server for friends' downloads, while one is switched on
        self.share_error: str | None = None
        self._lock = threading.RLock()
        self._hub_lock = threading.RLock()  # hub.json: one change at a time (see _update_hub_file)
        self._web = self._load_web()
        self._apply_curseforge_key()

    @classmethod
    def single(cls, daemon: Daemon) -> Hub:
        """`craft-conductor run --web`: a hub view of one server run the classic way."""
        hub = cls.__new__(cls)
        hub.home = daemon.m.config.root
        hub.http = daemon.m.http
        hub._single = daemon
        hub.updater = daemon.updater
        hub.daemons = {HOME_ID: daemon}
        hub.problems = {}
        hub.join_requests = {}  # summary() also runs for classic single-server dashboards
        hub.stop_requested = daemon.stop_requested
        hub._lock = threading.RLock()
        hub._hub_lock = threading.RLock()
        hub.ui = None
        hub.share = None
        hub.share_error = None
        hub.trials = {}
        hub.setup_checks = {}
        hub.previews = {}
        hub._push = None
        hub.discord_bot = None
        hub._health, hub._health_lock = None, threading.Lock()
        hub.gallery = None
        hub.map_session = None
        hub._upnp_lock = threading.Lock()
        hub._upnp_status = None
        hub._gateway, hub._gateway_at = None, 0.0
        hub.make_manager = lambda cfg: Manager(cfg, http=hub.http, echo=False)
        return hub

    # --------------------------------------------------------- settings
    @property
    def is_single(self) -> bool:
        return self._single is not None

    @property
    def root(self) -> Path:
        return self.home

    @property
    def state_dir(self) -> Path:
        return self._single.m.config.state_dir if self._single else self.home / configmod.STATE_DIR

    @property
    def web(self) -> WebConfig:
        return self._single.m.config.web if self._single else self._web

    def _hub_file(self) -> dict:
        try:
            data = json.loads((self.state_dir / HUB_FILE).read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _update_hub_file(self, change: Callable[[dict], object]) -> object:
        """Change hub.json: read it, let ``change`` edit what's in it, write it back, all as one step,
        so two changes at once (a page saving a setting while the router forwarding, which waits for
        the router, writes down its ports) never undo each other. Nothing is written if ``change``
        raises. Returns what ``change`` returned. Slow work (network) goes before or after, never in it."""
        with self._hub_lock:
            data = self._hub_file()
            result = change(data)
            self._save_hub_file(data)
            return result

    def _save_hub_file(self, data: dict) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.state_dir / (HUB_FILE + ".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        try:
            tmp.chmod(0o600)  # it can hold the CurseForge key and the Discord bot token
        except OSError:
            pass
        os.replace(tmp, self.state_dir / HUB_FILE)

    def _load_web(self) -> WebConfig:
        """Control panel settings: hub.json, else the [web] of a server kept in the home folder."""
        web = WebConfig()
        legacy = self.home / configmod.CONFIG_NAME
        if legacy.exists():
            try:
                old = configmod.load(self.home).web
                web = WebConfig(host=old.host, port=old.port, password=old.password,
                                allowed_hosts=list(old.allowed_hosts))
            except ConfigError:
                pass
        saved = self._hub_file().get("web", {})
        if isinstance(saved, dict):
            web.host = str(saved.get("host", web.host))
            web.port = int(saved.get("port", web.port))
            web.password = str(saved.get("password", web.password))
            web.allowed_hosts = [str(x).lower() for x in saved.get("allowed_hosts", web.allowed_hosts)]
            web.tls_cert = str(saved.get("tls_cert", web.tls_cert))
            web.tls_key = str(saved.get("tls_key", web.tls_key))
        web.enabled = True
        return web

    def save_web(self, **changes) -> None:
        """Remember control panel settings (they apply the next time craft-conductor starts)."""
        self._update_hub_file(lambda data: data.setdefault("web", {}).update(changes))
        for key, value in changes.items():  # what's configured now (the running panel keeps its address)
            if hasattr(self.web, key):
                setattr(self.web, key, value)

    # ------------------------------------------------------- CurseForge
    def curseforge_key(self) -> str:
        """The CurseForge API key: saved in craft-conductor settings, or CRAFT_CONDUCTOR_CURSEFORGE_API_KEY."""
        return str(self._hub_file().get("curseforge_api_key") or os.environ.get("CRAFT_CONDUCTOR_CURSEFORGE_API_KEY", ""))

    def _apply_curseforge_key(self) -> None:
        # Servers read CRAFT_CONDUCTOR_CURSEFORGE_API_KEY when their craft-conductor.toml has no key of its own.
        key = self._hub_file().get("curseforge_api_key")
        if key:
            os.environ["CRAFT_CONDUCTOR_CURSEFORGE_API_KEY"] = key

    def save_curseforge_key(self, key: str) -> None:
        """Check a key with CurseForge, then use it everywhere (empty removes it)."""
        from .mods import curseforge as cf
        key = key.strip()
        if key:
            if not re.fullmatch(r"[A-Za-z0-9$./_+=-]{20,120}", key):
                raise ConfigError("that doesn't look like a CurseForge API key")
            try:
                # (never a remembered answer: that was for whichever key asked before)
                self.http.get_json(f"{cf.API}/games/{cf.MINECRAFT_GAME_ID}", headers={"x-api-key": key}, cache=False)
            except Exception as e:
                raise ConfigError(f"CurseForge didn't accept that key ({e})") from None

        def change(data: dict) -> None:
            if key:
                data["curseforge_api_key"] = key
            else:
                data.pop("curseforge_api_key", None)
        self._update_hub_file(change)
        if key:
            os.environ["CRAFT_CONDUCTOR_CURSEFORGE_API_KEY"] = key
        else:
            os.environ.pop("CRAFT_CONDUCTOR_CURSEFORGE_API_KEY", None)
            cf.use_bundled_key()  # back to the built-in one, if this build has one
        for d in list(self.daemons.values()):
            try:
                d.m.reload_config()
            except Exception as e:
                log.warning("couldn't reload a server's settings: %s", e)

    # ---------------------------------------------------------- Discord
    def discord(self):
        """The Discord bot for posting invites, or None if none is set up."""
        from .discord import Discord
        token = str(self._hub_file().get("discord", {}).get("token") or "")
        return Discord(self.http, token) if token else None

    def discord_settings(self) -> dict:
        d = self._hub_file().get("discord", {})
        return {"set": bool(d.get("token")), "bot": d.get("bot"), "guild": d.get("guild", ""), "channel": d.get("channel", ""),
                "status_channel": d.get("status_channel", "")}

    def set_discord_status(self, channel: str) -> None:
        """Keep a live status message in this channel ("" stops it)."""
        from .discord import SNOWFLAKE
        if channel and not SNOWFLAKE.fullmatch(channel):
            raise ValueError("that isn't a Discord channel")

        def change(data: dict) -> None:
            if "discord" not in data:
                raise ValueError("add a Discord bot first")
            data["discord"]["status_channel"] = channel
            data["discord"].pop("status_message", None)
        self._update_hub_file(change)
        self._status_sent = None
        if channel:
            threading.Thread(target=self.discord_status, daemon=True, name="discord-status").start()

    STATUS_REFRESH = 600  # post the same status again at most this often (the "updated" time)

    def discord_status(self, off: bool = False) -> None:
        """Bring the live status message up to date: edit it when something changed (state,
        players), post a new one if it was deleted. Quietly does nothing without a bot or channel."""
        from .discord import DiscordError, MessageGone, status_embed
        if not (self._status_lock.acquire(timeout=10) if off else self._status_lock.acquire(blocking=False)):
            return  # (one update at a time; the closing one waits for a running one)
        try:
            data = self._hub_file()
            d = data.get("discord", {})
            channel, bot = d.get("status_channel"), self.discord()
            if not channel or bot is None:
                return
            embed = status_embed(self.summary(), (self.share_settings().get("address") or "").strip(), off=off)
            sig = json.dumps(embed, sort_keys=True)
            if sig == self._status_sent and time.monotonic() - self._status_at < self.STATUS_REFRESH and not off:
                return
            embed["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            try:
                if d.get("status_message"):
                    bot.edit(channel, d["status_message"], "", embed)
                else:
                    raise MessageGone()
            except MessageGone:
                msg = bot.post(channel, "", embed)

                def remember(data: dict) -> None:
                    if isinstance(data.get("discord"), dict):  # (unless the bot was removed meanwhile)
                        data["discord"]["status_message"] = msg["id"]
                self._update_hub_file(remember)
            self._status_sent, self._status_at = sig, time.monotonic()
        except (DiscordError, OSError) as e:
            log.warning("couldn't update the Discord status message: %s", e)
        finally:
            self._status_lock.release()

    def save_discord_token(self, token: str) -> dict | None:
        """Check a bot token with Discord and keep it (empty removes it). Returns the bot."""
        from .discord import Discord, check_token
        if not token.strip():
            self._update_hub_file(lambda data: data.pop("discord", None))
            return None
        token = check_token(token)
        bot = Discord(self.http, token).me()  # (asked before hub.json is opened: it takes a moment)
        self._update_hub_file(lambda data: data.__setitem__("discord", {"token": token, "bot": bot}))
        return bot

    # ------------------------------------------- Whitelist through Discord
    def discord_whitelist(self) -> dict:
        w = self._hub_file().get("discord", {}).get("whitelist", {})
        bot = self.discord_bot
        return {"enabled": bool(w.get("enabled")), "mode": w.get("mode", "ask"), "role": w.get("role", ""),
                "status": bot.status() if bot else None}

    def set_discord_whitelist(self, enabled: bool, mode: str = "ask", role: str = "") -> None:
        from .discordbot import check_settings
        mode, role = check_settings(mode, role)

        def change(data: dict) -> None:
            if "discord" not in data:
                raise ValueError("add a Discord bot first")
            data["discord"]["whitelist"] = {"enabled": bool(enabled), "mode": mode, "role": role}
        self._update_hub_file(change)
        old, self.discord_bot = self.discord_bot, None
        if old is not None:
            old.close()
            if not enabled:
                threading.Thread(target=old.unregister, daemon=True, name="discord-commands").start()
        self.sync_discord_bot()

    def sync_discord_bot(self) -> None:
        """Start or stop the bot to match the settings; keep /whitelist's server list current."""
        from .discordbot import WhitelistBot
        d = self._hub_file().get("discord", {})
        w = d.get("whitelist", {})
        want = bool(w.get("enabled") and d.get("token")) and not self.is_single
        bot = self.discord_bot
        if not want:
            if bot is not None:
                bot.close()
                self.discord_bot = None
            return
        if bot is None or bot.token != d["token"] or (bot.state == "stopped" and bot.stop.is_set()):
            if bot is not None:
                bot.close()
            bot = self.discord_bot = WhitelistBot(self, d["token"], w)
            bot.start()
        else:
            bot.settings = w
            if bot.state == "connected":
                bot.register()

    def summary_for_discord(self) -> list[dict]:
        """The Minecraft servers /whitelist can pick from (ones that are set up)."""
        from .properties import read_properties
        out = []
        for sid, d in list(self.daemons.items()):
            if d.setup_pending:
                continue
            motd = read_properties(d.m.server_dir / "server.properties").get("motd") or sid
            out.append({"id": sid, "name": motd})
        return out

    def whitelist_from_discord(self, sid: str, name: str, who: str) -> str:
        """Let in someone who asked with /whitelist (in "Let them in" mode)."""
        from .players import Players
        d = self.daemons[sid]
        running = d.state == "running"
        message = Players(d.m.server_dir, d.m.http, d.send_command if running else None).act("whitelist-add", name)
        self.answer_join_request(sid, name)
        log.info("%s let themselves into %s through Discord (%s)", name, sid, who)
        d.m.notifier.send(f"{name} was let in through Discord (/whitelist, by {who}).")
        return message

    def remember_discord_channel(self, guild: str, channel: str) -> None:
        def change(data: dict) -> None:
            if "discord" in data:
                data["discord"].update(guild=guild, channel=channel)
        self._update_hub_file(change)

    # ---------------------------------------------------------- sharing
    # ------------------------------------------------ mod conflict memory
    def share_conflicts(self) -> bool:
        """Whether mod conflicts that "Find which mods break it" finds are shared (conflicts.py)."""
        return bool(self._hub_file().get("share_conflicts")) and not self.is_single

    def set_share_conflicts(self, on: bool) -> None:
        self._update_hub_file(lambda data: data.__setitem__("share_conflicts", bool(on)))

    @property
    def known_conflicts(self):
        if getattr(self, "_known", None) is None:
            from .conflicts import Known
            self._known = Known(self.state_dir, self.http)
        return self._known

    def share_settings(self) -> dict:
        """Friends' downloads: the share server's port, and the address friends use (blank = the
        address they opened the invite with)."""
        from .share import DEFAULT_PORT
        s = self._hub_file().get("share", {}) if not self.is_single else {}
        return {"port": int(s.get("port", DEFAULT_PORT)), "address": str(s.get("address", "")),
                "tunnel": str(s.get("tunnel", ""))}

    def share_tunnel(self) -> tuple[str, int] | None:
        """The playit.gg tunnel friends' craft-conductor reaches the downloads through, if one is set."""
        from .tunnel import TunnelError, parse_address
        try:
            return parse_address(self.share_settings().get("tunnel", ""), default_port=0) or None
        except TunnelError:
            return None

    def save_share(self, port: int, address: str, tunnel: str | None = None) -> None:
        def change(data: dict) -> None:
            data["share"] = {"port": port, "address": address,
                             "tunnel": tunnel if tunnel is not None else data.get("share", {}).get("tunnel", "")}
        self._update_hub_file(change)
        self.update_share(restart=True)

    def update_share(self, restart: bool = False) -> None:
        """Run the share server while any server has its friend download switched on, with a link
        that still works (it's reachable from the internet: closed when there's nothing to share)."""
        if self.is_single:
            return
        from .share import ShareServer
        now = time.time()
        wanted = any(d.m.config.client.link_works(now) for d in list(self.daemons.values()))
        port = self.share_settings()["port"]
        if self.share and (not wanted or restart or self.share.port != port):
            self.share.stop()
            self.share = None
        if wanted and self.share is None:
            server = ShareServer(self, port)
            try:
                server.start()
                self.share, self.share_error = server, None
            except (OSError, ValueError) as e:  # (ssl.SSLError is an OSError)
                self.share_error = f"port {port} is busy ({e.strerror or e}); pick another in Craft Conductor settings"
                log.warning("couldn't start sharing: %s", self.share_error)

    def share_fingerprint(self) -> str:
        """The share server's certificate fingerprint (it goes in every invite)."""
        if self.share and self.share.fingerprint:
            return self.share.fingerprint
        if not getattr(self, "_fingerprint", None):  # sharing is off: make/read the certificate once
            from . import tlscert
            self._fingerprint = tlscert.ensure(self.state_dir / "tls")[2]
        return self._fingerprint

    PUBLIC_IP_SERVICES = ("https://api.ipify.org?format=json", "https://api64.ipify.org?format=json",
                          "https://ifconfig.co/json")

    def public_ip(self) -> str:
        """This network's address on the internet, as other sites see it."""
        import ipaddress
        errors = []
        for url in self.PUBLIC_IP_SERVICES:
            try:
                ip = str(self.http.get_json(url, headers={"Accept": "application/json"}).get("ip", "")).strip()
                addr = ipaddress.ip_address(ip)
            except Exception as e:
                errors.append(str(e))
                continue
            if addr.is_global:
                return str(addr)
        raise RuntimeError("couldn't find your public address (" + (errors[-1] if errors else "no answer") + "); "
                           "check the internet connection, or type it in under Craft Conductor settings → Sharing")

    def share_status(self) -> dict:
        from .cli import lan_ip
        return {**self.share_settings(), "running": bool(self.share), "error": self.share_error, "lan_ip": lan_ip()}

    # ---------------------------------------------------------- servers
    def _extra_roots(self) -> list[Path]:
        return [Path(p) for p in self._hub_file().get("extra", []) if isinstance(p, str)]

    def add_folder(self, root: Path) -> None:
        """Also list a server folder that lives somewhere else (e.g. where craft-conductor was started)."""
        root = root.resolve()
        if root == self.home or root.parent == self.home / SERVERS_DIR:
            return

        def change(data: dict) -> None:
            extra = [p for p in data.get("extra", []) if isinstance(p, str)]
            if str(root) not in extra:
                data["extra"] = extra + [str(root)]
        self._update_hub_file(change)

    def discover(self) -> dict[str, Path]:
        found: dict[str, Path] = {}
        hidden = {Path(p) for p in self._hub_file().get("hidden", []) if isinstance(p, str)}
        if (self.home / configmod.CONFIG_NAME).exists() and self.home not in hidden:
            found[HOME_ID] = self.home
        servers = self.home / SERVERS_DIR
        if servers.is_dir():
            for d in sorted(servers.iterdir()):
                if (d / configmod.CONFIG_NAME).exists() and d.name not in found and d.resolve() not in hidden:
                    found[d.name] = d
        for root in self._extra_roots():
            if (root / configmod.CONFIG_NAME).exists() and root not in found.values() and root not in hidden:
                sid, n = slugify(root.name), 2
                while sid in found:
                    sid, n = f"{slugify(root.name)}-{n}", n + 1
                found[sid] = root
        return found

    def scan(self) -> None:
        """Pick up new server folders, and restart the manager of any server whose manager stopped."""
        if self.is_single:
            return
        with self._lock:
            for sid, root in self.discover().items():
                thread = self._threads.get(sid)
                if sid in self.daemons and thread and thread.is_alive():
                    continue
                self._attach(sid, root)

    def _attach(self, sid: str, root: Path) -> None:
        try:
            m = self.make_manager(configmod.load(root))
            m.mod_files = self.mod_files  # (files the setup page or a check already downloaded)
        except (ConfigError, OSError, ValueError) as e:
            self.problems[sid] = {"root": str(root), "problem": f"its craft-conductor.toml has a problem: {e}"}
            self.daemons.pop(sid, None)
            return
        if pid := running_pid(m):
            if pid != os.getpid():
                self.problems[sid] = {"root": str(root), "name": m.config.root.name,
                                      "problem": "another Craft Conductor window (or `craft-conductor run`) is running this server"}
                self.daemons.pop(sid, None)
                return
        self.problems.pop(sid, None)
        d = Daemon(m, tick=self.tick, autostart=False, server_id=sid, hub_managed=True)
        d.hub = self
        m.notifier.listeners.append(lambda message, sid=sid: self.phone_notify(sid, message))
        d.web_enabled = True  # problems are shown in the web UI instead of stopping craft-conductor
        self.daemons[sid] = d
        t = threading.Thread(target=d.run, daemon=True, name=f"server:{sid}")
        self._threads[sid] = t
        t.start()

    @property
    def health(self):
        """Warnings about this computer: disk space, CPU, memory (health.py)."""
        if self._health is None:
            from .health import Health
            self._health = Health(self)
        return self._health

    @property
    def push(self):
        if self._push is None:
            from .push import Push
            self._push = Push(self.state_dir)
        return self._push

    def phone_notify(self, sid: str, message: str) -> None:
        """A server's message (what goes to Discord), to the phones that turned notifications on."""
        from .properties import read_properties
        d = self.daemons.get(sid)
        name = sid
        if d is not None:
            name = read_properties(d.m.server_dir / "server.properties").get("motd") or sid
        self.push.notify(name, message, url=f"/#s/{sid}/dashboard", tag=sid.replace("-", "_")[:32])

    def get(self, sid: str) -> Daemon | None:
        return self.daemons.get(sid)

    def only(self) -> tuple[str, Daemon] | None:
        """The one server, when there is exactly one (older single-server URLs use it)."""
        return next(iter(self.daemons.items())) if len(self.daemons) == 1 else None

    def ports(self, exclude: str | None = None) -> dict[int, str]:
        """Minecraft port -> server id, for every server here."""
        from .properties import read_properties
        out = {}
        for sid, d in self.daemons.items():
            if sid != exclude:
                try:
                    out[int(read_properties(d.m.server_dir / "server.properties").get("server-port", "25565"))] = sid
                except ValueError:
                    pass
        return out

    def free_port(self, start: int = 25565) -> int:
        taken = self.ports()
        port = start
        while port in taken or port in self.reserved_ports() or not port_free(port):
            port += 1
        return port

    def reserved_ports(self) -> set[int]:
        """Ports craft-conductor itself listens on (the control panel and the friends' download)."""
        out = {self.web.port}
        if self.ui is not None and self.ui.httpd is not None:
            out.add(self.ui.httpd.server_address[1])
        if not self.is_single:
            out.add(self.share_settings()["port"])
        return out

    def port_info(self, port: int, exclude: str | None = None) -> dict:
        """Whether a Minecraft port can be used: by another server here, by craft-conductor, or by another program."""
        from .properties import read_properties
        used_by = None
        sid = self.ports(exclude).get(port)
        if sid is not None and sid in self.daemons:
            used_by = read_properties(self.daemons[sid].m.server_dir / "server.properties").get("motd") or sid
        running_here = sid is not None and sid in self.daemons and bool(
            self.daemons[sid].proc and self.daemons[sid].proc.running)
        return {"port": port, "used_by": used_by, "craft-conductor": port in self.reserved_ports(),
                "busy": not running_here and not port_free(port), "suggestion": self.free_port()}

    def check_port(self, daemon: Daemon) -> None:
        """Refuse to start a server whose port another running server here already uses."""
        from .properties import read_properties
        port = read_properties(daemon.m.server_dir / "server.properties").get("server-port", "25565")
        for sid, other in self.daemons.items():
            if other is daemon or not (other.proc and other.proc.running):
                continue
            if read_properties(other.m.server_dir / "server.properties").get("server-port", "25565") == port:
                name = read_properties(other.m.server_dir / "server.properties").get("motd") or sid
                raise RuntimeError(f"port {port} is already used by {name}, which is running; "
                                   "stop it first, or give this server another port in its Settings")

    def _check_health(self) -> None:
        if not self._health_lock.acquire(blocking=False):
            return  # (the last look hasn't finished: a drive that doesn't answer)
        try:
            self.health.check()
        except Exception:
            log.exception("couldn't check the computer's disk, CPU and memory")
        finally:
            self._health_lock.release()

    def memory_plan(self, adding: str | None = None) -> dict:
        """The memory given to the running servers (plus ``adding``, about to start) against this
        computer's, leaving some for the computer itself (limits.py)."""
        from . import limits, stats
        from .setup import suggested_memory_gb, total_ram_gb
        total = total_ram_gb()
        default = suggested_memory_gb(total)
        gb = lambda d: stats.heap_bytes(d.m.config.server.memory, default) / 1024 ** 3  # noqa: E731
        running = {sid: d for sid, d in list(self.daemons.items()) if d.proc and d.proc.running and sid != adding}
        extra = self.daemons.get(adding)
        plan = limits.memory_fits([gb(d) for d in running.values()], gb(extra) if extra else 0.0, total)
        plan["running"] = [{"id": sid, "gb": round(gb(d), 1)} for sid, d in running.items()]
        plan["adding_gb"] = round(gb(extra), 1) if extra else 0.0
        return plan

    def check_memory(self, daemon: Daemon) -> None:
        """Say (in the activity) when starting this server gives the servers more memory than the
        computer has; the page asks before starting it (see memory_plan)."""
        sid = next((k for k, v in self.daemons.items() if v is daemon), None)
        if sid is None:
            return
        plan = self.memory_plan(sid)
        if not plan["fits"]:
            log.warning("the running servers are given %.1f GB of memory with this one, and this computer has %.1f GB: "
                        "it may slow down or a server may crash; give them less memory, or stop one", plan["after_gb"], plan["total_gb"])

    @property
    def staging_dir(self) -> Path:
        return self.state_dir / "staging"

    @property
    def mod_files(self):
        """Mod files kept by their hash, for every server here (modfiles.py)."""
        from .modfiles import Store
        if getattr(self, "_mod_files", None) is None or self._mod_files.folder != self.state_dir / "mod-files":
            self._mod_files = Store(self.state_dir / "mod-files", self.http)
        return self._mod_files

    def stage_upload(self, handler, filename: str, max_bytes: int) -> dict:
        """Keep an upload (from the setup page) until the server it's for is created."""
        import secrets
        cutoff = time.time() - 86400
        if self.staging_dir.is_dir():
            for old in self.staging_dir.iterdir():
                if old.stat().st_mtime < cutoff:
                    shutil.rmtree(old, ignore_errors=True)
        sid = secrets.token_hex(8)
        dest = self.staging_dir / sid / filename
        receive(handler, dest, max_bytes)
        return {"id": sid, "filename": filename, "size": dest.stat().st_size}

    def world_source(self, choice: str) -> Path | None:
        """Where a world picked on the setup page (or Settings) is: an upload, or a singleplayer save."""
        from . import world
        if not choice:
            return None
        if choice.startswith("save:"):
            return world.find_save(choice[5:])
        found = list((self.staging_dir / choice).glob("*.zip")) if re.fullmatch(r"[a-f0-9]{16}", choice) else []
        if not found:
            raise ConfigError("the uploaded world isn't here any more; upload it again")
        return found[0]

    def take_staged(self, stage_ids: list[str], mods_dir: Path) -> int:
        """Move jars picked with "Local files" on the setup page into a server's mods folder."""
        moved = 0
        for stage_id in stage_ids:
            folder = self.staging_dir / stage_id
            for f in folder.glob("*.jar"):
                mods_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), mods_dir / f.name)
                moved += 1
            shutil.rmtree(folder, ignore_errors=True)
        return moved

    def create(self, spec: setupmod.SetupSpec) -> str:
        """Make a new server folder from the setup page and start installing it (not running it)."""
        if self.is_single:
            raise RuntimeError("this Craft Conductor runs a single server (`craft-conductor run`); use `craft-conductor start` for several")
        with self._lock:
            base = slugify(spec.motd)
            sid, n = base, 2
            taken = set(self.discover()) | {HOME_ID}
            while sid in taken or (self.home / SERVERS_DIR / sid).exists():
                sid, n = f"{base}-{n}", n + 1
            root = self.home / SERVERS_DIR / sid
            if spec.port in self.ports():
                if spec.port_chosen:
                    other = self.ports()[spec.port]
                    raise ConfigError(f"port {spec.port} is already used by another server here ({other}); pick another")
                spec.port = self.free_port(spec.port)  # two servers can't share a port
            spec.network_access = False  # the hub's own setting decides who can open the panel
            spec.world_source = self.world_source(spec.world)  # before any files are written
            setupmod.configure(root, spec)
            setupmod.mark_pending(root)
            cfg = configmod.load(root)
            self.take_staged(spec.local_mods, cfg.server.dir / mods_folder(spec.loader))
            self.take_staged(spec.client_local, client_dir(cfg))  # friends' own files
            if cfg.manual_dir:
                self.take_staged(spec.manual_files, cfg.manual_dir)  # mods downloaded by hand (handdownload.py)
            self._attach(sid, root)
            d = self.daemons.get(sid)
            if d is None:
                raise RuntimeError(self.problems.get(sid, {}).get("problem", "the server couldn't be loaded"))
        log.info("creating server %s in %s", sid, root)
        if not d.submit("set up server", d.run_setup, spec):
            raise RuntimeError("the new server is busy; try again")
        return sid

    @property
    def exports_dir(self) -> Path:
        return self.home / "exports"

    def import_server(self, stage_id: str) -> str:
        """Add a server from an export (Settings → Export on another computer)."""
        if self.is_single:
            raise RuntimeError("this Craft Conductor runs a single server (`craft-conductor run`); use `craft-conductor start` to import servers")
        if not re.fullmatch(r"[a-f0-9]{16}", stage_id or ""):
            raise ConfigError("that upload isn't here any more; upload the file again")
        found = list((self.staging_dir / stage_id).glob("*.zip"))
        if not found:
            raise ConfigError("that upload isn't here any more; upload the file again")
        sid = self.import_archive(found[0])
        shutil.rmtree(self.staging_dir / stage_id, ignore_errors=True)
        return sid

    def import_archive(self, archive: Path, name: str | None = None,
                       prepare: Callable[[Path], None] | None = None) -> str:
        """A new server from an export (``name`` renames it; ``prepare`` adjusts its folder
        before it's loaded)."""
        from . import transfer
        manifest = transfer.read_manifest(archive)
        with self._lock:
            base = slugify(name or manifest.get("name") or manifest.get("folder") or "imported")
            sid, n = base, 2
            taken = set(self.discover()) | {HOME_ID}
            while sid in taken or (self.home / SERVERS_DIR / sid).exists():
                sid, n = f"{base}-{n}", n + 1
            root = self.home / SERVERS_DIR / sid
            transfer.import_into(archive, root)
            from .properties import read_properties, write_properties
            props_path = configmod.load(root).server.dir / "server.properties"
            if name:
                write_properties(props_path, {"motd": name[:59]})
            port = int(read_properties(props_path).get("server-port", "25565") or 25565)
            if port in self.ports():  # another server here already uses it
                new = self.free_port(port)
                write_properties(props_path, {"server-port": str(new)})
                log.info("the imported server used port %d, which is taken here; it now uses %d", port, new)
            if prepare:
                prepare(root)
            self._attach(sid, root)
        log.info("imported %s into %s", name or manifest.get("name"), root)
        return sid

    def delete(self, sid: str, delete_files: bool) -> str:
        """Take a server off the list; with ``delete_files``, also erase its world, mods,
        backups and settings. Only files craft-conductor made inside the server's folder are touched."""
        with self._lock:
            d = self.daemons.get(sid)
            if d is None:
                raise RuntimeError("there's no server with that id")
            if (d.proc and d.proc.running) or d.job:
                raise RuntimeError("stop the server (and wait for anything it's doing to finish) first")
            cfg = d.m.config
            root = cfg.root
            d.stop_requested.set()
            t = self._threads.pop(sid, None)
            if t:
                t.join(timeout=30)
            self.daemons.pop(sid, None)
            # It no longer counts as using its Java; deleted, a shared Java only it used goes too.
            others = {dd.m.lock.java_major for dd in self.daemons.values()}
            gone = d.m.java.forget(prune=delete_files, keep=others)
            if gone:
                log.info("removed the shared Java %s: no other server uses it", ", ".join(map(str, gone)))
            store = d.m.java.dir

            def forget(data: dict) -> None:
                data["extra"] = [p for p in data.get("extra", []) if p != str(root)]
                if not delete_files:
                    data["hidden"] = sorted(set(data.get("hidden", [])) | {str(root)})
            self._update_hub_file(forget)
            if not delete_files:
                log.info("removed server %s from the list; its files are still in %s", sid, root)
                return f"removed from the list; its files are still in {root}"
            if root.parent == self.home / SERVERS_DIR:
                _rmtree(root)  # craft-conductor's own folder for this server
            else:
                # A folder craft-conductor doesn't own (the home folder, or one you pointed it at): delete
                # only what belongs to the server, and leave anything else there alone.
                inside = [cfg.server.dir, cfg.backups.dir, cfg.manual_dir, root / configmod.CONFIG_NAME,
                          root / "craft-conductor.lock.json"]
                if root != self.home:
                    inside.append(cfg.state_dir)
                for p in inside:
                    if p is None or not p.exists() or root not in p.parents:
                        continue  # never anything outside the server's folder
                    if p == store or p in store.parents:
                        continue  # nor the shared Java folder
                    if p.is_dir():
                        _rmtree(p)
                    else:
                        p.unlink()
                if root == self.home:
                    setupmod.clear_pending(root)
                elif root.exists() and not any(root.iterdir()):
                    root.rmdir()
        log.info("deleted server %s and all of its files (%s)", sid, root)
        return "deleted, with its world, mods and backups"

    # ----------------------------------------------- router port forwarding
    UPNP_EVERY = 30 * 60  # renew the forwards (they're asked for with a 2-hour limit)

    def upnp_settings(self) -> dict:
        u = self._hub_file().get("upnp", {}) if not self.is_single else {}
        return {"enabled": bool(u.get("enabled")), "mapped": [tuple(x) for x in u.get("mapped", [])
                                                              if isinstance(x, list) and len(x) == 2]}

    def upnp_wanted(self) -> list[tuple[int, str, str]]:
        """(port, protocol, label) craft-conductor forwards: each server's Minecraft port and friends' downloads.
        Never the control panel's port or a server's RCON port, even if one of those is the same number."""
        from .properties import read_properties
        out, private = [], {self.web.port}
        if self.ui is not None and getattr(self.ui, "httpd", None) is not None:
            private.add(self.ui.httpd.server_address[1])  # (the port it actually listens on)
        for sid, d in sorted(self.daemons.items()):
            try:
                props = read_properties(d.m.server_dir / "server.properties")
                port = int(props.get("server-port", "25565") or 25565)
                if props.get("enable-rcon") == "true":
                    private.add(int(props.get("rcon.port", "25575") or 25575))
            except (OSError, ValueError):
                continue
            out.append((port, "TCP", f"Craft Conductor {sid}"[:60]))
        if self.share:
            out.append((self.share_settings()["port"], "TCP", "Craft Conductor friends' downloads"))
        seen, unique = set(), []
        for port, proto, label in out:
            if port in private:
                log.warning("not forwarding port %s on the router: the control panel or RCON uses it", port)
            elif (port, proto) not in seen:
                seen.add((port, proto))
                unique.append((port, proto, label))
        return unique

    def upnp_sync(self, enabled: bool | None = None) -> dict:
        """Forward the wanted ports (or, switched off, take back the ones craft-conductor forwarded)."""
        from . import upnp
        with self._upnp_lock:
            settings = self.upnp_settings()
            if enabled is not None:
                settings["enabled"] = enabled
            wanted = self.upnp_wanted() if settings["enabled"] else []
            status = {"enabled": settings["enabled"], "checked": time.time(), "ports": [], "router": "", "external_ip": "",
                      "error": "", "warning": "", "exposure": upnp.EXPOSURE_WARNING if settings["enabled"] else ""}
            mapped = set(settings["mapped"])
            if settings["enabled"] or mapped:
                try:
                    gw = self._gateway if self._gateway and time.time() - self._gateway_at < 600 else None
                    if gw is None:
                        gw = upnp.find()
                        self._gateway, self._gateway_at = gw, time.time()
                    status["router"] = gw.name
                    for port, proto in sorted(mapped - {(p, pr) for p, pr, _ in wanted}):
                        try:
                            upnp.remove(gw, port, proto)
                            mapped.discard((port, proto))
                        except upnp.UpnpError as e:
                            log.warning("couldn't take back port %s on the router: %s", port, e)
                    for port, proto, label in wanted:
                        try:
                            upnp.add(gw, port, proto, label)
                            mapped.add((port, proto))
                            status["ports"].append({"port": port, "protocol": proto, "label": label, "ok": True})
                        except upnp.UpnpError as e:
                            status["ports"].append({"port": port, "protocol": proto, "label": label, "ok": False, "error": str(e)})
                    if wanted:
                        try:
                            status["external_ip"] = upnp.external_ip(gw)
                            status["warning"] = upnp.shared_address(status["external_ip"]) or ""
                        except upnp.UpnpError:
                            pass
                except upnp.UpnpError as e:
                    self._gateway = None
                    status["error"] = str(e)
                except OSError as e:
                    self._gateway = None
                    status["error"] = f"couldn't look for the router ({e.strerror or e})"
            # (written into hub.json as it is now: anything saved while the router was asked stays)
            saved = {"enabled": settings["enabled"], "mapped": [list(x) for x in sorted(mapped)]}
            self._update_hub_file(lambda data: data.__setitem__("upnp", saved))
            self._upnp_status = status
            if status["error"] and settings["enabled"]:
                log.warning("automatic port forwarding: %s", status["error"])
            return status

    def _upnp_close(self) -> None:
        from . import upnp
        mapped = self.upnp_settings()["mapped"]
        gw = self._gateway or upnp.find(timeout=2)
        for port, proto in mapped:
            try:
                upnp.remove(gw, port, proto)
            except upnp.UpnpError as e:
                log.warning("couldn't take back port %s on the router: %s", port, e)
        self._update_hub_file(lambda data: data.__setitem__("upnp", {**data.get("upnp", {}), "mapped": []}))

    def upnp_status(self) -> dict:
        from .upnp import EXPOSURE_WARNING
        settings = self.upnp_settings()
        return self._upnp_status or {**settings, "ports": [], "checked": None, "error": "", "warning": "",
                                     "exposure": EXPOSURE_WARNING if settings["enabled"] else ""}

    # ---------------------------------------------------- playit.gg tunnels
    def check_tunnels(self) -> None:
        """Check each server's playit.gg tunnel (every 5 minutes), and say when one stops or
        starts working again (in its activity, and to Discord if set up)."""
        for d in list(self.daemons.values()):
            if d.m.config.tunnel_address:
                d.tunnel_check(force=True)

    # -------------------------------------------------- friends asking to join
    JOIN_REQUESTS_KEPT = 20

    def add_join_request(self, sid: str, name: str, ip: str) -> str:
        """A friend (with the invite) asks to be let in: kept for the owner to Allow or Ignore
        on the Players page. One ask per address every 10 seconds; at most 20 waiting."""
        now = time.time()
        with self._requests_lock:
            last = self._request_times.get(ip, 0)
            if now - last < 10:
                return "slow down"
            self._request_times[ip] = now
            if len(self._request_times) > 500:  # forget old addresses
                self._request_times = {k: v for k, v in self._request_times.items() if now - v < 60}
            d = self.daemons.get(sid)
            if d is not None:
                from .players import Players
                try:
                    if any(str(p.get("name", "")).lower() == name.lower() for p in Players(d.m.server_dir)._read("whitelist")):
                        return "already allowed"
                except Exception:  # an unreadable whitelist: ask the owner anyway
                    pass
            waiting = [r for r in self.join_requests.get(sid, []) if r["name"].lower() != name.lower()]
            waiting.append({"name": name, "time": now})
            self.join_requests[sid] = waiting[-self.JOIN_REQUESTS_KEPT:]
        log.info("%s asks to join %s", name, sid)
        if d is not None:
            d.m.notifier.send(f"{name} asks to join: allow them on the Players page in Craft Conductor.")
        return "asked"

    def answer_join_request(self, sid: str, name: str) -> None:
        with self._requests_lock:
            self.join_requests[sid] = [r for r in self.join_requests.get(sid, []) if r["name"].lower() != name.lower()]

    def summary(self) -> list[dict]:
        out = []
        for sid, d in list(self.daemons.items()):
            from .properties import read_properties
            props = read_properties(d.m.server_dir / "server.properties")
            lk = d.m.lock
            out.append({
                "id": sid, "name": props.get("motd") or sid, "state": d.state,
                "setup_pending": d.setup_pending, "job": d.job, "minecraft": lk.minecraft,
                "loader": lk.loader or d.m.config.server.loader, "players": len(d.players),
                "max_players": int(props.get("max-players", "20") or 20),
                "port": props.get("server-port", "25565"), "folder": str(d.m.config.root),
                "update": bool(d.last_check and not d.last_check.get("up_to_date") and d.last_check.get("target")),
                "crashed_at": d.crashed_at, "last_job": d.last_job,
                "join_requests": len(self.join_requests.get(sid, [])),
            })
        for sid, p in self.problems.items():
            out.append({"id": sid, "name": p.get("name") or sid, "state": "unavailable", "problem": p["problem"],
                        "folder": p["root"]})
        return out

    # ------------------------------------------------------ self-update
    def update_channel(self) -> str:
        """Which Craft Conductor releases are offered: stable (the default) or beta too."""
        if self._single:
            return self._single.m.config.self_update_channel
        saved = self._hub_file().get("self_update")
        return selfupdate.channel_or_default(saved.get("channel") if isinstance(saved, dict) else None)

    def set_update_channel(self, channel: str) -> None:
        if channel not in selfupdate.CHANNELS:
            raise ConfigError("the update channel is stable or beta")
        if self._single:
            configmod.set_value(self._single.m.config.path, "craft-conductor", "update_channel", json.dumps(channel))
            self._single.m.reload_config()
            self.updater.forget()  # (what was offered may not be on this channel)
            return

        def change(data: dict) -> None:
            saved = data.get("self_update") if isinstance(data.get("self_update"), dict) else {}
            data["self_update"] = {**saved, "channel": channel}
        self._update_hub_file(change)
        self.updater.forget()
        log.info("Craft Conductor updates: %s channel", channel)

    def check_self_update(self) -> str:
        if self._single:
            return self._single.check_self_update()
        if self.updater.in_progress:  # (what's being installed isn't offered again)
            return f"Craft Conductor {self.updater.release['version']} is being installed"
        try:
            release = selfupdate.check(self.http, channel=self.update_channel())
        except Exception as e:
            log.debug("craft-conductor update check failed: %s", e)
            return f"couldn't check for Craft Conductor updates: {e}"
        if release is None:
            self.updater.offer(None)
            return f"Craft Conductor {selfupdate.__version__} is the latest version"
        can, why = selfupdate.install_method(release)
        first = self.updater.offer({**release.to_dict(), "current": selfupdate.__version__, "can_install": can, "reason": why})
        if first:  # (phones are told too; the update itself is done in the control panel)
            self.update_push(f"Craft Conductor {release.version} is available (you have {selfupdate.__version__}). "
                             "Open Craft Conductor on your computer to update.", "/#craft-conductor")
        return f"Craft Conductor {release.version} is available"

    def self_update_info(self) -> dict | None:
        """The update on offer and where it stands (selfupdate.Updater.snapshot), or None."""
        return self.updater.snapshot()

    def start_self_update(self, version: str) -> bool:
        """Accept the update and install it in the background. False when one is already under way:
        a second click (or a second browser) starts nothing."""
        if not self.updater.begin(version):
            return False
        self.run_job(f"update Craft Conductor to {version}", self.apply_self_update)
        return True

    def apply_self_update(self) -> str:
        """Install the accepted update (see start_self_update), stop every server cleanly, and
        restart craft-conductor on the new version."""
        if self._single:
            return self._single.apply_self_update()
        u = self.updater
        if not u.in_progress:
            raise RuntimeError("no craft-conductor update is accepted")
        old, new = selfupdate.__version__, (u.release or {}).get("version", "")
        try:
            message = u.run_install(self.http, self.state_dir)
        except Exception as e:
            self.update_failed(old, new, str(e), bool(u.failure and u.failure.get("reverted")))
            raise
        running = [d for d in self.daemons.values() if d.proc and d.proc.running]
        if any(d.players for d in running):
            for d in running:
                d.proc.say("Server stopping in 1 minute: updating the server manager")
            self.stop_requested.wait(60)
        for d in running:
            d.proc.say("Stopping now!")
        log.info("%s; restarting Craft Conductor", message)
        self.restart_requested = True
        self.stop_requested.set()
        return message

    # What the phones (and Discord) are told about the update. Phones can't update anything: they're told,
    # and tapping the notification opens Craft Conductor, where it's done.
    def update_push(self, message: str, url: str = "/") -> None:
        try:
            self.push.notify("Craft Conductor", message, url=url, tag="cc_update", kind="updates")
        except Exception:
            log.exception("couldn't send the update notification")

    def update_failed(self, old: str, new: str, why: str, reverted: bool) -> None:
        """An update that didn't work, before the restart (Craft Conductor carries on): recorded, so every
        open page and phone hears of it once."""
        message = f"The update to Craft Conductor {new} didn't work: {why}"
        if reverted:
            message += f" Craft Conductor {old} is back."
        rollback.record_result(self.state_dir, False, old, new, message, reverted)
        rollback.mark_announced(self.state_dir)
        self.update_push(message[:300], "/#craft-conductor")

    def settle_update(self) -> None:
        """Called once the control panel is up. If this copy is the one an update was installing, it says so
        (the guard then lets the previous version go); and the phones hear how the last update ended."""
        try:
            outcome = rollback.settle(self.state_dir, selfupdate.__version__)
        except Exception:
            log.exception("couldn't settle the last update")
            return
        if outcome:
            if outcome.get("ok"):
                self.update_push(f"Craft Conductor was updated to {outcome['to']}. Open it to launch the new version.")
            else:
                self.update_push(outcome.get("message") or "The Craft Conductor update didn't work.", "/#craft-conductor")

    def update_result(self) -> dict | None:
        """How the last update ended, for the page (read again only when the file changed: every page asks every 2 s)."""
        path = self.state_dir / rollback.RESULT
        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            return None
        cached = getattr(self, "_result_cache", None)
        if cached is None or cached[0] != stamp:
            cached = self._result_cache = (stamp, rollback.public(rollback.result(self.state_dir)))
        return cached[1]

    def run_job(self, name: str, fn: Callable[[], str]) -> None:
        """Run a hub-level task (like installing an craft-conductor update) in the background."""
        def runner():
            set_current_server(None)
            try:
                fn()
            except Exception as e:
                log.error("%s failed: %s", name, e)
        threading.Thread(target=runner, daemon=True, name=f"hub:{name}").start()

    # --------------------------------------------------------- lifecycle
    def run(self) -> int:
        """Serve the web UI and manage the servers until asked to stop."""
        from .web import WebUI

        state = self.state_dir
        state.mkdir(parents=True, exist_ok=True)
        if pid := running_hub(self.home):
            log.error("Craft Conductor is already running (pid %s)", pid)
            return 1
        hub_pid_path(self.home).write_text(str(os.getpid()))
        hub_stop_path(self.home).unlink(missing_ok=True)
        from . import preview
        threading.Thread(target=preview.clean, args=(self,), daemon=True, name="preview-clean").start()  # last time's maps
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, lambda *_: self.stop_requested.set())
        ui = None
        try:
            self.scan()
            ui = WebUI(self)
            ui.start()
            self.ui = ui
            self.settle_update()
            if self.open_browser:
                import webbrowser
                threading.Timer(1.0, webbrowser.open, args=(ui.url,)).start()
            next_scan, next_self_check = 0.0, time.monotonic() + 30
            next_status = time.monotonic() + 20
            next_tunnels = time.monotonic() + 60
            next_upnp = time.monotonic() + 15
            next_health = time.monotonic() + 30
            while not self.stop_requested.is_set():
                if hub_stop_path(self.home).exists():
                    hub_stop_path(self.home).unlink(missing_ok=True)
                    log.info("stop requested")
                    break
                now = time.monotonic()
                if now >= next_scan:
                    next_scan = now + SCAN_EVERY
                    self.scan()
                    self.update_share()
                if now >= next_self_check:
                    next_self_check = now + SELF_CHECK_INTERVAL
                    self.run_job("craft-conductor update check", self.check_self_update)
                if now >= next_tunnels:
                    next_tunnels = now + 300
                    threading.Thread(target=self.check_tunnels, daemon=True, name="tunnels").start()
                if now >= next_upnp:
                    next_upnp = now + self.UPNP_EVERY
                    if self.upnp_settings()["enabled"]:
                        threading.Thread(target=self.upnp_sync, daemon=True, name="upnp").start()
                if now >= next_health:
                    next_health = now + 60
                    threading.Thread(target=self._check_health, daemon=True, name="health").start()
                if now >= next_status:
                    next_status = now + 30
                    threading.Thread(target=self.discord_status, daemon=True, name="discord-status").start()
                    threading.Thread(target=self.sync_discord_bot, daemon=True, name="discord-whitelist-sync").start()
                self.stop_requested.wait(self.tick)
            return 0
        finally:
            if ui:
                ui.stop()
            if self.share:
                self.share.stop()
            if self._hub_file().get("discord", {}).get("status_channel"):
                self.discord_status(off=True)  # say craft-conductor is closed, rather than leave "online" up
            if self.discord_bot is not None:
                self.discord_bot.close()
            if self.map_session is not None:  # (a map's private server)
                self.map_session.close()
            for d in list(self.daemons.values()):  # (an update rehearsal's copy of a server)
                if d.rehearsal is not None:
                    d.rehearsal.close()
            if self.upnp_settings()["mapped"]:  # the servers stop: close the ports on the router too
                try:
                    self._upnp_close()
                except Exception:
                    log.exception("couldn't take the ports back on the router")
            self._stop_all()
            hub_pid_path(self.home).unlink(missing_ok=True)

    def _stop_all(self) -> None:
        for d in self.daemons.values():
            d.stop_requested.set()
        for t in self._threads.values():
            t.join(timeout=max((d.m.config.server.stop_timeout for d in self.daemons.values()), default=60) + 30)
