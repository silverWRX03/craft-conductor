"""Signing in with a fingerprint or face (passkeys): a software authenticator plays the phone."""

import hashlib
import json

import pytest

from craft_conductor import passkeys, webpush
from craft_conductor.passkeys import Passkeys, PasskeyError

RP = "server.tail1234.ts.net"
ORIGINS = {f"https://{RP}"}


def cbor(value) -> bytes:
    """A tiny CBOR encoder (enough for WebAuthn's structures)."""
    def head(major, n):
        if n < 24:
            return bytes([major << 5 | n])
        for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
            if n < 1 << (8 * size):
                return bytes([major << 5 | info]) + n.to_bytes(size, "big")
    if isinstance(value, bool):
        return b"\xf5" if value else b"\xf4"
    if isinstance(value, int):
        return head(0, value) if value >= 0 else head(1, -1 - value)
    if isinstance(value, bytes):
        return head(2, len(value)) + value
    if isinstance(value, str):
        return head(3, len(value.encode())) + value.encode()
    if isinstance(value, list):
        return head(4, len(value)) + b"".join(cbor(v) for v in value)
    if isinstance(value, dict):
        return head(5, len(value)) + b"".join(cbor(k) + cbor(v) for k, v in value.items())
    raise TypeError(value)


def der(raw: bytes) -> bytes:
    def integer(b):
        b = b.lstrip(b"\x00") or b"\x00"
        if b[0] & 0x80:
            b = b"\x00" + b
        return b"\x02" + bytes([len(b)]) + b
    body = integer(raw[:32]) + integer(raw[32:])
    return b"\x30" + bytes([len(body)]) + body


class Phone:
    """What a phone's browser and its secure chip do with navigator.credentials."""

    def __init__(self, rp=RP, origin=f"https://{RP}"):
        self.private = webpush.new_private()
        self.cred_id = b"cred-" + hashlib.sha256(str(self.private).encode()).digest()[:10]
        self.rp, self.origin, self.count = rp, origin, 0

    def _client(self, kind, challenge):
        return json.dumps({"type": f"webauthn.{kind}", "challenge": challenge, "origin": self.origin}).encode()

    def _auth(self, flags, extra=b""):
        return hashlib.sha256(self.rp.encode()).digest() + bytes([flags]) + self.count.to_bytes(4, "big") + extra

    def create(self, options, flags=0x45):
        x, y = webpush.public_of(self.private)
        cose = cbor({1: 2, 3: -7, -1: 1, -2: x.to_bytes(32, "big"), -3: y.to_bytes(32, "big")})
        attested = b"\x00" * 16 + len(self.cred_id).to_bytes(2, "big") + self.cred_id + cose
        att = cbor({"fmt": "none", "attStmt": {}, "authData": self._auth(flags, attested)})
        return webpush.b64u(self._client("create", options["challenge"])), webpush.b64u(att)

    def get(self, options, flags=0x05, count_step=1):
        self.count += count_step
        client, auth = self._client("get", options["challenge"]), self._auth(flags)
        sig = der(webpush.sign(self.private, auth + hashlib.sha256(client).digest()))
        return {"id": webpush.b64u(self.cred_id), "client_data": webpush.b64u(client),
                "auth_data": webpush.b64u(auth), "signature": webpush.b64u(sig)}


def added(tmp_path):
    store, phone = Passkeys(tmp_path), Phone()
    store.add(RP, ORIGINS, *phone.create(store.creation_options(RP)), name="My phone")
    return store, phone


def test_a_phone_adds_a_passkey_and_signs_in_with_it(tmp_path):
    store, phone = added(tmp_path)
    assert [p["name"] for p in store.list()] == ["My phone"] and store.count(RP) == 1 and store.count("other") == 0
    answer = phone.get(store.request_options(RP))
    assert store.verify(RP, ORIGINS, answer["id"], answer["client_data"], answer["auth_data"], answer["signature"])["name"] == "My phone"
    with pytest.raises(PasskeyError, match="already used"):  # a challenge works once
        store.verify(RP, ORIGINS, answer["id"], answer["client_data"], answer["auth_data"], answer["signature"])
    assert (tmp_path / passkeys.FILE).stat().st_mode & 0o077 == 0 or __import__("os").name == "nt"


