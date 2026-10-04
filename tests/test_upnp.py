"""Automatic port forwarding (UPnP) against a fake router."""

import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from craft_conductor import upnp

from test_hub import login

SERVICE = "urn:schemas-upnp-org:service:WANIPConnection:1"
DESCRIPTION = f"""<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0"><device><friendlyName>Test Router</friendlyName>
<deviceList><device><deviceList><device><serviceList>
<service><serviceType>{SERVICE}</serviceType><controlURL>/ctl</controlURL></service>
</serviceList></device></deviceList></device></deviceList></device></root>"""


class Router:
    def __init__(self, external="203.0.113.7", permanent_only=False, locked=False):
        self.mappings: dict = {}
        self.external, self.permanent_only, self.locked = external, permanent_only, locked
        router = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = DESCRIPTION.encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                data = self.rfile.read(int(self.headers["Content-Length"])).decode()
                action = self.headers["SOAPAction"].strip('"').split("#")[1]
                arg = lambda name: (re.search(f"<{name}>(.*?)</{name}>", data) or [None, ""])[1]  # noqa: E731
                out, fault = "", None
                if action == "AddPortMapping":
                    if router.locked:
                        fault = "606"
                    elif router.permanent_only and arg("NewLeaseDuration") != "0":
                        fault = "725"
                    else:
                        router.mappings[(int(arg("NewExternalPort")), arg("NewProtocol"))] = (arg("NewInternalClient"), arg("NewPortMappingDescription"))
                elif action == "DeletePortMapping":
                    if router.mappings.pop((int(arg("NewExternalPort")), arg("NewProtocol")), None) is None:
                        fault = "714"
                elif action == "GetExternalIPAddress":
                    out = f"<NewExternalIPAddress>{router.external}</NewExternalIPAddress>"
                if fault:
                    body = (f'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body><s:Fault><faultcode>s:Client</faultcode>'
                            f'<detail><UPnPError xmlns="urn:schemas-upnp-org:control-1-0"><errorCode>{fault}</errorCode>'
                            f'<errorDescription>nope</errorDescription></UPnPError></detail></s:Fault></s:Body></s:Envelope>').encode()
                    self.send_response(500)
                else:
                    body = (f'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
                            f'<u:{action}Response xmlns:u="{SERVICE}">{out}</u:{action}Response></s:Body></s:Envelope>').encode()
                    self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/desc.xml"

    def close(self):
        self.server.shutdown()


@pytest.fixture
def router(monkeypatch):
    r = Router()
    monkeypatch.setattr(upnp, "discover", lambda timeout=3.0: [("127.0.0.1", r.url)])
    yield r
    r.close()


def test_forwarding_ports(router):
    gw = upnp.find()
    assert gw.name == "Test Router" and gw.local_ip == "127.0.0.1"
    upnp.add(gw, 25565)
    assert router.mappings[(25565, "TCP")] == ("127.0.0.1", "craft-conductor")
    assert upnp.external_ip(gw) == "203.0.113.7"
    upnp.remove(gw, 25565)
    upnp.remove(gw, 25565)  # already gone: fine
    assert router.mappings == {}
    router.permanent_only = True  # routers that won't take a time limit
    upnp.add(gw, 25566)
    assert gw.permanent_only and (25566, "TCP") in router.mappings
    router.locked = True
    with pytest.raises(upnp.UpnpError, match="locked"):
        upnp.add(gw, 25567)


def test_shared_addresses_are_explained():
    assert "CGNAT" in upnp.shared_address("100.72.1.9")
    assert "double NAT" in upnp.shared_address("192.168.0.2")
    assert upnp.shared_address("203.0.113.7") is None


def test_only_routers_on_the_home_network_are_believed():
    class FakeSock:
        def __init__(self):
            self.answers = [
                (b"HTTP/1.1 200 OK\r\nLOCATION: http://192.168.1.1:5000/desc.xml\r\n\r\n", ("192.168.1.1", 1900)),
                (b"HTTP/1.1 200 OK\r\nLOCATION: http://8.8.8.8/desc.xml\r\n\r\n", ("192.168.1.9", 1900)),  # elsewhere
                (b"HTTP/1.1 200 OK\r\nLOCATION: http://93.184.216.34/d.xml\r\n\r\n", ("93.184.216.34", 1900)),  # not home
            ]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def settimeout(self, t):
            pass

        def setsockopt(self, *a):
            pass

        def sendto(self, data, addr):
            assert b"M-SEARCH" in data and addr == upnp.SSDP

        def recvfrom(self, n):
            if self.answers:
                return self.answers.pop(0)
            raise socket.timeout

    assert upnp.discover(timeout=0.3, sock_factory=FakeSock) == [("192.168.1.1", "http://192.168.1.1:5000/desc.xml")]
    with pytest.raises(upnp.UpnpError):
        upnp._fetch("http://93.184.216.34/desc.xml")


