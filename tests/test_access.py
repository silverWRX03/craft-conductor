"""Per-person, per-server access to the control panel (access.py, users.py): who may do what is
decided by the server for every request, whatever the page shows.

Everything here goes through the real web server with real sessions, as someone on another
device would: direct API calls, downloads, and requests for servers someone wasn't given.
"""

from __future__ import annotations

import time

import pytest

from craft_conductor import access, push, users as usersmod, webauth, webpush
from craft_conductor.config import ConfigError

from test_hub import login
from test_remote import PERSON_PASSWORD, STRONG, as_other_device, invite, pair_phone, ready_for_links
from test_web import Client

NO_SERVER = "there's no server with that id"


def owner_ready(hub, c):
    """The owner, signed in with a strong password, network access on (so links can be made)."""
    login(c)
    assert c.post("/api/auth/change", {"mode": "password", "secret": STRONG})[0] == 200
    assert c.post("/api/hub/network", {"enabled": True})[0] == 200
    ready_for_links(hub)


def call(client, method, path, body=None):
    return client.get(path) if method == "GET" else client.post(path, body or {})


# ------------------------------------------------------------------ the tables
def test_every_route_is_in_the_tables(hub_env):
    """A new route that isn't listed is the owner's: listing it is how it's opened to anyone else."""
    hub, _ = hub_env
    assert set(hub.ui.api_for("alpha").routes) == set(access.SERVER_ROUTES)
    hub_routes = set(hub.ui.hub_api.routes)
    assert set(access.HUB_ROUTES) <= hub_routes
    assert not set(access.SERVER_ROUTES) & hub_routes


def test_presets_and_risky_permissions():
    p = access.PRESETS
    assert p["viewer"] == {"status.view"}
    assert p["moderator"] == {"status.view", "players.moderate"}
    assert p["operator"] == {"status.view", "server.power", "backups.make", "updates.check"}
    assert p["manager"] == p["moderator"] | p["operator"] | {"logs.view", "settings.safe", "mods.view"}
    assert not p["moderator"] >= p["operator"] and not p["operator"] >= p["moderator"]
    assert access.DEFAULT_PRESET == "viewer"
    # Off by default, each with its risk spelled out when ticked.
    for cap in ("console.execute", "players.op", "mods.manage", "runtime.configure", "updates.apply", "files.write",
                "files.read", "server.export", "backups.restore", "backups.delete", "server.delete", "friends.share"):
        assert cap in access.RISKY and access.CAPS[cap][2], cap
        assert not any(cap in preset for preset in p.values()), cap
    assert access.preset_of(set(p["manager"])) == "manager" and access.preset_of({"status.view", "logs.view"}) is None
    with pytest.raises(ValueError):
        access.valid_caps(["status.view", "owner"])


def test_host_wide_things_are_the_owners_whatever_someone_was_given():
    everything = set(access.CAPS)
    for path in ("/api/hub/users/invite", "/api/hub/users/update", "/api/hub/users/remove", "/api/hub/users/new-link",
                 "/api/self-update/apply", "/api/self-update/check", "/api/self-update/channel", "/api/hub/network",
                 "/api/hub/network/apply", "/api/hub/remote/tls", "/api/hub/upnp", "/api/hub/firewall/remove",
                 "/api/hub/devices/pair", "/api/hub/create", "/api/hub/import", "/api/hub/quit", "/api/hub/share",
                 "/api/hub/discord", "/api/hub/curseforge", "/api/notice/accept", "/api/hub/passkeys/add"):
        assert not access.allows(everything, "POST", path), path
    for path in ("/api/hub/users", "/api/hub/remote", "/api/hub/firewall-rules", "/api/self-update", "/api/hub/discord"):
        assert not access.allows(everything, "GET", path), path
    for path in ("/api/doctor/fix", "/api/open", "/api/play-here", "/api/webmap/port"):
        assert not access.allows(everything, "POST", path), path
    for key in ("discord_webhook", "backup_copy_to", "backup_include", "tunnel_address", "port"):
        assert not access.allows(everything, "POST", "/api/settings", {key: "x"}), key
    assert not access.allows(everything, "POST", "/api/settings", {"properties": {"online-mode": False}})


