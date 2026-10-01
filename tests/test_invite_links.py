"""Invite links friends click: craft-conductor's invite page, and craft-conductor:// links that open craft-conductor."""

import pytest

from craft_conductor import join, urlhandler

FP = "F" * 43


def test_invite_page_links_carry_the_invite_after_the_hash():
    inv = join.Invite("mc.example.com", 8766, "A" * 24, FP)
    link = inv.page_link("Weekend Survival!")
    assert link.startswith(join.INVITE_PAGE + "#craft-conductor-") and link.endswith("/Weekend%20Survival%21")
    for text in (link, f"craft-conductor://join/{inv.code}", f"Join us: {link} (see you there)", inv.code):
        assert join.parse_invite(text) == inv
    with pytest.raises(join.JoinError):
        join.parse_invite(join.INVITE_PAGE + "#craft-conductor-short")


def test_craft_conductor_links_open_this_craft_conductor_on_linux(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    ran = []
    monkeypatch.setattr(urlhandler.shutil, "which", lambda name: "/usr/bin/xdg-mime")
    monkeypatch.setattr(urlhandler.subprocess, "run", lambda args, **kw: ran.append(args))
    assert urlhandler._linux("/home/me/craft-conductor-linux-x64")  # (the Linux part runs on any system)
    entry = (tmp_path / "applications" / urlhandler.DESKTOP_FILE).read_text(encoding="utf-8")
    assert 'Exec="/home/me/craft-conductor-linux-x64" join -- %u' in entry and "x-scheme-handler/craft-conductor;" in entry
    assert ran == [["xdg-mime", "default", urlhandler.DESKTOP_FILE, "x-scheme-handler/craft-conductor"]]
    assert not urlhandler._linux('/home/me/odd"name')  # never anything that could break the Exec line


def test_nothing_registered_when_not_the_standalone_app(monkeypatch):
    monkeypatch.setattr("craft_conductor.selfupdate.frozen", lambda: False)
    assert urlhandler.register() is False


def test_invite_page_decodes_the_full_command_prefix():
    """The hosted join page must decode the same invite as the Python client."""
    import json
    import shutil
    import subprocess
    from pathlib import Path

    if shutil.which("node") is None:
        pytest.skip("needs Node.js")
    source = (Path(__file__).resolve().parents[1] / "site" / "join" / "join.js").read_text()
    parser = source[source.index("function readInvite("):source.index("function detectOS(")]
    invite = join.Invite("mc.example.com", 8798, "A" * 24, FP)
    hashes = [invite.code + "/Weekend%20Survival", "craft-conductor-short",
              "craft-conductor-" + "A" * 45, "%broken"]
    program = parser + "\nconsole.log(JSON.stringify(" + json.dumps(hashes) + ".map(readInvite)));"
    result = subprocess.run(["node", "-e", program], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == [
        {"code": invite.code, "name": "Weekend Survival"}, None, None, None]
