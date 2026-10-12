"""What backups hold (Backups → Backup settings), the part locked to this computer, and restoring
a backup that left something out."""

import json
import os
import tarfile

from craft_conductor import backup, parts
from craft_conductor.properties import read_properties, write_properties

from test_hub import login
from test_secrets import access, only_mine
from test_web import wait_for


def a_server(tmp_path):
    sd = tmp_path / "server"
    (sd / "world" / "region").mkdir(parents=True)
    (sd / "world" / "level.dat").write_bytes(b"level v1")
    (sd / "mods").mkdir()
    (sd / "mods" / "a.jar").write_bytes(b"mod v1")
    (sd / "config").mkdir()
    (sd / "config" / "a.toml").write_text("x = 1")
    (sd / "logs").mkdir()
    (sd / "logs" / "latest.log").write_text("Steve[/203.0.113.9:5555] logged in")
    (sd / "bluemap" / "web").mkdir(parents=True)
    (sd / "bluemap" / "web" / "tile.png").write_bytes(b"tile")
    (sd / "banned-ips.json").write_text('[{"ip": "203.0.113.9", "reason": "test"}]')
    (sd / "ops.json").write_text("[]")
    write_properties(sd / "server.properties", {"level-name": "world", "enable-rcon": "true", "rcon.password": "fake-rcon-password"})
    return sd


def plain_bytes(archive) -> tuple[set, bytes]:
    """The names in a backup, and everything in it but its locked part."""
    with tarfile.open(archive) as tar:
        members = [m for m in tar if m.isfile()]
        return {m.name for m in members}, b"".join(tar.extractfile(m).read() for m in members if m.name != backup.LOCKED)


def test_a_backup_holds_what_was_chosen(tmp_path):
    sd = a_server(tmp_path)
    archive = backup.create(sd, tmp_path / "backups", "manual", [], ["mods", "configs", "players"])
    names, plain = plain_bytes(archive)
    assert {"server/mods/a.jar", "server/config/a.toml", "server/ops.json", "server/server.properties"} <= names
    assert not any(n.startswith(("server/world", "server/bluemap", "server/logs")) for n in names)
    assert "server/banned-ips.json" not in names and backup.LOCKED not in names
    assert b"fake-rcon-password" not in plain and b"203.0.113.9" not in plain  # (secrets left out: not in it at all)
    assert backup.about(archive) == {"format": 1, "holds": ["configs", "mods", "players"], "level": "world",
                                     "locked": [], "excluded": []}


def test_passwords_keys_ip_bans_and_logs_go_in_locked_to_this_computer(tmp_path):
    sd = a_server(tmp_path)
    archive = backup.create(sd, tmp_path / "backups", "manual", [], [*parts.CHOICES, "secrets", "logs"])
    names, plain = plain_bytes(archive)
    assert backup.LOCKED in names and "server/logs/latest.log" not in names and "server/banned-ips.json" not in names
    assert b"fake-rcon-password" not in plain and b"203.0.113.9" not in plain
    assert backup.about(archive)["locked"] == ["logs", "secrets"]
    assert only_mine(archive), access(archive)
    # Restored on this computer: all of it comes back, the locked part too.
    (sd / "logs" / "latest.log").write_text("later")
    write_properties(sd / "server.properties", {"rcon.password": "changed since"})
    (sd / "banned-ips.json").write_text("[]")
    result = backup.restore(archive, sd)
    assert result["opened"] == ["logs", "secrets"] and result["why"] is None
    assert read_properties(sd / "server.properties")["rcon.password"] == "fake-rcon-password"
    assert (sd / "logs" / "latest.log").read_text().startswith("Steve")
    assert b"203.0.113.9" in (sd / "banned-ips.json").read_bytes()


def test_on_another_computer_the_locked_part_stays_shut_and_the_servers_own_are_kept(tmp_path, monkeypatch):
    sd = a_server(tmp_path)
    archive = backup.create(sd, tmp_path / "backups", "manual", [], [*parts.CHOICES, "secrets", "logs"])
    monkeypatch.setenv("CRAFT_CONDUCTOR_HOME", str(tmp_path / "another-computer"))  # (another key)
    write_properties(sd / "server.properties", {"rcon.password": "this-computers-own"})
    (sd / "logs" / "latest.log").write_text("this computer's log")
    (sd / "banned-ips.json").write_text("[]")
    (sd / "world" / "level.dat").write_bytes(b"level v2")
    result = backup.restore(archive, sd)
    assert result["locked"] == ["logs", "secrets"] and result["opened"] == [] and "another computer" in result["why"]
    assert read_properties(sd / "server.properties")["rcon.password"] == "this-computers-own"
    assert (sd / "logs" / "latest.log").read_text() == "this computer's log"
    assert (sd / "banned-ips.json").read_text() == "[]"
    assert (sd / "world" / "level.dat").read_bytes() == b"level v1"  # (the rest is the backup's)


