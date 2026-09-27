"""The friend's side of an invite, as a page in their browser ("mcfui").

Double-clicking a server's download opens this page: it shows the server (name,
Minecraft version, mods), lets the friend tick the launchers to add it to (Minecraft
Launcher, Prism Launcher, Modrinth App, CurseForge), and shows progress. It only
listens on 127.0.0.1, behind a random secret in every URL, and stops when the page
is closed. The console flow (join.run_interactive) remains for when no browser opens.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import launchers
from .http import HttpError
from .mods.base import ModError
from .friendextras import ExtrasError
from .join import Invite, Joiner, JoinError, _supports_quick_play, validate_pack

log = logging.getLogger(__name__)

HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' https: data:; style-src 'self'; "
                               "frame-ancestors 'none'; form-action 'none'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
STATIC = {"": ("join.html", "text/html; charset=utf-8"), "join.js": ("join.js", "text/javascript; charset=utf-8"),
          "rich.js": ("rich.js", "text/javascript; charset=utf-8"),
          "style.css": ("style.css", "text/css; charset=utf-8"), "icon.png": ("icon.png", "image/png")}
ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
START_SERVER = -1  # run() result: the person chose to run their own server instead
IDLE_SECONDS = 180  # the page pings while it's open; stop a while after it's closed


class ExtrasChanges(Exception):
    """Some of the friend's extras don't fit the server's Minecraft: ask before going on."""

    def __init__(self, changes: list[dict]):
        super().__init__("changes")
        self.changes = changes


def _invites_file(mc_dir: Path) -> Path:
    return mc_dir / "mcsm" / "invites.json"


def _running_file(mc_dir: Path) -> Path:
    """Where the open setup page is noted (its port and secret), so opening mcsm again, or an
    invite page's "Open in mcsm", brings that page back instead of starting a second copy."""
    return mc_dir / "mcsm" / "join-running.json"


