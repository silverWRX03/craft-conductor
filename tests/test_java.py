"""The shared Java folder: one download per Java version for every server, Java already on the
computer used first, and nothing removed from under a running server."""

import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import urllib.parse
from pathlib import Path

import pytest

from craft_conductor import backup, config as configmod, setup as setupmod
from craft_conductor.http import HashMismatch
from craft_conductor.java import ADOPTIUM, LEASES, JavaError, JavaInfo, JavaManager, parse_info

from conftest import FakeLoader, FakeMojang
from test_manager import update
from test_web import running  # noqa: F401  (the fixture)

LINUX_X64 = lambda: ("linux", "x64")  # noqa: E731
JAVA = "java.exe" if os.name == "nt" else "java"
posix_only = pytest.mark.skipif(os.name == "nt", reason="the stand-in Temurin's java is a shell script")


def publish(http, major, release, java_script=None, arch="x64", os_name="linux"):
    """A fake Temurin release on the fake Adoptium API (checksum included, like the real one)."""
    body = java_script or f"#!/bin/sh\necho 'openjdk version \"{major}.0.1\"' >&2\n".encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(f"{release}-jre/bin/java")
        info.size, info.mode = len(body), 0o755
        tar.addfile(info, io.BytesIO(body))
    data = buf.getvalue()
    name = f"OpenJDK{major}U-jre_{arch}_{os_name}_{release}.tar.gz"
    link = f"https://github.test/temurin/{name}"
    http.files[link] = data
    params = {"architecture": arch, "image_type": "jre", "os": os_name, "vendor": "eclipse"}
    http.json[f"{ADOPTIUM}/assets/latest/{major}/hotspot?{urllib.parse.urlencode(params)}"] = [{
        "release_name": release, "version": {"semver": release.removeprefix("jdk-")},
        "binary": {"package": {"name": name, "link": link, "checksum": hashlib.sha256(data).hexdigest()}},
    }]
    return link


def server(tmp_path, name, minecraft="1.21.1", default="/nonexistent/java"):
    root = tmp_path / "servers" / name
    setupmod.configure(root, setupmod.SetupSpec.from_dict({"loader": "fabric", "minecraft": minecraft, "motd": name,
                                                           "accept_eula": True}))
    configmod.set_value(root / configmod.CONFIG_NAME, "java", "default", json.dumps(default))
    return configmod.load(root)


def downloads(http, link):
    return sum(1 for u in http.downloads if u == link)


# ------------------------------------------------------------------ the shared folder
def test_two_servers_that_need_the_same_java_download_it_once(tmp_path, http, java_store):
    link = publish(http, 21, "jdk-21.0.4+7")
    a, b = server(tmp_path, "Survival"), server(tmp_path, "Creative")
    ja, jb = JavaManager(a, http, platform_fn=LINUX_X64), JavaManager(b, http, platform_fn=LINUX_X64)
    assert ja.choose(21).source == "download"
    first = ja.select(21)
    assert jb.choose(21).source == "shared"
    assert jb.select(21) == first and downloads(http, link) == 1
    assert Path(first).is_relative_to(java_store / "21")
    # Each server says which Java it uses, and who else does.
    c = jb.choose(21)
    assert "shared Java 21" in c.note and [u["name"] for u in jb.users_of(c)] == ["Survival"]
    assert sorted(u["name"] for u in ja.store.users()) == ["Creative", "Survival"]
    # Neither server's own folder has a copy.
    assert not (a.state_dir / "java").exists() and not (b.state_dir / "java").exists()


def test_different_requirements_get_separate_runtimes(tmp_path, http):
    l17, l21 = publish(http, 17, "jdk-17.0.12+7"), publish(http, 21, "jdk-21.0.4+7")
    old, new = server(tmp_path, "Old", "1.20.4"), server(tmp_path, "New")
    j17 = JavaManager(old, http, platform_fn=LINUX_X64).select(17)
    j21 = JavaManager(new, http, platform_fn=LINUX_X64).select(21)
    assert j17 != j21 and "/17/" in Path(j17).as_posix() and "/21/" in Path(j21).as_posix()
    assert downloads(http, l17) == downloads(http, l21) == 1
    assert sorted(JavaManager(old, http).installed()) == [17, 21]


