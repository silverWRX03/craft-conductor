"""A CurseForge API key saved in craft-conductor settings, checked with CurseForge and used by every server."""

import os

from craft_conductor.http import HttpError
from craft_conductor.mods import curseforge as cf

from test_hub import login

KEY = "$2a$10$abcdefghijklmnopqrstuv"


def test_save_check_and_remove_the_key(hub_env, monkeypatch):
    hub, c = hub_env
    login(c)
    monkeypatch.delenv("CRAFT_CONDUCTOR_CURSEFORGE_API_KEY", raising=False)
    assert c.get("/api/hub/curseforge")[1] == {"set": False, "own": False, "builtin": False}
    url = f"{cf.API}/games/{cf.MINECRAFT_GAME_ID}"
    hub.http.json[url] = HttpError(url, 403, "HTTP 403")
    status, body, _ = c.post("/api/hub/curseforge", {"key": KEY})
    assert status == 400 and "didn't accept" in body["error"]
    assert c.post("/api/hub/curseforge", {"key": "short"})[0] == 400
    hub.http.json[url] = {"data": {"id": 432}}
    assert c.post("/api/hub/curseforge", {"key": KEY})[1]["set"]
    assert os.environ["CRAFT_CONDUCTOR_CURSEFORGE_API_KEY"] == KEY
    assert hub.get("alpha").m.config.curseforge_api_key == KEY  # servers pick it up
    assert c.get("/api/hub/curseforge")[1] == {"set": True, "own": True, "builtin": False}
    assert "curseforge_api_key" in hub._hub_file()
    assert c.post("/api/hub/curseforge", {"key": ""})[1] == {"ok": True, "set": False}
    assert "CRAFT_CONDUCTOR_CURSEFORGE_API_KEY" not in os.environ


def test_a_built_in_key_is_the_fallback(hub_env, monkeypatch):
    """Release builds can carry craft-conductor's own key (like Prism Launcher); a key you enter wins."""
    import sys
    import types
    from craft_conductor.mods import curseforge as cf
    hub, c = hub_env
    login(c)
    monkeypatch.delenv("CRAFT_CONDUCTOR_CURSEFORGE_API_KEY", raising=False)
    assert c.get("/api/hub/curseforge")[1] == {"set": False, "own": False, "builtin": False}
    monkeypatch.setitem(sys.modules, "craft_conductor._buildkeys", types.SimpleNamespace(CURSEFORGE_API_KEY=BUILT_IN))
    cf.use_bundled_key()
    assert c.get("/api/hub/curseforge")[1] == {"set": True, "own": False, "builtin": True}
    hub.http.json[f"{cf.API}/games/{cf.MINECRAFT_GAME_ID}"] = {"data": {"id": 432}}
    assert c.post("/api/hub/curseforge", {"key": KEY})[0] == 200
    assert c.get("/api/hub/curseforge")[1]["own"] and hub.curseforge_key() == KEY
    assert c.post("/api/hub/curseforge", {"key": ""})[0] == 200  # removing yours: back to the built-in one
    assert hub.curseforge_key() == BUILT_IN


BUILT_IN = "$2a$10$builtinbuiltinbuiltinbu"


def test_every_key_entered_is_checked_with_curseforge(hub_env, monkeypatch):
    """Not with a remembered answer to the key checked before it (answers are kept for minutes)."""
    import io
    import pytest
    from craft_conductor.config import ConfigError
    from craft_conductor.http import HttpClient
    hub, _ = hub_env
    monkeypatch.delenv("CRAFT_CONDUCTOR_CURSEFORGE_API_KEY", raising=False)
    client, asked = HttpClient(retries=1), []

    def curseforge(req):  # accepts KEY only, like CurseForge would
        asked.append(req.get_header("X-api-key"))
        if req.get_header("X-api-key") != KEY:
            raise HttpError(req.full_url, 403, "HTTP 403")
        return io.BytesIO(b'{"data": {"id": 432}}')
    monkeypatch.setattr(client, "_open", curseforge)
    monkeypatch.setattr(hub, "http", client)
    hub.save_curseforge_key(KEY)
    with pytest.raises(ConfigError, match="didn't accept"):
        hub.save_curseforge_key(OTHER)
    assert asked == [KEY, OTHER] and hub.curseforge_key() == KEY


def test_secrets_stay_out_of_programs_craft_conductor_starts(tmp_path, monkeypatch):
    """The Minecraft server runs every mod's code, and its environment is theirs to read; the
    installers and launchers aren't ours either."""
    import subprocess
    import sys
    from craft_conductor import desktop
    from craft_conductor.loaders import base
    from craft_conductor.process import ServerProcess
    monkeypatch.setenv("CRAFT_CONDUCTOR_CURSEFORGE_API_KEY", BUILT_IN)
    monkeypatch.setenv("CRAFT_CONDUCTOR_INITIAL_PASSWORD", "first-password-for-the-test")
    monkeypatch.setenv("CRAFT_CONDUCTOR_TEST_SETTING", "kept")  # everything else is passed on
    assert set(desktop.child_env()) == set(os.environ) - set(desktop.SECRET_ENV)

    script = ("import os; print('seen:', sorted(k for k in os.environ if k.startswith('CRAFT_CONDUCTOR_')));"
              "print('[Server thread/INFO]: Done (0.1s)! For help, type \"help\"', flush=True); input()")
    server = ServerProcess([sys.executable, "-c", script], tmp_path, echo=False)
    server.start()
    try:
        assert server.wait_ready(60)
        seen = next(line for line in server.lines if line.startswith("seen:"))
    finally:
        server.proc.kill()
        server.proc.wait()
    assert "CRAFT_CONDUCTOR_TEST_SETTING" in seen
    assert "CURSEFORGE" not in seen and "INITIAL_PASSWORD" not in seen

    envs = []

    def run(cmd, **kw):
        envs.append(kw.get("env"))
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(base.subprocess, "run", run)
    base.run_installer("java", tmp_path / "installer.jar", ["--installServer"], cwd=tmp_path)
    assert envs[0] is not None and "CRAFT_CONDUCTOR_CURSEFORGE_API_KEY" not in envs[0]
    assert envs[0]["CRAFT_CONDUCTOR_TEST_SETTING"] == "kept"


def test_modrinth_needs_no_key_and_never_gets_one(make_config, http, modrinth):
    """Modrinth works with no CurseForge key at all, and a key that is set only goes to CurseForge."""
    from craft_conductor.config import ModSpec
    from test_manager import manager, update
    sent = []
    real = http.get_json

    def recording(url, params=None, headers=None, cache=True):
        sent.append((url, dict(headers or {})))
        return real(url, params, headers, cache)
    http.get_json = recording
    modrinth.project("AAA", "goodmod", "Good Mod")
    modrinth.version("AAA", "1.0", ["1.21.1"])
    for key in ("", KEY):
        cfg = make_config([ModSpec("modrinth", "goodmod")])
        cfg.curseforge_api_key = key
        assert update(manager(cfg, http, ["1.21.1"])).ok
    assert any("modrinth" in url for url, _ in sent)
    assert not [url for url, headers in sent if any(KEY in str(v) for v in headers.values())]


OTHER = "$2a$10$zyxwvutsrqponmlkjihgfe"
