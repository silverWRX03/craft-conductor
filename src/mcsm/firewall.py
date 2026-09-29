"""Windows Firewall: whether Craft Conductor's ports get through, and letting them through.

Reading the rules needs no administrator rights: one PowerShell call (about two seconds), only
when Check my setup asks. Letting ports through does: Windows asks the person at this computer
with its usual administrator prompt. Only Craft Conductor's own rules are added (TCP ports, in
the group "Craft Conductor", for private and public networks: Windows puts many home networks
under "public"), and only block rules for Craft Conductor's own Java are removed (Windows makes
those when its own "allow Java?" prompt is answered Cancel, and a block rule beats any allow).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

GROUP = "Craft Conductor"
ALLOW, BLOCK = 2, 4                                  # (NetSecurity's Action values)
PROFILE_FLAGS = {"Domain": 1, "DomainAuthenticated": 1, "Private": 2, "Public": 4}  # (a rule's Profile: 0 is any)

# Everything the check needs, in one call, in words that don't depend on Windows' language.
QUERY = r"""
$ErrorActionPreference = 'SilentlyContinue'
$profiles = @(Get-NetFirewallProfile | ForEach-Object { [pscustomobject]@{ name = "$($_.Name)"; on = ("$($_.Enabled)" -eq 'True') } })
$networks = @(Get-NetConnectionProfile | ForEach-Object { [pscustomobject]@{ category = "$($_.NetworkCategory)";
    ips = @((Get-NetIPAddress -InterfaceIndex $_.InterfaceIndex -AddressFamily IPv4).IPAddress) } })
$apps = @{}; Get-NetFirewallApplicationFilter -All | ForEach-Object { $apps[$_.InstanceID] = $_ }
$ports = @{}; Get-NetFirewallPortFilter -All | ForEach-Object { $ports[$_.InstanceID] = $_ }
$services = @{}; Get-NetFirewallServiceFilter -All | ForEach-Object { $services[$_.InstanceID] = "$($_.Service)" }
$rules = @(Get-NetFirewallRule -Direction Inbound -Enabled True | ForEach-Object {
    $p = $ports[$_.Name]; $a = $apps[$_.Name]
    [pscustomobject]@{ action = [int]$_.Action; profile = [int]$_.Profile; program = "$($a.Program)"; package = "$($a.Package)";
                       service = "$($services[$_.Name])"; protocol = "$($p.Protocol)";
                       ports = @($p.LocalPort | ForEach-Object { "$_" }) } })
