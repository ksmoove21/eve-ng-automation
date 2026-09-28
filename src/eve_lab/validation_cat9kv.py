"""Read-only Catalyst 9000v UADP profile validation."""
from ipaddress import IPv4Address, IPv4Interface
import re

from .initialize_cat9kv import (
    MANAGEMENT_INTERFACE, MANAGEMENT_VRF, parse_license_state,
)
from .topology import interface_key
from .validation_iosxe import OSPF_STATES, parse_ospf, parse_route


FIELDS = {
    "cat9kv-dnac-bootstrap": set(),
    "cat9kv-underlay": {"neighbors"},
}


def validate_check(check):
    kind = check["type"]
    if kind == "cat9kv-dnac-bootstrap":
        return
    neighbors = check.get("neighbors", [])
    if not isinstance(neighbors, list):
        raise ValueError("Cat9Kv underlay neighbors must be a list")
    seen = set()
    for neighbor in neighbors:
        if not isinstance(neighbor, dict) or set(neighbor) != {"neighbor", "state"}:
            raise ValueError("Each Cat9Kv underlay neighbor requires neighbor and state")
        try:
            address = str(IPv4Address(neighbor["neighbor"]))
        except (TypeError, ValueError):
            raise ValueError("Cat9Kv OSPF neighbor must be an IPv4 address") from None
        state = neighbor["state"]
        if not isinstance(state, str) or state.lower() not in OSPF_STATES:
            raise ValueError("Unsupported Cat9Kv OSPF neighbor state")
        if address in seen:
            raise ValueError("Duplicate Cat9Kv OSPF neighbor")
        seen.add(address)


def _interface_config(output):
    if re.search(r"^\s*%", output, re.M):
        raise RuntimeError("IOS-XE rejected interface configuration query")
    address = re.search(
        r"^\s*ip address (\d+\.\d+\.\d+\.\d+) (\d+\.\d+\.\d+\.\d+)\s*$",
        output, re.M)
    vrf = re.search(r"^\s*vrf forwarding (\S+)\s*$", output, re.M)
    ospf = re.search(r"^\s*ip ospf (\d+) area (\S+)\s*$", output, re.M)
    return {
        "address": (str(IPv4Interface(address.group(1) + "/" + address.group(2)))
                    if address else None),
        "vrf": vrf.group(1) if vrf else None,
        "ospf_process_id": int(ospf.group(1)) if ospf else None,
        "ospf_area": ospf.group(2) if ospf else None,
        "network_type": ("point-to-point" if re.search(
            r"^\s*ip ospf network point-to-point\s*$", output, re.M) else None),
        "routed": bool(re.search(r"^\s*no switchport\s*$", output, re.M)),
        "shutdown": bool(re.search(r"^\s*shutdown\s*$", output, re.M)),
    }


def _read_interface_config(console, interface):
    """Retry once when the serial console returns no interface stanza."""
    command = "show running-config interface " + interface
    output = console.command(command)
    if not re.search(
            r"^interface " + re.escape(interface) + r"\s*$", output, re.M):
        output = console.command(command)
    return _interface_config(output)


def _status(console):
    return {interface_key(item["interface"]): item
            for item in console.interface_status()}


def _dnac(console, intent, username):
    management = intent["management"]
    desired_license = set(intent["dnac"]["license"].values())
    hostname = console.command("show running-config | include ^hostname")
    domain = console.command("show running-config | include ^ip domain name")
    aaa = console.command("show running-config | section ^aaa")
    local_users = console.command("show running-config | include ^username")
    ssh = console.command("show ip ssh")
    privilege = console.command("show privilege")
    netconf = console.command("show netconf-yang status")
    snmp = console.command("show running-config | include ^snmp-server community")
    keys = console.command("show crypto key mypubkey rsa")
    interface = _read_interface_config(console, MANAGEMENT_INTERFACE)
    statuses = _status(console)
    route = parse_route(console.command(
        f"show ip route vrf {MANAGEMENT_VRF} 0.0.0.0 0.0.0.0"))
    license_state = parse_license_state(console.command("show version", timeout=120))
    management_status = statuses.get(interface_key(MANAGEMENT_INTERFACE))
    expected_address = management["address"] + "/" + str(management["prefix_length"])
    checks = {
        "hostname": bool(re.search(
            r"^hostname " + re.escape(intent["hostname"]) + r"\s*$", hostname, re.M)),
        "domain_name": bool(re.search(
            r"^ip domain name " + re.escape(intent["domain_name"]) + r"\s*$",
            domain, re.M)),
        "aaa_new_model": bool(re.search(r"^aaa new-model\s*$", aaa, re.M)),
        "aaa_local_login": bool(re.search(
            r"^aaa authentication login default local\s*$", aaa, re.M)),
        "aaa_local_exec": bool(re.search(
            r"^aaa authorization exec default local if-authenticated\s*$", aaa, re.M)),
        "aaa_console_authorization": bool(re.search(
            r"^aaa authorization console\s*$", aaa, re.M)),
        "privilege_15_user": bool(re.search(
            r"^username " + re.escape(username)
            + r" privilege 15 (?:password|secret)\b", local_users, re.M)),
        "privilege_15": bool(re.search(
            r"Current privilege level is 15\b", privilege, re.I)),
        "ssh_v2": bool(re.search(r"SSH Enabled\s*-\s*version 2(?:\.0)?", ssh, re.I)),
        "netconf_enabled": bool(re.search(
            r"(?:netconf-yang|NETCONF).*enabled", netconf, re.I)),
        "snmp_ro": bool(re.search(r"^snmp-server community \S+ RO(?:\s|$)", snmp, re.M)),
        "snmp_rw": bool(re.search(r"^snmp-server community \S+ RW(?:\s|$)", snmp, re.M)),
        "rsa_key": bool(re.search(
            r"^\s*(?:Key name:|Key Data:|Usage: General Purpose Key)", keys, re.M | re.I)),
        "management_config": (
            interface["address"] == expected_address
            and interface["vrf"] == MANAGEMENT_VRF
            and not interface["shutdown"]),
        "management_state": bool(
            management_status
            and management_status["ip_address"] == management["address"]
            and management_status["status"].lower() == "up"
            and management_status["protocol"].lower() == "up"),
        "management_default_route": (
            route["present"] and route["prefix"] == "0.0.0.0/0"
            and management["gateway"] in route["next_hops"]),
        "license": desired_license <= set(license_state["current"]),
    }
    evidence = {
        "readiness": "DNAC_BOOTSTRAP_READY",
        "expected": {
            "hostname": intent["hostname"],
            "management_interface": MANAGEMENT_INTERFACE,
            "management_address": expected_address,
            "management_gateway": management["gateway"],
            "license": sorted(desired_license),
        },
        "observed": {
            "checks": checks,
            "management_interface": management_status,
            "management_route": route,
            "license": license_state,
        },
    }
    passed = all(checks.values())
    if not passed:
        evidence["reason"] = "Catalyst Center bootstrap state is incomplete"
    return passed, evidence


