"""Bedrock players through Geyser: whether the server can, whether it's on, and the port."""

from craft_conductor import config as configmod
from craft_conductor.config import ModSpec

from test_hub import login


def test_bedrock_offers_beta_without_changing_server_policy(hub_env, modrinth):
    hub, c = hub_env
    login(c)
    modrinth.project("GEY", "geyser", "Geyser")
    modrinth.version("GEY", "2.11", ["1.21.1"], version_type="beta")
    modrinth.project("FLO", "floodgate", "Floodgate")
    modrinth.version("FLO", "2.2", ["1.21.1"])
    code, r, _ = c.get("/api/servers/alpha/bedrock/check")
    assert code == 200
    assert [(x["id"], x["channel"]) for x in r["mods"]] == [("geyser", "beta"), ("floodgate", "release")]
    assert hub.get("alpha").m.config.updates.mod_channel == "release"
    assert not {s.id for s in hub.get("alpha").m.config.mods} & {"geyser", "floodgate"}


def test_bedrock_status(hub_env):
    hub, c = hub_env
    login(c)
    r = c.get("/api/servers/alpha/bedrock")[1]
    assert r["supported"] is True and r["geyser"] is False and r["port"] == 19132
    d = hub.get("alpha")
    for mod in ("geyser", "floodgate"):
        configmod.append_mod(d.m.config.path, ModSpec("modrinth", mod, required=False))
    d.m.reload_config()
    cfg = d.m.server_dir / "config" / "Geyser-Fabric" / "config.yml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("bedrock:\n  address: 0.0.0.0\n  port: 19133\nremote:\n  port: 25565\n")
    r = c.get("/api/servers/alpha/bedrock")[1]
    assert r["geyser"] and r["floodgate"] and r["port"] == 19133
