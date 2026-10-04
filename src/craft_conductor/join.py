"""`craft-conductor join`: set up a friend's Minecraft to play on an craft-conductor server.

The friend downloads craft-conductor from the server's invite page. The file is named after the
server and carries the invite (host, share port and secret) in its name, so
double-clicking it is enough. It then:

1. fetches the server's client pack (clientpack.py) from the share server;
2. installs the matching Minecraft version and mod loader into the official
   Minecraft Launcher (which keeps handling sign-in: craft-conductor never sees a password);
3. downloads the mods into a folder of their own (other installations are untouched),
   checking every file's hash and only accepting Modrinth/CurseForge downloads;
4. adds an installation named after the server, and puts the server in its
   multiplayer list (on Minecraft 1.20+ it joins straight away);
5. opens the Minecraft Launcher.

Prism Launcher, the Modrinth App and CurseForge are set up by launchers.py; the page
where the friend picks launchers is joinui.py.

Running it again brings the mods in line with the server (e.g. after it upgraded).
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Callable
from urllib.parse import quote, urlparse

from . import nbt
from .desktop import child_env
from .clientpack import FORMAT, allowed_url
from .http import HashMismatch, HttpClient, HttpError, sha1_file
from .loaders.fabric import FABRIC_META, QUILT_META
from .loaders.forge import FORGE_MAVEN, NEOFORGE_MAVEN

PROFILE_FILES = ("launcher_profiles.json", "launcher_profiles_microsoft_store.json")
INVITE_IN_NAME = re.compile(r"\(craft-conductor-([A-Za-z0-9_-]{8,200})\)")
LOADERS = ("vanilla", "fabric", "quilt", "neoforge", "forge")
MANIFEST = ".craft-conductor-client.json"
FOLDERS = ("mods", "resourcepacks", "shaderpacks")  # where a pack's files go in the game directory


def folder_of(m: dict) -> str:
    return m.get("folder") if m.get("folder") in FOLDERS else "mods"


class JoinError(Exception):
    pass


@dataclass(frozen=True)
class Invite:
    """Where a server's friend download is, its secret, and the fingerprint of the certificate
    it must present: connections are HTTPS, and pinned to that certificate (tlscert.py)."""
    host: str
    port: int
    token: str
    fp: str = ""

    @property
    def netloc(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}".lower()

    @property
    def url(self) -> str:
        return f"https://{self.netloc}/join/{self.token}"

    @property
    def code(self) -> str:
        """What friends paste into craft-conductor (it's also in the invite link after the #)."""
        raw = f"{self.host}|{self.port}|{self.token}|{self.fp}".encode()
        return "craft-conductor-" + base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @property
    def link(self) -> str:
        """The server's own address with the fingerprint (for `craft-conductor join`; not for browsers)."""
        return f"{self.url}#{self.fp}"

    def page_link(self, name: str = "") -> str:
        """The link friends click: craft-conductor's invite page on GitHub Pages (a real certificate, so no
        browser warning). The invite follows the #, which browsers never send anywhere: the
        page reads it, offers craft-conductor's download from GitHub, and hands the invite to craft-conductor."""
        tail = "/" + quote(name.strip()[:60], safe="") if name.strip() else ""
        return f"{INVITE_PAGE}#{self.code}{tail}"


INVITE_PAGE = "https://silverwrx03.github.io/craft-conductor/join/"
CODE = re.compile(r"craft-conductor-[A-Za-z0-9_-]{40,400}")
OLD_INVITE = ("that invite is from an older Craft Conductor and isn't secure; ask the server's owner "
              "for a new one (their Craft Conductor needs updating first)")


def _checked(host: str, port, token: str, fp: str) -> Invite:
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise JoinError("that invite has a bad port") from None
    if not re.fullmatch(r"[A-Za-z0-9.:-]{1,253}", host or "") or not 1 <= port <= 65535 \
            or not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", token or ""):
        raise JoinError("that doesn't look like an Craft Conductor invite")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", fp or ""):
        raise JoinError(OLD_INVITE)
    return Invite(host, port, token, fp)


def parse_invite(text: str) -> Invite:
    """An invite code (craft-conductor-...) or link (https://host:port/join/<secret>#<fingerprint>)."""
    text = text.strip().strip('"').strip("'").strip("<>")
    code = CODE.search(text)
    if code and not text.startswith("craft-conductor-"):  # an invite page link, an craft-conductor:// link, a whole message
        return parse_invite(code.group(0))
    if "://" in text:
        u = urlparse(text)
        m = re.fullmatch(r"/join/([A-Za-z0-9_-]+)(/.*)?", u.path)
        if u.scheme not in ("http", "https") or not m or not u.hostname:
            raise JoinError("that link isn't an Craft Conductor invite (it should look like https://.../join/...)")
        if u.scheme != "https":
            raise JoinError(OLD_INVITE)
        return _checked(u.hostname, u.port or 443, m.group(1), u.fragment)
    code = text.removeprefix("craft-conductor-")
    try:
        raw = base64.urlsafe_b64decode(code + "=" * (-len(code) % 4)).decode()
        parts = raw.split("|")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise JoinError("that doesn't look like an Craft Conductor invite") from None
    if len(parts) == 3:
        raise JoinError(OLD_INVITE)
    if len(parts) != 4:
        raise JoinError("that doesn't look like an Craft Conductor invite")
    return _checked(*parts)


def invite_from_name(path: str | Path) -> Invite | None:
    """The invite carried in a downloaded file's name, e.g. "Join My Server (craft-conductor-XXXX).exe"."""
    m = INVITE_IN_NAME.search(Path(path).name)
    if not m:
        return None
    try:
        return parse_invite(m.group(1))
    except JoinError:
        return None


def minecraft_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / ".minecraft"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "minecraft"
    return Path.home() / ".minecraft"


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "server"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _supports_quick_play(minecraft: str) -> bool:
    """Minecraft 1.20+ can join a server straight from the launcher (--quickPlayMultiplayer)."""
    nums = [int(n) for n in re.findall(r"\d+", minecraft.split("-")[0])[:2]]
    if not nums:
        return False
    major, minor = nums[0], (nums[1] if len(nums) > 1 else 0)
    return major > 1 or minor >= 20


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def validate_pack(pack: object, base: str | None = None) -> dict:
    """Check a pack before using it. ``base`` is the invite link it came from: the server's
    own files for players are downloaded from there (and only from there). Anything
    unexpected is refused before it's acted on."""
    if not isinstance(pack, dict) or pack.get("format") != FORMAT:
        raise JoinError("the server sent something this version of Craft Conductor doesn't understand; "
                        "download the invite again")
    name, mc, loader = pack.get("name"), pack.get("minecraft"), pack.get("loader")
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise JoinError("the server's name is missing")
    if not isinstance(mc, str) or not re.fullmatch(r"\d+(\.\d+){1,3}(-[A-Za-z0-9.]+)?", mc):
        raise JoinError("the server's Minecraft version is missing")
    if loader not in LOADERS:
        raise JoinError(f"this server uses {loader!r}, which Craft Conductor can't set up for players")
    lv = pack.get("loader_version")
    if loader != "vanilla" and not (isinstance(lv, str) and re.fullmatch(r"[A-Za-z0-9.+_-]{1,64}", lv)):
        raise JoinError("the server's mod loader version is missing")
    if pack.get("singleplayer") is True and pack.get("address") == "":
        pass  # a single-player game (singleplayer.py): no server to join
    elif not isinstance(pack.get("address"), str) or not re.fullmatch(r"[A-Za-z0-9.:\[\]-]{1,260}", pack["address"]):
        raise JoinError("the server's address is missing")
    # Mods to download by hand: shown as links on the friend's page, so https ones only.
    pack["manual"] = [m for m in pack.get("manual", []) if isinstance(m, dict) and isinstance(m.get("url"), str)
                      and m["url"].startswith("https://") and isinstance(m.get("name"), str)]
    own = f"{base}/mods/" if base else None
    if not own:  # no invite (a server folder on this computer): its own files can't be fetched
        pack["mods"] = [m for m in pack.get("mods", []) if not (isinstance(m, dict) and m.get("local"))]
    for m in pack.get("mods", []):
        if not isinstance(m, dict) or not re.fullmatch(r"[^/\\:*?\"<>|]{1,200}\.jar", str(m.get("filename", ""))) \
                or str(m["filename"]).startswith("."):
            raise JoinError("the server's mod list has a bad file name in it")
        if m.get("local") and own and str(m.get("url", "")).startswith(own) and m.get("sha1"):
            continue  # one of the server owner's own files, from the server itself
        if not allowed_url(str(m.get("url", ""))):
            raise JoinError(f"{m.get('name')}: Craft Conductor only downloads mods from Modrinth or CurseForge")
        if not (m.get("sha512") or m.get("sha1")):
            raise JoinError(f"{m.get('name')}: the mod list has no checksum for it")
    return pack


class Joiner:
    def __init__(self, invite: Invite, mc_dir: Path | None = None, http: HttpClient | None = None,
                 say: Callable[[str], None] = print, run=subprocess.run, java_probe=None):
        self.invite = invite
        self.mc = mc_dir or minecraft_dir()
        self.http = http or HttpClient(cache_ttl=0)
        if invite.fp:  # the server's own address: HTTPS, and only with the certificate the invite names
            self.http.pin(invite.netloc, invite.fp)
        self.say = say
        self.run_cmd = run
        self.java_probe = java_probe

    # ------------------------------------------------------------ steps
    def fetch_pack(self) -> dict:
        try:
            pack = self.http.get_json(f"{self.invite.url}/pack.json")
        except HttpError as e:
            if e.status == 404:
                raise JoinError("the server doesn't recognise this invite any more; ask for a new one") from e
            if e.status == 410:
                raise JoinError("this invite has expired; ask the server's owner for a new link") from e
            raise JoinError(f"couldn't reach the server at {self.invite.host}:{self.invite.port} ({e}). "
                            "Is Craft Conductor running there, and is the share port forwarded?") from e
        return validate_pack(pack, self.invite.url)

    def ask_to_join(self, name: str) -> str:
        """Ask the server's owner to let this Minecraft name in (for a server with a whitelist)."""
        if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", name):
            raise JoinError("that isn't a Minecraft name (3 to 16 letters, numbers or _)")
        try:
            result = str(self.http.post_json(f"{self.invite.url}/request", {"name": name}).get("result", "asked"))
        except HttpError as e:
            if e.status == 429:
                return "slow down"
            if e.status == 410:
                raise JoinError("this invite has expired; ask the server's owner for a new link") from e
            raise JoinError(f"couldn't reach the server to ask ({e.friendly})") from e
        return result

    def profiles(self) -> list[Path]:
        found = [self.mc / f for f in PROFILE_FILES if (self.mc / f).exists()]
        if not found:
            raise JoinError(f"couldn't find the Minecraft Launcher's files in {self.mc}. Install the Minecraft "
                            "Launcher from minecraft.net, open it and sign in once, then run this again.")
        return found

    def install_loader(self, pack: dict) -> str:
        """Put the loader's version into the launcher; returns its version id."""
        mc, loader, lv = pack["minecraft"], pack["loader"], pack.get("loader_version")
        if loader == "vanilla":
            return mc  # the launcher downloads Minecraft itself
        if loader in ("fabric", "quilt"):
            meta = FABRIC_META if loader == "fabric" else QUILT_META
            profile = self.http.get_json(f"{meta}/versions/loader/{mc}/{lv}/profile/json")
            vid = str(profile.get("id", ""))
            if not re.fullmatch(r"[A-Za-z0-9._+-]{1,100}", vid):
                raise JoinError(f"{loader} sent an unexpected version")
            _write_json(self.mc / "versions" / vid / f"{vid}.json", profile)
            return vid
        vid = f"neoforge-{lv}" if loader == "neoforge" else f"{mc}-forge-{lv}"
        if (self.mc / "versions" / vid / f"{vid}.json").exists():
            return vid
        url = (f"{NEOFORGE_MAVEN}/{lv}/neoforge-{lv}-installer.jar" if loader == "neoforge"
               else f"{FORGE_MAVEN}/{mc}-{lv}/forge-{mc}-{lv}-installer.jar")
        self.say(f"  installing {loader.capitalize()} {lv} (this takes a minute or two)")
        java = self.java(int(pack.get("java_major") or 21))
        with tempfile.TemporaryDirectory() as tmp:
            jar = Path(tmp) / "installer.jar"
            self.http.download(url, jar)
            from .desktop import NO_WINDOW
            proc = self.run_cmd([java, "-jar", str(jar), "--installClient", str(self.mc)], cwd=tmp, **NO_WINDOW,
                                capture_output=True, text=True, env=child_env())
            if proc.returncode != 0:
                tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-15:])
                raise JoinError(f"the {loader} installer failed:\n{tail}")
        if not (self.mc / "versions" / vid / f"{vid}.json").exists():
            raise JoinError(f"the {loader} installer didn't create {vid}")
        return vid

    def java(self, major: int) -> str:
        from .java import JavaManager, probe
        cfg = SimpleNamespace(state_dir=self.mc / "craft-conductor" / ".craft-conductor", java_image="jre", java_default="java",
                              java_versions={}, java_version=None, java_auto_install=True)
        return JavaManager(cfg, self.http, self.java_probe or probe).select(major)

    def write_version(self, pack: dict, base: str, slug: str) -> str:
        """Our own launcher version: the loader's, plus joining the server on start (1.20+)."""
        vid = f"craft-conductor-{slug}"
        data = {"id": vid, "inheritsFrom": base, "jar": pack["minecraft"], "type": "release",
                "time": _now(), "releaseTime": _now()}
        if pack["address"] and _supports_quick_play(pack["minecraft"]):
            data["arguments"] = {"game": ["--quickPlayMultiplayer", pack["address"]]}
        _write_json(self.mc / "versions" / vid / f"{vid}.json", data)
        return vid

    def sync_mods(self, pack: dict, game_dir: Path) -> tuple[int, int]:
        """Download what's missing or changed; remove files craft-conductor put here that are no longer wanted
        (the server dropped a mod, or the friend removed one of their extras)."""
        mods_dir = game_dir / "mods"
        mods_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = game_dir / MANIFEST
        try:
            placed = set(json.loads(manifest_path.read_text()).get("mods", []))
        except (OSError, ValueError):
            placed = set()
        wanted, fetched = set(), 0
        for m in pack.get("mods", []):
            folder = folder_of(m)
            dest = game_dir / folder / m["filename"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            wanted.add(m["filename"] if folder == "mods" else f"{folder}/{m['filename']}")
            if dest.exists() and m.get("sha1") and sha1_file(dest) == m["sha1"]:
                continue
            self.say(f"  downloading {m['name']}")
            try:
                self.http.download(m["url"], dest, sha1=m.get("sha1"), sha512=m.get("sha512"))
            except HashMismatch as e:
                raise JoinError(f"{m['name']} didn't match its checksum, so it wasn't installed") from e
            fetched += 1
        removed = 0
        gone_packs = []
        for old in placed - wanted:
            folder, _, name = old.rpartition("/")
            if folder == "resourcepacks":
                gone_packs.append(name)
            if (folder or "mods") in FOLDERS and name and "\\" not in name and (game_dir / (folder or "mods") / name).is_file():
                (game_dir / (folder or "mods") / name).unlink()
                removed += 1
        _write_json(manifest_path, {"mods": sorted(wanted), "server": pack["name"], "synced": _now()})
        from .friendextras import enable_packs
        enable_packs(game_dir, [m for m in pack.get("mods", []) if m.get("extra")], tuple(gone_packs))
        return fetched, removed

    def add_server(self, pack: dict, game_dir: Path) -> None:
        path = game_dir / "servers.dat"
        try:
            old = path.read_bytes() if path.exists() else None
            data = nbt.add_server(old, pack["name"], pack["address"])
        except nbt.NBTError:
            data = nbt.add_server(None, pack["name"], pack["address"])  # unreadable: start a fresh list
        tmp = path.with_name(".servers.dat.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def write_profiles(self, files: list[Path], pack: dict, slug: str, version: str, game_dir: Path) -> None:
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                raise JoinError(f"couldn't read {f.name} ({e}); open and close the Minecraft Launcher, then try again") from e
            profiles = data.setdefault("profiles", {})
            key = f"craft-conductor-{slug}"
            old = profiles.get(key, {})
            profiles[key] = {
                **old,
                "name": pack["name"],
                "type": "custom",
                "created": old.get("created", _now()),
                "lastUsed": _now(),  # the launcher selects the most recently used installation
                "lastVersionId": version,
                "gameDir": str(game_dir),
                "icon": pack.get("icon") or "Grass",
                "javaArgs": f"-Xmx{int(pack.get('memory_gb') or 4)}G -XX:+UseG1GC",
            }
            shutil.copyfile(f, f.with_name(f.name + ".craft-conductor-backup"))
            _write_json(f, data)

    def open_launcher(self) -> bool:
        """Best effort: start the Minecraft Launcher."""
        candidates: list[list[str]] = []
        if os.name == "nt":
            for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                         os.environ.get("LOCALAPPDATA") and os.path.join(os.environ["LOCALAPPDATA"], "Programs")):
                if base:
                    exe = Path(base) / "Minecraft Launcher" / "MinecraftLauncher.exe"
                    if exe.exists():
                        candidates.append([str(exe)])
            candidates.append(["explorer.exe", r"shell:AppsFolder\Microsoft.4297127D64EC6_8wekyb3d8bbwe!Minecraft"])
        elif sys.platform == "darwin":
            candidates.append(["open", "-a", "Minecraft"])
        else:
            if shutil.which("minecraft-launcher"):
                candidates.append(["minecraft-launcher"])
            if shutil.which("flatpak"):
                candidates.append(["flatpak", "run", "com.mojang.Minecraft"])
        for cmd in candidates:
            try:
                subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 env=child_env())
                return True
            except OSError:
                continue
        return False

    # ------------------------------------------------------------- all
    def run(self, pack: dict | None = None, open_launcher: bool = True) -> dict:
        """Set up the official Minecraft Launcher."""
        pack = pack or self.fetch_pack()
        files = self.profiles()
        slug = slugify(pack["name"])
        game_dir = self.mc / "craft-conductor" / slug
        game_dir.mkdir(parents=True, exist_ok=True)
        label = pack["loader"] if pack["loader"] == "vanilla" else f"{pack['loader']} {pack['loader_version']}"
        self.say(f"Setting up Minecraft {pack['minecraft']} ({label})")
        base = self.install_loader(pack)
        version = self.write_version(pack, base, slug)
        fetched, removed = self.sync_mods(pack, game_dir)
        if pack["address"]:
            self.add_server(pack, game_dir)
        self.write_profiles(files, pack, slug, version, game_dir)
        opened = self.open_launcher() if open_launcher else False
        return {"name": pack["name"], "mods": len(pack.get("mods", [])), "downloaded": fetched, "removed": removed,
                "manual": pack.get("manual", []), "game_dir": str(game_dir), "opened": opened,
                "quick_play": bool(pack["address"]) and _supports_quick_play(pack["minecraft"]), "address": pack["address"]}


    def run_targets(self, pack: dict, targets: list[str], open_after: bool = True,
                    prism_dir: Path | None = None, out_dir: Path | None = None) -> list[dict]:
        """Add the server to each chosen launcher. One failing doesn't stop the others."""
        from . import launchers, opener
        slug = slugify(pack["name"])
        out_dir = out_dir or opener.downloads_dir()
        results = []
        for key in [t for t in launchers.KEYS if t in targets]:
            label = launchers.LABELS[key]
            self.say(f"{label}:")
            try:
                if key == "minecraft":
                    r = self.run(pack, open_launcher=open_after and len(targets) == 1)
                    r = {**r, "launcher": key, "where": r["game_dir"],
                         "message": f"added the \"{pack['name']}\" installation to the Minecraft Launcher"}
                elif key == "prism":
                    found = prism_dir or next((d for d in launchers.prism_dirs() if d.is_dir()), None)
                    if found is None:
                        raise JoinError("Prism Launcher isn't installed (or hasn't been opened yet)")
                    r = launchers.install_prism(self, pack, slug, found)
                    if open_after and len(targets) == 1:
                        r["opened"] = launchers.open_prism(slug, pack["address"])
                elif key == "modrinth":
                    r = launchers.install_modrinth(self, pack, out_dir, open_it=open_after)
                else:
                    r = launchers.install_curseforge(self, pack, out_dir, open_it=open_after)
                r["ok"] = True
            except (JoinError, HttpError, OSError) as e:
                r = {"launcher": key, "ok": False, "message": str(e)}
            r["label"] = label
            self.say(f"  {'done: ' if r['ok'] else 'failed: '}{r['message']}")
            results.append(r)
        return results