def test_with_no_java_at_all_it_installs_and_without_downloads_it_says_so(tmp_path, http):
    cfg = server(tmp_path, "Solo")
    jm = JavaManager(cfg, http, platform_fn=LINUX_X64)
    cfg.java_auto_install = False
    with pytest.raises(JavaError, match="Java 21 isn't on this computer, and downloads are off"):
        jm.select(21)
    cfg.java_auto_install = True
    link = publish(http, 21, "jdk-21.0.4+7")
    assert jm.select(21) and downloads(http, link) == 1
    http.files[publish(http, 25, "jdk-25+36")] = b"not the real archive"
    with pytest.raises(HashMismatch):  # (a tampered download is refused)
        jm.install(25)
    assert 25 not in jm.installed()


# ------------------------------------------------------------------ Java on the computer
def fake_javas(tmp_path, **kinds):
    """Files standing in for Java installed on the computer, by folder name."""
    for name in kinds:
        binary = tmp_path / "jvm" / name / "bin" / JAVA
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o755)
    return [str(tmp_path / "jvm" / "*" / "bin" / JAVA)]


def test_a_java_already_on_the_computer_is_used_and_the_wrong_architecture_skipped(tmp_path, http):
    """On an Apple silicon Mac, an x86 Java isn't a match; the ARM one is, and is written into the
    server's [java.versions] so its choice stays explicit. Each Java is run with -version once."""
    kinds = {"temurin-21-x64": JavaInfo(21, "x64", "21.0.4"), "temurin-21-arm": JavaInfo(21, "aarch64", "21.0.3"),
             "zulu-17-arm": JavaInfo(17, "aarch64", "17.0.9")}
    folders = fake_javas(tmp_path, **kinds)
    runs = []

    def probe(binary):
        runs.append(binary)
        return kinds.get(Path(binary).parents[1].name)
    cfg = server(tmp_path, "Mac")
    jm = JavaManager(cfg, http, probe_fn=probe, platform_fn=lambda: ("mac", "aarch64"), folders_fn=lambda: folders)
    found = {Path(f.path).parents[1].name: f for f in jm.found()}
    assert "built for x64" in found["temurin-21-x64"].problem and not found["temurin-21-arm"].problem
    c = jm.choose(21)
    assert c.source == "found" and "temurin-21-arm" in c.binary
    assert jm.select(21) == c.binary and http.downloads == []
    assert configmod.load(cfg.root).java_versions == {21: c.binary}  # (explicit from now on)
    assert jm.choose(21).source == "configured" and "your own Java at" in jm.choose(21).note
    # -version ran once per Java, however often it was looked at.
    for _ in range(3):
        jm.found()
        jm.choose(21, offers=True)
    ran = [r for r in runs if Path(r).exists()]  # (a missing one isn't run at all)
    assert len(ran) == 3 and sorted(ran) == sorted(set(ran))


def test_only_an_x86_java_means_a_download(tmp_path, http):
    folders = fake_javas(tmp_path, x64=None)
    cfg = server(tmp_path, "Mac")
    link = publish(http, 21, "jdk-21.0.4+7", arch="aarch64", os_name="mac")
    jm = JavaManager(cfg, http, probe_fn=lambda b: JavaInfo(21, "x64") if "x64" in b else None,
                     platform_fn=lambda: ("mac", "aarch64"), folders_fn=lambda: folders)
    assert jm.choose(21).source == "download"
    assert "/21/" in Path(jm.select(21)).as_posix() and downloads(http, link) == 1
    assert configmod.load(cfg.root).java_versions == {}


def test_a_newer_java_is_only_used_when_asked(tmp_path, http):
    folders = fake_javas(tmp_path, j25=None)
    cfg = server(tmp_path, "Modded")
    jm = JavaManager(cfg, http, probe_fn=lambda b: JavaInfo(25, "x64") if "j25" in b else None,
                     platform_fn=LINUX_X64, folders_fn=lambda: folders)
    c = jm.choose(21, offers=True)
    assert c.source == "download" and [f.info.major for f in c.newer] == [25]  # (offered, not picked)
    cfg.java_auto_install = False
    with pytest.raises(JavaError, match="Java 25 is on this computer: to use it instead, press Use Java 25"):
        jm.select(21)
    cfg.java_version = 25  # (Use Java 25, on the Java page)
    assert Path(jm.select(21)).parents[1].name == "j25"


