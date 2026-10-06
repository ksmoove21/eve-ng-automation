"""Compile topology-bound, secret-free c8000v Catalyst SD-WAN edge intent."""

from ipaddress import IPv4Address, IPv4Interface, IPv4Network
import re

from .sdwan_edge import stages_from_edge_plan


_TOKEN = re.compile(r"[A-Za-z0-9_.-]+\Z")
_DECLARED_INTERFACE = re.compile(r"(?:Gi|GigabitEthernet)([1-9][0-9]*)\Z")
_SECRET_KEYS = {"token", "otp", "password", "chassis", "chassis_number",
                "uuid", "serial", "bootstrap"}
_ALLOWED = {"version", "organization_name", "vbond_address",
            "controller_transport_prefix", "edges"}
_EDGE = {"name", "hostname", "system_ip", "site_id", "transport", "transports",
         "service_interfaces"}
_TRANSPORT = {"interface", "address", "gateway", "color", "peer", "distance"}
_SERVICE = {"vpn", "interface", "address", "peer"}


def _mapping(value, label, allowed):
    if not isinstance(value, dict):
        raise ValueError(label + " must be a mapping")
    if set(value) - allowed:
        raise ValueError(label + " contains unsupported fields")
    return value


def _token(value, label):
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise ValueError(label + " must be a safe token")
    return value


def _ipv4(value, label):
    try:
        return IPv4Address(value)
    except (TypeError, ValueError):
        raise ValueError(label + " must be an IPv4 address") from None


def _address(value, label):
    try:
        result = IPv4Interface(value)
    except (TypeError, ValueError):
        raise ValueError(label + " must be an IPv4 interface") from None
    if result.ip in (result.network.network_address, result.network.broadcast_address):
        raise ValueError(label + " cannot use network or broadcast")
    return result


def _network(value, label):
    try:
        return IPv4Network(value, strict=True)
    except (TypeError, ValueError):
        raise ValueError(label + " must be a canonical IPv4 network") from None


def _command_interface(value, label):
    if not isinstance(value, str):
        raise ValueError(label + " must be a c8000v Ethernet interface")
    match = _DECLARED_INTERFACE.fullmatch(value)
    if not match:
        raise ValueError(label + " must be GiN or GigabitEthernetN")
    return "GigabitEthernet" + match.group(1)


def _reject_runtime(value, path="intent"):
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower().replace("-", "_") in _SECRET_KEYS:
                raise ValueError(path + " must not contain runtime secret or identity field")
            _reject_runtime(item, path + "." + str(key))
    elif isinstance(value, list):
        for item in value:
            _reject_runtime(item, path)


def _node_map(topology):
    if not isinstance(topology, dict) or not isinstance(topology.get("nodes"), list):
        raise ValueError("topology.nodes must be a list")
    result = {}
    for node in topology["nodes"]:
        if not isinstance(node, dict) or not isinstance(node.get("name"), str):
            raise ValueError("topology node must have a name")
        if node["name"] in result:
            raise ValueError("topology node names must be unique")
        result[node["name"]] = node
    return result


def _peer(value, label, nodes):
    item = _mapping(value, label, {"node", "interface"})
    node = _token(item.get("node"), label + ".node")
    if node not in nodes:
        raise ValueError(label + ".node is not declared")
    interface = item.get("interface")
    if not isinstance(interface, str) or not interface:
        raise ValueError(label + ".interface is required")
    return {"node": node, "interface": interface}


def _direct_link(topology, node, declared_interface, peer):
    matches, shared = [], False
    for link in topology.get("links", []):
        if not isinstance(link, dict):
            continue
        if link.get("node") == node and link.get("interface") == declared_interface:
            shared = shared or "network" in link
        left, right = link.get("from"), link.get("to")
        if not isinstance(left, dict) or not isinstance(right, dict):
            continue
        endpoints = ((left.get("node"), left.get("interface")),
                     (right.get("node"), right.get("interface")))
        if (node, declared_interface) in endpoints:
            matches.append(right if endpoints[0] == (node, declared_interface) else left)
    if shared:
        raise ValueError(node + "." + declared_interface + " must not use a shared network")
    if len(matches) != 1:
        raise ValueError(node + "." + declared_interface + " must have one direct link")
    if matches[0].get("node") != peer["node"] or matches[0].get("interface") != peer["interface"]:
        raise ValueError(node + "." + declared_interface + " must use its declared direct peer")


def _mask(address):
    return str(address.network.netmask)


def _identity(hostname, system, site, organization, vbond):
    return ["logging console critical", "hostname " + hostname, "system",
            "system-ip " + str(system), "site-id " + str(site),
            "organization-name " + organization, "vbond " + str(vbond), "exit"]


def _operation(name, commands):
    return {"name": name, "mode": "config-transaction",
            "commands": commands, "commit": True}


