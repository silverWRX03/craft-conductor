"""Recent servers in the left panel: when each server last started, and last had players on."""

import json

from craft_conductor.activity import Activity
from craft_conductor.hub import HUB_FILE


def test_last_played_is_now_while_someone_is_on(tmp_path):
    a = Activity(tmp_path)
    a.joined("Alex", now=100.0)
    assert a.last_played(now=500.0) == 500.0


def test_last_played_is_when_the_last_visit_ended(tmp_path):
    a = Activity(tmp_path)
    a.joined("Alex", now=100.0)
    a.left("Alex", now=200.0)
    a.joined("Steve", now=150.0)
    a.left("Steve", now=300.0)
    assert a.last_played(now=1000.0) == 300.0
    assert Activity(tmp_path).last_played(now=1000.0) == 300.0  # (kept in the file, after a restart)


def test_last_played_is_none_without_visits(tmp_path):
    assert Activity(tmp_path).last_played() is None
    assert Activity(None).last_played() is None


def _summary(hub, sid):
    return next(s for s in hub.summary() if s["id"] == sid)


def test_a_server_that_comes_up_is_noted_as_last_started(hub_env):
    hub, _ = hub_env
    assert _summary(hub, "alpha")["last_started"] is None
    hub.after_ready(hub.get("alpha"))
    started = _summary(hub, "alpha")["last_started"]
    assert isinstance(started, float) and started > 0
    assert _summary(hub, "main")["last_started"] is None
    saved = json.loads((hub.state_dir / HUB_FILE).read_text())
    assert saved["started"]["alpha"] == started
    assert "last_played" in _summary(hub, "alpha")


def test_a_damaged_started_list_is_ignored(hub_env):
    hub, _ = hub_env
    hub._update_hub_file(lambda data: data.update(started=5))
    assert _summary(hub, "alpha")["last_started"] is None
    hub.after_ready(hub.get("alpha"))  # (and replaced by a good one)
    assert _summary(hub, "alpha")["last_started"]


def test_a_removed_server_is_forgotten(hub_env):
    hub, _ = hub_env
    hub.after_ready(hub.get("alpha"))
    hub.delete("alpha", delete_files=False)
    saved = json.loads((hub.state_dir / HUB_FILE).read_text())
    assert "alpha" not in saved.get("started", {})


def test_invited_people_get_what_the_recent_list_and_icon_need():
    from craft_conductor import access
    result = {"servers": [{"id": "alpha", "name": "Alpha", "state": "running", "icon": 123,
                           "last_started": 10.0, "last_played": 20.0, "folder": "C:/secret"}]}
    who = access.Subject("user", "u1", "Sam", grants={"alpha": access.PRESETS["viewer"]})
    s = access.hub_answer(who, result)["servers"][0]
    assert (s["icon"], s["last_started"], s["last_played"]) == (123, 10.0, 20.0)
    assert "folder" not in s or s["folder"] is None


def test_start_times_that_arent_numbers_json_can_send_are_ignored(hub_env):
    """hub.json edited by hand: infinity, NaN or a huge number never breaks the server list (every page)."""
    hub, _ = hub_env
    (hub.state_dir / HUB_FILE).write_text('{"started": {"alpha": 1e999, "main": NaN, "x": 1' + "0" * 400 + '}}')
    hub._started = None
    servers = hub.summary()
    json.dumps(servers, allow_nan=False)
    assert all(s.get("last_started") is None for s in servers)


def test_a_start_that_cant_be_noted_doesnt_stop_the_rest(hub_env, monkeypatch):
    hub, _ = hub_env
    checked = []
    monkeypatch.setattr(hub, "bedrock_both_ways", lambda d: checked.append(d) or False)
    monkeypatch.setattr(hub, "_update_hub_file", lambda change: (_ for _ in ()).throw(RuntimeError("busy")))
    hub.after_ready(hub.get("alpha"))
    assert checked == [hub.get("alpha")]