def hand_over(mc_dir: Path, invite: Invite | None) -> bool:
    """Ask an mcsm that's already setting up Minecraft to show its page again (with this invite,
    if one came along). True when it did, so this copy can simply exit."""
    try:
        data = json.loads(_running_file(mc_dir).read_text())
        port, token = int(data["port"]), str(data["token"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", token) or not 0 < port < 65536:
        return False
    import urllib.request
    req = urllib.request.Request(f"http://127.0.0.1:{port}/{token}/api/reopen", method="POST",
                                 data=json.dumps({"invite": invite.code if invite else ""}).encode(),
                                 headers={"Content-Type": "application/json", "X-MCSM": "1"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # this computer only, never a proxy
    try:
        with opener.open(req, timeout=5) as r:
            return json.loads(r.read() or b"{}").get("ok") is True
    except (OSError, ValueError):
        return False  # not running any more (a leftover note)


def remembered(mc_dir: Path) -> list[dict]:
    """Servers this computer has joined: open mcsm again to update one, no invite needed."""
    try:
        data = json.loads(_invites_file(mc_dir).read_text())
        return [x for x in data if isinstance(x, dict) and isinstance(x.get("code"), str) and isinstance(x.get("name"), str)]
    except (OSError, ValueError, TypeError):
        return []


def pack_digest(pack: dict) -> str:
    """A short fingerprint of what a server asks players to have (Minecraft, loader, mods), to
    tell later whether the server changed since this computer was set up for it."""
    import hashlib
    key = {"minecraft": pack.get("minecraft"), "loader": pack.get("loader"), "loader_version": pack.get("loader_version"),
           "mods": sorted(f"{m.get('filename')}|{m.get('sha1') or m.get('sha512')}" for m in pack.get("mods", [])),
           "manual": sorted(str(m.get("name")) for m in pack.get("manual", []))}
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:20]


def remember(mc_dir: Path, name: str, code: str, digest: str = "") -> None:
    items = [x for x in remembered(mc_dir) if x["name"] != name and x["code"] != code]
    items.insert(0, {"name": name[:100], "code": code, "at": time.time(), "digest": digest})
    path = _invites_file(mc_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # the invites hold each server's secret
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(items[:20], indent=2))
    tmp.replace(path)


class JoinUI:
    def __init__(self, invite: Invite | None, pack: dict | None = None, mc_dir: Path | None = None,
                 prism_dir: Path | None = None, out_dir: Path | None = None, http=None):
        self.invite = invite
        self.pack = validate_pack(pack) if pack else None
        self.pack_error = ""
        self.prism_dir = prism_dir
        self.out_dir = out_dir
        self.lines: list[str] = []
        self._mc_dir, self._http = mc_dir, http
        self.joiner = Joiner(invite or Invite("localhost", 1, "local-" + "0" * 16), mc_dir=mc_dir, http=http,
                             say=self._say)
        self.wants_server = False  # "I want to run my own server instead" (no invite)
        self.token = secrets.token_urlsafe(18)
        self.results: list[dict] = []
        self.running = False
        self.done = threading.Event()
        self.last_seen = time.monotonic()
        self._lock = threading.Lock()
        self.httpd: ThreadingHTTPServer | None = None
        self.url = ""
        self.open_browser = webbrowser.open

    # ------------------------------------------------------------ state
    def _say(self, line: str) -> None:
        with self._lock:
            self.lines.append(line)
        print(line, flush=True)

    def load_pack(self) -> None:
        if self.pack is not None or self.invite is None:
            return
        try:
            self.pack = self.joiner.fetch_pack()
            self.pack_error = ""
        except JoinError as e:
            self.pack_error = str(e)

    def use_invite(self, text: str) -> None:
        """An invite pasted on the page (mcsm was opened without one)."""
        from .join import parse_invite
        invite = parse_invite(text)
        with self._lock:
            self.invite, self.pack, self.pack_error = invite, None, ""
            self.joiner = Joiner(invite, mc_dir=self._mc_dir, http=self._http, say=self._say)
        self.load_pack()
        if self.pack is None:
            raise ValueError(self.pack_error or "couldn't reach the server")

    def check_remembered(self) -> list[dict]:
        """Whether each server joined before has changed (Minecraft or mods) since: asked of each
        server at once, briefly, over its pinned HTTPS."""
        from concurrent.futures import ThreadPoolExecutor
        from .http import HttpClient
        from .join import parse_invite

        def one(entry: dict) -> dict:
            out = {"code": entry["code"], "changed": None, "minecraft": None, "error": None}
            try:
                http = self._http or HttpClient(retries=1, timeout=8, cache_ttl=0)
                pack = Joiner(parse_invite(entry["code"]), mc_dir=self._mc_dir, http=http, say=lambda _: None).fetch_pack()
                out["minecraft"] = pack.get("minecraft")
                out["changed"] = bool(entry.get("digest")) and pack_digest(pack) != entry["digest"]
            except (JoinError, HttpError, OSError, ValueError) as e:
                out["error"] = str(e)
            return out
        items = remembered(self.joiner.mc)[:10]
        if not items:
            return []
        with ThreadPoolExecutor(max_workers=4) as pool:
            return list(pool.map(one, items))

    def ask_to_join(self, name: str) -> str:
        if self.invite is None:
            raise ValueError("there's no invite to ask with")
        return self.joiner.ask_to_join(name)

    def info(self) -> dict:
        self.load_pack()
        p = self.pack
        need = self.invite is None and p is None
        copied = None
        if need:  # an invite the friend copied: filled in for them
            from . import clipboard
            found = clipboard.invite()
            copied = found.code if found else None
        return {
            "need_invite": need,
            "running": self.running, "finished": bool(self.results),
            "copied_invite": copied,
            "remembered": remembered(self.joiner.mc) if need else [],
            "pack": None if p is None else {
                "name": p["name"], "address": p["address"], "minecraft": p["minecraft"], "loader": p["loader"],
                "loader_version": p.get("loader_version"), "mods": [m["name"] for m in p.get("mods", [])],
                "manual": p.get("manual", []), "icon": p.get("icon") if str(p.get("icon") or "").startswith("data:image/png;base64,") else None,
                "quick_play": _supports_quick_play(p["minecraft"]), "memory_gb": int(p.get("memory_gb") or 4),
                "whitelist": bool(p.get("whitelist")) and self.invite is not None},
            "error": self.pack_error,
            "system_gb": _system_gb(),
            "launchers": [f.to_dict() for f in launchers.detect(self.joiner.mc, self.prism_dir)],
        }

    # ------------------------------------------------------ the friend's extras
    def store(self):
        from .friendextras import Store
        if self.pack is None:
            raise ValueError(self.pack_error or "the server's details haven't loaded")
        return Store(self.joiner.mc, self.pack["name"])

    def extras(self) -> dict:
        from .friendextras import MOD_LOADERS, SHADER_LOADERS
        data = self.store().load()
        loader = self.pack["loader"]
        return {"items": data["items"], "deps": data.get("deps", []), "minecraft": self.pack["minecraft"],
                "kinds": {"shader": loader in SHADER_LOADERS, "resourcepack": True, "mod": loader in MOD_LOADERS}}

    def _resolve(self, data: dict):
        from .friendextras import resolve
        included = {m.get("project") for m in self.pack.get("mods", []) if m.get("project")}
        return resolve(self.joiner.http, data, self.pack, included)

    def check_extras(self) -> dict:
        """Which extras fit the server's Minecraft, what comes along with them, and what doesn't fit."""
        from .friendextras import changes_for
        store = self.store()
        data = store.load()
        entries, problems = self._resolve(data)
        adds = [{"name": e["name"], "needed_by": e.get("needed_by")} for e in entries if e.get("needed_by")]
        if data.get("deps") != adds:  # remembered, so the list can show what each extra brings along
            store.save({**store.load(), "deps": adds})
        return {"adds": adds,
                "changes": changes_for(data, self.pack, problems), "previous": data.get("minecraft"),
                "minecraft": self.pack["minecraft"]}

    def setup(self, targets: list[str], memory_gb: int | None = None, accept_changes: bool = False) -> None:
        targets = [t for t in targets if t in launchers.KEYS]
        if not targets:
            raise ValueError("pick at least one launcher")
        if self.pack is None:
            raise ValueError(self.pack_error or "the server's details haven't loaded")
        if memory_gb is not None:  # the friend's own choice for their computer
            if not 1 <= int(memory_gb) <= 64:
                raise ValueError("pick between 1 and 64 GB of memory")
            self.pack = {**self.pack, "memory_gb": int(memory_gb)}
        # Their own extras: some may not fit the server's (new) Minecraft. Ask before changing anything.
        from .friendextras import apply_changes, changes_for
        store = self.store()
        data = store.load()
        notes: list[str] = []
        if data["items"]:
            entries, problems = self._resolve(data)
            if problems and not accept_changes:
                raise ExtrasChanges(changes_for(data, self.pack, problems))
            if problems:
                data, notes = apply_changes(store, data, self.pack, problems)
                entries, _ = self._resolve(data)
            store.save({**data, "minecraft": self.pack["minecraft"]})
            install_pack = {**self.pack, "mods": self.pack.get("mods", []) + entries}
        else:
            install_pack = self.pack
        with self._lock:
            if self.running:
                raise RuntimeError("already setting things up")
            self.running = True
            self.results = []

        def work():
            try:
                self._say(f"Setting up Minecraft {self.pack['minecraft']} for {self.pack['name']}")
                for note in notes:
                    self._say(note)
                self.results = self.joiner.run_targets(install_pack, targets, prism_dir=self.prism_dir, out_dir=self.out_dir)
                if self.invite and self.invite.fp and any(r.get("ok") for r in self.results):
                    remember(self.joiner.mc, self.pack["name"], self.invite.code, pack_digest(self.pack))  # to update it next time
            except HttpError as e:
                self._say(f"A download failed: {e}. Check your internet connection and try again.")
            except Exception as e:  # keep the page informed whatever happens
                log.exception("setting up failed")
                self._say(f"Something went wrong: {e}")
            finally:
                self.running = False
                self._say("Finished.")
        threading.Thread(target=work, daemon=True).start()

    def open_again(self, key: str) -> bool:
        from . import opener
        r = next((x for x in self.results if x.get("launcher") == key and x.get("ok")), None)
        if r is None:
            return False
        if key == "minecraft":
            return self.joiner.open_launcher()
        if key == "prism":
            return launchers.open_prism(launchers_slug(self.pack), self.pack["address"])
        if key == "modrinth":
            return opener.open_path(Path(r["where"]))
        return opener.reveal(Path(r["where"]))

    # ------------------------------------------------------------ serving
    def start(self) -> str:
        ui = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status: int, body: bytes, ctype: str) -> None:
                self.send_response(status)
                for k, v in HEADERS.items():
                    self.send_header(k, v)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _json(self, status: int, data) -> None:
                self._send(status, json.dumps(data).encode(), "application/json")

            def _route(self) -> str | None:
                host = (self.headers.get("Host") or "").lower()
                port = ui.httpd.server_address[1]
                if host not in (f"127.0.0.1:{port}", f"localhost:{port}"):
                    self._json(403, {"error": "forbidden"})
                    return None
                path = urlparse(self.path).path
                prefix = f"/{ui.token}/"
                if not path.startswith(prefix):
                    self._json(404, {"error": "not found"})
                    return None
                ui.last_seen = time.monotonic()
                return path[len(prefix):]

            def do_GET(self):
                rest = self._route()
                if rest is None:
                    return
                if rest in STATIC:
                    name, ctype = STATIC[rest]
                    self._send(200, resources.files("mcsm").joinpath("webui", name).read_bytes(), ctype)
                elif rest == "api/info":
                    self._json(200, ui.info())
                elif rest.startswith("api/extras"):
                    try:
                        if rest == "api/extras":
                            self._json(200, ui.extras())
                        elif rest == "api/extras/check":
                            self._json(200, ui.check_extras())
                        elif rest == "api/extras/search":
                            from .friendextras import search
                            q = parse_qs(urlparse(self.path).query)
                            if ui.pack is None:
                                raise ValueError(ui.pack_error or "the server's details haven't loaded")
                            self._json(200, {"results": search(ui.joiner.http, (q.get("kind") or [""])[0],
                                                               (q.get("q") or [""])[0], ui.pack,
                                                               int((q.get("offset") or ["0"])[0] or 0),
                                                               (q.get("sort") or [""])[0], (q.get("category") or [""])[0])})
                        elif rest == "api/extras/project":  # the details pane
                            from .browse import Browser
                            pid = (parse_qs(urlparse(self.path).query).get("id") or [""])[0]
                            if not ID_RE.fullmatch(pid):
                                raise ValueError("bad project id")
                            self._json(200, Browser(ui.joiner.http).project("modrinth", pid))
                        elif rest == "api/extras/requires":  # what a mod brings along, before adding it
                            from .friendextras import MOD_LOADERS
                            from .mods.modrinth import ModrinthProvider
                            from .web import mod_requirements
                            pid = (parse_qs(urlparse(self.path).query).get("id") or [""])[0]
                            if not ID_RE.fullmatch(pid):
                                raise ValueError("bad project id")
                            if ui.pack is None or ui.pack["loader"] not in MOD_LOADERS:
                                raise ValueError("this server can't run mods")
                            self._json(200, mod_requirements(ModrinthProvider(ui.joiner.http), pid,
                                                             MOD_LOADERS[ui.pack["loader"]], ui.pack["minecraft"]))
                        elif rest == "api/extras/categories":
                            from .browse import Browser
                            from .friendextras import KINDS
                            kind = (parse_qs(urlparse(self.path).query).get("kind") or [""])[0]
                            if kind not in KINDS:
                                raise ValueError("unknown kind")
                            self._json(200, {"categories": Browser(ui.joiner.http).categories("modrinth", KINDS[kind][1])})
                        else:
                            self._json(404, {"error": "not found"})
                    except (ValueError, ExtrasError, ModError) as e:
                        self._json(400, {"error": str(e)})
                    except HttpError as e:
                        self._json(502, {"error": e.friendly})
                elif rest == "api/remembered/check":
                    self._json(200, {"servers": ui.check_remembered()})
                elif rest == "api/progress":
                    since = int((parse_qs(urlparse(self.path).query).get("since") or ["0"])[0] or 0)
                    with ui._lock:
                        lines = ui.lines[since:]
                        n = len(ui.lines)
                    self._json(200, {"lines": lines, "next": n, "running": ui.running, "results": ui.results})
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self):
                rest = self._route()
                if rest is None:
                    return
                if self.headers.get("X-MCSM") != "1":
                    self._json(403, {"error": "missing header"})
                    return
                try:
                    length = min(int(self.headers.get("Content-Length") or 0), 64 * 1024)
                    body = json.loads(self.rfile.read(length) or b"{}")
                    if rest == "api/invite":
                        ui.use_invite(str(body.get("invite", ""))[:2000])
                        self._json(200, ui.info())
                    elif rest == "api/reopen":  # mcsm was opened again: show this page again
                        ui.reopen(str(body.get("invite", ""))[:2000])
                        self._json(200, {"ok": True})
                    elif rest == "api/ask-to-join":
                        result = ui.ask_to_join(str(body.get("name", "")).strip()[:16])
                        self._json(200, {"ok": result != "slow down", "result": result})
                    elif rest == "api/own-server":  # not joining after all: open mcsm's control panel
                        ui.wants_server = True
                        ui.done.set()
                        self._json(200, {"ok": True})
                    elif rest == "api/setup":
                        mem = body.get("memory_gb")
                        ui.setup([str(x) for x in body.get("launchers", [])],
                                 int(mem) if isinstance(mem, (int, float)) else None, body.get("accept_changes") is True)
                        self._json(200, {"ok": True})
                    elif rest == "api/extras/add":
                        ui.store().add(str(body.get("kind", "")), str(body.get("id", "")), str(body.get("slug", "")),
                                       str(body.get("name", "")))
                        check = ui.check_extras()  # first: it remembers what comes along
                        self._json(200, {**ui.extras(), **check})
                    elif rest == "api/extras/remove":
                        ui.store().remove(str(body.get("id", "")))
                        try:
                            ui.check_extras()  # what's still brought along
                        except HttpError:
                            pass  # offline: the list catches up next time
                        self._json(200, ui.extras())
                    elif rest == "api/extras/enable":
                        ui.store().set_enabled(str(body.get("id", "")), body.get("enabled") is True)
                        self._json(200, ui.extras())
                    elif rest == "api/open":
                        self._json(200, {"ok": ui.open_again(str(body.get("launcher", "")))})
                    elif rest == "api/quit":
                        ui.done.set()  # before replying, so whoever asked sees it done
                        self._json(200, {"ok": True})
                    else:
                        self._json(404, {"error": "not found"})
                except ExtrasChanges as e:
                    self._json(409, {"error": "some of your extras don't fit this Minecraft version", "changes": e.changes})
                except (ValueError, RuntimeError, ExtrasError, JoinError) as e:
                    self._json(400, {"error": str(e)})
                except HttpError as e:
                    self._json(502, {"error": e.friendly})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/{self.token}/"
        self._note_running()
        return self.url

    def _note_running(self) -> None:
        path = _running_file(self.joiner.mc)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # holds the page's secret
            with os.fdopen(fd, "w") as f:
                f.write(json.dumps({"port": self.httpd.server_address[1], "token": self.token, "pid": os.getpid()}))
        except OSError as e:
            log.debug("couldn't note the open page: %s", e)

    def reopen(self, invite_text: str) -> None:
        """Show the page again (someone closed the tab, then opened mcsm again). A new invite
        replaces the current one unless Minecraft is being set up right now."""
        if invite_text and not self.running:
            from .join import parse_invite
            try:
                new = parse_invite(invite_text)
                if self.invite is None or new.code != self.invite.code:
                    with self._lock:
                        self.invite, self.pack, self.pack_error, self.results = new, None, "", []
                        self.joiner = Joiner(new, mc_dir=self._mc_dir, http=self._http, say=self._say)
            except JoinError as e:
                log.debug("ignored an invite handed over: %s", e)
        self.last_seen = time.monotonic()
        threading.Thread(target=self.open_browser, args=(self.url,), daemon=True).start()

    def stop(self) -> None:
        if self.httpd:
            try:
                path = _running_file(self.joiner.mc)
                if json.loads(path.read_text()).get("token") == self.token:
                    path.unlink()
            except (OSError, ValueError, AttributeError):
                pass
            self.httpd.shutdown()
            self.httpd.server_close()

    def wait(self) -> None:
        while not self.done.wait(2):
            if not self.running and time.monotonic() - self.last_seen > IDLE_SECONDS:
                break


def _system_gb() -> int | None:
    from .setup import total_ram_gb
    total = total_ram_gb()
    return int(total) if total else None


def launchers_slug(pack: dict) -> str:
    from .join import slugify
    return slugify(pack["name"])


def run(invite: Invite | None, pack: dict | None = None, mc_dir: Path | None = None,
        open_browser=webbrowser.open) -> int | None:
    """Show the page; ``None`` when no browser could be opened (use the console instead)."""
    ui = JoinUI(invite, pack=pack, mc_dir=mc_dir)
    if pack is None and hand_over(ui.joiner.mc, invite):
        print("mcsm is already setting up Minecraft: its page is open in your browser again.")
        return 0
    ui.open_browser = open_browser
    url = ui.start()
    try:
        if not open_browser(url):
            return None
        print("mcsm opened a page in your browser to set up Minecraft for this server.")
        print(f"If it didn't appear, open {url}")
        print("Keep this window open until you're done there.", flush=True)
        ui.wait()
        if ui.wants_server:
            return START_SERVER
        return 0 if any(r.get("ok") for r in ui.results) else 1
    finally:
        ui.stop()
