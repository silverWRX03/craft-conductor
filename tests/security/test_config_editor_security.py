"""Hardening of the config file editor (a server → Mods → a mod's config files): it reads and
writes only text config files physically inside the server's config folders."""

from __future__ import annotations

from pathlib import Path

import pytest

from craft_conductor import configs


@pytest.fixture
def server(tmp_path: Path) -> Path:
    sd = tmp_path / "server"
    (sd / "config").mkdir(parents=True)
    (sd / "config" / "mod.toml").write_text("a = 1\n")
    return sd


def _symlink(link: Path, target: Path, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"symlinks unavailable: {e}")


def test_a_level_name_outside_the_server_neither_crashes_the_list_nor_adds_outside_files(tmp_path: Path, server: Path) -> None:
    """level-name comes from server.properties (a modpack's server-overrides can set it). It used
    to add ``<server>/../outside/serverconfig`` to the editable folders, and the list crashed."""
    outside = tmp_path / "outside" / "serverconfig"
    outside.mkdir(parents=True)
    (outside / "elsewhere.toml").write_text("x = 1\n")
    (server / "server.properties").write_text("level-name=../outside\n")

    files = configs.list_files(server)

    assert "config/mod.toml" in files
    assert not any("elsewhere" in f for f in files)
    assert all(r.resolve().is_relative_to(server.resolve()) for r in configs.roots(server))


def test_a_config_folder_that_links_elsewhere_cannot_be_read_or_written(tmp_path: Path, server: Path) -> None:
    outside = tmp_path / "home"
    outside.mkdir()
    (outside / "secrets.json").write_text('{"token": "not-a-real-token"}')
    _symlink(server / "config" / "shared", outside, directory=True)

    with pytest.raises(configs.ConfigFileError, match="through a link"):
        configs.read(server, "config/shared/secrets.json")
    with pytest.raises(configs.ConfigFileError, match="through a link"):
        configs.write(server, server.parent / "bk", "config/shared/secrets.json", "{}")
    assert (outside / "secrets.json").read_text() == '{"token": "not-a-real-token"}'


def test_a_config_file_that_is_a_link_cannot_be_written(tmp_path: Path, server: Path) -> None:
    target = tmp_path / "victim.toml"
    target.write_text("keep = true\n")
    _symlink(server / "config" / "evil.toml", target)
    with pytest.raises(configs.ConfigFileError, match="through a link"):
        configs.write(server, server.parent / "bk", "config/evil.toml", "owned = true\n")
    assert target.read_text() == "keep = true\n"


def test_saving_never_writes_through_a_link_left_where_the_temporary_file_goes(tmp_path: Path, server: Path) -> None:
    target = tmp_path / "victim.txt"
    target.write_text("keep")
    _symlink(server / "config" / ".mod.toml.craft-conductor-tmp", target)

    configs.write(server, server.parent / "bk", "config/mod.toml", "a = 2\n")

    assert target.read_text() == "keep"
    assert (server / "config" / "mod.toml").read_text() == "a = 2\n"
    assert not (server / "config" / ".mod.toml.craft-conductor-tmp").exists()


def test_saving_a_file_with_brackets_in_its_name_keeps_other_files_backups(server: Path) -> None:
    """The old versions were found with a glob pattern: "[ab].toml" matched "a.toml"'s, and
    saving it deleted them."""
    (server / "config" / "a.toml").write_text("a = 1\n")
    (server / "config" / "[ab].toml").write_text("b = 1\n")
    backups = server.parent / "bk"
    backups.mkdir()
    for i in range(configs.KEEP_BACKUPS):
        (backups / f"config__a.toml.20200101-00000{i}").write_text("old")

    configs.write(server, backups, "config/[ab].toml", "b = 2\n")

    assert len(list(backups.glob("config__a.toml.*"))) == configs.KEEP_BACKUPS
    assert (server / "config" / "[ab].toml").read_text() == "b = 2\n"


@pytest.mark.parametrize("rel", ["config/a\x00.toml", "config/\x1b[31m.toml", "config/nul.toml", "config/con.json",
                                 "config/x.toml:stream", "../config/mod.toml", "/etc/passwd.toml", "config//mod.toml",
                                 "config/x.exe", "server.properties"])
def test_paths_that_arent_editable_config_files_are_refused_plainly(server: Path, rel: str) -> None:
    with pytest.raises(configs.ConfigFileError):
        configs.read(server, rel)


def test_odd_but_ordinary_config_names_still_work(server: Path) -> None:
    name = "config/my mod (1) [beta] ünï 日本.toml"
    (server / name).write_text("x = 1\n")
    assert configs.read(server, name)["text"] == "x = 1\n"
    configs.write(server, server.parent / "bk", name, "x = 2\n")
    assert (server / name).read_text() == "x = 2\n"


def test_the_list_shows_no_file_the_editor_would_refuse(tmp_path: Path, server: Path) -> None:
    outside = tmp_path / "shared"
    outside.mkdir()
    (outside / "shared.toml").write_text("s = 1\n")
    _symlink(server / "defaultconfigs", outside, directory=True)
    _symlink(server / "purpur.yml", outside / "shared.toml")

    files = configs.list_files(server)

    assert files == ["config/mod.toml"]
    for rel in files:
        configs.read(server, rel)