def explain(pack: dict) -> str:
    n = len(pack.get("mods", []))
    loader = "plain Minecraft" if pack["loader"] == "vanilla" else f"{pack['loader'].capitalize()} {pack['loader_version']}"
    return "\n".join([
        f"This sets up your Minecraft to play on {pack['name']} ({pack['address']}):",
        f"  - adds \"{pack['name']}\" to your launcher: Minecraft {pack['minecraft']} with {loader}",
        f"  - downloads {n} mod{'' if n == 1 else 's'} from Modrinth/CurseForge into its own folder "
        "(your other worlds and installations aren't touched)",
        "  - puts the server in that installation's multiplayer list",
        "It never asks for your Microsoft password (the Minecraft Launcher signs you in) and sends",
        "nothing about you anywhere. Craft Conductor is open-source software that was written with the help of AI.",
    ])


def run_interactive(invite: Invite | None, confirm: bool = True, open_launcher: bool = True,
                    pack: dict | None = None, mc_dir: Path | None = None, targets: list[str] | None = None) -> int:
    """Set things up, printing progress. Either fetch the pack through ``invite``, or use
    ``pack`` (built from a server folder on this computer)."""
    joiner = Joiner(invite or Invite("localhost", 1, "local-" + "0" * 16), mc_dir=mc_dir)
    try:
        if pack is None:
            print(f"Contacting the server ({invite.host})...")
            pack = joiner.fetch_pack()
        else:
            pack = validate_pack(pack)
        print()
        print(explain(pack))
        print()
        if confirm:
            try:
                answer = input("Continue? [Y/n] ").strip().lower()
            except EOFError:
                answer = "y"
            if answer not in ("", "y", "yes"):
                print("Nothing was changed.")
                return 1
        started = time.monotonic()
        if targets and targets != ["minecraft"]:
            results = joiner.run_targets(pack, targets, open_after=open_launcher)
            print(f"\nDone in {time.monotonic() - started:.0f}s.")
            for r in results:
                print(f"  {r['label']}: {r['message']}")
            for m in pack.get("manual", []):
                print(f"  ! {m['name']} can't be downloaded automatically: get it from {m['url']}")
            return 0 if all(r["ok"] for r in results) else 1
        result = joiner.run(pack, open_launcher=open_launcher)
    except JoinError as e:
        print(f"\nCouldn't set things up: {e}")
        return 1
    except HttpError as e:
        print(f"\nA download failed: {e}\nCheck your internet connection and try again.")
        return 1
    print(f"\nDone in {time.monotonic() - started:.0f}s. {result['downloaded']} mod(s) downloaded"
          + (f", {result['removed']} old one(s) removed" if result["removed"] else "") + ".")
    for m in result["manual"]:
        print(f"  ! {m['name']} can't be downloaded automatically: get {m.get('filename') or 'it'} from\n"
              f"    {m['url']}\n    and put it in {result['game_dir']}{os.sep}mods")
    steps = ["Open the Minecraft Launcher" if not result["opened"] else "In the Minecraft Launcher",
             f"pick \"{result['name']}\" next to the Play button (it's already selected if the launcher was closed)",
             "press Play"]
    print("\n" + ", ".join(steps) + ".")
    print(f"Minecraft will join {result['address']} by itself." if result["quick_play"]
          else f"Then choose Multiplayer: {result['name']} is at the top of the list.")
    print("If the server updates, run this file again before playing to update your mods.")
    return 0
