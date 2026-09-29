"""Read-only acceptance validation for running EVE-NG lab nodes."""
from pathlib import Path
import re
from urllib.parse import urlsplit

import paramiko

from .config import load_server
from .console_backup import palo_running
from .deploy import lab_path, named
from .device_console import Console, credentials
from .initialize import PaloConsole
from .initialize_cat9kv import (
    TEMPLATE as CAT9KV_TEMPLATE, load_bootstrap as load_cat9kv_bootstrap,
)
from .palo_ssh import connect_palo, management_targets
from .topology import interface_key
from . import validation_cat9kv, validation_iosxe, validation_nxos, validation_panos


# Register only templates with an implemented and tested adapter.
PLATFORMS = {
    "c8000v": validation_iosxe,
    CAT9KV_TEMPLATE: validation_cat9kv,
    "paloalto": validation_panos,
    "nxosv9k": validation_nxos,
    "nxosv9k-9300v": validation_nxos,
}


def _checks(topology):
    checks = topology.get("validation", [])
    if not isinstance(checks, list) or not checks:
        raise ValueError("Topology validation must be a nonempty list")
    allowed = {
        "interface": {"name", "type", "node", "interface", "address", "state"},
        "ping": {"name", "type", "node", "destination", "min_success_rate"},
    }
    allowed.update({kind: {"name", "type", "node"} | fields
                    for kind, fields in validation_iosxe.FIELDS.items()})
    allowed.update({kind: {"name", "type", "node"} | fields
                    for kind, fields in validation_panos.FIELDS.items()})
    allowed.update({kind: {"name", "type", "node"} | fields
                    for kind, fields in validation_nxos.FIELDS.items()})
    allowed.update({kind: {"name", "type", "node"} | fields
                    for kind, fields in validation_cat9kv.FIELDS.items()})
    for fields in allowed.values():
        fields.add("required")
    names = set()
    result = []
    for check in checks:
        if not isinstance(check, dict):
            raise ValueError("Each validation check must be a mapping")
        kind = check.get("type")
        if not isinstance(kind, str) or kind not in allowed or set(check) - allowed[kind]:
            raise ValueError("Unsupported validation check: " + repr(check))
        for field in ("name", "node"):
            if not isinstance(check.get(field), str) or not check[field].strip():
                raise ValueError("Validation " + field + " must be a nonempty string")
        if check["name"] in names:
            raise ValueError("Duplicate validation check name: " + check["name"])
        names.add(check["name"])
        if type(check.get("required", True)) is not bool:
            raise ValueError("Validation required must be a boolean")
        if kind in validation_cat9kv.FIELDS:
            validation_cat9kv.validate_check(check)
        elif kind in validation_iosxe.FIELDS:
            validation_iosxe.validate_check(check)
        elif kind in validation_nxos.FIELDS:
            validation_nxos.validate_check(check)
        elif kind in validation_panos.FIELDS:
            validation_panos.validate_check(check)
        elif kind == "interface":
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
    try:
        channel.get_pty(term="vt100", width=512, height=1000)
        channel.exec_command("telnet 127.0.0.1 " + str(url.port))
        console = Console(channel, boot_timeout=timeout)
        console.login(*login, read_only=True)
    except Exception:
        channel.close()
        raise
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


def _append_result(report, check, node_name, passed, evidence):
    item = {
        "name": check["name"],
        "type": check["type"],
        "node": node_name,
        "result": "pass" if passed else "fail",
        "evidence": evidence,
    }
    if "required" in check:
        item["required"] = check["required"]
    report["checks"].append(item)
    if not passed and check.get("required", True):
        report["result"] = "fail"


def _fail_node(report, node_name, checks, error):
    # A node-level execution failure means no assertion was actually evaluated.
    # It fails the validation run independently of each check's required flag.
    report["result"] = "fail"
    for check in checks:
        _append_result(report, check, node_name, False, {
            "reason": str(error),
            "failure_kind": "execution",
        })


