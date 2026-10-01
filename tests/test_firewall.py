"""Windows Firewall in Check my setup: reading whether the ports get through, and letting them through."""

import os
import re
import subprocess

import pytest

from craft_conductor import doctor, firewall

REAL_READ = firewall.read  # (conftest fakes it for every test)
JAVA = r"C:\Users\Sam Smith\craft-conductor\servers\survival\.craft-conductor\java\21\bin\java.exe"
WANTED = [{"port": 25565, "label": "Survival (Minecraft)", "program": JAVA},
          {"port": 8766, "label": "friends' downloads", "program": r"C:\cc\craft-conductor.exe"}]


def state(rules, public_on=True):
    return {"profiles": [{"name": "Domain", "on": True}, {"name": "Private", "on": True}, {"name": "Public", "on": public_on}],
            "networks": [{"category": "Private", "ips": ["100.64.0.2"]}, {"category": "Public", "ips": ["192.168.1.20"]}],
            "rules": rules}


def rule(action=2, profile=0, program="Any", protocol="TCP", ports=("Any",), package="", service="Any"):
    return {"action": action, "profile": profile, "program": program, "protocol": protocol, "ports": list(ports),
            "package": package, "service": service}


def ports(fw):
    return [(p["port"], p["allowed"], p["blocked"]) for p in fw["ports"]]


def test_which_ports_get_through():
    lan = "192.168.1.20"  # (on a network Windows calls public)
    assert ports(firewall.assess(state([]), lan, WANTED)) == [(25565, False, False), (8766, False, False)]
    # A rule for the port, for public networks; a private-only one doesn't count here.
    fw = firewall.assess(state([rule(ports=["25565"], profile=4), rule(ports=["8766"], profile=2)]), lan, WANTED)
    assert fw["network"] == "Public" and ports(fw) == [(25565, True, False), (8766, False, False)]
    # A range, and "allowed for this program" (Windows' own prompt makes those; their ports can't always be read).
    fw = firewall.assess(state([rule(ports=["8000-9000"]), rule(program=JAVA.lower(), protocol="", ports=[""])]), lan, WANTED)
    assert ports(fw) == [(25565, True, False), (8766, True, False)]
    # Another program's rule, a Store app's or a service's, or one whose details couldn't be read: not for us.
    others = [rule(program=r"C:\other\java.exe"), rule(package="S-1-15-2-1"), rule(service="Dnscache"), rule(program="", protocol="")]
    assert ports(firewall.assess(state(others), lan, WANTED)) == [(25565, False, False), (8766, False, False)]
    # Cancel on Windows' prompt makes a block rule, which beats any allow.
    fw = firewall.assess(state([rule(ports=["Any"]), rule(action=4, program=JAVA, protocol="", ports=[""])]), lan, WANTED)
    assert ports(fw) == [(25565, False, True), (8766, True, False)]
    # Switched off for this network: nothing is blocked.
    assert firewall.assess(state([], public_on=False), lan, WANTED)["on"] is False


def test_check_my_setup_says_it_plainly():
    lan = "192.168.1.20"
    c = doctor.firewall_check(firewall.assess(state([], public_on=False), lan, WANTED))
    assert c.status == doctor.OK and "off" in c.detail and "public" in c.detail
    c = doctor.firewall_check(firewall.assess(state([rule()]), lan, WANTED))
    assert c.status == doctor.OK and "25565" in c.detail and not c.action
    c = doctor.firewall_check(firewall.assess(state([rule(ports=["25565"])]), lan, WANTED))
    assert c.status == doctor.WARN and "8766 (friends' downloads)" in c.detail and c.action == "firewall"
    c = doctor.firewall_check(firewall.assess(state([rule(), rule(action=4, program=JAVA)]), lan, WANTED))
    assert c.status == doctor.BAD and "Cancel" in c.detail and c.action == "firewall"


def test_its_own_rules_are_read_one_by_one():
    """Without administrator rights, Windows' list of all ports left out the rules just added:
    Check my setup said they still weren't there. Craft Conductor's own are asked about singly."""
    assert "$_.Group -eq 'Craft Conductor'" in firewall.QUERY and "Get-NetFirewallPortFilter }" in firewall.QUERY
    assert f"-Group {firewall._ps_string(firewall.GROUP)}" in firewall.script([{"port": 25565, "label": "x"}])


