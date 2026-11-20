"""The shipped Craft Conductor Ping helper jars (built from helpers/ping/ by tools/build_helpers.py)."""
import zipfile
from pathlib import Path

HELPERS = Path(__file__).resolve().parent.parent / "src" / "craft_conductor" / "helpers"


def _only_ours(names):
    # "craft_conductor/" is only the folder entry that holds craft_conductor/ping/.
    return [n for n in names if not (n in ("plugin.yml", "craft_conductor/") or n.startswith("META-INF/")
                                     or n.startswith("craft_conductor/ping/"))]


def test_the_paper_helper_is_shipped():
    jars = sorted(HELPERS.glob("craft_conductor_ping-paper-*.jar"))
    assert len(jars) == 1, jars
    with zipfile.ZipFile(jars[0]) as z:
        yml = z.read("plugin.yml").decode("utf-8")
        names = z.namelist()
    assert "name: craft_conductor_ping" in yml.splitlines()
    assert 'api-version: "1.17"' in yml.splitlines()
    assert "main: craft_conductor.ping.PingPlugin" in yml.splitlines()
    assert _only_ours(names) == []
    assert "craft_conductor/ping/PingPlugin.class" in names
