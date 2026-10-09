"""Will the mods start together: the loaders' own check (fabric.mod.json, mods.toml,
neoforge.mods.toml), run before anyone launches, on the server's mods and on players'."""

import io
import json
import zipfile

from craft_conductor import config as configmod, doctor, modcheck
from craft_conductor.clientpack import PackBuilder
from craft_conductor.config import ModSpec
from craft_conductor.modcheck import check, fabric_matches, maven_matches, read_bytes

from test_manager import manager, update


def jar(files: dict[str, bytes | str | dict]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, body in files.items():
            if isinstance(body, dict):
                body = json.dumps(body)
            z.writestr(name, body)
    return buf.getvalue()


def fabric(mod_id, version, depends=None, name=None, **more) -> bytes:
    return jar({"fabric.mod.json": {"schemaVersion": 1, "id": mod_id, "version": version, "name": name or mod_id,
                                    "depends": depends or {}, **more}})


def mods_of(*blobs, loader="fabric"):
    return [m for i, b in enumerate(blobs) for m in read_bytes(b, loader, f"{i}.jar")]


def fabric_check(*blobs, side="client", minecraft="26.1", **kw):
    return check(mods_of(*blobs), loader="fabric", minecraft=minecraft, loader_version="0.19.5", java_major=25,
                 side=side, **kw)


# ------------------------------------------------------------------ Fabric
IRIS = fabric("iris", "1.11.4+mc26.1.2", {"sodium": "0.9.x", "minecraft": ">=26.1"}, "Iris")
SODIUM = fabric("sodium", "0.8.9+mc26.1.1", {"minecraft": ">=26.1"}, "Sodium", environment="client")
TERRALITH = fabric("terralith", "2.6.2", {"lithostitched": ">=1.6.3"}, "Terralith")


def test_the_crash_from_the_bug_report_is_found_before_launching():
    """Iris needing a newer Sodium and Terralith needing Lithostitched: what Fabric said in Prism."""
    problems = fabric_check(IRIS, SODIUM, TERRALITH)
    assert [(p.kind, p.mod_id, p.needs) for p in problems] == [("version", "iris", "sodium"), ("missing", "terralith", "lithostitched")]
    assert problems[0].text == "Iris 1.11.4+mc26.1.2 needs Sodium any 0.9.x version, but Sodium 0.8.9+mc26.1.1 is the one there."
    assert problems[1].text == "Terralith 2.6.2 needs lithostitched (1.6.3 or later), which is missing."


def test_mods_that_fit_together_pass():
    assert fabric_check(fabric("iris", "1.10.9", {"sodium": ">=0.8.0 <0.9"}), SODIUM,
                        TERRALITH, fabric("lithostitched", "1.6.4")) == []


def test_the_loader_minecraft_and_java_are_there_without_files():
    ok = fabric("a", "1", {"fabricloader": ">=0.16", "minecraft": "~26.1", "java": ">=21"})
    assert fabric_check(ok) == []
    old = fabric("b", "1", {"minecraft": "1.21.x"}, "Old")
    assert [p.text for p in fabric_check(old)] == ["Old 1 is made for Minecraft any 1.21.x version, not 26.1."]
    assert [p.kind for p in fabric_check(fabric("c", "1", {"java": ">=26"}))] == ["java"]
    assert [p.kind for p in fabric_check(fabric("d", "1", {"fabricloader": ">=0.20"}))] == ["loader"]


def test_provided_and_bundled_mods_count():
    api = jar({"fabric.mod.json": {"id": "fabric-api", "version": "0.140.0+26.1", "provides": ["fabric"],
                                   "jars": [{"file": "META-INF/jars/base.jar"}]},
               "META-INF/jars/base.jar": fabric("fabric-api-base", "1.0.5")})
    user = fabric("user", "1", {"fabric": "*", "fabric-api-base": ">=1.0"})
    assert fabric_check(api, user) == []
    assert [p.needs for p in fabric_check(user)] == ["fabric", "fabric-api-base"]


def test_a_mod_only_for_one_side_is_ignored_on_the_other():
    """Sodium (client only) on a server: Fabric doesn't load it there, so what it needs doesn't matter."""
    client_only = fabric("hud", "1", {"missing-lib": "*"}, environment="client")
    assert fabric_check(client_only, side="server") == []
    assert [p.needs for p in fabric_check(client_only, side="client")] == ["missing-lib"]


def test_breaks():
    a = fabric("a", "1", name="A", breaks={"optifabric": "*"})
    assert [p.text for p in fabric_check(a, fabric("optifabric", "1.14"))] == ["A 1 doesn't work with optifabric 1.14."]
    assert fabric_check(a) == []


def test_what_cant_be_told_is_taken_as_fine():
    weird = fabric("w", "1", {"lib": ">=1.0"})
    assert fabric_check(weird, fabric("lib", "build-2024")) == []   # a version that isn't one
    assert fabric_check(fabric("x", "1", {"lib": ">=what"}), fabric("lib", "1.0")) == []
    assert fabric_check(weird, complete=False) == []                # lib may be in a file that couldn't be read
    assert mods_of(b"not a zip at all", b"PK\x03\x04broken") == []
    assert mods_of(jar({"fabric.mod.json": "{ not json"})) == []


def test_fabric_versions():
    assert fabric_matches("0.9.2", ["0.9.x"]) and not fabric_matches("0.8.9+mc26.1.1", ["0.9.x"])
    assert fabric_matches("1.6.3", [">=1.6.3"]) and not fabric_matches("1.6.2", [">=1.6.3"])
    assert fabric_matches("1.2.9", ["~1.2.3"]) and not fabric_matches("1.3.0", ["~1.2.3"])
    assert fabric_matches("1.9", ["^1.2"]) and not fabric_matches("2.0", ["^1.2"])
    assert fabric_matches("1.5", [">=1.0 <2.0"]) and not fabric_matches("2.0", [">=1.0 <2.0"])
    assert fabric_matches("3.0", ["<2", ">=3"])                        # any of them
    assert not fabric_matches("1.0.0-beta.2", [">=1.0.0"]) and fabric_matches("1.0.0-beta.2", [">=1.0.0-beta.1"])
    assert fabric_matches("26.1", ["26.1.0"]) and fabric_matches("anything", ["*"])
    assert fabric_matches("26.1", ["~26.1-"]) and fabric_matches("26.1.2", ["~26.1-"]) and not fabric_matches("26.2", ["~26.1-"])
    assert fabric_matches("26.1-rc.1", [">=26.1-"]) and not fabric_matches("26.0.9", [">=26.1-"])


# ------------------------------------------------------------------ Forge and NeoForge
def forge_jar(mod_id, version, deps="", path="META-INF/mods.toml", name=None, extra=None):
    toml = f'modLoader="javafml"\nloaderVersion="[47,)"\n[[mods]]\nmodId="{mod_id}"\nversion="{version}"\n' \
           f'displayName="{name or mod_id}"\n{deps}'
    return jar({path: toml, **(extra or {})})


def dep(owner, mod_id, version_range, mandatory=None, kind=None, side="BOTH"):
    how = f"type=\"{kind}\"" if kind else f"mandatory={str(mandatory).lower()}"
    return f'[[dependencies.{owner}]]\nmodId="{mod_id}"\n{how}\nversionRange="{version_range}"\nside="{side}"\n'


def forge_check(*blobs, loader="forge", side="client", minecraft="1.20.1", loader_version="47.2.0", **kw):
    return check(mods_of(*blobs, loader=loader), loader=loader, minecraft=minecraft, loader_version=loader_version,
                 side=side, **kw)


def test_forge_mandatory_dependencies_and_ranges():
    needs = forge_jar("create", "0.5.1", dep("create", "forge", "[47,)", True) + dep("create", "minecraft", "[1.20.1,1.21)", True)
                      + dep("create", "flywheel", "[0.6.10,0.7)", True) + dep("create", "jei", "*", False), name="Create")
    assert [p.text for p in forge_check(needs)] == ["Create 0.5.1 needs flywheel (0.6.10 or later, older than 0.7), which is missing."]
    assert [p.kind for p in forge_check(needs, forge_jar("flywheel", "0.6.9"))] == ["version"]
    assert forge_check(needs, forge_jar("flywheel", "0.6.10-7")) == []
    assert [p.kind for p in forge_check(needs, forge_jar("flywheel", "0.6.11"), minecraft="1.21.1")] == ["minecraft"]
    assert [p.kind for p in forge_check(needs, forge_jar("flywheel", "0.6.11"), loader_version="46.0.1")] == ["loader"]


def test_forge_versions_from_the_jar_manifest_and_client_side_dependencies():
    lib = forge_jar("lib", "${file.jarVersion}", extra={"META-INF/MANIFEST.MF": "Manifest-Version: 1.0\nImplementation-Version: 2.1.0\n"})
    assert mods_of(lib, loader="forge")[0].version == "2.1.0"
    user = forge_jar("user", "1", dep("user", "lib", "[3.0,)", True) + dep("user", "hud", "*", True, side="CLIENT"))
    assert [(p.kind, p.needs) for p in forge_check(user, lib, side="server")] == [("version", "lib")]   # (hud: players only)
    assert [p.needs for p in forge_check(user, lib, side="client")] == ["lib", "hud"]
    unknown = forge_jar("lib", "${global.mcVersion}")
    assert forge_check(user, unknown, side="server") == []


def test_neoforge_required_incompatible_and_bundled_mods():
    inner = forge_jar("bundled", "1.4.0", path="META-INF/neoforge.mods.toml")
    outer = forge_jar("outer", "2.0", dep("outer", "neoforge", "[21.1,)", kind="required")
                      + dep("outer", "bundled", "[1.4,)", kind="required") + dep("outer", "badmod", "*", kind="incompatible")
                      + dep("outer", "nice", "*", kind="optional"), path="META-INF/neoforge.mods.toml", name="Outer",
                      extra={"META-INF/jarjar/metadata.json": json.dumps({"jars": [{"path": "META-INF/jarjar/bundled.jar"}]}),
                             "META-INF/jarjar/bundled.jar": inner})
    args = dict(loader="neoforge", minecraft="1.21.1", loader_version="21.1.77")
    assert forge_check(outer, **args) == []
    assert [p.text for p in forge_check(outer, forge_jar("badmod", "3", path="META-INF/neoforge.mods.toml"), **args)] == \
        ["Outer 2.0 doesn't work with badmod 3."]
    old_style = forge_jar("old", "1", dep("old", "neoforge", "[20.4,)", True))  # (mods.toml, before 20.5)
    assert forge_check(old_style, **args) == []


def test_maven_versions():
    assert maven_matches("1.2.0", ["[1.0,2.0)"]) and not maven_matches("2.0", ["[1.0,2.0)"])
    assert maven_matches("2.0", ["[1.0,2.0]"]) and maven_matches("5", ["[1.0,)"]) and not maven_matches("0.9", ["[1.0,)"])
    assert maven_matches("1.0", ["[1.0]"]) and not maven_matches("1.0.1", ["[1.0]"])
    assert maven_matches("0.5", ["(,1.0)"]) and maven_matches("3.1", ["[1.0,2.0),[3.0,)"])
    assert maven_matches("9", ["1.0"])                                  # a bare version only recommends
    assert not maven_matches("1.0-beta", ["[1.0,)"]) and maven_matches("1.0.1", ["[1.0,)"])
    assert maven_matches("1.20.1-0.5.1.f", ["[1.20.1-0.5,)"])


# ------------------------------------------------------------------ on the server and for players
def test_check_folder_reads_a_mods_folder(tmp_path):
    (tmp_path / "terralith.jar").write_bytes(TERRALITH)
    (tmp_path / "notes.txt").write_text("not a mod")
    problems = modcheck.check_folder(tmp_path, loader="fabric", minecraft="26.1", loader_version="0.19.5")
    assert [p.needs for p in problems] == ["lithostitched"]
    (tmp_path / "lithostitched.jar").write_bytes(fabric("lithostitched", "1.6.4"))
    assert modcheck.check_folder(tmp_path, loader="fabric", minecraft="26.1", loader_version="0.19.5") == []
    assert modcheck.check_folder(tmp_path, loader="paper", minecraft="26.1", loader_version="1") == []


def test_players_get_a_server_mod_their_mods_need_even_when_its_site_says_servers_only(make_config, http, modrinth):
    """Terralith runs on players' computers too and needs Lithostitched; Modrinth says Lithostitched
    is for servers only. Players get it anyway (or Minecraft wouldn't start)."""
    modrinth.project("TER", "terralith", "Terralith", client_side="optional")
    modrinth.version("TER", "2.6.2", ["1.21.1"], deps=["LIT"], content=TERRALITH)
    modrinth.project("LIT", "lithostitched", "Lithostitched", client_side="unsupported")
    modrinth.version("LIT", "1.6.4", ["1.21.1"], content=fabric("lithostitched", "1.6.4"))
    modrinth.project("TOOL", "servertool", "Server Tool", client_side="unsupported")
    modrinth.version("TOOL", "1.0", ["1.21.1"], content=fabric("servertool", "1.0"))
    cfg = make_config([ModSpec("modrinth", "terralith"), ModSpec("modrinth", "servertool")])
    m = manager(cfg, http, ["1.21.1"])
    assert update(m).ok
    p = PackBuilder(m).build("mc.example.com")
    got = {x["name"]: x.get("needed_by") for x in p["mods"]}
    assert got == {"Terralith": None, "Lithostitched": "Terralith"}   # (not the server tool)
    assert p["problems"] == []


def test_players_mods_that_dont_fit_are_told_and_looked_at_once(make_config, http, modrinth):
    modrinth.project("IRIS", "iris", "Iris", server_side="unsupported")
    modrinth.version("IRIS", "1.11.4", ["1.21.1"], deps=["SOD"], content=fabric("iris", "1.11.4", {"sodium": "0.9.x"}, "Iris"))
    modrinth.project("SOD", "sodium", "Sodium", server_side="unsupported")
    modrinth.version("SOD", "0.8.9", ["1.21.1"], content=fabric("sodium", "0.8.9", name="Sodium"))
    cfg = make_config([])
    configmod.set_value(cfg.path, "client", "mods", '["iris"]')
    m = manager(configmod.load(cfg.root), http, ["1.21.1"])
    assert update(m).ok
    p = PackBuilder(m).build("mc.example.com")
    assert [x["text"] for x in p["problems"]] == ["Iris 1.11.4 needs Sodium any 0.9.x version, but Sodium 0.8.9 is the one there."]
    # Downloaded only to look inside (and not kept), once: the next build reads what was found.
    assert len(list((m.config.state_dir / "mod-files").glob("*.jar"))) == 2  # (kept for installing, by hash)
    downloads = len(http.downloads)
    http.files.clear()
    assert PackBuilder(m).build("mc.example.com")["problems"] == p["problems"]
    assert len(http.downloads) == downloads


def test_an_update_whose_mods_wouldnt_start_is_refused(make_config, http, modrinth):
    """Nothing changes on the server: the loader would stop it, so it isn't installed."""
    modrinth.project("TER", "terralith", "Terralith")
    modrinth.version("TER", "2.6.2", ["1.21.1"], content=TERRALITH)  # (its site doesn't say it needs anything)
    cfg = make_config([ModSpec("modrinth", "terralith")])
    m = manager(cfg, http, ["1.21.1"])
    r = update(m)
    assert not r.ok and "wouldn't start together" in r.message and "lithostitched" in r.message
    assert not m.lock.installed and not list(m.mods_dir.glob("*.jar"))


def test_the_doctor_finds_mods_the_server_lacks(make_config, http, modrinth):
    modrinth.project("AAA", "goodmod", "Good Mod")
    modrinth.version("AAA", "1.0", ["1.21.1"])
    cfg = make_config([ModSpec("modrinth", "goodmod")])
    m = manager(cfg, http, ["1.21.1"])
    assert update(m).ok
    (m.mods_dir / "terralith.jar").write_bytes(TERRALITH)   # (one of your own files)
    found = next(c for c in doctor.run(m, "stopped", total_gb=32) if c.id == "mods")
    assert found.status == doctor.BAD and "lithostitched" in found.detail and "Fabric won't start" in found.detail
    (m.mods_dir / "lithostitched.jar").write_bytes(fabric("lithostitched", "1.6.4"))
    assert next(c for c in doctor.run(m, "stopped", total_gb=32) if c.id == "mods").status == doctor.OK
