"""Where servers, backups and exports are kept (locations.py): chosen once after the first sign-in,
used by new servers, backups and exports, and moved (checked file by file) when changed."""

import json
import os
from pathlib import Path

import pytest

from craft_conductor import folders, locations as locmod

from test_access import owner_ready
from test_hub import login
from test_remote import invite
from test_web import login as single_login, running, wait_for  # noqa: F401  (running: the fixture)


def moved(c, timeout=60):
    """Wait for the move under way to finish: what GET /api/hub/locations says then."""
    wait_for(lambda: not (c.get("/api/hub/locations")[1].get("move") or {}).get("running"), timeout=timeout)
    return c.get("/api/hub/locations")[1]


# ------------------------------------------------------------------ choosing
def test_the_first_use_choice_offers_todays_folders(hub_env):
    hub, c = hub_env
    hub._save_locations(hub.locations(), chosen=False)  # (a new install: not chosen yet)
    login(c)
    home = hub.home
    assert c.get("/api/hub")[1]["locations"] == {"chosen": False, "choosable": True}
    status, r, _ = c.get("/api/hub/locations")
    assert status == 200 and r["chosen"] is False and r["why_not"] is None
    assert (r["servers"], r["backups"], r["exports"]) == (str(home / "servers"), None, str(home / "exports"))
    # Use these folders: nothing moves, and the page doesn't ask again.
    status, r, _ = c.post("/api/hub/locations", {"servers": r["servers"], "backups": "", "exports": r["exports"], "go": True})
    assert status == 200 and r["changes"] == [] and r["locations"]["chosen"] is True, r
    assert c.get("/api/hub")[1]["locations"]["chosen"] is True
    assert "One folder per server" in (home / "servers" / "README.txt").read_text(encoding="utf-8")
    assert "Import a server" in (home / "exports" / "README.txt").read_text(encoding="utf-8")
    assert hub.discover()["alpha"] == home / "servers" / "alpha"  # (a README there isn't a server)


def test_servers_backups_and_exports_go_where_chosen(hub_env, tmp_path):
    """Choose three folders: the servers there move (asked first), and from then on new servers,
    their backups and exports go there; Import a server… lists the exports with no upload."""
    hub, c = hub_env
    login(c)
    S, B, E = tmp_path / "My servers", tmp_path / "My backups", tmp_path / "My exports"
    wanted = {"servers": str(S), "backups": str(B), "exports": str(E)}
    status, ask, _ = c.post("/api/hub/locations", wanted)  # (what it would do: asked first)
    assert status == 200 and not S.exists(), ask
    assert {x["kind"]: x["count"] for x in ask["changes"]}["servers"] == 1 and ask["busy"] == []
    assert c.post("/api/hub/locations", {**wanted, "go": True})[0] == 200
    r = moved(c)
    assert r["move"]["ok"] is True, r["move"]
    assert (r["servers"], r["backups"], r["exports"]) == (os.path.realpath(S), os.path.realpath(B), os.path.realpath(E))
    real_s = Path(os.path.realpath(S))
    assert (real_s / "alpha" / "craft-conductor.toml").exists() and not (hub.home / "servers" / "alpha").exists()
    assert not (hub.home / "servers").exists()  # (the old folder, left empty: gone)
    assert hub.get("alpha").m.config.root == real_s / "alpha"
    assert (real_s / "README.txt").exists() and (Path(os.path.realpath(B)) / "README.txt").exists()
    # A backup goes in the backups folder, in a folder named after the server.
    assert c.post("/api/servers/alpha/backups/create", {"label": "test"})[0] == 200
    d = hub.get("alpha")
    wait_for(lambda: d.last_job and d.last_job["name"] == "backup", timeout=60)
    assert d.m.config.backups.dir == Path(os.path.realpath(B)) / "alpha"
    assert list(d.m.config.backups.dir.glob("*.tar.gz")), d.last_job
    # An export goes in the exports folder, and Import a server… lists it.
    assert c.post("/api/servers/alpha/export", {})[0] == 200
    wait_for(lambda: d.last_job and d.last_job["name"] == "export", timeout=60)
    assert d.last_job["ok"], d.last_job
    exports = c.get("/api/hub/exports")[1]
    assert exports["folder"] == os.path.realpath(E) and exports["exports"][0]["server"] == "alpha"
    status, r, _ = c.post("/api/hub/import", {"export": exports["exports"][0]["path"]})
    assert status == 200 and r["id"] != "alpha", r
    copy = hub.get(r["id"])
    assert copy.m.config.root.parent == real_s and copy.m.config.backups.dir == Path(os.path.realpath(B)) / r["id"]
    for bad in ("../x.craft-conductor.zip", "alpha/../../x.craft-conductor.zip", "a/b/c.craft-conductor.zip", "alpha/notes.txt"):
        assert c.post("/api/hub/import", {"export": bad})[0] == 400, bad
    # Backups back in each server's own folder: they move back too.
    assert c.post("/api/hub/locations", {"backups": "", "go": True})[0] == 200
    assert moved(c)["move"]["ok"]
    assert hub.get("alpha").m.config.backups.dir == real_s / "alpha" / "backups"
    assert list((real_s / "alpha" / "backups").glob("*.tar.gz"))


