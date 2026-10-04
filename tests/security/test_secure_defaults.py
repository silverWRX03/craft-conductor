"""Nothing is reachable from the network until the owner asks: the control panel listens on
127.0.0.1 (a computer without a screen too), and the router is left alone."""

from __future__ import annotations

import pytest

from craft_conductor import cli, config as configmod, service, setup as setupmod
from craft_conductor.hub import Hub

LOOPBACK = ("127.0.0.1", "localhost", "::1")


def test_the_panel_listens_on_localhost_by_default(hub_env):
    hub, _ = hub_env
    assert configmod.WebConfig().host == "127.0.0.1"
    assert 'host = "127.0.0.1"' in configmod.TEMPLATE
    assert hub.web.host == "127.0.0.1" and hub.ui.httpd.server_address[0] == "127.0.0.1"
    assert not hub.ui.remote_on()


def test_a_new_server_doesnt_open_the_panel(tmp_path):
    spec = setupmod.SetupSpec.from_dict({"loader": "fabric", "accept_eula": True})
    assert spec.network_access is False
    setupmod.configure(tmp_path / "s", spec)
    assert configmod.load(tmp_path / "s").web.host == "127.0.0.1"


@pytest.fixture
def start(tmp_path, monkeypatch):
    """`craft-conductor start` on a computer without a screen, up to the point the panel would open."""
    home = tmp_path / "home"
    monkeypatch.setattr(cli, "default_home", lambda: home)
    monkeypatch.setattr(cli, "has_display", lambda: False)
    monkeypatch.delenv("CRAFT_CONDUCTOR_INITIAL_PASSWORD", raising=False)
    seen = {}

    def run(self):
        seen["host"] = self.web.host
        return 0
    monkeypatch.setattr(Hub, "run", run)

    def go(*flags):
        args = cli.build_parser().parse_args(["-C", str(tmp_path / "elsewhere"), "start", "--no-browser", *flags])
        args.root = args.root.resolve()
        assert cli.cmd_start(args) == 0
        return seen["host"], home
    return go


def test_a_computer_without_a_screen_stays_on_localhost(start, capsys):
    host, home = start()
    out = capsys.readouterr().out
    assert host == "127.0.0.1"
    assert "web" not in Hub(home)._hub_file()  # nothing saved that opens it later either
    assert "ssh -L" in out and "Craft-Conductor-" in out  # reached through SSH, with a one-time password


def test_opening_it_to_the_network_is_asked_for(start, capsys):
    host, home = start("--web-host", "0.0.0.0")
    out = capsys.readouterr().out
    assert host == "0.0.0.0"
    # Never the built-in PASSWORD on a panel other devices can reach: a one-time one instead.
    assert "Craft-Conductor-" in out and "PASSWORD" not in out
    assert "web" not in Hub(home)._hub_file()  # (for this run only)


def test_the_boot_service_never_overrides_the_address(tmp_path):
    for panel in (True, False):
        text = service.plan(tmp_path, system=False, home=tmp_path, panel=panel).text
        assert "--web-host" not in text and "0.0.0.0" not in text


def test_the_setup_questions_default_to_this_computer_only(tmp_path, monkeypatch):
    asked = {}

    def answer(question, default, choices=None):
        asked[question] = default
        if "EULA" in question:
            return "no"  # (stop there: nothing gets set up)
        return default
    monkeypatch.setattr(cli, "_ask", answer)
    monkeypatch.setattr(cli, "has_display", lambda: False)
    cli._wizard(tmp_path)
    assert next(d for q, d in asked.items() if "other devices" in q) == "no"


def test_upnp_is_off_until_switched_on(tmp_path):
    hub = Hub(tmp_path)
    assert hub.upnp_settings()["enabled"] is False
    assert hub.upnp_status()["enabled"] is False and hub.upnp_status()["exposure"] == ""
