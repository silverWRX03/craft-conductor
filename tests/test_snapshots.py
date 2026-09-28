"""Snapshots: backups that say what changed, and roll the whole server back."""

from mcsm import backup, config as configmod, snapshots
from mcsm.config import ModSpec
from mcsm.daemon import Daemon

from test_manager import manager, update


def test_what_changed_and_rolling_back(make_config, http, modrinth):
    modrinth.project("AAA", "goodmod", "Good Mod")
    modrinth.version("AAA", "1.0", ["1.21.1"])
    modrinth.version("AAA", "2.0", ["1.21.4"])
    modrinth.project("BBB", "newmod", "New Mod")
    modrinth.version("BBB", "1.0", ["1.21.4"])
    cfg = make_config([ModSpec("modrinth", "goodmod")])
    m = manager(cfg, http, ["1.21.1"])
    assert update(m).ok
    sd = cfg.server.dir
    (sd / "config").mkdir()
    (sd / "config" / "goodmod.toml").write_text("speed = 1\n")
    d = Daemon(m, autostart=False)
    first = d.backup_now("first")
    assert "created" in first
    archive1 = backup.list_backups(cfg.backups.dir)[-1]
    note = snapshots.load(archive1)
    assert note["minecraft"] == "1.21.1" and [x["version"] for x in note["mods"].values()] == ["1.0"]
    assert "goodmod" in note["toml"] and note["configs"]["config/goodmod.toml"]

    # Changes: a new mod, a new Minecraft (the update makes its own snapshot first), a setting, a config file.
    configmod.append_mod(cfg.path, ModSpec("modrinth", "newmod"))
    m2 = manager(configmod.load(cfg.root), http, ["1.21.1", "1.21.4"])
    assert update(m2).ok
    (sd / "server.properties").write_text("difficulty=hard\nrcon.password=secret\nmanagement-server-secret=abc\n")
    (sd / "config" / "goodmod.toml").write_text("speed = 2\n")
    Daemon(m2, autostart=False).backup_now("after")
    names = [p.name for p in backup.list_backups(cfg.backups.dir)]
    assert len(names) == 4 and "install" in names[0] and "first" in names[1] and "before-1.21.1-to-1.21.4" in names[2]
    names = names[1:]  # (the first install made a backup too)
    listing = snapshots.listing(cfg.backups.dir)
    assert listing["20" + names[0][2:]]["snapshot"]
    assert listing[names[1]]["changes"] == ["mcsm's settings for the server changed"]  # newmod added to mcsm.toml
    last = listing[names[2]]["changes"]
    assert last[:4] == ["Minecraft 1.21.1 → 1.21.4", "+ New Mod 1.0", "~ Good Mod 1.0 → 2.0", "Setting difficulty: (none) → hard"]
    assert "Mod config files changed: config/goodmod.toml" in last
    assert not any("rcon" in line or "management" in line for line in last)

    # Rolling back to the first puts everything back: files, mod list, settings.
    message = snapshots.roll_back(archive1, m2)
    assert "rolled back" in message
    assert m2.lock.minecraft == "1.21.1" and [x.version_number for x in m2.lock.mods] == ["1.0"]
    assert [s.id for s in m2.config.mods] == ["goodmod"]
    assert (sd / "config" / "goodmod.toml").read_text() == "speed = 1\n"
    assert sorted(p.name for p in (sd / "mods").iterdir()) == ["AAA-1.0.jar"]
    assert snapshots.changes(snapshots.load(archive1), snapshots.describe(m2)) == []  # nothing left to undo
    # Pruning takes the notes away with the backups.
    backup.prune(cfg.backups.dir, 1)
    assert sorted(p.name for p in cfg.backups.dir.iterdir() if not p.name.startswith(".")) == [names[2], names[2] + ".json"]


def test_an_older_backup_restores_its_files(make_config, http, modrinth):
    modrinth.project("AAA", "goodmod", "Good Mod")
    modrinth.version("AAA", "1.0", ["1.21.1"])
    cfg = make_config([ModSpec("modrinth", "goodmod")])
    m = manager(cfg, http, ["1.21.1"])
    assert update(m).ok
    archive = backup.create(cfg.server.dir, cfg.backups.dir, "old", [])  # (no note: made by mcsm 0.14)
    assert "only the files" in snapshots.roll_back(archive, m)
    assert snapshots.listing(cfg.backups.dir)[archive.name]["snapshot"] is False


def test_rolling_back_from_the_page(hub_env):
    from test_hub import login
    from test_web import wait_for
    hub, c = hub_env
    login(c)
    assert c.post("/api/servers/alpha/backups/create", {"label": "one"})[0] == 200
    wait_for(lambda: any("one" in x["name"] for x in c.get("/api/servers/alpha/backups")[1]["backups"]), timeout=30)
    b = next(x for x in c.get("/api/servers/alpha/backups")[1]["backups"] if "one" in x["name"])
    assert b["snapshot"] and b["minecraft"] == "1.21.1"
    assert c.get(f"/api/servers/alpha/backups/changes?name={b['name']}")[1] == {"snapshot": True, "undo": []}
    assert c.get("/api/servers/alpha/backups/changes?name=../x")[0] == 404