def _validate_iosxe_node(ssh, node, node_name, checks, root, timeout, report):
    channel = None
    try:
        login = credentials(root, prefix="CISCO")
        channel, console = _open_console(ssh, node, login, timeout)
        if any(check["type"] in validation_iosxe.FIELDS or check["type"] in validation_nxos.FIELDS for check in checks):
            console.command("terminal length 0")
        for check in checks:
            try:
                if check["type"] == "interface":
                    passed, evidence = _interface_check(console, check)
                elif check["type"] == "ping":
                    passed, evidence = _ping_check(console, check)
                elif check["type"] in validation_iosxe.FIELDS:
                    passed, evidence = validation_iosxe.evaluate(console, check)
                else:
                    passed, evidence = validation_nxos.evaluate(console, check)
            except RuntimeError as error:
                passed, evidence = False, {"reason": str(error)}
            _append_result(report, check, node_name, passed, evidence)
    except RuntimeError as error:
        _fail_node(report, node_name, checks, error)
    finally:
        if channel is not None:
            channel.close()


def _management_service(ssh, address, port):
    channel = None
    try:
        channel = ssh.get_transport().open_channel(
            'direct-tcpip', (address, port), ('127.0.0.1', 0), timeout=10)
        return True
    except (OSError, paramiko.SSHException):
        return False
    finally:
        if channel is not None:
            channel.close()


def _validate_cat9kv_node(ssh, node, node_name, checks, intent, root, timeout, report):
    channel = None
    try:
        login = credentials(root, prefix="CISCO")
        channel, console = _open_console(ssh, node, login, timeout)
        console.command("terminal length 0")
        for check in checks:
            try:
                if check["type"] == "interface":
                    passed, evidence = _interface_check(console, check)
                elif check["type"] == "ping":
                    passed, evidence = _ping_check(console, check)
                elif check["type"] in validation_iosxe.FIELDS:
                    passed, evidence = validation_iosxe.evaluate(console, check)
                else:
                    passed, evidence = validation_cat9kv.evaluate(
                        console, check, intent, username=login[0])
                    if check["type"] == "cat9kv-dnac-bootstrap":
                        address = intent["management"]["address"]
                        services = {
                            "ssh_22": _management_service(ssh, address, 22),
                            "netconf_830": _management_service(ssh, address, 830),
                        }
                        evidence.setdefault("observed", {})["management_services"] = services
                        if not all(services.values()):
                            passed = False
                            evidence["reason"] = (
                                "Management SSH or NETCONF is not reachable from the EVE host")
            except RuntimeError as error:
                passed, evidence = False, {"reason": str(error)}
            _append_result(report, check, node_name, passed, evidence)
    except RuntimeError as error:
        _fail_node(report, node_name, checks, error)
    finally:
        if channel is not None:
            channel.close()


