from __future__ import annotations

import errno
import hashlib
import os
import subprocess
import sys
import textwrap
import time
import zipfile
from pathlib import Path

import pytest

from craft_conductor import backup, selfupdate, world


def _pythonpath_env() -> dict[str, str]:
    env = dict(os.environ)
    repo = Path(__file__).resolve().parents[2]
    src = repo / "src"
    env["PYTHONPATH"] = str(src) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def _wait_for(path: Path, proc: subprocess.Popen, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        if proc.poll() is not None:
            raise AssertionError(f"chaos worker exited early with {proc.returncode}")
        time.sleep(0.02)
    proc.kill()
    proc.wait(timeout=5)
    raise AssertionError(f"chaos worker never reached synchronization point: {path}")


def test_process_kill_during_backup_never_publishes_partial_archive(tmp_path: Path) -> None:
    server = tmp_path / "server"
    server.mkdir()
    (server / "level.dat").write_bytes(b"world")
    backups = tmp_path / "backups"
    marker = tmp_path / "backup-opened"

    worker = textwrap.dedent(
        """
        import sys, tarfile, time
        from pathlib import Path
        from craft_conductor import backup

        server, backups, marker = map(Path, sys.argv[1:4])
        original_add = tarfile.TarFile.add

        def stall(self, *args, **kwargs):
            marker.write_text("ready")
            time.sleep(60)
            return original_add(self, *args, **kwargs)

        tarfile.TarFile.add = stall
        backup.create(server, backups, "chaos", [])
        """
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", worker, str(server), str(backups), str(marker)],
        env=_pythonpath_env(),
    )
    try:
        _wait_for(marker, proc)
        proc.kill()
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)

    assert backup.list_backups(backups) == [], "a killed backup must not appear as a valid restore point"
    assert not list(backups.glob("*.tar.gz")), "the final archive name must only appear after a successful close"
    assert list(backups.glob("*.part")), "an abrupt kill may leave a clearly incomplete .part file"
    assert (server / "level.dat").read_bytes() == b"world"


def test_process_kill_during_self_update_download_keeps_current_binary(tmp_path: Path) -> None:
    exe = tmp_path / ("craft-conductor.exe" if os.name == "nt" else "craft-conductor")
    exe.write_bytes(b"CURRENT-BINARY")
    marker = tmp_path / "new-binary-downloaded"

    worker = textwrap.dedent(
        """
        import hashlib, sys, time
        from pathlib import Path
        from craft_conductor import selfupdate

        exe, marker = map(Path, sys.argv[1:3])
        name = selfupdate.asset_name()
        new_bytes = b"NEW-BINARY"
        digest = hashlib.sha256(new_bytes).hexdigest()
        release = selfupdate.Release(
            version="99.0.0",
            tag="v99.0.0",
            url="https://example.invalid/release",
            notes="",
            assets={name: "asset://binary", "SHA256SUMS.txt": "asset://sums"},
        )

        class Http:
            def download(self, url, dest, sha256=None, max_bytes=None):
                dest.parent.mkdir(parents=True, exist_ok=True)
                if url == "asset://sums":
                    dest.write_text(f"{digest}  {name}\\n")
                    return dest
                dest.write_bytes(new_bytes)
                if sha256 and hashlib.sha256(new_bytes).hexdigest() != sha256:
                    raise AssertionError("hash mismatch in test fixture")
                marker.write_text("ready")
                time.sleep(60)  # parent kills us before install_binary can swap files
                return dest

        selfupdate.install_binary(release, exe, Http())
        """
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", worker, str(exe), str(marker)],
        env=_pythonpath_env(),
    )
    try:
        _wait_for(marker, proc)
        proc.kill()
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)

    assert exe.read_bytes() == b"CURRENT-BINARY", "the running binary changed before the verified swap point"


def test_full_disk_during_world_write_cleans_staging_and_keeps_destination_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "world.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("world/level.dat", b"corrupt-but-present")
        z.writestr("world/region/r.0.0.mca", b"x" * 4096)

    def no_space(src, dst, length=0):
        chunk = src.read(32)
        if chunk:
            dst.write(chunk)
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(world.shutil, "copyfileobj", no_space)
    dest = tmp_path / "server" / "world"

    with pytest.raises(OSError) as exc:
        world.install(archive, dest)

    assert exc.value.errno == errno.ENOSPC
    assert not dest.exists(), "a failed world write must not publish a partial destination"
    assert not dest.with_name(f".{dest.name}.importing").exists(), "staging should be cleaned after ENOSPC"


def test_corrupted_world_archive_is_reported_and_does_not_replace_destination(tmp_path: Path) -> None:
    source = tmp_path / "corrupt.zip"
    source.write_bytes(b"PK\x03\x04truncated-not-a-valid-zip")
    dest = tmp_path / "world"

    with pytest.raises(world.WorldError, match="damaged|isn't a .zip"):
        world.install(source, dest)

    assert not dest.exists()
    assert not dest.with_name(f".{dest.name}.importing").exists()


def test_corrupted_level_dat_is_nonfatal_metadata_failure() -> None:
    assert world.level_info(b"not-gzip-not-nbt") == {}


def test_failed_backup_write_never_becomes_listed_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fault injection complements the SIGKILL test and verifies the naming/visibility invariant."""
    import tarfile

    server = tmp_path / "server"
    server.mkdir()
    (server / "level.dat").write_bytes(b"world")
    backups = tmp_path / "backups"

    def abort(*args, **kwargs):
        raise KeyboardInterrupt("simulated abrupt termination")

    monkeypatch.setattr(tarfile.TarFile, "add", abort)

    with pytest.raises(KeyboardInterrupt):
        backup.create(server, backups, "chaos", [])

    assert backup.list_backups(backups) == []
    assert not list(backups.glob("*.tar.gz"))
    # Unlike a SIGKILL (above), an exception lets create() remove its unfinished file, so a
    # failure (a full disk especially) doesn't keep the space.
    assert not list(backups.glob("*.part"))


def test_self_update_hash_mismatch_never_replaces_binary(tmp_path: Path) -> None:
    exe = tmp_path / "craft-conductor"
    exe.write_bytes(b"CURRENT")
    name = selfupdate.asset_name()
    release = selfupdate.Release(
        version="99.0.0",
        tag="v99.0.0",
        url="https://example.invalid/release",
        notes="",
        assets={name: "asset://binary", "SHA256SUMS.txt": "asset://sums"},
    )

    class HashMismatchHttp:
        def download(self, url, dest, sha256=None, max_bytes=None):
            if url == "asset://sums":
                dest.write_text(f"{'0' * 64}  {name}\n")
                return dest
            data = b"TAMPERED"
            if sha256 and hashlib.sha256(data).hexdigest() != sha256:
                from craft_conductor.http import HashMismatch
                raise HashMismatch(url)
            dest.write_bytes(data)
            return dest

    with pytest.raises(Exception):
        selfupdate.install_binary(release, exe, HashMismatchHttp())

    assert exe.read_bytes() == b"CURRENT"
