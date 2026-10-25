"""The guided setup: a checklist for someone running a Minecraft server for the first time, from
making the server to a friend joining it. Each step ticks itself as it happens (a step craft-conductor can't
see, like sending the invite, can be ticked by hand). Offered once, the first time craft-conductor is used
(skipping is fine), and started again any time from Help or the Servers page.

Its state is kept in the hub's file under ``"guide"``: ``{"asked", "active", "ticked": [...], "started", "joined"}``.
"""

from __future__ import annotations

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


def _players(daemon) -> set[str]:
    """Everyone who has joined the server: its player activity (the join lines in its log). Not Minecraft's
    usercache.json, which also gets a name whenever one is looked up (a ban, the whitelist, an operator)."""
    activity = getattr(daemon, "activity", None)
    return activity.players() if activity is not None else set()


def state(hub) -> dict:
    saved = hub._hub_file().get("guide") or {}
    return {"asked": bool(saved.get("asked")), "active": bool(saved.get("active")),
            "ticked": [x for x in saved.get("ticked", []) if x in MANUAL],
            "started": bool(saved.get("started")), "joined": int(saved.get("joined") or 0)}


def save(hub, **changes) -> dict:
    def change(data: dict) -> dict:
        g = data["guide"] = {**state(hub), **changes}
        return g
    return hub._update_hub_file(change)


def steps(hub) -> dict:
    """The checklist as it stands, with the server the next steps are about."""
    g = state(hub)
    daemons = list(hub.daemons.values())
    installed = [d for d in daemons if d.m.lock.installed]
    running = [d for d in installed if d.state == "running"]
    if running and not g["started"]:
        g = save(hub, started=True)  # (remembered: stopping it again doesn't untick "Start it")
    joined = len(set().union(*(_players(d) for d in installed))) if installed else 0
    if joined > g["joined"]:
        g = save(hub, joined=joined)  # (remembered: old visits are forgotten after 90 days)
    joined = max(joined, g["joined"])
    upnp = hub.upnp_status() if hasattr(hub, "upnp_status") else {}
    done = {
        "make": bool(installed),
        "start": bool(running) or g["started"],
        "join": joined >= 1,
        "open": bool(upnp.get("mapped")) or any(d.m.config.tunnel_address for d in installed) or "open" in g["ticked"],
        "invite": any(d.m.config.client.enabled for d in installed) or "invite" in g["ticked"],
        "friend": joined >= 2,
    }
    focus = (running or installed or [None])[0]
    out = [{"id": sid, "title": title, "how": how, "done": done[sid], "manual": sid in MANUAL} for sid, title, how in STEPS]
    return {**g, "steps": out, "server": focus.server_id if focus else None,
            "next": next((s["id"] for s in out if not s["done"]), None)}
