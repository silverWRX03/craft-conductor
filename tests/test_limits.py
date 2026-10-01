"""Limits per server (CPU cores, priority), the memory check, and the computer's warnings."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from craft_conductor import health, limits


def test_settings_are_checked():
    assert limits.check(0, "normal") == (0, "normal")
    assert limits.check("2", "low") == (2, "low")
    with pytest.raises(ValueError):
        limits.check(-1, "normal")
    with pytest.raises(ValueError):
        limits.check(1, "urgent")
    with pytest.raises(ValueError):
        limits.check("lots", "normal")


@pytest.mark.skipif(not hasattr(__import__("os"), "sched_setaffinity"), reason="CPU affinity is Linux-only")
def test_a_started_process_gets_its_cores_and_priority():
    out = subprocess.run([sys.executable, "-c", "import os; print(len(os.sched_getaffinity(0)), os.nice(0))"],
                         capture_output=True, text=True, **limits.popen_options(1, "low")).stdout.split()
    assert out == ["1", str(limits.LOW_NICE)]
    assert limits.popen_options(0, "normal") == {}


def test_memory_fits():
    ok = limits.memory_fits([4, 4], 4, 16)
    assert ok["fits"] and ok["after_gb"] == 12 and ok["free_gb"] == 6.5
    too_much = limits.memory_fits([6, 6], 4, 16)
    assert not too_much["fits"] and too_much["after_gb"] == 16
    assert limits.memory_fits([], 4, None)["fits"]  # (the computer's memory is unknown: don't block)


def test_the_config_takes_limits(tmp_path):
    from craft_conductor import config as configmod
    base = {"server": {"loader": "fabric", "minecraft": "1.21.1"}}
    c = configmod.parse(tmp_path, {**base, "server": {**base["server"], "cpu_cores": 2, "priority": "low"}})
    assert (c.server.cpu_cores, c.server.priority) == (2, "low")
    with pytest.raises(configmod.ConfigError):
        configmod.parse(tmp_path, {**base, "server": {**base["server"], "priority": "high"}})


class FakeHub:
    def __init__(self, home):
        self.home = home
        self.daemons = {}
        self.sent = []
        self.push = SimpleNamespace(notify=lambda title, body, url="/", tag="", kind=None: self.sent.append(body))

    def memory_plan(self, adding=None):
        return {"running": [], "running_gb": 0, "total_gb": 16}


def test_warnings_are_sent_once(tmp_path, monkeypatch):
    hub = FakeHub(tmp_path)
    h = health.Health(hub)
    monkeypatch.setattr(health, "disk_free", lambda paths: [(Path(tmp_path), 2.0)])
    monkeypatch.setattr(health, "memory_available_gb", lambda: 8.0)
    w = h.check()
    assert [x["level"] for x in w] == ["bad"] and "2.0 GB" in w[0]["title"]
    h.check()
    assert len(hub.sent) == 1  # (the same problem isn't sent again)
    monkeypatch.setattr(health, "disk_free", lambda paths: [(Path(tmp_path), 50.0)])
    assert h.check() == []


def test_a_busy_cpu_is_noticed(tmp_path, monkeypatch):
    h = health.Health(FakeHub(tmp_path))
    monkeypatch.setattr(health, "disk_free", lambda paths: [])
    monkeypatch.setattr(health, "memory_available_gb", lambda: None)
    monkeypatch.setattr(h, "_cpu_sample", lambda: 0.97)
    for _ in range(health.CPU_MINUTES - 1):
        assert h.check() == []  # (it has to last a few minutes)
    assert [x["id"] for x in h.check()] == ["cpu"]


def test_the_page_gets_the_plan_and_saves_limits(hub_env):
    from test_hub import login
    hub, c = hub_env
    login(c)
    status, plan, _ = c.get("/api/hub/memory?adding=alpha")
    assert status == 200 and "fits" in plan and plan["adding_gb"] > 0
    s = c.get("/api/servers/alpha/settings")[1]
    assert s["cpu_cores"] == 0 and s["priority"] == "normal" and s["cpu_count"] >= 1
    assert c.post("/api/servers/alpha/settings", {"priority": "low", "cpu_cores": 1})[0] == 200
    cfg = hub.get("alpha").m.config.server
    assert (cfg.cpu_cores, cfg.priority) == (1, "low")
    assert c.post("/api/servers/alpha/settings", {"priority": "urgent"})[0] == 400
    assert c.post("/api/servers/alpha/settings", {"cpu_cores": "lots"})[0] == 400
    assert "health" in c.get("/api/hub")[1]
