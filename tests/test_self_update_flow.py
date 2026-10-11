"""Craft Conductor's own update, as the person sees it: one state (selfupdate.Updater) that says whether an
update is available, deferred with Later, under way, restarting or failed, and that the page only shows.

The page's side of it (the prompt closing, the update screen, the red dots, the same-tab reload) is
tests/test_ui_update.py, which needs a browser.
"""

import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from craft_conductor import cli, notice, rollback, selfupdate
from craft_conductor.selfupdate import Updater

from test_notice_update import fresh_user, publish_wheel, release, web_daemon  # noqa: F401  (fixtures and helpers)
from test_hub import login as hub_login
from test_web import login, wait_for

@pytest.fixture(autouse=True)
def stand_in_install(monkeypatch):
    """The installers here are stand-ins: nothing is really installed, so the new version isn't started."""
    monkeypatch.setattr(rollback, "check_new_version", lambda *a, **k: None)


INFO = {"version": "9.9.9", "tag": "v9.9.9", "url": "https://github.test/v9.9.9", "notes": "what's new",
        "current": "0.1.0", "can_install": True, "reason": ""}


# ----------------------------------------------------------------- the state itself
def test_the_updater_starts_once_and_says_where_it_stands():
    u = Updater()
    assert u.snapshot() is None and u.phase == "idle"
    with pytest.raises(LookupError):
        u.begin("9.9.9")  # nothing known to install
    assert u.offer(dict(INFO)) is True and u.offer(dict(INFO)) is False  # (only the first sight is "new")
    assert u.snapshot()["phase"] == "available" and not u.snapshot()["in_progress"]
    with pytest.raises(ValueError):
        u.begin("9.9.8")
    assert u.begin("9.9.9") is True
    assert u.begin("9.9.9") is False  # a second click starts nothing
    snap = u.snapshot()
    assert snap["phase"] == "downloading" and snap["stage"] == "preparing" and snap["in_progress"]
    u.step("downloading", 50, 200)
    assert u.snapshot()["progress"] == {"done": 50, "total": 200}
    u.step("downloading", 60, None)  # (a size nobody knows: no made-up percentage)
    assert "progress" not in u.snapshot()
    u.step("verifying")
    assert u.snapshot()["phase"] == "downloading" and u.snapshot()["stage"] == "verifying"
    u.step("installing")
    assert u.snapshot()["phase"] == "installing"
    u.step("restarting")
    assert u.snapshot()["phase"] == "restarting" and u.begin("9.9.9") is False


def test_what_is_being_installed_is_not_offered_again():
    """The check that runs by itself finds the same release while it installs: that must change nothing."""
    u = Updater()
    u.offer(dict(INFO))
    u.begin("9.9.9")
    u.step("installing")
    assert u.offer(dict(INFO)) is False and u.snapshot()["phase"] == "installing"
    assert u.offer(None) is False and u.snapshot()["phase"] == "installing"  # (a late "nothing newer" can't end it)
    u.forget()
    assert u.snapshot()["phase"] == "installing"


def test_a_failure_leaves_the_update_available_and_kept_for_diagnosis():
    u = Updater()
    u.offer(dict(INFO))
    u.begin("9.9.9")
    u.step("downloading", 1, 2)
    u.fail("the download doesn't match its checksum")
    snap = u.snapshot()
    assert snap["phase"] == "failed" and not snap["in_progress"]       # out of "under way"
    assert snap["error"] and snap["version"] == "9.9.9"               # still there for the red dots
    assert snap["failure"]["message"] == "the download doesn't match its checksum"
    assert any("downloading" in line for line in snap["failure"]["log"])  # what happened, for "View update log"
    assert u.begin("9.9.9") is True                                    # and it can be tried again
    assert u.snapshot()["phase"] == "downloading" and u.snapshot()["error"] == ""


def test_later_lasts_for_this_run_and_only_for_that_version():
    u = Updater()
    u.offer(dict(INFO))
    assert u.snapshot()["deferred"] is False
    assert u.defer("9.9.8") is False and u.defer("9.9.9") is True
    assert u.snapshot()["deferred"] is True and u.snapshot()["version"] == "9.9.9"  # (Later hides no update)
    u.offer(dict(INFO))  # (the daily check finds it again)
    assert u.snapshot()["deferred"] is True
    u.offer({**INFO, "version": "9.9.10", "tag": "v9.9.10"})  # a newer release is new news
    assert u.snapshot()["deferred"] is False
    u.defer()
    u.offer(None)  # (nothing newer any more: nothing to be deferred)
    assert u.snapshot() is None and Updater().snapshot() is None


