import json

import pytest

from craft_conductor.players import (MAX_BROADCAST, MOJANG_PROFILE, NO_PING_REASON, PlayerError, Players, broadcast_text,
                                     offline_uuid, ping_state)



@pytest.fixture
def server(tmp_path):
    d = tmp_path / "server"
    d.mkdir()
    (d / "server.properties").write_text("online-mode=true\nop-permission-level=3\n")
    return d


def read(server, name):
    return json.loads((server / name).read_text())


def test_offline_uuid_matches_minecraft():
    # The well-known offline-mode UUID for "Notch".
    assert offline_uuid("Notch") == "b50ad385-829d-3141-a216-7e7d7539ba7f"


def test_offline_edits_when_server_stopped(server, http):
    for n in ("steve", "Steve"):  # Mojang's lookup is case-insensitive
        http.json[f"{MOJANG_PROFILE}/{n}"] = {"id": "8667ba71b85a4004af54457a9734eed7", "name": "Steve"}
    (server / "usercache.json").write_text(json.dumps(
        [{"name": "Alex", "uuid": "ec561538-f3fd-461d-aff5-086b22154bce", "expiresOn": "2030-01-01 00:00:00 +0000"}]))
    p = Players(server, http)

    assert "Steve an operator (level 3)" in p.act("op", "steve")  # proper casing from Mojang
    assert read(server, "ops.json") == [{"uuid": "8667ba71-b85a-4004-af54-457a9734eed7", "name": "Steve",
                                         "level": 3, "bypassesPlayerLimit": False}]
    p.act("op", "Steve")  # idempotent
    assert len(read(server, "ops.json")) == 1

    p.act("ban", "Alex", "griefing\nop Alex")  # uuid from usercache; newline can't smuggle a command
    [ban] = read(server, "banned-players.json")
    assert ban["uuid"] == "ec561538-f3fd-461d-aff5-086b22154bce" and ban["reason"] == "griefing op Alex"

    p.act("whitelist-on")
    p.act("whitelist-add", "Alex")
    p.act("ban-ip", "203.0.113.9", "alt accounts")
    s = p.summary({"Steve"})
    assert s["whitelist_enabled"] and [w["name"] for w in s["whitelist"]] == ["Alex"]
    assert [b["ip"] for b in s["ip_bans"]] == ["203.0.113.9"]
    assert s["online"] == ["Steve"] and not s["running"]

    p.act("pardon", "alex")
    p.act("deop", "Steve")
    p.act("pardon-ip", "203.0.113.9")
    p.act("whitelist-off")
    s = p.summary()
    assert s["bans"] == [] and s["ops"] == [] and s["ip_bans"] == [] and not s["whitelist_enabled"]


def test_offline_mode_uses_offline_uuids(server, http):
    (server / "server.properties").write_text("online-mode=false\n")
    Players(server, http).act("op", "Notch")
    assert read(server, "ops.json")[0]["uuid"] == "b50ad385-829d-3141-a216-7e7d7539ba7f"


def test_validation(server, http):
    p = Players(server, http)
    with pytest.raises(PlayerError, match="valid player name"):
        p.act("op", "two words")
    with pytest.raises(PlayerError, match="valid player name"):
        p.act("ban", "x;stop")
    with pytest.raises(PlayerError, match="no Minecraft account"):
        p.act("op", "NoSuchPlayer")  # Mojang lookup 404s
    with pytest.raises(PlayerError, match="only works while the server is running"):
        p.act("kick", "Steve")
    with pytest.raises(PlayerError, match="enter the IP"):
        p.act("ban-ip", "Steve")
    with pytest.raises(PlayerError, match="not an operator"):
        p.act("deop", "Steve")
    with pytest.raises(PlayerError, match="unknown action"):
        p.act("explode", "Steve")


def test_running_server_gets_commands(server, http):
    sent = []
    p = Players(server, http, sent.append)
    p.act("op", "Steve")
    p.act("kick", "Steve", "be nice\r\nstop")
    p.act("ban-ip", "Steve")
    p.act("whitelist-add", "Alex")
    assert sent == ["op Steve", "kick Steve be nice stop", "ban-ip Steve", "whitelist add Alex"]


