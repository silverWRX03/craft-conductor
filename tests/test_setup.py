"""First-time setup: the web setup page, its validation, and `craft-conductor start` on a new machine."""

import json
import threading

import pytest

from craft_conductor import config as configmod, lock as lockmod, setup as setupmod
from craft_conductor.config import ConfigError
from craft_conductor.daemon import Daemon
from craft_conductor.properties import read_properties

from test_manager import manager
from test_web import Client, login, wait_for


def spec(**kw):
    return setupmod.SetupSpec.from_dict({"accept_eula": True, **kw})


def test_spec_validation():
    s = spec(loader="fabric", mods=["lithium"], memory_gb=6, motd="  My   cool\nserver  ")
    assert s.mods == ["fabric-api", "lithium"]  # Fabric API added for Fabric mods
    assert s.motd == "My cool server"  # one line, so it can't break server.properties
    assert spec(loader="neoforge", mods=["create"]).mods == ["create"]
    assert spec(loader="fabric").mods == []  # no mods, no Fabric API needed
    with pytest.raises(ConfigError, match="EULA"):
        setupmod.SetupSpec.from_dict({"loader": "fabric"})
    with pytest.raises(ConfigError, match="can't run mods"):
        spec(loader="vanilla", mods=["lithium"])
    for bad in ({"loader": "bukkit"}, {"mods": ["../x"]}, {"minecraft": "1.21; rm"},
                {"memory_gb": 0}, {"port": 80}, {"difficulty": "nightmare"}, {"mods": "lithium"}):
        with pytest.raises(ConfigError):
            spec(**bad)


def test_configure_writes_the_server(tmp_path):
    root = tmp_path / "srv"
    cfg = setupmod.configure(root, spec(loader="neoforge", minecraft="1.21.1", mods=["create"],
                                        optional_mods=["jei"], memory_gb=6, motd="Friends", max_players=8,
                                        difficulty="hard", port=25570, network_access=True))
    assert cfg.server.loader == "neoforge" and cfg.server.minecraft == "1.21.1" and cfg.server.memory == "6G"
    assert [(m.id, m.required) for m in cfg.mods] == [("create", True), ("jei", False)]
    assert cfg.web.host == "0.0.0.0"
    assert cfg.updates.strategy == "mods-only"  # a chosen version is kept
    latest = setupmod.configure(tmp_path / "srv2", spec(loader="fabric"))
    assert latest.updates.strategy == "latest-compatible"  # "newest": the forever server
    props = read_properties(cfg.server.dir / "server.properties")
    assert props["motd"] == "Friends" and props["max-players"] == "8" and props["server-port"] == "25570"
    assert props["difficulty"] == "hard"
    assert "eula=true" in (cfg.server.dir / "eula.txt").read_text()


def test_memory_suggestion():
    assert setupmod.suggested_memory_gb(16) == 8
    assert setupmod.suggested_memory_gb(6) == 3
    assert setupmod.suggested_memory_gb(2) == 2
    assert setupmod.suggested_memory_gb(64) == 8
    assert setupmod.suggested_memory_gb(0) == 4


@pytest.fixture
def pending_daemon(make_config, http, modrinth, fake_java, monkeypatch):
    modrinth.project("FAPI", "fabric-api", "Fabric API")
    modrinth.version("FAPI", "0.1", ["1.21.1"])
    modrinth.project("AAA", "goodmod", "Good Mod")
    modrinth.version("AAA", "1.0", ["1.21.1"])
    cfg = make_config([])
    cfg.web.port = 0
    cfg.web.password = "hunter2hunter2"
    setupmod.mark_pending(cfg.root)

    # configure() writes a fresh craft-conductor.toml; keep the test's fake java and short timeouts.
    real = configmod.render_template

    def render(loader, minecraft):
        text = real(loader, minecraft).replace('default = "java"', f"default = {json.dumps(str(fake_java))}")
        return text.replace("warn_minutes = [10, 5, 1]", "warn_minutes = []") \
                   .replace('startup_timeout = "10m"', 'startup_timeout = "30s"')
    monkeypatch.setattr(configmod, "render_template", render)

    m = manager(cfg, http, ["1.21.1"])
    d = Daemon(m, tick=0.1)
    t = threading.Thread(target=d.run, kwargs={"web": True}, daemon=True)
    t.start()
    wait_for(lambda: d.ui is not None)
    yield d, Client(d.ui.url.rstrip("/")), cfg
    d.stop_requested.set()
    t.join(20)


