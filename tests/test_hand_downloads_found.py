"""Mods downloaded by hand, found where the browser saved them (handdownload.look, folders.py):
the Downloads folder on each computer, folders the owner chose, and the folder browser."""

import hashlib
import os
from pathlib import Path

import pytest

from craft_conductor import folders, handdownload

from test_access import owner_ready
from test_curseforgepack import _check, serve_blocked_mod
from test_hub import login as hub_login
from test_remote import invite
from test_web import login, running, wait_for  # noqa: F401  (running: the fixture)

JAR = b"fancy jar"
SHA1 = hashlib.sha1(JAR).hexdigest()
WANT = {"name": "Fancy Client", "filename": "fancy-client-2.1.jar", "sha1": SHA1}


@pytest.fixture(autouse=True)
def fresh_cache():
    for cache in (handdownload._wanted, handdownload._resolved, handdownload._hashed, handdownload._listed):
        cache.clear()
    yield
    for cache in (handdownload._wanted, handdownload._resolved, handdownload._hashed, handdownload._listed):
        cache.clear()


@pytest.fixture
def downloads(tmp_path, monkeypatch):
    """This computer's Downloads folder, for the test."""
    d = tmp_path / "Downloads"
    d.mkdir()
    monkeypatch.setattr(folders, "downloads_dir", lambda *a, **k: d)
    return d


# ------------------------------------------------------------------ where Downloads is
def test_the_downloads_folder_on_windows_is_where_windows_says(tmp_path, monkeypatch):
    moved = tmp_path / "D" / "My downloads"
    moved.mkdir(parents=True)
    monkeypatch.setattr(folders, "known_folder", lambda guid: moved if guid == folders.DOWNLOADS else None)
    assert folders.downloads_dir("windows", tmp_path / "home") == moved  # (moved to another drive)
    monkeypatch.setattr(folders, "known_folder", lambda guid: None)
    (tmp_path / "home" / "Downloads").mkdir(parents=True)
    assert folders.downloads_dir("windows", tmp_path / "home") == tmp_path / "home" / "Downloads"


def test_the_downloads_folder_on_a_mac(tmp_path):
    home = tmp_path / "home"
    assert folders.downloads_dir("darwin", home) is None  # (none there)
    (home / "Downloads").mkdir(parents=True)
    assert folders.downloads_dir("darwin", home) == home / "Downloads"


def test_the_downloads_folder_on_linux_follows_the_xdg_setting(tmp_path):
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    assert folders.downloads_dir("linux", home, {}) == home / "Downloads"  # (no user-dirs.dirs)
    config = home / ".config" / "user-dirs.dirs"
    config.parent.mkdir()
    (home / "Telechargements").mkdir()
    config.write_text('# written by xdg-user-dirs-update\nXDG_DESKTOP_DIR="$HOME/Desktop"\n'
                      'XDG_DOWNLOAD_DIR="$HOME/Telechargements"\n', encoding="utf-8")
    assert folders.downloads_dir("linux", home, {}) == home / "Telechargements"
    elsewhere = tmp_path / "data" / "dl"
    elsewhere.mkdir(parents=True)
    config.write_text(f'XDG_DOWNLOAD_DIR="{elsewhere.as_posix()}"\n', encoding="utf-8")
    if os.name != "nt":  # (an absolute path is a POSIX one)
        assert folders.downloads_dir("linux", home, {}) == elsewhere
    config.write_text('XDG_DOWNLOAD_DIR="$HOME/"\n', encoding="utf-8")
    assert folders.downloads_dir("linux", home, {}) is None  # (set to the home folder: switched off)
    other = tmp_path / "other-config"
    other.mkdir()
    (other / "user-dirs.dirs").write_text('XDG_DOWNLOAD_DIR="$HOME/Telechargements"\n', encoding="utf-8")
    assert folders.downloads_dir("linux", home, {"XDG_CONFIG_HOME": str(other)}) == home / "Telechargements"


def test_no_downloads_folder_it_can_read(tmp_path, monkeypatch):
    """A service running as another account, Docker: no Downloads folder, and nothing is looked in."""
    assert folders.downloads_dir("linux", tmp_path / "nobody", {}) is None
    monkeypatch.setattr(folders, "downloads_dir", lambda *a, **k: None)
    assert handdownload.where_to_look([]) == []


