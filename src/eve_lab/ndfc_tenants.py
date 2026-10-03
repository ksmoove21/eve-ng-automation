"""Compile declared NDFC tenant overlays without accessing the live controller."""

from ipaddress import ip_address, ip_interface, ip_network
import re


def _range(text):
    try:
        low, high = map(int, text.split("-", 1))
    except (AttributeError, ValueError) as exc:
        raise ValueError("NDFC tenant range must be LOW-HIGH") from exc
    if not 1 <= low <= high <= 16777215:
        raise ValueError("NDFC tenant range is invalid")
    return range(low, high + 1)


def compile_tenants(intent, site="DC1"):
    """Validate tenant intent and return explicit VRF/network switch targets.

    The returned objects contain no NDFC API defaults or runtime identities.
    Serial numbers and template capabilities must be checked against live NDFC
    before a mutation is submitted.
    """
    profiles = [item for item in intent["ndfc_fabrics"] if item["site"] == site]
    if site != "DC1" or len(profiles) != 1:
        raise ValueError("Exactly one active DC1 fabric is required")
    profile = profiles[0]
    regular = tuple(profile["regular_leaf_pair"]["nodes"])
    border = tuple(profile["border_leaf_pair"]["nodes"])
    if len(regular) != 2 or len(border) != 2 or len(set(regular + border)) != 4:
        raise ValueError("DC1 tenant attachments require two unique regular and border leafs")
    tenants = intent["tenants"][site.lower()]
    if len(tenants) < 2 or intent["tenants"]["isolation"] != "no_inter_vrf_route_leaking":
        raise ValueError("DC1 needs at least two isolated tenant VRFs")
    policy = intent["tenants"]["vni_policy"]
    l2, l3 = _range(policy["l2_range"]), _range(policy["l3_range"])
    vlan_range = _range(profile["network_vlan_range"])
    names, zones, l3_ids, l2_ids, vlans, prefixes = set(), set(), set(), set(), set(), []
    vrfs, networks = [], []
    for tenant in tenants:
        name, zone = tenant["vrf"], tenant["zone"]
        vrf_vni, vrf_vlan = tenant["vrf_vni"], tenant["vrf_vlan"]
        if name in names or zone in zones or vrf_vni in l3_ids or vrf_vlan in vlans:
            raise ValueError("Duplicate DC1 VRF name, zone, VNI, or VLAN")
        if not name or not zone or vrf_vni not in l3 or vrf_vlan not in vlan_range:
            raise ValueError("DC1 VRF identifier is outside declared ranges")
        names.add(name)
        zones.add(zone)
        l3_ids.add(vrf_vni)
        vlans.add(vrf_vlan)
        if not tenant["networks"]:
            raise ValueError("DC1 tenant VRF has no networks")
        vrfs.append({"name": name, "vni": vrf_vni, "vlan": vrf_vlan,
                     "zone": zone, "switches": regular + border})
        tenant_prefixes = []
        for network in tenant["networks"]:
            network_name = network["name"]
            net = ip_network(network["prefix"], strict=True)
            gateway = ip_address(network["gateway"])
            if (network_name in names or network["vni"] in l2_ids or
                    network["vlan"] in vlans):
                raise ValueError("Duplicate DC1 network name, VNI, or VLAN")
            if (network["vni"] not in l2 or network["vlan"] not in vlan_range or
                    gateway not in net or gateway == net.network_address or
                    gateway == net.broadcast_address):
                raise ValueError("DC1 network VNI, VLAN, or gateway is invalid")
            if any(net.overlaps(existing) for existing in prefixes):
                raise ValueError("DC1 tenant networks overlap")
            names.add(network_name)
            l2_ids.add(network["vni"])
            vlans.add(network["vlan"])
            prefixes.append(net)
            tenant_prefixes.append(net)
            networks.append({"name": network_name, "vrf": name, "vni": network["vni"],
                             "vlan": network["vlan"], "prefix": str(net),
                             "gateway": str(gateway), "switches": regular})
        for endpoint in tenant.get("endpoints", []):
            host = ip_interface(endpoint["address"])
            if sum(host.ip in net for net in tenant_prefixes) != 1:
                raise ValueError("DC1 endpoint is outside its tenant network")
            matching = next(net for net in tenant_prefixes if host.ip in net)
            if host.network != matching or ip_address(endpoint["gateway"]) not in matching:
                raise ValueError("DC1 endpoint mask or gateway conflicts with network")
    return {"fabric": profile["name"], "vrfs": vrfs, "networks": networks}

def preflight_inventory(intent, inventory, allowed_cc_status=("In-Sync",)):
    """Bind tenant attachment names to exact managed DC1 serial identities."""
    from .ndfc_switches import compile_switches

    _, declared = compile_switches(intent)
    by_name = {item.get("logicalName"): item for item in inventory}
    if len(inventory) != len(declared) or set(by_name) != {
            item["name"] for item in declared}:
        raise ValueError("NDFC tenant preflight inventory differs from declared DC1 switches")
    roles = {"spine": "spine", "leaf": "leaf",
             "border": "border gateway", "tor": "tor"}
    serials = {}
    for wanted in declared:
        item = by_name[wanted["name"]]
        serial = item.get("serialNumber")
        if (item.get("ipAddress") != wanted["ip"] or
                item.get("switchRole") != roles[wanted["role"]] or
                not isinstance(serial, str) or not serial.strip() or
                item.get("ccStatus") not in allowed_cc_status):
            raise ValueError("NDFC tenant preflight switch identity or sync differs for " +
                             wanted["name"])
        if serial in serials.values():
            raise ValueError("NDFC tenant preflight returned duplicate serial")
        serials[wanted["name"]] = serial
    return serials