def compile_edge_intent(intent, topology):
    """Return secret-free plans; omit service-lan until it is declared."""
    _mapping(intent, "intent", _ALLOWED)
    _reject_runtime(intent)
    if intent.get("version") != 1:
        raise ValueError("intent.version must be 1")
    organization = _token(intent.get("organization_name"), "organization_name")
    vbond = _ipv4(intent.get("vbond_address"), "vbond_address")
    controller_prefix = _network(intent.get("controller_transport_prefix"),
                                 "controller_transport_prefix")
    edges = intent.get("edges")
    if not isinstance(edges, list) or not edges:
        raise ValueError("edges must be a nonempty list")
    nodes = _node_map(topology)
    systems, hostnames, names, addresses, plans = set(), set(), set(), set(), {}
    for raw in edges:
        edge = _mapping(raw, "edge", _EDGE)
        name = _token(edge.get("name"), "edge.name")
        if name in names:
            raise ValueError("edge names must be unique")
        names.add(name)
        node = nodes.get(name, {})
        if node.get("template") != "c8000v" or node.get("image") != "c8000v-17.15.01a":
            raise ValueError(name + " must be declared as c8000v-17.15.01a")
        hostname = _token(edge.get("hostname"), name + ".hostname")
        system = _ipv4(edge.get("system_ip"), name + ".system_ip")
        if hostname in hostnames or system in systems:
            raise ValueError("edge hostnames and system_ip values must be unique")
        hostnames.add(hostname)
        systems.add(system)
        site = edge.get("site_id")
        if type(site) is not int or not 1 <= site <= 4294967295:
            raise ValueError(name + ".site_id must be an SD-WAN site integer")
        if edge.get("transport") is not None and edge.get("transports") is not None:
            raise ValueError(name + " must not declare both transport and transports")
        transports = edge.get("transports")
        if transports is None and edge.get("transport") is not None:
            transports = [edge["transport"]]
        if not isinstance(transports, list) or not transports:
            raise ValueError(name + ".transports must be a nonempty list")
        interfaces, colors, normalized, transport_commands = set(), set(), [], []
        for raw_transport in transports:
            item = _mapping(raw_transport, name + ".transport", _TRANSPORT)
            declared = item.get("interface")
            command_interface = _command_interface(declared, name + ".transport.interface")
            address = _address(item.get("address"), name + ".transport.address")
            gateway = _ipv4(item.get("gateway"), name + ".transport.gateway")
            color = _token(item.get("color"), name + ".transport.color")
            peer = _peer(item.get("peer"), name + ".transport.peer", nodes)
            distance = item.get("distance", 1)
            if type(distance) is not int or not 1 <= distance <= 255:
                raise ValueError(name + ".transport.distance must be 1 through 255")
            if (command_interface in interfaces or color in colors or address.ip in addresses):
                raise ValueError("transport interfaces, colors, and addresses must be unique")
            if (gateway not in address.network or gateway == address.ip or
                    gateway in (address.network.network_address, address.network.broadcast_address)):
                raise ValueError(name + " transport gateway must be a usable peer address")
            _direct_link(topology, name, declared, peer)
            interfaces.add(command_interface)
            colors.add(color)
            addresses.add(address.ip)
            number = re.search(r"(\d+)\Z", command_interface).group(1)
            normalized.append((declared, command_interface, address, gateway, color, distance))
            transport_commands += [
                "interface " + command_interface, "no shutdown",
                "ip address " + str(address.ip) + " " + _mask(address), "exit",
                "interface Tunnel" + number, "no shutdown",
                "ip unnumbered " + command_interface, "tunnel source " + command_interface,
                "tunnel mode sdwan", "exit", "sdwan",
                "interface " + command_interface, "tunnel-interface",
                "encapsulation ipsec", "color " + color, "allow-service all",
                "exit", "exit", "exit",
                "ip route 0.0.0.0 0.0.0.0 " + str(gateway) +
                (" " + str(distance) if distance != 1 else ""),
                "ip route " + str(controller_prefix.network_address) + " " +
                str(controller_prefix.netmask) + " " + str(gateway) +
                (" " + str(distance) if distance != 1 else "")]
        raw_service = edge.get("service_interfaces", [])
        if raw_service is None:
            raw_service = []
        if not isinstance(raw_service, list):
            raise ValueError(name + ".service_interfaces must be a list")
        service_commands, service_vpns = [], set()
        for item in raw_service:
            service = _mapping(item, name + ".service_interface", _SERVICE)
            vpn = service.get("vpn")
            if type(vpn) is not int or vpn < 1 or vpn in (0, 512):
                raise ValueError(name + ".service_interface.vpn must be nonreserved")
            declared = service.get("interface")
            command_interface = _command_interface(declared, name + ".service_interface.interface")
            if command_interface in interfaces:
                raise ValueError(name + " service interface must be unique")
            address = _address(service.get("address"), name + ".service_interface.address")
            if address.ip in addresses:
                raise ValueError("transport and service addresses must be unique")
            peer = _peer(service.get("peer"), name + ".service_interface.peer", nodes)
            _direct_link(topology, name, declared, peer)
            interfaces.add(command_interface)
            addresses.add(address.ip)
            if vpn not in service_vpns:
                service_commands += ["vrf definition " + str(vpn), "address-family ipv4",
                                     "exit-address-family", "exit"]
                service_vpns.add(vpn)
            service_commands += ["interface " + command_interface,
                                 "vrf forwarding " + str(vpn),
                                 "ip address " + str(address.ip) + " " + _mask(address),
                                 "no shutdown", "exit"]
        operations = [_operation("identity", _identity(hostname, system, site, organization, vbond)),
                      _operation("transport", transport_commands)]
        if service_commands:
            operations.append(_operation("service-lan", service_commands))
        plans[name] = {"adapter": "c8000v-sdwan", "operations": operations}
    return {"adapter": "c8000v-sdwan-edge-intent", "edges": plans}


def compile_edge_stages(intent, topology):
    """Return executable EdgeStages through the shared cEdge contract."""
    return {name: stages_from_edge_plan(plan)
            for name, plan in compile_edge_intent(intent, topology)["edges"].items()}