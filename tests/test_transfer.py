"""Moving a server to another computer: export to one .zip, import it there."""

import io
import json
import re
import zipfile

import pytest

from craft_conductor import lock as lockmod, transfer
from craft_conductor.properties import read_properties

from test_hub import login
from test_web import wait_for


def test_export_and_import_through_the_web(hub_env):
    hub, c = hub_env
    login(c)
    d = hub.get("alpha")
    world = d.m.server_dir / "world"
    (world / "region").mkdir(parents=True, exist_ok=True)
    (world / "level.dat").write_bytes(b"level")
    (world / "session.lock").write_bytes(b"lock")
    (d.m.server_dir / "logs").mkdir(exist_ok=True)
    (d.m.server_dir / "logs" / "latest.log").write_text("noise")
    (d.m.config.state_dir / "java").mkdir(parents=True, exist_ok=True)

    assert c.post("/api/servers/alpha/export", {"backups": False})[0] == 200
    wait_for(lambda: d.last_job and d.last_job["name"] == "export", timeout=30)
    assert d.last_job["ok"], d.last_job
    exports = c.get("/api/servers/alpha/export")[1]["exports"]
    assert len(exports) == 1 and exports[0]["name"].startswith("Alpha ") and exports[0]["name"].endswith(".craft-conductor.zip")
    status, data, headers = c.get(f"/api/servers/alpha/export/download?name={exports[0]['name'].replace(' ', '%20')}")
    assert status == 200 and "attachment" in headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
    assert {"craft-conductor-export.json", "craft-conductor.toml", "craft-conductor.lock.json", "server/world/level.dat"} <= names
    assert not any(n.startswith(("server/logs/", ".craft-conductor")) or n.endswith("session.lock") for n in names)
    assert c.get("/api/servers/alpha/export/download?name=../craft-conductor.toml")[0] == 404

    # "The other computer": upload the export and import it.
    status, staged, _ = c.call("POST", "/api/hub/stage?filename=alpha.zip", raw=data)
    assert status == 200
    status, body, _ = c.post("/api/hub/import", {"id": staged["id"]})
    assert status == 200, body
    sid = body["id"]
    assert sid == "alpha-2" and body["left_out"] == []  # (no secrets to leave out)
    new = hub.get(sid)
    from craft_conductor.properties import server_name
    names = [server_name(read_properties(x.m.server_dir / "server.properties")) for x in (d, new)]
    assert names[0] and names[1] == f"{names[0]} (2)"  # (two cards with one name are easy to mix up)
    assert (new.m.server_dir / "world" / "level.dat").read_bytes() == b"level"
    assert new.m.lock.minecraft == "1.21.1" and new.m.config.server.dir == new.m.config.root / "server"
    # It used alpha's port, which is taken here, so it got another.
    assert read_properties(new.m.server_dir / "server.properties")["server-port"] != \
        read_properties(d.m.server_dir / "server.properties").get("server-port", "25565")
    assert new.state == "stopped"
    assert c.post("/api/hub/import", {"id": staged["id"]})[0] == 400  # used up

    assert c.post("/api/servers/alpha/export/delete", {"name": exports[0]["name"]})[0] == 200
    assert c.get("/api/servers/alpha/export")[1]["exports"] == []


def test_an_export_leaves_out_the_discord_webhook_and_curseforge_key(hub_env, tmp_path):
    """An export is a file that gets sent around and kept: a Discord webhook or a CurseForge key in
    it would work for anyone who has it. They're left out, and the import says where to enter them
    again. The copy made on this computer to try a beta keeps them."""
    import tomllib
    from craft_conductor import config as configmod
    hub, c = hub_env
    login(c)
    d = hub.get("alpha")
    webhook = "https://discord.com/api/webhooks/0/fake-webhook-for-tests"
    configmod.set_value(d.m.config.path, "notify", "discord_webhook", json.dumps(webhook))
    configmod.set_value(d.m.config.path, "curseforge", "api_key", '"fake-curseforge-key-for-tests"')
    d.m.reload_config()

    path = transfer.export(d.m, tmp_path / "out.zip")
    from test_secrets import access, only_mine
    assert only_mine(path), access(path)  # (it still holds the invite secret and an RCON password: this account's only)
    with zipfile.ZipFile(path) as z:
        settings = z.read("craft-conductor.toml").decode("utf-8")
        manifest = json.loads(z.read("craft-conductor-export.json"))
    assert "fake-webhook" not in settings and "fake-curseforge" not in settings
    parsed = tomllib.loads(settings)
    assert parsed["notify"]["discord_webhook"] == "" and parsed["curseforge"]["api_key"] == ""
    assert parsed["server"]["loader"] == d.m.config.server.loader  # (the rest is as it was)
    assert manifest["left_out"] == ["curseforge_api_key", "discord_webhook"] and manifest["locked"] == []
    assert webhook in d.m.config.path.read_text(encoding="utf-8")  # (the server itself keeps them)

    status, staged, _ = c.call("POST", "/api/hub/stage?filename=alpha.zip", raw=path.read_bytes())
    status, body, _ = c.post("/api/hub/import", {"id": staged["id"]})
    assert status == 200 and body["left_out"] == ["curseforge_api_key", "discord_webhook"]
    imported = hub.get(body["id"]).m.config
    assert imported.discord_webhook == "" and "fake-curseforge" not in imported.path.read_text(encoding="utf-8")

    copy = transfer.export(d.m, tmp_path / "copy.zip", keep_secrets=True)  # (the beta copy)
    with zipfile.ZipFile(copy) as z:
        assert webhook in z.read("craft-conductor.toml").decode("utf-8")
        assert json.loads(z.read("craft-conductor-export.json"))["left_out"] == []