def test_a_move_is_refused_while_a_server_runs(hub_env, tmp_path):
    hub, c = hub_env
    login(c)
    assert c.post("/api/servers/alpha/server/start")[0] == 200
    wait_for(lambda: hub.get("alpha").state == "running", timeout=30)
    status, r, _ = c.post("/api/hub/locations", {"servers": str(tmp_path / "S")})
    assert status == 200 and r["busy"] == ["Alpha is running"], r
    status, r, _ = c.post("/api/hub/locations", {"servers": str(tmp_path / "S"), "go": True})
    assert status == 400 and "stop these first: Alpha is running" in r["error"]
    assert not (tmp_path / "S").exists() and hub.servers_dir == hub.home / "servers"


def test_places_that_are_refused(hub_env, tmp_path, monkeypatch):
    hub, c = hub_env
    login(c)
    home = hub.home

    def refused(**wanted):
        status, r, _ = c.post("/api/hub/locations", wanted)
        assert status == 400, (wanted, r)
        return r["error"]
    assert "the exports folder" in refused(servers=str(home / "exports" / "inside"))  # (inside another one)
    assert "the servers folder" in refused(backups=str(home / "servers" / "backups"))
    assert "holds" in refused(exports=str(home))  # (holds the servers folder and Craft Conductor's own)
    assert "Craft Conductor's own folder" in refused(backups=str(home / ".craft-conductor" / "backups"))
    assert "one of the computer's own folders" in refused(servers="C:\\" if os.name == "nt" else "/")
    assert "isn't a full path" in refused(servers="relative/folder")
    monkeypatch.setattr(locmod, "is_removable", lambda p: True)
    assert "removable drive" in refused(backups=str(tmp_path / "usb"))
    monkeypatch.setattr(locmod, "is_removable", lambda p: False)
    network = folders.is_network
    monkeypatch.setattr(folders, "is_network", lambda p: True)
    assert "on the network" in refused(backups=str(tmp_path / "share"))
    monkeypatch.setattr(folders, "is_network", network)
    # A synced folder: fine for backups, a warning for servers.
    synced = tmp_path / "OneDrive - Home"
    synced.mkdir()
    r = c.post("/api/hub/locations", {"backups": str(synced / "Backups")})[1]
    assert r["warnings"] == []
    r = c.post("/api/hub/locations", {"servers": str(synced / "Servers")})[1]
    assert "synced by OneDrive" in r["warnings"][0]
    # A folder that has files in it already isn't moved into.
    full = tmp_path / "full"
    full.mkdir()
    (full / "something.txt").write_text("x")
    assert "must be new or empty" in refused(servers=str(full))


