"""A modpack's mods are held at the pack's files: only the pack's next version changes them."""

from craft_conductor import config as configmod
from craft_conductor.config import ModSpec
from craft_conductor.mods import providers_for

from test_manager import manager, update


def test_a_pack_mod_stays_on_the_packs_file_and_brings_nothing_the_pack_leaves_out(make_config, http, modrinth):
    modrinth.project("LIB", "iris", "Iris")        # a client-only mod the pack's author left out
    modrinth.version("LIB", "1.0", ["1.21.1"])
    modrinth.project("AAA", "goodmod", "Good Mod")
    modrinth.version("AAA", "1.0", ["1.21.1"], deps=["LIB"])
    modrinth.version("AAA", "1.1", ["1.21.1"], deps=["LIB"])  # newer than the pack's
    cfg = make_config([ModSpec("modrinth", "AAA", pack=True)])
    configmod.set_pin(cfg.path, "modrinth:AAA", configmod.Pin("AAA-1.0", "1.21.1"))
    cfg = configmod.load(cfg.root)
    assert cfg.mods[0].pack and cfg.pins["modrinth:AAA"].version == "AAA-1.0"

    m = manager(cfg, http, ["1.21.1"])
    assert update(m).ok
    assert [(x.name, x.version_id) for x in m.lock.mods] == [("Good Mod", "AAA-1.0")]  # not 1.1, and no Iris

    # a mod the person adds later still brings what it needs
    modrinth.project("BBB", "extra", "Extra")
    modrinth.version("BBB", "1.0", ["1.21.1"], deps=["LIB"])
    configmod.append_mod(cfg.path, ModSpec("modrinth", "BBB"))
    m.reload_config()
    assert update(m).ok
    assert {x.name for x in m.lock.mods} == {"Good Mod", "Extra", "Iris"}
    assert next(x for x in m.lock.mods if x.name == "Good Mod").version_id == "AAA-1.0"


def test_the_pack_flag_is_kept_in_the_config_file(tmp_path):
    path = tmp_path / "craft-conductor.toml"
    path.write_text(configmod.render_template("fabric", "1.21.1"))
    configmod.append_mod(path, ModSpec("modrinth", "AAA", pack=True))
    configmod.append_mod(path, ModSpec("modrinth", "BBB"))
    assert [(m.id, m.pack) for m in configmod.load(tmp_path).mods] == [("AAA", True), ("BBB", False)]
