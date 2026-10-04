"""The Dashboard's Connected Players card in a real browser (optional, like test_ui_browser.py).

    CRAFT_UI_NODE=node CRAFT_UI_PLAYWRIGHT=<path to the playwright package> pytest tests/test_ui_players.py

Players join and leave a fake server while the page is open; the page must keep its rows, heads,
open actions, focus and scroll position, and announce who came and went once.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

from craft_conductor.players import offline_uuid

pytestmark = pytest.mark.skipif(not (os.environ.get("CRAFT_UI_NODE") and os.environ.get("CRAFT_UI_PLAYWRIGHT")),
                                reason="optional browser verification")

PEOPLE = ["Steve", "Alex"] + [f"Player{n:02d}" for n in range(1, 24)]   # 25 players


def test_connected_players_card(hub_env):
    hub, client = hub_env
    assert client.post("/api/login", {"password": "PASSWORD"})[0] == 200
    assert client.post("/api/servers/alpha/server/start")[0] == 200
    daemon = hub.get("alpha")
    from test_web import wait_for
    wait_for(lambda: daemon.state == "running", timeout=30)
    folder = daemon.m.server_dir
    (folder / "server.properties").write_text("max-players=30\n")
    (folder / "ops.json").write_text(json.dumps([{"uuid": offline_uuid("Steve"), "name": "Steve", "level": 4},
                                                 {"uuid": offline_uuid("Alex"), "name": "Alex", "level": 2}]))
    (folder / "whitelist.json").write_text(json.dumps([{"uuid": offline_uuid("Sam"), "name": "Sam"}]))
    (folder / "usercache.json").write_text(json.dumps([{"name": n, "uuid": offline_uuid(n)} for n in ("Sam", "Kit_9")]))
    join = lambda n: daemon._on_line(f"[12:00:00] [Server thread/INFO]: {n} joined the game")  # noqa: E731
    leave = lambda n: daemon._on_line(f"[12:00:05] [Server thread/INFO]: {n} left the game")  # noqa: E731
    for name in PEOPLE:
        join(name)

    # (Minecraft rewrites its own files when it gets these; the fake server doesn't)
    from craft_conductor.properties import write_properties
    real_send = daemon.send_command

    def send(command):
        real_send(command)
        words = command.split()
        if command in ("whitelist on", "whitelist off"):
            write_properties(folder / "server.properties", {"white-list": "true" if command.endswith("on") else "false"})
        elif words[:2] in (["whitelist", "add"], ["whitelist", "remove"]):
            names = [e for e in json.loads((folder / "whitelist.json").read_text()) if e["name"] != words[2]]
            if words[1] == "add":
                names.append({"uuid": offline_uuid(words[2]), "name": words[2]})
            (folder / "whitelist.json").write_text(json.dumps(names))
    daemon.send_command = send
    actions = {"a-player-joins": lambda: join("Zed"), "a-player-leaves": lambda: leave("Zed"),
               "the-open-player-leaves": lambda: leave("Player07")}   # (the 8th row, the one with its actions open)
    node = subprocess.Popen([os.environ["CRAFT_UI_NODE"], str(Path(__file__).with_name("ui_players.cjs")), client.base],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for line in node.stdout:
            if line.startswith("STEP "):
                actions.get(line[5:].strip(), lambda: None)()
                node.stdin.write("\n")
                node.stdin.flush()
            elif line.startswith("OK"):
                break
        assert node.wait(timeout=120) == 0, node.stderr.read()
    finally:
        node.kill()
