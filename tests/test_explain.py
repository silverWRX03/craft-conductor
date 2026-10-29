"""What went wrong: plain words and fix buttons when a server crashes or won't start."""

from types import SimpleNamespace

from craft_conductor import explain

from test_hub import login
from test_web import wait_for


def test_common_causes_in_plain_words():
    e = explain.explain(["java.lang.OutOfMemoryError: Java heap space"])
    assert e["cause"] == "memory" and e["actions"][0]["kind"] == "memory-up"
    assert explain.explain(["**** FAILED TO BIND TO PORT!"])["actions"][0]["kind"] == "port"
    assert explain.explain(["java.lang.UnsupportedClassVersionError: net/minecraft/Main has been compiled by a more recent "
                            "version of the Java Runtime"])["cause"] == "java"
    assert explain.explain(["[Server thread/WARN]: Failed to load level.dat"])["actions"][0]["kind"] == "backups"
    assert explain.explain(["You need to agree to the EULA in order to run the server."])["cause"] == "eula"
    assert explain.explain(["[Server thread/INFO]: Done (1.0s)!"]) is None


def test_a_missing_mod_is_offered():
    fabric = ["Incompatible mods found!", " - Mod 'Create' (create) 0.5.1 requires any version of mod 'Architectury' (architectury), which is missing!"]
    e = explain.explain(fabric)
    assert e["cause"] == "missing" and e["actions"] == [{"kind": "add-mod", "id": "architectury", "name": "Architectury", "label": "Add Architectury"}]
    neo = ["\tMod ID: 'flywheel', Requested by: 'create', Expected range: '[1.0,)', Actual version: '[MISSING]'"]
    assert explain.explain(neo)["actions"][0]["id"] == "flywheel"


def test_the_mod_to_blame_gets_a_button():
    mods = [SimpleNamespace(name="Lithium", filename="lithium.jar")]
    lines = ["java.lang.NoSuchMethodError: foo", "\tat me.jellysquid.Lithium.x(Lithium.java:3) [lithium.jar:?]"]
    e = explain.explain(lines, None, mods)
    assert e["cause"] == "mod" and e["actions"] == [{"kind": "remove-mod", "filename": "lithium.jar", "name": "Lithium", "label": "Remove Lithium"}]


def test_the_dashboard_explains_a_failed_start_and_fixes_it(hub_env):
    hub, c = hub_env
    login(c)
    d = hub.get("alpha")
    mods = d.m.server_dir / "mods"
    mods.mkdir(exist_ok=True)
    (mods / "crash-1.0.jar").write_bytes(b"PK")  # a jar added by hand that stops the server
    c.post("/api/servers/alpha/server/start", {})
    wait_for(lambda: c.get("/api/servers/alpha/status")[1].get("problem"), timeout=30)
    p = c.get("/api/servers/alpha/status")[1]["problem"]
    assert p["kind"] == "start" and p["cause"] == "mod", p
    assert p["actions"] == [{"kind": "disable-jar", "filename": "crash-1.0.jar", "name": "crash-1.0", "label": "Switch crash-1.0 off"}]
    assert c.post("/api/servers/alpha/problem/fix", {"kind": "memory-up"})[0] == 409  # not offered
    status, r, _ = c.post("/api/servers/alpha/problem/fix", {"kind": "disable-jar", "filename": "crash-1.0.jar"})
    assert status == 200 and "switched off" in r["message"]
    assert (mods / "crash-1.0.jar.disabled").exists() and not (mods / "crash-1.0.jar").exists()
    assert c.get("/api/servers/alpha/status")[1]["problem"]["fixed"]
    # it starts now, and a failed start's explanation goes away by itself
    (mods / "crash-1.0.jar.disabled").unlink()  # (the fake server fails on any file named crash*)
    wait_for(lambda: c.get("/api/servers/alpha/status")[1]["job"] is None, timeout=30)
    c.post("/api/servers/alpha/server/start", {})
    wait_for(lambda: c.get("/api/servers/alpha/status")[1]["state"] == "running", timeout=30)
    assert c.get("/api/servers/alpha/status")[1]["problem"] is None
    d.problem = {"kind": "crash", "time": 0, "actions": []}
    assert c.post("/api/servers/alpha/problem/fix", {"kind": "dismiss"})[0] == 200
    assert c.get("/api/servers/alpha/status")[1]["problem"] is None
    # Dismissing is for whoever can restart the server; the fixes need what they change.
    from craft_conductor import access
    operator = access.PRESETS["operator"]
    assert access.allows(operator, "POST", "/api/problem/fix", {"kind": "dismiss"})
    for kind in ("memory-up", "java-auto", "add-mod", "remove-mod", "disable-jar", "eula", "port", "anything"):
        assert not any(access.allows(p, "POST", "/api/problem/fix", {"kind": kind}) for p in access.PRESETS.values()), kind


def test_a_file_of_your_own_that_only_runs_on_players_computers(tmp_path):
    """A mod file of your own (not one Craft Conductor manages) reaching for the parts of Minecraft
    only players have: said so, no "check for an update", and offered to players' mods (#189)."""
    mods = tmp_path / "mods"
    mods.mkdir()
    (mods / "controlify-3.5.3.jar").write_bytes(b"PK")
    lines = ["java.lang.NoClassDefFoundError: net/minecraft/client/gui/screens/Screen",
             "\tat dev.isxander.controlify.Controlify.init(Controlify.java:3) [controlify-3.5.3.jar:?]"]
    e = explain.explain(lines, tmp_path, [])
    assert e["cause"] == "players-only" and "only runs on players' computers" in e["title"], e
    assert "update" in e["words"] and "won't change" in e["words"]
    assert [a["kind"] for a in e["actions"]] == ["jar-to-players", "disable-jar"]
    assert e["actions"][0]["filename"] == "controlify-3.5.3.jar"


def test_moving_a_file_of_your_own_to_players_mods(hub_env):
    hub, c = hub_env
    login(c)
    d = hub.get("alpha")
    mods = d.m.server_dir / "mods"
    mods.mkdir(exist_ok=True)
    (mods / "controlify-3.5.3.jar").write_bytes(b"PK")
    d.problem = {"kind": "start", "cause": "players-only", "time": 0,
                 "actions": [{"kind": "jar-to-players", "filename": "controlify-3.5.3.jar", "name": "controlify",
                              "label": "Move controlify to players' mods"}]}
    status, r, _ = c.post("/api/servers/alpha/problem/fix", {"kind": "jar-to-players", "filename": "controlify-3.5.3.jar"})
    assert status == 200 and "friends' download" in r["message"], r
    from craft_conductor.clientpack import local_jars
    assert not (mods / "controlify-3.5.3.jar").exists()
    assert [p.name for p in local_jars(d.m.config)] == ["controlify-3.5.3.jar"]
    assert c.post("/api/servers/alpha/problem/fix", {"kind": "jar-to-players", "filename": "controlify-3.5.3.jar"})[0] == 409
