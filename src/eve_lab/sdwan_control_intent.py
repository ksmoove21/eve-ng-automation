"""Compile controller-only Catalyst SD-WAN intent without topology synthesis."""

from ipaddress import IPv4Address, IPv4Interface
from pathlib import Path
import re

import yaml


_TOKEN = re.compile(r"[A-Za-z0-9_.-]+\Z")
_INTERFACE = re.compile(r"[A-Za-z][A-Za-z0-9./-]*\Z")
_SECRET_KEYS = {"otp", "password", "token", "uuid", "chassis", "chassis_number"}
_UNSAFE_KEYS = {"command", "commands", "operation", "operations"}
_TOP_LEVEL = {"version", "name", "organization_name", "vbond_address", "controllers"}
_PERSONALITIES = {"manager", "validator", "controller"}
_APPLIANCES = {
    "manager": ("vtmgmt", "vtmgmt-20.15.1"),
    "validator": ("vtbond", "vtbond-20.15.1"),
    "controller": ("vtsmart", "vtsmart-20.15.1"),
}


def _mapping(value, name, allowed=None):
    if not isinstance(value, dict):
        raise ValueError(name + " must be a mapping")
    if allowed is not None and set(value) - set(allowed):
        raise ValueError(name + " contains unsupported fields: " +
                         ", ".join(sorted(set(value) - set(allowed))))
    return value


def _sequence(value, name):
    if not isinstance(value, list) or not value:
        raise ValueError(name + " must be a nonempty list")
    return value


def _token(value, name):
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise ValueError(name + " must be a safe nonempty token")
    return value


def _interface(value, name):
    if not isinstance(value, str) or not _INTERFACE.fullmatch(value):
        raise ValueError(name + " must be a safe interface name")
    return value


def _network_name(value, name):
    if (not isinstance(value, str) or not value.strip()
            or "\n" in value or "\r" in value):
        raise ValueError(name + " must be a nonempty single-line topology network name")
    return value


def _address(value, name):
    try:
        result = IPv4Interface(value)
    except (TypeError, ValueError):
        raise ValueError(name + " must be an IPv4 interface") from None
    if result.ip in (result.network.network_address, result.network.broadcast_address):
        raise ValueError(name + " cannot use a network or broadcast address")
    return result


def _ipv4(value, name):
    try:
        return IPv4Address(value)
    except (TypeError, ValueError):
        raise ValueError(name + " must be an IPv4 address") from None



def _gateway(address, gateway, name):
    if gateway not in address.network or gateway in (
            address.network.network_address, address.network.broadcast_address):
        raise ValueError(name + " must be a usable address in the interface subnet")
    if gateway == address.ip:
        raise ValueError(name + " must differ from the interface address")


