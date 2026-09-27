"""mcsm's own certificate for the share server, and friends' mcsm pinning it."""

import os
import socket
import ssl
import threading

import pytest

from mcsm import join, joinui, tlscert

from test_friends import FP, pack
from test_web import Client


def test_certificate_is_valid_tls_and_kept(tmp_path):
    cert, key, fp = tlscert.ensure(tmp_path)
    assert len(fp) == 43
    if os.name != "nt":  # (Windows keeps it private by where it is: the user's own profile)
        assert oct(key.stat().st_mode & 0o777) == "0o600"
    assert tlscert.ensure(tmp_path) == (cert, key, fp)  # made once, then reused
    ctx = tlscert.server_context(cert, key)
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def serve():
        conn, _ = srv.accept()
        with ctx.wrap_socket(conn, server_side=True) as s:
            s.sendall(b"hi")
    threading.Thread(target=serve, daemon=True).start()
    # A strict client (signature, dates, name) accepts it: it's a proper certificate.
    client = ssl.create_default_context(cafile=str(cert))
    with socket.create_connection(srv.getsockname()) as raw, client.wrap_socket(raw, server_hostname="mcsm") as s:
        assert s.recv(2) == b"hi" and tlscert.fingerprint(s.getpeercert(binary_form=True)) == fp
    srv.close()


def test_certificate_is_renewed_near_its_end(tmp_path):
    import datetime
    key = tlscert.generate_key()
    old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=3640)
    (tmp_path / tlscert.KEY_FILE).write_text(tlscert.key_pem(key))
    (tmp_path / tlscert.CERT_FILE).write_text(tlscert._pem("CERTIFICATE", tlscert.make_certificate(key, now=old)))
    (tmp_path / "share-cert.json").write_text(__import__("json").dumps({"expires": (old + datetime.timedelta(days=tlscert.VALID_DAYS)).timestamp()}))
    before = tlscert.fingerprint(ssl.PEM_cert_to_DER_cert((tmp_path / tlscert.CERT_FILE).read_text()))
    assert tlscert.ensure(tmp_path)[2] != before


def test_friend_page_asks_for_an_invite_and_remembers_servers(tmp_path, http, monkeypatch):
    from mcsm import clipboard
    inv = join.Invite("mc.example.com", 8766, "D" * 24, FP)
    http.json[f"{inv.url}/pack.json"] = pack(name="Weekend Server")
    monkeypatch.setattr(clipboard, "read_text", lambda: f"join us! {inv.code}")
    ui = joinui.JoinUI(None, mc_dir=tmp_path / ".minecraft", http=http, prism_dir=tmp_path / "prism", out_dir=tmp_path)
    url = ui.start()
    try:
        c = Client(url.rstrip("/"))
        info = c.get("/api/info")[1]
        assert info["need_invite"] and info["copied_invite"] == inv.code and info["remembered"] == []
        assert c.post("/api/invite", {"invite": "nonsense"})[0] == 400
        info = c.post("/api/invite", {"invite": inv.code})[1]
        assert not info["need_invite"] and info["pack"]["name"] == "Weekend Server"
        assert http.pins[inv.netloc] == FP  # the server's certificate is pinned
    finally:
        ui.stop()
    joinui.remember(tmp_path / ".minecraft", "Weekend Server", inv.code)
    assert joinui.remembered(tmp_path / ".minecraft") == [{"name": "Weekend Server", "code": inv.code,
                                                             "at": pytest.approx(joinui.remembered(tmp_path / ".minecraft")[0]["at"])}]
    # Running your own server instead.
    ui = joinui.JoinUI(None, mc_dir=tmp_path / ".minecraft", http=http)
    url = ui.start()
    try:
        assert Client(url.rstrip("/")).post("/api/own-server", {})[0] == 200
        assert ui.wants_server and ui.done.is_set()
    finally:
        ui.stop()