def test_the_downloaded_programs_folder(tmp_path, monkeypatch):
    """The program often sits in Downloads: that folder can't be a place (nor one holding it), but a
    folder inside it can."""
    downloads = tmp_path / "you" / "Downloads"
    downloads.mkdir(parents=True)
    monkeypatch.setattr(locmod.sys, "frozen", True, raising=False)
    monkeypatch.setattr(locmod.sys, "executable", str(downloads / "craft-conductor-windows-x64.exe"))
    state = tmp_path / "home" / ".craft-conductor"
    for refused in (downloads, tmp_path / "you"):
        with pytest.raises(locmod.LocationError, match="holds Craft Conductor's program"):
            locmod.check_place("exports", str(refused), {}, state)
    assert locmod.check_place("exports", str(downloads / "Exports"), {}, state)[0] == Path(os.path.realpath(downloads / "Exports"))


@pytest.mark.skipif(os.name != "nt", reason="Windows network paths")
def test_network_paths_are_refused_without_connecting():
    for text in ("\\\\nas.invalid\\share\\mods", "//nas.invalid/share"):
        assert folders.is_network(text)
        with pytest.raises(folders.FolderError, match="on another computer"):
            folders.check(text)
        with pytest.raises(locmod.LocationError, match="on the network"):
            locmod.check_place("backups", text, {}, Path("C:/nowhere"))


def test_a_folder_on_a_linux_network_mount_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(folders, "mount_type", lambda p: "nfs4")
    monkeypatch.setattr(folders.os, "name", "posix")
    monkeypatch.setattr(folders.sys, "platform", "linux")
    assert folders.is_network(tmp_path)


def test_not_enough_space_is_said_before_anything_moves(hub_env, tmp_path, monkeypatch):
    import shutil
    hub, c = hub_env
    login(c)
    monkeypatch.setattr(locmod, "_same_drive", lambda src, dst: False)  # (another drive: copied)
    monkeypatch.setattr(locmod.shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(10, 10, 1000))
    status, r, _ = c.post("/api/hub/locations", {"servers": str(tmp_path / "S"), "go": True})
    assert status == 400 and "isn't enough free space" in r["error"], r
    assert not (tmp_path / "S").exists() and (hub.home / "servers" / "alpha").exists()


def test_a_move_that_fails_halfway_leaves_everything_where_it_was(hub_env, tmp_path, monkeypatch):
    hub, c = hub_env
    login(c)
    alpha = hub.home / "servers" / "alpha"
    before = sorted(str(p.relative_to(alpha)) for p in alpha.rglob("*"))
    monkeypatch.setattr(locmod, "_same_drive", lambda src, dst: False)
    real, n = locmod._copy_checked, []

    def failing(src, dst, done):
        n.append(1)
        if len(n) == 3:
            raise OSError(28, "No space left on device")
        real(src, dst, done)
    monkeypatch.setattr(locmod, "_copy_checked", failing)
    assert c.post("/api/hub/locations", {"servers": str(tmp_path / "S"), "go": True})[0] == 200
    r = moved(c)
    assert r["move"]["ok"] is False and "No space left" in r["move"]["message"], r["move"]
    assert r["servers"] == str(hub.home / "servers")
    assert sorted(str(p.relative_to(alpha)) for p in alpha.rglob("*")) == before  # (nothing lost)
    assert not (tmp_path / "S" / "alpha").exists() and not (hub.state_dir / locmod.JOURNAL).exists()
    wait_for(lambda: hub.get("alpha") is not None and hub.get("alpha").m.config.root == alpha)
    assert c.post("/api/servers/alpha/server/start")[0] == 200  # (and it still works)


def test_a_move_cut_off_by_a_stop_is_put_back_at_the_next_start(tmp_path):
    """The computer turned off halfway: the next start removes the copies and puts the
    servers' backups setting back; the originals were never touched."""
    src = tmp_path / "old" / "alpha"
    (src / "server").mkdir(parents=True)
    (src / "server" / "level.dat").write_bytes(b"world")
    toml = tmp_path / "old" / "alpha" / "craft-conductor.toml"
    toml.write_text('[backups]\ndir = "D:\\\\new\\\\alpha"\n', encoding="utf-8")
    dst = tmp_path / "new" / "alpha"
    (dst / "server").mkdir(parents=True)
    (dst / "server" / "level.dat").write_bytes(b"wor")  # (a copy cut off)
    state = tmp_path / "state"
    state.mkdir()
    (state / locmod.JOURNAL).write_text(json.dumps({
        "kind": "backups", "old": str(tmp_path / "old"), "new": str(tmp_path / "new"), "phase": "moving",
        "extra": {"tomls": {str(toml): None}},
        "items": [{"src": str(src), "dst": str(dst), "how": "copy", "done": False}]}), encoding="utf-8")
    from craft_conductor.hub import put_tomls
    message = locmod.recover(state, lambda extra: put_tomls(extra["tomls"]))
    assert "put back" in message
    assert not dst.exists() and (src / "server" / "level.dat").read_bytes() == b"world"
    assert "dir" not in toml.read_text(encoding="utf-8") and not (state / locmod.JOURNAL).exists()


