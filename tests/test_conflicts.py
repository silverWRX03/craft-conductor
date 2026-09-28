"""Mod conflict memory: what's shared (ids only, opted in) and the warnings from the shared list."""

import json
import time

from mcsm import conflicts


RESULT = {"bisected": True, "working": ["sodium", "lithium", "fabric-api"],
          "outliers": [{"id": "BadMod", "source": "modrinth", "suspect_ids": ["sodium", "not-tested", "badmod"]},
                       {"id": "my-local.jar", "source": "local"}, {"id": "broken", "source": "modrinth"}]}


def test_reports_hold_only_ids_and_versions():
    reports = conflicts.reports_for("Fabric", "1.21.1", RESULT)
    assert reports == [{"loader": "fabric", "minecraft": "1.21.1", "mod": "badmod", "with": ["sodium"]},
                       {"loader": "fabric", "minecraft": "1.21.1", "mod": "broken", "with": []}]
    assert conflicts.reports_for("fabric", "1.21.1", {**RESULT, "bisected": False}) == []
    assert conflicts.reports_for("evil", "1.21.1", RESULT) == []


def test_sharing_goes_to_the_relay_only_when_there_is_one(monkeypatch):
    sent = []
    http = type("H", (), {"post_json": lambda self, url, body: sent.append((url, body))})()
    monkeypatch.setattr(conflicts, "RELAY", "")
    monkeypatch.delenv("MCSM_CONFLICTS_URL", raising=False)
    assert conflicts.share(http, conflicts.reports_for("fabric", "1.21.1", RESULT)) == 0
    monkeypatch.setenv("MCSM_CONFLICTS_URL", "https://relay.test/")
    assert conflicts.share(http, conflicts.reports_for("fabric", "1.21.1", RESULT)) == 2
    assert sent[0][0] == "https://relay.test/report"
    monkeypatch.setenv("MCSM_CONFLICTS_URL", "http://insecure.test")
    assert conflicts.relay_url() == ""


def test_the_shared_list_warns_about_mods_used_together(tmp_path, monkeypatch):
    monkeypatch.setenv("MCSM_CONFLICTS_URL", "https://relay.test")
    listing = {"conflicts": [{"loader": "fabric", "minecraft": "1.21.1", "mod": "badmod", "with": ["sodium"], "reports": 4},
                             {"loader": "fabric", "minecraft": "1.21.1", "mod": "broken", "with": [], "reports": 3}]}
    http = type("H", (), {"get_json": lambda self, url, cache=True: listing})()
    known = conflicts.Known(tmp_path, http)
    known.refresh()
    assert [c["mod"] for c in known.matching("fabric", "1.21.1", ["BadMod", "sodium"])] == ["badmod"]
    assert known.matching("fabric", "1.21.1", ["badmod"]) == []  # without its partner, fine
    assert known.matching("fabric", "1.21.4", ["badmod", "sodium", "broken"]) == []  # other versions: not known
    assert json.loads((tmp_path / conflicts.FILE).read_text())["conflicts"] == listing["conflicts"]
    fresh = conflicts.Known(tmp_path, None)  # read back from the file; no fetch while it's fresh
    assert [c["mod"] for c in fresh.matching("fabric", "1.21.1", ["broken"])] == ["broken"]


def test_the_setting_is_off_until_switched_on(hub_env, monkeypatch):
    from test_hub import login
    hub, c = hub_env
    login(c)
    monkeypatch.setattr(conflicts, "RELAY", "https://relay.test")
    assert c.get("/api/hub/conflicts")[1] == {"enabled": False, "available": True, "relay": "https://relay.test"}
    assert c.post("/api/hub/conflicts", {"enabled": True})[1]["enabled"] is True and hub.share_conflicts()
    assert "known_conflicts" in c.get("/api/servers/alpha/mods")[1]
