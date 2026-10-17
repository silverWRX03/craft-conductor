"""The website demo's simulated backend (site/demo/app/sim/) against the real one: it must answer every
request the control panel makes, with the same shape of answer.

The real Craft Conductor is started with the example servers of the manual's pictures (example_hub.py)
and asked every GET route it has; the simulation (run by demo_contract.cjs, without a browser) is asked
the same, on its "existing server" demo. Each key the real answer has must be in the simulation's, with
the same kind of value: a page that reads a field the demo doesn't give would break in the demo. A
new route the page calls, or a new field in an answer, fails here until the simulation learns it.
Nothing is stored: answers are compared as they come (they hold paths of this computer).
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from example_hub import example_hub
from test_web import Client

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import check_demo_contract as contract  # noqa: E402
sys.path.pop(0)

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "site" / "demo" / "app" / "sim"
APP = ROOT / "src" / "craft_conductor" / "webui" / "app.js"
NODE = os.environ.get("CRAFT_UI_NODE") or shutil.which("node")
needs_node = pytest.mark.skipif(not NODE, reason="needs Node.js (the simulation is JavaScript)")
# The example servers -> the demo's own.
SERVERS = {"survival": "family-survival", "creative": "creative-builds", "adventure": "modded-adventure"}
# GET routes not compared: pictures and downloads (sent by the request handler, not JSON), and ones
# that only answer about something started a moment before (a check, a map, a test boot).
NOT_JSON = {"/api/players/skin", "/api/doctor/report", "/api/modsets/export", "/api/export/download", "/api/hub/preview/map",
            "/api/hub/map/tile"}
NEEDS_A_JOB = {"/api/hub/mods/check", "/api/hub/trial", "/api/hub/preview", "/api/hub/preview/gallery", "/api/hub/map",
               "/api/hub/map/biome", "/api/hub/map/poi", "/api/backups/changes", "/api/configs/file"}
# Asked with what they need (the page always sends these).
QUERIES = {"/api/hub/mods/requires": "?id=lithium&loader=fabric&version=1.21.1", "/api/hub/mods/versions": "?key=modrinth%3Alithium&loader=fabric&minecraft=1.21.1",
           "/api/hub/browse/search": "?type=mod&q=&loader=fabric&version=1.21.1", "/api/hub/browse/project": "?id=lithium",
           "/api/hub/setup/newest": "?loader=fabric", "/api/hub/port": "?port=25570", "/api/hub/singleplayer/versions": "?loader=fabric&key=modrinth%3Alithium",
           "/api/mods/versions": "?key=modrinth%3Alithium", "/api/mods/requires": "?id=lithium", "/api/browse/search": "?type=mod&q=",
           "/api/browse/project": "?id=lithium", "/api/players/online": "?whitelist=1", "/api/console": "?since=0", "/api/events": "?since=0",
           "/api/hub/memory": "?adding=survival", "/api/client/search": "?q=minimap", "/api/mods/search": "?q=lith"}
# Answers that need an outside service (Modrinth's categories, Discord) fail in the real test too.
OUTSIDE = {"/api/hub/browse/categories", "/api/browse/categories", "/api/hub/discord/guilds", "/api/hub/discord/channels",
           "/api/hub/discord/roles", "/api/bedrock/check"}


def renamed(x):
    """The example servers' ids, where they are keys (people's grants per server), as the demo's."""
    if isinstance(x, dict):
        return {SERVERS.get(k, k): renamed(v) for k, v in x.items()}
    return [renamed(v) for v in x] if isinstance(x, list) else x


