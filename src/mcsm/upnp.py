"""Opening ports on the router by itself (UPnP), so friends outside can join without anyone
logging in to the router.

Most home routers let a program on the home network ask for a port to be forwarded to it
("UPnP IGD"). mcsm asks only for its own ports (each server's Minecraft port and the
friends' download port), only to this computer, only when you switch it on, and takes them
back when you switch it off. Many routers have UPnP switched off (or don't do it well): then
the router guide is still there, and mcsm says so.

Standard library only: SSDP (a UDP multicast) finds the router, its description (XML over
HTTP) says where to send requests, and each request is a small SOAP message.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

SSDP = ("239.255.255.250", 1900)
SEARCH_TARGETS = ("urn:schemas-upnp-org:device:InternetGatewayDevice:2",
                  "urn:schemas-upnp-org:device:InternetGatewayDevice:1",
                  "urn:schemas-upnp-org:service:WANIPConnection:1")
SERVICES = ("urn:schemas-upnp-org:service:WANIPConnection:2", "urn:schemas-upnp-org:service:WANIPConnection:1",
            "urn:schemas-upnp-org:service:WANPPPConnection:1")
LEASE = 2 * 3600  # renewed every half hour while mcsm runs; routers drop it by themselves after
MAX_XML = 256 * 1024
DESCRIPTION = "mcsm"


class UpnpError(Exception):
    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


@dataclass
class Gateway:
    control_url: str
    service: str
    local_ip: str  # this computer's address on the router's network
    name: str = "your router"
    permanent_only: bool = False  # routers that only take mappings without a time limit
    mapped: dict = field(default_factory=dict)


HOME_NETWORKS = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
                                                     "127.0.0.0/8", "fc00::/7", "fe80::/10", "::1/128")]


def _home_address(host: str) -> bool:
    """A router's address: on the home network (Python's is_private also counts documentation ranges)."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(ip in n for n in HOME_NETWORKS if n.version == ip.version)


def discover(timeout: float = 3.0, sock_factory=None) -> list[tuple[str, str]]:
    """(responder address, description URL) of the routers that answer on this network."""
    make = sock_factory or (lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP))
    found: dict[str, tuple[str, str]] = {}
    with make() as s:
        s.settimeout(0.5)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        for st in SEARCH_TARGETS:
            msg = (f"M-SEARCH * HTTP/1.1\r\nHOST: {SSDP[0]}:{SSDP[1]}\r\nMAN: \"ssdp:discover\"\r\n"
                   f"MX: 2\r\nST: {st}\r\n\r\n").encode()
            s.sendto(msg, SSDP)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, (addr, _) = s.recvfrom(4096)
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                break
            m = re.search(rb"^location:\s*(\S+)", data, re.I | re.M)
            if not m:
                continue
            url = m.group(1).decode("ascii", "replace")
            host = urllib.parse.urlsplit(url).hostname or ""
            # Only a device on the home network, describing itself at its own address.
            if _home_address(addr) and host == addr and url.startswith("http://"):
                found.setdefault(url, (addr, url))
    return list(found.values())


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _fetch(url: str, data: bytes | None = None, headers: dict | None = None, timeout: float = 5) -> bytes:
    host = urllib.parse.urlsplit(url).hostname or ""
    if not url.startswith("http://") or not _home_address(host):
        raise UpnpError("the router gave an address outside the home network")
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    # never through a proxy, and never redirected (off the home network, say)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirects)
    try:
        with opener.open(req, timeout=timeout) as r:
            body = r.read(MAX_XML + 1)
    except urllib.error.HTTPError as e:
        body = e.read(MAX_XML + 1)
        if not body:
            raise UpnpError(f"the router answered HTTP {e.code}") from None
        return body[:MAX_XML]
    except (urllib.error.URLError, OSError) as e:
        raise UpnpError(f"couldn't reach the router ({getattr(e, 'reason', e)})") from None
    if len(body) > MAX_XML:
        raise UpnpError("the router's answer is too big")
    return body


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _local_ip_towards(host: str) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((host, 1900))
        return s.getsockname()[0]