def test_craft_conductor_starting_again_asks_again():
    """Later is only in memory, so a new run (a new Updater) knows nothing of it."""
    first = Updater()
    first.offer(dict(INFO))
    first.defer("9.9.9")
    assert first.snapshot()["deferred"]
    second = Updater()  # (Craft Conductor exited and started again: its first check finds the update still there)
    assert second.offer(dict(INFO)) is True
    assert second.snapshot()["deferred"] is False and second.snapshot()["phase"] == "available"


# ------------------------------------------------------------- the installer's progress
def test_the_installer_reports_real_progress(monkeypatch, http):
    monkeypatch.setattr(selfupdate, "install_method", lambda release=None: (True, ""))
    seen = []
    r = publish_wheel(http, b"the wheel")
    runner = lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "ok", "")  # noqa: E731
    selfupdate.install(r, runner, http=http, progress=lambda *a: seen.append(a))
    stages = [s for s, _, _ in seen]
    assert stages[0] == "preparing" and stages[-1] == "installing"
    assert stages.index("downloading") < stages.index("verifying") < stages.index("installing")
    assert ("downloading", len(b"the wheel"), len(b"the wheel")) in seen  # (the downloader's own numbers)


def test_a_bad_download_still_installs_nothing(monkeypatch, http):
    """The progress hooks don't loosen the checks: a download that doesn't match its checksum is refused."""
    monkeypatch.setattr(selfupdate, "install_method", lambda release=None: (True, ""))
    r = publish_wheel(http, b"the wheel")
    http.files[r.assets[selfupdate.wheel_name(r)]] = b"someone else's wheel"
    ran = []
    u = Updater()
    u.offer({**r.to_dict(), "current": "0.1.0", "can_install": True, "reason": ""})
    u.begin(r.version)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: ran.append(a))
    with pytest.raises(selfupdate.VerificationError):
        u.run_install(http)
    assert ran == [] and u.snapshot()["phase"] == "failed" and u.release is not None


# ------------------------------------------------------------- the same browser tab
def test_the_restarted_copy_knows_not_to_open_another_tab(monkeypatch):
    """The update restarts `craft-conductor start`, which opens the control panel in a browser: with the page
    already open that was a second tab. The restarted copy is told, once."""
    started = []
    monkeypatch.setattr(selfupdate, "WINDOWS", False)
    monkeypatch.setattr(os, "execve", lambda path, argv, env: started.append(env))
    monkeypatch.setattr(sys, "argv", ["craft-conductor", "start"])
    selfupdate.restart()
    assert started[0][selfupdate.RESTARTED_ENV] == "1"
    monkeypatch.setenv(selfupdate.RESTARTED_ENV, "1")
    assert selfupdate.restarted_after_update() is True
    assert selfupdate.restarted_after_update() is False  # (read once: what it starts later isn't "restarted")


@pytest.mark.parametrize("restarted", [False, True])
def test_start_opens_the_browser_except_after_an_update(tmp_path, monkeypatch, restarted):
    from craft_conductor.hub import Hub
    opened = []
    monkeypatch.setenv("CRAFT_CONDUCTOR_HOME", str(tmp_path / "home"))
    if restarted:
        monkeypatch.setenv(selfupdate.RESTARTED_ENV, "1")
    else:
        monkeypatch.delenv(selfupdate.RESTARTED_ENV, raising=False)
    monkeypatch.setattr(cli, "has_display", lambda: True)
    monkeypatch.setattr(Hub, "run", lambda self: opened.append(self.open_browser) or 0)
    assert cli.main(["-C", str(tmp_path), "start"]) == 0
    assert opened == [not restarted]