def shape_problems(real, demo, where="") -> list[str]:
    """What the demo's answer lacks of the real one's shape (null on either side matches anything)."""
    if real is None or demo is None:
        return []
    if isinstance(real, bool) or isinstance(demo, bool):
        return [] if isinstance(real, bool) and isinstance(demo, bool) else [f"{where}: {type(real).__name__} in the real answer, {type(demo).__name__} in the demo's"]
    if isinstance(real, (int, float)) and isinstance(demo, (int, float)):
        return []
    if type(real) is not type(demo):
        return [f"{where}: {type(real).__name__} in the real answer, {type(demo).__name__} in the demo's"]
    if isinstance(real, dict):
        out = []
        if where.endswith(".links"):  # (a mod's own links: whichever its page has)
            return out
        for k, v in real.items():
            if k not in demo:
                out.append(f"{where}.{k}: missing in the demo's answer")
            else:
                out += shape_problems(v, demo[k], f"{where}.{k}")
        return out
    if isinstance(real, list) and real and demo:
        merged = {}
        for item in real:  # (the keys any real item has, against the demo's first)
            if isinstance(item, dict):
                merged.update({k: v for k, v in item.items() if v is not None or k not in merged})
        return shape_problems(merged if merged else real[0], demo[0], where + "[]")
    return []