# ------------------------------------------------------------------ over the network
def test_every_route_refuses_what_someone_wasnt_given(hub_env):
    """Table-driven, through the web server: a viewer of alpha gets nothing else there, nothing at all
    on main (as if it didn't exist), and none of the owner's routes."""
    hub, c = hub_env
    owner_ready(hub, c)
    viewer, _ = invite(hub, c, "Vivian", {"alpha": ["status.view"]})
    for (method, path), need in access.SERVER_ROUTES.items():
        sub = path.removeprefix("/api")
        status, body, _ = call(viewer, method, "/api/servers/main" + sub)
        assert status == 404 and NO_SERVER in body["error"], (method, path)
        if access.Subject("user", grants={"s": access.PRESETS["viewer"]}).can("s", need):
            continue
        status, body, _ = call(viewer, method, "/api/servers/alpha" + sub)
        assert status == 403, (method, path, status, body)
    for (method, path) in hub.ui.hub_api.routes:
        if (method, path) in access.HUB_ROUTES or path in ("/api/account/password",):
            continue
        status, _, _ = call(viewer, method, path)
        assert status == 403, (method, path, status)
    assert hub.ui.httpd is not None and not hub.stop_requested.is_set()   # (/api/hub/quit was refused)


def test_a_server_someone_wasnt_given_looks_like_one_that_doesnt_exist(hub_env):
    hub, c = hub_env
    owner_ready(hub, c)
    manager, _ = invite(hub, c, "Manny", {"alpha": sorted(access.PRESETS["manager"])})
    missing = manager.get("/api/servers/nope/status")
    hidden = manager.get("/api/servers/main/status")
    assert missing[0] == hidden[0] == 404 and missing[1] == hidden[1]
    assert manager.get("/api/servers/alpha/status")[0] == 200
    overview = manager.get("/api/hub")[1]
    assert [s["id"] for s in overview["servers"]] == ["alpha"]
    assert overview["role"] == "user" and overview["access"] == {"alpha": sorted(access.PRESETS["manager"])}
    assert "folder" not in overview["servers"][0] and overview["home"] is None and overview["auth"] is None
    status = manager.get("/api/servers/alpha/status")[1]
    assert "server_dir" not in status and "self_update" not in status
    # The short addresses (one server) resolve the server first, then check it.
    hub.only = lambda: ["main"]
    assert manager.get("/api/status")[0] == 404
    hub.only = lambda: ["alpha"]
    assert manager.get("/api/status")[0] == 200


def test_downloads_need_their_own_permission(hub_env):
    hub, c = hub_env
    owner_ready(hub, c)
    manager, mid = invite(hub, c, "Manny", {"alpha": sorted(access.PRESETS["manager"])})
    for path in ("/api/servers/alpha/export/download?name=x.zip", "/api/servers/alpha/doctor/report",
                 "/api/servers/alpha/configs/file?path=server.properties", "/api/servers/alpha/export"):
        assert manager.get(path)[0] == 403, path
    assert manager.get("/api/servers/alpha/modsets/export?name=x")[0] != 403   # (mods.view: a list of mod names)
    assert c.post("/api/hub/users/update", {"id": mid, "grants": {"alpha": sorted(access.PRESETS["manager"] | {"server.export"})}})[0] == 200
    assert manager.get("/api/servers/alpha/export/download?name=x.zip")[0] in (400, 404)   # (allowed now: there's no such file)
    assert manager.get("/api/servers/alpha/doctor/report")[0] == 403   # (always the owner's)


