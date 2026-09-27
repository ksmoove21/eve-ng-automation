"""Read-only acceptance validation for running EVE-NG lab nodes."""
import re
from urllib.parse import urlsplit

import paramiko

from .config import load_server
from .deploy import lab_path, named
from .device_console import Console, credentials
from .topology import interface_key


def _checks(topology):
    checks = topology.get("validation", [])
    if not isinstance(checks, list) or not checks:
        raise ValueError("Topology validation must be a nonempty list")
    allowed = {
        "interface": {"name", "type", "node", "interface", "address", "state"},
        "ping": {"name", "type", "node", "destination", "min_success_rate"},
    }
    names = set()
    result = []
    for check in checks:
        if not isinstance(check, dict):
            raise ValueError("Each validation check must be a mapping")
        kind = check.get("type")
        if kind not in allowed or set(check) - allowed[kind]:
            raise ValueError("Unsupported validation check: " + repr(check))
        for field in ("name", "node"):
            if not isinstance(check.get(field), str) or not check[field].strip():
                raise ValueError("Validation " + field + " must be a nonempty string")
        if check["name"] in names:
            raise ValueError("Duplicate validation check name: " + check["name"])
        names.add(check["name"])
        if kind == "interface":
            if not isinstance(check.get("interface"), str) or not check["interface"].strip():
                raise ValueError("Interface validation requires interface")
            if "address" in check and (not isinstance(check["address"], str) or not check["address"].strip()):
                raise ValueError("Interface validation address must be a nonempty string")
            if check.get("state", "up") not in ("up", "down"):
                raise ValueError("Interface validation state must be up or down")
        else:
            if not isinstance(check.get("destination"), str) or not check["destination"].strip():
                raise ValueError("Ping validation requires destination")
            rate = check.get("min_success_rate", 100)
            if type(rate) is not int or not 0 <= rate <= 100:
                raise ValueError("Ping min_success_rate must be an integer from 0 to 100")
        result.append(check)
    return result


def _open_console(ssh, node, login, timeout):
    url = urlsplit(node.get("url", ""))
    if node.get("console") != "telnet" or url.scheme != "telnet" or not url.port:
        raise RuntimeError("Telnet console required for validation")
    channel = ssh.get_transport().open_session(timeout=10)
    channel.get_pty(term="vt100", width=512, height=1000)
    channel.exec_command("telnet 127.0.0.1 " + str(url.port))
    console = Console(channel, boot_timeout=timeout)
    console.login(*login)
    return channel, console


def _interface_check(console, check):
    interfaces = console.interface_status()
    matches = [item for item in interfaces
               if interface_key(item["interface"]) == interface_key(check["interface"])]
    if len(matches) != 1:
        return False, {"reason": "interface not found with an assigned IPv4 address"}
    item = matches[0]
    expected_state = check.get("state", "up")
    actual_up = item["status"].lower() == "up" and item["protocol"].lower() == "up"
    state_ok = actual_up if expected_state == "up" else not actual_up
    address_ok = "address" not in check or item["ip_address"] == check["address"]
    evidence = {
        "interface": item["interface"],
        "ip_address": item["ip_address"],
        "status": item["status"],
        "protocol": item["protocol"],
    }
    if not state_ok:
        evidence["reason"] = "interface state does not match"
    elif not address_ok:
        evidence["reason"] = "interface address does not match"
    return state_ok and address_ok, evidence


def _ping_check(console, check):
    destination = check["destination"]
    if not re.fullmatch(r"[A-Za-z0-9:.%-]+", destination):
        raise ValueError("Ping destination contains unsupported characters")
    minimum = check.get("min_success_rate", 100)
    best = 0
    attempts = []
    for _ in range(2):
        output = console.command("ping " + destination + " repeat 5 timeout 2", timeout=30)
        match = re.search(r"Success rate is\s+(\d+)\s+percent\s+\((\d+)/(\d+)\)", output, re.I)
        if not match:
            return False, {"destination": destination, "reason": "unrecognized ping result"}
        rate, received, sent = map(int, match.groups())
        attempts.append({"success_rate": rate, "received": received, "sent": sent})
        best = max(best, rate)
        if best >= minimum:
            break
    return best >= minimum, {
        "destination": destination,
        "success_rate": best,
        "minimum_success_rate": minimum,
        "attempts": attempts,
    }


def validate_lab(client, topology, root, server_name="default", timeout=60):
    """Execute declared acceptance checks without changing device configuration."""
    if not 1 <= timeout <= 3600:
        raise ValueError("--timeout must be between 1 and 3600 seconds")
    checks = _checks(topology)
    nodes = named(client, lab_path(topology) + "/nodes")
    declared = {node["name"] for node in topology["nodes"]}
    for check in checks:
        if check["node"] not in declared:
            raise ValueError("Validation references undeclared node: " + check["node"])
        if check["node"] not in nodes:
            raise RuntimeError("Validation node missing from EVE: " + check["node"])
        node = nodes[check["node"]]
        if node.get("template") != "c8000v":
            raise ValueError("Validation currently supports c8000v nodes only: " + check["node"])
        if str(node.get("status")) != "2":
            raise RuntimeError("Start " + check["node"] + " before validation")

    server = load_server(root, server_name, auth="ssh")
    login = credentials(root, prefix="CISCO")
    grouped = {}
    for check in checks:
        grouped.setdefault(check["node"], []).append(check)

    report = {"lab": topology["name"], "result": "pass", "checks": []}
    ssh = paramiko.SSHClient()
    try:
        ssh.load_system_host_keys()
        ssh.connect(server.get("ssh_host") or urlsplit(server["url"]).hostname,
                    username=server["ssh_username"], password=server["ssh_password"],
                    timeout=10, auth_timeout=10, banner_timeout=10,
                    allow_agent=False, look_for_keys=False)
        for node_name, node_checks in grouped.items():
            channel = None
            try:
                channel, console = _open_console(ssh, nodes[node_name], login, timeout)
                for check in node_checks:
                    try:
                        passed, evidence = (_interface_check(console, check)
                                            if check["type"] == "interface"
                                            else _ping_check(console, check))
                    except RuntimeError as error:
                        passed, evidence = False, {"reason": str(error)}
                    report["checks"].append({
                        "name": check["name"],
                        "type": check["type"],
                        "node": node_name,
                        "result": "pass" if passed else "fail",
                        "evidence": evidence,
                    })
                    if not passed:
                        report["result"] = "fail"
            finally:
                if channel is not None:
                    channel.close()
    except paramiko.BadHostKeyException:
        raise RuntimeError("EVE host SSH key has changed; verify it before validation") from None
    except paramiko.AuthenticationException:
        raise RuntimeError("EVE host SSH authentication failed during validation") from None
    except paramiko.SSHException:
        raise RuntimeError("EVE host SSH handshake failed during validation") from None
    except OSError:
        raise RuntimeError("Cannot connect to EVE host SSH during validation") from None
    finally:
        ssh.close()
    return report
