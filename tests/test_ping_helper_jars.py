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
