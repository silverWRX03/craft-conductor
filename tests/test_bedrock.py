"""Bedrock players through Geyser: whether the server can, whether it's on, and the port."""

from mcsm import config as configmod
from mcsm.config import ModSpec

from test_hub import login


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
