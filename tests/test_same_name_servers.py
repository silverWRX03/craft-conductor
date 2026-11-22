"""Two servers with the same name on one friend's computer (#254): each gets its own game folder,
launcher profile, Prism instance and extras; a setup made before keeps its folder."""

import json

from craft_conductor import clientpack, join

from test_friends import pack


def test_each_server_keeps_a_name_of_its_own(tmp_path):
    mc = tmp_path / "mc"
    first, second = "a" * 16, "b" * 16
    old = pack(name="A Minecraft Server")  # (from an older Craft Conductor: by its name, as before)
    assert join.server_slug(mc, old) == "a-minecraft-server"
    one = join.validate_pack(pack(name="A Minecraft Server", server_id=first))
    two = join.validate_pack(pack(name="A Minecraft Server", server_id=second))
    assert join.server_slug(mc, one) == "a-minecraft-server"          # (the first keeps the plain name)
    assert join.server_slug(mc, two) == "a-minecraft-server-bbbbbb"   # (another of the same name: apart)
    assert join.server_slug(mc, one) == "a-minecraft-server"          # (and each keeps its own next time)
    renamed = join.validate_pack(pack(name="Our Server", server_id=second))
    assert join.server_slug(mc, renamed) == "a-minecraft-server-bbbbbb"  # (renamed: still its own folder)
    assert "server_id" not in join.validate_pack(pack(server_id="../x"))  # (an odd id isn't used)
    (mc / "craft-conductor" / join.SERVERS_FILE).write_text("not json")
    assert join.server_slug(mc, one) == "a-minecraft-server"  # (a damaged list: starts again)


def test_two_servers_of_the_same_name_dont_share_a_game_folder(tmp_path, http):
    mc = tmp_path / "mc"
    mc.mkdir()
    (mc / "launcher_profiles.json").write_text(json.dumps({"profiles": {}}))
    j = join.Joiner(join.Invite("mc.example.com", 1, "A" * 24), mc_dir=mc, http=http, say=lambda s: None)
    a = j.run(join.validate_pack(pack(name="A Minecraft Server", loader="vanilla", server_id="1" * 16)), open_launcher=False)
    b = j.run(join.validate_pack(pack(name="A Minecraft Server", loader="vanilla", server_id="2" * 16)), open_launcher=False)
    assert a["game_dir"] != b["game_dir"]
    profiles = json.loads((mc / "launcher_profiles.json").read_text())["profiles"]
    assert {"craft-conductor-a-minecraft-server", "craft-conductor-a-minecraft-server-222222"} <= set(profiles)


def test_the_servers_id_is_kept_and_moves_with_it(hub_env, tmp_path):
    """Made once; an export takes it along (the same server, moved); imported where the server already is,
    it's a copy and gets one of its own."""
    from craft_conductor import transfer
    hub, _ = hub_env
    d = hub.get("alpha")
    fid = clientpack.friends_id(d.m.config)
    assert clientpack.friends_id(d.m.config) == fid and clientpack.FRIENDS_ID_FORM.fullmatch(fid)
    export = transfer.export(d.m, tmp_path / "alpha.craft-conductor.zip")
    assert transfer.read_manifest(export)["friends_id"] == fid
    moved = tmp_path / "elsewhere"
    transfer.import_into(export, moved)
    assert (moved / ".craft-conductor" / clientpack.FRIENDS_ID).read_text().strip() == fid
    sid, _ = hub.import_archive(export)  # (a copy on the same computer)
    copy = hub.get(sid)
    assert clientpack.read_friends_id(copy.m.config) is None and clientpack.friends_id(copy.m.config) != fid


def test_the_friend_app_remembers_both_servers_of_the_same_name(tmp_path, monkeypatch):
    """Two hosts, each with "A Minecraft Server": setting up the second kept only it in the list of
    servers the friend app can update without an invite (#305). Each is kept, and told apart."""
    from craft_conductor import clipboard, joinui
    monkeypatch.setattr(clipboard, "invite", lambda: None)  # (not this computer's real clipboard)
    mc = tmp_path / ".minecraft"
    fp = "F" * 43
    a1 = join.Invite("192.168.1.10", 25580, "A" * 24, fp).code
    b1 = join.Invite("friend-b.example.net", 25580, "B" * 24, fp).code
    a2 = join.Invite("192.168.1.10", 25580, "C" * 24, fp).code   # (host A's next invite: same server)
    joinui.remember(mc, "A Minecraft Server", a1, "d1", "a" * 16)
    joinui.remember(mc, "A Minecraft Server", b1, "d2", "b" * 16)
    assert [(x["code"], x.get("server_id")) for x in joinui.remembered(mc)] == [(b1, "b" * 16), (a1, "a" * 16)]
    joinui.remember(mc, "A Minecraft Server", a2, "d3", "a" * 16)   # (the same server again: replaced, not added)
    assert [x["code"] for x in joinui.remembered(mc)] == [a2, b1]
    # Remembered before this (no id): the same name on the same computer is the same server, another computer's isn't.
    old = tmp_path / "old" / ".minecraft"
    joinui.remember(old, "A Minecraft Server", a1)
    joinui.remember(old, "A Minecraft Server", b1, server_id="b" * 16)
    joinui.remember(old, "A Minecraft Server", a2, server_id="a" * 16)
    assert [x["code"] for x in joinui.remembered(old)] == [a2, b1]
    # The page shows whose computer each is, to tell them apart.
    ui = joinui.JoinUI(None, mc_dir=mc)
    hosts = {x["code"]: x["host"] for x in ui.info()["remembered"]}
    assert hosts == {a2: "192.168.1.10", b1: "friend-b.example.net"}
