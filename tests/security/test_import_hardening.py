"""Hardening of everything that unpacks a file someone gave us: a world (.zip or a singleplayer
folder), a Modrinth modpack (.mrpack), and a whole server exported from another computer.

Each hostile input must be refused or left out, never written outside its folder, and say why
in the log (one line per archive, with control characters escaped)."""

from __future__ import annotations

import json
import logging
import os
import struct
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from craft_conductor import config as configmod, modpack, safearchive, transfer, world

UNSAFE_NAMES = [
    "../../escaped.txt",              # zip-slip
    "/tmp/craft-conductor-owned",     # absolute (Unix)
    "C:/Windows/owned.txt",           # drive letter
    "\\\\server\\share\\owned.txt",   # UNC
    "region/NUL",                     # Windows device
    "region/com1.mca",                # Windows device, with an extension
    "level.dat:hidden",               # Windows alternate data stream
    "region/trailing./r.0.0.mca",     # Windows drops the dot: two names become one
    "region/bell\x07.mca",            # control character
    "a//b.dat",                       # empty folder name
]
ODD_BUT_FINE = ["region/space (1) [copy] naïve_日本_💾.dat", "data/it's #1 & 100%.dat", "data/ünïcödé/ДАННЫЕ.nbt"]


def _zip(path: Path, files: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


# ------------------------------------------------------------------ names
@pytest.mark.parametrize("name", UNSAFE_NAMES)
def test_every_unsafe_name_is_refused_with_a_reason(name: str) -> None:
    with pytest.raises(safearchive.UnsafeName) as e:
        safearchive.parts(name)
    assert str(e.value), "a refusal must say why"


@pytest.mark.parametrize("name", ODD_BUT_FINE + ["./region/r.0.0.mca", "region\\r.0.0.mca", ".hidden/ok.txt"])
def test_unusual_but_harmless_names_are_kept(name: str) -> None:
    assert safearchive.parts(name)


def test_log_lines_escape_control_and_direction_characters() -> None:
    shown = safearchive.printable("evil\x1b[31m\u202egpj.exe\n")
    assert "\x1b" not in shown and "\u202e" not in shown and "\n" not in shown
    assert "\\u001b" in shown and "\\u202e" in shown


# ------------------------------------------------------------------ world
def test_world_zip_leaves_out_every_unsafe_name_and_logs_once(tmp_path: Path, caplog) -> None:
    files = {"world/level.dat": b"x", **{f"world/{n}": b"owned" for n in UNSAFE_NAMES},
             **{f"world/{n}": b"fine" for n in ODD_BUT_FINE}}
    archive = _zip(tmp_path / "hostile.zip", files)
    dest = tmp_path / "server" / "world"

    with caplog.at_level(logging.WARNING):
        world.install(archive, dest)

    for n in ODD_BUT_FINE:
        assert (dest / n).read_bytes() == b"fine"
    unpacked = [p for p in tmp_path.rglob("*") if p.is_file() and p != archive]
    assert not [p for p in unpacked if p.read_bytes() == b"owned"], "an unsafe member was written somewhere"
    warnings = [w for w in _warnings(caplog) if "left" in w and "hostile.zip" in w]
    assert len(warnings) == 1, "one warning per archive, not one per member"
    assert f"left {len(UNSAFE_NAMES)} file(s) out" in warnings[0]
    assert "\x07" not in warnings[0], "control characters must be escaped in logs"


def test_world_zip_with_a_file_where_a_folder_should_be_is_handled(tmp_path: Path, caplog) -> None:
    archive = _zip(tmp_path / "clash.zip", {"world/level.dat": b"x", "world/region": b"a file",
                                            "world/region/r.0.0.mca": b"data"})
    dest = tmp_path / "world"
    with caplog.at_level(logging.WARNING):
        world.install(archive, dest)  # no raw NotADirectoryError
    assert (dest / "level.dat").exists()
    assert any("clash.zip" in w for w in _warnings(caplog))


def test_world_zip_with_too_many_files_is_refused_before_it_is_opened(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(world, "MAX_WORLD_FILES", 10)
    archive = _zip(tmp_path / "many.zip", {"world/level.dat": b"x", **{f"world/data/{i}.dat": b"" for i in range(50)}})

    def must_not_open(*a, **k):
        raise AssertionError("the member list was loaded before the count was checked")
    monkeypatch.setattr(zipfile, "ZipFile", must_not_open)

    with pytest.raises(world.WorldError, match="too many files"):
        world.install(archive, tmp_path / "world")
    assert not (tmp_path / "world").exists()


def test_world_zip_that_understates_its_file_count_is_still_refused(tmp_path: Path, monkeypatch) -> None:
    """zipfile reads the member list by its size, not the count in the end record: a zip that
    claims one member but lists thousands must not get through."""
    monkeypatch.setattr(world, "MAX_WORLD_FILES", 10)
    archive = _zip(tmp_path / "liar.zip", {"world/level.dat": b"x",
                                          **{f"world/data/{i:04}.dat": b"" for i in range(200)}})
    data = bytearray(archive.read_bytes())
    end = data.rfind(b"PK\x05\x06")
    data[end + 8:end + 12] = struct.pack("<HH", 1, 1)  # "1 member on this disk, 1 in total"
    archive.write_bytes(bytes(data))
    assert safearchive.zip_entries(archive)[0] == 1

    with pytest.raises(world.WorldError, match="too many files"):
        world.install(archive, tmp_path / "world")


def test_world_zip_larger_than_the_free_disk_space_is_refused(tmp_path: Path, monkeypatch, caplog) -> None:
    archive = _zip(tmp_path / "big.zip", {"world/level.dat": b"x", "world/region/r.0.0.mca": b"\0" * 4096})
    monkeypatch.setattr(safearchive, "free_bytes", lambda path: 1000)
    with caplog.at_level(logging.WARNING), pytest.raises(world.WorldError, match="enough free disk space"):
        world.install(archive, tmp_path / "world")
    assert not (tmp_path / "world").exists()
    assert any("refused to unpack" in w for w in _warnings(caplog))


def test_world_zip_that_is_not_a_zip_is_a_clear_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"this is not a zip at all")
    with pytest.raises(world.WorldError, match="isn't a .zip"):
        world.install(bad, tmp_path / "world")


def test_singleplayer_world_folder_copy_leaves_links_out(tmp_path: Path, caplog) -> None:
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "id_rsa").write_text("PRIVATE")
    save = tmp_path / "saves" / "My World"
    (save / "region").mkdir(parents=True)
    (save / "level.dat").write_bytes(b"x")
    (save / "region" / "r.0.0.mca").write_bytes(b"region")
    try:
        (save / "keys").symlink_to(secret / "id_rsa")
        (save / "home").symlink_to(secret, target_is_directory=True)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"symlinks unavailable: {e}")
    dest = tmp_path / "server" / "world"

    with caplog.at_level(logging.WARNING):
        world.install(save, dest)

    assert (dest / "region" / "r.0.0.mca").read_bytes() == b"region"
    assert not (dest / "keys").exists() and not (dest / "home").exists()
    assert not any("PRIVATE" in p.read_text(errors="ignore") for p in dest.rglob("*") if p.is_file())
    assert any("left 2 link(s) out" in w for w in _warnings(caplog))


