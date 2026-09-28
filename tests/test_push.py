"""Phone notifications: subscriptions, what's sent, and what the phone gets."""

import hashlib
import hmac
import json
import os
import struct
import urllib.error

import pytest

from mcsm import push, webpush, web

FCM = "https://fcm.googleapis.com/fcm/send/abc123"


def phone():
    """A browser's subscription keys (and its private key, to read what it's sent)."""
    private = webpush.new_private()
    return private, webpush.b64u(webpush.public_bytes(webpush.public_of(private))), webpush.b64u(b"0123456789abcdef")


def read(private, auth_b64, body):
    """Decrypt a push message the way the phone does (AES-GCM decryption is the same keystream)."""
    ua_public = webpush.public_bytes(webpush.public_of(private))
    salt, idlen = body[:16], body[20]
    as_public, ciphertext = body[21:21 + idlen], body[21 + idlen:]
    shared = webpush.ecdh(private, webpush.point_from(as_public))
    mac = lambda k, d: hmac.new(k, d, hashlib.sha256).digest()  # noqa: E731
    prk = mac(salt, mac(mac(webpush.unb64u(auth_b64), shared), b"WebPush: info\0" + ua_public + as_public + b"\x01"))
    cek, nonce = mac(prk, b"Content-Encoding: aes128gcm\0\x01")[:16], mac(prk, b"Content-Encoding: nonce\0\x01")[:12]
    data = ciphertext[:-16]
    plain = webpush.aes_gcm_encrypt(cek, nonce, data)[:len(data)]  # (CTR: encrypting again decrypts)
    assert webpush.aes_gcm_encrypt(cek, nonce, plain)[-16:] == ciphertext[-16:]  # the tag checks out
    return json.loads(plain.rstrip(b"\x02"))


def test_only_push_services_are_accepted(tmp_path):
    p = push.Push(tmp_path)
    _, key, auth = phone()
    for bad in ("http://fcm.googleapis.com/x", "https://evil.example/x", "https://fcm.googleapis.com:8443/x",
                "https://169.254.169.254/latest", "file:///etc/passwd", "https://fcm.googleapis.com.evil.com/x"):
        with pytest.raises(push.PushError):
            p.subscribe(bad, key, auth, "x")
    with pytest.raises(push.PushError):
        p.subscribe(FCM, webpush.b64u(b"\x04" + bytes(64)), auth, "x")  # not a real key
    for good in (FCM, "https://web.push.apple.com/QGuQyavXutnMH", "https://updates.push.services.mozilla.com/wpush/v2/x",
                 "https://wns2-par02p.notify.windows.com/w/?token=x"):
        assert p.subscribe(good, key, auth, "Kyle's <iPhone>")["name"] == "Kyle's iPhone"
    assert len(p.subscriptions()) == 4
    if os.name != "nt":  # (Windows has no Unix permissions)
        assert oct((tmp_path / "push.json").stat().st_mode)[-3:] == "600"  # (the private key)


def test_sending_and_forgetting_gone_devices(tmp_path, monkeypatch):
    p = push.Push(tmp_path)
    private, key, auth = phone()
    p.subscribe(FCM, key, auth, "Phone")
    p.subscribe("https://web.push.apple.com/gone", key, auth, "Old iPad")
    sent = []

    class Resp:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout):
        sent.append(req)
        if "gone" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 410, "Gone", {}, None)
        return Resp()
    monkeypatch.setattr(push._OPENER, "open", urlopen)
    results = p.send_now({"title": "Weekend Survival", "body": "The server crashed", "url": "/#s/alpha/dashboard", "tag": "alpha"})
    assert [r["ok"] for r in results] == [True, False]
    assert [s["name"] for s in p.subscriptions()] == ["Phone"]  # the gone one is forgotten
    req = sent[0]
    headers = {k.lower(): v for k, v in req.header_items()}
    assert headers["content-encoding"] == "aes128gcm" and headers["ttl"] == str(push.TTL) and headers["topic"] == "alpha"
    token = headers["authorization"].split("t=")[1].split(",")[0]
    claims = json.loads(webpush.unb64u(token.split(".")[1]))
    assert claims["aud"] == "https://fcm.googleapis.com" and claims["sub"] == push.SUBJECT
    assert headers["authorization"].endswith("k=" + p.public_key())
    assert read(private, auth, req.data) == {"title": "Weekend Survival", "body": "The server crashed",
                                             "url": "/#s/alpha/dashboard", "tag": "alpha"}
    assert struct.unpack(">I", req.data[16:20])[0] == 4096