def _validate_panos_node(ssh, topology, node_name, checks, root, timeout, report, node=None):
    device = None
    channel = None
    try:
        targets = management_targets(root, topology["name"])
        login = credentials(root, prefix="PALO")
        if node_name in targets:
            device, channel = connect_palo(ssh, targets[node_name], login[0], login[1], timeout)
            console = PaloConsole(channel, boot_timeout=timeout)
            console.login(*login)
        else:
            url = urlsplit((node or {}).get("url", ""))
            if (node or {}).get("console") != "telnet" or url.scheme != "telnet" or not url.port:
                raise RuntimeError("PAN-OS validation requires management_ip or an advertised Telnet console")
            channel = ssh.get_transport().open_session(timeout=10)
            channel.get_pty(term="vt100", width=512, height=1000)
            channel.exec_command("telnet 127.0.0.1 " + str(url.port))
            console = PaloReadOnlyConsole(channel, boot_timeout=timeout)
            console.login(*login)
        root_xml = validation_panos.parse_running_config(palo_running(console, timeout))
        for check in checks:
            try:
                passed, evidence = (validation_panos.evaluate_operational(console, check)
                                    if check["type"] in validation_panos.OPERATIONAL
                                    else validation_panos.evaluate(root_xml, check))
            except RuntimeError as error:
                passed, evidence = False, {"reason": str(error)}
            _append_result(report, check, node_name, passed, evidence)
    except RuntimeError as error:
        _fail_node(report, node_name, checks, error)
    finally:
        if channel is not None:
            channel.close()
        if device is not None:
            device.close()


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
        template = node.get("template")
        if template not in PLATFORMS:
            raise ValueError(
                "Validation currently supports c8000v, cat9kvuadp, paloalto, nxosv9k, and nxosv9k-9300v nodes only: " +
                check["node"])
        kind = check["type"]
        if template == "c8000v" and kind not in ({"interface", "ping"} | set(validation_iosxe.FIELDS)):
            raise ValueError("c8000v validation requires IOS XE or legacy check types: " + check["name"])
        if template in ("nxosv9k", "nxosv9k-9300v") and kind not in validation_nxos.FIELDS:
            raise ValueError("NX-OS validation requires nxos-* check types: " + check["name"])
        if (template == CAT9KV_TEMPLATE
                and kind not in ({"interface", "ping"}
                                 | set(validation_iosxe.FIELDS)
                                 | set(validation_cat9kv.FIELDS))):
            raise ValueError(
                "cat9kvuadp validation requires Cat9Kv or IOS-XE check types: "
                + check["name"])
        if template == "paloalto" and kind not in validation_panos.FIELDS:
            raise ValueError(
                "Palo Alto validation currently requires panos-* check types: " +
                check["name"])
        if str(node.get("status")) != "2":
            raise RuntimeError("Start " + check["node"] + " before validation")

    cat9kv_intents = {}
    base = (Path(root) / "labs" / topology["name"] / "configs").resolve()
    for node_name in {check["node"] for check in checks}:
        if nodes[node_name].get("template") != CAT9KV_TEMPLATE:
            continue
        path = (base / (node_name + "-init.yaml")).resolve()
        if not path.is_relative_to(base) or not path.is_file():
            raise ValueError(
                "Cat9Kv validation requires configs/" + node_name + "-init.yaml")
        intent = load_cat9kv_bootstrap(path, root)
        if (any(check["node"] == node_name
                and check["type"] == "cat9kv-underlay" for check in checks)
                and "ospf-underlay" not in intent["profiles"]):
            raise ValueError(
                "cat9kv-underlay validation requires the ospf-underlay profile")
        cat9kv_intents[node_name] = intent

    server = load_server(root, server_name, auth="ssh")
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
            node = nodes[node_name]
            if node["template"] == "paloalto":
                _validate_panos_node(
                    ssh, topology, node_name, node_checks, root, timeout, report, node=node)
            elif node["template"] == CAT9KV_TEMPLATE:
                _validate_cat9kv_node(
                    ssh, node, node_name, node_checks,
                    cat9kv_intents[node_name], root, timeout, report)
            else:
                _validate_iosxe_node(
                    ssh, node, node_name, node_checks, root, timeout, report)
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
    if cat9kv_intents:
        report["readiness"] = {}
        for node_name in cat9kv_intents:
            results = [item for item in report["checks"] if item["node"] == node_name]
            dnac = [item for item in results
                    if item["type"] == "cat9kv-dnac-bootstrap"]
            underlay = [item for item in results
                        if item["type"] == "cat9kv-underlay"]
            states = []
            if dnac and all(item["result"] == "pass" for item in dnac):
                states.append("DNAC_BOOTSTRAP_READY")
            required_pass = all(
                item["result"] == "pass" for item in results
                if item.get("required", True))
            if underlay and required_pass and all(
                    item["result"] == "pass" for item in underlay):
                states.append("UNDERLAY_READY")
            report["readiness"][node_name] = states
    return report


class PaloReadOnlyConsole(PaloConsole):
    """Serial validation never performs first-boot setup or leaves config mode."""
    def login(self, username, password, secret=None):
        # Clear any unfinished command before requesting an empty prompt.
        self.channel.sendall("\x15\r")
        pattern = r"(?im:^[^\n]*login:\s*$|^username:\s*$|^password:\s*$|^(?:enter )?(?:old|new|confirm|retype)[^\n]*password[^\n]*$)|^[\w.@()/:\-]+[>#]\s*$"
        for _ in range(6):
            _, match = self.expect(pattern, timeout=self.boot_timeout, wake=False)
            prompt = match.group().strip()
            if re.search(r"old|new|confirm|retype", prompt, re.I) or prompt.endswith("#"):
                raise RuntimeError("PAN-OS validation refuses setup/configuration prompts")
            if prompt.endswith(">"):
                return
            if prompt.lower().endswith(("login:", "username:")):
                self.send(username)
            elif prompt.lower() == "password:":
                self.send(password)
        raise RuntimeError("PAN-OS read-only login failed")