# --------------------------------------------------------------------- through the web UI
def test_pressing_update_twice_starts_one_update(web_daemon, monkeypatch):
    d, c, cfg = web_daemon
    notice.accept(cfg.root, by="web")
    login(c)
    d.self_update = dict(INFO)
    release_install, calls = threading.Event(), []

    def slow_install(rel, **kw):
        calls.append(rel.tag)
        kw["progress"]("downloading", 10, 100)
        assert release_install.wait(20)
        kw["progress"]("installing", None, None)
        return f"installed Craft Conductor {rel.version}"
    monkeypatch.setattr(selfupdate, "install", slow_install)

    results = [c.post("/api/self-update/apply", {"version": "9.9.9"}) for _ in range(5)]
    assert [r[0] for r in results] == [200] * 5
    assert [r[1]["started"] for r in results] == [True, False, False, False, False]
    wait_for(lambda: calls)
    wait_for(lambda: c.get("/api/self-update")[1]["self_update"].get("progress"))
    state = c.get("/api/self-update")[1]["self_update"]
    assert state["phase"] == "downloading" and state["in_progress"] and state["progress"] == {"done": 10, "total": 100}
    # the check that runs by itself, and the check button, find nothing new to offer while it installs
    release(d.m.http, "v9.9.9")
    assert "being installed" in d.check_self_update()
    assert c.post("/api/self-update/check")[1]["self_update"]["phase"] == "downloading"
    assert c.post("/api/self-update/apply", {"version": "9.9.9"})[1]["started"] is False
    release_install.set()
    wait_for(lambda: d.restart_requested and d.stop_requested.is_set())
    assert calls == ["v9.9.9"]  # one download, one install
    assert d.updater.snapshot()["phase"] == "restarting"  # (until this copy ends: the new one starts afresh)


def test_a_failed_update_can_be_tried_again(web_daemon, monkeypatch):
    d, c, cfg = web_daemon
    notice.accept(cfg.root, by="web")
    login(c)
    d.self_update = dict(INFO)
    outcomes = [selfupdate.VerificationError("the download doesn't match the release's published checksum"), None]

    def install(rel, **kw):
        kw["progress"]("downloading", 1, 2)
        failure = outcomes.pop(0)
        if failure:
            raise failure
        return f"installed Craft Conductor {rel.version}"
    monkeypatch.setattr(selfupdate, "install", install)
    assert c.post("/api/self-update/apply", {"version": "9.9.9"})[1]["started"] is True
    wait_for(lambda: c.get("/api/self-update")[1]["self_update"]["phase"] == "failed")
    state = c.get("/api/self-update")[1]["self_update"]
    assert "checksum" in state["error"] and state["failure"]["log"]  # useful diagnostics are kept
    assert state["version"] == "9.9.9" and not state["in_progress"]  # still available: the dots stay
    assert not d.restart_requested and not d.stop_requested.is_set()  # no restart, nothing reported as installed
    assert c.get("/api/status")[1]["self_update"]["phase"] == "failed"
    # (what the person sees now is the failure, not the prompt again: the page doesn't offer a failed one by itself)
    assert c.post("/api/self-update/apply", {"version": "9.9.9"})[1]["started"] is True  # Try again
    wait_for(lambda: d.restart_requested)
    assert outcomes == []


def test_later_hides_nothing_but_the_automatic_message(web_daemon, monkeypatch):
    monkeypatch.setattr(selfupdate, "install_method", lambda release=None: (True, ""))
    d, c, cfg = web_daemon
    notice.accept(cfg.root, by="web")
    login(c)
    d.self_update = dict(INFO)
    assert c.get("/api/self-update")[1]["self_update"]["deferred"] is False
    r = c.post("/api/self-update/later", {"version": "9.9.9"})[1]["self_update"]
    assert r["deferred"] is True and r["version"] == "9.9.9" and r["phase"] == "available"
    assert c.get("/api/status")[1]["self_update"]["deferred"] is True  # (the dots read this: still there)
    # the daily check finds the same release: still deferred, still available
    release(d.m.http, "v9.9.9")
    d.check_self_update()
    assert c.get("/api/self-update")[1]["self_update"]["deferred"] is True
    # the check button gives the update back to the person (the page offers it again), without a restart
    checked = c.post("/api/self-update/check")[1]
    assert checked["self_update"]["version"] == "9.9.9" and checked["self_update"]["can_install"]


def test_the_dots_clear_when_nothing_newer_is_found(web_daemon, monkeypatch):
    monkeypatch.setattr(selfupdate, "install_method", lambda release=None: (True, ""))
    d, c, cfg = web_daemon
    notice.accept(cfg.root, by="web")
    login(c)
    d.self_update = {**INFO, "version": "99.0.0", "tag": "v99.0.0"}
    release(d.m.http, "v99.0.0")
    assert c.post("/api/self-update/check")[1]["self_update"]["version"] == "99.0.0"
    release(d.m.http, "v0.0.1")  # (a fresh look: nothing newer than what's running)
    checked = c.post("/api/self-update/check")[1]
    assert checked["self_update"] is None and "latest version" in checked["message"]
    assert c.get("/api/status")[1]["self_update"] is None


