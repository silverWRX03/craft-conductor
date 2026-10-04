"""Invites and pairing: each kind of link is limited in the way that fits how it's used.

* A friends' invite link is shared (a Discord channel, a group chat), so it can't be single-use.
  It stops working by itself after the time the owner picked (7 days unless they choose), and
  the owner can stop or replace it at any moment.
* A phone pairing code is for one phone: it works once, for five minutes, and can be cancelled.
"""

from __future__ import annotations

import threading
import time
import urllib.request

import pytest

from craft_conductor import clientpack, config as configmod, join, share, web, webauth
from craft_conductor.config import ClientConfig, ConfigError
from craft_conductor.http import HttpClient, HttpError

from test_friends import free_port
from test_hub import login

DAY = 86400


# ------------------------------------------------------------- friends' invite links
def test_a_link_works_until_it_expires():
    now = 1_000_000.0
    assert ClientConfig(enabled=True, token="t" * 24, expires=int(now) + 60).link_works(now)
    assert not ClientConfig(enabled=True, token="t" * 24, expires=int(now)).link_works(now)
    assert ClientConfig(enabled=True, token="t" * 24, expires=0).link_works(now)  # chosen: until replaced
    assert not ClientConfig(enabled=False, token="t" * 24, expires=0).link_works(now)
    assert not ClientConfig(enabled=True, token="", expires=0).link_works(now)


def test_new_links_expire_after_seven_days_unless_chosen(tmp_path):
    assert configmod.DEFAULT_LINK_DAYS == 7 and ClientConfig().link_days == 7
    root = tmp_path / "s"
    root.mkdir()
    path = root / configmod.CONFIG_NAME
    path.write_text(configmod.render_template("fabric", "latest"))
    clientpack.make_link(path, now=1_000_000)
    c = configmod.load(root).client
    assert c.token and c.link_days == 7 and c.expires == 1_000_000 + 7 * DAY
    first = c.token
    clientpack.make_link(path, 1, now=2_000_000)
    c = configmod.load(root).client
    assert c.token != first and c.expires == 2_000_000 + DAY  # (the old one stops at once)
    clientpack.renew_link(path, 0)
    assert configmod.load(root).client.expires == 0 and configmod.load(root).client.token == c.token
    clientpack.stop_link(path, now=3_000_000)
    assert configmod.load(root).client.expires == 3_000_000
    for bad in (2, -1, "x", None):
        with pytest.raises(ConfigError):
            clientpack.make_link(path, bad)
    configmod.set_value(path, "client", "link_days", "365")
    with pytest.raises(ConfigError):
        configmod.load(root)


def test_the_share_server_tells_an_expired_invite_from_a_wrong_one():
    class D:
        def __init__(self, client):
            self.m = type("M", (), {"config": type("C", (), {"client": client})()})()
    good = ClientConfig(enabled=True, token="G" * 24, expires=int(time.time()) + 60)
    old = ClientConfig(enabled=True, token="O" * 24, expires=int(time.time()) - 1)
    hub = type("Hub", (), {"daemons": {"a": D(good), "b": D(old)}})()
    s = share.ShareServer(hub)
    assert s.server_for("G" * 24)[0] == "a" and s.server_for("G" * 24)[1] is not None
    assert s.server_for("O" * 24) == ("b", None)       # expired: 410, "ask for a new link"
    assert s.server_for("Z" * 24) == (None, None)      # not ours: 404


@pytest.fixture
def sharing(hub_env):
    """The installed server with its friends' download on, sharing on a free port."""
    hub, c = hub_env
    login(c)
    port = free_port()
    hub._save_hub_file({**hub._hub_file(), "share": {"port": port, "address": ""}})
    status, info, _ = c.post("/api/servers/alpha/client", {"enabled": True})
    assert status == 200, info
    return hub, c, port


def _pinned(hub, port, token):
    inv = join.Invite("127.0.0.1", port, token, hub.share.fingerprint)
    http = HttpClient(cache_ttl=0, retries=1)
    http.pin(inv.netloc, inv.fp)
    return inv, http


