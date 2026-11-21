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


@pytest.mark.parametrize("version", ["../49.0.2", "49.0.2/../../x", r"49.0.2\x", "49 0 2", "", ".."])
def test_a_version_that_isnt_a_forge_build_is_refused_before_anything_is_downloaded(tmp_path, monkeypatch, version):
    monkeypatch.setattr(forge, "run_installer", lambda *a, **k: pytest.fail("the installer ran"))
    http = FakeHttp()
    # (an installer the version would reach is there to download: nothing may be)
    http.files[f"{forge.FORGE_MAVEN}/1.20.3-{version}/forge-1.20.3-{version}-installer.jar"] = b"installer"
    dest = tmp_path / "runtime"
    dest.mkdir()
    with pytest.raises(LoaderError, match="isn't a Forge version"):
        forge.ForgeLoader(http, FakeMojang(http, ["1.20.3"])).install("1.20.3", version, dest, "java")
    assert not list(dest.iterdir())


@pytest.mark.parametrize("version", ["49.0.2", "47.4.0", "1.20.1-47.4.0", "10.12.2.1149-prerelease"])
def test_every_kind_of_forge_build_is_taken(version):
    assert forge._FORGE_BUILD.fullmatch(version)


def test_a_forge_server_that_starts_from_its_starter_jar_is_installed_and_started(make_config, http, monkeypatch):
    # Through the Manager, as New server does: every file the install lists is moved into the server's
    # folder (49.0.2 has no run.sh, which once failed the install), and the first start is checked.
    import zipfile

    from craft_conductor import config as configmod
    from craft_conductor.manager import Manager
    from craft_conductor.mods import providers_for
    from conftest import FAKE_SERVER

    cfg = make_config(minecraft="1.20.3")
    path = cfg.root / configmod.CONFIG_NAME
    path.write_text(path.read_text().replace('loader = "fabric"', 'loader = "forge"', 1))
    cfg = configmod.load(cfg.root)
    full, shim = "1.20.3-49.0.2", "forge-1.20.3-49.0.2-shim.jar"
    http.json[forge.FORGE_PROMOS] = {"promos": {"1.20.3-latest": "49.0.2"}}
    http.files[f"{forge.FORGE_MAVEN}/{full}/forge-{full}-installer.jar"] = b"installer"

    def installer(java, jar, args, cwd):  # Forge 49.0.2's layout, with a "jar" the fake java can run
        (cwd / "libraries/net/minecraftforge/forge" / full).mkdir(parents=True)
        with zipfile.ZipFile(cwd / shim, "w") as z:
            z.writestr("__main__.py", FAKE_SERVER)
        jar.unlink()

    monkeypatch.setattr(forge, "run_installer", installer)
    mojang = FakeMojang(http, ["1.20.3"])
    m = Manager(cfg, http=http, mojang=mojang, loader=forge.ForgeLoader(http, mojang),
                providers=providers_for(cfg, http), echo=False, sleep=lambda s: None)
    decision, _ = m.check()
    result = m.apply(decision.plan)
    assert result.ok, result.message
    assert m.lock.launch == ["-jar", shim, "nogui"]
    assert (cfg.server.dir / shim).is_file() and not (cfg.server.dir / "run.sh").exists()
    argv = m.launch_argv()
    assert argv[0] == cfg.java_default and argv[-3:] == ["-jar", shim, "nogui"]
    assert any(a.startswith("-Xmx") for a in argv)