@pytest.mark.parametrize("level", ["../outside", "..", "a/b", "C:\\Windows", ".hidden", "NUL", "world\x00"])
def test_level_name_outside_the_server_is_refused(tmp_path: Path, level: str) -> None:
    server = tmp_path / "server"
    server.mkdir()
    (server / "server.properties").write_text(f"level-name={level}\n")
    with pytest.raises(world.WorldError, match="plain folder name"):
        world.level_dir(server)


def test_replace_world_never_moves_or_deletes_a_folder_outside_the_server(tmp_path: Path) -> None:
    """level-name comes from server.properties, which a modpack's server-overrides, an imported
    server or a restored backup can bring. Replacing the world used to rename the folder it names
    aside and delete it."""
    from craft_conductor.web import Api

    server = tmp_path / "root" / "server"
    server.mkdir(parents=True)
    victim = tmp_path / "root" / "precious"
    victim.mkdir()
    (victim / "keep.txt").write_text("keep")
    (server / "server.properties").write_text("level-name=../precious\n")
    upload = _zip(tmp_path / "new.zip", {"world/level.dat": b"x"})

    api = Api.__new__(Api)
    api.d = SimpleNamespace(state="stopped", m=SimpleNamespace(server_dir=server, config=SimpleNamespace()))
    api.web = SimpleNamespace(hub=SimpleNamespace(world_source=lambda choice: upload, staging_dir=tmp_path / "st"))
    jobs = []
    api._job = lambda name, fn: jobs.append(fn)

    with pytest.raises(world.WorldError, match="plain folder name"):
        api.replace_world({}, {"world": "0123456789abcdef"})

    assert not jobs, "the job must not even start"
    assert (victim / "keep.txt").read_text() == "keep"