# ------------------------------------------------------------------ looking
def test_a_matching_file_is_found_and_copied(downloads, tmp_path):
    (downloads / "fancy-client-2.1 (1).jar").write_bytes(JAR)  # (the browser's second copy)
    found, wrong = handdownload.look([downloads], [WANT])
    assert found == {"fancy-client-2.1.jar": downloads / "fancy-client-2.1 (1).jar"} and wrong == {}
    dest = tmp_path / "staging" / "fancy-client-2.1.jar"
    taken, failed = handdownload.copy_found(found, [WANT], lambda x: dest)
    assert taken == [WANT] and not failed
    assert dest.read_bytes() == JAR and (downloads / "fancy-client-2.1 (1).jar").read_bytes() == JAR  # (copied, not moved)


def test_a_file_with_the_name_but_not_the_checksum_is_refused(downloads):
    (downloads / "fancy-client-2.1.jar").write_bytes(b"another version")
    found, wrong = handdownload.look([downloads], [WANT])
    assert found == {} and wrong == {"fancy-client-2.1.jar": downloads / "fancy-client-2.1.jar"}
    # A right copy beside it wins (Firefox's "name(1).jar"), and nothing wrong is said.
    (downloads / "fancy-client-2.1(1).jar").write_bytes(JAR)
    found, wrong = handdownload.look([downloads], [WANT])
    assert found == {"fancy-client-2.1.jar": downloads / "fancy-client-2.1(1).jar"} and wrong == {}


def test_only_the_files_asked_for_are_read(downloads, monkeypatch):
    for name in ("notes.txt", "fancy-client-2.0.jar", "other-mod.jar", "fancy-client-2.1.jar.zip"):
        (downloads / name).write_bytes(JAR)
    (downloads / "fancy-client-2.1.jar").write_bytes(b"")  # (Firefox's empty file while it downloads)
    (downloads / "fancy-client-2.1 (2).jar").write_bytes(JAR)
    (downloads / "fancy-client-2.1 (2).jar.crdownload").write_bytes(b"half")  # (still being saved)
    opened = []
    real = handdownload._open_file
    monkeypatch.setattr(handdownload, "_open_file", lambda p: (opened.append(p.name), real(p))[1])
    assert handdownload.look([downloads], [WANT]) == ({}, {})
    assert opened == ["fancy-client-2.1.jar"]  # (looked at, empty: not read; nothing else opened)


def test_names_like_a_file_are_found_without_reading_them_all():
    names = handdownload._Names(["notes.txt", "Fancy-Client-2.1 (1).jar", "fancy-client-2.10.jar", "fancy-client-2.1-3.jar", "zz.jar"])
    assert names.starting("fancy-client-2.1") == ["fancy-client-2.1 (1).jar", "fancy-client-2.1-3.jar", "fancy-client-2.10.jar"]
    assert handdownload._candidates(names, "fancy-client-2.1.jar") == [("Fancy-Client-2.1 (1).jar", True), ("fancy-client-2.1-3.jar", False)]


def test_a_file_is_read_once_until_it_changes(downloads, monkeypatch):
    import hashlib as hl
    reads = []
    real = hl.sha1
    monkeypatch.setattr(hl, "sha1", lambda *a: (reads.append(1), real(*a))[1])
    path = downloads / "fancy-client-2.1.jar"
    path.write_bytes(b"wrong")
    for _ in range(3):
        assert handdownload.look([downloads], [WANT])[1]
    assert len(reads) == 1
    path.write_bytes(JAR)
    os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 10_000_000))
    assert handdownload.look([downloads], [WANT])[0]
    assert len(reads) == 2


def test_links_are_never_followed(downloads, tmp_path):
    real = tmp_path / "elsewhere.jar"
    real.write_bytes(JAR)
    try:
        (downloads / "fancy-client-2.1.jar").symlink_to(real)
        (downloads / "sub").symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this computer doesn't let the tests make links")
    assert handdownload.look([downloads], [WANT]) == ({}, {})
    assert [x["name"] for x in folders.listing(str(downloads))["folders"]] == []


@pytest.mark.skipif(os.name != "nt", reason="Windows junctions")
def test_junctions_are_never_followed(tmp_path):
    import _winapi
    (tmp_path / "browse" / "real").mkdir(parents=True)
    _winapi.CreateJunction(str(tmp_path / "browse" / "real"), str(tmp_path / "browse" / "junction"))
    assert [x["name"] for x in folders.listing(str(tmp_path / "browse"))["folders"]] == ["real"]


def test_a_file_that_changes_while_it_is_copied_is_not_kept(downloads, tmp_path, monkeypatch):
    (downloads / "fancy-client-2.1.jar").write_bytes(JAR)
    found, _ = handdownload.look([downloads], [WANT])
    monkeypatch.setattr(handdownload, "sha1_file", lambda p: "0" * 40)  # (the copy isn't CurseForge's file)
    dest = tmp_path / "manual" / "fancy-client-2.1.jar"
    taken, failed = handdownload.copy_found(found, [WANT], lambda x: dest)
    assert not taken and failed == [WANT]
    assert not dest.exists() and list(dest.parent.iterdir()) == []  # (nothing half-copied left)