# ------------------------------------------------------------------ updates and running servers
def server_java(fake_java):
    """A Temurin "java" that runs the fake Minecraft server (and answers -version)."""
    return f'#!/bin/sh\nexec "{fake_java}" "$@"\n'.encode()


@posix_only
def test_an_update_while_a_server_runs_keeps_its_release_until_it_restarts(tmp_path, http, modrinth, fake_java):
    modrinth.project("AAA", "goodmod", "Good Mod")
    modrinth.version("AAA", "1.0", ["1.21.1"])
    publish(http, 21, "jdk-21.0.4+7", server_java(fake_java))
    cfg = server(tmp_path, "Survival")
    from craft_conductor.manager import Manager
    from craft_conductor.mods import providers_for
    mojang = FakeMojang(http, ["1.21.1"])
    m = Manager(cfg, http=http, mojang=mojang, loader=FakeLoader(http, mojang), providers=providers_for(cfg, http),
                echo=False, sleep=lambda s: None)
    m.java.platform = LINUX_X64
    assert update(m).ok
    old = m.java.installed()[21]
    proc = m.start_server()
    try:
        assert proc.argv[0] == str(old.binary)
        assert (old.dir / LEASES / str(proc.proc.pid)).is_file()  # (a note: this process runs from it)
        publish(http, 21, "jdk-21.0.5+11", server_java(fake_java))
        assert m.java.update() == [(21, "jdk-21.0.4+7", "jdk-21.0.5+11")]
        new = m.java.installed()[21]
        assert old.binary.is_file() and new.binary.is_file() and new.dir.parent == old.dir.parent
        m.java.store.tidy()
        assert old.binary.is_file()  # still running on it
    finally:
        proc.stop(10)
    proc = m.start_server()  # the next start moves to the new release, and the old one goes
    try:
        assert proc.argv[0] == str(new.binary)
        assert not old.dir.exists()
        assert [j.release for j in m.java.store.releases()[21]] == ["jdk-21.0.5+11"]
    finally:
        proc.stop(10)


def test_an_old_release_a_process_still_runs_from_is_kept(tmp_path, http):
    cfg = server(tmp_path, "S")
    jm = JavaManager(cfg, http, platform_fn=LINUX_X64)
    publish(http, 21, "jdk-21.0.4+7")
    old = jm.install(21)
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        jm.lease(str(old.binary), sleeper.pid)
        publish(http, 21, "jdk-21.0.5+11")
        jm.update()
        assert old.binary.is_file() and jm.store.running(old) == [sleeper.pid]
    finally:
        sleeper.kill()
        sleeper.wait()
    assert jm.store.tidy() == ["jdk-21.0.4+7"] and not old.dir.exists()


def test_a_release_replaced_moments_ago_waits(tmp_path, http, monkeypatch):
    """A server may be starting on the old release that very moment: it's kept for a few minutes."""
    from craft_conductor import java as javamod
    monkeypatch.setattr(javamod, "GRACE", 300)
    jm = JavaManager(server(tmp_path, "S"), http, platform_fn=LINUX_X64)
    publish(http, 21, "jdk-21.0.4+7")
    old = jm.install(21)
    publish(http, 21, "jdk-21.0.5+11")
    jm.update()
    assert old.binary.is_file() and jm.store.tidy() == []


# ------------------------------------------------------------------ removing
def test_removing_a_server_keeps_a_runtime_another_server_uses(tmp_path, http):
    publish(http, 21, "jdk-21.0.4+7")
    a, b = server(tmp_path, "Survival"), server(tmp_path, "Creative")
    ja, jb = JavaManager(a, http, platform_fn=LINUX_X64), JavaManager(b, http, platform_fn=LINUX_X64)
    ja.select(21)
    jb.select(21)
    with pytest.raises(JavaError, match="used by"):
        ja.remove(21)
    assert ja.forget(prune=True) == [] and 21 in jb.installed()  # Creative still uses it
    assert jb.forget(prune=True) == [21] and jb.installed() == {}  # the last one: it goes too