def test_forged_or_replayed_answers_are_refused(tmp_path):
    store, phone = added(tmp_path)
    ok = lambda a: store.verify(RP, ORIGINS, a["id"], a["client_data"], a["auth_data"], a["signature"])  # noqa: E731
    other = Phone()  # a different key claiming the same passkey id
    other.cred_id = phone.cred_id
    with pytest.raises(PasskeyError, match="signature"):
        ok(other.get(store.request_options(RP)))
    with pytest.raises(PasskeyError, match="fingerprint, face or PIN"):  # not verified on the device
        ok(phone.get(store.request_options(RP), flags=0x01))
    elsewhere = Phone(origin="https://evil.example")
    elsewhere.private, elsewhere.cred_id = phone.private, phone.cred_id
    with pytest.raises(PasskeyError, match="another address"):
        ok(elsewhere.get(store.request_options(RP)))
    ok(phone.get(store.request_options(RP)))
    with pytest.raises(PasskeyError, match="counter"):  # a copied key: its counter doesn't go up
        ok(phone.get(store.request_options(RP), count_step=0))
    a = phone.get(store.request_options(RP))
    a["signature"] = webpush.b64u(b"\x30\x06\x02\x01\x01\x02\x01\x01")
    with pytest.raises(PasskeyError):
        ok(a)


def test_adding_needs_a_verified_person_and_this_address(tmp_path):
    store = Passkeys(tmp_path)
    with pytest.raises(PasskeyError, match="fingerprint, face or PIN"):
        store.add(RP, ORIGINS, *Phone().create(store.creation_options(RP), flags=0x41), name="x")
    with pytest.raises(PasskeyError, match="another address"):
        store.add(RP, ORIGINS, *Phone(rp="evil.example").create(store.creation_options(RP)), name="x")
    with pytest.raises(PasskeyError):  # garbage
        store.add(RP, ORIGINS, webpush.b64u(b"{}"), webpush.b64u(b"\xff\xff"), name="x")
    assert store.list() == []


def test_the_panel_signs_in_with_a_passkey(hub_env, monkeypatch):
    from test_hub import login
    from craft_conductor import web
    hub, c = hub_env
    monkeypatch.setattr(web, "host_allowed", lambda host, extra: True)
    login(c)
    host = {"Host": RP}
    assert c.post("/api/hub/passkeys/options", {}, headers=host)[0] == 400  # still the default password
    c.post("/api/auth/change", {"mode": "password", "secret": "Correct-Horse-Battery-1"})
    phone = Phone()
    options = c.post("/api/hub/passkeys/options", {}, headers=host)[1]
    client_data, attestation = phone.create(options)
    assert c.post("/api/hub/passkeys/add", {"client_data": client_data, "attestation": attestation, "name": "Phone"},
                  headers=host)[0] == 200
    assert c.call("GET", "/api/auth", headers=host)[1]["passkeys"] is True
    assert c.post("/api/hub/passkeys/options", {}, headers={"Host": "192.168.1.5"})[0] == 400  # no IP addresses
    c.post("/api/logout", {})
    options = c.post("/api/passkey/options", {}, headers=host)[1]
    status, r, headers = c.post("/api/passkey/login", phone.get(options), headers=host)
    assert status == 200 and "craft_conductor_session=" in headers.get("Set-Cookie", "")
    c.post("/api/auth/change", {"mode": "password", "secret": "Another-Horse-Battery-2"})
    assert hub.ui.passkeys.list() == []  # a new password removes them, like paired phones


def test_rsa_passkeys_are_checked_too():
    from craft_conductor import tlscert
    key = tlscert.generate_key(2048)
    size = 256
    cose = {1: 3, 3: -257, -1: key["n"].to_bytes(size, "big"), -2: key["e"].to_bytes(3, "big")}
    stored = passkeys.public_key(cose)
    message = b"authenticator data and client hash"
    assert passkeys.check_signature(stored, message, tlscert._sign(key, message))
    assert not passkeys.check_signature(stored, message + b"!", tlscert._sign(key, message))
    with pytest.raises(PasskeyError, match="isn't supported"):
        passkeys.public_key({1: 1, 3: -8})