class Demo:
    """The simulation, in Node: ask(method, path, body) -> (status, answer)."""

    def __init__(self, catalog: Path, scenario: str = "existing"):
        self.p = subprocess.Popen([NODE, str(Path(__file__).with_name("demo_contract.cjs")), str(catalog), scenario],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        self.unhandled = []

    def ask(self, method, path, body=None, advance=0):
        self.p.stdin.write(json.dumps({"method": method, "path": path, "body": body or {}, "advance": advance}) + "\n")
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        if not line:
            raise AssertionError("the simulation stopped: " + self.p.stderr.read())
        r = json.loads(line)
        self.unhandled += r["unhandled"]
        return r["status"], r["body"]

    def close(self):
        self.p.stdin.close()
        self.p.wait(10)


@pytest.fixture(scope="module")
def catalog(tmp_path_factory):
    """Craft Conductor's own texts for the simulation, made the way the website build makes them."""
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import build_website
    finally:
        sys.path.pop(0)
    data = {**build_website.release_catalog(ROOT / "src"), "version": "test", "channel": "development",
            "qr": {"invite": "<svg/>", "pair": "<svg/>"}, "links": build_website.DEMO_LINKS}
    path = tmp_path_factory.mktemp("demo") / "catalog-release.js"
    path.write_text("window.CC_DEMO_RELEASE = " + json.dumps(data) + ";\n", encoding="utf-8")
    return path


def test_every_address_the_panel_calls_is_simulated():
    """Each /api/ address in app.js has an answer in the simulation (by any method)."""
    assert len(contract.app_paths(APP.read_text(encoding="utf-8"))) > 150
    gaps = contract.missing(APP.read_text(encoding="utf-8"))
    assert not gaps, "the website demo doesn't answer: " + ", ".join(gaps)


def test_every_real_route_is_simulated(hub_env):
    """Each route of the real API is known to the simulation (or deliberately left out above)."""
    hub, _ = hub_env
    real = {p for _, p in hub.ui.hub_api.routes} | {p for _, p in hub.ui.api_for("alpha").routes}
    missing = sorted(p for p in real - contract.demo_paths() if p not in NOT_JSON)
    assert not missing, "routes the website demo doesn't simulate: " + ", ".join(missing)


@needs_node
def test_the_demo_answers_like_the_real_api(tmp_path, http, modrinth, fake_java, monkeypatch, catalog):
    from craft_conductor import world
    monkeypatch.setattr(world, "list_saves", lambda *a, **k: [  # (not this computer's own Minecraft saves)
        {"id": "w1", "folder": "Island", "name": "Island", "version": "1.21.1", "hardcore": False, "launcher": "Minecraft Launcher",
         "played": 0.0, "path": str(tmp_path / "saves" / "Island"), "icon": ""}])
    demo = Demo(catalog)
    problems, compared = [], 0
    try:
        with example_hub(tmp_path, http, modrinth, fake_java, monkeypatch) as hub:
            c = Client(hub.ui.url.rstrip("/"))
            assert c.post("/api/login", {"password": "PASSWORD"})[0] == 200
            assert c.post("/api/auth/change", {"mode": "password", "secret": "Creeper-Proof-42"})[0] == 200
            asks = [("/api/auth", "/api/auth"), ("/api/notice", "/api/notice"), ("/api/account", "/api/account"),
                    ("/api/self-update", "/api/self-update")]
            asks += [(p + QUERIES.get(p, ""), p + QUERIES.get(p, "")) for m, p in sorted(hub.ui.hub_api.routes)
                     if m == "GET" and p not in NOT_JSON | NEEDS_A_JOB | OUTSIDE]
            for real_id, demo_id in SERVERS.items():
                for m, p in sorted(hub.ui.api_for(real_id).routes):
                    if m == "GET" and p not in NOT_JSON | NEEDS_A_JOB | OUTSIDE:
                        q = QUERIES.get(p, "")
                        asks.append((f"/api/servers/{real_id}/{p[5:]}{q}", f"/api/servers/{demo_id}/{p[5:]}{q}"))
            for real_path, demo_path in asks:
                status, real = c.get(real_path)[:2]
                if status != 200 or not isinstance(real, (dict, list)):
                    continue  # (the real one couldn't answer either: an outside service, or nothing there)
                d_status, answer = demo.ask("GET", demo_path)
                compared += 1
                if d_status != 200:
                    problems.append(f"{demo_path}: the demo answered {d_status}: {answer}")
                    continue
                problems += [f"{demo_path}{x}" for x in shape_problems(renamed(real), answer)]
    finally:
        demo.close()
    assert compared > 80, f"only {compared} answers were compared"
    assert not demo.unhandled, demo.unhandled
    assert not problems, f"{len(problems)} difference(s) from the real API:\n" + "\n".join(problems)


@needs_node
def test_the_demo_survives_a_visit(catalog):
    """A short visit to both demos: making a server, starting it, a friend joining, a backup and an update."""
    for scenario in ("new", "existing"):
        demo = Demo(catalog, scenario)
        try:
            if scenario == "new":
                assert demo.ask("GET", "/api/hub")[1]["servers"] == []
                s, r = demo.ask("POST", "/api/hub/create", {"loader": "fabric", "minecraft": "1.21.1", "motd": "Family Survival",
                                                             "mods": ["lithium", "simple-voice-chat"], "accept_eula": True, "port": 25565})
                assert s == 200 and r["id"] == "family-survival", r
                sid = r["id"]
                assert demo.ask("GET", f"/api/servers/{sid}/status", advance=10)[1]["setup_pending"] is False
                assert demo.ask("POST", f"/api/servers/{sid}/server/start")[0] == 200
                st = demo.ask("GET", f"/api/servers/{sid}/status", advance=25)[1]
                assert st["state"] == "running" and "Alex" in st["players"], st
                req = demo.ask("GET", f"/api/servers/{sid}/join-requests")[1]["requests"]
                assert [x["name"] for x in req] == ["Sam_Builds"]
                assert demo.ask("POST", f"/api/servers/{sid}/join-requests/answer", {"name": "Sam_Builds", "allow": True})[0] == 200
                st = demo.ask("GET", f"/api/servers/{sid}/status", advance=4)[1]
                assert "Sam_Builds" in st["players"]
                hub = demo.ask("GET", "/api/hub")[1]
                assert hub["servers"][0]["players"] == len(st["players"]) and hub["servers"][0]["join_requests"] == 0
            else:
                sid = "family-survival"
                assert demo.ask("POST", f"/api/servers/{sid}/backups/create", {"label": "test"})[0] == 200
                names = [b["name"] for b in demo.ask("GET", f"/api/servers/{sid}/backups", advance=4)[1]["backups"]]
                assert names[0].endswith("-test.tar.gz")
                c = demo.ask("GET", f"/api/servers/{sid}/updates")[1]["check"]
                assert not c["up_to_date"] and c["target"] == "1.21.1" and c["lagging"]["version"] == "1.21.4"
                assert demo.ask("POST", f"/api/servers/{sid}/updates/apply", {"target": "1.21.1"})[0] == 200
                st = demo.ask("GET", f"/api/servers/{sid}/status", advance=12)[1]
                assert st["last_job"]["name"] == "update" and st["last_job"]["ok"], st["last_job"]
                assert demo.ask("GET", f"/api/servers/{sid}/updates")[1]["check"]["up_to_date"]
            assert not demo.unhandled, demo.unhandled
        finally:
            demo.close()
