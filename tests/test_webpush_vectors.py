"""Web Push known answers (worked out with the cryptography package), checked without it."""

from mcsm import webpush

A = 0x1234567890ABCDEF1234567890ABCDEF1234567890ABCDEF1234567890ABCDEF % webpush.N
B = 0x0FEDCBA0987654321FEDCBA0987654321FEDCBA0987654321FEDCBA09876543 % webpush.N
PUB_A = bytes.fromhex("04471c3e758c4904285bba7e53118ed0f524adeb0757d25bd2f8e7b0d76dfa714cdd520f7aca8a8b917acc37f51de8f0c9"
                      "bbe3ad858382e702dc25a12d09f7a858")


def test_aes_gcm():
    got = webpush.aes_gcm_encrypt(bytes(range(16)), bytes(range(100, 112)), b"Craft Conductor: the server crashed", b"hdr")
    assert got.hex() == ("59102fc3af22fb95f55a2273f2a559d610fc109ab2dab828820ac3b7df809680d299363ded11ad670841"
                         "9965c5dd25aa4e38f1")


def test_p256_keys_and_ecdh():
    assert webpush.public_bytes(webpush.public_of(A)) == PUB_A
    assert webpush.ecdh(A, webpush.public_of(B)).hex() == "24c0e0846a3aed3e85298e5979afbf022567111554e6bb0f7a1bef661c409e83"
    sig = webpush.sign(A, b"hello")
    assert webpush.verify(webpush.point_from(PUB_A), b"hello", sig) and not webpush.verify(webpush.point_from(PUB_A), b"x", sig)


def test_rfc8291_message():
    ua_public = webpush.public_bytes(webpush.public_of(B))
    body = webpush.encrypt(b'{"title":"x"}', ua_public, bytes(16), as_private=A, salt=bytes(range(16)))
    assert body.hex() == ("000102030405060708090a0b0c0d0e0f000010004104471c3e758c4904285bba7e53118ed0f524adeb0757d25bd2f8"
                          "e7b0d76dfa714cdd520f7aca8a8b917acc37f51de8f0c9bbe3ad858382e702dc25a12d09f7a8584dcd2924eb64b36b"
                          "4e3b6d87be090a41df852b28d6dc1ce2c70f183e139b")
