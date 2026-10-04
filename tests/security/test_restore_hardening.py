"""Hardening of backups: restoring one never writes or links outside the server folder, never
fills the disk, and leaves the server exactly as it was whenever it can't finish. Making one
never leaves a half-written file taking up space."""

from __future__ import annotations

import errno
import io
import logging
import os
import tarfile
import time
from pathlib import Path

import pytest

from craft_conductor import backup, safearchive


def _tar(path: Path, members: list[tarfile.TarInfo | tuple[str, bytes]]) -> Path:
    with tarfile.open(path, "w:gz") as tar:
        server = tarfile.TarInfo("server")
        server.type = tarfile.DIRTYPE
        server.mode = 0o755
        tar.addfile(server)
        for m in members:
            if isinstance(m, tuple):
                info = tarfile.TarInfo(m[0])
                info.size = len(m[1])
                tar.addfile(info, io.BytesIO(m[1]))
            else:
                tar.addfile(m)
    return path


def _link(name: str, target: str, hard: bool = False) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = tarfile.LNKTYPE if hard else tarfile.SYMTYPE
    info.linkname = target
    return info


@pytest.fixture
def live(tmp_path: Path) -> Path:
    server = tmp_path / "server"
    server.mkdir()
    (server / "sentinel.txt").write_text("old")
    return server


def _untouched(server: Path) -> None:
    assert (server / "sentinel.txt").read_text() == "old", "the live server must be left as it was"
    assert not server.with_name("server.restoring").exists(), "the unpacked copy must be cleaned up"
    assert not server.with_name("server.replaced").exists()


def test_a_link_that_points_outside_the_server_once_moved_into_place_is_refused(tmp_path: Path, live: Path) -> None:
    """``server/escape -> ..`` stays inside the staging folder, so Python's own "data" filter
    allows it; once the server folder is moved into place it would point at its parent (every
    other server, craft-conductor.toml...)."""
    archive = _tar(tmp_path / "b.tar.gz", [("server/level.dat", b"new"), _link("server/escape", "..")])
    with tarfile.open(archive) as tar:
        member = tar.getmember("server/escape")
        tarfile.data_filter(member, str(tmp_path / "staging"))  # (the data filter alone lets it through)

    with pytest.raises(backup.RestoreError, match="outside the server folder"):
        backup.restore(archive, live)
    _untouched(live)


def test_a_hard_link_to_a_file_outside_the_server_folder_is_refused(tmp_path: Path, live: Path) -> None:
    archive = _tar(tmp_path / "b.tar.gz", [("other/secret.txt", b"secret"), _link("server/x", "other/secret.txt", hard=True)])
    with pytest.raises(backup.RestoreError, match="outside the server folder"):
        backup.restore(archive, live)
    _untouched(live)


def test_a_server_folder_that_is_itself_a_link_is_refused(tmp_path: Path, live: Path) -> None:
    archive = tmp_path / "b.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.addfile(_link("server", "."))
    with pytest.raises(backup.RestoreError):
        backup.restore(archive, live)
    _untouched(live)


def test_links_inside_the_server_folder_still_restore(tmp_path: Path, live: Path) -> None:
    try:
        (tmp_path / "probe").symlink_to(tmp_path)
    except (OSError, NotImplementedError) as e:  # (Windows without the right to make links)
        pytest.skip(f"symlinks unavailable: {e}")
    archive = _tar(tmp_path / "b.tar.gz", [("server/world/level.dat", b"lvl"), _link("server/latest", "world")])
    backup.restore(archive, live)
    assert (live / "latest").is_symlink() and (live / "latest" / "level.dat").read_bytes() == b"lvl"


def test_members_outside_the_server_folder_are_left_out_and_logged(tmp_path: Path, live: Path, caplog) -> None:
    archive = _tar(tmp_path / "b.tar.gz", [("server/level.dat", b"new"), ("notes.txt", b"hi"), ("./other/x", b"x")])
    with caplog.at_level(logging.WARNING):
        backup.restore(archive, live)
    assert (live / "level.dat").read_bytes() == b"new"
    assert not (tmp_path / "notes.txt").exists()
    assert any("left 2 file(s) out of the backup b.tar.gz" in r.getMessage() for r in caplog.records)


def test_a_backup_with_too_many_files_is_refused_part_way(tmp_path: Path, live: Path, monkeypatch) -> None:
    monkeypatch.setattr(backup, "MAX_RESTORE_MEMBERS", 5)
    archive = _tar(tmp_path / "b.tar.gz", [(f"server/f{i}", b"") for i in range(20)])
    with pytest.raises(backup.RestoreError, match="too big"):
        backup.restore(archive, live)
    _untouched(live)


def test_a_backup_bigger_than_the_free_disk_space_is_refused_before_unpacking(tmp_path: Path, live: Path, monkeypatch, caplog) -> None:
    archive = _tar(tmp_path / "b.tar.gz", [("server/level.dat", os.urandom(4096))])
    monkeypatch.setattr(safearchive, "free_bytes", lambda path: 100)
    with caplog.at_level(logging.WARNING), pytest.raises(backup.RestoreError, match="enough free disk space"):
        backup.restore(archive, live)
    _untouched(live)


