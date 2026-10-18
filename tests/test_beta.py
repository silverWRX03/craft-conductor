"""Trying beta Minecraft versions: offered in setup, and tested on a copy of a server."""

from craft_conductor import config as configmod, packupdate, setup as setupmod
from craft_conductor.config import ModSpec
from craft_conductor.lock import Lock

from conftest import FakeMojang
from test_hub import login
from test_planner import planner
from test_web import wait_for


def test_betas_are_listed_newest_first(http):
    mojang = FakeMojang(http, ["1.21.1", "1.21.2"])
    assert mojang.betas() == ["99w01a"]
    for v in ("99w01a", "1.21.5-pre1", "1.21.5-rc2"):
        assert setupmod.SetupSpec.from_dict({"loader": "fabric", "minecraft": v, "accept_eula": True}).minecraft == v


def test_a_beta_server_stays_on_its_beta(make_config, http, modrinth):
    modrinth.project("AAA", "lithium")
    modrinth.version("AAA", "1.0", ["1.21.1", "99w01a"])
    cfg = make_config([ModSpec("modrinth", "lithium")], strategy="latest-compatible")
    decision = planner(cfg, http, lock=Lock(minecraft="99w01a", launch=["x"])).decide()
    assert decision.plan.minecraft == "99w01a"  # never "upgraded" back to an older release


def test_test_copy_on_a_beta(hub_env):
    hub, c = hub_env
    login(c)
    r = c.get("/api/servers/alpha/beta")[1]
    assert r["betas"] == ["99w01a"] and r["copies"]
    assert c.post("/api/servers/alpha/beta/test", {"version": "1.21.1"})[0] == 400
    alpha = hub.get("alpha")
    # (made from a modpack: its loader held at the pack's build, for the pack's Minecraft)
    configmod.set_value(alpha.m.config.path, "server", "minecraft", '"1.21.1"')
    configmod.hold_loader(alpha.m.config.path, "0.16.0")
    packupdate.record(alpha.m.config.root, "modrinth", "PACKPROJ", "PACKV001", "Test Pack 1.0", {}, [], {}, {})
    alpha.m.reload_config()
    assert c.post("/api/servers/alpha/beta/test", {"version": "99w01a"})[0] == 200
    wait_for(lambda: alpha.last_job and alpha.last_job["name"] == "beta test copy", timeout=30)
    assert alpha.last_job["ok"], alpha.last_job
    copy = hub.get("alpha-beta-99w01a")
    wait_for(lambda: copy.last_job and copy.last_job["name"] == "install beta", timeout=30)
    assert copy.last_job["ok"], copy.last_job
    assert copy.m.lock.minecraft == "99w01a" and copy.m.config.updates.strategy == "mods-only"
    assert all(not s.required for s in copy.m.config.mods)
    # The pack's loader build is for the pack's Minecraft, and the copy isn't a version of the pack.
    assert copy.m.lock.loader_version == "loader-99w01a" and copy.m.config.modpack is None
    assert alpha.m.lock.minecraft == "1.21.1"  # the original is untouched
    assert alpha.m.config.server.loader_version == "0.16.0" and alpha.m.config.modpack is not None
    assert c.get("/api/hub")[1]["servers"]
