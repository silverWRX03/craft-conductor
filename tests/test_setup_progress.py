"""What creating a server shows while it works (roadmap 49): each step, and how many of the mods
are in, reported by the manager and kept in the daemon's job for the setup page."""

import pytest

from craft_conductor import config as configmod, setup as setupmod
from craft_conductor.config import ModSpec
from craft_conductor.daemon import Daemon

from test_manager import manager, update


def two_mods(modrinth):
    modrinth.project("FAPI", "fabric-api", "Fabric API")  # (a new Fabric server gets it)
    modrinth.version("FAPI", "0.1", ["1.21.1"])
    modrinth.project("AAA", "goodmod", "Good Mod")
    modrinth.version("AAA", "1.0", ["1.21.1"])
    modrinth.project("BBB", "othermod", "Other Mod")
    modrinth.version("BBB", "1.0", ["1.21.1"])


def test_the_manager_reports_each_step(make_config, http, modrinth):
    two_mods(modrinth)
    m = manager(make_config([ModSpec("modrinth", "goodmod"), ModSpec("modrinth", "othermod")]), http, ["1.21.1"])
    seen = []
    m.progress = lambda *a: seen.append(a)
    assert update(m).ok
    assert seen[0] == ("java", None, None)
    order = [("mods", 0, 2), ("mods", 2, 2), ("runtime", None, None), ("boot", None, None)]
    at = [seen.index(x) for x in order]
    assert at == sorted(at), seen


def test_a_broken_progress_callback_doesnt_stop_the_install(make_config, http, modrinth):
    two_mods(modrinth)
    m = manager(make_config([ModSpec("modrinth", "goodmod")]), http, ["1.21.1"])

    def broken(*a):
        raise RuntimeError("the page went away")
    m.progress = broken
    assert update(m).ok


def setup_daemon(make_config, http):
    cfg = make_config()
    m = manager(cfg, http, ["1.21.1"])
    m.reload_config = lambda: setattr(m, "config", configmod.load(cfg.root))  # (keeping the made-up loader)
    d = Daemon(m, autostart=False)
    d.job = {"name": "set up server"}
    seen = []
    real = d._progress

    def spy(*a):
        real(*a)
        seen.append(dict(d.job["progress"]))
    d._progress = spy
    return d, seen


def test_setup_records_progress_in_the_job(make_config, http, modrinth, fake_template):
    two_mods(modrinth)
    d, seen = setup_daemon(make_config, http)
    d.run_setup(setupmod.SetupSpec.from_dict({"loader": "fabric", "minecraft": "1.21.1", "mods": ["goodmod"],
                                              "accept_eula": True}))
    assert seen[0]["steps"] == ["plan", "java", "mods", "runtime", "boot"] and seen[0]["step"] == "plan"
    assert [s["step"] for s in seen if s["step"] != "mods"] == ["plan", "java", "runtime", "boot"]
    assert {"step": "mods", "done": 2, "total": 2} == {k: seen[-3][k] for k in ("step", "done", "total")}
    assert d.m.progress is None


def test_a_failed_setup_clears_the_progress_callback(make_config, http, modrinth, fake_template):
    d, seen = setup_daemon(make_config, http)
    with pytest.raises(Exception):
        d.run_setup(setupmod.SetupSpec.from_dict({"loader": "fabric", "minecraft": "1.21.1", "mods": ["nosuchmod"],
                                                  "accept_eula": True}))
    assert seen and d.m.progress is None