def test_an_export_carries_what_was_chosen_and_locks_the_secrets_chosen(hub_env, tmp_path):
    """The export window: parts can stay behind, and the passwords, keys and IP bans picked to go
    along are locked with a password made for the export; the import asks for it."""
    from craft_conductor import config as configmod, secretzip
    from craft_conductor.properties import read_properties, write_properties
    hub, c = hub_env
    login(c)
    d = hub.get("alpha")
    sd = d.m.server_dir
    (sd / "world" / "region").mkdir(parents=True, exist_ok=True)
    (sd / "world" / "level.dat").write_bytes(b"level")
    (sd / "mods").mkdir(exist_ok=True)
    (sd / "mods" / "lithium.jar").write_bytes(b"jar")
    (sd / "bluemap" / "web").mkdir(parents=True)
    (sd / "bluemap" / "web" / "tile.png").write_bytes(b"tile")
    (sd / "banned-ips.json").write_text('[{"ip": "203.0.113.9", "reason": "test"}]')
    write_properties(sd / "server.properties", {"enable-rcon": "true", "rcon.password": "fake-rcon-password"})
    configmod.set_value(d.m.config.path, "curseforge", "api_key", '"fake-curseforge-key-for-tests"')
    configmod.set_value(d.m.config.path, "notify", "discord_webhook", '"https://discord.com/api/webhooks/0/fake"')
    (d.m.config.root / "client-mods").mkdir(exist_ok=True)
    (d.m.config.root / "client-mods" / "my-own.jar").write_bytes(b"for players")
    d.m.reload_config()
    info = c.get("/api/servers/alpha/export")[1]
    assert {"world", "mods", "maps"} <= set(info["parts"])
    assert set(info["sensitive"]) == {"curseforge_api_key", "discord_webhook", "rcon", "ip_bans"}

    # Everything but the world and the map; the CurseForge key, RCON and the IP bans go along, locked.
    status, body, _ = c.post("/api/servers/alpha/export", {"backups": False, "parts": ["mods", "configs", "players"],
                                                          "secrets": ["curseforge_api_key", "rcon", "ip_bans"]})
    assert status == 200 and re.fullmatch(r"[A-Z2-9]{4}(-[A-Z2-9]{4}){5}", body["password"])
    wait_for(lambda: d.last_job and d.last_job["name"] == "export", timeout=30)
    assert d.last_job["ok"], d.last_job
    assert body["password"] not in json.dumps(d.last_job)  # (only whoever asked sees it)
    name = c.get("/api/servers/alpha/export")[1]["exports"][0]["name"]
    data = c.get(f"/api/servers/alpha/export/download?name={name.replace(' ', '%20')}")[1]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
        manifest = json.loads(z.read("craft-conductor-export.json"))
        locked = secretzip.decrypt(z.read("craft-conductor-locked.zip"), body["password"])
        props = z.read("server/server.properties").decode("latin-1")
        settings = z.read("craft-conductor.toml").decode("utf-8")
    assert "server/mods/lithium.jar" in names and "client-mods/my-own.jar" in names
    assert not any(n.startswith(("server/world/", "server/bluemap/")) for n in names) and "server/banned-ips.json" not in names
    assert "fake-rcon-password" not in props and "fake-curseforge" not in settings and "webhooks" not in settings
    assert manifest["locked"] == ["curseforge_api_key", "ip_bans", "rcon"] and manifest["left_out"] == ["discord_webhook"]
    assert json.loads(locked["secrets.json"]) == {"toml": {"curseforge.api_key": "fake-curseforge-key-for-tests"},
                                                  "properties": {"rcon.password": "fake-rcon-password"}}
    assert b"203.0.113.9" in locked["server/banned-ips.json"]

    # "The other computer": the import asks for the password, and a wrong one changes nothing.
    staged = c.call("POST", "/api/hub/stage?filename=alpha.zip", raw=data)[1]
    first = c.post("/api/hub/import", {"id": staged["id"]})[1]
    assert first["needs_password"] and first["locked"] == ["curseforge_api_key", "ip_bans", "rcon"]
    status, wrong, _ = c.post("/api/hub/import", {"id": staged["id"], "password": "AAAA-AAAA-AAAA-AAAA-AAAA-AAAA"})
    assert status == 400 and "isn't the one" in wrong["error"]
    status, done, _ = c.post("/api/hub/import", {"id": staged["id"], "password": body["password"]})
    assert status == 200 and done["opened"] == ["curseforge_api_key", "ip_bans", "rcon"] and done["left_out"] == ["discord_webhook"]
    new = hub.get(done["id"]).m
    assert new.config.curseforge_api_key == "fake-curseforge-key-for-tests" and new.config.discord_webhook == ""
    assert read_properties(new.server_dir / "server.properties")["rcon.password"] == "fake-rcon-password"
    assert b"203.0.113.9" in (new.server_dir / "banned-ips.json").read_bytes()
    assert (new.server_dir / "mods" / "lithium.jar").is_file() and not (new.server_dir / "world").exists()
    assert (new.config.root / "client-mods" / "my-own.jar").read_bytes() == b"for players"

    # Without the password: everything but the locked part; RCON gets a new password of its own.
    staged = c.call("POST", "/api/hub/stage?filename=alpha.zip", raw=data)[1]
    status, skip, _ = c.post("/api/hub/import", {"id": staged["id"], "skip_locked": True})
    assert status == 200 and skip["opened"] == [] and set(skip["left_out"]) == {"curseforge_api_key", "discord_webhook",
                                                                                "ip_bans", "rcon"}
    other = hub.get(skip["id"]).m
    fresh = read_properties(other.server_dir / "server.properties")["rcon.password"]
    assert fresh and fresh != "fake-rcon-password" and not (other.server_dir / "banned-ips.json").exists()


