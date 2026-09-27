"""Performance: reading ticks per second from each loader's console command, sampling only
now and then, and the Dashboard's endpoint."""

from mcsm import perf

from test_hub import login


def test_commands_and_parsing():
    assert perf.command_for("fabric", "1.21.1") == "tick query"
    assert perf.command_for("vanilla", "26.1") == "tick query"
    assert perf.command_for("fabric", "1.20.1") is None  # too old to report it
    assert perf.command_for("paper", "1.20.1") == "tps"
    assert perf.command_for("neoforge", "1.21.1") == "neoforge tps"
    assert perf.command_for("quilt", "24w14a") is None  # snapshot
    assert perf.parse(["[12:00:00] [Server thread/INFO]: Average time per tick: 62.5ms (Target: 50.0ms)"]) == {"tps": 16.0, "mspt": 62.5}
    assert perf.parse(["§6TPS from last 1m, 5m, 15m: §a*20.0, §a19.9, §a19.8"])["tps"] == 20.0
    assert perf.parse(["Overall: 19.500 TPS (51.282 ms/tick)"]) == {"tps": 19.5, "mspt": 51.282}
    assert perf.parse(["Overall : Mean tick time: 25.000 ms. Mean TPS: 20.000"])["tps"] == 20.0
    assert perf.parse(["something else"]) is None
    assert perf.verdict(20.0)[0] == "ok" and perf.verdict(18)[0] == "warn" and perf.verdict(12)[0] == "bad"


class FakeProc:
    running = True

    def __init__(self):
        self.sent = []

    def ask(self, command, parse, timeout=5):
        self.sent.append(command)
        return parse(["Average time per tick: 25.0ms (Target: 50.0ms)"])


def test_the_meter_asks_now_and_then():
    m, proc = perf.Meter(), FakeProc()
    first = m.sample(proc, "fabric", "1.21.1")
    assert first["tps"] == 20.0 and first["mspt"] == 25.0
    assert m.sample(proc, "fabric", "1.21.1") == first  # asked again at once: the last sample
    assert proc.sent == ["tick query"] and len(m.samples) == 1


def test_the_endpoint(hub_env):
    hub, c = hub_env
    login(c)
    r = c.get("/api/servers/alpha/performance")[1]
    assert r["supported"] is True and r["running"] is False and r["current"] is None and r["spark"] is False
    status, body, _ = c.post("/api/servers/alpha/performance/spark", {})
    assert status == 400 and "spark" in body["error"]
    assert "crashed_at" in c.get("/api/hub")[1]["servers"][0]  # for notifications