def test_high_risk_actions_are_refused_until_granted(hub_env):
    from test_web import wait_for
    hub, c = hub_env
    owner_ready(hub, c)
    manager, mid = invite(hub, c, "Manny", {"alpha": sorted(access.PRESETS["manager"])})
    base = "/api/servers/alpha"
    now = c.get(base + "/settings")[1]   # (changes, not what's there already)
    risky = [("/command", {"command": "say hi"}), ("/players/action", {"action": "op", "name": "Steve"}),
             ("/mods/add", {"id": "goodmod"}), ("/java/use", {"major": 21}), ("/updates/apply", {}),
             ("/configs/file", {"path": "server.properties", "text": ""}), ("/backups/restore", {"name": "x"}),
             ("/export", {}), ("/setup", {}), ("/world/replace", {}), ("/client/new-link", {}),
             ("/settings", {"memory": "13G" if now["memory"] != "13G" else "12G"}),
             ("/settings", {"auto_upgrade": not now["auto_upgrade"]}), ("/settings", {"backups_keep": now["backups_keep"] + 1})]
    for path, body in risky:
        assert manager.post(base + path, body)[0] == 403, path
    assert manager.post("/api/hub/delete", {"id": "alpha"})[0] == 403
    assert manager.post("/api/hub/delete", {"id": "main"})[0] == 404
    # Granted on purpose, the console works (the server says why it can't, not the permissions).
    caps = sorted(access.PRESETS["manager"] | {"console.execute", "players.op"})
    assert c.post("/api/hub/users/update", {"id": mid, "grants": {"alpha": caps}})[0] == 200
    assert c.post(base + "/server/start")[0] == 200
    wait_for(lambda: hub.get("alpha").state == "running", timeout=30)
    assert manager.post(base + "/command", {"command": "say hi from manny"})[0] == 200
    assert manager.post(base + "/players/action", {"action": "op", "name": "Steve"})[0] == 200
    assert manager.post(base + "/mods/add", {"id": "goodmod"})[0] == 403   # (still not mods)


def test_settings_check_each_change(hub_env):
    """The Settings page sends the whole form: what's sent unchanged needs nothing, each change
    needs its own permission, and the owner's settings aren't shown to anyone else."""
    hub, c = hub_env
    owner_ready(hub, c)
    assert c.post("/api/servers/alpha/settings", {"discord_webhook": "https://discord.com/api/webhooks/1/sample"})[0] == 200
    manager, _ = invite(hub, c, "Manny", {"alpha": sorted(access.PRESETS["manager"])})
    shown = manager.get("/api/servers/alpha/settings")[1]
    for key in access.SETTINGS_OWNER_ONLY:
        assert key not in shown, key
    form = {k: v for k, v in shown.items() if k in hub.ui.api_for("alpha").SETTINGS}
    form["properties"] = shown["properties"]
    assert manager.post("/api/servers/alpha/settings", form)[0] == 200   # (nothing changed)
    assert manager.post("/api/servers/alpha/settings", {**form, "check_interval": "12h"})[0] == 200
    assert hub.get("alpha").m.config.updates.check_interval == 12 * 3600
    props = dict(shown["properties"])
    assert manager.post("/api/servers/alpha/settings", {"properties": {**props, "pvp": not props.get("pvp")}})[0] == 200
    for change in ({"properties": {**props, "online-mode": False}}, {"properties": {**props, "op-permission-level": 2}},
                   {"memory": "12G"}, {"port": 25599}, {"discord_webhook": ""}, {"nonsense": 1}):
        assert manager.post("/api/servers/alpha/settings", change)[0] == 403, change
    assert hub.get("alpha").m.config.discord_webhook == "https://discord.com/api/webhooks/1/sample"


def test_the_console_hides_addresses_and_folders_from_others(hub_env):
    hub, c = hub_env
    owner_ready(hub, c)
    manager, _ = invite(hub, c, "Manny", {"alpha": sorted(access.PRESETS["manager"])})
    from pathlib import Path
    hub.get("alpha")._on_line(f"[12:00:00] [Server thread/INFO]: Steve[/203.0.113.7:51234] logged in from {Path.home()}\\x")
    mine = c.get("/api/servers/alpha/console?since=0")[1]["lines"]
    theirs = manager.get("/api/servers/alpha/console?since=0")[1]["lines"]
    assert any("203.0.113.7" in x["text"] for x in mine)
    assert not any("203.0.113.7" in x["text"] or str(Path.home()) in x["text"] for x in theirs)
    assert any("[address hidden]" in x["text"] for x in theirs)
    assert access.redact("v6 [2001:db8::1]:25565 at 12:00:00", home="") == "v6 [address hidden] at 12:00:00"


