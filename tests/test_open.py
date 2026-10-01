"""'Open folder' buttons: only on the server's own computer, only craft-conductor's own folders."""

from craft_conductor import opener

from test_hub import login
from test_web import wait_for


def test_open_folders(hub_env, monkeypatch):
    hub, c = hub_env
    login(c)
    opened = []
    monkeypatch.setattr(opener, "open_path", lambda p: opened.append(p) or True)
    assert c.get("/api/hub")[1]["local"] is True

    d = hub.get("alpha")
    assert c.post("/api/servers/alpha/open", {"what": "mods"})[0] == 200
    assert opened[-1] == d.m.server_dir / "mods"
    assert c.post("/api/servers/alpha/open", {"what": "backups"})[0] == 200
    assert opened[-1] == d.m.config.backups.dir and opened[-1].is_dir()  # made if missing
    status, body, _ = c.post("/api/servers/alpha/open", {"what": "world"})
    assert status == 404 and "doesn't exist yet" in body["error"]  # never run
    assert c.post("/api/servers/alpha/open", {"what": "/etc"})[0] == 400
    assert c.post("/api/servers/alpha/open", {"what": "../.."})[0] == 400
    assert c.post("/api/hub/open", {"what": "home"})[0] == 200 and opened[-1] == hub.home

    # Through a proxy (or from another device), there's no screen to open it on.
    before = len(opened)
    via_proxy = {"X-Forwarded-For": "203.0.113.9"}
    assert c.post("/api/servers/alpha/open", {"what": "mods"}, headers=via_proxy)[0] == 403
    assert c.post("/api/hub/open", {"what": "home"}, headers=via_proxy)[0] == 403
    assert len(opened) == before


def test_play_on_this_computer(hub_env, monkeypatch):
    """Play on this computer: the numbers for the warning, then Minecraft's setup page (the
    friends' one, pointed at localhost). Only in a browser on the server's own computer."""
    import webbrowser
    from craft_conductor import clientpack, joinui
    from test_friends import pack
    hub, c = hub_env
    login(c)
    info = c.get("/api/servers/alpha/play-here")[1]
    assert info["installed"] is True and info["server_gb"] == 4 and info["game_gb"] == 4 and info["cpus"] >= 1
    built = []
    monkeypatch.setattr(clientpack.PackBuilder, "build", lambda self, address: built.append(address) or pack())
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)
    monkeypatch.setattr(joinui, "_running_file", lambda mc: hub.home / "join-running.json")
    status, body, _ = c.post("/api/servers/alpha/play-here", {})
    try:
        assert status == 200 and body["url"].startswith("http://127.0.0.1:")
        assert built == ["localhost"]  # this computer's Minecraft joins at localhost
        wait_for(lambda: opened)
        assert c.post("/api/servers/alpha/play-here", {})[1]["url"] == body["url"]  # pressed again: the same page
        assert len(built) == 1
        away = {"X-Forwarded-For": "203.0.113.9"}
        assert c.call("GET", "/api/servers/alpha/play-here", headers=away)[0] == 403
        assert c.post("/api/servers/alpha/play-here", {}, headers=away)[0] == 403
    finally:
        hub._play_ui.done.set()
        hub._play_ui.stop()
