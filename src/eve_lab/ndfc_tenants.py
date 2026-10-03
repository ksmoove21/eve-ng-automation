"""Compile selected-site NDFC tenant overlays without live controller access."""

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
    if site not in ("DC1", "DC2"):
        raise ValueError("NDFC tenant site must be DC1 or DC2")
    profiles = [item for item in intent["ndfc_fabrics"] if item["site"] == site]
    if len(profiles) != 1:
        raise ValueError("Exactly one declared " + site + " fabric is required")
    profile = profiles[0]
    regular = tuple(profile["regular_leaf_pair"]["nodes"])
    border = tuple(profile["border_leaf_pair"]["nodes"])
    if len(regular) != 2 or len(border) != 2 or len(set(regular + border)) != 4:
        raise ValueError(site + " tenant attachments require two unique regular and border leafs")
    tenants = intent["tenants"].get(site.lower())
    if not isinstance(tenants, list):
        raise ValueError(site + " tenant list is absent")
    if len(tenants) < 2 or intent["tenants"]["isolation"] != "no_inter_vrf_route_leaking":
        raise ValueError(site + " needs at least two isolated tenant VRFs")
    policy = intent["tenants"]["vni_policy"]
    l2, l3 = _range(policy["l2_range"]), _range(policy["l3_range"])
    vlan_range = _range(profile["network_vlan_range"])
    vrf_vlan_range = _range(profile.get("vrf_vlan_range",
                                        profile["network_vlan_range"]))
    if "vrf_vlan_range" in profile and set(vlan_range) & set(vrf_vlan_range):
        raise ValueError(site + " VRF and Network VLAN ranges overlap")
    names, zones, l3_ids, l2_ids, vlans, prefixes = set(), set(), set(), set(), set(), []
    vrfs, networks = [], []
    for tenant in tenants:
        name, zone = tenant["vrf"], tenant["zone"]
        if "vrf_vlan" not in tenant:
            raise ValueError(site + " tenant " + str(name) + " lacks vrf_vlan")
        vrf_vni, vrf_vlan = tenant["vrf_vni"], tenant["vrf_vlan"]
        if name in names or zone in zones or vrf_vni in l3_ids or vrf_vlan in vlans:
            raise ValueError("Duplicate " + site + " VRF name, zone, VNI, or VLAN")
        if not name or not zone or vrf_vni not in l3 or vrf_vlan not in vrf_vlan_range:
            raise ValueError(site + " VRF identifier is outside declared ranges")
        names.add(name)
        zones.add(zone)
        l3_ids.add(vrf_vni)
        vlans.add(vrf_vlan)
        if not tenant["networks"]:
            raise ValueError(site + " tenant VRF has no networks")
        vrfs.append({"name": name, "vni": vrf_vni, "vlan": vrf_vlan,
                     "zone": zone, "switches": regular + border})
        tenant_prefixes = []
        for network in tenant["networks"]:
            network_name = network["name"]
            net = ip_network(network["prefix"], strict=True)
            gateway = ip_address(network["gateway"])
            if (network_name in names or network["vni"] in l2_ids or
                    network["vlan"] in vlans):
                raise ValueError("Duplicate " + site + " network name, VNI, or VLAN")
            if (network["vni"] not in l2 or network["vlan"] not in vlan_range or
                    gateway not in net or gateway == net.network_address or
                    gateway == net.broadcast_address):
                raise ValueError(site + " network VNI, VLAN, or gateway is invalid")
            if any(net.overlaps(existing) for existing in prefixes):
                raise ValueError(site + " tenant networks overlap")
            names.add(network_name)
            l2_ids.add(network["vni"])
            vlans.add(network["vlan"])
            prefixes.append(net)
            tenant_prefixes.append(net)
            networks.append({"name": network_name, "vrf": name, "vni": network["vni"],
                             "vlan": network["vlan"], "prefix": str(net),
                             "gateway": str(gateway), "switches": regular,
                             "dhcp": network.get("dhcp"),
                             "dhcp_deployment": network.get("dhcp_deployment")})
        for endpoint in tenant.get("endpoints", []):
            host = ip_interface(endpoint["address"])
            if sum(host.ip in net for net in tenant_prefixes) != 1:
                raise ValueError(site + " endpoint is outside its tenant network")
            matching = next(net for net in tenant_prefixes if host.ip in net)
            if host.network != matching or ip_address(endpoint["gateway"]) not in matching:
                raise ValueError(site + " endpoint mask or gateway conflicts with network")
    return {"fabric": profile["name"], "vrfs": vrfs, "networks": networks}