@posix_only
def test_deleting_a_server_in_the_hub(tmp_path, http, modrinth, fake_java, java_store):
    from craft_conductor.hub import Hub
    from test_manager import manager
    modrinth.project("FAPI", "fabric-api", "Fabric API")
    modrinth.version("FAPI", "0.1", ["1.21.1"])
    publish(http, 21, "jdk-21.0.4+7", server_java(fake_java))
    home = tmp_path / "home"
    for name in ("a", "b"):
        root = home / "servers" / name
        setupmod.configure(root, setupmod.SetupSpec.from_dict({"loader": "fabric", "minecraft": "1.21.1", "motd": name,
                                                               "accept_eula": True}))
        configmod.set_value(root / configmod.CONFIG_NAME, "java", "default", '"/nonexistent/java"')
        m = manager(configmod.load(root), http, ["1.21.1"])
        m.java.platform = LINUX_X64
        assert update(m).ok
    assert len([u for u in http.downloads if "temurin" in u]) == 1
    hub = Hub(home, make_manager=lambda cfg: manager(cfg, http, ["1.21.1"]), http=http, tick=0.1)
    try:
        hub.scan()
        hub.delete("a", True)
        assert 21 in JavaManager(configmod.load(home / "servers" / "b"), http).installed()
        hub.delete("b", True)
        assert not (java_store / "21").exists()
    finally:
        hub.stop_requested.set()


def test_the_computers_java_is_kept_where_it_really_is(tmp_path, http):
    """[java] default = "java" (the PATH's): when it fits, the server keeps that Java's own folder,
    so a different java on the PATH later doesn't change it unasked."""
    home = tmp_path / "jvm" / "temurin-21"
    (home / "bin").mkdir(parents=True)
    (home / "bin" / JAVA).write_text("#!/bin/sh\n")
    cfg = server(tmp_path, "S", default="java")
    jm = JavaManager(cfg, http, platform_fn=LINUX_X64,
                     probe_fn=lambda b: JavaInfo(21, "x64", "21.0.4", "", str(home)) if b == "java" else None)
    assert jm.choose(21).source == "default"
    assert jm.select(21) == str(home / "bin" / JAVA)
    assert configmod.load(cfg.root).java_versions == {21: str(home / "bin" / JAVA)}
    # An x64 java on the PATH of an Apple silicon Mac doesn't count either.
    mac = JavaManager(server(tmp_path, "Mac", default="java"), http, platform_fn=lambda: ("mac", "aarch64"),
                      probe_fn=lambda b: JavaInfo(21, "x64") if b == "java" else None)
    assert mac.choose(21).source == "download"


@posix_only
def test_a_java_other_users_can_change_is_never_run(tmp_path, http):
    folders = fake_javas(tmp_path, shared=None)
    (tmp_path / "jvm" / "shared" / "bin" / JAVA).chmod(0o777)
    runs = []
    jm = JavaManager(server(tmp_path, "S"), http, platform_fn=LINUX_X64, folders_fn=lambda: folders,
                     probe_fn=lambda b: runs.append(b) or (JavaInfo(21, "x64") if "shared" in b else None))
    [f] = [f for f in jm.found() if f.source == "installed"]
    assert "other users" in f.problem and not [r for r in runs if "shared" in r]
    assert jm.choose(21).source == "download"


def test_a_download_without_a_checksum_is_refused(tmp_path, http):
    from craft_conductor.java import ADOPTIUM as API
    publish(http, 21, "jdk-21.0.4+7")
    key = next(k for k in http.json if k.startswith(f"{API}/assets/latest/21/"))
    del http.json[key][0]["binary"]["package"]["checksum"]
    jm = JavaManager(server(tmp_path, "S"), http, platform_fn=LINUX_X64)
    with pytest.raises(JavaError, match="no checksum"):
        jm.select(21)
    assert http.downloads == []


def test_clean_up_stays_inside_the_store(tmp_path, http, java_store):
    jm = JavaManager(server(tmp_path, "S"), http, platform_fn=LINUX_X64)
    outside = tmp_path / "precious"
    (outside / "bin").mkdir(parents=True)
    (outside / "bin" / "java").write_text("mine")
    (outside / "craft-conductor-java.json").write_text(json.dumps({"major": 21, "release": "x", "java": "bin/java"}))
    (java_store / "21").mkdir(parents=True)
    try:
        (java_store / "21" / "evil").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("no symlinks here")
    assert jm.installed() == {}  # (a link isn't a release)
    # Nor a release whose note points its java outside its folder.
    (java_store / "21" / "odd").mkdir()
    (java_store / "21" / "odd" / "craft-conductor-java.json").write_text(json.dumps(
        {"major": 21, "release": "odd", "java": str(outside / "bin" / "java")}))
    assert jm.installed() == {}
    assert not jm.store._delete(outside) and not jm.store._delete(java_store / "21" / "evil")
    jm.store.tidy()
    assert (outside / "bin" / "java").read_text() == "mine"


