"""The lag finder: Minecraft's profiler and the world's files, turned into plain words."""

import threading
from collections import deque
from types import SimpleNamespace

from mcsm import lagfinder

from test_preview import write_world

PROFILE = """\
---- Minecraft Profiler Results ----
--- BEGIN PROFILE DUMP ---
[00] tick(600/1) - 100.00%/100.00%
[01] |   levels(600/1) - 92.00%/92.00%
[02] |   |   ServerLevel[world] minecraft:overworld(600/1) - 95.00%/87.40%
[03] |   |   |   tick(600/1) - 99.00%/86.53%
[04] |   |   |   |   entities(600/1) - 60.00%/51.92%
[05] |   |   |   |   |   tick(600/1) - 98.00%/50.88%
[06] |   |   |   |   |   |   minecraft:cow(240000/400) - 70.00%/35.62%
[06] |   |   |   |   |   |   create:contraption(600/1) - 10.00%/5.09%
[04] |   |   |   |   blockEntities(600/1) - 20.00%/17.31%
[05] |   |   |   |   |   minecraft:hopper(90000/150) - 80.00%/13.85%
[04] |   |   |   |   chunkSource(600/1) - 5.00%/4.33%
[01] |   connection(600/1) - 2.00%/2.00%
--- END PROFILE DUMP ---
"""


def test_the_profile_in_plain_words():
    s = lagfinder.summarize_profile(lagfinder.parse_profile(PROFILE))
    assert s["entities"]["share"] == 51.9 and s["machines"]["share"] == 17.3
    assert s["entities"]["types"][0] == ("minecraft:cow", 35.6)
    assert ("create:contraption", 5.1) in s["entities"]["types"]
    assert s["machines"]["types"] == [("minecraft:hopper", 13.8)]
    mods = [SimpleNamespace(name="Create", key="modrinth:create", filename="create-6.0.jar")]
    r = lagfinder.report(s, {}, 12.5, 3, mods)
    kinds = [f["kind"] for f in r["findings"]]
    assert kinds == ["entities", "machines"]  # chunks (4%) and the network (2%) are too small to mention
    assert "cow (35.6% of the tick)" in r["findings"][0]["detail"] and r["findings"][0]["mods"] == ["Create"]
    assert r["summary"].startswith("The biggest cost: mobs") and "51.9%" in r["summary"]
    assert "hoppers" in r["findings"][1]["tip"]


def entities_file(world, cx, cz, kinds):
    """An entities region file with one chunk holding ``kinds`` ({type: count})."""
    tmp = world.parent / "tmp-entities"
    ents = [{"id": k} for k, n in kinds.items() for _ in range(n)]
    write_world(tmp, {(cx, cz): {"Position": ("I", [cx, cz]), "Entities": ents}})
    (world / "entities").mkdir(parents=True, exist_ok=True)
    for f in (tmp / "region").iterdir():
        f.rename(world / "entities" / f.name)


def test_the_busiest_places(tmp_path):
    world = tmp_path / "world"
    write_world(world, {(10, 10): {"block_entities": [{"id": "minecraft:hopper", "x": 160, "y": 64, "z": 160}] * 30},
                        (0, 0): {"block_entities": []}})
    entities_file(world, 75, -25, {"minecraft:cow": 380, "minecraft:item": 30})
    places = lagfinder.hotspots(world)
    cows = places["entities"][0]
    assert (cows["x"], cows["z"], cows["count"], cows["dimension"]) == (1208, -392, 410, "the Overworld")
    assert cows["types"][0] == ("minecraft:cow", 380)
    assert places["machines"][0]["types"] == [("minecraft:hopper", 30)]
    r = lagfinder.report({}, places, None, 0)
    assert r["findings"][0]["places"][0].startswith("around x 1208, z -392 in the Overworld: 410 in all (380 cow")


class FakeProc:
    """Answers /debug stop by writing a profile, like Minecraft does."""

    def __init__(self, server_dir):
        self.server_dir = server_dir
        self.running = True
        self.lines = deque(maxlen=500)
        self.line_count = 0
        self.sent = []

    def send(self, cmd):
        self.sent.append(cmd)
        if cmd == "debug stop":
            (self.server_dir / "debug").mkdir(exist_ok=True)
            (self.server_dir / "debug" / "profile-results-2026-09-28_10.00.00.txt").write_text(PROFILE)
            self.lines.append("[Server thread/INFO]: Stopped debug profiling after 1.00 seconds and 13 ticks (13.00 ticks per second)")
            self.line_count += 1


def test_a_look_from_start_to_finish(make_config):
    cfg = make_config()
    world = cfg.server.dir / "world"
    entities_file(world, 75, -25, {"minecraft:cow": 50})
    proc = FakeProc(cfg.server.dir)
    d = SimpleNamespace(m=SimpleNamespace(server_dir=cfg.server.dir, config=cfg, lock=SimpleNamespace(mods=[])), proc=proc)
    f = lagfinder.LagFinder(d, seconds=1)
    result = f.run()
    assert f.state == "done", result
    assert proc.sent[:1] == ["debug start"] and "debug stop" in proc.sent
    assert result["tps"] == 13.0 and result["profiled"]
    assert result["findings"][0]["kind"] == "entities" and "x 1208" in result["findings"][0]["places"][0]
    assert not list((cfg.server.dir / "debug").iterdir())  # the profiler's file is tidied away
    assert lagfinder.load_report(cfg)["summary"] == result["summary"]
    # Stopped part-way: the profiler is still switched off.
    proc2 = FakeProc(cfg.server.dir)
    f2 = lagfinder.LagFinder(SimpleNamespace(m=d.m, proc=proc2), seconds=30)
    threading.Timer(0.3, f2.cancel.set).start()
    f2.run()
    assert f2.state == "cancelled" and "debug stop" in proc2.sent


class EmptyServer(FakeProc):
    """Minecraft 26.x with nobody online: paused, so the profiler counts no ticks and writes nothing."""

    def send(self, cmd):
        self.sent.append(cmd)
        if cmd == "debug stop":
            self.lines.append("[Server thread/INFO]: System chat: Stopped tick profiling after 30.05 second(s) and 0 tick(s) "
                              "(0.00 tick(s) per second)")
            self.line_count += 1


def test_a_paused_server_isnt_blamed_on_the_computer(make_config):
    """26.x words it differently, and an empty server is paused: the look said the computer may
    be too slow, when there was simply nothing to measure."""
    line = "Stopped tick profiling after 30.05 second(s) and 600 tick(s) (19.97 tick(s) per second)"
    assert lagfinder._STOPPED.search(line) and lagfinder._TICKS_PER_SECOND.search(line).group(1) == "19.97"
    cfg = make_config()
    (cfg.server.dir / "world").mkdir(parents=True)
    d = SimpleNamespace(m=SimpleNamespace(server_dir=cfg.server.dir, config=cfg, lock=SimpleNamespace(mods=[])),
                        proc=EmptyServer(cfg.server.dir))
    result = lagfinder.LagFinder(d, seconds=1).run()
    assert "Nobody was online" in result["summary"] and "too slow" not in result["summary"]
    assert result["tps"] is None and "note" not in result


def test_lag_finder_from_the_page(hub_env):
    from test_hub import login
    hub, c = hub_env
    login(c)
    assert c.get("/api/servers/alpha/performance/lag")[1] == {"finder": None, "report": None}
    assert c.post("/api/servers/alpha/performance/lag")[0] == 409  # (not running)
    assert c.post("/api/servers/alpha/performance/lag/stop")[0] == 404
    assert c.get("/api/servers/alpha/settings")[1]["find_lag"] is True
