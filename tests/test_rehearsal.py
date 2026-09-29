"""Update rehearsal: an update tried on a copy of the server, which isn't touched."""

import json

import pytest
from types import SimpleNamespace

from mcsm import rehearsal
from mcsm.config import ModSpec
from mcsm.daemon import Daemon

from test_manager import manager, update
from test_web import wait_for


def installed(make_config, http, modrinth, new_file=None):
    """A server on 1.21.1 with Good Mod; Good Mod 2.0 is out for 1.21.4 (as ``new_file``)."""
    modrinth.project("AAA", "goodmod", "Good Mod")
    modrinth.version("AAA", "1.0", ["1.21.1"])
    modrinth.version("AAA", "2.0", ["1.21.4"], filename=new_file)
    cfg = make_config([ModSpec("modrinth", "goodmod")])
    m = manager(cfg, http, ["1.21.1"])
    assert update(m).ok
    (cfg.server.dir / "world").mkdir()
    (cfg.server.dir / "world" / "level.dat").write_bytes(b"x")
    (cfg.server.dir / "logs").mkdir()
    (cfg.server.dir / "logs" / "latest.log").write_text("old log, not copied")
    return cfg, m


def rehearse(cfg, http, releases, minutes=0.05):
    daemon = SimpleNamespace(m=manager(cfg, http, releases), proc=None)
    r = rehearsal.Rehearsal(daemon, lambda c: manager(c, http, releases))
    r.minutes = minutes  # (seconds, for the test)
    return r, r.run()


def test_a_rehearsal_that_works(make_config, http, modrinth):
    cfg, m = installed(make_config, http, modrinth)
    before = (cfg.root / "mcsm.lock.json").read_text()
    r, result = rehearse(cfg, http, ["1.21.1", "1.21.4"])
    assert r.state == "done", r.log
    assert result["verdict"] == "good" and result["started"] and not result["crashed"], result
    assert result["from"] == "1.21.1" and result["to"] == "1.21.4"
    assert any("1.21.4" in line for line in result["changes"])
    # The server itself wasn't touched, and the copy is gone.
    assert (cfg.root / "mcsm.lock.json").read_text() == before
    assert not (cfg.state_dir / "rehearsal").exists()
    assert json.loads((cfg.state_dir / "rehearsal.json").read_text())["verdict"] == "good"
    # It counts for exactly this update.
    decision, _ = manager(cfg, http, ["1.21.1", "1.21.4"]).check()
    assert rehearsal.passed(cfg, decision.plan.fingerprint)
    assert not rehearsal.passed(cfg, "something else")


def test_a_rehearsal_that_fails_names_the_mod(make_config, http, modrinth):
    cfg, m = installed(make_config, http, modrinth, new_file="crash-2.0.jar")
    r, result = rehearse(cfg, http, ["1.21.1", "1.21.4"])
    assert result["verdict"] == "bad" and not result["started"], result
    assert "crash-2.0.jar" in result["error"] or "Good Mod" in result["error"]
    assert m.lock.minecraft == "1.21.1" and (cfg.server.dir / "mods" / "AAA-1.0.jar").exists()
    assert not rehearsal.passed(cfg, result["fingerprint"])


def test_the_copy_uses_the_servers_own_java(make_config, http, modrinth):
    """Nothing is linked or copied (Windows can't link without administrator rights, and a Java
    downloaded inside the copy made paths past Windows' 260-character limit)."""
    cfg, _ = installed(make_config, http, modrinth)
    (cfg.state_dir / "java" / "21").mkdir(parents=True)
    daemon = SimpleNamespace(m=manager(cfg, http, ["1.21.1", "1.21.4"]), proc=None)
    used = []

    def make(c):
        m = manager(c, http, ["1.21.1", "1.21.4"])
        used.append(m)
        return m
    r = rehearsal.Rehearsal(daemon, make)
    r.minutes = 0.05
    assert r.run()["verdict"] == "good"
    assert used[0].java.dir == cfg.state_dir / "java"
    assert (cfg.state_dir / "java" / "21").is_dir()  # (still there after the copy was removed)


def test_an_error_in_one_line():
    from mcsm.diagnose import headline
    message = ("Update failed and was rolled back (Minecraft 1.21.11 -> 26.3): server did not finish starting:\n"
               "Starting the server\nError: missing `server' JVM at `C:\\x\\bin\\server\\jvm.dll'.\n")
    assert headline(message).endswith("server did not finish starting: Error: missing `server' JVM at `C:\\x\\bin\\server\\jvm.dll'.")
    assert headline("java.lang.RuntimeException: boom:\nCaused by: X\n\tat a.b(C.java:1)") == \
        "java.lang.RuntimeException: boom: Caused by: X"
    assert headline("one line") == "one line" and headline("") == ""


def test_nothing_to_rehearse(make_config, http, modrinth):
    cfg, _ = installed(make_config, http, modrinth)
    r, result = rehearse(cfg, http, ["1.21.1"])
    assert r.state == "failed" and "no update" in result["error"]
    assert not (cfg.state_dir / "rehearsal").exists()