def test_an_interrupted_world_replace_puts_the_old_world_back(tmp_path: Path) -> None:
    dest = tmp_path / "server" / "world"
    old = dest.with_name(".world.replaced")
    old.mkdir(parents=True)
    (old / "level.dat").write_bytes(b"old world")

    assert world.recover(dest)
    assert (dest / "level.dat").read_bytes() == b"old world"
    assert not old.exists()
    assert not world.recover(dest), "nothing to do the second time"


# ---------------------------------------------------------------- modpack
def _modrinth_index(**extra) -> dict:
    return {"formatVersion": 1, "game": "minecraft", "versionId": "t", "name": "Test Pack",
            "dependencies": {"minecraft": "1.21.1", "fabric-loader": "0.16.0"}, "files": [], **extra}


def _pack(path: Path, entries: dict[str, bytes], index: object | None = None) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("modrinth.index.json", json.dumps(index if index is not None else _modrinth_index()))
        for name, data in entries.items():
            z.writestr(name, data)
    return path


def test_modpack_overrides_leave_out_unsafe_names_keep_odd_ones_and_log(tmp_path, make_config, http, caplog) -> None:
    cfg = make_config()
    pack = _pack(tmp_path / "p.mrpack", {**{f"overrides/{n}": b"owned" for n in UNSAFE_NAMES},
                                          **{f"overrides/config/{n}": b"fine" for n in ODD_BUT_FINE}})
    with caplog.at_level(logging.WARNING):
        result = modpack.apply_file(cfg.root, pack, http)

    assert result["overrides"] == len(ODD_BUT_FINE)
    for n in ODD_BUT_FINE:
        assert (cfg.server.dir / "config" / n).read_bytes() == b"fine"
    assert not (cfg.root / "escaped.txt").exists() and not (tmp_path / "escaped.txt").exists()
    assert any(f"left {len(UNSAFE_NAMES)} file(s) out of the modpack" in w for w in _warnings(caplog))


def test_modpack_too_big_is_refused_before_the_server_settings_change(tmp_path, make_config, http, monkeypatch) -> None:
    cfg = make_config()
    before = cfg.path.read_text()
    monkeypatch.setattr(modpack, "MAX_UNPACKED_PACK", 1 << 20)
    index = _modrinth_index(dependencies={"minecraft": "1.20.4", "neoforge": "20.4.1"})
    pack = _pack(tmp_path / "bomb.mrpack", {"overrides/config/bomb.bin": b"\0" * (2 << 20)}, index)

    with pytest.raises(modpack.ModpackError, match="too big"):
        modpack.apply_file(cfg.root, pack, http)

    assert cfg.path.read_text() == before, "a refused modpack must not switch the loader or Minecraft version"
    assert not (cfg.server.dir / "config" / "bomb.bin").exists()


def test_modpack_with_too_many_files_is_refused(tmp_path, make_config, http, monkeypatch) -> None:
    cfg = make_config()
    monkeypatch.setattr(modpack, "MAX_PACK_FILES", 5)
    pack = _pack(tmp_path / "many.mrpack", {f"overrides/config/{i}.toml": b"" for i in range(20)})
    with pytest.raises(modpack.ModpackError, match="too many files"):
        modpack.apply_file(cfg.root, pack, http)


def test_modpack_larger_than_the_free_disk_space_is_refused(tmp_path, make_config, http, monkeypatch) -> None:
    cfg = make_config()
    before = cfg.path.read_text()
    monkeypatch.setattr(safearchive, "free_bytes", lambda path: 10)
    pack = _pack(tmp_path / "p.mrpack", {"overrides/config/a.toml": b"a = 1"})
    with pytest.raises(modpack.ModpackError, match="enough free disk space"):
        modpack.apply_file(cfg.root, pack, http)
    assert cfg.path.read_text() == before


@pytest.mark.parametrize("index", [[], "text", {"game": "minecraft", "files": "x"},
                                   {"game": "minecraft", "files": ["not a dict"]},
                                   {"game": "minecraft", "dependencies": ["minecraft"]}])
def test_modpack_with_a_malformed_index_is_a_clear_error(tmp_path, make_config, http, index) -> None:
    cfg = make_config()
    with pytest.raises(modpack.ModpackError, match="damaged|isn't a Modrinth modpack"):
        modpack.apply_file(cfg.root, _pack(tmp_path / "m.mrpack", {}, index), http)


def test_a_file_that_isnt_a_modpack_is_a_clear_error(tmp_path, make_config, http) -> None:
    cfg = make_config()
    bad = tmp_path / "bad.mrpack"
    bad.write_bytes(b"not a zip")
    with pytest.raises(modpack.ModpackError, match="damaged"):
        modpack.apply_file(cfg.root, bad, http)


