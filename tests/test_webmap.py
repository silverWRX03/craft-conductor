"""The web map: which one is installed, its port, and BlueMap's download OK."""

from types import SimpleNamespace

import pytest

from craft_conductor import webmap


def mod(name, filename=""):
    return SimpleNamespace(name=name, key=name.lower(), filename=filename)


def test_which_map_is_installed():
    assert webmap.installed([mod("Lithium"), mod("BlueMap", "bluemap-5.4-fabric.jar")]) == "bluemap"
    assert webmap.installed([mod("dynmap®")]) == "dynmap"
    assert webmap.installed([mod("Chunky")]) is None


def test_port_and_download(tmp_path):
    folder = tmp_path / "config" / "bluemap"
    assert webmap.port(tmp_path, "bluemap", "fabric") == 8100  # not set up yet: the default
    with pytest.raises(webmap.WebMapError):
        webmap.set_port(tmp_path, "bluemap", "fabric", 8200)
    assert webmap.download_accepted(tmp_path, "fabric") is None
    folder.mkdir(parents=True)
    (folder / "webserver.conf").write_text('enabled: true\n# the port\nport: 8100\nlog: {\n  file: "x"\n}\n')
    (folder / "core.conf").write_text("# read Mojang's terms\naccept-download: false\nrender-thread-count: 1\n")
    assert webmap.download_accepted(tmp_path, "fabric") is False
    webmap.accept_download(tmp_path, "fabric")
    assert webmap.download_accepted(tmp_path, "fabric") is True
    assert "render-thread-count: 1" in (folder / "core.conf").read_text()
    webmap.set_port(tmp_path, "bluemap", "fabric", 8200)
    assert webmap.port(tmp_path, "bluemap", "fabric") == 8200
    with pytest.raises(webmap.WebMapError):
        webmap.set_port(tmp_path, "bluemap", "fabric", 25565, taken={25565})
    with pytest.raises(webmap.WebMapError):
        webmap.set_port(tmp_path, "bluemap", "fabric", 80)


def test_dynmap_as_a_plugin(tmp_path):
    folder = tmp_path / "plugins" / "dynmap"
    folder.mkdir(parents=True)
    (folder / "configuration.txt").write_text("deftemplatesuffix: hires\nwebserver-bindaddress: 0.0.0.0\nwebserver-port: 8123\n")
    assert webmap.port(tmp_path, "dynmap", "paper") == 8123
    webmap.set_port(tmp_path, "dynmap", "paper", 8124)
    assert "webserver-port: 8124" in (folder / "configuration.txt").read_text()


def test_the_page(hub_env):
    from test_hub import login
    hub, c = hub_env
    login(c)
    status, r, _ = c.get("/api/servers/alpha/webmap")
    assert status == 200 and r["kind"] is None and r["maps"] == {"bluemap": "BlueMap", "dynmap": "Dynmap"}
    assert c.post("/api/servers/alpha/webmap/add", {"kind": "squaremap"})[0] == 400
    assert c.post("/api/servers/alpha/webmap/port", {"port": 8200})[0] == 400