def test_a_file_without_a_checksum_isnt_taken(downloads):
    (downloads / "fancy-client-2.1.jar").write_bytes(JAR)
    assert handdownload.look([downloads], [{**WANT, "sha1": None}]) == ({}, {})


# ------------------------------------------------------------------ the folder browser
def test_the_folder_browser_lists_folders_only(tmp_path):
    tmp_path = tmp_path / "browse"
    tmp_path.mkdir()
    (tmp_path / "Mods").mkdir()
    (tmp_path / "b-folder").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "file.jar").write_bytes(b"x")
    got = folders.listing(str(tmp_path))
    assert [x["name"] for x in got["folders"]] == ["b-folder", "Mods"]
    assert got["path"] == os.path.realpath(tmp_path) and got["parent"] == os.path.realpath(tmp_path.parent)
    for bad in ("", "relative/path", str(tmp_path / "file.jar"), str(tmp_path / "missing")):
        with pytest.raises(folders.FolderError):
            folders.listing(bad)
    assert folders.check(str(tmp_path / "Mods" / ".." / "b-folder")) == Path(os.path.realpath(tmp_path / "b-folder"))
    places = folders.places("linux", tmp_path)
    assert places[0] == {"name": "Home", "path": os.path.realpath(tmp_path)}
    assert all(Path(p["path"]).is_dir() for p in places)


# ------------------------------------------------------------------ through the control panel
def test_the_setup_page_finds_a_mod_in_downloads(hub_env, downloads, tmp_path, monkeypatch):
    """The setup page asks which files it still misses: one in Downloads is copied to the staging
    area (as if it was dropped on the page), one with the name but not the checksum is said, and
    creating the server puts the found one where the server looks for it."""
    hub, c = hub_env
    hub_login(c)
    monkeypatch.setenv("CRAFT_CONDUCTOR_CURSEFORGE_API_KEY", "test-key-not-real")
    serve_blocked_mod(hub.http, JAR)
    assert c.post("/api/hub/manual/needed", {"loader": "forge", "minecraft": "1.20.1",
                                             "mods": [{"id": "22", "channel": "beta"}]})[0] == 200
    # Not there yet: nothing found, and the page says where it looked.
    status, r, _ = c.post("/api/hub/manual/look", {"filenames": ["fancy-client-2.1.jar"]})
    assert status == 200 and r["found"] == [] and r["wrong"] == [] and r["looked"] == ["Downloads"], r
    assert r["downloads"] == str(downloads) and r["folders"] == []
    (downloads / "fancy-client-2.1.jar").write_bytes(b"not it")
    r = c.post("/api/hub/manual/look", {"filenames": ["fancy-client-2.1.jar"]})[1]
    assert r["found"] == [] and r["wrong"] == [{"filename": "fancy-client-2.1.jar", "name": "Fancy Client", "where": "Downloads"}]
    (downloads / "fancy-client-2.1 (1).jar").write_bytes(JAR)
    r = c.post("/api/hub/manual/look", {"filenames": ["fancy-client-2.1.jar", "not-asked-for.jar"]})[1]
    assert [(x["filename"], x["where"]) for x in r["found"]] == [("fancy-client-2.1.jar", "Downloads")] and r["wrong"] == []
    staged = r["found"][0]["id"]
    assert (hub.staging_dir / staged / "fancy-client-2.1.jar").read_bytes() == JAR
    status, body, _ = c.post("/api/hub/create", {"loader": "fabric", "minecraft": "1.21.1", "motd": "Found",
                                                  "manual_files": [staged], "accept_eula": True})
    assert status == 200, body
    d = hub.get(body["id"])
    wait_for(lambda: d.last_job and d.last_job["name"] == "set up server", timeout=30)
    assert (d.m.config.manual_dir / "fancy-client-2.1.jar").read_bytes() == JAR
    assert (downloads / "fancy-client-2.1 (1).jar").exists()  # (the original stays)
    assert c.post("/api/hub/manual/look", {"filenames": "x"})[0] == 400


