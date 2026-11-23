"""Uninstall Craft Conductor… in Craft Conductor settings → About & updates (roadmap 38): the page's side.

GET /api/hub/uninstall is the plan (uninstall.plan, the tick boxes in the query); POST runs it with the
password typed again, as a background job followed with GET /api/hub/uninstall/progress, and the hub
exits once the page has the report. Only the owner, only from a browser on this computer.

Everything runs in the test hub's temporary home, with the person's folders pointed into the
temporary folder too, and a runner that only records (nothing on this computer is touched).
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import pytest

from craft_conductor import access, folders, uninstall
from craft_conductor.uninstall import Choices

from test_cli_uninstall import TOML, FakeRunner, running  # noqa: F401  (running: the fixture)
from test_hub import login
from test_remote import PERSON_PASSWORD, STRONG, as_other_device, pair_phone, ready_for_links
from test_web import Client, wait_for

PLAN, PROGRESS = "/api/hub/uninstall", "/api/hub/uninstall/progress"


@pytest.fixture
def uhub(hub_env, tmp_path, monkeypatch):
    """The test hub, with the person's own folders in the temporary folder, a runner that only
    records, and a Downloads folder for the report."""
    hub, c = hub_env
    user = tmp_path / "user"
    downloads = user / "Downloads"
    downloads.mkdir(parents=True)
    env = {"HOME": str(user), "USERPROFILE": str(user), "XDG_CONFIG_HOME": str(tmp_path / "xdg"),
           "XDG_DATA_HOME": str(user / ".local" / "share")}
    for name in ("HOME", "USERPROFILE", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, env[name])
    monkeypatch.delenv("CRAFT_CONDUCTOR_CONTAINER", raising=False)
    monkeypatch.setattr(folders, "downloads_dir", lambda *a, **k: downloads)
    monkeypatch.setattr(uninstall, "_frozen", lambda: False)
    monkeypatch.setattr(uninstall, "_prefix", lambda: str(tmp_path / "venv"))
    runner = FakeRunner()
    hub.ui.hub_api.uninstall_runner = runner
    hub.ui.hub_api.uninstall_env = env
    return hub, c, runner, env, downloads


def _finish(c, job: str, timeout=60) -> dict:
    """Follow the job until it's done (as the page does), and return the last answer."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, body, _ = c.get(f"{PROGRESS}?id={job}")
        assert status == 200, body
        if body["state"] != "running":
            return body
        time.sleep(0.1)
    raise AssertionError("the uninstall didn't finish")


# ------------------------------------------------------------------ who may
def test_nobody_but_the_owner_at_this_computer_can_plan_or_start_it(uhub):
    hub, c, runner, env, _ = uhub
    assert c.get(PLAN)[0] == 401  # (not signed in)
    login(c)
    assert c.post("/api/auth/change", {"mode": "password", "secret": STRONG})[0] == 200
    assert c.post("/api/hub/network", {"enabled": True})[0] == 200
    ready_for_links(hub)
    ticks = {"password": STRONG, "servers": True}
    # The owner, from another computer (or through a proxy or a tunnel on this one).
    away = as_other_device(Client(c.base))
    assert away.post("/api/login", {"password": STRONG})[0] == 200
    tunnel = Client(c.base)
    tunnel.cookie = away.cookie
    for who, headers in ((away, {}), (tunnel, {"Tailscale-User-Login": "someone@example.com"}),
                         (tunnel, {"CF-Connecting-IP": "203.0.113.7"})):
        assert who.call("GET", PLAN, headers=headers)[0] == 403
        assert who.call("POST", PLAN, ticks, headers=headers)[0] == 403
        assert who.call("GET", f"{PROGRESS}?id=x", headers=headers)[0] == 403
    # An invited person, here on this computer, and a paired phone.
    status, r, _ = c.post("/api/hub/users/invite", {"name": "Sam", "grants": {"alpha": sorted(access.PRESETS["manager"])},
                                                    "host": "mc.example.com"})
    assert status == 200, r
    person = Client(c.base)
    assert person.post("/api/invite/accept", {"token": r["url"].split("#invite=")[1], "username": "sam",
                                              "password": PERSON_PASSWORD})[0] == 200
    phone = pair_phone(hub, c, r["person"])
    for who in (person, phone):
        assert who.get(PLAN)[0] == 403
        assert who.post(PLAN, {**ticks, "password": PERSON_PASSWORD})[0] == 403
        assert who.get(f"{PROGRESS}?id=x")[0] == 403
    assert runner.calls == [] and not hub.stop_requested.is_set()
    assert c.get(PLAN)[0] == 200  # (the owner, here: yes)


