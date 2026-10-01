from __future__ import annotations

import io
import json
import os
import stat
import tarfile
import zipfile
from pathlib import Path

import pytest

from craft_conductor import backup, modpack, world


def _write_zip(path: Path, files: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


def _write_world_zip(path: Path, extra: dict[str, bytes] | None = None) -> Path:
    files = {"world/level.dat": b"corrupt-but-present"}
    files.update(extra or {})
    return _write_zip(path, files)


def _modrinth_index() -> dict:
    return {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": "security-test",
        "name": "Security Test Pack",
        "dependencies": {
            "minecraft": "1.21.1",
            "fabric-loader": "0.16.0",
        },
        "files": [],
    }


def _write_modpack(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("modrinth.index.json", json.dumps(_modrinth_index()))
        for name, data in entries.items():
            z.writestr(name, data)
    return path


def _add_tar_bytes(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


def test_world_zip_slip_cannot_escape_destination(tmp_path: Path) -> None:
    archive = _write_world_zip(
        tmp_path / "world.zip",
        {
            "world/region/r.0.0.mca": b"safe",
            "world/../../escaped.txt": b"owned",
            "world/../sibling.txt": b"owned",
        },
    )
    dest = tmp_path / "server" / "world"

    world.install(archive, dest)

    assert (dest / "region" / "r.0.0.mca").read_bytes() == b"safe"
    assert not (tmp_path / "escaped.txt").exists(), "zip-slip wrote outside the world destination"
    assert not (dest.parent / "sibling.txt").exists(), ".. traversal escaped the world destination"


def test_world_absolute_and_drive_paths_are_ignored(tmp_path: Path) -> None:
    archive = _write_world_zip(
        tmp_path / "absolute.zip",
        {
            "world//tmp/craft-conductor-owned": b"unix-absolute",
            "world/C:/Windows/Temp/craft-conductor-owned": b"windows-drive",
            r"world/\\server\share\craft-conductor-owned": b"unc",
            "world/safe.txt": b"safe",
        },
    )
    dest = tmp_path / "world"

    world.install(archive, dest)

    assert (dest / "safe.txt").read_bytes() == b"safe"
    assert not (dest / "tmp" / "craft-conductor-owned").exists()
    assert not (dest / "C:" / "Windows" / "Temp" / "craft-conductor-owned").exists()
    assert not (dest / "server" / "share" / "craft-conductor-owned").exists()


def test_world_zip_symlink_entry_is_materialized_as_plain_data(tmp_path: Path) -> None:
    archive = tmp_path / "symlink.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("world/level.dat", b"corrupt-but-present")
        link = zipfile.ZipInfo("world/link")
        link.create_system = 3  # Unix metadata.
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(link, "../../outside.txt")

    dest = tmp_path / "world"
    world.install(archive, dest)

    extracted = dest / "link"
    assert extracted.exists()
    assert not extracted.is_symlink(), "archive-controlled symlinks must never be created"
    assert extracted.read_text() == "../../outside.txt"
    assert not (tmp_path / "outside.txt").exists()


def test_world_compressed_bomb_is_rejected_before_extraction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Lower the production limit so this test exercises the same branch without allocating gigabytes.
    monkeypatch.setattr(world, "MAX_WORLD", 1024)
    archive = _write_world_zip(
        tmp_path / "bomb.zip",
        {"world/region/highly-compressible.mca": b"\0" * 4096},
    )
    dest = tmp_path / "world"

    assert archive.stat().st_size < 1024, "fixture should behave like a compression bomb"
    with pytest.raises(world.WorldError, match="too big"):
        world.install(archive, dest)

    assert not dest.exists(), "a rejected archive must not leave a partially imported world"
    assert not dest.with_name(f".{dest.name}.importing").exists()


def test_world_safe_special_characters_round_trip(tmp_path: Path) -> None:
    odd_name = "region/space (1) [copy] naïve_日本_💾.dat"
    archive = _write_world_zip(tmp_path / "unicode.zip", {f"world/{odd_name}": b"ok"})
    dest = tmp_path / "world"

    world.install(archive, dest)

    assert (dest / odd_name).read_bytes() == b"ok"


def test_modpack_override_zip_slip_and_absolute_paths_are_ignored(
    tmp_path: Path, make_config, http
) -> None:
    cfg = make_config()
    pack = _write_modpack(
        tmp_path / "malicious.mrpack",
        {
            "overrides/config/safe.txt": b"safe",
            "overrides/../../escaped.txt": b"owned",
            "overrides//tmp/craft-conductor-owned": b"owned",
            "server-overrides/C:/Windows/Temp/craft-conductor-owned": b"owned",
        },
    )

    modpack.apply_file(cfg.root, pack, http)

    assert (cfg.server.dir / "config" / "safe.txt").read_bytes() == b"safe"
    assert not (cfg.root / "escaped.txt").exists()
    assert not (cfg.server.dir / "tmp" / "craft-conductor-owned").exists()
    assert not (cfg.server.dir / "C:" / "Windows" / "Temp" / "craft-conductor-owned").exists()


def test_modpack_override_cannot_follow_preexisting_symlink(
    tmp_path: Path, make_config, http
) -> None:
    cfg = make_config()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = cfg.server.dir / "config"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation is unavailable on this platform: {exc}")

    pack = _write_modpack(
        tmp_path / "symlink-parent.mrpack",
        {"overrides/config/owned.txt": b"owned"},
    )

    modpack.apply_file(cfg.root, pack, http)

    assert not (outside / "owned.txt").exists(), "override extraction followed a symlink outside server.dir"


@pytest.mark.xfail(
    reason=(
        "Known security gap on current main: modpack overrides have a compressed-file cap but no "
        "total uncompressed extraction cap. Remove this xfail after adding an expansion limit."
    ),
    strict=False,
)
def test_modpack_override_zip_bomb_requires_uncompressed_limit(
    tmp_path: Path, make_config, http, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = make_config()
    # This is a test-scale stand-in for a many-gigabyte expansion bomb.
    monkeypatch.setattr(modpack, "MAX_UNPACKED_PACK", 1 << 20, raising=False)
    pack = _write_modpack(
        tmp_path / "override-bomb.mrpack",
        {"overrides/config/bomb.bin": b"\0" * (2 << 20)},
    )
    assert pack.stat().st_size < (64 << 10), "fixture should have a high compression ratio"

    with pytest.raises(modpack.ModpackError, match="too big|uncompressed|expand"):
        modpack.apply_file(cfg.root, pack, http)

    assert not (cfg.server.dir / "config" / "bomb.bin").exists()


def test_backup_restore_rejects_tar_path_traversal_without_touching_live_server(tmp_path: Path) -> None:
    server = tmp_path / "server"
    server.mkdir()
    (server / "sentinel.txt").write_text("old")
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        _add_tar_bytes(tar, "server/level.dat", b"new")
        _add_tar_bytes(tar, "server/../../escaped.txt", b"owned")

    with pytest.raises(tarfile.FilterError):
        backup.restore(archive, server)

    assert (server / "sentinel.txt").read_text() == "old"
    assert not (tmp_path / "escaped.txt").exists()


def test_backup_restore_absolute_member_cannot_overwrite_outside_restore(tmp_path: Path) -> None:
    server = tmp_path / "server"
    server.mkdir()
    (server / "sentinel.txt").write_text("old")
    outside = tmp_path.parent / f"craft-conductor-absolute-{tmp_path.name}"
    outside.unlink(missing_ok=True)
    archive = tmp_path / "absolute.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        _add_tar_bytes(tar, "server/level.dat", b"new")
        _add_tar_bytes(tar, str(outside), b"owned")

    # Python's tarfile data filter may reject an absolute member or sanitize it by
    # stripping the leading separator. Either behavior is safe as long as the member
    # cannot write outside the restore staging directory.
    try:
        backup.restore(archive, server)
    except tarfile.FilterError:
        pass

    assert not outside.exists(), "an absolute tar member wrote outside the restore staging directory"


def test_backup_restore_rejects_link_outside_destination(tmp_path: Path) -> None:
    server = tmp_path / "server"
    server.mkdir()
    (server / "sentinel.txt").write_text("old")
    archive = tmp_path / "symlink.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        _add_tar_bytes(tar, "server/level.dat", b"new")
        link = tarfile.TarInfo("server/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside.txt"
        tar.addfile(link)

    with pytest.raises(tarfile.FilterError):
        backup.restore(archive, server)

    assert (server / "sentinel.txt").read_text() == "old"
    assert not (tmp_path / "outside.txt").exists()


def test_backup_label_special_characters_cannot_escape_backup_directory(tmp_path: Path) -> None:
    server = tmp_path / "server"
    server.mkdir()
    (server / "world.dat").write_bytes(b"world")
    backups = tmp_path / "backups"

    made = backup.create(server, backups, "../../evil 😈 : * ? [manual]", exclude=[])

    assert made.parent.resolve() == backups.resolve()
    assert made.exists()
    assert os.sep not in made.name
    assert "/" not in made.name and "\\" not in made.name
    assert made.name.endswith(backup.SUFFIX)


@pytest.mark.xfail(
    reason=(
        "Known security gap on current main: backup.restore() relies on tarfile's path/link filter "
        "but does not cap total uncompressed bytes. Remove this xfail after adding a restore-size limit."
    ),
    strict=False,
)
def test_backup_restore_bomb_requires_uncompressed_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backup, "MAX_RESTORE_BYTES", 1 << 20, raising=False)
    archive = tmp_path / "restore-bomb.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        _add_tar_bytes(tar, "server/level.dat", b"new")
        _add_tar_bytes(tar, "server/region/bomb.bin", b"\0" * (2 << 20))
    assert archive.stat().st_size < (64 << 10), "fixture should have a high compression ratio"

    server = tmp_path / "server"
    server.mkdir()
    (server / "sentinel.txt").write_text("old")

    with pytest.raises((ValueError, tarfile.TarError), match="too big|uncompressed|size|limit"):
        backup.restore(archive, server)

    assert (server / "sentinel.txt").read_text() == "old"
