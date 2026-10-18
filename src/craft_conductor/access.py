"""Who may do what in the control panel: the owner, and the people the owner invited.

The **owner** signs in with the panel's password, PIN or passkeys (webauth.py) and may do
everything. An **invited person** (users.py) has their own sign-in and, for each server they
were given, a set of permissions (CAPS). Phones paired to a person can do what that person can.

Every API route is in one of the tables below. ``SERVER_ROUTES`` covers each server's routes
(``/api/servers/<id>/...``): the permission it needs on *that* server. ``HUB_ROUTES`` lists the
few routes outside one server that an invited person may use; every other one is the owner's
(user and grant administration, Craft Conductor's own updates, remote access, the router and
firewall, new servers...). A route in neither table is the owner's too: nothing new is opened
by forgetting it here (tests/test_access.py checks every route is listed).

Some routes need more than the route says: what a players action, a settings change or a
"What went wrong" fix does decides the permission (``body_needs``). Those are looked at after
the route itself has been allowed, so nothing expensive happens for someone with no access.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

OWNER = "owner"       # only the owner (in HUB_ROUTES / SERVER_ROUTES / body_needs)
SIGNED_IN = "signed-in"   # anyone signed in (HUB_ROUTES only); the answer is cut down to what they may see

# ------------------------------------------------------------------ permissions
# id -> (group, what it allows, the risk to show when it's ticked: None for everyday ones)
CAPS: dict[str, tuple[str, str, str | None]] = {
    "status.view": ("Status", "See the server's status, who's online, its activity and performance", None),
    "players.moderate": ("Players", "Manage players: kick, ban and unban, the whitelist and join requests; "
                                    "message everyone", None),
    "players.op": ("Players", "Make players operators (OP), and change what operators and command blocks can do",
                   "Operators can run almost any command in the game, including commands mods add that can "
                   "reach files on this computer."),
    "server.power": ("Power", "Start, stop and restart the server (and schedule restarts)", None),
    "backups.make": ("Backups", "See, make and check backups", None),
    "backups.restore": ("Backups", "Restore backups and replace the world",
                        "Overwrites the world: what's there now is lost unless it was backed up."),
    "backups.delete": ("Backups", "Change how many backups are kept",
                       "Keeping fewer deletes the oldest backups."),
    "server.export": ("Backups", "Export the server and download the export",
                      "An export is the whole server: its worlds, settings and players' data."),
    "updates.check": ("Updates", "Check for updates", None),
    "updates.apply": ("Updates", "Apply updates (Minecraft and mods), test them first and change how updates happen",
                      "Updates install new programs (mods) that run on this computer."),
    "logs.view": ("Console", "Read the console (IP addresses and this computer's folders are hidden)", None),
    "console.execute": ("Console", "Type console commands",
                        "A console command can do anything an operator can, and some mods add commands that "
                        "reach files on this computer."),
    "settings.safe": ("Settings", "Change everyday settings: game rules, the world border, server.properties, "
                                  "when updates and backups happen", None),
    "mods.view": ("Mods", "See the mods and plugins, and check them", None),
    "mods.manage": ("Mods", "Add, remove and upload mods and plugins; change what friends download",
                    "Mods and plugins are programs: they run on this computer with Craft Conductor's access, "
                    "and friends' games run the ones they download."),
    "friends.share": ("Mods", "See and share the friends' invite link",
                      "Anyone with the link can download the server's mods and find its address."),
    "runtime.configure": ("Launch", "Change Java, memory and launch settings, and the Minecraft version",
                          "Launch settings decide which programs run on this computer."),
    "files.read": ("Files", "Open the configuration files",
                   "Configuration files can hold passwords and keys."),
    "files.write": ("Files", "Edit the configuration files",
                    "Some configuration files decide what mods run or load."),
    "server.delete": ("Danger", "Delete the server",
                      "Removes the server from Craft Conductor, and its folder too if asked: worlds included."),
}
GROUPS = list(dict.fromkeys(g for g, _, _ in CAPS.values()))
RISKY = frozenset(c for c, (_, _, risk) in CAPS.items() if risk)

_VIEWER = {"status.view"}
_MODERATOR = _VIEWER | {"players.moderate"}
_OPERATOR = _VIEWER | {"server.power", "backups.make", "updates.check"}
PRESETS: dict[str, frozenset[str]] = {
    "viewer": frozenset(_VIEWER),
    "moderator": frozenset(_MODERATOR),
    "operator": frozenset(_OPERATOR),
    "manager": frozenset(_MODERATOR | _OPERATOR | {"logs.view", "settings.safe", "mods.view"}),
}
PRESET_NAMES = {"viewer": "Viewer", "moderator": "Moderator", "operator": "Operator", "manager": "Manager"}
PRESET_SUMMARIES = {
    "viewer": "Sees the server's status and who's online.",
    "moderator": "Viewer, and manages players: kick, ban, the whitelist, join requests.",
    "operator": "Viewer, and starts, stops and restarts the server, makes backups and checks for updates.",
    "manager": "Moderator and Operator, and reads the console (with addresses hidden), sees the mods and "
               "changes everyday settings.",
}
DEFAULT_PRESET = "viewer"
assert not any(PRESETS[p] & RISKY for p in PRESETS), "a preset never includes a risky permission"


# Some permissions are no use without another: typing commands without seeing the console, and so
# on. Every grant includes seeing the server's status.
IMPLIES = {"console.execute": "logs.view", "files.write": "files.read", "mods.manage": "mods.view",
           "updates.apply": "updates.check", "backups.restore": "backups.make"}


def normalize(caps: frozenset[str] | set[str]) -> frozenset[str]:
    """Permissions as kept: with what they need (IMPLIES, status.view); none stays none."""
    out = set(caps)
    if out:
        out.add("status.view")
        out |= {IMPLIES[c] for c in caps if c in IMPLIES}
    return frozenset(out)


def preset_of(caps: frozenset[str] | set[str]) -> str | None:
    """The preset these permissions are exactly, if any (else they're "Custom")."""
    return next((p for p, c in PRESETS.items() if c == frozenset(caps)), None)


def valid_caps(caps: object) -> frozenset[str]:
    if not isinstance(caps, (list, tuple, set, frozenset)) or not all(isinstance(c, str) for c in caps):
        raise ValueError("permissions must be a list")
    unknown = [c for c in caps if c not in CAPS]
    if unknown:
        raise ValueError(f"unknown permission {unknown[0]!r}")
    return frozenset(caps)


def catalog() -> dict:
    """For the invite and edit forms."""
    return {"groups": [{"name": g, "caps": [{"id": c, "label": label, "risk": risk}
                                            for c, (group, label, risk) in CAPS.items() if group == g]}
                       for g in GROUPS],
            "presets": [{"id": p, "name": PRESET_NAMES[p], "summary": PRESET_SUMMARIES[p], "caps": sorted(PRESETS[p])}
                        for p in PRESETS],
            "default": DEFAULT_PRESET, "implies": IMPLIES}


# ------------------------------------------------------------------ who's asking
@dataclass(frozen=True)
class Subject:
    """Who sent a request, worked out from the current users file on every request (so a change
    or removal counts at once). ``grants``: server id -> permissions on it."""
    kind: str                     # "owner" or "user"
    user_id: str = ""
    name: str = ""
    device: str = ""              # a paired phone's id, when the request came from one
    device_name: str = ""
    grants: Mapping[str, frozenset[str]] = field(default_factory=dict)

    @property
    def is_owner(self) -> bool:
        return self.kind == "owner"

    @property
    def key(self) -> str:
        """Names this person in other files (notifications, passkeys)."""
        return "owner" if self.is_owner else f"user:{self.user_id}"

    def caps(self, sid: str) -> frozenset[str]:
        return frozenset(CAPS) if self.is_owner else self.grants.get(sid, frozenset())

    def can(self, sid: str, need: str | tuple[str, ...]) -> bool:
        if self.is_owner:
            return True
        if need == OWNER:
            return False
        have = self.grants.get(sid, frozenset())
        return any(n in have for n in need) if isinstance(need, tuple) else need in have

    def sees(self, sid: str) -> bool:
        return self.is_owner or bool(self.grants.get(sid))


OWNER_SUBJECT = Subject("owner", name="owner")


# ------------------------------------------------------------------ the routes
# Each server's routes -> the permission needed on that server. A tuple: any one of them will do
# (the answer, or body_needs, then narrows it down).
_SETTINGS_ANY = ("settings.safe", "runtime.configure", "updates.apply", "backups.delete")
SERVER_ROUTES: dict[tuple[str, str], str | tuple[str, ...]] = {
    # status
    ("GET", "/api/status"): "status.view",
    ("GET", "/api/events"): "status.view",
    ("GET", "/api/players/online"): "status.view",
    ("GET", "/api/players/skin"): "status.view",
    ("GET", "/api/performance"): "status.view",
    ("GET", "/api/performance/lag"): "status.view",
    # power
    ("POST", "/api/server/start"): "server.power",
    ("POST", "/api/server/stop"): "server.power",
    ("POST", "/api/server/restart"): "server.power",
    # players
    ("GET", "/api/players"): "players.moderate",
    ("GET", "/api/players/activity"): "players.moderate",
    ("GET", "/api/join-requests"): "players.moderate",
    ("POST", "/api/join-requests/answer"): "players.moderate",
    ("POST", "/api/players/action"): ("players.moderate", "players.op"),   # body_needs: which action
    ("POST", "/api/broadcast"): "players.moderate",
    # console
    ("GET", "/api/console"): "logs.view",
    ("POST", "/api/command"): "console.execute",
    # backups
    ("GET", "/api/backups"): "backups.make",
    ("GET", "/api/backups/changes"): "backups.make",
    ("POST", "/api/backups/create"): "backups.make",
    ("POST", "/api/backups/check"): "backups.make",
    ("POST", "/api/backups/restore"): "backups.restore",
    ("POST", "/api/backups/area"): "backups.restore",
    ("POST", "/api/world/replace"): "backups.restore",
    ("GET", "/api/export"): "server.export",
    ("GET", "/api/export/download"): "server.export",
    ("POST", "/api/export"): "server.export",
    ("POST", "/api/export/delete"): "server.export",
    # updates
    ("GET", "/api/updates"): "updates.check",
    ("GET", "/api/updates/readiness"): "updates.check",
    ("GET", "/api/beta"): "updates.check",
    ("POST", "/api/updates/check"): "updates.check",
    ("POST", "/api/updates/apply"): "updates.apply",
    ("GET", "/api/modpack"): "updates.check",
    ("POST", "/api/modpack/check"): "updates.check",
    ("POST", "/api/modpack/update"): "updates.apply",
    ("POST", "/api/updates/remove-and-upgrade"): "updates.apply",
    ("GET", "/api/updates/rehearsal"): "updates.apply",
    ("POST", "/api/updates/rehearsal"): "updates.apply",
    ("POST", "/api/updates/rehearsal/stop"): "updates.apply",
    ("POST", "/api/beta/test"): "updates.apply",
    # settings and the world
    ("GET", "/api/settings"): _SETTINGS_ANY,
    ("POST", "/api/settings"): _SETTINGS_ANY + ("server.power", "backups.make", "players.op"),   # body_needs
    ("GET", "/api/world/tools"): "settings.safe",
    ("POST", "/api/world/rule"): "settings.safe",
    ("POST", "/api/world/border"): "settings.safe",
    ("POST", "/api/world/chunky"): "settings.safe",
    ("POST", "/api/performance/lag"): "settings.safe",
    ("POST", "/api/performance/lag/stop"): "settings.safe",
    ("POST", "/api/problem/fix"): ("server.power", "runtime.configure", "mods.manage"),   # body_needs
    # mods
    ("GET", "/api/mods"): "mods.view",
    ("GET", "/api/mods/search"): "mods.view",
    ("GET", "/api/mods/versions"): "mods.view",
    ("GET", "/api/mods/requires"): "mods.view",
    ("GET", "/api/browse/search"): "mods.view",
    ("GET", "/api/browse/project"): "mods.view",
    ("GET", "/api/browse/categories"): "mods.view",
    ("GET", "/api/browse/added"): "mods.view",
    ("GET", "/api/modsets"): "mods.view",
    ("GET", "/api/modsets/export"): "mods.view",
    ("GET", "/api/bedrock"): "mods.view",
    ("GET", "/api/bedrock/check"): "mods.view",
    ("GET", "/api/webmap"): "mods.view",
    ("POST", "/api/mods/check"): "mods.view",
    ("POST", "/api/mods/filecheck"): "mods.view",
    ("POST", "/api/client/check"): "mods.view",
    ("POST", "/api/mods/add"): "mods.manage",
    ("POST", "/api/mods/add-many"): "mods.manage",
    ("POST", "/api/mods/remove"): "mods.manage",
    ("POST", "/api/mods/jar"): "mods.manage",
    ("POST", "/api/mods/required"): "mods.manage",
    ("POST", "/api/mods/pin"): "mods.manage",
    ("POST", "/api/mods/players"): "mods.manage",
    ("POST", "/api/mods/local"): "mods.manage",
    ("POST", "/api/manual/upload"): "mods.manage",
    ("POST", "/api/manual/stop"): "mods.manage",
    ("POST", "/api/manual/look"): OWNER,    # reads this computer's Downloads and folders (the drop box is mods.manage)
    ("POST", "/api/modsets/save"): "mods.manage",
    ("POST", "/api/modsets/restore"): "mods.manage",
    ("POST", "/api/modsets/delete"): "mods.manage",
    ("POST", "/api/modsets/import"): "mods.manage",
    ("POST", "/api/webmap/add"): "mods.manage",
    ("POST", "/api/webmap/accept"): "mods.manage",
    # what friends download, and the friends' invite link
    ("GET", "/api/client"): "friends.share",
    ("GET", "/api/client/search"): "mods.manage",
    ("POST", "/api/client"): "mods.manage",
    ("POST", "/api/client/local"): "mods.manage",
    ("POST", "/api/client/local/remove"): "mods.manage",
    ("POST", "/api/client/new-link"): "friends.share",
    ("POST", "/api/client/stop-link"): "friends.share",
    ("POST", "/api/client/discord"): "friends.share",
    # Java, launch and the Minecraft version
    ("GET", "/api/setup"): "runtime.configure",
    ("POST", "/api/setup"): "runtime.configure",
    ("GET", "/api/java"): "runtime.configure",
    ("POST", "/api/java/install"): "runtime.configure",
    ("POST", "/api/java/use"): "runtime.configure",
    ("POST", "/api/java/scan"): "runtime.configure",
    ("POST", "/api/java/update"): "runtime.configure",
    ("POST", "/api/java/remove"): "runtime.configure",
    ("POST", "/api/performance/spark"): "runtime.configure",
    # configuration files
    ("GET", "/api/configs"): "files.read",
    ("GET", "/api/configs/file"): "files.read",
    ("POST", "/api/configs/file"): "files.write",
    # the owner's: this computer's screen and folders, its network, the setup check (firewall, router)
    ("POST", "/api/open"): OWNER,
    ("GET", "/api/play-here"): OWNER,
    ("POST", "/api/play-here"): OWNER,
    ("GET", "/api/tunnel"): OWNER,
    ("GET", "/api/reach"): OWNER,   # how friends outside join, the ports opened, the whitelist rule (reach.py)
    ("POST", "/api/reach"): OWNER,
    ("GET", "/api/doctor"): OWNER,
    ("POST", "/api/doctor/internet"): OWNER,
    ("POST", "/api/doctor/fix"): OWNER,
    ("GET", "/api/doctor/report"): OWNER,
    ("POST", "/api/webmap/port"): OWNER,
}

# Routes outside one server an invited person may use. Everything else there is the owner's.
HUB_ROUTES: dict[tuple[str, str], str] = {
    ("GET", "/api/hub"): SIGNED_IN,                    # cut down to their servers (hub_answer)
    ("GET", "/api/notice"): SIGNED_IN,
    ("GET", "/api/licenses"): SIGNED_IN,
    ("GET", "/api/hub/phone"): SIGNED_IN,              # cut down to their own notifications
    ("POST", "/api/hub/phone/subscribe"): SIGNED_IN,   # notifications for their servers only (push.py)
    ("POST", "/api/hub/phone/unsubscribe"): SIGNED_IN,  # (these three: only their own devices)
    ("POST", "/api/hub/phone/test"): SIGNED_IN,
    ("POST", "/api/hub/phone/prefs"): SIGNED_IN,
    ("POST", "/api/hub/delete"): "server.delete",      # on the server named in the request
    ("GET", "/api/hub/mods/check"): SIGNED_IN,         # a mod check's progress: only the checks they started
    ("GET", "/api/account"): SIGNED_IN,                # their own sign-in
    ("POST", "/api/account/password"): SIGNED_IN,
    ("POST", "/api/account/passkeys/options"): SIGNED_IN,
    ("POST", "/api/account/passkeys/add"): SIGNED_IN,
    ("POST", "/api/account/passkeys/remove"): SIGNED_IN,
}
# Of those, the ones that name a server in the request body ("id").
HUB_SERVER_IN_BODY = {("POST", "/api/hub/delete")}
# Server routes that start a mod check in the background (followed with GET /api/hub/mods/check).
STARTS_A_CHECK = {("POST", "/api/mods/check"), ("POST", "/api/mods/filecheck"), ("POST", "/api/client/check")}
# Server routes whose request decides what they need (body_needs).
BODY_CHECKED = {("POST", "/api/players/action"), ("POST", "/api/problem/fix"), ("POST", "/api/settings")}


def allows(caps: frozenset[str] | set[str], method: str, path: str, body: dict | None = None) -> bool:
    """Whether someone with these permissions (on the server concerned) may use a route at all,
    and, given ``body``, this request (settings: compared with nothing, so every key counts)."""
    if (method, path) in SERVER_ROUTES:
        need = SERVER_ROUTES[(method, path)]
    else:
        need = HUB_ROUTES.get((method, path), OWNER)
        if need == SIGNED_IN:
            return True
    subject = Subject("user", grants={"s": frozenset(caps)})
    if not subject.can("s", need):
        return False
    return body is None or all(subject.can("s", n) for n in body_needs(path, body))


def server_route_need(method: str, path: str) -> str | tuple[str, ...]:
    """The permission a server's route needs; a route not listed is the owner's."""
    return SERVER_ROUTES.get((method, path), OWNER)


def hub_route_need(method: str, path: str) -> str:
    return HUB_ROUTES.get((method, path), OWNER)


# ------------------------------------------------------------------ what's in the request
OP_ACTIONS = {"op", "deop"}
MODERATE_ACTIONS = {"kick", "ban", "pardon", "ban-ip", "pardon-ip", "whitelist-add", "whitelist-remove",
                    "whitelist-on", "whitelist-off"}

# Each setting (web.Api.SETTINGS) -> what changing it needs (all of them).
SETTING_NEEDS: dict[str, tuple[str, ...]] = {
    "memory": ("runtime.configure",), "aikar_flags": ("runtime.configure",), "find_lag": ("runtime.configure",),
    "cpu_cores": ("runtime.configure",), "priority": ("runtime.configure",),
    "restart_on_crash": ("server.power",),
    "strategy": ("updates.apply",), "mod_channel": ("updates.apply",), "auto_upgrade": ("updates.apply",),
    "check_interval": ("settings.safe",), "warn_minutes": ("settings.safe",), "wait_for_empty": ("settings.safe",),
    "rehearse": ("settings.safe",), "verify_boot": ("settings.safe",),
    "backups_keep": ("backups.delete",),
    "schedule_restart": ("settings.safe", "server.power"), "restart_when_empty": ("settings.safe", "server.power"),
    "schedule_backup": ("settings.safe", "backups.make"),
    # (the owner's: a web address notifications go to, folders on this computer, what backups keep
    # of passwords and keys, the address friends are given, the port the router and firewall open)
    "discord_webhook": (OWNER,), "backup_copy_to": (OWNER,), "backup_copy_keep": (OWNER,),
    "backup_include": (OWNER,), "tunnel_address": (OWNER,), "port": (OWNER,),
    "whitelist_off_ok": (),  # (that the warning was seen: the whitelist itself is a server.properties setting)
}
# server.properties settings that need more than settings.safe.
PROPERTY_NEEDS: dict[str, tuple[str, ...]] = {
    "online-mode": (OWNER,), "enforce-secure-profile": (OWNER,),   # who can join as whom
    "op-permission-level": ("settings.safe", "players.op"), "enable-command-block": ("settings.safe", "players.op"),
    "level-name": ("settings.safe", "backups.restore"),               # a different world
}
PROBLEM_NEEDS: dict[str, str] = {
    "dismiss": "server.power", "memory-up": "runtime.configure", "java-auto": "runtime.configure",
    "add-mod": "mods.manage", "remove-mod": "mods.manage", "disable-jar": "mods.manage", "players-only": "mods.manage",
}


def body_needs(path: str, body: dict, current: Mapping | None = None) -> list[str]:
    """What else this request needs, from what it asks for. ``current``: for settings, what they
    are now (a setting sent unchanged needs nothing: the Settings page sends the whole form)."""
    if path == "/api/players/action":
        action = str(body.get("action", ""))
        return ["players.op"] if action in OP_ACTIONS else ["players.moderate"] if action in MODERATE_ACTIONS else [OWNER]
    if path == "/api/problem/fix":
        return [PROBLEM_NEEDS.get(str(body.get("kind", "")), OWNER)]
    if path == "/api/settings":
        current = current or {}
        out: list[str] = []
        for key, value in body.items():
            if key == "properties":
                now = current.get("properties") or {}
                for prop, v in (value or {}).items() if isinstance(value, dict) else ():
                    if _same(v, now.get(prop)):
                        continue
                    out += PROPERTY_NEEDS.get(prop, ("settings.safe",))
            elif not _same(value, current.get(key)):
                out += SETTING_NEEDS.get(key, (OWNER,))
        return out
    return []


def _same(a, b) -> bool:
    norm = lambda v: str(v).lower() if isinstance(v, bool) else str(v).strip() if v is not None else ""  # noqa: E731
    if isinstance(a, list) or isinstance(b, list):
        return [norm(x) for x in a or []] == [norm(x) for x in b or []]
    return norm(a) == norm(b)


# ------------------------------------------------------------------ what's in the answer
_IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?![\w.])")
_IPV6 = re.compile(r"(?<![\w:.])\[?[0-9a-fA-F]{0,4}(?::[0-9a-fA-F]{0,4}){2,7}\]?(?::\d{1,5})?(?![\w:])")
_CLOCK = re.compile(r"\d{1,2}:\d{2}(?::\d{2})?")


