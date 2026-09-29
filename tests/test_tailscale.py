"""Tailscale serve: the secure address for the phone app."""

import sys
import time

from mcsm import tailscale

WAITS = ("print('Serve is not enabled on your tailnet.'); print('To enable, visit:'); print(); "
         "print('         https://login.tailscale.com/f/serve?node=abc123'); import sys, time; sys.stdout.flush(); time.sleep(60)")


def fake(monkeypatch, script):
    monkeypatch.setattr(tailscale, "_argv", lambda args: [sys.executable, "-c", script])


def test_serve_passes_on_the_link_to_switch_it_on(monkeypatch):
    """tailscale serve prints the link and then waits: the wait ended in a timeout that said
    "Tailscale isn't installed on this computer", and the link was lost."""
    fake(monkeypatch, WAITS)
    began = time.monotonic()
    r = tailscale.serve(8765, timeout=20)
    assert time.monotonic() - began < 15  # (as soon as the link is printed)
    assert r == {"ok": False, "message": "Serve is not enabled on your tailnet.",
                 "enable_url": "https://login.tailscale.com/f/serve?node=abc123"}


def test_serve_works_and_fails(monkeypatch):
    fake(monkeypatch, "print('Available within your tailnet: https://pc.tail.ts.net/')")
    assert tailscale.serve(8765)["ok"]
    fake(monkeypatch, "import sys; print('serve: not logged in'); sys.exit(1)")
    assert tailscale.serve(8765) == {"ok": False, "message": "serve: not logged in", "enable_url": None}
    monkeypatch.setattr(tailscale, "_argv", lambda args: None)
    assert "isn't installed" in tailscale.serve(8765)["message"]