def gateway(responder: str, url: str) -> Gateway:
    """Read a router's description: where to send port-forwarding requests."""
    try:
        root = ET.fromstring(_fetch(url))
    except ET.ParseError:
        raise UpnpError("the router's description isn't readable") from None
    name = next((el.text for el in root.iter() if _local_name(el.tag) == "friendlyName" and el.text), "your router")
    for svc in root.iter():
        if _local_name(svc.tag) != "service":
            continue
        fields = {_local_name(c.tag): (c.text or "").strip() for c in svc}
        if fields.get("serviceType") in SERVICES and fields.get("controlURL"):
            control = urllib.parse.urljoin(url, fields["controlURL"])
            if (urllib.parse.urlsplit(control).hostname or "") != responder:
                continue
            local = _local_ip_towards(responder)
            return Gateway(control, fields["serviceType"], local, name.strip()[:80])
    raise UpnpError(f"{name} doesn't offer port forwarding (UPnP)")


def _soap(gw: Gateway, action: str, args: dict[str, str]) -> dict[str, str]:
    from xml.sax.saxutils import escape
    body = "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in args.items())
    envelope = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
                f'<u:{action} xmlns:u="{gw.service}">{body}</u:{action}></s:Body></s:Envelope>').encode()
    raw = _fetch(gw.control_url, envelope, {"Content-Type": 'text/xml; charset="utf-8"',
                                            "SOAPAction": f'"{gw.service}#{action}"'})
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise UpnpError("the router's answer isn't readable") from None
    values = {_local_name(el.tag): (el.text or "").strip() for el in root.iter()}
    if "errorCode" in values or "faultcode" in values:
        code = values.get("errorCode", "")
        raise UpnpError(ERRORS.get(code, f"the router said no ({values.get('errorDescription') or code or 'error'})"), code)
    return values


ERRORS = {
    "606": "the router only lets its owner change port forwarding (UPnP is locked)",
    "714": "that port isn't forwarded",
    "718": "another device already uses that port on the router",
    "725": "the router only accepts permanent forwards",
    "729": "the router won't forward that port",
}


def external_ip(gw: Gateway) -> str:
    return _soap(gw, "GetExternalIPAddress", {}).get("NewExternalIPAddress", "")


def add(gw: Gateway, port: int, protocol: str = "TCP", label: str = DESCRIPTION) -> None:
    args = {"NewRemoteHost": "", "NewExternalPort": port, "NewProtocol": protocol, "NewInternalPort": port,
            "NewInternalClient": gw.local_ip, "NewEnabled": 1, "NewPortMappingDescription": label[:60],
            "NewLeaseDuration": 0 if gw.permanent_only else LEASE}
    try:
        _soap(gw, "AddPortMapping", args)
    except UpnpError as e:
        if e.code == "725" and not gw.permanent_only:
            gw.permanent_only = True
            return add(gw, port, protocol, label)
        raise
    gw.mapped[(port, protocol)] = label


def remove(gw: Gateway, port: int, protocol: str = "TCP") -> None:
    try:
        _soap(gw, "DeletePortMapping", {"NewRemoteHost": "", "NewExternalPort": port, "NewProtocol": protocol})
    except UpnpError as e:
        if e.code != "714":
            raise
    gw.mapped.pop((port, protocol), None)


def find(timeout: float = 3.0) -> Gateway:
    """The first router on the network that does port forwarding."""
    routers = discover(timeout)
    if not routers:
        raise UpnpError("no router answered: UPnP is probably switched off on it (or this computer's "
                        "firewall blocks the answer)")
    last = None
    for responder, url in routers:
        try:
            return gateway(responder, url)
        except UpnpError as e:
            last = e
    raise last or UpnpError("no router does port forwarding")


def shared_address(ip: str) -> str | None:
    """Why forwarding can't help when the router's own internet address isn't a public one."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if addr in ipaddress.ip_network("100.64.0.0/10"):
        return ("your internet provider shares one internet address between many homes (CGNAT), so forwarded "
                "ports can't be reached from outside: use a playit.gg tunnel instead")
    if _home_address(ip):
        return ("this router is behind another router (double NAT): forward the ports on the other one too, "
                "or use a playit.gg tunnel")
    return None
