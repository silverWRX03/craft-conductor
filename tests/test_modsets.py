"""Saved mod lists: save, switch (the current list saved first), download and load back."""

import json

from craft_conductor import config as configmod
from craft_conductor.config import ModSpec

from test_hub import login


def test_save_switch_and_back(hub_env):
    hub, c = hub_env
    login(c)
    d = hub.get("alpha")
    before = [(m.source, m.id) for m in d.m.config.mods]
    assert c.post("/api/servers/alpha/modsets/save", {"name": "Plain"})[0] == 200
    configmod.append_mod(d.m.config.path, ModSpec("modrinth", "lithium"))
    d.m.reload_config()
    assert c.post("/api/servers/alpha/modsets/save", {"name": "Fast"})[0] == 200
    names = [x["name"] for x in c.get("/api/servers/alpha/modsets")[1]["sets"]]
    assert names == ["Fast", "Plain"]

    r = c.post("/api/servers/alpha/modsets/restore", {"name": "Plain"})
    assert r[0] == 200 and "Plain" in r[1]["message"]
    assert [(m.source, m.id) for m in d.m.config.mods] == before  # the file says so, comments and all
    sets = {x["name"]: x for x in c.get("/api/servers/alpha/modsets")[1]["sets"]}
    assert "lithium" in sets["Before Plain"]["mods"]  # what it had, kept to go back to

    status, body, headers = c.call("GET", "/api/servers/alpha/modsets/export?name=Fast")
    assert status == 200 and "attachment" in headers["Content-Disposition"]
    exported = body if isinstance(body, dict) else json.loads(body)
    exported["name"] = "Fast (copy)"
    assert c.post("/api/servers/alpha/modsets/import", {"set": exported})[0] == 200
    bad = {**exported, "mods": [{"source": "modrinth", "id": "bad id; rm -rf"}]}
    assert c.post("/api/servers/alpha/modsets/import", {"set": bad})[0] == 400
    assert c.post("/api/servers/alpha/modsets/restore", {"name": "nope"})[0] == 400
    assert c.post("/api/servers/alpha/modsets/delete", {"name": "Fast (copy)"})[0] == 200