def test_web_setup_builds_and_starts_the_server(pending_daemon):
    d, c, cfg = pending_daemon
    login(c)
    status = c.get("/api/status")[1]
    assert status["setup_pending"] and status["state"] == "stopped"  # nothing starts before setup

    opts = c.get("/api/setup")[1]
    assert opts["pending"] and opts["versions"] == ["1.21.1"]
    assert [l["name"] for l in opts["loaders"]][:3] == ["fabric", "neoforge", "forge"]
    assert 1 <= opts["memory_gb"] <= 8

    # Search is filtered by the loader picked on the setup page.
    from craft_conductor.mods.modrinth import API
    d.m.http.json[f"{API}/search"] = {"hits": [{"project_id": "AAA", "slug": "goodmod", "title": "Good Mod"}]}
    assert c.get("/api/mods/search?loader=fabric&q=good")[1]["results"][0]["slug"] == "goodmod"
    assert c.get("/api/mods/search?loader=bukkit&q=good")[0] == 400

    assert c.post("/api/setup", {"loader": "fabric", "minecraft": "1.21.1", "mods": ["goodmod"]})[0] == 400  # no EULA
    status_code, body, _ = c.post("/api/setup", {"loader": "fabric", "minecraft": "1.21.1", "mods": ["goodmod"],
                                                 "memory_gb": 2, "motd": "Test", "accept_eula": True})
    assert status_code == 200, body
    wait_for(lambda: d.state == "running" and not d.setup_pending, timeout=30)
    lk = lockmod.load(cfg.root)
    assert lk.minecraft == "1.21.1" and {m.name for m in lk.mods} == {"Fabric API", "Good Mod"}
    assert read_properties(cfg.server.dir / "server.properties")["motd"] == "Test"
    assert c.get("/api/status")[1]["setup_pending"] is False
    assert c.post("/api/setup", {"accept_eula": True})[0] == 409  # only once


def test_failed_setup_can_be_retried(pending_daemon):
    d, c, cfg = pending_daemon
    login(c)
    assert c.post("/api/setup", {"loader": "fabric", "mods": ["no-such-mod"], "accept_eula": True})[0] == 200
    wait_for(lambda: d.last_job and d.last_job["name"] == "set up server")
    assert not d.last_job["ok"] and "no-such-mod" in d.last_job["message"]
    assert d.setup_pending and d.state == "stopped"
    # where to read more: a report with the error and what happened before it
    where = d.last_job["message"].split("The details are in ", 1)[1].strip()
    report = open(where, encoding="utf-8").read()
    assert "set up server failed" in report and "no-such-mod" in report and "Minecraft's own log" in report

    assert c.post("/api/setup", {"loader": "fabric", "mods": ["goodmod"], "accept_eula": True})[0] == 200
    wait_for(lambda: d.state == "running" and not d.setup_pending, timeout=30)


def test_a_retry_takes_out_what_was_taken_off_the_form(pending_daemon):
    """#235: the first try put a file of your own and an imported world in the server. Removed on the
    setup page since (or a new world chosen), the retry takes them out, so it doesn't fail the same way."""
    d, c, cfg = pending_daemon
    login(c)
    assert c.post("/api/setup", {"loader": "fabric", "mods": ["no-such-mod"], "accept_eula": True})[0] == 200
    wait_for(lambda: d.last_job and d.last_job["name"] == "set up server")
    assert d.setup_pending
    mods, server = cfg.server.dir / "mods", cfg.server.dir
    mods.mkdir(parents=True, exist_ok=True)
    (mods / "rt-server-needs-1.0.0.jar").write_bytes(b"PK")   # (as the first try left them)
    (mods / "kept-1.0.jar").write_bytes(b"PK")
    (server / "world").mkdir(exist_ok=True)
    (server / "world" / "level.dat").write_bytes(b"imported")
    body = {"loader": "fabric", "mods": ["goodmod"], "accept_eula": True,
            "remove_local": ["rt-server-needs-1.0.0.jar", "../craft-conductor.toml"], "replace_world": True}
    assert c.post("/api/setup", body)[0] == 200
    wait_for(lambda: d.state == "running" and not d.setup_pending, timeout=30)
    assert not (mods / "rt-server-needs-1.0.0.jar").exists() and (mods / "kept-1.0.jar").exists()
    assert (cfg.root / "craft-conductor.toml").exists()
    assert not (server / "world" / "level.dat").exists() or (server / "world" / "level.dat").read_bytes() != b"imported"


def test_a_second_setup_while_one_runs_changes_nothing(pending_daemon):
    """A second click (or browser) while the setup runs is refused as busy before it removes the world
    or files the running one is using."""
    import threading
    d, c, cfg = pending_daemon
    login(c)
    server, mods = cfg.server.dir, cfg.server.dir / "mods"
    mods.mkdir(parents=True, exist_ok=True)
    (mods / "mine-1.0.jar").write_bytes(b"PK")
    (server / "world").mkdir(exist_ok=True)
    (server / "world" / "level.dat").write_bytes(b"being imported")
    gate = threading.Event()
    assert d.submit("set up server", lambda: gate.wait(20) and "done")  # (the first setup, still running)
    try:
        body = {"loader": "fabric", "mods": [], "accept_eula": True, "remove_local": ["mine-1.0.jar"], "replace_world": True}
        status, r, _ = c.post("/api/setup", body)
        assert status == 409 and "busy" in r["error"], r
        assert (server / "world" / "level.dat").read_bytes() == b"being imported" and (mods / "mine-1.0.jar").exists()
    finally:
        gate.set()