def test_a_wrong_password_is_refused_and_nothing_happens(uhub):
    hub, c, runner, env, _ = uhub
    login(c)
    status, body, _ = c.post(PLAN, {"password": "not-it"})
    assert status == 403 and "wrong password" in body["error"]
    status, body, _ = c.post(PLAN, {})
    assert status == 403
    assert runner.calls == [] and not hub.stop_requested.is_set()
    assert hub.ui.hub_api.uninstall_job is None


def test_the_request_carries_only_the_tick_boxes(uhub, tmp_path):
    hub, c, runner, env, _ = uhub
    login(c)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    for extra in ({"paths": [str(elsewhere)]}, {"home": str(elsewhere)}, {"servers": str(elsewhere)},
                  {"servers": "yes"}, {"keep_lockbox_key": 1}):
        status, body, _ = c.post(PLAN, {"password": "PASSWORD", **extra})
        assert status == 400, (extra, body)
    status, body, _ = c.get(f"{PLAN}?home={elsewhere}&paths={elsewhere}")
    assert status == 400, body
    assert runner.calls == [] and not hub.stop_requested.is_set()


# ------------------------------------------------------------------ the plan
def _shown(part: uninstall.Part) -> dict:
    return {"key": part.key, "label": part.label, "present": part.present, "kept": part.kept, "action": part.action,
            "manual": part.manual}


def test_the_plan_is_uninstall_plan_with_every_box_off(uhub):
    hub, c, runner, env, _ = uhub
    login(c)
    status, got, _ = c.get(PLAN)
    assert status == 200, got
    want = uninstall.plan(hub.home, Choices(), env=env, runner=runner)
    assert [{k: p[k] for k in ("key", "label", "present", "kept", "action", "manual")} for p in got["parts"]] \
        == [_shown(p) for p in want]
    assert got["choices"] == {"servers": False, "backups": False, "exports": False, "games": False,
                              "keep_lockbox_key": False}
    kept = {p["key"]: p["kept"] for p in got["parts"] if p["present"]}
    assert kept["servers"] and kept["state"] is False
    state = next(p for p in got["parts"] if p["key"] == "state")
    assert state["paths"] == [str(x) for x in next(p for p in want if p.key == "state").paths][:len(state["paths"])]
    assert got["servers"] == len(uninstall.servers_of(hub.home)) and "worlds" in got
    # Ticking a box shows what it changes.
    status, ticked, _ = c.get(f"{PLAN}?servers=1&keep_lockbox_key=1")
    assert status == 200 and ticked["choices"]["servers"] and ticked["choices"]["keep_lockbox_key"]
    want = uninstall.plan(hub.home, Choices(servers=True, keep_lockbox_key=True), env=env, runner=runner)
    assert [p["action"] for p in ticked["parts"]] == [p.action for p in want]
    assert not next(p for p in ticked["parts"] if p["key"] == "servers")["kept"]
    assert runner.calls == []  # (planning changes nothing)


def test_a_server_with_players_on_is_asked_about_first(uhub):
    hub, c, runner, env, _ = uhub
    login(c)
    d = hub.get("alpha")

    class Running:  # (a server with someone on it; nothing really runs)
        running, stopping = True, False

    d.proc, d.players = Running(), {"Steve"}
    try:
        plan = c.get(PLAN)[1]
        assert plan["running"] == [{"id": "alpha", "name": "Alpha", "players": 1}]
        status, body, _ = c.post(PLAN, {"password": "PASSWORD"})
        assert status == 409 and body.get("confirm") == "players" and "Alpha" in body["error"]
        assert runner.calls == [] and hub.ui.hub_api.uninstall_job is None
    finally:
        d.proc, d.players = None, set()


