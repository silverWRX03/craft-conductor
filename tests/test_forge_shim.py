"""Forge for Minecraft 26.x starts through a jar the installer leaves in the server's folder."""

from craft_conductor.loaders import forge


def _installed(tmp_path, args_line):
    args = "libraries/net/minecraftforge/forge/26.3-66.0.12/win_args.txt"
    (tmp_path / args).parent.mkdir(parents=True)
    (tmp_path / args).write_text(args_line)
    return args


def test_the_jar_the_args_file_launches_is_kept_with_the_loader(tmp_path):
    (tmp_path / "forge-26.3-66.0.12-shim.jar").write_bytes(b"jar")
    args = _installed(tmp_path, "-DlibraryDirectory=libraries --add-modules ALL-MODULE-PATH -jar forge-26.3-66.0.12-shim.jar\n")
    assert forge.installer_files(tmp_path, args) == [*forge.INSTALLER_FILES, "forge-26.3-66.0.12-shim.jar"]


def test_older_forge_keeps_only_the_usual_files(tmp_path):
    args = _installed(tmp_path, "-DlibraryDirectory=libraries cpw.mods.bootstraplauncher.BootstrapLauncher\n")
    assert forge.installer_files(tmp_path, args) == forge.INSTALLER_FILES


def test_a_jar_that_is_missing_or_outside_the_folder_is_not_listed(tmp_path):
    args = _installed(tmp_path, "-jar gone-shim.jar -jar ../evil.jar -jar libraries/x.jar\n")
    assert forge.installer_files(tmp_path, args) == forge.INSTALLER_FILES