def zip_with(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_import_is_careful(tmp_path):
    manifest = json.dumps({"format": 1, "name": "X"})
    bad = tmp_path / "bad.zip"
    bad.write_bytes(zip_with({"hello.txt": "hi"}))
    with pytest.raises(transfer.TransferError, match="isn't an Craft Conductor server export"):
        transfer.read_manifest(bad)
    bad.write_bytes(b"not a zip")
    with pytest.raises(transfer.TransferError, match="isn't a .zip"):
        transfer.read_manifest(bad)
    bad.write_bytes(zip_with({"craft-conductor-export.json": json.dumps({"format": 99}), "craft-conductor.toml": ""}))
    with pytest.raises(transfer.TransferError, match="newer Craft Conductor"):
        transfer.read_manifest(bad)

    # Paths outside the server (or craft-conductor's own files) are never written.
    evil = tmp_path / "evil.zip"
    evil.write_bytes(zip_with({"craft-conductor-export.json": manifest, "craft-conductor.toml": '[server]\nloader = "vanilla"\n',
                               "server/../../escaped.txt": "x", "/etc/passwd": "x", ".craft-conductor/web-auth.json": "{}",
                               "server/world/level.dat": "ok"}))
    root = tmp_path / "imported"
    transfer.import_into(evil, root)
    assert (root / "server" / "world" / "level.dat").read_text() == "ok"
    assert not (tmp_path / "escaped.txt").exists() and not (root / ".craft-conductor" / "web-auth.json").exists()
    with pytest.raises(transfer.TransferError, match="isn't empty"):
        transfer.import_into(evil, root)

    # A broken craft-conductor.toml: nothing is left behind.
    broken = tmp_path / "broken.zip"
    broken.write_bytes(zip_with({"craft-conductor-export.json": manifest, "craft-conductor.toml": "[server\nnot toml"}))
    with pytest.raises(transfer.TransferError):
        transfer.import_into(broken, tmp_path / "b")
    assert not (tmp_path / "b").exists()


def test_forge_launch_file_follows_the_os(tmp_path, monkeypatch):
    from craft_conductor.loaders import base
    root = tmp_path / "s"
    root.mkdir()
    lockmod.save(root, lockmod.Lock(minecraft="1.21.1", launch=["@libraries/net/neoforged/neoforge/21.1.1/win_args.txt", "nogui"]))
    monkeypatch.setattr(base, "args_file_name", lambda: "unix_args.txt")
    transfer._fix_launch(root)
    assert lockmod.load(root).launch[0].endswith("/unix_args.txt")