# ------------------------------------------------------------------ sessions and revocation
def test_removing_someone_or_their_grant_counts_at_once(hub_env):
    hub, c = hub_env
    owner_ready(hub, c)
    person, pid = invite(hub, c, "Sam", {"alpha": ["status.view"], "main": ["status.view"]})
    phone = pair_phone(hub, c, pid)
    assert person.get("/api/servers/main/status")[0] == 200
    assert c.post("/api/hub/users/update", {"id": pid, "grants": {"alpha": ["status.view"]}})[0] == 200
    assert person.get("/api/servers/main/status")[0] == 404 and phone.get("/api/servers/main/status")[0] == 404
    assert c.post("/api/hub/users/update", {"id": pid, "grants": {"nope": ["status.view"]}})[0] == 400
    assert c.post("/api/hub/users/update", {"id": pid, "grants": {"alpha": ["owner"]}})[0] == 400
    assert c.post("/api/hub/users/remove", {"id": pid})[0] == 200
    for client in (person, phone):
        assert client.get("/api/hub")[0] == 401 and client.get("/api/servers/alpha/status")[0] == 401
    assert as_other_device(Client(c.base)).post("/api/login", {"username": "sam", "password": PERSON_PASSWORD})[0] == 401


def test_a_new_sign_in_link_ends_the_old_password(hub_env):
    hub, c = hub_env
    owner_ready(hub, c)
    person, pid = invite(hub, c, "Sam", {"alpha": ["status.view"]})
    phone = pair_phone(hub, c, pid)
    r = c.post("/api/hub/users/new-link", {"id": pid, "host": "mc.example.com"})[1]
    assert person.get("/api/hub")[0] == 401 and phone.get("/api/hub")[0] == 401
    away = as_other_device(Client(c.base))
    assert away.post("/api/login", {"username": "sam", "password": PERSON_PASSWORD})[0] == 401
    token = r["url"].split("#invite=")[1]
    assert away.post("/api/invite", {"token": token})[1]["username"] == "sam"   # (looking doesn't use it up)
    assert away.post("/api/invite/accept", {"token": token, "username": "someone-else", "password": "Another-Pass-22"})[0] == 400
    assert away.post("/api/invite/accept", {"token": token, "username": "sam", "password": "Another-Pass-22"})[0] == 200
    assert away.get("/api/servers/alpha/status")[0] == 200


def test_signing_in_and_changing_ones_own_password(hub_env):
    hub, c = hub_env
    owner_ready(hub, c)
    invite(hub, c, "Sam", {"alpha": ["status.view"]})
    a, b = as_other_device(Client(c.base)), as_other_device(Client(c.base))
    assert a.post("/api/login", {"username": "SAM ", "password": PERSON_PASSWORD})[0] == 200   # (any case)
    assert b.post("/api/login", {"username": "sam", "password": PERSON_PASSWORD})[0] == 200
    assert a.get("/api/account")[1]["username"] == "sam"
    assert a.post("/api/account/password", {"current": "wrong", "new": "Brand-New-Pass-3"})[0] == 400
    assert a.post("/api/account/password", {"current": PERSON_PASSWORD, "new": "short"})[0] == 400
    assert a.post("/api/account/password", {"current": PERSON_PASSWORD, "new": "Brand-New-Pass-3"})[0] == 200
    assert a.get("/api/hub")[0] == 200 and b.get("/api/hub")[0] == 401   # (their other sessions end)
    assert c.post("/api/account/password", {"current": STRONG, "new": "Brand-New-Pass-3"})[0] == 400  # (the owner's is elsewhere)
    assert a.post("/api/auth/change", {"mode": "password", "secret": "Brand-New-Pass-4"})[0] == 403  # (not the owner's)


