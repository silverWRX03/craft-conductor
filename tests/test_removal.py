"""Deleting folders that are marked read-only (every folder OneDrive syncs is, #216)."""

import os
import shutil
import stat

import pytest

from craft_conductor import backup
from craft_conductor.removal import gone, rmtree


def read_only_tree(root):
    leaf = root / "server.replaced" / "libraries" / "lz4"
    leaf.mkdir(parents=True)
    (leaf / "lz4-java.jar").write_bytes(b"PK")
    for p in (leaf / "lz4-java.jar", leaf, leaf.parent):
        os.chmod(p, stat.S_IREAD | (stat.S_IEXEC if p.is_dir() else 0))
    return root / "server.replaced"


def test_read_only_files_and_folders_are_deleted(tmp_path):
    tree = read_only_tree(tmp_path)
    if os.name != "nt" and os.geteuid() == 0:
        pytest.skip("root deletes anything")
    with pytest.raises(PermissionError):
        shutil.rmtree(tree)
    rmtree(tree)
    assert not tree.exists()
    assert gone(tmp_path / "never-there")
    rmtree(tmp_path / "never-there", ignore_errors=True)


def test_a_restore_isnt_stopped_by_a_folder_it_replaced_before(tmp_path, monkeypatch):
    server = tmp_path / "server"
    server.mkdir()
    (server / "server.properties").write_text("motd=Old\n")
    archive = backup.create(server, tmp_path / "backups", label="test", exclude=[])
    (server / "server.properties").write_text("motd=Changed\n")
    read_only_tree(tmp_path)  # (left by an earlier restore that couldn't delete it)
    backup.restore(archive, server)
    assert (server / "server.properties").read_text() == "motd=Old\n"
    assert not (tmp_path / "server.replaced").exists() and not (tmp_path / "server.restoring").exists()


def test_what_was_put_right_is_on_the_page_once(hub_env):
    """A roll back cut off while unpacking is put right at the next start; the page is told, so it says
    so once and it's in the bell, not only in the server's Activity (#200)."""
    from test_hub import login
    hub, c = hub_env
    login(c)
    d = hub.get("alpha")
    staging = d.m.server_dir.with_name(d.m.server_dir.name + ".restoring")
    (staging / "server").mkdir(parents=True)
    assert d.m.recover()
    [r] = c.get("/api/hub")[1]["recovered"]
    assert r["sid"] == "alpha" and "stopped in the middle of something" in r["message"] and r["time"]
    assert not staging.exists()


def test_little_disk_space_is_said_in_mb():
    """30 MB free said "Only 0.0 GB of disk space left" (#215)."""
    from craft_conductor.doctor import _gb
    assert _gb(30 / 1024) == "30 MB" and _gb(0) == "0 MB" and _gb(1.5) == "1.5 GB" and _gb(16) == "16 GB"


def test_starting_asks_when_little_memory_is_free_now(hub_env, monkeypatch):
    """Other programs using most of the memory: a server given more than is free now gets asked about,
    not only one past the computer's total (#187)."""
    from craft_conductor import health
    hub, c = hub_env
    monkeypatch.setattr(health, "memory_available_gb", lambda: 0.5)
    plan = hub.memory_plan("alpha")
    assert plan["available_gb"] == 0.5 and plan["fits_free"] is False
    monkeypatch.setattr(health, "memory_available_gb", lambda: 64.0)
    assert hub.memory_plan("alpha")["fits_free"] is True
    monkeypatch.setattr(health, "memory_available_gb", lambda: None)  # (can't tell: no question)
    assert hub.memory_plan("alpha")["fits_free"] is True