def test_the_search_goes_out_the_adapter_the_internet_uses(monkeypatch):
    """With several adapters (Wi-Fi Direct, Hyper-V, VPNs), Windows sent the search out one with no
    router behind it: "no router answered" with UPnP switched on and no firewall."""
    options = []

    class FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def settimeout(self, t):
            pass

        def setsockopt(self, *a):
            options.append(a)

        def sendto(self, data, addr):
            pass

        def recvfrom(self, n):
            raise socket.timeout

    monkeypatch.setattr(upnp, "_lan_address", lambda: "192.168.1.69")
    upnp.discover(timeout=0.1, sock_factory=FakeSock)
    assert (socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton("192.168.1.69")) in options
    monkeypatch.undo()
    monkeypatch.setattr(upnp, "_local_ip_towards", lambda host: "169.254.4.5")  # no network behind it
    assert upnp._lan_address() is None
    monkeypatch.setattr(upnp, "_local_ip_towards", lambda host: "10.0.0.7")
    assert upnp._lan_address() == "10.0.0.7"


def test_switching_it_on_and_off_from_the_page(hub_env, router):
    hub, c = hub_env
    login(c)
    assert c.get("/api/hub/upnp")[1]["enabled"] is False
    # Switching it on is agreed to first, knowing it opens the server to the internet.
    status, r, _ = c.post("/api/hub/upnp", {"enabled": True})
    assert status == 400 and "whole internet" in r["error"] and not router.mappings
    assert c.post("/api/servers/alpha/doctor/fix", {"action": "upnp"})[0] in (400, 409) and not router.mappings
    status, r, _ = c.post("/api/hub/upnp", {"enabled": True, "accept": True})
    assert status == 200 and r["enabled"] and not r["error"], r
    assert r["exposure"] == upnp.EXPOSURE_WARNING
    assert c.post("/api/hub/upnp", {})[1]["enabled"]  # (checking again needs no new agreement)
    assert r["router"] == "Test Router" and r["external_ip"] == "203.0.113.7"
    ports = {p["port"] for p in r["ports"] if p["ok"]}
    assert ports and all((p, "TCP") in router.mappings for p in ports)
    assert hub.upnp_settings()["mapped"]
    checks = c.get("/api/servers/alpha/doctor")[1]["checks"]
    assert any(x["id"] == "router" and x["status"] == "ok" for x in checks), checks
    # off: craft-conductor takes back what it forwarded (and only that)
    router.mappings[(8080, "TCP")] = ("192.168.1.50", "someone else's")
    r = c.post("/api/hub/upnp", {"enabled": False})[1]
    assert not r["enabled"] and list(router.mappings) == [(8080, "TCP")] and r["exposure"] == ""
    assert hub.upnp_settings()["mapped"] == []
    assert c.post("/api/hub/upnp", {"enabled": "yes"})[0] == 400


def test_a_router_without_upnp_says_so(hub_env, monkeypatch):
    hub, c = hub_env
    login(c)
    monkeypatch.setattr(upnp, "discover", lambda timeout=3.0: [])
    r = c.post("/api/hub/upnp", {"enabled": True, "accept": True})[1]
    assert r["enabled"] and "switched off" in r["error"]
    checks = c.get("/api/servers/alpha/doctor")[1]["checks"]
    assert any(x["id"] == "router" and x["status"] == "warn" for x in checks)


def test_upnp_is_off_by_default_and_never_opens_the_panel(hub_env):
    hub, c = hub_env
    assert hub.upnp_settings()["enabled"] is False and hub.upnp_status()["exposure"] == ""
    # Even a server whose game port is the control panel's (or its RCON port) isn't forwarded.
    alpha = hub.daemons["alpha"]
    props = alpha.m.server_dir / "server.properties"
    from craft_conductor.properties import write_properties
    panel = hub.ui.httpd.server_address[1]
    write_properties(props, {"server-port": str(panel)})
    assert all(port != panel for port, _, _ in hub.upnp_wanted())
    write_properties(props, {"server-port": "25600", "enable-rcon": "true", "rcon.port": "25600"})
    assert all(port != 25600 for port, _, _ in hub.upnp_wanted())
    write_properties(props, {"enable-rcon": "false"})
    assert any(port == 25600 for port, _, _ in hub.upnp_wanted())


def test_the_page_shows_the_same_warning():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] / "src" / "craft_conductor" / "webui" / "app.js").read_text(encoding="utf-8")
    start = js.index("const UPNP_WARNING = ")
    text = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', js[start:js.index('";\n', start) + 1]))
    assert text == upnp.EXPOSURE_WARNING