def test_the_new_copy_is_known_by_its_version(web_daemon):
    """What the page that asked for the update polls: this copy's version, and whether it is the expected one
    (signed in or not: the restart signs everyone out)."""
    d, c, cfg = web_daemon
    notice.accept(cfg.root, by="web")
    anon = type(c)(c.base)
    auth = anon.get("/api/auth?expected=" + selfupdate.__version__)[1]
    assert auth["version"] == selfupdate.__version__ and auth["matches"] is True
    assert anon.get("/api/auth?expected=99.0.0")[1]["matches"] is False
    assert anon.get("/api/auth")[1]["matches"] is False
    assert anon.get("/api/self-update")[0] == 401  # (the update's details aren't public)
    login(c)
    state = c.get(f"/api/self-update?expected=v{selfupdate.__version__}")[1]
    assert state["version"] == selfupdate.__version__ and state["matches"] is True
    assert c.get("/api/self-update?expected=99.0.0")[1]["matches"] is False
    assert selfupdate.same_version("0.25.0-beta.1", "0.25.0b1") and not selfupdate.same_version("0.25.0", "0.25.0b1")
    assert not selfupdate.same_version("nightly", "nightly")


def test_a_hub_runs_one_update_too(hub_env, monkeypatch):
    hub, c = hub_env
    hub_login(c)
    hub.updater.offer(dict(INFO))
    gate, calls = threading.Event(), []

    def install(rel, **kw):
        calls.append(rel.tag)
        gate.wait(20)
        return "installed"
    monkeypatch.setattr(selfupdate, "install", install)
    first = c.post("/api/self-update/apply", {"version": "9.9.9"})[1]
    second = c.post("/api/self-update/apply", {"version": "9.9.9"})[1]
    assert first["started"] is True and second["started"] is False
    assert c.get("/api/hub")[1]["self_update"]["in_progress"] is True
    gate.set()
    wait_for(lambda: hub.restart_requested)
    assert calls == ["v9.9.9"]


def test_servers_that_ran_start_again_after_an_update(hub_env, http, monkeypatch):
    """Servers running when Craft Conductor updates itself are stopped for it and started again by the
    new version, once the update's guard has let the previous version go; nothing else starts, and a
    note left from long ago starts nothing."""
    import time
    from craft_conductor.hub import START_AFTER_UPDATE, Hub
    from test_manager import manager
    hub, c = hub_env
    hub_login(c)
    alpha = hub.get("alpha")
    assert c.post("/api/servers/alpha/server/start")[0] == 200
    wait_for(lambda: alpha.state == "running", timeout=30)
    hub.updater.offer(dict(INFO))
    monkeypatch.setattr(selfupdate, "install", lambda rel, **kw: "installed")
    assert c.post("/api/self-update/apply", {"version": "9.9.9"})[1]["started"] is True
    wait_for(lambda: hub.restart_requested and not hub._threads["alpha"].is_alive(), timeout=60)
    assert alpha.state == "stopped" and hub._hub_file()[START_AFTER_UPDATE]["servers"] == ["alpha"]

    # The new version starts (the same folder): it waits while the guard is watching it...
    new = Hub(hub.home, make_manager=lambda cfg: manager(cfg, http, ["1.21.1"]), http=http, tick=0.1)
    try:
        new.scan()
        assert rollback.pending(new.state_dir) is not None
        assert new.start_after_update() is True and new.get("alpha").state == "stopped"
        # ...then, once the guard has let the previous version go, starts what was running.
        (new.state_dir / rollback.PENDING).unlink()
        assert new.start_after_update() is False
        wait_for(lambda: new.get("alpha").state == "running", timeout=30)
        assert new.get("main").state == "stopped" and START_AFTER_UPDATE not in new._hub_file()
        new.get("alpha").submit("stop", new.get("alpha").stop_server)
        wait_for(lambda: new.get("alpha").state == "stopped", timeout=60)
        # A note from long ago (Craft Conductor was closed before it got this far) starts nothing.
        new._update_hub_file(lambda d: d.__setitem__(START_AFTER_UPDATE, {"servers": ["alpha"], "at": time.time() - 7200}))
        assert new.start_after_update() is False and START_AFTER_UPDATE not in new._hub_file()
        time.sleep(1)
        assert new.get("alpha").state == "stopped" and new.get("alpha").job is None
    finally:
        new._stop_all()