def preflight_inventory(intent, inventory, allowed_cc_status=("In-Sync",), site="DC1"):
    """Bind tenant attachment names to exact managed site serial identities."""
    from .ndfc_switches import compile_switches

    _, declared = compile_switches(intent, site)
    by_name = {item.get("logicalName"): item for item in inventory}
    if len(inventory) != len(declared) or set(by_name) != {
            item["name"] for item in declared}:
        raise ValueError("NDFC tenant preflight inventory differs from declared " + site + " switches")
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
    if site not in ("DC1", "DC2"):
        raise ValueError("NDFC tenant site must be DC1 or DC2")
    profiles = [item for item in intent["ndfc_fabrics"] if item["site"] == site]
    if len(profiles) != 1:
        raise ValueError("Exactly one declared " + site + " fabric is required")
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
                raise ValueError(site + " endpoint lacks one exact declared ToR link: " + name)
            tor, port = matches[0]
            if not isinstance(port, str) or not re.fullmatch(r"Ethernet\d+/\d+", port):
                raise ValueError(site + " endpoint ToR interface is not Ethernet: " + name)
            if (tor, port) in used_ports:
                raise ValueError(site + " tenant endpoints share a ToR host port")
            used_ports.add((tor, port))
            address = ip_interface(endpoint["address"]).ip
            selected = [network_name for network_name, prefix in networks
                        if address in prefix]
            if len(selected) != 1:
                raise ValueError(site + " endpoint does not match one tenant network")
            result.setdefault(selected[0], {}).setdefault(tor, []).append(port)
    return {name: " ".join(tor + "(" + ",".join(sorted(ports)) + ")"
                           for tor, ports in sorted(tor_map.items()))
            for name, tor_map in result.items()}


def compile_tor_access_ports(intent, topology, site="DC1"):
    """Map declared untagged endpoint links to their Network access VLANs."""
    if intent["tenants"].get("host_port_mode") != "access":
        raise ValueError(site + " tenant host_port_mode must explicitly be access")
    networks = {item["name"]: item["vlan"] for item in
                compile_tenants(intent, site)["networks"]}
    tor_ports = compile_tor_ports(intent, topology, site)
    result = []
    for network, text in sorted(tor_ports.items()):
        for tor, ports in re.findall(r"(\S+)\(([^)]*)\)", text):
            for port in ports.split(","):
                result.append({"tor": tor, "port": port,
                               "network": network, "vlan": networks[network]})
    if not result or len({(item["tor"], item["port"]) for item in result}) != len(result):
        raise ValueError(site + " tenant host access ports are absent or duplicated")
    return result


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


def validate_network_dhcp(network):
    """Require explicit deferral before staging unsupported leaf DHCP intent."""
    mode = network.get("dhcp")
    deployment = network.get("dhcp_deployment")
    if mode == "fabric_leaf" and deployment == "deferred":
        return "deferred"
    if mode in (None, "deferred_out_of_scope") and deployment is None:
        return "not-requested"
    raise ValueError("NDFC Network " + network["name"] +
                     " DHCP intent requires explicit supported deployment or "
                     "dhcp_deployment: deferred")


def network_create_payload(fabric, network):
    """Cisco LAN top-down routed network payload; replication is fabric-owned."""
    import json

    validate_network_dhcp(network)

    gateway = str(ip_interface(
        network["gateway"] + "/" + network["prefix"].split("/")[-1]))
    template_config = {
        "networkName": network["name"],
        "vrfName": network["vrf"],
        "segmentId": network["vni"],
        "vlanId": network["vlan"],
        "gatewayIpAddress": gateway,
        "tag": "",
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
