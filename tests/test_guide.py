"""The guided setup: asked once, skippable, started again later; steps tick themselves."""

import json

from test_hub import login


def test_the_guided_setup(hub_env):
    hub, c = hub_env
    login(c)
    assert c.get("/api/hub")[1]["guide"] == {"asked": False, "active": False}  # (the page offers it)
    g = c.post("/api/hub/guide", {"action": "skip"})[1]
    assert g["asked"] and not g["active"]
    assert c.get("/api/hub")[1]["guide"] == {"asked": True, "active": False}  # not asked again
    # Started later (from Help or the Servers page).
    g = c.post("/api/hub/guide", {"action": "start"})[1]
    assert g["active"] and [s["id"] for s in g["steps"]] == ["make", "start", "join", "open", "invite", "friend"]
    done = {s["id"]: s["done"] for s in g["steps"]}
    assert done["make"] and not done["join"] and g["next"] == "start" and g["server"] == "alpha"
    # Players who joined tick "join", then "friend".
    sd = hub.get("alpha").m.server_dir
    (sd / "usercache.json").write_text(json.dumps([{"name": "Me", "uuid": "1"}]))
    done = {s["id"]: s["done"] for s in c.get("/api/hub/guide")[1]["steps"]}
    assert done["join"] and not done["friend"]
    (sd / "usercache.json").write_text(json.dumps([{"name": "Me", "uuid": "1"}, {"name": "Pal", "uuid": "2"}]))
    assert {s["id"]: s["done"] for s in c.get("/api/hub/guide")[1]["steps"]}["friend"]
    # Steps mcsm can't see can be ticked by hand; the others can't.
    g = c.post("/api/hub/guide", {"action": "tick", "step": "invite"})[1]
    assert {s["id"]: s["done"] for s in g["steps"]}["invite"]
    assert c.post("/api/hub/guide", {"action": "tick", "step": "friend"})[0] == 400
    assert not c.post("/api/hub/guide", {"action": "stop"})[1]["active"]