# ------------------------------------------------------------------ doing it
def test_it_stops_the_servers_runs_the_plan_reports_and_the_hub_exits(uhub):
    hub, c, runner, env, downloads = uhub
    login(c)
    alpha = hub.get("alpha")
    status, started, _ = c.post(PLAN, {"password": "PASSWORD", "exports": True})
    assert status == 200, started
    # While it runs, the rest of the control panel answers nothing (so nothing is written back).
    status, body, _ = c.get("/api/hub")
    assert status == 503
    done = _finish(c, started["id"])
    assert done["state"] == "done", done
    report = done["report"]
    assert report["text"].startswith("Craft Conductor uninstall report")
    assert any("Settings and state" in line for line in report["removed"])
    assert any("Servers and worlds" in line for line in report["kept"])
    # The steps, in order, each with its label (two parts may share a key: "tunnels").
    labels = [s["label"] for s in done["steps"]]
    assert labels[0] == "Stopping the servers" and "Settings and state" in labels
    assert all(s["status"] in ("done", "failed", "kept") for s in done["steps"])
    # Each server was stopped the usual way (its manager asked to stop), before anything was deleted.
    assert not hub._threads["alpha"].is_alive() and alpha.stop_requested.is_set()
    state = hub.home / ".craft-conductor"
    assert runner.gone(state / "hub.json") or runner.gone(state)
    assert not any(runner.gone(p) for p in uninstall.servers_of(hub.home).values() if p != hub.home)
    # The report is saved in Downloads (there's something left to do: the pip install).
    assert report["manual"] and (downloads / "Craft Conductor uninstall report.txt").read_text(encoding="utf-8") == report["text"]
    assert report["saved"] == str(downloads / "Craft Conductor uninstall report.txt")
    # The page has the report: Craft Conductor closes.
    wait_for(lambda: hub.stop_requested.is_set(), timeout=10)
    wait_for(lambda: hub.ui.httpd is None or hub.ui.httpd.socket.fileno() == -1, timeout=30)


def test_only_one_uninstall_at_a_time(uhub, monkeypatch):
    hub, c, runner, env, _ = uhub
    login(c)
    import threading
    hold = threading.Event()
    api = hub.ui.hub_api
    real = api._stop_servers_for_uninstall
    monkeypatch.setattr(api, "_stop_servers_for_uninstall", lambda: (hold.wait(20), real())[1])
    status, started, _ = c.post(PLAN, {"password": "PASSWORD"})
    assert status == 200
    assert c.post(PLAN, {"password": "PASSWORD"})[0] == 503  # (everything but the progress waits)
    hold.set()
    assert _finish(c, started["id"])["state"] == "done"


def test_the_log_file_in_the_state_folder_is_let_go_of_before_the_state_is_deleted(uhub, monkeypatch):
    """R7: on Windows a file held open can't be deleted, and Craft Conductor without a window writes
    its log into the state folder (desktop.py)."""
    hub, c, runner, env, _ = uhub
    login(c)
    state = hub.home / ".craft-conductor"
    log_file = open(state / "craft-conductor.log", "a", encoding="utf-8")
    handler = logging.StreamHandler(log_file)
    logging.getLogger("craft_conductor").addHandler(handler)
    monkeypatch.setattr(sys, "stderr", log_file)
    seen = []
    real = runner.delete_tree

    def delete_tree(path):
        if Path(path) == state or Path(path).parent == state:
            seen.append(log_file.closed)
        return real(path)
    runner.delete_tree = delete_tree
    runner.delete_file = lambda path, real=runner.delete_file: (seen.append(log_file.closed) if Path(path).parent == state
                                                                 else None, real(path))[1]
    try:
        status, started, _ = c.post(PLAN, {"password": "PASSWORD"})
        assert status == 200
        assert _finish(c, started["id"])["state"] == "done"
        assert seen and all(seen)
        assert sys.stderr is not log_file and handler.stream is not log_file
    finally:
        logging.getLogger("craft_conductor").removeHandler(handler)
        log_file.close()


