"""Windows Firewall in Check my setup: reading whether the ports get through, and letting them through."""

import json
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
    assert c.status == doctor.OK and "25565" in c.detail and not c.action and "Java program" not in c.detail
    # What Windows' own "allow Java?" prompt makes is a rule for the program: the line says so, not "port".
    c = doctor.firewall_check(firewall.assess(state([rule(program=JAVA, protocol="", ports=[""])]), lan, WANTED[:1]))
    assert c.status == doctor.OK and "Port 25565 (Survival (Minecraft)) gets through because of a Windows rule for the Java program (any port), not a rule for that port." in c.detail
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


def test_accented_rule_names_and_folders_are_read(monkeypatch):
    """PowerShell writes UTF-8 and it's read as UTF-8: a rule for a folder with accents (or Windows' own rule
    names outside English) no longer made the whole read fail (#150)."""
    seen = {}
    monkeypatch.setattr(subprocess, "run", lambda args, **kw: seen.update(args=args, **kw) or subprocess.CompletedProcess(args, 0, "", ""))
    firewall._powershell(["-Command", firewall.QUERY], 30)
    assert seen["encoding"] == "utf-8" and seen["errors"] == "replace"
    assert seen["args"][-1].startswith(firewall.UTF8_OUTPUT)


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell")
def test_powershell_really_answers_in_utf8():
    name = "C:\\servers\\ünïcødé 日本語"
    r = firewall._powershell(["-Command", firewall.UTF8_OUTPUT + f"'{name}' | ConvertTo-Json"], 60)
    assert r.returncode == 0 and json.loads(r.stdout) == name


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


def ours(port, name=None, **kw):
    return {**rule(ports=[str(port)], **kw), "group": "Craft Conductor", "name": name or f"Craft Conductor: Alpha (TCP {port})"}


def test_only_craft_conductors_own_rules_can_be_removed():
    st = state([ours(25565), ours(8766, "Craft Conductor: friends downloads (TCP 8766)"),
                {**rule(ports=["25565"]), "group": "", "name": "Someone else's rule for the same port"},
                {**ours(25570), "ports": ["25570-25580"]},          # (a range: not one Craft Conductor made)
                {**ours(25571), "action": 4}])                      # (a block rule)
    assert firewall.own_rules(st, 25565) == [{"name": "Craft Conductor: Alpha (TCP 25565)", "port": 25565, "protocol": "TCP"}]
    assert [r["port"] for r in firewall.own_rules(st)] == [25565, 8766]
    assert firewall.own_rules(None) == []
    text = firewall.remove_script(["Craft Conductor: Sam's server (TCP 1)"])
    assert "Get-NetFirewallRule -DisplayName 'Craft Conductor: Sam''s server (TCP 1)'" in text
    assert "$_.Group -eq 'Craft Conductor'" in text and text.count("Remove-NetFirewallRule") == 1


def test_a_deleted_servers_rule_is_offered_and_removed_on_request(hub_env, monkeypatch):
    from test_hub import login
    hub, c = hub_env
    login(c)
    from craft_conductor.properties import write_properties
    write_properties(hub.get("alpha").m.server_dir / "server.properties", {"server-port": "25599"})  # (main, the other one here, has 25565)
    port = int(read_port(hub))
    assert port == 25599
    st = state([ours(port), ours(port + 1, "Craft Conductor: Other (TCP %d)" % (port + 1))])
    removed = []
    monkeypatch.setattr(firewall, "read", lambda timeout=30, fresh=False: st)
    monkeypatch.setattr(firewall, "available", lambda: True)
    monkeypatch.setattr(firewall, "remove", lambda names, timeout=300: removed.append(names))
    rules = c.get("/api/hub/firewall-rules?id=alpha")[1]["rules"]
    assert [r["port"] for r in rules] == [port]
    assert c.get("/api/hub/firewall-rules?id=nothere")[1] == {"rules": []}
    write_properties(hub.get("alpha").m.server_dir / "server.properties", {"server-port": "25565"})
    assert c.get("/api/hub/firewall-rules?id=alpha")[1] == {"rules": []}   # (another server here uses 25565: its rule stays)
    write_properties(hub.get("alpha").m.server_dir / "server.properties", {"server-port": "25599"})
    # only rules that are there, and Craft Conductor's own, are removed
    status, r, _ = c.post("/api/hub/firewall/remove", {"names": [rules[0]["name"], "Core Networking - Echo Request", "x"]})
    assert status == 200 and removed == [[rules[0]["name"]]] and r["removed"] == [rules[0]["name"]]
    away = {"X-Forwarded-For": "203.0.113.9"}
    assert c.post("/api/hub/firewall/remove", {"names": [rules[0]["name"]]}, headers=away)[0] in (401, 403)
    assert c.post("/api/hub/firewall/remove", {"names": []})[0] == 400
    assert len(removed) == 1