# ------------------------------------------------------------------ the rest of the house
def test_backups_and_exports_leave_java_out(tmp_path, http, modrinth, make_config):
    from test_manager import manager
    modrinth.project("AAA", "goodmod", "Good Mod")
    modrinth.version("AAA", "1.0", ["1.21.1"])
    cfg = make_config()
    m = manager(cfg, http, ["1.21.1"])
    assert update(m).ok
    publish(http, 21, "jdk-21.0.4+7")
    m.java.platform = LINUX_X64
    m.java.install(21)
    archive = backup.create(cfg.server.dir, cfg.backups.dir, "test", [])
    with tarfile.open(archive) as t:
        assert not [n for n in t.getnames() if "craft-conductor-java" in n or "/bin/java" in n]
    assert not m.java.dir.is_relative_to(cfg.root)


def test_reading_what_a_java_is():
    out = ("Property settings:\n    java.home = /usr/lib/jvm/temurin-21\n    java.runtime.version = 21.0.4+7-LTS\n"
           "    java.vendor = Eclipse Adoptium\n    java.version = 21.0.4\n    os.arch = amd64\n\n"
           'openjdk version "21.0.4" 2024-07-16 LTS\n')
    assert parse_info(out) == JavaInfo(21, "x64", "21.0.4+7-LTS", "Eclipse Adoptium", "/usr/lib/jvm/temurin-21")
    assert parse_info('java version "1.8.0_392"\n    os.arch = aarch64\n').arch == "aarch64"
    assert parse_info('java version "1.8.0_392"\n').arch is None
    assert parse_info("garbage") is None


def test_the_probe_runs_only_version_without_injected_options(tmp_path, monkeypatch):
    """A Java found on the computer is only run with -version, and JAVA_TOOL_OPTIONS (which would load
    an agent even then) isn't passed on."""
    from craft_conductor import java as javamod
    seen = {}

    def run(argv, **kw):
        seen["argv"], seen["env"] = argv, kw["env"]
        return subprocess.CompletedProcess(argv, 0, "", 'openjdk version "21.0.4"\n    os.arch = x86_64\n')
    binary = tmp_path / "java"
    binary.write_text("")
    binary.chmod(0o755)
    monkeypatch.setattr(javamod.shutil, "which", lambda b: str(binary))
    monkeypatch.setattr(javamod.subprocess, "run", run)
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "-javaagent:evil.jar")
    assert javamod.run_version(str(binary)) == JavaInfo(21, "x64")
    assert seen["argv"][1:] == ["-XshowSettings:properties", "-version"]
    assert "JAVA_TOOL_OPTIONS" not in seen["env"]


def test_the_java_page(running):  # noqa: F811  (the fixture)
    from test_web import login
    d, c, cfg = running
    login(c)
    status, r, _ = c.get("/api/java")
    assert status == 200 and r["required"] == 21 and r["store"] == str(d.m.java.dir)
    assert r["choice"]["source"] == "default" and r["choice"]["binary"] == cfg.java_default
    assert any(f["source"] == "default" and f["major"] == 21 for f in r["found"])
    assert r["shared"] == [] and r["old_folder"] is None
    # Only a Java the scan found can be chosen, never any path.
    status, body, _ = c.post("/api/java/use", {"version": "auto", "path": "/bin/sh"})
    assert status == 400 and "found" in body["error"]
    assert c.post("/api/java/scan")[0] == 200
    assert c.post("/api/java/remove", {"major": 21})[0] == 404
    assert c.post("/api/java/remove", {"major": "21; rm -rf /"})[0] == 400
    assert c.post("/api/java/use", {"version": "25"})[0] == 200  # (asked for: Use Java 25)
    assert configmod.load(cfg.root).java_version == 25
    assert c.post("/api/java/use", {"version": "auto"})[0] == 200
    # A server's folder from before the shared one is pointed out (to delete by hand), never touched.
    (cfg.state_dir / "java" / "21").mkdir(parents=True)
    (cfg.state_dir / "java" / "21" / "lib.bin").write_bytes(b"x" * 1000)
    r = c.get("/api/java")[1]
    assert r["old_folder"] == str(cfg.state_dir / "java") and r["old_bytes"] == 1000
