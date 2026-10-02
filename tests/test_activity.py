"""Player activity: visits noted as players join and leave, and what's worked out from them."""

import datetime as dt
import json
import time

from craft_conductor.activity import Activity, summarise


def at(day, hour, minute=0):
    """A local time in the week of Monday 1 January 2024."""
    return dt.datetime(2024, 1, day, hour, minute).timestamp()


def test_visits_are_noted_and_survive_a_restart(tmp_path):
    a = Activity(tmp_path)
    a._pruned = time.time()  # (these 2024 visits are older than 90 days: pruning would drop them)
    a.joined("Steve", at(1, 20))
    a.joined("Alex", at(1, 20, 30))
    a.left("Steve", at(1, 22))
    a.left("Nobody", at(1, 22))  # (never seen joining: ignored)
    a.all_left(at(1, 23))       # the server stopped
    rows = [json.loads(x) for x in (tmp_path / "activity.jsonl").read_text().splitlines()]
    assert [(r["name"], r["end"] - r["start"]) for r in rows] == [("Steve", 7200), ("Alex", 9000)]
    again = Activity(tmp_path)
    assert [v["name"] for v in again.visits(at(1, 0), at(2, 0))] == ["Steve", "Alex"]


def test_still_online_counts_up_to_now(tmp_path):
    a = Activity(tmp_path)
    a.joined("Steve", at(1, 20))
    s = a.summary(days=7, now=at(1, 21))
    assert s["players"] == [{"name": "Steve", "seconds": 3600, "visits": 1, "last_seen": at(1, 21), "online": True}]
    assert s["recent"][0]["online"] and not s["enough"]


def test_just_joined_player_is_visible_without_clock_tick(tmp_path):
    """Coarse clocks (notably Windows) can return the same timestamp for join and summary."""
    a = Activity(tmp_path)
    now = time.time()
    a.joined("Steve", now)
    s = a.summary(days=7, now=now)
    assert s["players"] == [{"name": "Steve", "seconds": 0, "visits": 1, "last_seen": now, "online": True}]


def test_the_quietest_hour_and_the_busiest():
    visits = []
    for day in range(1, 8):  # every evening 18:00-23:00, two players; one plays at 3 in the morning too
        visits += [{"name": "Steve", "start": at(day, 18), "end": at(day, 23)},
                   {"name": "Alex", "start": at(day, 19), "end": at(day, 23)},
                   {"name": "Alex", "start": at(day, 3), "end": at(day, 4)}]
    visits.append({"name": "Steve", "start": at(6, 12), "end": at(6, 18)})  # a long Saturday
    s = summarise(sorted(visits, key=lambda v: v["start"]), 30, at(8, 0))
    assert s["enough"]
    assert s["quiet"]["hour"] == 4 and s["quiet"]["average"] == 0 and s["quiet"]["cron"] == "0 4 * * *"
    assert s["week"][0][20] == 2.0 and s["week"][0][18] == 1.0 and s["week"][0][3] == 1.0
    assert s["busiest"]["hour"] in range(19, 23)
    assert s["players"][0]["name"] == "Steve"


def test_the_quietest_hour_prefers_early_morning():
    visits = [{"name": "Steve", "start": at(day, 12), "end": at(day, 13)} for day in range(1, 8)]
    s = summarise(visits, 30, at(8, 0))
    assert s["quiet"]["hour"] == 4  # (every other hour is equally empty)


def test_a_damaged_line_is_skipped(tmp_path):
    (tmp_path / "activity.jsonl").write_text('{"name": "Steve", "start": 10, "end": 20}\n{"name": "Al')
    assert [v["name"] for v in Activity(tmp_path).visits(0, 30)] == ["Steve"]


def test_the_players_page_shows_it(hub_env):
    from test_hub import login
    hub, c = hub_env
    login(c)
    d = hub.get("alpha")
    d._on_line("[12:00:00] [Server thread/INFO]: Steve joined the game")
    status, r, _ = c.get("/api/servers/alpha/players/activity?days=7")
    assert status == 200, r
    assert r["players"][0]["name"] == "Steve" and r["players"][0]["online"]
    assert "schedule_restart" in r
    d._on_line("[12:30:00] [Server thread/INFO]: Steve left the game")
    assert not d.activity.online
