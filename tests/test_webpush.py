"""Web Push without libraries: checked against the cryptography package (a test-only dependency)."""

import json
import os
import struct

import pytest

from mcsm import webpush

try:  # (the system copy can be broken: then these are skipped)
    from cryptography.hazmat.primitives import hashes as _h  # noqa: F401
except BaseException:  # noqa: BLE001
    pytest.skip("cryptography isn't usable here", allow_module_level=True)
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature  # noqa: E402
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402


def test_aes_gcm_matches():
    assert webpush.SBOX[0x00] == 0x63 and webpush.SBOX[0x01] == 0x7C and webpush.SBOX[0x53] == 0xED
    for n in (0, 1, 15, 16, 17, 100):
        key, nonce, data, aad = os.urandom(16), os.urandom(12), os.urandom(n), os.urandom(n % 7)
        assert webpush.aes_gcm_encrypt(key, nonce, data, aad) == AESGCM(key).encrypt(nonce, data, aad)


def test_keys_ecdh_and_signatures_match():
    mine = webpush.new_private()
    theirs = ec.generate_private_key(ec.SECP256R1())
    their_public = theirs.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    my_public = webpush.public_bytes(webpush.public_of(mine))
    mine_key = ec.derive_private_key(mine, ec.SECP256R1())
    assert mine_key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint) == my_public
    assert webpush.ecdh(mine, webpush.point_from(their_public)) == \
        theirs.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), my_public))
    sig = webpush.sign(mine, b"hello")
    der = encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big"))
    mine_key.public_key().verify(der, b"hello", ec.ECDSA(hashes.SHA256()))  # (raises if wrong)
    assert webpush.verify(webpush.public_of(mine), b"hello", sig)
    assert not webpush.verify(webpush.public_of(mine), b"hellO", sig)
    with pytest.raises(ValueError):
        webpush.point_from(b"\x04" + bytes(64))  # not on the curve


def test_a_message_the_browser_can_read():
    """Decrypt what we send the way a browser does (RFC 8291)."""
    import hmac
    import hashlib
    ua = ec.generate_private_key(ec.SECP256R1())
    ua_public = ua.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = os.urandom(16)
    message = json.dumps({"title": "Weekend Survival", "body": "The server crashed"}).encode()
    body = webpush.encrypt(message, ua_public, auth)
    salt, rs, idlen = body[:16], struct.unpack(">I", body[16:20])[0], body[20]
    as_public, ciphertext = body[21:21 + idlen], body[21 + idlen:]
    assert rs == 4096 and idlen == 65
    shared = ua.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public))
    mac = lambda k, d: hmac.new(k, d, hashlib.sha256).digest()  # noqa: E731
    ikm = mac(mac(auth, shared), b"WebPush: info\0" + ua_public + as_public + b"\x01")
    prk = mac(salt, ikm)
    cek, nonce = mac(prk, b"Content-Encoding: aes128gcm\0\x01")[:16], mac(prk, b"Content-Encoding: nonce\0\x01")[:12]
    plain = AESGCM(cek).decrypt(nonce, ciphertext, None)
    assert plain == message + b"\x02"


def test_the_vapid_token():
    key = webpush.new_private()
    header = webpush.vapid_header(key, "https://fcm.googleapis.com/fcm/send/abc", "https://example.org", now=1000)
    t, k = header.removeprefix("vapid t=").split(", k=")
    head, body, sig = t.split(".")
    claims = json.loads(webpush.unb64u(body))
    assert claims == {"aud": "https://fcm.googleapis.com", "exp": 1000 + 12 * 3600, "sub": "https://example.org"}
    assert json.loads(webpush.unb64u(head)) == {"typ": "JWT", "alg": "ES256"}
    assert webpush.verify(webpush.point_from(webpush.unb64u(k)), f"{head}.{body}".encode(), webpush.unb64u(sig))