def test_the_disk_filling_up_while_restoring_leaves_the_server_as_it_was(tmp_path: Path, live: Path, monkeypatch, caplog) -> None:
    archive = _tar(tmp_path / "b.tar.gz", [("server/level.dat", b"new"), ("server/region/r.0.0.mca", b"r" * 8192)])
    real = tarfile.copyfileobj

    def fill(src, dst, length=None, exception=OSError, bufsize=None):
        if length and length > 1000:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(src, dst, length, exception, bufsize)
    monkeypatch.setattr(tarfile, "copyfileobj", fill)

    with caplog.at_level(logging.ERROR), pytest.raises(backup.RestoreError, match="disk filled up") as e:
        backup.restore(archive, live)
    assert "left as it was" in str(e.value)
    _untouched(live)
    assert any("couldn't restore b.tar.gz" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("damage", ["truncate", "garbage", "empty"])
def test_a_damaged_backup_is_a_clear_error_and_the_server_is_kept(tmp_path: Path, live: Path, damage: str) -> None:
    archive = _tar(tmp_path / "b.tar.gz", [("server/level.dat", os.urandom(20000))])
    data = archive.read_bytes()
    archive.write_bytes({"truncate": data[: len(data) // 2], "garbage": b"\x1f\x8bnot really gzip" + data[20:],
                         "empty": b""}[damage])
    with pytest.raises(backup.RestoreError, match="damaged|cut short|isn't a Craft Conductor backup|can't be restored"):
        backup.restore(archive, live)
    _untouched(live)


def test_a_failed_swap_puts_the_old_server_folder_back(tmp_path: Path, live: Path, monkeypatch) -> None:
    archive = _tar(tmp_path / "b.tar.gz", [("server/level.dat", b"new")])
    real = Path.rename

    def rename(self, target):
        if self.name == "server" and self.parent.name == "server.restoring":
            raise OSError(errno.EACCES, "the file is in use")  # (Windows: a program has a file open)
        return real(self, target)
    monkeypatch.setattr(Path, "rename", rename)

    with pytest.raises(OSError):
        backup.restore(archive, live)
    _untouched(live)


def test_a_restore_cut_off_between_the_two_renames_is_put_right(tmp_path: Path) -> None:
    server = tmp_path / "server"
    aside = tmp_path / "server.replaced"
    aside.mkdir()
    (aside / "sentinel.txt").write_text("old")
    (tmp_path / "server.restoring" / "server").mkdir(parents=True)

    assert backup.recover(server)
    assert (server / "sentinel.txt").read_text() == "old"


def test_restore_after_an_interrupted_restore_keeps_the_only_good_copy(tmp_path: Path) -> None:
    """The old code deleted ``server.replaced`` first: after a cut-off swap that was the only
    copy of the server, and a damaged backup then lost everything."""
    server = tmp_path / "server"
    aside = tmp_path / "server.replaced"
    aside.mkdir()
    (aside / "sentinel.txt").write_text("old")
    damaged = tmp_path / "damaged.tar.gz"
    damaged.write_bytes(b"\x1f\x8b\x08\x00broken")

    with pytest.raises(backup.RestoreError):
        backup.restore(damaged, server)
    assert (server / "sentinel.txt").read_text() == "old"


# ------------------------------------------------------------------ create
def test_a_backup_that_fills_the_disk_removes_its_unfinished_file_and_says_so(tmp_path: Path, monkeypatch, caplog) -> None:
    server = tmp_path / "server"
    server.mkdir()
    (server / "level.dat").write_bytes(os.urandom(50_000))
    backups = tmp_path / "backups"
    real = tarfile.TarFile.addfile

    def addfile(self, tarinfo, fileobj=None):
        real(self, tarinfo, fileobj)
        if tarinfo.isfile():
            raise OSError(errno.ENOSPC, "No space left on device")
    monkeypatch.setattr(tarfile.TarFile, "addfile", addfile)

    with caplog.at_level(logging.ERROR), pytest.raises(OSError) as e:
        backup.create(server, backups, "scheduled", [])
    assert e.value.errno == errno.ENOSPC
    assert not list(backups.iterdir()), "the unfinished .part file must be removed to give the space back"
    assert any("the disk is full" in r.getMessage() for r in caplog.records)


def test_unfinished_backups_left_by_a_killed_run_are_cleaned_up_next_time(tmp_path: Path) -> None:
    server = tmp_path / "server"
    server.mkdir()
    (server / "level.dat").write_bytes(b"w")
    backups = tmp_path / "backups"
    backups.mkdir()
    stale = backups / "20200101-000000-chaos.tar.gz.part"
    stale.write_bytes(b"x" * 1000)
    old = time.time() - backup.STALE_PART - 60
    os.utime(stale, (old, old))
    fresh = backups / "20200101-000001-other.tar.gz.part"  # (perhaps still being written by another run)
    fresh.write_bytes(b"x")

    made = backup.create(server, backups, "next", [])

    assert made.exists() and not stale.exists() and fresh.exists()
    assert backup.list_backups(backups) == [made]


def test_a_member_that_steps_out_of_the_server_folder_and_back_into_staging_is_left_out(tmp_path: Path, live: Path) -> None:
    archive = _tar(tmp_path / "b.tar.gz", [("server/level.dat", b"new"), ("server/../stray.txt", b"stray")])
    backup.restore(archive, live)
    assert (live / "level.dat").read_bytes() == b"new"
    assert not (tmp_path / "stray.txt").exists() and not (live / "stray.txt").exists()