def test_a_server_still_running_keeps_its_folders(uhub, monkeypatch):
    """The hub's stop_servers returns the exact folders (roots) of servers still running; they're kept."""
    hub, c, runner, env, _ = uhub
    login(c)
    alpha = uninstall.servers_of(hub.home)["alpha"]
    monkeypatch.setattr(hub.ui.hub_api, "_stop_servers_for_uninstall", lambda: [alpha])
    status, started, _ = c.post(PLAN, {"password": "PASSWORD", "servers": True, "backups": True})
    assert status == 200, started
    done = _finish(c, started["id"])
    assert not runner.gone(alpha) and not any(runner.gone(p) for p in alpha.rglob("*"))
    assert any(str(alpha) in line for line in done["report"]["failed"])


def test_stop_servers_answers_with_the_inventorys_own_folders(uhub, monkeypatch):
    """A server that didn't stop is named by its folder as the inventory has it; one the inventory
    doesn't know makes every server count as running (never a guess that lets one be deleted)."""
    hub, c, runner, env, _ = uhub
    api = hub.ui.hub_api
    d = hub.get("alpha")
    monkeypatch.setattr(api, "UNINSTALL_STOP_GRACE", 0.5)
    monkeypatch.setattr(d.m.config.server, "stop_timeout", 0)
    thread = hub._threads["alpha"]

    class Stuck:  # (a manager thread that doesn't end)
        def is_alive(self):
            return True
    hub._threads["alpha"] = Stuck()
    monkeypatch.setattr("craft_conductor.daemon.STOP_WARNING", 0)
    try:
        assert api._stop_servers_for_uninstall() == [uninstall.servers_of(hub.home)["alpha"]]
        monkeypatch.setattr(uninstall, "servers_of", lambda home: {})
        with pytest.raises(RuntimeError):
            api._stop_servers_for_uninstall()
    finally:
        hub._threads["alpha"] = thread


def test_a_server_another_craft_conductor_runs_is_kept_and_shown_as_running(uhub, running, monkeypatch):
    """A server the hub doesn't look after because another Craft Conductor window (or `craft-conductor
    run`) runs it is never deleted: it's asked to stop the usual way, and kept while it still runs (as
    the command does), and the dialog lists it with the running servers."""
    hub, c, runner, env, _ = uhub
    login(c)
    gamma = hub.home / "servers" / "gamma"
    gamma.mkdir(parents=True)
    (gamma / "craft-conductor.toml").write_text(TOML, encoding="utf-8")
    running(gamma, "ignore")  # (another Craft Conductor's, which doesn't stop when asked)
    hub.scan()
    assert "gamma" in hub.problems and "gamma" not in hub.daemons
    monkeypatch.setattr(hub.ui.hub_api, "UNINSTALL_STOP_UNANSWERED", 0.5)
    from craft_conductor import daemon
    asked, real = [], daemon.request_stop_in
    monkeypatch.setattr(daemon, "request_stop_in", lambda state, words="": (asked.append((Path(state), words)),
                                                                            real(state, words))[1])
    plan = c.get(PLAN)[1]
    assert {"id": "gamma", "name": "gamma", "players": 0} in plan["running"]
    status, started, _ = c.post(PLAN, {"password": "PASSWORD", "servers": True, "backups": True})
    assert status == 200, started
    done = _finish(c, started["id"])
    assert done["state"] == "done", done
    assert (gamma / ".craft-conductor", uninstall.PLAYERS_TOLD) in asked  # (asked to stop, the usual way)
    assert not (gamma / ".craft-conductor" / "stop-requested").exists()  # (the unanswered request isn't left behind)
    root = uninstall.servers_of(hub.home)["gamma"]
    assert not runner.gone(root) and not any(runner.gone(x) for x in root.rglob("*"))
    assert any(f"the server in {root} is still running" in line for line in done["report"]["failed"])
