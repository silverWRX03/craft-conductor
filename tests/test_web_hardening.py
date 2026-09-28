"""The control panel against misbehaving clients: HTTPS handshakes, odd request bodies."""

import socket
import ssl
import time
import urllib.request


def test_a_silent_connection_doesnt_hold_up_others(hub_env, tmp_path):
    from mcsm import tlscert
    from mcsm.web import WebUI
    hub, _ = hub_env
    cert, key, _ = tlscert.ensure(tmp_path / "tls")
    hub.web.tls_cert, hub.web.tls_key = str(cert), str(key)
    ui = WebUI(hub, host="127.0.0.1", port=0)
    ui.start()
    try:
        port = ui.httpd.server_address[1]
        silent = socket.create_connection(("127.0.0.1", port))  # connects, never says hello
        time.sleep(0.3)
        context = ssl.create_default_context()
        context.check_hostname, context.verify_mode = False, ssl.CERT_NONE
        started = time.monotonic()
        with urllib.request.urlopen(f"https://127.0.0.1:{port}/", context=context, timeout=10) as r:
            assert r.status == 200
        assert time.monotonic() - started < 5
        silent.close()
        # A plain-HTTP request to the HTTPS port gets an answer, not a hang.
        plain = socket.create_connection(("127.0.0.1", port), timeout=10)
        plain.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
        plain.recv(100)
        plain.close()
    finally:
        ui.stop()


def test_a_negative_length_is_refused_before_sign_in(hub_env):
    hub, c = hub_env
    port = hub.ui.httpd.server_address[1]
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
    s.sendall(b"POST /api/login HTTP/1.1\r\nHost: localhost\r\nX-MCSM: 1\r\nContent-Length: -1\r\n\r\n{}")
    assert s.recv(100).startswith(b"HTTP/1.0 400")  # (at once: it doesn't wait for more to read)
    s.close()


def test_guesses_sent_all_at_once_still_count(hub_env):
    import http.client
    import json
    import threading
    hub, _ = hub_env
    port = hub.ui.httpd.server_address[1]
    statuses = []

    def guess(i):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        try:
            conn.request("POST", "/api/login", json.dumps({"password": f"wrong-{i}"}),
                         {"X-MCSM": "1", "Content-Type": "application/json"})
            statuses.append(conn.getresponse().status)
        except ConnectionError:  # (a busy computer may turn some away: they don't get to guess either)
            statuses.append("refused")
        finally:
            conn.close()
    threads = [threading.Thread(target=guess, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert statuses.count(401) == 5 and statuses.count(429) + statuses.count("refused") == 15 and statuses.count(429)