def test_phones_manage_their_own_notifications():
    for path in ("/api/hub/phone/subscribe", "/api/hub/phone/unsubscribe", "/api/hub/phone/test", "/api/hub/phone/prefs"):
        assert web.device_allowed("POST", path, "viewer") and web.device_allowed("POST", path, "helper")
    for path in ("/api/hub/phone/remove", "/api/hub/phone/tailscale"):
        assert not web.device_allowed("POST", path, "helper")


def test_a_servers_messages_reach_phones(hub_env, monkeypatch):
    from test_hub import login
    hub, c = hub_env
    login(c)
    info = c.get("/api/hub/phone")[1]
    assert info["devices"] == [] and len(webpush.unb64u(info["public_key"])) == 65 and info["tailscale"] is None
    _, key, auth = phone()
    assert c.post("/api/hub/phone/subscribe", {"endpoint": "https://evil.example/x", "keys": {"p256dh": key, "auth": auth}})[0] == 400
    status, r, _ = c.post("/api/hub/phone/subscribe", {"endpoint": FCM, "keys": {"p256dh": key, "auth": auth}, "name": "Phone"})
    assert status == 200, r
    queued = []
    monkeypatch.setattr(hub.push, "notify", lambda title, body, url="/", tag="": queued.append((title, body, url, tag)))
    hub.get("alpha").m.notifier.send("Server is up (Minecraft 1.21.1)")
    assert queued == [("Alpha", "Server is up (Minecraft 1.21.1)", "/#s/alpha/dashboard", "alpha")]
    assert c.post("/api/hub/phone/test", {"endpoint": "https://fcm.googleapis.com/fcm/send/other"})[0] == 404
    prefs = c.post("/api/hub/phone/prefs", {"endpoint": FCM})[1]
    assert "status" not in prefs["kinds"] and "crash" in prefs["kinds"] and "computer" in prefs["all"]
    assert c.post("/api/hub/phone/prefs", {"endpoint": FCM, "kinds": ["crash", "nonsense"]})[1]["kinds"] == ["crash"]
    assert c.post("/api/hub/phone/prefs", {"endpoint": FCM, "kinds": "crash"})[0] == 400
    assert c.post("/api/hub/phone/prefs", {"endpoint": "https://fcm.googleapis.com/fcm/send/other"})[0] == 404
    assert c.post("/api/hub/phone/subscribe", {"endpoint": FCM, "keys": {"p256dh": key, "auth": auth}, "name": "Phone"})[0] == 200
    assert c.post("/api/hub/phone/prefs", {"endpoint": FCM})[1]["kinds"] == ["crash"]  # (kept when it signs up again)
    assert c.post("/api/hub/phone/unsubscribe", {"endpoint": FCM})[1]["removed"] == 1
    assert c.post("/api/hub/phone/tailscale", {"on": True})[0] == 400  # (no strong password yet)


def test_messages_are_sorted_into_kinds():
    assert push.kind_of("The server crashed") == "crash"
    assert push.kind_of("Steve asks to join") == "join"
    assert push.kind_of("Minecraft 1.21.2 is out") == "updates"
    assert push.kind_of("Server is up (Minecraft 1.21.1)") == "status"
    assert push.kind_of("Hello") == "other"


def test_a_device_only_gets_the_kinds_it_chose(tmp_path, monkeypatch):
    p = push.Push(tmp_path)
    _, key, auth = phone()
    p.subscribe(FCM, key, auth, "Phone")
    posted = []
    monkeypatch.setattr(p, "_post", lambda k, sub, payload, tag: posted.append(json.loads(payload)) or 201)
    p.send_now({"title": "A", "body": "Server is up", "url": "/", "tag": "", "kind": "status"})
    assert posted == []  # (off by default)
    p.set_kinds(FCM, ["status"])
    p.send_now({"title": "A", "body": "Server is up", "url": "/", "tag": "", "kind": "status"})
    assert posted == [{"title": "A", "body": "Server is up", "url": "/", "tag": ""}]
    p.send_now({"title": "A", "body": "crashed", "url": "/", "tag": "", "kind": "crash"})
    assert len(posted) == 1