def test_nobody_can_give_themselves_more(hub_env):
    hub, c = hub_env
    owner_ready(hub, c)
    person, pid = invite(hub, c, "Sam", {"alpha": ["status.view"]})
    everything = {"alpha": sorted(access.CAPS), "main": sorted(access.CAPS)}
    for path, body in (("/api/hub/users/update", {"id": pid, "grants": everything}),
                       ("/api/hub/users/invite", {"name": "Me again", "grants": everything, "host": "mc.example.com"}),
                       ("/api/hub/users/new-link", {"id": pid, "host": "mc.example.com"}),
                       ("/api/hub/devices/pair", {"host": "mc.example.com", "user": pid}),
                       ("/api/notice/accept", {}), ("/api/hub/passkeys/options", {})):
        assert person.post(path, body)[0] == 403, path
    assert person.get("/api/hub/users")[0] == 403
    # (what the page sends can't say who's asking)
    assert person.post("/api/hub/phone/prefs", {"endpoint": "x", "__subject": "owner"})[0] == 404
    assert hub.ui.users.subject(pid).grants == {"alpha": frozenset({"status.view"})}


def test_too_many_wrong_passwords_wait(hub_env):
    hub, c = hub_env
    owner_ready(hub, c)
    invite(hub, c, "Sam", {"alpha": ["status.view"]})
    away = as_other_device(Client(c.base))
    for _ in range(5):
        assert away.post("/api/login", {"username": "sam", "password": "Wrong-Password-1"})[0] == 401
    assert away.post("/api/login", {"username": "sam", "password": PERSON_PASSWORD})[0] == 429
    assert away.post("/api/login", {"username": "nobody", "password": "x"})[0] == 429   # (the same address)


def test_the_owner_can_always_recover(hub_env):
    """Forgot the password: the owner's own computer goes back to the default. Everyone is signed
    out and links not used yet stop working; invited people keep their accounts."""
    hub, c = hub_env
    owner_ready(hub, c)
    person, pid = invite(hub, c, "Sam", {"alpha": ["status.view"]})
    phone = pair_phone(hub, c, pid)
    pending = c.post("/api/hub/users/invite", {"name": "Later", "grants": {"alpha": ["status.view"]},
                                               "host": "mc.example.com"})[1]["url"].split("#invite=")[1]
    assert person.post("/api/auth/reset-local")[0] == 403   # (never over the network)
    assert Client(c.base).post("/api/auth/reset-local")[0] == 200
    assert person.get("/api/hub")[0] == 401 and phone.get("/api/hub")[0] == 401 and c.get("/api/hub")[0] == 401
    away = as_other_device(Client(c.base))
    assert away.post("/api/invite", {"token": pending})[0] == 404
    assert away.post("/api/login", {"username": "sam", "password": PERSON_PASSWORD})[0] == 200
    login(c)


# ------------------------------------------------------------------ invites
def test_an_invite_works_once_and_expires(tmp_path):
    people = usersmod.Users(tmp_path)
    now = 1_000_000.0
    token, u = people.invite("Sam <b>", {"alpha": access.PRESETS["viewer"]}, now)
    assert u["name"] == "Sam b" and people.subject(u["id"]) is None   # (not until they choose a password)
    assert people.invite_info(token, now)["servers"] == ["alpha"]
    for bad in ("ab", "Has Space", "-dash", "x" * 33):
        with pytest.raises(ConfigError):
            people.accept(token, bad, PERSON_PASSWORD, now)
    for weak in ("short", "alllowercase-123", "sam"):
        with pytest.raises(ConfigError):
            people.accept(token, "sam", weak, now)
    people.accept(token, "sam", PERSON_PASSWORD, now)
    with pytest.raises(ConfigError, match="expired or was already used"):
        people.accept(token, "sam", PERSON_PASSWORD, now)
    late, _ = people.invite("Late", {"alpha": access.PRESETS["viewer"]}, now)
    with pytest.raises(ConfigError, match="expired"):
        people.invite_info(late, now + usersmod.INVITE_SECONDS + 1)
    taken, _ = people.invite("Other Sam", {"alpha": access.PRESETS["viewer"]}, now)
    with pytest.raises(ConfigError, match="taken"):
        people.accept(taken, "sam", PERSON_PASSWORD, now)
    data = (tmp_path / usersmod.FILE).read_text()
    assert token not in data and PERSON_PASSWORD not in data   # (only hashes are kept)


