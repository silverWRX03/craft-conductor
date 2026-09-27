"""Check my setup: plain-words checks, the internet test (only when asked), and a report
for bug reports with the secrets taken out."""

import io
import socket
import zipfile

from mcsm import doctor

from test_hub import login


def test_checks_and_report(hub_env):
    hub, c = hub_env
    login(c)
    d = hub.get("alpha")
    d.m.config.client.token = "fake-" + "x" * 20  # (the invite secret lives in the config)
    checks = {x["id"]: x for x in c.get("/api/servers/alpha/doctor")[1]["checks"]}
    assert checks["installed"]["status"] == "ok" and checks["disk"]["status"] in ("ok", "warn", "bad")
    assert "port" in checks and checks["memory"]["status"] in ("ok", "warn", "bad")

    status, body, headers = c.call("GET", "/api/servers/alpha/doctor/report")
    assert status == 200 and headers["Content-Type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(body if isinstance(body, bytes) else body.encode("latin-1")))
    assert {"checks.json", "system.json", "latest.log"} <= set(z.namelist())
    everything = b"".join(z.read(n) for n in z.namelist())
    assert b"fake-xxxxxxxx" not in everything
    assert "mcsm.toml" in z.namelist()  # the config, secrets taken out (see test_secrets_are_taken_out)
    from mcsm.web import device_allowed
    assert not device_allowed("GET", "/api/doctor/report")  # not for paired phones


def test_a_busy_port_is_found(hub_env):
    hub, c = hub_env
    d = hub.get("alpha")
    with socket.socket() as s:  # another program on the server's port
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        props = d.m.server_dir / "server.properties"
        text = props.read_text() if props.exists() else ""
        props.write_text(text + f"\nserver-port={port}\n")
        checks = {x.id: x for x in doctor.run(d.m, "stopped", total_gb=64)}
    assert checks["port"].status == "bad" and "Another program" in checks["port"].detail
    assert checks["memory"].status == "ok"
    tight = {x.id: x for x in doctor.run(d.m, "stopped", total_gb=4.5)}["memory"]
    assert tight.status == "bad" and "less memory" in tight.fix


def test_the_internet_test(http):
    http.json[doctor.PORT_CHECK.format(port=25565)] = {"ip": "203.0.113.7", "port": 25565, "reachable": False}
    r = doctor.internet_check(http, 25565, running=True)
    assert r.status == "bad" and "Forward TCP port 25565" in r.fix
    http.json[doctor.PORT_CHECK.format(port=25565)] = {"ip": "203.0.113.7", "port": 25565, "reachable": True}
    assert doctor.internet_check(http, 25565, running=True).status == "ok"
    assert doctor.internet_check(http, 25565, running=False).status == "info"  # nothing to connect to


def test_secrets_are_taken_out():
    text = "\n".join([
        '[client]', 'token = "abcdefghijklmnopqrstuv"', 'enabled = true',
        'discord_webhook = "https://discord.com/api/webhooks/123/abc"',
        'curseforge_api_key = "k" ', 'motd = "My server"',
        'seen https://mc.example.com:8766/join/Abcdefghijklmnop/pack.json',
        'invite mcsm-' + "Q" * 60,
        '[Server thread/INFO]: Steve[/203.0.113.44:51234] logged in; also [2001:db8::7]:25565',
        'listening on 127.0.0.1:8765',
    ])
    out = doctor.redact(text)
    for secret in ("abcdefghijklmnopqrstuv", "webhooks/123/abc", "Abcdefghijklmnop", "Q" * 60, "203.0.113.44", "2001:db8::7"):
        assert secret not in out
    assert 'motd = "My server"' in out and "enabled = true" in out and "127.0.0.1:8765" in out
