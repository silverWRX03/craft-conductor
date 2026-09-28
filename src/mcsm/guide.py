"""The guided setup: a checklist for someone running a Minecraft server for the first time, from
making the server to a friend joining it. Each step ticks itself as it happens (a step mcsm can't
see, like sending the invite, can be ticked by hand). Offered once, the first time mcsm is used
(skipping is fine), and started again any time from Help or the Servers page.

Its state is kept in the hub's file under ``"guide"``: ``{"asked", "active", "ticked": [...]}``.
"""

from __future__ import annotations

import json
from pathlib import Path

STEPS = [  # id, title, what to do
    ("make", "Make your server",
     "Press New server and pick one of the ready-made setups (Quick start), or choose everything yourself."),
    ("start", "Start it",
     "On the server's Dashboard, press Start. The first start takes a minute or two while Minecraft makes the world."),
    ("join", "Join it yourself",
     "Open Minecraft on this computer, choose Multiplayer → Add Server, and type localhost as the address."),
    ("open", "Let friends reach it",
     "Friends outside your home need a way in: Craft Conductor settings → Sharing with friends → Router (automatic port "
     "forwarding), a playit.gg tunnel, or the router guide in Help. Check my setup → Test from the internet tells you "
     "if it works."),
    ("invite", "Invite a friend",
     "On the server's Friends page, make the invite and send them the link: it sets up their game with the right "
     "mods and adds your server."),
    ("friend", "A friend joined",
     "When a friend joins, this ticks itself. That's it: you're running a Minecraft server!"),
]
MANUAL = {"open", "invite"}  # steps that can be ticked by hand


def _players(server_dir: Path) -> set[str]:
    """Everyone who has ever joined the server (Minecraft's usercache.json)."""
    try:
        data = json.loads((server_dir / "usercache.json").read_text())
        return {str(x.get("name")) for x in data if isinstance(x, dict) and x.get("name")}
    except (OSError, ValueError, TypeError):
        return set()


def state(hub) -> dict:
    saved = hub._hub_file().get("guide") or {}
    return {"asked": bool(saved.get("asked")), "active": bool(saved.get("active")),
            "ticked": [x for x in saved.get("ticked", []) if x in MANUAL],
            "started": bool(saved.get("started"))}


def save(hub, **changes) -> dict:
    data = hub._hub_file()
    g = {**state(hub), **changes}
    data["guide"] = g
    hub._save_hub_file(data)
    return g


def steps(hub) -> dict:
    """The checklist as it stands, with the server the next steps are about."""
    g = state(hub)
    daemons = list(hub.daemons.values())
    installed = [d for d in daemons if d.m.lock.installed]
    running = [d for d in installed if d.state == "running"]
    if running and not g["started"]:
        g = save(hub, started=True)  # (remembered: stopping it again doesn't untick "Start it")
    players = set().union(*(_players(d.m.server_dir) for d in installed)) if installed else set()
    upnp = hub.upnp_status() if hasattr(hub, "upnp_status") else {}
    done = {
        "make": bool(installed),
        "start": bool(running) or g["started"],
        "join": len(players) >= 1,
        "open": bool(upnp.get("mapped")) or any(d.m.config.tunnel_address for d in installed) or "open" in g["ticked"],
        "invite": any(d.m.config.client.enabled for d in installed) or "invite" in g["ticked"],
        "friend": len(players) >= 2,
    }
    focus = (running or installed or [None])[0]
    out = [{"id": sid, "title": title, "how": how, "done": done[sid], "manual": sid in MANUAL} for sid, title, how in STEPS]
    return {**g, "steps": out, "server": focus.server_id if focus else None,
            "next": next((s["id"] for s in out if not s["done"]), None)}