def test_an_invite_used_at_the_same_time_works_once(tmp_path):
    import threading
    people = usersmod.Users(tmp_path)
    token, _ = people.invite("Sam", {"alpha": access.PRESETS["viewer"]}, time.time())
    results, start = [], threading.Barrier(6)

    def attempt(i):
        start.wait()
        try:
            results.append(people.accept(token, f"sam{i}", PERSON_PASSWORD, time.time()))
        except ConfigError:
            results.append(None)
    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(r is not None for r in results) == 1


def test_a_friends_invite_never_opens_the_control_panel(hub_env):
    """The Minecraft friends' invite link (the mods download) is a different thing altogether."""
    hub, c = hub_env
    owner_ready(hub, c)
    c.post("/api/servers/alpha/client", {"enabled": True})
    friends_token = hub.get("alpha").m.config.client.token
    assert friends_token
    away = as_other_device(Client(c.base))
    assert away.post("/api/invite", {"token": friends_token})[0] == 404
    assert away.post("/api/invite/accept", {"token": friends_token, "username": "friend", "password": PERSON_PASSWORD})[0] == 400
    for cookie in (f"craft_conductor_session={friends_token}", f"craft_conductor_device={friends_token}"):
        assert away.call("GET", "/api/hub", headers={"Cookie": cookie})[0] == 401
    assert hub.ui.users.list(time.time()) == []


def test_inviting_needs_a_server_and_an_address_that_works(hub_env):
    hub, c = hub_env
    owner_ready(hub, c)
    assert c.post("/api/hub/users/invite", {"name": "Sam", "grants": {}, "host": "mc.example.com"})[0] == 400
    assert c.post("/api/hub/users/invite", {"name": "Sam", "grants": {"alpha": ["status.view"]}, "host": "evil.example"})[0] == 400
    assert c.post("/api/hub/users/invite", {"name": "", "grants": {"alpha": ["status.view"]}, "host": "mc.example.com"})[0] == 400
    assert hub.ui.users.list(time.time()) == []   # (nobody made by the failed tries)
    people = c.get("/api/hub/users")[1]
    assert people["catalog"]["default"] == "viewer" and {s["id"] for s in people["servers"]} == {"alpha", "main"}


def test_deleting_a_server_takes_away_its_grants(hub_env):
    hub, c = hub_env
    owner_ready(hub, c)
    person, pid = invite(hub, c, "Sam", {"alpha": ["status.view"], "main": ["status.view", "server.delete"]})
    assert person.post("/api/hub/delete", {"id": "alpha"})[0] == 403
    assert person.post("/api/hub/delete", {"id": "main"})[0] == 200
    assert hub.get("main") is None and set(hub.ui.users.subject(pid).grants) == {"alpha"}


# ------------------------------------------------------------------ phones, notifications, passkeys
def test_notifications_reach_only_those_who_may_hear(tmp_path, monkeypatch):
    p = push.Push(tmp_path)
    key, auth = webpush.b64u(webpush.public_bytes(webpush.public_of(webpush.new_private()))), webpush.b64u(b"0" * 16)
    for who, n in (("owner", 1), ("user:sam", 2), ("user:ann", 3)):
        p.subscribe(f"https://fcm.googleapis.com/fcm/send/{n}", key, auth, who.removeprefix("user:"), who=who)
    data = p._load()
    data["subscriptions"].append({**data["subscriptions"][0], "id": "old", "endpoint": "https://fcm.googleapis.com/fcm/send/9"})
    del data["subscriptions"][-1]["who"]   # (turned on before notifications belonged to someone)
    p._save(data)
    sent = []
    monkeypatch.setattr(p, "_post", lambda key, sub, payload, tag: sent.append(sub["name"]) or 201)
    p.audience = lambda who, sid: (who, sid) == ("user:sam", "alpha")
    p.send_now({"title": "Alpha", "body": "The server crashed", "kind": "crash", "sid": "alpha"})
    assert sorted(sent) == ["owner", "sam"]
    sent.clear()
    p.send_now({"title": "Craft Conductor", "body": "1.2 is out", "kind": "crash", "sid": None})
    assert sent == ["owner"]
    assert p.unsubscribe(endpoint="https://fcm.googleapis.com/fcm/send/1", who="user:sam") == 0   # (not theirs)
    assert p.unsubscribe(who="user:sam") == 1 and [s["who"] for s in p.subscriptions(who="user:sam")] == []


