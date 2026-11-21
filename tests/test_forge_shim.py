"""The starter ("shim") jar Forge's installers leave in the server's folder: Forge for Minecraft 26.x
starts through it from its args file, and Forge's first builds for 1.20.3 and 1.20.4 start from it
alone (#340)."""

import pytest

from craft_conductor.loaders import forge
from craft_conductor.loaders.base import LoaderError, args_file_name

from conftest import FakeHttp, FakeMojang


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


# What Forge's installers leave in the server's folder (looked at on real installs, #340).
def _install(tmp_path, monkeypatch, full, *, args_file, shim=True):
    def installer(java, jar, args, cwd):
        assert args == ["--installServer"]
        lib = cwd / "libraries/net/minecraftforge/forge" / full
        lib.mkdir(parents=True)
        (lib / f"forge-{full}-server.jar").write_bytes(b"jar")
        if shim:
            (cwd / f"forge-{full}-shim.jar").write_bytes(b"jar")
        if args_file:
            (lib / args_file_name()).write_text("-DlibraryDirectory=libraries net.minecraftforge.bootstrap.ForgeBootstrap\n")
            for script in ("run.sh", "run.bat"):
                (cwd / script).write_text("java @user_jvm_args.txt\n")
        jar.unlink()

    monkeypatch.setattr(forge, "run_installer", installer)
    http = FakeHttp()
    http.files[f"{forge.FORGE_MAVEN}/{full}/forge-{full}-installer.jar"] = b"installer"
    minecraft, version = full.split("-", 1)
    return forge.ForgeLoader(http, FakeMojang(http, [minecraft])).install(minecraft, version, tmp_path, "java")


def test_forge_that_installs_only_a_starter_jar_starts_from_it(tmp_path, monkeypatch):
    # Forge 49.0.2, the only build for Minecraft 1.20.3 (and 1.20.4's first builds): no args file,
    # a jar beside the libraries that starts the server by itself.
    rt = _install(tmp_path, monkeypatch, "1.20.3-49.0.2", args_file=False)
    assert rt.launch == ["-jar", "forge-1.20.3-49.0.2-shim.jar", "nogui"]
    # (nor a run.sh or run.bat: each file listed is moved into the server's folder)
    assert rt.files == ["libraries", "forge-1.20.3-49.0.2-shim.jar"]
    assert all((tmp_path / name).exists() for name in rt.files)


def test_forge_with_an_args_file_still_starts_from_it(tmp_path, monkeypatch):
    # Forge 1.20.4 49.2.13 leaves a starter jar too, but its args file is how it starts.
    rt = _install(tmp_path, monkeypatch, "1.20.4-49.2.13", args_file=True)
    assert rt.launch == [f"@libraries/net/minecraftforge/forge/1.20.4-49.2.13/{args_file_name()}", "nogui"]
    assert rt.files == forge.INSTALLER_FILES


def test_forge_that_installs_neither_is_refused(tmp_path, monkeypatch):
    with pytest.raises(LoaderError, match="did not produce"):
        _install(tmp_path, monkeypatch, "1.16.5-36.2.42", args_file=False, shim=False)
