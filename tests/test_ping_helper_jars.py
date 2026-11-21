"""The shipped Craft Conductor Ping helper jars (built from helpers/ping/ by tools/build_helpers.py)."""
import json
import zipfile
from pathlib import Path

HELPERS = Path(__file__).resolve().parent.parent / "src" / "craft_conductor" / "helpers"


def _only_ours(names):
    # "craft_conductor/" is only the folder entry that holds craft_conductor/ping/.
    return [n for n in names if not (n in ("plugin.yml", "fabric.mod.json", "craft_conductor/")
                                     or n.startswith("META-INF/") or n.startswith("craft_conductor/ping/"))]


def _one(pattern):
    jars = sorted(HELPERS.glob(pattern))
    assert len(jars) == 1, jars
    return jars[0]


def test_the_paper_helper_is_shipped():
    with zipfile.ZipFile(_one("craft_conductor_ping-paper-*.jar")) as z:
        yml = z.read("plugin.yml").decode("utf-8")
        names = z.namelist()
    assert "name: craft_conductor_ping" in yml.splitlines()
    assert 'api-version: "1.17"' in yml.splitlines()
    assert "main: craft_conductor.ping.PingPlugin" in yml.splitlines()
    assert _only_ours(names) == []
    assert "craft_conductor/ping/PingPlugin.class" in names


def _fabric_mod(pattern):
    with zipfile.ZipFile(_one(pattern)) as z:
        mod = json.loads(z.read("fabric.mod.json"))
        names = z.namelist()
        code = b"".join(z.read(n) for n in names if n.endswith(".class"))
    assert mod["id"] == "craft_conductor_ping"
    assert mod["environment"] == "server"  # (never offered to players)
    assert mod["entrypoints"] == {"server": ["craft_conductor.ping.PingMod"]}
    assert set(mod["depends"]) == {"fabricloader", "minecraft"}  # (no Fabric API: it pulls in no other mod)
    assert "fabric-api" not in json.dumps(mod)
    assert _only_ours(names) == []
    assert "craft_conductor/ping/PingMod.class" in names
    return mod, code


def test_the_fabric_helper_is_shipped():
    mod, code = _fabric_mod("craft_conductor_ping-fabric-*.jar")
    assert mod["depends"] == {"fabricloader": ">=0.14", "minecraft": ">=1.20.2 <26"}
    # Remapped to Fabric's intermediary names, which Fabric and Quilt run obfuscated Minecraft on.
    assert b"net/minecraft/class_" in code
    assert b"net/minecraft/server/level/ServerPlayer" not in code


def test_the_fabric26_helper_is_shipped():
    """Minecraft 26.1 and newer isn't obfuscated: Fabric runs mods on Mojang's own names there."""
    mod, code = _fabric_mod("craft_conductor_ping-fabric26-*.jar")
    assert mod["depends"] == {"fabricloader": ">=0.14", "minecraft": ">=26"}
    assert b"net/minecraft/server/level/ServerPlayer" in code
    assert b"net/minecraft/class_" not in code


def test_the_two_fabric_jars_hold_the_same_classes():
    """The same compile in both: only the names the mod reaches Minecraft by differ."""
    with zipfile.ZipFile(_one("craft_conductor_ping-fabric-*.jar")) as old, \
            zipfile.ZipFile(_one("craft_conductor_ping-fabric26-*.jar")) as new:
        assert sorted(n for n in old.namelist() if n.endswith(".class")) \
            == sorted(n for n in new.namelist() if n.endswith(".class"))


def _neoforge_mod(pattern, metadata):
    """A NeoForge jar: its metadata file (TOML), the names in it and its classes."""
    import tomllib
    with zipfile.ZipFile(_one(pattern)) as z:
        names = z.namelist()
        toml = tomllib.loads(z.read(metadata).decode("utf-8"))
        classes = {n: z.read(n) for n in names if n.endswith(".class")}
    assert _only_ours(names) == []
    assert [n for n in names if n.endswith(("mods.toml", ".json", ".yml"))] == [metadata]   # (one metadata file)
    assert "craft_conductor/ping/PingNeoForge.class" in names
    assert toml["modLoader"] == "javafml" and toml["loaderVersion"] == "[1,)"
    [mod] = toml["mods"]
    assert mod["modId"] == "craft_conductor_ping"
    deps = {d["modId"]: d for d in toml["dependencies"]["craft_conductor_ping"]}
    assert set(deps) == {"minecraft", "neoforge"}                 # (it pulls in no other mod)
    assert all(d["type"] == "required" for d in deps.values())
    # Not required on clients: no network channel or payload (NeoForge lets a client without the mod join).
    code = b"".join(classes.values())
    assert b"net/neoforged/neoforge/network" not in code and b"RegisterPayload" not in code
    # Mojang's names (NeoForge runs Minecraft on them from 1.20.2), compiled for Java 17 (1.20.2 to 1.20.4 run on it).
    assert b"net/minecraft/server/level/ServerPlayer" in code and b"net/minecraft/class_" not in code
    assert all(int.from_bytes(c[6:8], "big") == 61 for c in classes.values())
    return mod, deps, classes


def test_the_neoforge_helper_is_shipped():
    """Minecraft 1.20.2 to 1.20.4: NeoForge 20.2 to 20.4 read META-INF/mods.toml."""
    mod, deps, _ = _neoforge_mod("craft_conductor_ping-neoforge-*.jar", "META-INF/mods.toml")
    assert deps["minecraft"]["versionRange"] == "[1.20.2,1.20.5)"
    assert deps["neoforge"]["versionRange"] == "[20.2,)"
    assert all(d["mandatory"] is True for d in deps.values())     # (NeoForge 20.2 reads "mandatory", 20.4 "type")
    assert mod["displayTest"] == "IGNORE_ALL_VERSION"             # (a client without it is never told it's missing)


def test_the_neoforge1_20_5_helper_is_shipped():
    """Minecraft 1.20.5 and newer: NeoForge reads META-INF/neoforge.mods.toml (and has no display test)."""
    mod, deps, _ = _neoforge_mod("craft_conductor_ping-neoforge1.20.5-*.jar", "META-INF/neoforge.mods.toml")
    assert deps["minecraft"]["versionRange"] == "[1.20.5,)"
    assert deps["neoforge"]["versionRange"] == "[20.2,)"
    assert "displayTest" not in mod and all("mandatory" not in d for d in deps.values())


def test_the_two_neoforge_jars_hold_the_same_classes():
    """The same compile in both: only the metadata file differs."""
    _, _, old = _neoforge_mod("craft_conductor_ping-neoforge-*.jar", "META-INF/mods.toml")
    _, _, new = _neoforge_mod("craft_conductor_ping-neoforge1.20.5-*.jar", "META-INF/neoforge.mods.toml")
    assert old == new