def test_an_expired_or_stopped_link_is_refused(sharing, tmp_path):
    hub, c, port = sharing
    d = hub.daemons["alpha"]
    info = c.get("/api/servers/alpha/client")[1]
    assert info["link_days"] == 7 and not info["expired"] and info["links"]["local"]
    assert abs(info["expires"] - (time.time() + 7 * DAY)) < 120
    token = d.m.config.client.token
    inv, http = _pinned(hub, port, token)
    assert http.get_json(f"{inv.url}/pack.json")["name"]

    # A week later: the link stops by itself, for everything it gave access to.
    clientpack.renew_link(d.m.config.path, 1, now=time.time() - 2 * DAY)
    d.m.reload_config()
    with pytest.raises(HttpError) as e:
        http.get_json(f"{inv.url}/pack.json")
    assert e.value.status == 410
    with pytest.raises(join.JoinError, match="expired"):
        join.Joiner(inv, mc_dir=tmp_path / "mc", http=http).fetch_pack()
    with pytest.raises(join.JoinError, match="expired"):
        join.Joiner(inv, mc_dir=tmp_path / "mc", http=http).ask_to_join("Friendly_1")
    with pytest.raises(urllib.error.HTTPError) as e:
        with http._pins[inv.netloc].open(urllib.request.Request(f"{inv.url}/pack.json")):
            pass
    assert e.value.code == 410 and share.EXPIRED.encode() in e.value.read()
    info = c.get("/api/servers/alpha/client")[1]
    assert info["expired"] and info["links"] == {} and info["link"] is None  # nothing dead to copy
    hub.update_share()
    assert hub.share is None  # nothing left to share: the internet-facing port is closed

    # New links (for 30 days): sharing again, and the expired one stays dead.
    status, info, _ = c.post("/api/servers/alpha/client/new-link", {"days": 30})
    assert status == 200 and not info["expired"] and abs(info["expires"] - (time.time() + 30 * DAY)) < 120
    assert hub.share is not None and d.m.config.client.token != token
    new, http2 = _pinned(hub, port, d.m.config.client.token)
    assert http2.get_json(f"{new.url}/pack.json")["name"]
    with pytest.raises(HttpError) as e:
        http.get_json(f"{inv.url}/pack.json")
    assert e.value.status == 404

    # Stopped by hand: refused straight away, and choosing another lifetime doesn't bring it back.
    status, info, _ = c.post("/api/servers/alpha/client/stop-link", {})
    assert status == 200 and info["expired"]
    with pytest.raises(HttpError) as e:
        http2.get_json(f"{new.url}/pack.json")
    assert e.value.status in (410, None)  # (410, or the port already closed)
    for days in (30, 0):
        info = c.post("/api/servers/alpha/client", {"link_days": days})[1]
        assert info["expired"] and info["links"] == {} and info["link_days"] == days
    assert not d.m.config.client.link_works(time.time())

    # Switching the download off and on again after that makes a fresh, working link.
    c.post("/api/servers/alpha/client", {"enabled": False})
    info = c.post("/api/servers/alpha/client", {"enabled": True})[1]
    assert not info["expired"] and info["links"]
    # The lifetime can be changed for the current link (from now), only to the choices offered.
    info = c.post("/api/servers/alpha/client", {"link_days": 0})[1]
    assert info["expires"] is None and not info["expired"]
    assert c.post("/api/servers/alpha/client", {"link_days": 365})[0] == 400
    assert c.post("/api/servers/alpha/client/new-link", {"days": "soon"})[0] == 400


def test_phones_cant_make_or_stop_invite_links():
    for path in ("/api/client/new-link", "/api/client/stop-link", "/api/client", "/api/hub/devices/cancel-pairing",
                 "/api/hub/devices/pair"):
        assert not web.device_allowed("POST", path), path


def test_the_discord_post_says_when_the_invite_stops():
    from craft_conductor.discord import invite_message
    _, embed = invite_message("", "Alpha", "1.21.1", {"internet": "https://x.test/#c"}, expires=1_700_000_000)
    assert "<t:1700000000:f>" in embed["description"]
    _, embed = invite_message("", "Alpha", "1.21.1", {"internet": "https://x.test/#c"})
    assert "<t:" not in embed["description"]


# ------------------------------------------------------------------- phone pairing
def test_a_pairing_code_works_once_even_when_tried_at_the_same_time(tmp_path):
    devices = webauth.Devices(tmp_path)
    now = time.time()
    code = devices.new_code(now)
    results, start = [], threading.Barrier(8)

    def attempt():
        start.wait()
        try:
            results.append(devices.pair(code, "Phone", "10.0.0.2", now))
        except ConfigError:
            results.append(None)
    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(r is not None for r in results) == 1 and len(devices.list()) == 1
    with pytest.raises(ConfigError):
        devices.pair(code, "Phone", "10.0.0.2", now)


def test_a_pairing_code_expires_and_can_be_cancelled(tmp_path):
    devices = webauth.Devices(tmp_path)
    now = time.time()
    late = devices.new_code(now)
    with pytest.raises(ConfigError, match="expired"):
        devices.pair(late, "Phone", "10.0.0.2", now + webauth.PAIR_SECONDS + 1)
    cancelled = devices.new_code(now)
    assert devices.cancel_codes() == 1
    with pytest.raises(ConfigError):
        devices.pair(cancelled, "Phone", "10.0.0.2", now)
    # Removing every phone also cancels codes not used yet; a paired phone can be removed alone.
    pending = devices.new_code(now)
    token, phone = devices.pair(devices.new_code(now), "Phone", "10.0.0.2", now)
    assert devices.find(token, now)
    assert devices.remove(phone["id"]) == 1 and devices.find(token, now) is None
    devices.remove(None)
    with pytest.raises(ConfigError):
        devices.pair(pending, "Phone", "10.0.0.2", now)


def test_only_a_few_pairing_codes_wait_at_once(tmp_path):
    devices = webauth.Devices(tmp_path)
    now = time.time()
    codes = [devices.new_code(now + i) for i in range(webauth.MAX_CODES + 2)]
    for old in codes[:2]:
        with pytest.raises(ConfigError):
            devices.pair(old, "Phone", "10.0.0.2", now + 10)
    assert devices.pair(codes[-1], "Phone", "10.0.0.2", now + 10)


def test_cancelling_pairing_from_the_page(hub_env):
    hub, c = hub_env
    login(c)
    hub.ui.devices.new_code(time.time())
    status, body, _ = c.post("/api/hub/devices/cancel-pairing", {})
    assert status == 200 and body["cancelled"] == 1
    assert c.post("/api/hub/devices/cancel-pairing", {})[1]["cancelled"] == 0