def test_automatic_updates_wait_for_a_rehearsal(make_config, http, modrinth, monkeypatch):
    cfg, _ = installed(make_config, http, modrinth, new_file="crash-2.0.jar")
    text = (cfg.root / "mcsm.toml").read_text().replace("rehearse = false", "rehearse = true")
    (cfg.root / "mcsm.toml").write_text(text)
    from mcsm import config as configmod
    m = manager(configmod.load(cfg.root), http, ["1.21.1", "1.21.4"])
    sent = []
    m.notifier.send = sent.append
    d = Daemon(m, autostart=True)
    d.make_manager = lambda: (lambda c: manager(c, http, ["1.21.1", "1.21.4"]))
    runs = []
    real = rehearsal.Rehearsal.run
    monkeypatch.setattr(rehearsal.Rehearsal, "run", lambda self: (runs.append(1), setattr(self, "minutes", 0.05), real(self))[2])
    assert d.check_for_updates().startswith("trying the update")  # a rehearsal starts in the background
    assert d.check_for_updates() == "waiting for the update rehearsal to finish"
    wait_for(lambda: d.rehearsal.state != "running", timeout=30)
    # (checked again straight away: once the copy is cleaned up, just after the state changes)
    wait_for(lambda: d.next_check == 0.0, timeout=30)
    assert d.check_for_updates().startswith("held back")
    assert m.lock.minecraft == "1.21.1"
    assert sum("held back" in x for x in sent) == 1
    assert d.check_for_updates().startswith("held back") and len(runs) == 1  # not tried again and again
    # Update now (from the page) still goes ahead: the real update's own test boot rolls it back.
    with pytest.raises(RuntimeError, match="rolled back"):
        d.check_for_updates(True)


def test_a_passing_rehearsal_lets_the_update_go_ahead(make_config, http, modrinth, monkeypatch):
    cfg, _ = installed(make_config, http, modrinth)
    text = (cfg.root / "mcsm.toml").read_text().replace("rehearse = false", "rehearse = true")
    (cfg.root / "mcsm.toml").write_text(text)
    from mcsm import config as configmod
    m = manager(configmod.load(cfg.root), http, ["1.21.1", "1.21.4"])
    d = Daemon(m, autostart=True)
    d.make_manager = lambda: (lambda c: manager(c, http, ["1.21.1", "1.21.4"]))
    real = rehearsal.Rehearsal.run
    monkeypatch.setattr(rehearsal.Rehearsal, "run", lambda self: (setattr(self, "minutes", 0.05), real(self))[1])
    assert d.check_for_updates().startswith("trying the update")
    wait_for(lambda: d.rehearsal.state != "running", timeout=30)
    assert d.check_for_updates().startswith("updated") and m.lock.minecraft == "1.21.4"


def test_complaints_are_grouped_by_mod():
    mods = [SimpleNamespace(name="Sodium", filename="sodium-fabric-0.6.0.jar", key="modrinth:AANobbMI"),
            SimpleNamespace(name="Create", filename="create-1.21.1-6.0.jar", key="modrinth:create")]
    lines = [
        "[12:00:00] [Server thread/WARN]: Sodium couldn't find a renderer option",
        "[12:00:01] [Server thread/ERROR]: Exception in create:mechanical_press ticking",
        "\tat com.simibubi.create.content.Press.tick(Press.java:10) [create-1.21.1-6.0.jar:?]",
        "[12:00:02] [Server thread/WARN]: Can't keep up! Is the server overloaded? Running 2500ms or 50 ticks behind",
        "[12:00:03] [Server thread/WARN]: Ambiguity between arguments",
        "[12:00:04] [Server thread/INFO]: Create says hello",
    ]
    c = rehearsal.complaints(lines, mods)
    assert [(x["name"], x["warnings"], x["errors"]) for x in c["mods"]] == [("Create", 0, 2), ("Sodium", 1, 0)]
    assert c["other"]["warnings"] == 1 and c["lag"] == {"count": 1, "worst_ms": 2500}
    result = {"started": True, "crashed": False, "tps_avg": 19.9, "complaints": c}
    assert rehearsal.verdict(result)[0] == "warn"
    assert rehearsal.verdict({**result, "complaints": {**c, "mods": [], "lag": {"count": 0}}})[0] == "good"
    assert rehearsal.verdict({"started": False, "error": "boom"})[0] == "bad"


def test_rehearsal_from_the_page(hub_env):
    from test_hub import login
    from test_web import wait_for
    hub, c = hub_env
    login(c)
    base = "/api/servers/alpha/updates/rehearsal"
    assert c.post(base, {"minutes": 0})[0] == 400
    assert c.post(base, {"minutes": "3"})[0] == 400
    assert c.post(base, {"target": "1.21; stop"})[0] == 400
    assert c.get(base)[1] == {"rehearsal": None, "report": None}
    status, r, _ = c.post(base, {"minutes": 1})
    assert status == 200, r
    wait_for(lambda: c.get(base)[1]["rehearsal"]["state"] != "running", timeout=30)
    got = c.get(base)[1]["rehearsal"]
    assert got["state"] == "failed" and "no update" in got["result"]["error"]  # (alpha is up to date)
    assert c.post(base + "/stop")[0] == 404
    assert "rehearse" in c.get("/api/servers/alpha/settings")[1]