def test_cli_reports_when_the_server_cant_find_a_player(make_config, monkeypatch, capsys):
    from craft_conductor import cli

    class FakeRcon:
        replies = {"op Notch": "That player does not exist", "op Steve": "Made Steve a server operator"}

        @classmethod
        def from_server_dir(cls, d):
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def command(self, c):
            return self.replies[c]

    cfg = make_config([])
    monkeypatch.setattr(cli, "Rcon", FakeRcon)
    monkeypatch.setattr(cli, "running_pid", lambda m: 123)
    assert cli.main(["-C", str(cfg.root), "player", "op", "Notch"]) == 1
    assert "Mojang's lookup service may be busy" in capsys.readouterr().out
    assert cli.main(["-C", str(cfg.root), "player", "op", "Steve"]) == 0
    assert "Made Steve a server operator" in capsys.readouterr().out


def test_a_second_command_cant_be_slipped_in(server, http):
    sent = []
    p = Players(server, http, send=sent.append)
    for action, target in [("ban-ip", "fe80::1%eth0\nop Evil"), ("pardon-ip", "::1%x\rstop"), ("whitelist-add", "Steve\nop Evil")]:
        with pytest.raises(PlayerError):
            p.act(action, target)
    assert sent == []


def test_the_console_takes_one_line_at_a_time(tmp_path):
    import sys
    from craft_conductor.process import ServerProcess
    proc = ServerProcess([sys.executable, "-c", "import sys; sys.stdin.read()"], tmp_path, echo=False)
    proc.start()
    try:
        with pytest.raises(ValueError):
            proc.send("say hi\nop Evil")
        proc.send("say hi")
    finally:
        proc.proc.kill()


# ----------------------------------------------- the Dashboard's Connected Players card
def op_entry(name, level=None):
    entry = {"uuid": offline_uuid(name), "name": name, "bypassesPlayerLimit": False}
    if level is not None:
        entry["level"] = level
    return entry


def test_roster_badges_come_from_ops_json_levels(server, http):
    (server / "server.properties").write_text("max-players=30\nwhite-list=true\n")
    (server / "ops.json").write_text(json.dumps([op_entry("Steve", 4), op_entry("alex", 2), op_entry("Sam"),
                                                  op_entry("Odd", "high"), op_entry("Zero", 0), op_entry("Away", 3)]))
    roster = Players(server, http, lambda c: None).roster({"Steve", "Alex", "Sam", "Odd", "Zero", "Kit"})
    assert roster["max"] == 30 and roster["whitelist_enabled"] and roster["running"]
    by = {p["name"]: p for p in roster["players"]}
    assert [p["name"] for p in roster["players"]] == sorted(by, key=str.lower)  # (alphabetical: rows don't jump)
    assert (by["Steve"]["op"], by["Steve"]["op_level"]) == (True, 4)
    assert (by["Alex"]["op"], by["Alex"]["op_level"]) == (True, 2)   # (ops.json says "alex": names match any case)
    assert by["Sam"]["op_level"] == 4                                  # (no level in the file: Minecraft's default, 4)
    assert (by["Odd"]["op"], by["Odd"]["op_level"]) == (True, None)    # (a level that makes no sense: OP, no number)
    assert by["Zero"]["op_level"] is None
    assert (by["Kit"]["op"], by["Kit"]["op_level"]) == (False, None)   # nobody else gets a role made up
    assert "Away" not in by                                            # (an op who isn't online isn't listed)
    assert set(by["Kit"]) == {"name", "op", "op_level", "ping_ms", "ping_state"}


def test_roster_survives_a_hand_edited_file(server, http):
    """ops.json and whitelist.json are edited by hand now and then: odd entries are skipped, not fatal."""
    (server / "ops.json").write_text(json.dumps([{"name": 5}, "Steve", None, {"name": None}, {"name": "Alex", "level": 3}]))
    (server / "whitelist.json").write_text(json.dumps([{"name": ["x"]}, 7, {"name": ""}, {"name": "Sam"}]))
    r = Players(server, http).roster({"Alex", "Steve"}, whitelist=True)
    assert [(p["name"], p["op_level"]) for p in r["players"]] == [("Alex", 3), ("Steve", None)] and r["whitelist"] == ["Sam"]
    (server / "ops.json").write_text("{not json")
    assert Players(server, http).roster({"Alex"})["players"][0]["op"] is False