def test_modpack_downloads_to_unsafe_paths_are_never_fetched(tmp_path, make_config, http, caplog) -> None:
    import hashlib
    cfg = make_config()
    body = b"jar"
    files = [{"path": p, "hashes": {"sha1": hashlib.sha1(body).hexdigest()},
              "downloads": ["https://github.com/example/x/releases/download/1/x.jar"]}
             for p in ("../../evil.jar", "/abs/evil.jar", "mods/NUL.jar", "mods/x.jar:stream")]
    http.files["https://github.com/example/x/releases/download/1/x.jar"] = body
    pack = _pack(tmp_path / "d.mrpack", {}, _modrinth_index(files=files))

    with caplog.at_level(logging.WARNING):
        result = modpack.apply_file(cfg.root, pack, http)

    assert result["files"] == 0 and not http.downloads
    assert any("left 4 file(s) out of the downloads listed by the modpack" in w for w in _warnings(caplog))


# --------------------------------------------------- server export import
def _export(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(transfer.MANIFEST, json.dumps({"format": transfer.FORMAT, "name": "Imported"}))
        z.writestr(configmod.CONFIG_NAME, configmod.render_template("fabric", "1.21.1"))
        for name, data in entries.items():
            z.writestr(name, data)
    return path


def test_server_import_leaves_out_unsafe_names_and_logs_once(tmp_path: Path, caplog) -> None:
    archive = _export(tmp_path / "e.craft-conductor.zip",
                      {"server/eula.txt": b"eula=true", **{f"server/{n}": b"owned" for n in UNSAFE_NAMES},
                       "elsewhere/file.txt": b"owned", **{f"server/{n}": b"fine" for n in ODD_BUT_FINE}})
    root = tmp_path / "servers" / "imported"

    with caplog.at_level(logging.WARNING):
        transfer.import_into(archive, root)

    for n in ODD_BUT_FINE:
        assert (root / "server" / n).read_bytes() == b"fine"
    assert not (root / "elsewhere").exists()
    assert not (tmp_path / "escaped.txt").exists() and not (tmp_path / "servers" / "escaped.txt").exists()
    warnings = [w for w in _warnings(caplog) if "e.craft-conductor.zip" in w]
    assert len(warnings) == 1 and f"left {len(UNSAFE_NAMES) + 1} file(s) out" in warnings[0]


def test_server_import_too_big_is_refused_before_writing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(transfer, "MAX_IMPORT", 1 << 20)
    archive = _export(tmp_path / "bomb.craft-conductor.zip", {"server/world/region/r.0.0.mca": b"\0" * (2 << 20)})
    root = tmp_path / "servers" / "bomb"
    with pytest.raises(transfer.TransferError, match="too big"):
        transfer.import_into(archive, root)
    assert not root.exists()


def test_server_import_larger_than_the_free_disk_space_is_refused(tmp_path: Path, monkeypatch) -> None:
    archive = _export(tmp_path / "e.craft-conductor.zip", {"server/eula.txt": b"eula=true"})
    monkeypatch.setattr(safearchive, "free_bytes", lambda path: 10)
    with pytest.raises(transfer.TransferError, match="enough free disk space"):
        transfer.import_into(archive, tmp_path / "servers" / "x")
    assert not (tmp_path / "servers" / "x").exists()


def test_server_import_with_too_many_files_is_refused(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(transfer, "MAX_IMPORT_FILES", 5)
    archive = _export(tmp_path / "e.craft-conductor.zip", {f"server/f{i}": b"" for i in range(20)})
    with pytest.raises(transfer.TransferError, match="too many files"):
        transfer.read_manifest(archive)


def test_a_world_zipped_with_backslashes_imports(tmp_path: Path) -> None:
    """Some Windows tools write "world\\level.dat" instead of "world/level.dat"."""
    archive = _zip(tmp_path / "win.zip", {"My World\\level.dat": b"x", "My World\\region\\r.0.0.mca": b"r"})
    dest = tmp_path / "world"
    world.install(archive, dest)
    assert (dest / "region" / "r.0.0.mca").read_bytes() == b"r"


@pytest.mark.skipif(os.name == "nt", reason="Windows has no Unix permission bits")
def test_unpacked_files_are_only_yours_even_with_a_zero_umask(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "w.zip", {"world/level.dat": b"x"})
    old = os.umask(0)
    try:
        world.install(archive, tmp_path / "world")
    finally:
        os.umask(old)
    assert (tmp_path / "world" / "level.dat").stat().st_mode & 0o777 == 0o600
