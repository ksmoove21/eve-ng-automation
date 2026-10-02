"""Validate and compile reusable Catalyst SD-WAN lab intent.

The compiler is deliberately offline.  It turns a private lab's semantic
`intent.yaml` into ordered, secret-free lifecycle and console operations.
Execution adapters consume this plan in later stages; no EVE or device state is
changed while compiling it.
"""

from ipaddress import IPv4Address, IPv4Interface, IPv4Network
from pathlib import Path
import re

import yaml


_TOKEN = re.compile(r"[A-Za-z0-9_.-]+\Z")
_INTERFACE = re.compile(r"[A-Za-z][A-Za-z0-9./-]*\Z")
_SECRET_KEYS = {"otp", "password", "token", "uuid", "chassis", "chassis_number"}
_TOP_LEVEL = {
    "version", "name", "organization_name", "control_plane",
    "transport_fabrics", "edges", "management", "acceptance",
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


def _address(value, name):
    try:
        result = IPv4Interface(value)
    except (TypeError, ValueError):
        raise ValueError(name + " must be an IPv4 interface") from None
    if result.ip in (result.network.network_address, result.network.broadcast_address):
        raise ValueError(name + " cannot use a network or broadcast address")
    return result


def _network(value, name):
    try:
        return IPv4Network(value, strict=True)
    except (TypeError, ValueError):
        raise ValueError(name + " must be a canonical IPv4 network") from None


def _ipv4(value, name):
    try:
        return IPv4Address(value)
    except (TypeError, ValueError):
        raise ValueError(name + " must be an IPv4 address") from None


def _reject_secrets(value, path="intent"):
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower().replace("-", "_") in _SECRET_KEYS:
                raise ValueError(path + " must not contain runtime identity or secret field " +
                                 repr(key))
            _reject_secrets(item, path + "." + str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secrets(item, path + f"[{index}]")


def _direct_links(topology):
    links = set()
    for item in topology.get("links", []):
        if not isinstance(item, dict) or "from" not in item or "to" not in item:
            continue
        left, right = item["from"], item["to"]
        if not isinstance(left, dict) or not isinstance(right, dict):
            continue
        links.add(frozenset(((left.get("node"), left.get("interface")),
                             (right.get("node"), right.get("interface")))))
    return links


def _linked(links, left_node, left_interface, right_node):
    return any((left_node, left_interface) in link and
               any(node == right_node for node, _ in link)
               for link in links)


def _peer_interface(links, node, peer):
    matches = [interface for link in links
               if any(endpoint[0] == node for endpoint in link)
               and any(endpoint[0] == peer for endpoint in link)
               for endpoint_node, interface in link if endpoint_node == node]
    if len(matches) != 1:
        raise ValueError(node + " must have one direct link to " + peer)
    return _interface(matches[0], node + ".vpn0_interface")


def _network_interface(topology, node, network):
    matches = [item.get("interface") for item in topology.get("links", [])
               if isinstance(item, dict) and item.get("node") == node
               and item.get("network") == network]
    if len(matches) != 1:
        raise ValueError(node + " must have one attachment to " + network)
    return _interface(matches[0], node + ".vpn512_interface")


def _node_map(topology):
    nodes = topology.get("nodes", [])
    if not isinstance(nodes, list):
        raise ValueError("Topology nodes must be a list")
    result = {}
    for node in nodes:
        if isinstance(node, dict) and isinstance(node.get("name"), str):
            result[node["name"]] = node
    return result


def _mask(interface):
    return str(interface.network.netmask)


def _prefix_parts(prefix):
    network = IPv4Network(prefix)
    return str(network.network_address), str(network.netmask)


def _tunnel_number(interface):
    match = re.search(r"(\d+)\Z", interface)
    if not match:
        raise ValueError("Cannot derive tunnel number from " + interface)
    return match.group(1)


def _dc1_commands(aggregation, components, links):
    node = aggregation["node"]
    controller_ports = []
    for component in components:
        matches = [next(endpoint for endpoint in link if endpoint[0] == node)
                   for link in links
                   if any(endpoint[0] == node for endpoint in link)
                   and any(endpoint[0] == component["name"] for endpoint in link)]
        if len(matches) != 1:
            raise ValueError(node + " must have one direct link to " + component["name"])
        controller_ports.append(matches[0][1])
    svi = aggregation["controller_svi"]
    svi_address = _address(svi["address"], "controller_svi.address")
    commands = ["hostname " + node, "ip routing", "vlan 10",
                "name SDWAN-CONTROLLERS", "exit"]
    for port in controller_ports:
        commands += ["interface " + _interface(port, "controller link interface"),
                     "switchport mode access", "switchport access vlan 10",
                     "no shutdown", "exit"]
    commands += ["interface " + _interface(svi["interface"], "controller_svi.interface"),
                 "ip address " + str(svi_address.ip) + " " + _mask(svi_address),
                 "no shutdown", "exit"]
    for transport in aggregation["transports"].values():
        address = _address(transport["address"], "aggregation transport address")
        commands += ["interface " + _interface(transport["interface"],
                                                "aggregation transport interface"),
                     "no switchport",
                     "ip address " + str(address.ip) + " " + _mask(address),
                     "no shutdown", "exit"]
    return commands


def _edge_commands(edge, organization, vbond):
    identity = [
        "logging console critical",
        "hostname " + edge["hostname"],
        "system",
        "system-ip " + edge["system_ip"],
        "site-id " + str(edge["site_id"]),
        "organization-name " + organization,
        "vbond " + str(vbond),
        "exit",
    ]
    transport = []
    for item in edge["transports"]:
        address = IPv4Interface(item["address"])
        tunnel = "Tunnel" + _tunnel_number(item["interface"])
        transport += [
            "interface " + item["interface"],
            "no shutdown",
            "ip address " + str(address.ip) + " " + _mask(address),
            "exit",
            "interface " + tunnel,
            "no shutdown",
            "ip unnumbered " + item["interface"],
            "tunnel source " + item["interface"],
            "tunnel mode sdwan",
            "exit",
            "sdwan",
            "interface " + item["interface"],
            "tunnel-interface",
            "encapsulation ipsec",
            "color " + item["color"],
            "allow-service all",
            "exit",
            "exit",
            "exit",
        ]
    for route in edge["controller_routes"]:
        address, mask = _prefix_parts(route["prefix"])
        transport.append("ip route " + address + " " + mask + " " + route["next_hop"])
    return identity, transport


def _bridge_commands(fabric):
    commands = ["hostname " + fabric["name"]]
    for interface in fabric["member_interfaces"]:
        commands += [
            "interface " + interface,
            "no ip address",
            "no shutdown",
            "service instance 1 ethernet",
            "encapsulation untagged",
            "bridge-domain " + str(fabric["bridge_domain"]),
            "exit",
            "exit",
        ]
    return commands


def _control_operations(component, organization, vbond, color,
                        vpn0_interface, vpn512_interface,
                        management_address, management_gateway):
    transport = _address(component["vpn0_address"], component["name"] + ".vpn0_address")
    management = _address(management_address, component["name"] + ".vpn512_address")
    identity = [
        "system",
        "host-name " + component["hostname"],
        "system-ip " + component["system_ip"],
        "site-id " + str(component["site_id"]),
        'organization-name "' + organization + '"',
    ]
    if component["personality"] == "validator":
        identity.append("vbond " + str(transport.ip) + " local")
    else:
        identity.append("vbond " + str(vbond))
    identity += ["clock timezone UTC", "exit"]
    vpn0 = ["vpn 0"]
    vpn0.append("no interface " + vpn512_interface)
    vpn0 += [
        "interface " + vpn0_interface,
        "ip address " + str(transport),
        "tunnel-interface",
    ]
    if component["personality"] == "validator":
        vpn0.append("encapsulation ipsec")
    if component["personality"] != "manager":
        # 20.15.1 control appliances can retain the detailed default denies
        # while ``allow-service all`` is present.  Remove that override and
        # make Manager enrollment (NETCONF/830) and recovery (SSH) explicit.
        vpn0.extend(("no allow-service all", "allow-service netconf",
                     "allow-service sshd"))
    vpn0.append("color " + color)
    if component["personality"] == "manager":
        vpn0.append("allow-service all")
    vpn0 += [
        "exit",
        "no shutdown",
        "exit",
        "ip route 0.0.0.0/0 " + component["vpn0_gateway"],
        "exit",
    ]
    vpn512 = [
        "vpn 512",
        "interface " + vpn512_interface,
        "ip address " + str(management),
        "no shutdown",
        "exit",
        "ip route 0.0.0.0/0 " + str(management_gateway),
        "exit",
    ]
    return [
        {"name": "identity", "mode": "config-transaction",
         "commands": identity, "commit": True},
        {"name": "vpn0", "mode": "config-transaction",
         "commands": vpn0, "commit": True},
        {"name": "vpn512", "mode": "config-transaction",
         "commands": vpn512, "commit": True},
    ]


def compile_intent(intent, topology):
    """Return a deterministic secret-free execution plan."""
    _mapping(intent, "intent", _TOP_LEVEL)
    _reject_secrets(intent)
    if intent.get("version") != 1:
        raise ValueError("SD-WAN intent version must be 1")
    lab = _token(intent.get("name"), "intent.name")
    if topology.get("name") != lab:
        raise ValueError("SD-WAN intent name must match topology name")
    organization = intent.get("organization_name")
    if not isinstance(organization, str) or not organization.strip() or "\n" in organization:
        raise ValueError("organization_name must be a nonempty single-line string")

    nodes = _node_map(topology)
    links = _direct_links(topology)
    control = _mapping(intent.get("control_plane"), "control_plane",
                       {"site_id", "service_network", "vbond_address", "transport_color",
                        "aggregation", "components"})
    service_network = _network(control.get("service_network"), "control_plane.service_network")
    vbond = _ipv4(control.get("vbond_address"), "control_plane.vbond_address")
    transport_color = _token(control.get("transport_color"),
                             "control_plane.transport_color")
    if type(control.get("site_id")) is not int:
        raise ValueError("control_plane.site_id must be an integer")
    aggregation = _mapping(control.get("aggregation"), "control_plane.aggregation",
                           {"node", "controller_svi", "transports"})
    aggregate_name = _token(aggregation.get("node"), "aggregation.node")
    if nodes.get(aggregate_name, {}).get("template") != "viosl2":
        raise ValueError("Aggregation node must be a declared viosl2 node")
    _mapping(aggregation.get("controller_svi"), "aggregation.controller_svi",
             {"interface", "address"})
    transports = _mapping(aggregation.get("transports"), "aggregation.transports")
    components = _sequence(control.get("components"), "control_plane.components")
    personalities = set()
    for item in components:
        _mapping(item, "control component",
                 {"name", "personality", "hostname", "system_ip", "site_id",
                  "vpn0_address", "vpn0_gateway"})
        name = _token(item.get("name"), "component.name")
        if name not in nodes:
            raise ValueError("Control component is not declared in topology: " + name)
        personality = item.get("personality")
        if personality not in {"manager", "validator", "controller"}:
            raise ValueError("Unsupported control component personality")
        personalities.add(personality)
        _ipv4(item.get("system_ip"), name + ".system_ip")
        vpn0 = _address(item.get("vpn0_address"), name + ".vpn0_address")
        if vpn0.network != service_network:
            raise ValueError(name + " VPN 0 address is outside the controller network")
        if _ipv4(item.get("vpn0_gateway"), name + ".vpn0_gateway") != IPv4Interface(
                aggregation["controller_svi"]["address"]).ip:
            raise ValueError(name + " VPN 0 gateway must be the aggregation SVI")
    if personalities != {"manager", "validator", "controller"}:
        raise ValueError("Exactly manager, validator, and controller personalities are required")

    fabrics = _sequence(intent.get("transport_fabrics"), "transport_fabrics")
    fabric_by_color = {}
    fabric_by_name = {}
    bridge_domains = set()
    for fabric in fabrics:
        _mapping(fabric, "transport fabric",
                 {"name", "color", "subnet", "mode", "bridge_domain",
                  "gateway", "member_interfaces"})
        name = _token(fabric.get("name"), "fabric.name")
        color = _token(fabric.get("color"), "fabric.color")
        if name in fabric_by_name or color in fabric_by_color:
            raise ValueError("Transport fabric names and colors must be unique")
        if nodes.get(name, {}).get("template") != "iol":
            raise ValueError(name + " must be a declared native IOL node")
        subnet = _network(fabric.get("subnet"), name + ".subnet")
        if subnet.prefixlen != 24:
            raise ValueError(name + " must preserve its declared /24")
        if fabric.get("mode") != "transparent_bridge":
            raise ValueError(name + " must use transparent_bridge mode")
        bridge_domain = fabric.get("bridge_domain")
        if type(bridge_domain) is not int or not 1 <= bridge_domain <= 4094:
            raise ValueError(name + " bridge_domain must be an integer from 1 to 4094")
        if bridge_domain in bridge_domains:
            raise ValueError("Transport bridge_domain values must be unique")
        bridge_domains.add(bridge_domain)
        gateway = _mapping(fabric.get("gateway"), name + ".gateway",
                           {"node", "interface", "address"})
        if gateway.get("node") != aggregate_name:
            raise ValueError(name + " gateway owner must be the aggregation node")
        gateway_address = _address(gateway.get("address"), name + ".gateway.address")
        if gateway_address.network != subnet:
            raise ValueError(name + " gateway address is outside its transport subnet")
        aggregate_matches = [
            item for item in transports.values()
            if isinstance(item, dict) and item == {
                "interface": gateway.get("interface"),
                "address": gateway.get("address"),
            }
        ]
        if len(aggregate_matches) != 1:
            raise ValueError(name + " gateway must match aggregation transport " + color)
        if not _linked(links, aggregate_name, gateway["interface"], name):
            raise ValueError(name + " gateway interface is not linked to the fabric node")
        members = _sequence(fabric.get("member_interfaces"), name + ".member_interfaces")
        if len(set(members)) != len(members):
            raise ValueError(name + " member interfaces must be unique")
        for member in members:
            _interface(member, name + ".member_interface")
        fabric_by_name[name] = {**fabric, "network": subnet,
                                "gateway_ip": gateway_address.ip}
        fabric_by_color[color] = fabric_by_name[name]

    edge_plans = {}
    switch_plans = {}
    used_transport_ips = set()
    edges = _sequence(intent.get("edges"), "edges")
    for edge in edges:
        _mapping(edge, "edge",
                 {"name", "hostname", "system_ip", "site_id", "transports",
                  "controller_routes", "service"})
        name = _token(edge.get("name"), "edge.name")
        if nodes.get(name, {}).get("template") != "c8000v":
            raise ValueError(name + " must be a declared c8000v node")
        _token(edge.get("hostname"), name + ".hostname")
        _ipv4(edge.get("system_ip"), name + ".system_ip")
        if type(edge.get("site_id")) is not int or not 0 <= edge["site_id"] <= 4294967295:
            raise ValueError(name + ".site_id must be an SD-WAN site integer")
        edge_transports = _sequence(edge.get("transports"), name + ".transports")
        if {item.get("color") for item in edge_transports
                if isinstance(item, dict)} != set(fabric_by_color):
            raise ValueError(name + " must have exactly one transport for every fabric color")
        normalized_transports = []
        for item in edge_transports:
            _mapping(item, name + ".transport", {"interface", "address", "color"})
            interface = _interface(item.get("interface"), name + ".transport.interface")
            fabric = fabric_by_color[item.get("color")]
            address = _address(item.get("address"), name + ".transport.address")
            if address.network != fabric["network"] or address.ip == fabric["gateway_ip"]:
                raise ValueError(name + " transport address does not match its shared fabric")
            if address.ip in used_transport_ips:
                raise ValueError("Duplicate transport address: " + str(address.ip))
            used_transport_ips.add(address.ip)
            if not _linked(links, name, interface, fabric["name"]):
                raise ValueError(name + " transport interface is not linked to " + fabric["name"])
            normalized_transports.append({**item, "address": str(address)})
        routes = _sequence(edge.get("controller_routes"), name + ".controller_routes")
        expected_routes = {(str(service_network), str(fabric["gateway_ip"]))
                           for fabric in fabric_by_name.values()}
        actual_routes = set()
        for route in routes:
            _mapping(route, name + ".controller_route", {"prefix", "next_hop"})
            actual_routes.add((str(_network(route.get("prefix"), name + ".route.prefix")),
                               str(_ipv4(route.get("next_hop"), name + ".route.next_hop"))))
        if actual_routes != expected_routes:
            raise ValueError(name + " must route the controller network through every DC1 gateway")
        service = _mapping(edge.get("service"), name + ".service",
                           {"vpn", "interface", "address", "switch", "switch_address"})
        if type(service.get("vpn")) is not int or service["vpn"] in (0, 512):
            raise ValueError(name + ".service.vpn must be a nonreserved integer")
        service_interface = _interface(service.get("interface"), name + ".service.interface")
        switch = _token(service.get("switch"), name + ".service.switch")
        if nodes.get(switch, {}).get("template") != "viosl2":
            raise ValueError(name + " service switch must be a declared viosl2 node")
        if not _linked(links, name, service_interface, switch):
            raise ValueError(name + " service interface is not linked to " + switch)
        service_address = _address(service.get("address"), name + ".service.address")
        switch_address = _address(service.get("switch_address"),
                                  name + ".service.switch_address")
        if service_address.network != switch_address.network:
            raise ValueError(name + " edge and switch service addresses must share a subnet")
        normalized = {**edge, "transports": normalized_transports}
        identity_commands, transport_commands = _edge_commands(
            normalized, organization, vbond)
        service_commands = [
            "vrf definition " + str(service["vpn"]),
            "address-family ipv4",
            "exit-address-family",
            "exit",
            "interface " + service_interface,
            "vrf forwarding " + str(service["vpn"]),
            "ip address " + str(service_address.ip) + " " + _mask(service_address),
            "no shutdown",
            "exit",
        ]
        edge_plans[name] = {
            "adapter": "c8000v-sdwan",
            "operations": [
                {"name": "controller-mode", "mode": "privileged-exec",
                 "command": "controller-mode enable", "confirm_reboot": True,
                 "one_shot": True},
                {"name": "identity", "mode": "config-transaction",
                 "commands": identity_commands, "commit": True},
                {"name": "transport", "mode": "config-transaction",
                 "commands": transport_commands, "commit": True},
                {"name": "service-lan", "mode": "config-transaction",
                 "commands": service_commands, "commit": True},
                {"name": "underlay-validation", "read_only": True,
                 "destinations": [str(component["vpn0_address"]).split("/")[0]
                                  for component in components]},
                {"name": "root-trust", "source": "manager-local-ca",
                 "require_nonzero": True, "require_parseable_pem": True,
                 "require_source_match": True},
                {"name": "payg-activation", "provider": "manager",
                 "correlate_before_use": True, "one_shot": True},
                {"name": "control-validation", "read_only": True,
                 "peers": ["validator", "manager", "controller"]},
            ],
            "desired": {
                "hostname": edge["hostname"], "system_ip": edge["system_ip"],
                "site_id": edge["site_id"], "organization_name": organization,
                "vbond": str(vbond), "transports": normalized_transports,
                "controller_routes": routes, "service": service,
            },
        }
        switch_plans[switch] = {
            "adapter": "ios-config",
            "commands": [
                "hostname " + switch,
                "interface GigabitEthernet0/0",
                "switchport mode access",
                "switchport access vlan 1",
                "no shutdown",
                "exit",
                "interface Vlan1",
                "ip address " + str(switch_address.ip) + " " + _mask(switch_address),
                "no shutdown",
                "exit",
                "ip default-gateway " + str(service_address.ip),
            ],
        }

    acceptance = _mapping(intent.get("acceptance"), "acceptance",
                          {"forbid_transport_prefixes", "require_dual_controller_routes",
                           "require_gateway_owner", "require_only_visible_network"})
    if acceptance.get("require_gateway_owner") != aggregate_name:
        raise ValueError("acceptance.require_gateway_owner must match aggregation")
    if acceptance.get("require_dual_controller_routes") is not True:
        raise ValueError("acceptance must require dual controller routes")
    management = _mapping(intent.get("management"), "management",
                          {"network", "vpn", "addressing_source", "pool",
                           "gateway", "assignments"})
    if management.get("vpn") != 512:
        raise ValueError("Management network must use VPN 512")
    if management.get("network") != acceptance.get("require_only_visible_network"):
        raise ValueError("Management network must be the sole visible network")
    if not isinstance(management.get("addressing_source"), str) or not management["addressing_source"]:
        raise ValueError("Management addressing_source must be nonempty")
    management_pool = _network(management.get("pool"), "management.pool")
    if management_pool.prefixlen != 24:
        raise ValueError("Management pool must preserve its approved /24")
    management_gateway = _ipv4(management.get("gateway"), "management.gateway")
    if management_gateway not in management_pool:
        raise ValueError("Management gateway is outside the management pool")
    assignments = _mapping(management.get("assignments"), "management.assignments")
    managed_names = {component["name"] for component in components} | {
        edge["name"] for edge in edges}
    if set(assignments) != managed_names:
        raise ValueError("Management assignments must exactly cover controllers and edges")
    normalized_management = {}
    used_management_ips = set()
    for name, value in assignments.items():
        address = _address(value, "management.assignments." + name)
        if address.network != management_pool or address.ip == management_gateway:
            raise ValueError(name + " management address does not match the approved pool")
        if address.ip in used_management_ips:
            raise ValueError("Duplicate management address: " + str(address.ip))
        used_management_ips.add(address.ip)
        normalized_management[name] = str(address)
        _network_interface(topology, name, management["network"])
    visible_networks = {item.get("name") for item in topology.get("networks", [])
                        if isinstance(item, dict)}
    if visible_networks != {management["network"]}:
        raise ValueError("Topology must declare only the management visible network")

    control_plans = {}
    for component in components:
        name = component["name"]
        vpn0_interface = _peer_interface(links, name, aggregate_name)
        vpn512_interface = _network_interface(
            topology, name, management["network"])
        required_interfaces = {
            "manager": ("eth1", "eth0"),
            "validator": ("ge0/0", "eth0"),
            "controller": ("eth1", "eth0"),
        }[component["personality"]]
        if (vpn0_interface, vpn512_interface) != required_interfaces:
            raise ValueError(
                name + " must use appliance transport/management interfaces "
                + required_interfaces[0] + "/" + required_interfaces[1])
        control_plans[name] = {
            "adapter": "viptela-control",
            "personality": component["personality"],
            "operations": _control_operations(
                component, organization, vbond, transport_color,
                vpn0_interface, vpn512_interface,
                normalized_management[name], management_gateway),
            "desired": {
                "hostname": component["hostname"],
                "system_ip": component["system_ip"],
                "site_id": component["site_id"],
                "organization_name": organization,
                "vbond": str(vbond),
                "vpn0_interface": vpn0_interface,
                "vpn0_address": component["vpn0_address"],
                "vpn512_interface": vpn512_interface,
                "vpn512_address": normalized_management[name],
                "management_gateway": str(management_gateway),
            },
        }
    for name, plan in edge_plans.items():
        plan["desired"]["vpn512_interface"] = _network_interface(
            topology, name, management["network"])
        plan["desired"]["vpn512_address"] = normalized_management[name]
        plan["desired"]["management_gateway"] = str(management_gateway)

    node_operations = {
        aggregate_name: {
            "adapter": "ios-config",
            "commands": _dc1_commands(aggregation, components, links),
        },
    }
    for fabric in fabric_by_name.values():
        node_operations[fabric["name"]] = {
            "adapter": "ios-transparent-bridge",
            "commands": _bridge_commands(fabric),
            "capability_gate": {
                "classification": "FIELD_PROVEN",
                "image": nodes[fabric["name"]]["image"],
                "member_interfaces": fabric["member_interfaces"],
                "desired_state": "one unnumbered transparent broadcast domain",
            },
            "validation": {
                "type": "iosxe-transparent-bridge",
                "bridge_domain": fabric["bridge_domain"],
                "service_instance": 1,
                "interfaces": fabric["member_interfaces"],
            },
        }
    node_operations.update(switch_plans)
    node_operations.update(control_plans)
    node_operations.update(edge_plans)

    return {
        "schema": 1,
        "lab": lab,
        "sequence": [
            "transport-underlay",
            "manager-install-and-baseline",
            "manager-enterprise-ca-and-certificate",
            "validator-baseline-certificate",
            "controller-baseline-certificate",
            "control-fabric-validation",
            "payg-correlation",
            "edge-controller-mode-cli-baseline-root-trust-activation",
            "multi-edge-control-validation",
            "destroyed-state-rebuild",
        ],
        "node_operations": node_operations,
        "safety": {
            "contains_secrets": False,
            "payg_activation_one_shot": True,
            "controller_mode_one_shot": True,
            "transport_prefixes": sorted(str(item["network"])
                                         for item in fabric_by_name.values()),
        },
    }


def load_and_compile(root, lab, topology):
    path = (Path(root) / "labs" / lab / "intent.yaml").resolve()
    base = (Path(root) / "labs" / lab).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise ValueError("Missing SD-WAN intent: labs/" + lab + "/intent.yaml")
    document = yaml.safe_load(path.read_text())
    if not isinstance(document, dict):
        raise ValueError("SD-WAN intent must be a mapping")
    return compile_intent(document, topology)
