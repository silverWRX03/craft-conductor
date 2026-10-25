"""The guided setup: asked once, skippable, started again later; steps tick themselves."""

import json
import time

from test_hub import login


def test_the_guided_setup(hub_env, monkeypatch):
    hub, c = hub_env
    login(c)
    # Offered only while there's no server yet: someone who has one doesn't need it.
    assert c.get("/api/hub")[1]["guide"] == {"asked": True, "active": False}
    from craft_conductor.daemon import Daemon
    with monkeypatch.context() as m:
        m.setattr(Daemon, "setup_pending", property(lambda self: True))
        assert c.get("/api/hub")[1]["guide"] == {"asked": False, "active": False}  # (the page offers it)
    g = c.post("/api/hub/guide", {"action": "skip"})[1]
    assert g["asked"] and not g["active"]
    assert c.get("/api/hub")[1]["guide"] == {"asked": True, "active": False}  # not asked again
    # Started later (from Help or the Servers page).
    g = c.post("/api/hub/guide", {"action": "start"})[1]
    assert g["active"] and [s["id"] for s in g["steps"]] == ["make", "start", "join", "open", "invite", "friend"]
    done = {s["id"]: s["done"] for s in g["steps"]}
    assert done["make"] and not done["join"] and g["next"] == "start" and g["server"] == "alpha"
    # A name Minecraft looked up (a ban, the whitelist) isn't someone joining (it's in usercache.json all the same).
    d = hub.get("alpha")
    (d.m.server_dir / "usercache.json").write_text(json.dumps([{"name": "Notch", "uuid": "1"}, {"name": "jeb_", "uuid": "2"}]))
    done = {s["id"]: s["done"] for s in c.get("/api/hub/guide")[1]["steps"]}
    assert not done["join"] and not done["friend"]
    # Players who joined tick "join", then "friend", and stay ticked after they leave.
    d.activity.joined("Me")
    done = {s["id"]: s["done"] for s in c.get("/api/hub/guide")[1]["steps"]}
    assert done["join"] and not done["friend"]
    d.activity.joined("Pal")
    d.activity.all_left(time.time() + 60)
    assert not d.activity.online
    assert {s["id"]: s["done"] for s in c.get("/api/hub/guide")[1]["steps"]}["friend"]
    d.activity.path.unlink()  # (visits older than 90 days are forgotten; the steps aren't)
    assert {s["id"]: s["done"] for s in c.get("/api/hub/guide")[1]["steps"]}["friend"]
    # Steps craft-conductor can't see can be ticked by hand; the others can't.
    g = c.post("/api/hub/guide", {"action": "tick", "step": "invite"})[1]
    assert {s["id"]: s["done"] for s in g["steps"]}["invite"]
    assert c.post("/api/hub/guide", {"action": "tick", "step": "friend"})[0] == 400
    assert not c.post("/api/hub/guide", {"action": "stop"})[1]["active"]