def test_a_persons_notifications_are_their_own(hub_env):
    hub, c = hub_env
    owner_ready(hub, c)
    person, pid = invite(hub, c, "Sam", {"alpha": ["status.view"]})
    key = webpush.b64u(webpush.public_bytes(webpush.public_of(webpush.new_private())))
    sub = {"keys": {"p256dh": key, "auth": webpush.b64u(b"1" * 16)}, "name": "Phone"}
    mine, theirs = "https://fcm.googleapis.com/fcm/send/owner", "https://fcm.googleapis.com/fcm/send/sam"
    assert c.post("/api/hub/phone/subscribe", {**sub, "endpoint": mine})[0] == 200
    assert person.post("/api/hub/phone/subscribe", {**sub, "endpoint": theirs})[0] == 200
    seen = person.get("/api/hub/phone")[1]
    assert [d["who"] for d in seen["devices"]] == [f"user:{pid}"] and seen["tailscale"] is None
    assert person.post("/api/hub/phone/prefs", {"endpoint": mine})[0] == 404
    assert person.post("/api/hub/phone/unsubscribe", {"endpoint": mine})[1]["removed"] == 0
    assert len(c.get("/api/hub/phone")[1]["devices"]) == 2
    assert hub.push.audience(f"user:{pid}", "alpha") and not hub.push.audience(f"user:{pid}", "main")
    assert c.post("/api/hub/users/remove", {"id": pid})[0] == 200
    assert [d["who"] for d in hub.push.subscriptions()] == ["owner"]


def test_passkeys_belong_to_someone(tmp_path):
    from craft_conductor import passkeys
    store = passkeys.Passkeys(tmp_path)
    store._write([{"id": "a", "name": "Owner's", "rp_id": "x"}, {"id": "b", "name": "Sam's", "rp_id": "x", "owner": "user:sam"}])
    assert [k["id"] for k in store.list()] == ["a"] and [k["id"] for k in store.list(owner="user:sam")] == ["b"]
    assert store.remove("a", owner="user:sam") == 0 and store.remove(None, owner="owner") == 1
    assert [k["id"] for k in store.list(owner=None)] == ["b"]
    store._write([{"id": "a", "name": "Owner's", "rp_id": "x"}, {"id": "b", "name": "Sam's", "rp_id": "x", "owner": "user:sam"}])
    options = store.creation_options("x", owner="user:sam", display="Sam")
    assert options["user"]["name"] == "Sam" and options["user"]["id"] != store.creation_options("x")["user"]["id"]
    assert [c["id"] for c in options["excludeCredentials"]] == ["b"]   # (never someone else's passkeys)


def test_old_helper_and_viewer_phones_no_longer_sign_in(tmp_path):
    devices = webauth.Devices(tmp_path)
    devices._write([{"id": "old", "name": "Phone", "hash": webauth._digest("old-key"), "expires": time.time() + 3600,
                     "role": "helper"}])
    assert devices.find("old-key", time.time()) is None and devices.list() == []
    assert devices.drop_unowned() == 1


def test_a_mod_check_is_followed_only_by_whoever_started_it(hub_env):
    """A server's mod check runs in the background and is followed through a route outside the
    server: someone else (even with the same permissions) can't read it; the owner can."""
    hub, c = hub_env
    owner_ready(hub, c)
    caps = sorted(access.PRESETS["manager"])
    ann, _ = invite(hub, c, "Ann", {"alpha": caps})
    bob, _ = invite(hub, c, "Bob", {"alpha": caps})
    status, r, _ = ann.post("/api/servers/alpha/mods/check", {"background": True, "__who": "owner"})
    assert status == 200 and r.get("id"), r
    assert hub.checks[r["id"]].who.startswith("user:")   # (from the session, whatever the page said)
    path = f"/api/hub/mods/check?id={r['id']}"
    assert ann.get(path)[0] == 200 and c.get(path)[0] == 200
    assert bob.get(path)[0] == 404
