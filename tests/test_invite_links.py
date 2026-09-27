"""Invite links friends click: mcsm's invite page, and mcsm:// links that open mcsm."""

import pytest

from mcsm import join, urlhandler

FP = "F" * 43


def test_invite_page_links_carry_the_invite_after_the_hash():
    inv = join.Invite("mc.example.com", 8766, "A" * 24, FP)
    link = inv.page_link("Weekend Survival!")
    assert link.startswith(join.INVITE_PAGE + "#mcsm-") and link.endswith("/Weekend%20Survival%21")
    for text in (link, f"mcsm://join/{inv.code}", f"Join us: {link} (see you there)", inv.code):
        assert join.parse_invite(text) == inv
    with pytest.raises(join.JoinError):
        join.parse_invite(join.INVITE_PAGE + "#mcsm-short")


def test_mcsm_links_open_this_mcsm_on_linux(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    ran = []
    monkeypatch.setattr(urlhandler.shutil, "which", lambda name: "/usr/bin/xdg-mime")
    monkeypatch.setattr(urlhandler.subprocess, "run", lambda args, **kw: ran.append(args))
    assert urlhandler._linux("/home/me/mcsm-linux-x64")  # (the Linux part runs on any system)
    entry = (tmp_path / "applications" / urlhandler.DESKTOP_FILE).read_text(encoding="utf-8")
    assert 'Exec="/home/me/mcsm-linux-x64" join -- %u' in entry and "x-scheme-handler/mcsm;" in entry
    assert ran == [["xdg-mime", "default", urlhandler.DESKTOP_FILE, "x-scheme-handler/mcsm"]]
    assert not urlhandler._linux('/home/me/odd"name')  # never anything that could break the Exec line


def test_nothing_registered_when_not_the_standalone_app(monkeypatch):
    monkeypatch.setattr("mcsm.selfupdate.frozen", lambda: False)
    assert urlhandler.register() is False