def test_restoring_a_backup_that_left_something_out_keeps_the_servers_own(tmp_path):
    sd = a_server(tmp_path)
    archive = backup.create(sd, tmp_path / "backups", "manual", [], ["mods", "configs", "players"])
    (sd / "world" / "level.dat").write_bytes(b"level v2 (played since)")
    (sd / "mods" / "a.jar").write_bytes(b"mod v2")
    (sd / "mods" / "new.jar").write_bytes(b"added since")
    backup.restore(archive, sd)
    assert (sd / "world" / "level.dat").read_bytes() == b"level v2 (played since)"  # (left out: the server's own)
    assert (sd / "bluemap" / "web" / "tile.png").read_bytes() == b"tile"
    assert (sd / "mods" / "a.jar").read_bytes() == b"mod v1" and not (sd / "mods" / "new.jar").exists()  # (in it)
    assert read_properties(sd / "server.properties")["rcon.password"] == "fake-rcon-password"  # (left out: kept)
    assert not (sd.with_name("server.restoring")).exists() and not (sd.with_name("server.replaced")).exists()


def test_the_world_left_out_keeps_the_world_the_server_uses_now(tmp_path):
    """The world folder was renamed after the backup: the restored settings still point at the one kept."""
    sd = a_server(tmp_path)
    archive = backup.create(sd, tmp_path / "backups", "manual", [], ["mods", "configs", "players"])
    os.replace(sd / "world", sd / "survival")
    write_properties(sd / "server.properties", {"level-name": "survival"})
    backup.restore(archive, sd)
    assert (sd / "survival" / "level.dat").read_bytes() == b"level v1"
    assert read_properties(sd / "server.properties")["level-name"] == "survival"


def test_an_interrupted_restore_puts_the_servers_own_files_back(tmp_path):
    """The computer turned off after the world (left out of the backup) went into the new folder,
    before the swap: the next start puts it back, and the next restore starts clean."""
    sd = a_server(tmp_path)
    staging = sd.with_name(sd.name + ".restoring")
    (staging / "server").mkdir(parents=True)
    (staging / "craft-conductor").mkdir()
    (staging / backup.KEPT).write_text(json.dumps(["world"]))
    os.replace(sd / "world", staging / "server" / "world")
    assert backup.recover(sd)
    assert (sd / "world" / "level.dat").read_bytes() == b"level v1"
    assert not (staging / backup.KEPT).exists()


def test_backups_made_before_an_update_hold_everything_a_roll_back_needs(tmp_path):
    sd = a_server(tmp_path)
    archive = backup.create(sd, tmp_path / "backups", "before-1.21.1-to-1.21.4", [])
    about = backup.about(archive)
    assert about["holds"] == sorted(parts.CHOICES) and about["locked"] == ["secrets"]  # (no logs: not needed)


def test_backup_settings_on_the_backups_page(hub_env):
    hub, c = hub_env
    login(c)
    d = hub.get("alpha")
    (d.m.server_dir / "world").mkdir(exist_ok=True)
    (d.m.server_dir / "world" / "level.dat").write_bytes(b"level")
    status, body, _ = c.post("/api/servers/alpha/settings", {"backup_include": ["mods", "logs"], "backups_keep": 4})
    assert status == 200, body
    assert d.m.config.backups.include == ["mods", "logs"] and d.m.config.backups.keep == 4
    assert "logs" not in d.m.config.backups.exclude  # (chosen on the page: it wins over the old exclude)
    assert c.post("/api/servers/alpha/settings", {"backup_include": ["everything"]})[0] == 400
    assert d.m.config.backups.include == ["mods", "logs"]
    assert c.post("/api/servers/alpha/backups/create", {"label": "chosen"})[0] == 200
    wait_for(lambda: d.last_job and d.last_job["name"] == "backup", timeout=30)
    listed = c.get("/api/servers/alpha/backups")[1]["backups"][0]
    assert listed["holds"] == ["mods"] and listed["locked"] in ([], ["logs"])