def test_the_rules_it_adds():
    text = firewall.script([{"port": 25565, "label": "Sam's server & co; rm -rf", "unblock": JAVA},
                            {"port": 8766, "label": "friends' downloads", "unblock": None}])
    assert "New-NetFirewallRule -DisplayName 'Craft Conductor: Sams server  co rm -rf (TCP 25565)' -Group 'Craft Conductor'" in text
    assert "-LocalPort 25565 -Profile Private,Public" in text and "-LocalPort 8766" in text
    assert f"-Program '{JAVA}'" in text and text.count("Remove-NetFirewallRule") == 3  # (two old rules of ours, one block)
    assert "Action -eq 'Block'" in text
    assert firewall._ps_string("it's") == "'it''s'"
    # PowerShell takes curly quotes as quotes too: a path like C:\Users\O’Brien stays text.
    assert firewall._ps_string("O\u2019Brien\u2018x") == "'O\u2019\u2019Brien\u2018\u2018x'"
    with pytest.raises(firewall.FirewallError):
        firewall.script([{"port": 70000, "label": "x"}])


def test_letting_through_asks_windows(monkeypatch):
    """Asked for straight from Craft Conductor (through a hidden PowerShell, Windows' prompt stayed
    out of sight until it gave up), and its answer read: No, or the script's own exit code. The
    script goes inline: no file another program could change before it runs as administrator."""
    import base64
    answers, seen = [None, 1, 0], []

    def fake(program, arguments, timeout):
        encoded = re.fullmatch(r"-NoProfile -NonInteractive -EncodedCommand ([A-Za-z0-9+/=]+)", arguments).group(1)
        assert program == "powershell.exe"
        seen.append(base64.b64decode(encoded).decode("utf-16-le"))
        return answers.pop(0)
    monkeypatch.setattr(firewall, "available", lambda: True)  # (not os.name: that breaks pathlib elsewhere)
    monkeypatch.setattr(firewall, "elevate", fake)
    with pytest.raises(firewall.FirewallError, match="answered No"):
        firewall.let_through([{"port": 25565, "label": "x"}])
    with pytest.raises(firewall.FirewallError, match="couldn't add"):
        firewall.let_through([{"port": 25565, "label": "x"}])
    firewall.let_through([{"port": 25565, "label": "x"}])
    assert "-LocalPort 25565" in seen[0] and seen[0] == firewall.script([{"port": 25565, "label": "x"}])


def test_the_firewall_is_read_once_in_a_while(monkeypatch):
    runs = []
    monkeypatch.setattr(firewall, "read", REAL_READ)  # (the real read, with PowerShell faked)
    monkeypatch.setattr(firewall, "available", lambda: True)
    monkeypatch.setattr(firewall, "_cache", None)
    monkeypatch.setattr(firewall, "_powershell", lambda args, timeout: runs.append(1) or
                        subprocess.CompletedProcess(args, 0, '{"profiles": [], "networks": [], "rules": []}', ""))
    assert firewall.read() == firewall.read() == {"profiles": [], "networks": [], "rules": []}
    assert len(runs) == 1
    firewall.read(fresh=True)  # (after letting ports through: what's there now)
    assert len(runs) == 2


def test_only_at_this_computer(hub_env, monkeypatch):
    """The fix shows Windows' administrator prompt on this computer: not from a phone or another device."""
    from test_hub import login
    from test_web import Client
    hub, c = hub_env
    login(c)
    added = []
    monkeypatch.setattr(firewall, "read", lambda timeout=30, fresh=False:
                        state([rule(ports=[str(p["port"]) for p in added[-1]])] if added else []))
    monkeypatch.setattr(firewall, "let_through", lambda ports: added.append(ports))
    monkeypatch.setattr(firewall, "available", lambda: True)
    checks = c.get("/api/servers/alpha/doctor")[1]["checks"]
    assert next(x for x in checks if x["id"] == "firewall")["action"] == "firewall"
    away = {"X-Forwarded-For": "203.0.113.9"}
    assert c.call("POST", "/api/servers/alpha/doctor/fix", {"action": "firewall"}, headers=away)[0] in (401, 403)
    assert c.post("/api/servers/alpha/doctor/fix", {"action": "firewall", "__local": True}, headers=away)[0] in (401, 403)
    assert not added
    status, r, _ = c.post("/api/servers/alpha/doctor/fix", {"action": "firewall"})
    assert status == 200, r
    assert added and added[0][0]["port"] == 25565
    # Windows said yes but nothing changed: it doesn't claim it worked.
    monkeypatch.setattr(firewall, "read", lambda timeout=30, fresh=False: state([]))
    status, r, _ = c.post("/api/servers/alpha/doctor/fix", {"action": "firewall"})
    assert status == 400 and "still doesn't let port 25565" in r["error"]