[pscustomobject]@{ profiles = $profiles; networks = $networks; rules = $rules } | ConvertTo-Json -Compress -Depth 5
"""


class FirewallError(RuntimeError):
    pass


def _powershell(script: list[str], timeout: float) -> subprocess.CompletedProcess:
    from .desktop import NO_WINDOW
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", *script], capture_output=True, text=True,
                          timeout=timeout, **NO_WINDOW)


def read(timeout: float = 30) -> dict | None:
    """The firewall's state and its enabled inbound rules; None when that can't be read (not
    Windows, or PowerShell failed)."""
    if os.name != "nt":
        return None
    try:
        r = _powershell(["-Command", QUERY], timeout)
        data = json.loads(r.stdout or "null")
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        log.info("couldn't read Windows Firewall's rules: %s", e)
        return None
    return data if isinstance(data, dict) else None


def _list(x) -> list:
    return x if isinstance(x, list) else [] if x is None else [x]


def _port_matches(spec: list[str], port: int) -> bool:
    for s in spec or ["Any"]:
        if s == "Any":
            return True
        if m := re.fullmatch(r"(\d+)-(\d+)", s):
            if int(m.group(1)) <= port <= int(m.group(2)):
                return True
        elif s.isdigit() and int(s) == port:
            return True
    return False


def _same_program(a: str, b: str | None) -> bool:
    return bool(b) and os.path.normcase(os.path.expandvars(a)) == os.path.normcase(str(b))


def assess(state: dict, lan_ip: str | None, wanted: list[dict]) -> dict:
    """Whether each wanted port gets through on the network this computer is on.

    ``wanted``: [{"port", "label", "program"}] (``program``: what listens on it, for rules made
    for a program rather than a port). Returns {"on", "network", "ports": [{"port", "label",
    "program", "allowed", "blocked"}]}."""
    networks = _list(state.get("networks"))
    mine = next((n for n in networks if lan_ip and lan_ip in _list(n.get("ips"))), None)
    category = str((mine or {}).get("category") or "Public")
    on = {str(p.get("name")): bool(p.get("on")) for p in _list(state.get("profiles"))}
    profile = "Domain" if category.startswith("Domain") else category
    flag = PROFILE_FLAGS.get(category, 4)
    out = {"on": on.get(profile, True), "network": category.replace("DomainAuthenticated", "Domain"), "ports": []}
    rules = [r for r in _list(state.get("rules")) if not r.get("profile") or int(r["profile"]) & flag]
    for w in wanted:
        def applies(r) -> bool:
            # (a rule whose details couldn't be read, or one for a Store app or a Windows service,
            # isn't taken to let anything else through)
            program, protocol = str(r.get("program") or ""), str(r.get("protocol") or "")
            if not program or str(r.get("service") or "Any") != "Any" or str(r.get("package") or "") not in ("", "Any"):
                return False
            if program != "Any":
                # A rule for the very program that listens (what Windows' own "allow?" prompt
                # makes: any port); its ports can't always be read without administrator rights.
                return _same_program(program, w.get("program")) and (
                    not protocol or (protocol in ("TCP", "Any") and _port_matches(_list(r.get("ports")), w["port"])))
            return protocol in ("TCP", "Any") and _port_matches(_list(r.get("ports")), w["port"])
        blocked = any(int(r.get("action", 0)) == BLOCK and applies(r) for r in rules)
        allowed = any(int(r.get("action", 0)) == ALLOW and applies(r) for r in rules)
        out["ports"].append({**w, "allowed": allowed and not blocked, "blocked": blocked})
    return out


def _ps_string(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def script(ports: list[dict]) -> str:
    """The PowerShell run with administrator rights: rules for these TCP ports (replacing
    Craft Conductor's own rules of the same name), and Craft Conductor's Java unblocked."""
    lines = ["$ErrorActionPreference = 'Stop'", "try {"]
    for p in ports:
        port = int(p["port"])
        if not 1 <= port <= 65535:
            raise FirewallError("that isn't a port")
        label = re.sub(r"[^A-Za-z0-9 ._()-]+", "", str(p["label"]))[:60].strip() or "server"
        name = _ps_string(f"{GROUP}: {label} (TCP {port})")
        lines += [f"  Get-NetFirewallRule -DisplayName {name} -ErrorAction SilentlyContinue | Remove-NetFirewallRule",
                  f"  New-NetFirewallRule -DisplayName {name} -Group {_ps_string(GROUP)} -Direction Inbound -Action Allow "
                  f"-Protocol TCP -LocalPort {port} -Profile Private,Public | Out-Null"]
        if p.get("unblock"):
            lines.append(f"  Get-NetFirewallApplicationFilter -Program {_ps_string(p['unblock'])} -ErrorAction SilentlyContinue | "
                         "Get-NetFirewallRule | Where-Object { $_.Direction -eq 'Inbound' -and $_.Action -eq 'Block' } | "
                         "Remove-NetFirewallRule")
    lines += ["  exit 0", "} catch { Write-Output $_.Exception.Message; exit 1 }"]
    return "\n".join(lines) + "\n"


def let_through(ports: list[dict], timeout: float = 300) -> None:
    """Add the rules, asking Windows for administrator rights (the person at this computer
    answers its prompt). Raises FirewallError when that's declined or fails."""
    if os.name != "nt":
        raise FirewallError("this is only for Windows")
    text = script(ports)
    fd, path = tempfile.mkstemp(prefix="mcsm-firewall-", suffix=".ps1")
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig") as f:
            f.write(text)
        run = ("$p = Start-Process powershell -Verb RunAs -WindowStyle Hidden -Wait -PassThru -ArgumentList "
               f"'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',{_ps_string(_quoted(path))}; exit $p.ExitCode")
        try:
            r = _powershell(["-Command", run], timeout)
        except (OSError, subprocess.SubprocessError) as e:
            raise FirewallError(f"Windows didn't run it ({e})") from None
    finally:
        Path(path).unlink(missing_ok=True)
    if r.returncode != 0:
        said = (r.stdout + r.stderr).strip()
        if "cancel" in said.lower() or not said:
            raise FirewallError("Windows didn't get the go-ahead (its administrator prompt was answered No)")
        raise FirewallError(said.splitlines()[-1][:300])
    log.info("Windows Firewall: let through TCP %s", ", ".join(str(p["port"]) for p in ports))


def _quoted(path: str) -> str:
    """A path as one argument for Start-Process (which joins its arguments with spaces)."""
    return f'"{path}"'