def _v6(m: re.Match) -> str:
    """An IPv6 address (with or without [] and a port), but not a time of day like [12:00:00]."""
    text = m.group(0)
    core = re.sub(r"^\[|\](?::\d+)?$", "", text)
    if _CLOCK.fullmatch(core) or not (core.count(":") >= 3 or "::" in core):
        return text
    return "[address hidden]"


def redact(text: str, home: str | None = None) -> str:
    """A console line for someone other than the owner: no IP addresses, no folders of this computer."""
    home = home if home is not None else str(Path.home())
    if home and len(home) > 3:
        text = re.sub(re.escape(home), "~", text, flags=re.I)
    text = _IPV4.sub("[address hidden]", text)
    return _IPV6.sub(_v6, text)


STATUS_OWNER_ONLY = ("server_dir", "self_update", "update_channel")
SETTINGS_OWNER_ONLY = tuple(k for k, need in SETTING_NEEDS.items() if OWNER in need)


def server_answer(subject: Subject, sid: str, path: str, result):
    """Cut a server route's answer down for an invited person."""
    if subject.is_owner or not isinstance(result, dict):
        return result
    if path == "/api/status":
        return {k: v for k, v in result.items() if k not in STATUS_OWNER_ONLY}
    if path == "/api/console":
        return {**result, "lines": [{**x, "text": redact(str(x.get("text", "")))} for x in result.get("lines", [])]}
    if path == "/api/events":
        return {**result, "events": [{**e, **({"text": redact(str(e["text"]))} if "text" in e else {}),
                                      **({"message": redact(str(e["message"]))} if "message" in e else {})}
                                     for e in result.get("events", []) if isinstance(e, dict)]}
    if path == "/api/settings":
        return {k: v for k, v in result.items() if k not in SETTINGS_OWNER_ONLY}
    return result


HUB_KEEP = ("version", "single", "notice_accepted")
SERVER_KEEP = ("id", "name", "state", "setup_pending", "job", "minecraft", "loader", "players", "max_players", "port",
               "update", "problem")


def hub_answer(subject: Subject, result: dict) -> dict:
    """The server list for an invited person: only their servers, and nothing about this computer."""
    if subject.is_owner:
        return result
    return {**{k: result.get(k) for k in HUB_KEEP},
            "servers": [{k: s.get(k) for k in SERVER_KEEP} for s in result.get("servers", []) if subject.sees(s.get("id"))],
            "share": None, "guide": None, "health": [], "self_update": None, "home": None, "auth": None}


def access_info(subject: Subject, server_ids) -> dict:
    """What the page needs to know to show only what this person can use (the server checks anyway)."""
    if subject.is_owner:
        return {"role": "owner"}
    return {"role": "user", "user": {"id": subject.user_id, "name": subject.name},
            "access": {sid: sorted(subject.caps(sid)) for sid in server_ids if subject.sees(sid)}}