def _reject_unsafe(value, path="intent"):
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in _SECRET_KEYS:
                raise ValueError(path + " must not contain runtime identity or secret field " +
                                 repr(key))
            if normalized in _UNSAFE_KEYS:
                raise ValueError(path + " must not contain generated command field " + repr(key))
            _reject_unsafe(item, path + "." + str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_unsafe(item, path + f"[{index}]")


def _nodes(topology):
    nodes = topology.get("nodes", [])
    if not isinstance(nodes, list):
        raise ValueError("Topology nodes must be a list")
    result = {}
    for item in nodes:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError("Topology nodes must have names")
        if item["name"] in result:
            raise ValueError("Topology contains duplicate node: " + item["name"])
        result[item["name"]] = item
    return result


def _direct_link(topology, node, interface, peer_node, peer_interface):
    wanted = {(node, interface), (peer_node, peer_interface)}
    matches = []
    for item in topology.get("links", []):
        if not isinstance(item, dict) or set(item) & {"network", "node"}:
            continue
        left, right = item.get("from"), item.get("to")
        if not isinstance(left, dict) or not isinstance(right, dict):
            continue
        endpoints = {(left.get("node"), left.get("interface")),
                     (right.get("node"), right.get("interface"))}
        if endpoints == wanted:
            matches.append(item)
    if len(matches) != 1:
        raise ValueError(node + " transport must match one explicit direct link to " + peer_node)


def _network_attachment(topology, node, interface, network):
    matches = [item for item in topology.get("links", [])
               if isinstance(item, dict)
               and item.get("node") == node
               and item.get("interface") == interface
               and item.get("network") == network]
    if len(matches) != 1:
        raise ValueError(node + " management must match one explicit " +
                         network + " attachment")
    declared = {item.get("name") for item in topology.get("networks", [])
                if isinstance(item, dict)}
    if network not in declared:
        raise ValueError(node + " management attachment must reference a declared topology network")


def _operations(component, organization, vbond):
    transport = component["transport"]
    transport_address = transport["address"]
    identity = [
        "system",
        "host-name " + component["hostname"],
        "system-ip " + str(component["system_ip"]),
        "site-id " + str(component["site_id"]),
        'organization-name "' + organization + '"',
    ]
    if component["personality"] == "validator":
        identity.append("vbond " + str(transport_address.ip) + " local")
    else:
        identity.append("vbond " + str(vbond))
    identity += ["clock timezone UTC", "exit"]

    vpn0 = ["vpn 0"]
    if component.get("management") is not None:
        vpn0.append("no interface " + component["management"]["interface"])
    vpn0 += ["interface " + transport["interface"],
             "no ip dhcp-client", "no ipv6 dhcp-client",
             "ip address " + str(transport_address), "tunnel-interface"]
    if component["personality"] == "validator":
        vpn0.append("encapsulation ipsec")
    if component["personality"] == "manager":
        vpn0.append("allow-service all")
    else:
        vpn0.extend(("no allow-service all", "allow-service netconf", "allow-service sshd"))
    vpn0 += ["color " + transport["color"], "exit", "no shutdown", "exit",
             "ip route 0.0.0.0/0 " + str(transport["gateway"]), "exit"]
    operations = [
        {"name": "identity", "mode": "config-transaction",
         "commands": identity, "commit": True},
        {"name": "vpn0", "mode": "config-transaction",
         "commands": vpn0, "commit": True},
    ]
    management = component.get("management")
    if management is not None:
        address = management["address"]
        operations.append({
            "name": "vpn512", "mode": "config-transaction",
            "commands": [
                "vpn 512", "interface " + management["interface"],
                "ip address " + str(address), "no shutdown", "exit",
                "ip route 0.0.0.0/0 " + str(management["gateway"]), "exit",
            ],
            "commit": True,
        })
    return operations


def compile_intent(intent, topology):
    """Return a secret-free controller-only plan tied to explicit topology."""
    _mapping(intent, "intent", _TOP_LEVEL)
    _reject_unsafe(intent)
    if intent.get("version") != 1:
        raise ValueError("Controller intent version must be 1")
    lab = _token(intent.get("name"), "intent.name")
    if topology.get("name") != lab:
        raise ValueError("Controller intent name must match topology name")
    organization = intent.get("organization_name")
    if (not isinstance(organization, str) or not organization.strip()
            or "\n" in organization or "\r" in organization or '"' in organization):
        raise ValueError("organization_name must be a safe nonempty single-line string")
    vbond = _ipv4(intent.get("vbond_address"), "vbond_address")
    nodes = _nodes(topology)
    controllers = _sequence(intent.get("controllers"), "controllers")
    names = set()
    hostnames = set()
    system_ips = set()
    transport_ips = set()
    management_ips = set()
    used_interfaces = set()
    plans = {}
    for item in controllers:
        _mapping(item, "controller", {"name", "personality", "hostname", "system_ip",
                                       "site_id", "transport", "management"})
        name = _token(item.get("name"), "controller.name")
        if name in names:
            raise ValueError("Duplicate controller name: " + name)
        names.add(name)
        if name not in nodes:
            raise ValueError("Controller is not declared in topology: " + name)
        personality = item.get("personality")
        if personality not in _PERSONALITIES:
            raise ValueError("Unsupported controller personality")
        expected_template, expected_image = _APPLIANCES[personality]
        if (nodes[name].get("template"), nodes[name].get("image")) != (
                expected_template, expected_image):
            raise ValueError(name + " must declare " + expected_template +
                             " image " + expected_image)
        hostname = _token(item.get("hostname"), name + ".hostname")
        if hostname in hostnames:
            raise ValueError("Duplicate controller hostname: " + hostname)
        hostnames.add(hostname)
        system_ip = _ipv4(item.get("system_ip"), name + ".system_ip")
        if system_ip in system_ips:
            raise ValueError("Duplicate controller system_ip: " + str(system_ip))
        system_ips.add(system_ip)
        site_id = item.get("site_id")
        if type(site_id) is not int or not 1 <= site_id <= 4294967295:
            raise ValueError(name + ".site_id must be a positive SD-WAN site integer")
        raw_transport = _mapping(item.get("transport"), name + ".transport",
                                 {"interface", "address", "gateway", "color", "peer"})
        interface = _interface(raw_transport.get("interface"), name + ".transport.interface")
        address = _address(raw_transport.get("address"), name + ".transport.address")
        gateway = _ipv4(raw_transport.get("gateway"), name + ".transport.gateway")
        _gateway(address, gateway, name + ".transport.gateway")
        color = _token(raw_transport.get("color"), name + ".transport.color")
        peer = _mapping(raw_transport.get("peer"), name + ".transport.peer",
                        {"node", "interface"})
        peer_name = _token(peer.get("node"), name + ".transport.peer.node")
        peer_interface = _interface(peer.get("interface"), name + ".transport.peer.interface")
        if peer_name not in nodes:
            raise ValueError(name + " transport peer is not declared in topology: " + peer_name)
        _direct_link(topology, name, interface, peer_name, peer_interface)
        if address.ip in transport_ips:
            raise ValueError("Duplicate controller transport address: " + str(address.ip))
        transport_ips.add(address.ip)
        if (name, interface) in used_interfaces:
            raise ValueError("Duplicate controller interface: " + name + "." + interface)
        used_interfaces.add((name, interface))
        component = {"name": name, "personality": personality, "hostname": hostname,
                     "system_ip": system_ip, "site_id": site_id,
                     "transport": {"interface": interface, "address": address,
                                   "gateway": gateway, "color": color,
                                   "peer": {"node": peer_name, "interface": peer_interface}}}
        if item.get("management") is not None:
            raw_management = _mapping(item["management"], name + ".management",
                                      {"network", "interface", "address", "gateway"})
            network = _network_name(raw_management.get("network"), name + ".management.network")
            management_interface = _interface(raw_management.get("interface"),
                                              name + ".management.interface")
            management_address = _address(raw_management.get("address"),
                                          name + ".management.address")
            management_gateway = _ipv4(raw_management.get("gateway"),
                                       name + ".management.gateway")
            _gateway(management_address, management_gateway, name + ".management.gateway")
            if management_address.ip in management_ips:
                raise ValueError("Duplicate controller management address: " +
                                 str(management_address.ip))
            management_ips.add(management_address.ip)
            if (name, management_interface) in used_interfaces:
                raise ValueError("Duplicate controller interface: " + name + "." +
                                 management_interface)
            used_interfaces.add((name, management_interface))
            _network_attachment(topology, name, management_interface, network)
            component["management"] = {"network": network, "interface": management_interface,
                                        "address": management_address,
                                        "gateway": management_gateway}
        plans[name] = {
            "adapter": "viptela-control", "personality": personality,
            "operations": _operations(component, organization, vbond),
            "desired": {
                "hostname": hostname, "system_ip": str(system_ip), "site_id": site_id,
                "organization_name": organization, "vbond": str(vbond),
                "vpn0_interface": interface, "vpn0_address": str(address),
                "vpn0_gateway": str(gateway), "transport_color": color,
            },
        }
        if "management" in component:
            management = component["management"]
            plans[name]["desired"].update({
                "vpn512_interface": management["interface"],
                "vpn512_address": str(management["address"]),
                "management_gateway": str(management["gateway"]),
                "management_network": management["network"],
            })
    return {"schema": 1, "lab": lab, "node_operations": plans,
            "safety": {"contains_secrets": False, "topology_synthesized": False}}


def load_and_compile(root, lab, topology):
    """Load controller-only intent next to an explicit lab topology."""
    if not isinstance(lab, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", lab):
        raise ValueError("Invalid controller lab name")
    path = (Path(root) / "labs" / lab / "controller-intent.yaml").resolve()
    base = (Path(root) / "labs" / lab).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise ValueError("Missing controller intent: labs/" + lab + "/controller-intent.yaml")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("Controller intent must be a mapping")
    return compile_intent(document, topology)