def test_a_copy_that_isnt_the_same_stops_the_move(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.bin").write_bytes(b"a" * 1000)
    monkeypatch.setattr(locmod, "_sha256", lambda p: "0" * 64)  # (the copy, read back, differs)
    with pytest.raises(locmod.LocationError, match="isn't the same as the original"):
        locmod.copy_tree(src, tmp_path / "dst", lambda n: None)


def test_folders_with_links_in_them_arent_moved(tmp_path):
    src = tmp_path / "server"
    (src / "world").mkdir(parents=True)
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(tmp_path), str(src / "world" / "elsewhere"))
        else:
            (src / "world" / "elsewhere").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("this computer doesn't let the tests make links")
    plan = locmod.Plan("servers", tmp_path, tmp_path / "new", [locmod.Item(src, tmp_path / "new" / "server")])
    with pytest.raises(locmod.LocationError, match="is a link"):
        locmod.prepare(plan)


def test_new_folder_in_the_folder_browser(hub_env, tmp_path):
    hub, c = hub_env
    login(c)
    status, r, _ = c.post("/api/hub/folders/new", {"parent": str(tmp_path), "name": "Minecraft servers"})
    assert status == 200 and r["path"] == os.path.realpath(tmp_path / "Minecraft servers") and r["folders"] == []
    for bad in ("", "..", "a/b", "con", "what?"):
        assert c.post("/api/hub/folders/new", {"parent": str(tmp_path), "name": bad})[0] == 400, bad


# ------------------------------------------------------------------ where it doesn't apply
def test_single_server_mode_keeps_its_own_folder(running):
    d, c, cfg = running
    single_login(c)
    r = c.get("/api/hub/locations")[1]
    assert r["single"] is True and "its own folder" in r["why_not"] and r["servers"] == str(cfg.root)
    assert c.get("/api/hub")[1]["locations"] == {"chosen": True, "choosable": False}
    assert c.post("/api/hub/locations", {"backups": str(cfg.root.parent / "elsewhere"), "go": True})[0] == 400


def test_docker_keeps_everything_in_its_volume(hub_env, monkeypatch, tmp_path):
    hub, c = hub_env
    login(c)
    monkeypatch.setenv("CRAFT_CONDUCTOR_CONTAINER", "1")
    r = c.get("/api/hub/locations")[1]
    assert "/data volume" in r["why_not"] and c.get("/api/hub")[1]["locations"]["choosable"] is False
    status, r, _ = c.post("/api/hub/locations", {"exports": str(tmp_path / "E"), "go": True})
    assert status == 400 and "/data volume" in r["error"]


def test_only_the_owner_chooses_where_files_are_kept(hub_env, tmp_path):
    from craft_conductor import access
    hub, c = hub_env
    owner_ready(hub, c)
    person, _ = invite(hub, c, "Manny", {"alpha": sorted(access.CAPS)})
    for method, path, body in (("GET", "/api/hub/locations", None), ("POST", "/api/hub/locations", {"exports": str(tmp_path / "E"), "go": True}),
                               ("POST", "/api/hub/folders/new", {"parent": str(tmp_path), "name": "x"}), ("GET", "/api/hub/exports", None),
                               ("POST", "/api/hub/import", {"export": "alpha/x.craft-conductor.zip"})):
        status = (person.get(path) if method == "GET" else person.post(path, body))[0]
        assert status == 403, path
    assert "locations" not in person.get("/api/hub")[1]
    assert not (tmp_path / "E").exists() and not (tmp_path / "x").exists()