def test_an_update_that_cannot_install_here_is_refused(web_daemon):
    d, c, cfg = web_daemon
    notice.accept(cfg.root, by="web")
    login(c)
    d.self_update = {**INFO, "can_install": False, "reason": "running from a source checkout"}
    status, body, _ = c.post("/api/self-update/apply", {"version": "9.9.9"})
    assert status == 400 and "source checkout" in body["error"]
    assert d.updater.snapshot()["phase"] == "available"  # (nothing began)


def test_the_update_page_never_opens_a_tab():
    """The update only ever moves the tab that's open: no window.open, and a reload (not a same-address
    replace, which would only move to the #fragment) once the new version answers."""
    app = (Path(__file__).resolve().parents[1] / "src" / "craft_conductor" / "webui" / "app.js").read_text(encoding="utf-8")
    block = app[app.index("// ------------------------------------------------------------ craft-conductor self-update"):
                app.index("// Which versions Craft Conductor offers")]
    assert "window.open" not in block and "target: \"_blank\"" in block  # (only the release notes link)
    assert block.count("_blank") == block.count("noopener noreferrer")
    assert "location.reload()" in block


# ----------------------------------------------------- phones, and every open page, hear how it went
@pytest.fixture
def pushes(hub_env, monkeypatch):
    hub, c = hub_env
    sent = []
    monkeypatch.setattr(hub.push, "notify", lambda title, body, url="/", tag="", kind=None: sent.append((body, url, kind)))
    return hub, c, sent


def test_phones_hear_that_an_update_is_available_once(pushes, monkeypatch):
    hub, c, sent = pushes
    monkeypatch.setattr(selfupdate, "install_method", lambda release=None: (True, ""))
    release(hub.http, "v9.9.9")
    hub.check_self_update()
    hub.check_self_update()  # (the same release again: nothing new to say)
    assert len(sent) == 1
    body, url, kind = sent[0]
    assert "9.9.9 is available" in body and "on your computer" in body and kind == "updates" and url == "/#craft-conductor"


def test_phones_hear_that_the_new_version_is_running(pushes):
    """The copy that an update installed says so once it's up: phones are told (tapping opens it), and the
    page that asked, and every other page, can see how it ended."""
    hub, c, sent = pushes
    hub_login(c)
    rollback.write_pending(hub.state_dir, "0.24.0", selfupdate.__version__, ["craft-conductor", "start"])
    hub.settle_update()
    hub.settle_update()
    assert len(sent) == 1 and f"updated to {selfupdate.__version__}" in sent[0][0] and sent[0][2] == "updates"
    assert rollback.pending(hub.state_dir)["confirmed"]  # (the guard lets the previous version go)
    seen = c.get("/api/hub")[1]["update_result"]
    assert seen["ok"] is True and seen["to"] == selfupdate.__version__ and "announced" not in seen
    anon = type(c)(c.base)
    assert anon.get("/api/auth")[1]["last_update"]["ok"] is True  # (after the restart signs everyone out)


def test_phones_hear_when_an_update_did_not_work(pushes, monkeypatch):
    hub, c, sent = pushes
    hub_login(c)
    hub.updater.offer(dict(INFO))
    monkeypatch.setattr(selfupdate, "install", lambda r, **kw: (_ for _ in ()).throw(
        selfupdate.VerificationError("the download doesn't match the release's published checksum")))
    assert c.post("/api/self-update/apply", {"version": "9.9.9"})[1]["started"] is True
    wait_for(lambda: hub.updater.snapshot()["phase"] == "failed")
    wait_for(lambda: sent)
    body, url, kind = sent[0]
    assert "didn't work" in body and "checksum" in body and kind == "updates"
    result = c.get("/api/hub")[1]["update_result"]
    assert result["ok"] is False and result["to"] == "9.9.9"
    hub.settle_update()
    assert len(sent) == 1  # (already told: not again at the next start)


def test_a_copy_that_was_put_back_tells_everyone(pushes):
    hub, c, sent = pushes
    hub_login(c)
    rollback.record_result(hub.state_dir, False, selfupdate.__version__, "9.9.9",
                           f"The update to 9.9.9 didn't work (the new version didn't start in time); Craft Conductor {selfupdate.__version__} is back",
                           reverted=True)
    hub.settle_update()
    assert len(sent) == 1 and "is back" in sent[0][0] and sent[0][1] == "/#craft-conductor"
    last = type(c)(c.base).get("/api/auth")[1]["last_update"]
    assert last["ok"] is False and last["reverted"] is True