def test_a_folder_chosen_on_the_page(hub_env, downloads, tmp_path, monkeypatch):
    """Not in Downloads: the page asks where it is. A folder chosen just this time is looked in
    once; one to always look in is remembered (and forgotten again)."""
    hub, c = hub_env
    hub_login(c)
    monkeypatch.setenv("CRAFT_CONDUCTOR_CURSEFORGE_API_KEY", "test-key-not-real")
    serve_blocked_mod(hub.http, JAR)
    c.post("/api/hub/manual/needed", {"loader": "forge", "minecraft": "1.20.1", "mods": [{"id": "22", "channel": "beta"}]})
    saved = tmp_path / "Saved mods"
    saved.mkdir()
    (saved / "fancy-client-2.1.jar").write_bytes(JAR)
    ask = {"filenames": ["fancy-client-2.1.jar"]}
    assert c.post("/api/hub/manual/look", ask)[1]["found"] == []
    r = c.post("/api/hub/manual/look", {**ask, "folder": str(saved)})[1]
    assert [x["where"] for x in r["found"]] == [os.path.realpath(saved)] and r["folders"] == []
    assert c.post("/api/hub/manual/look", {**ask, "folder": str(tmp_path / "missing")})[0] == 400
    assert c.post("/api/hub/manual/look", {**ask, "folder": "relative"})[0] == 400
    # Always look here
    status, r, _ = c.post("/api/hub/manual/folders", {"add": str(saved)})
    assert status == 200 and r["folders"] == [os.path.realpath(saved)] and r["downloads"] == str(downloads)
    assert c.get("/api/hub/manual/folders")[1]["folders"] == [os.path.realpath(saved)]
    r = c.post("/api/hub/manual/look", ask)[1]
    assert r["looked"] == ["Downloads", os.path.realpath(saved)] and [x["where"] for x in r["found"]] == [os.path.realpath(saved)]
    assert c.post("/api/hub/manual/folders", {"remove": os.path.realpath(saved)})[1]["folders"] == []
    assert c.post("/api/hub/manual/folders", {"add": str(tmp_path / "missing")})[0] == 400
    assert c.post("/api/hub/manual/folders", {})[0] == 400
    # The folder browser
    (saved / "inner").mkdir()
    status, r, _ = c.get(f"/api/hub/folders?path={saved}".replace(" ", "%20"))
    assert status == 200 and [x["name"] for x in r["folders"]] == ["inner"] and "fancy-client-2.1.jar" not in str(r)
    assert c.get("/api/hub/folders")[1]["folders"][0]["name"] == "Home"
    assert c.get("/api/hub/folders?path=nowhere")[0] == 400


def test_a_server_waiting_for_a_mod_finds_it_in_downloads(running, downloads):
    """Setup's wait (and an update's) on a server's panel: a file found in Downloads goes into the
    server's manual-downloads folder, and the wait carries on."""
    d, c, cfg = running
    login(c)
    d.last_check = _check({"name": "Blocked", "filename": "blocked-1.0.jar", "url": "u", "sha1": SHA1},
                          {"name": "Other", "filename": "other.jar", "url": "u", "sha1": "0" * 40})
    status, r, _ = c.post("/api/manual/look", {})
    assert status == 200 and r["found"] == [] and r["left"] == 2, r
    (downloads / "blocked-1.0.jar").write_bytes(JAR)
    r = c.post("/api/manual/look", {})[1]
    assert [x["filename"] for x in r["found"]] == ["blocked-1.0.jar"] and r["left"] == 1
    assert (cfg.manual_dir / "blocked-1.0.jar").read_bytes() == JAR
    assert [x["filename"] for x in d.last_check["manual"]] == ["other.jar"]


def test_only_the_owner_may_look_in_this_computers_folders(hub_env, downloads):
    """Someone given everything on a server keeps its drop box, but not this computer's folders."""
    from craft_conductor import access
    hub, c = hub_env
    owner_ready(hub, c)
    person, _ = invite(hub, c, "Manny", {"alpha": sorted(access.CAPS)})
    hub.get("alpha").last_check = _check({"name": "Blocked", "filename": "blocked-1.0.jar", "url": "u", "sha1": SHA1})
    (downloads / "blocked-1.0.jar").write_bytes(JAR)
    assert person.post("/api/servers/alpha/manual/look", {})[0] == 403
    for method, path in (("POST", "/api/hub/manual/look"), ("GET", "/api/hub/manual/folders"),
                         ("POST", "/api/hub/manual/folders"), ("GET", "/api/hub/folders")):
        status = (person.get(path) if method == "GET" else person.post(path, {"add": str(downloads)}))[0]
        assert status == 403, path
    assert not (hub.get("alpha").m.config.manual_dir / "blocked-1.0.jar").exists()
    assert c.post("/api/servers/alpha/manual/look", {})[1]["left"] == 0  # (the owner may)
