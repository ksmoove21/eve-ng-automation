"""Generic IOS-XE route-based IPsec profile with RIPv2."""
from ipaddress import IPv4Address, IPv4Interface, IPv4Network
import re
import yaml
from .device_console import environment_values


def load_profile(path):
    data = yaml.safe_load(path.read_text())
    fields = {"profile", "hostname", "underlay", "inside", "tunnel", "psk_env", "routes"}
    if (not isinstance(data, dict) or set(data) not in (fields, fields | {"ike_version"})
            or data["profile"] != "iosxe-ipsec"):
        raise ValueError("IOS-XE IPsec profile requires profile, hostname, underlay, inside, tunnel, psk_env, routes")
    if data.get("ike_version", 2) not in (1, 2):
        raise ValueError("IOS-XE IPsec ike_version must be 1 or 2")
    for field in ("hostname", "psk_env"):
        if not isinstance(data[field], str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", data[field]):
            raise ValueError("Invalid IOS-XE IPsec " + field)
    networks = []
    interfaces = []
    for side in ("underlay", "inside", "tunnel"):
        item = data[side]
        expected = {"interface", "address"} | ({"peer"} if side == "underlay" else set())
        if not isinstance(item, dict) or set(item) != expected:
            raise ValueError("Invalid IOS-XE IPsec " + side + " fields")
        physical = r"(?:GigabitEthernet|FastEthernet|Ethernet)[0-9]+(?:/[0-9]+){0,2}"
        pattern = physical if side == "underlay" else (r"Tunnel[0-9]+" if side == "tunnel" else rf"(?:{physical}|Loopback[0-9]+)")
        if not isinstance(item["interface"], str) or not re.fullmatch(pattern, item["interface"]):
            raise ValueError("Invalid IOS-XE IPsec interface")
        addr = IPv4Interface(item["address"])
        if addr.network.prefixlen < 31 and addr.ip in (addr.network.network_address, addr.network.broadcast_address):
            raise ValueError("IOS-XE IPsec addresses must be usable hosts")
        networks.append(addr.network); interfaces.append(item["interface"])
    if len(set(interfaces)) != 3 or any(a.overlaps(b) for i,a in enumerate(networks) for b in networks[i+1:]):
        raise ValueError("IOS-XE IPsec underlay, inside and tunnel must be distinct")
    peer = IPv4Address(data["underlay"]["peer"])
    if peer not in networks[0] or peer == IPv4Interface(data["underlay"]["address"]).ip:
        raise ValueError("IOS-XE IPsec underlay peer must be distinct and directly attached")
    if not isinstance(data["routes"], list):
        raise ValueError("IOS-XE IPsec routes must be a list")
    seen = set()
    for route in data["routes"]:
        if not isinstance(route, dict) or set(route) != {"prefix", "next_hop"}:
            raise ValueError("IOS-XE IPsec route requires prefix and next_hop")
        prefix = IPv4Network(route["prefix"], strict=True)
        hop = IPv4Address(route["next_hop"])
        if prefix in seen or any(prefix.overlaps(n) for n in networks) or hop not in networks[1]:
            raise ValueError("IOS-XE IPsec routes must be unique, isolated and reached through the inside network")
        seen.add(prefix)
    return data


def render(data, root):
    key = environment_values(root).get(data["psk_env"], "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{24,128}", key):
        raise ValueError("Set " + data["psk_env"] + " to a 24-128 character alphanumeric, underscore or hyphen lab PSK")
    underlay, inside, tun = (data[s] for s in ("underlay", "inside", "tunnel"))
    commands = ["hostname " + data["hostname"], "vrf definition Red", "address-family ipv4", "exit-address-family", "exit"]
    for item, red in ((underlay,False),(inside,True)):
        addr = IPv4Interface(item["address"])
        commands += ["interface " + item["interface"]]
        if red: commands += ["vrf forwarding Red"]
        commands += [f"ip address {addr.ip} {addr.netmask}", "no shutdown", "exit"]
    if data.get("ike_version", 2) == 2:
        commands += ["crypto ikev2 proposal IPSEC-PROPOSAL", "encryption aes-cbc-256", "integrity sha256", "group 14", "exit",
                     "crypto ikev2 policy IPSEC-POLICY", "match fvrf global", "proposal IPSEC-PROPOSAL", "exit",
                     "crypto ikev2 keyring IPSEC-KEYRING", "peer IPSEC-PEER", "address " + underlay["peer"],
                     "pre-shared-key local " + key, "pre-shared-key remote " + key, "exit", "exit",
                     "crypto ikev2 profile IPSEC-IKE", "match fvrf global", "match identity remote address " + underlay["peer"] + " 255.255.255.255",
                     "identity local address " + str(IPv4Interface(underlay["address"]).ip), "authentication local pre-share", "authentication remote pre-share",
                     "keyring local IPSEC-KEYRING", "exit", "crypto ipsec transform-set IPSEC-TRANSFORM esp-aes 256 esp-sha256-hmac", "mode tunnel", "exit",
                     "crypto ipsec profile IPSEC-PROFILE", "set transform-set IPSEC-TRANSFORM", "set ikev2-profile IPSEC-IKE", "exit"]
    else:
        commands += ["crypto isakmp policy 10", "encr aes 256", "hash sha256", "authentication pre-share", "group 14", "exit",
                     "crypto isakmp key " + key + " address " + underlay["peer"],
                     "crypto ipsec transform-set IPSEC-TRANSFORM esp-aes 256 esp-sha256-hmac", "mode tunnel", "exit",
                     "crypto ipsec profile IPSEC-PROFILE", "set transform-set IPSEC-TRANSFORM", "no set ikev2-profile IPSEC-IKE", "exit"]
    addr = IPv4Interface(tun["address"])
    commands += ["interface " + tun["interface"], "vrf forwarding Red", f"ip address {addr.ip} {addr.netmask}",
                 "ip mtu 1400", "ip tcp adjust-mss 1360", "tunnel source " + underlay["interface"], "tunnel destination " + underlay["peer"],
                 "tunnel mode ipsec ipv4", "tunnel protection ipsec profile IPSEC-PROFILE", "no shutdown", "exit"]
    for i,route in enumerate(data["routes"],1):
        net = IPv4Network(route["prefix"])
        commands += [f"ip route vrf Red {net.network_address} {net.netmask} {route['next_hop']}",
                     f"ip prefix-list IPSEC-EXPORT seq {i*10} permit {net}"]
    if data["routes"]:
        commands += ["route-map IPSEC-EXPORT permit 10", "match ip address prefix-list IPSEC-EXPORT", "exit"]
    commands += ["router rip", "passive-interface default", "no passive-interface " + tun["interface"], "address-family ipv4 vrf Red", "version 2", "no auto-summary"]
    # RIP uses classful network selectors; all selectors remain scoped to Red.
    major = set()
    for side in ("inside", "tunnel"):
        addr = IPv4Interface(data[side]["address"]).ip
        length = 8 if int(str(addr).split('.')[0]) < 128 else 16 if int(str(addr).split('.')[0]) < 192 else 24
        major.add(str(IPv4Network(f"{addr}/{length}", strict=False).network_address))
    commands += ["network " + network for network in sorted(major)]
    if data["routes"]: commands += ["redistribute static metric 1 route-map IPSEC-EXPORT"]
    commands += ["exit-address-family", "exit"]
    return commands


def prepare_license(console):
    """Select the minimum crypto-capable boot tier only on an unlicensed boot.

    This does not register entitlements or contact a licensing service.
    """
    console.command("terminal length 0")
    output=console.command("show version")
    match=re.search(r"^License Level:[ \t]*(.*)$",output,re.M)
    if not match: raise RuntimeError("Cannot identify IOS-XE boot license")
    if match[1].strip(): return False
    console.command("configure terminal")
    console.command("license boot level network-essentials addon dna-essentials")
    console.command("end")
    if "[OK]" not in console.command("write memory",timeout=120):
        raise RuntimeError("IOS-XE IPsec boot license save was not confirmed")
    console.send("reload")
    console.expect(r"Proceed with reload[^\n]*\[confirm\]",timeout=60)
    console.send("")
    # Observe actual reload before accepting another CLI prompt.
    console.expect(r"(?i:reload requested|reloading|initializing hardware|system bootstrap|linux version)",timeout=120)
    console.pending=""
    return True


def verify_license(console):
    console.command("terminal length 0")
    output=console.command("show version")
    if not re.search(r"^License Level:.*network-(?:essentials|advantage|premier)",output,re.M|re.I):
        raise RuntimeError("IOS-XE crypto boot license did not become active after reload")