def compile_tor_ports(intent, topology, site="DC1"):
    """Bind declared tenant endpoints to exact ToR host ports in the topology."""
    profiles = [item for item in intent["ndfc_fabrics"] if item["site"] == site]
    if site != "DC1" or len(profiles) != 1:
        raise ValueError("Exactly one active DC1 fabric is required")
    tors = set(profiles[0]["tor_pair"]["nodes"])
    by_endpoint = {}
    for link in topology["links"]:
        if "from" not in link or "to" not in link:
            continue
        for left, right in (("from", "to"), ("to", "from")):
            endpoint = link[left]["node"]
            if link[right]["node"] in tors:
                by_endpoint.setdefault(endpoint, []).append(
                    (link[right]["node"], link[right]["interface"]))
    used_ports = set()
    result = {}
    for tenant in intent["tenants"][site.lower()]:
        networks = [(item["name"], ip_network(item["prefix"], strict=True))
                    for item in tenant["networks"]]
        for endpoint in tenant.get("endpoints", []):
            name = endpoint["node"]
            matches = by_endpoint.get(name, [])
            if len(matches) != 1 or matches[0][0] != endpoint["attachment"]:
                raise ValueError("DC1 endpoint lacks one exact declared ToR link: " + name)
            tor, port = matches[0]
            if not isinstance(port, str) or not re.fullmatch(r"Ethernet\d+/\d+", port):
                raise ValueError("DC1 endpoint ToR interface is not Ethernet: " + name)
            if (tor, port) in used_ports:
                raise ValueError("DC1 tenant endpoints share a ToR host port")
            used_ports.add((tor, port))
            address = ip_interface(endpoint["address"]).ip
            selected = [network_name for network_name, prefix in networks
                        if address in prefix]
            if len(selected) != 1:
                raise ValueError("DC1 endpoint does not match one tenant network")
            result.setdefault(selected[0], {}).setdefault(tor, []).append(port)
    return {name: " ".join(tor + "(" + ",".join(sorted(ports)) + ")"
                           for tor, ports in sorted(tor_map.items()))
            for name, tor_map in result.items()}


def vrf_create_payload(fabric, vrf):
    """Cisco LAN top-down VRF payload using the base VRF template."""
    import json

    template_config = {
        "vrfName": vrf["name"],
        "vrfSegmentId": vrf["vni"],
        "vrfVlanId": vrf["vlan"],
        "nveId": "1",
        "mtu": "9216",
        "vrfRouteMap": "FABRIC-RMAP-REDIST-SUBNET",
        "maxBgpPaths": "1",
        "maxIbgpPaths": "2",
    }
    return {
        "fabric": fabric,
        "vrfName": vrf["name"],
        "vrfId": vrf["vni"],
        "vrfTemplate": "Default_VRF_Universal",
        "vrfExtensionTemplate": "Default_VRF_Extension_Universal",
        "vrfTemplateConfig": json.dumps(template_config, separators=(",", ":")),
    }


def network_create_payload(fabric, network):
    """Cisco LAN top-down routed network payload; replication is fabric-owned."""
    import json

    gateway = str(ip_interface(
        network["gateway"] + "/" + network["prefix"].split("/")[-1]))
    template_config = {
        "networkName": network["name"],
        "vrfName": network["vrf"],
        "segmentId": network["vni"],
        "vlanId": network["vlan"],
        "gatewayIpAddress": gateway,
        "nveId": "1",
        "isLayer2Only": False,
    }
    return {
        "fabric": fabric,
        "networkName": network["name"],
        "networkId": network["vni"],
        "vrf": network["vrf"],
        "networkTemplate": "Default_Network_Universal",
        "networkExtensionTemplate": "Default_Network_Extension_Universal",
        "networkTemplateConfig": json.dumps(template_config, separators=(",", ":")),
    }


def vrf_attach_payload(fabric, vrf, serials):
    """Build explicit VRF attachment request for declared managed switches."""
    return [{
        "vrfName": vrf["name"],
        "lanAttachList": [{
            "fabric": fabric,
            "vrfName": vrf["name"],
            "serialNumber": serials[name],
            "vlan": vrf["vlan"],
            "deployment": True,
        } for name in vrf["switches"]],
    }]


def network_attach_payload(fabric, network, serials, tor_ports=""):
    """Build overlay network attachments without touching switch ports."""
    return [{
        "networkName": network["name"],
        "lanAttachList": [{
            "fabric": fabric,
            "networkName": network["name"],
            "serialNumber": serials[name],
            "vlan": network["vlan"],
            "deployment": True,
            **({"torPorts": tor_ports} if tor_ports else {}),
        } for name in network["switches"]],
    }]