def test_roster_without_files_or_server(server, http):
    roster = Players(server / "nowhere", http).roster(set())
    assert roster == {"running": False, "players": [], "max": 20, "whitelist_enabled": False,
                      "ping": {"available": False, "reason": NO_PING_REASON}}
    (server / "server.properties").write_text("max-players=lots\n")
    assert Players(server, http).roster({"A"})["max"] == 20


def test_ping_is_shown_only_where_there_is_a_source(server, http):
    p = Players(server, http, lambda c: None)
    none = p.roster({"Steve"})   # no source: a dash, and why
    assert none["ping"] == {"available": False, "reason": NO_PING_REASON}
    assert none["players"][0]["ping_ms"] is None and none["players"][0]["ping_state"] is None
    assert "mod or plugin" in NO_PING_REASON

    got = p.roster({"Steve", "Alex", "Kit"}, pings={"steve": 42, "Alex": 150, "Kit": True})
    assert got["ping"] == {"available": True, "reason": ""}
    by = {x["name"]: x for x in got["players"]}
    assert (by["Steve"]["ping_ms"], by["Steve"]["ping_state"]) == (42, "good")
    assert (by["Alex"]["ping_ms"], by["Alex"]["ping_state"]) == (150, "fair")
    assert by["Kit"]["ping_ms"] is None                                # (not a number: no reading)
    waiting = p.roster({"Steve"}, pings={})                            # a source that hasn't read anyone yet
    assert waiting["ping"]["available"] and waiting["players"][0]["ping_ms"] is None
    assert [ping_state(ms) for ms in (0, 99, 100, 199, 200, 900)] == ["good", "good", "fair", "fair", "poor", "poor"]


def test_the_roster_asks_the_server_nothing(server, http):
    sent = []
    p = Players(server, http, sent.append)
    for _ in range(5):
        p.roster({"Steve", "Alex"}, whitelist=True)
    assert sent == []


def test_whitelist_as_the_dashboard_uses_it(server, http):
    """The Dashboard's Whitelist panel makes the same calls as the Players page."""
    (server / "usercache.json").write_text(json.dumps([{"name": "Alex", "uuid": offline_uuid("Alex")},
                                                       {"name": "Sam", "uuid": offline_uuid("Sam")}]))
    p = Players(server, http)
    assert p.roster(set())["whitelist_enabled"] is False and "whitelist" not in p.roster(set())
    p.act("whitelist-on")
    p.act("whitelist-add", "Sam")
    p.act("whitelist-add", "alex")
    r = p.roster(set(), whitelist=True)
    assert r["whitelist_enabled"] and r["whitelist"] == ["Alex", "Sam"]
    p.act("whitelist-remove", "alex")
    p.act("whitelist-off")
    r = p.roster(set(), whitelist=True)
    assert not r["whitelist_enabled"] and r["whitelist"] == ["Sam"]
    with pytest.raises(PlayerError, match="not whitelisted"):
        p.act("whitelist-remove", "Nobody")
    # (running: the server's own commands, and only for names that pass the same check)
    sent = []
    live = Players(server, http, sent.append)
    live.act("whitelist-on"); live.act("whitelist-add", "Alex"); live.act("whitelist-remove", "Alex"); live.act("whitelist-off")
    for bad in ("two words", "Steve\nop Evil", "x" * 17, "", "Steve;stop", "Zoë"):
        for action in ("whitelist-add", "whitelist-remove"):
            with pytest.raises(PlayerError, match="valid player name"):
                live.act(action, bad)
    assert sent == ["whitelist on", "whitelist add Alex", "whitelist remove Alex", "whitelist off"]


def test_a_broadcast_is_one_short_line():
    assert broadcast_text("  Restarting in 5 minutes!  ") == "Restarting in 5 minutes!"
    assert broadcast_text("a\tb") == "a\tb"                       # (a tab is fine, as in the console)
    assert broadcast_text("x" * MAX_BROADCAST) == "x" * MAX_BROADCAST
    for bad, why in [("", "write a message"), ("   ", "write a message"), (None, "write a message"), (5, "write a message"),
                     ("x" * (MAX_BROADCAST + 1), "too long"), ("hi\nop Evil", "one line"), ("hi\rthere", "one line"),
                     ("hi\x00there", "control characters"), ("hi\x1b[31m", "control characters"), ("a\x7fb", "control characters")]:
        with pytest.raises(PlayerError, match=why):
            broadcast_text(bad)