def read_port(hub):
    from craft_conductor.properties import read_properties
    return read_properties(hub.get("alpha").m.server_dir / "server.properties").get("server-port", "25565")


def test_check_my_setup_offers_to_remove_rules_for_ports_nothing_uses(hub_env, monkeypatch):
    from craft_conductor.properties import write_properties
    from test_hub import login
    hub, c = hub_env
    login(c)
    write_properties(hub.get("alpha").m.server_dir / "server.properties", {"server-port": "25599"})
    st = state([ours(25599), ours(25611, "Craft Conductor: Test World Spaces (Minecraft) (TCP 25611)"),
                ours(8766, "Craft Conductor: friends downloads (TCP 8766)")])   # (8766 is the friends' download port)
    removed = []
    monkeypatch.setattr(firewall, "read", lambda timeout=30, fresh=False: st)
    monkeypatch.setattr(firewall, "available", lambda: True)
    monkeypatch.setattr(firewall, "remove", lambda names, timeout=300: removed.append(names))
    checks = {x["id"]: x for x in c.get("/api/servers/alpha/doctor")[1]["checks"]}
    old = checks["firewall-old"]
    assert old["action"] == "firewall-clean" and "TCP 25611" in old["detail"] and "25599" not in old["detail"] and "8766" not in old["detail"]
    away = {"X-Forwarded-For": "203.0.113.9"}
    assert c.post("/api/servers/alpha/doctor/fix", {"action": "firewall-clean"}, headers=away)[0] in (401, 403)
    assert not removed
    status, r, _ = c.post("/api/servers/alpha/doctor/fix", {"action": "firewall-clean"})
    assert status == 200 and removed == [["Craft Conductor: Test World Spaces (Minecraft) (TCP 25611)"]], r


def test_the_friends_download_rule_is_offered_when_nothing_shares_it(hub_env, monkeypatch):
    from test_hub import login
    hub, c = hub_env
    login(c)
    port = hub.share_settings()["port"]
    monkeypatch.setattr(firewall, "available", lambda: True)
    monkeypatch.setattr(firewall, "read", lambda timeout=30, fresh=False: state([ours(port, f"Craft Conductor: friends downloads (TCP {port})")]))
    assert hub.share is None
    assert [r["port"] for r in c.get("/api/hub/firewall-rules?share=1")[1]["rules"]] == [port]
    hub.share = object()                    # (running: friends are using it)
    try:
        assert c.get("/api/hub/firewall-rules?share=1")[1] == {"rules": []}
    finally:
        hub.share = None


def test_the_command_line_lists_and_removes_the_rules(monkeypatch, capsys):
    from craft_conductor import cli
    removed = []
    monkeypatch.setattr(firewall, "available", lambda: True)
    monkeypatch.setattr(firewall, "read", lambda timeout=30, fresh=False: state([ours(25565), ours(8766, "Craft Conductor: friends downloads (TCP 8766)")]))
    monkeypatch.setattr(firewall, "remove", lambda names, timeout=300: removed.append(names))
    assert cli.main(["firewall", "list"]) == 0 and not removed
    assert "TCP 25565" in capsys.readouterr().out
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert cli.main(["firewall", "remove"]) == 0 and not removed and "Kept." in capsys.readouterr().out
    assert cli.main(["firewall", "remove", "--yes"]) == 0 and len(removed[0]) == 2
    monkeypatch.setattr(firewall, "available", lambda: False)
    assert cli.main(["firewall", "list"]) == 1


def test_the_settings_page_offers_every_rule_removed(hub_env, monkeypatch):
    from test_hub import login
    hub, c = hub_env
    login(c)
    monkeypatch.setattr(firewall, "available", lambda: True)
    monkeypatch.setattr(firewall, "read", lambda timeout=30, fresh=False: state([ours(25565), ours(9, "Craft Conductor: Other (TCP 9)")]))
    assert c.get("/api/hub/firewall-rules?available=1")[1] == {"available": True}
    got = c.get("/api/hub/firewall-rules?all=1")[1]
    assert got["available"] and [r["port"] for r in got["rules"]] == [25565, 9]