def _underlay(console, check, intent):
    if "ospf-underlay" not in intent["profiles"]:
        raise RuntimeError("Bootstrap intent does not request ospf-underlay")
    underlay = intent["underlay"]
    process_id = underlay["ospf"]["process_id"]
    routing = console.command("show running-config | include ^ip routing")
    ospf = console.command(
        "show ip ospf " + str(process_id) + " | include Routing Process|Router ID")
    router_match = re.search(
        r"Routing Process \"ospf " + str(process_id)
        + r"\" with ID (\d+\.\d+\.\d+\.\d+)", ospf, re.I)
    statuses = _status(console)
    interfaces = []
    expected_interfaces = [underlay["loopback"]] + underlay["routed_interfaces"]
    for expected in expected_interfaces:
        observed = _read_interface_config(console, expected["interface"])
        status = statuses.get(interface_key(expected["interface"]))
        is_routed = expected in underlay["routed_interfaces"]
        passed = (
            observed["address"] == expected["address"]
            and observed["ospf_process_id"] == expected["ospf_process_id"]
            and observed["ospf_area"] == expected["ospf_area"]
            and not observed["shutdown"]
            and bool(status)
            and status["ip_address"] == str(IPv4Interface(expected["address"]).ip)
            and status["status"].lower() == "up"
            and status["protocol"].lower() == "up"
            and (not is_routed or (
                observed["routed"]
                and observed["network_type"] == expected["network_type"])))
        interfaces.append({
            "interface": expected["interface"],
            "expected_address": expected["address"],
            "observed": observed,
            "status": status,
            "result": "pass" if passed else "fail",
        })
    neighbor_expectations = check.get("neighbors", [])
    observed_neighbors = []
    neighbor_results = []
    if neighbor_expectations:
        observed_neighbors = parse_ospf(console.command("show ip ospf neighbor"))
        for expected in neighbor_expectations:
            address = str(IPv4Address(expected["neighbor"]))
            matches = [item for item in observed_neighbors
                       if item["neighbor"] == address or item["address"] == address]
            passed = bool(matches) and all(
                item["state"] == expected["state"].lower() for item in matches)
            neighbor_results.append({
                "neighbor": address,
                "expected_state": expected["state"].lower(),
                "observed": matches,
                "result": "pass" if passed else "fail",
            })
    checks = {
        "ip_routing": bool(re.search(r"^ip routing\s*$", routing, re.M)),
        "ospf_router_id": bool(
            router_match
            and router_match.group(1) == underlay["ospf"]["router_id"]),
        "interfaces": all(item["result"] == "pass" for item in interfaces),
        "neighbors": all(item["result"] == "pass" for item in neighbor_results),
    }
    evidence = {
        "readiness": "UNDERLAY_READY",
        "expected": {
            "ospf_process_id": process_id,
            "ospf_router_id": underlay["ospf"]["router_id"],
            "neighbor_count": len(neighbor_expectations),
        },
        "observed": {
            "checks": checks,
            "interfaces": interfaces,
            "neighbors": neighbor_results,
        },
    }
    passed = all(checks.values())
    if not passed:
        evidence["reason"] = "Routed underlay state is incomplete"
    return passed, evidence


def evaluate(console, check, intent, username=None):
    """Evaluate a declared Cat9Kv profile without changing device state."""
    validate_check(check)
    try:
        if check["type"] == "cat9kv-dnac-bootstrap":
            if not username:
                raise RuntimeError("Catalyst bootstrap validation requires the login username")
            return _dnac(console, intent, username)
        return _underlay(console, check, intent)
    except RuntimeError as error:
        return False, {"reason": str(error)}
