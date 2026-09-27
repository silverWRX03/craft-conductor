"""World tools: game rules (either spelling), the world border and Chunky, through the server's
own commands."""

import pytest

from mcsm import worldtools

from test_hub import login


class FakeServer:
    """Answers like Minecraft: knows rules by one spelling."""
    running = True

    def __init__(self, snake=False, answers=True):
        self.snake, self.answers, self.sent = snake, answers, []
        self.rules = {"keepInventory": "false", "playersSleepingPercentage": "100"}

    def ask(self, command, parse, timeout=5):
        self.sent.append(command)
        if not self.answers:
            return None
        name = command.split()[-1]
        known = {(worldtools.snake(k) if self.snake else k): v for k, v in self.rules.items()}
        if command == "worldborder get":
            return parse(["The world border is currently 59999968 block(s) wide"])
        if name in known:
            return parse([f"Gamerule {name} is currently set to: {known[name]}"])
        return parse([f"Incorrect argument for command at position 9: gamerule <--[HERE]"])

    def send(self, command):
        self.sent.append(command)


def test_rules_in_either_spelling():
    old = worldtools.read_rules(FakeServer())
    assert {r["id"]: r["value"] for r in old} == {"keepInventory": "false", "playersSleepingPercentage": "100"}
    new = FakeServer(snake=True)
    got = worldtools.read_rules(new)
    assert {r["id"] for r in got} == {"keep_inventory", "players_sleeping_percentage"}
    assert "gamerule players_sleeping_percentage" in new.sent and "gamerule playersSleepingPercentage" not in new.sent  # the style is learnt
    silent = FakeServer(answers=False)
    assert worldtools.read_rules(silent) == [] and len(silent.sent) == 1  # not answering: asked once


def test_setting_things_is_checked():
    s = FakeServer()
    assert worldtools.set_rule(s, "keepInventory", "true") == "keepInventory set to true"
    for rule, value in (("keep Inventory", "true"), ("keepInventory", "yes; op me"), ("x", "1")):
        with pytest.raises(ValueError):
            worldtools.set_rule(s, rule, value)
    worldtools.set_border(s, 10000, 100, -50)
    assert s.sent[-2:] == ["worldborder center 100 -50", "worldborder set 10000"]
    with pytest.raises(ValueError):
        worldtools.set_border(s, 5)
    assert worldtools.border_size(FakeServer()) == 59999968
    worldtools.chunky_start(s, 2500)
    assert "chunky radius 2500" in s.sent and "chunky start" in s.sent
    with pytest.raises(ValueError):
        worldtools.chunky_start(s, 10)
    assert worldtools.chunky_progress(["[Chunky] Task running for minecraft:overworld. Processed: 5,000 chunks (12.50%), ETA: 1:00:00"])["percent"] == 12.5
    assert worldtools.chunky_progress(["[Chunky] Task finished for minecraft:overworld."])["running"] is False


def test_the_endpoints(hub_env):
    hub, c = hub_env
    login(c)
    assert c.get("/api/servers/alpha/world/tools")[1] == {"running": False, "chunky": False}
    assert c.post("/api/servers/alpha/world/rule", {"rule": "keepInventory", "value": "true"})[0] == 409  # stopped
    assert c.post("/api/servers/alpha/world/chunky", {"action": "start", "radius": 1000})[0] == 400  # no Chunky
