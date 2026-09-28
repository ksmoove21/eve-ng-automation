"""Catalyst 9000v UADP profile rendering and reload-aware bootstrap."""
from ipaddress import IPv4Address, IPv4Interface, IPv4Network
from pathlib import Path
import re
import time

import yaml

from .device_console import Console, environment_values


TEMPLATE = "cat9kvuadp"
MANAGEMENT_INTERFACE = "GigabitEthernet0/0"
MANAGEMENT_VRF = "Mgmt-vrf"
PROFILES = {"dnac-bootstrap", "ospf-underlay"}

_TOKEN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\Z")
_DOMAIN = re.compile(
    r"(?=.{1,253}\Z)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z"
)
_DATA_INTERFACE = re.compile(r"GigabitEthernet1/0/[1-9][0-9]*\Z", re.I)
_LOOPBACK_INTERFACE = re.compile(r"Loopback(?:0|[1-9][0-9]*)\Z", re.I)
_ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_LICENSE = re.compile(r"(?:network|dna)-(?:advantage|essentials)\Z")


def _exact(data, fields, label):
    if not isinstance(data, dict) or set(data) != set(fields):
        raise ValueError(label + " requires exactly " + ", ".join(fields))


def _token(value, field, pattern=_TOKEN):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(field + " must be a safe single token")
    return value


def _prefix(value, field):
    if type(value) is not int or not 1 <= value <= 32:
        raise ValueError(field + " must be an integer from 1 to 32")
    return value


def _area(value):
    if type(value) is int and 0 <= value <= 4294967295:
        return str(value)
    if isinstance(value, str):
        try:
            return str(IPv4Address(value))
        except ValueError:
            pass
    raise ValueError("ospf_area must be an integer or dotted-decimal OSPF area")


def _management_from_context(root, reference):
    """Resolve environment-owned management state from a workspace registry."""
    _exact(reference, ("source", "allocation_id", "logical_device_id"), "management")
    source = reference["source"]
    if not isinstance(source, str) or not source or Path(source).is_absolute():
        raise ValueError("management source must be a workspace-relative YAML path")
    workspace = Path(root).resolve()
    path = (workspace / source).resolve()
    if not path.is_relative_to(workspace):
        raise ValueError("management source must remain inside the workspace")
    try:
        document = yaml.safe_load(path.read_text())
    except OSError as error:
        raise ValueError("Cannot read management context: " + source) from error
    except yaml.YAMLError as error:
        raise ValueError("Invalid management context YAML: " + source) from error
    if not isinstance(document, dict):
        raise ValueError("Management context must be a mapping")
    allocations = document.get("allocations")
    pools = document.get("approved_pools")
    if not isinstance(allocations, list) or not isinstance(pools, list):
        raise ValueError("Management context requires approved_pools and allocations lists")
    allocation_id = _token(reference["allocation_id"], "allocation_id")
    logical_id = reference["logical_device_id"]
    if not isinstance(logical_id, str) or not logical_id or any(ord(c) < 32 for c in logical_id):
        raise ValueError("logical_device_id must be a nonempty printable string")
    matches = [item for item in allocations if isinstance(item, dict)
               and item.get("allocation_id") == allocation_id]
    if len(matches) != 1:
        raise ValueError("Management allocation_id must resolve exactly once")
    allocation = matches[0]
    assignments = allocation.get("assignments")
    if not isinstance(assignments, list):
        raise ValueError("Management allocation requires assignments")
    assigned = [item for item in assignments if isinstance(item, dict)
                and item.get("logical_device_id") == logical_id]
    if len(assigned) != 1:
        raise ValueError("Management logical_device_id must resolve exactly once")
    pool_id = allocation.get("pool_id")
    pool_matches = [item for item in pools if isinstance(item, dict)
                    and item.get("id") == pool_id]
    if len(pool_matches) != 1:
        raise ValueError("Management pool_id must resolve exactly once")
    pool = pool_matches[0]
    try:
        network = IPv4Network(pool["network"], strict=True)
        gateway = IPv4Address(pool["gateway"])
        address = IPv4Address(assigned[0]["address"])
    except (KeyError, ValueError):
        raise ValueError("Management context contains invalid IPv4 pool data") from None
    prefix = pool.get("interface_prefix_length")
    _prefix(prefix, "management interface_prefix_length")
    if network.prefixlen != prefix or address not in network or gateway not in network:
        raise ValueError("Management assignment and gateway must belong to the declared pool")
    if address in (network.network_address, network.broadcast_address) or gateway in (
            network.network_address, network.broadcast_address):
        raise ValueError("Management assignment and gateway must be usable host addresses")
    return {
        "interface": MANAGEMENT_INTERFACE,
        "vrf": MANAGEMENT_VRF,
        "address": str(address),
        "prefix_length": prefix,
        "gateway": str(gateway),
        "source": source,
        "allocation_id": allocation_id,
        "logical_device_id": logical_id,
    }


def _interface_intent(data, kind, process_id):
    required = ("interface", "address", "ospf_area")
    optional = {"network_type"} if kind == "routed" else set()
    if (not isinstance(data, dict)
            or set(data) - (set(required) | optional)
            or not set(required) <= set(data)):
        raise ValueError(kind + " interface requires interface, address, ospf_area"
                         + (", and optional network_type" if optional else ""))
    pattern = _DATA_INTERFACE if kind == "routed" else _LOOPBACK_INTERFACE
    interface = _token(data["interface"], kind + " interface", pattern)
    try:
        address = IPv4Interface(data["address"])
    except ValueError:
        raise ValueError(kind + " address must be IPv4 CIDR interface notation") from None
    if (address.ip in (address.network.network_address, address.network.broadcast_address)
            and address.network.prefixlen < 31):
        raise ValueError(kind + " address must be a usable host address")
    result = {
        "interface": interface,
        "address": str(address),
        "ospf_area": _area(data["ospf_area"]),
        "ospf_process_id": process_id,
    }
    if kind == "routed":
        network_type = data.get("network_type", "point-to-point")
        if network_type != "point-to-point":
            raise ValueError("Cat9Kv routed interface network_type must be point-to-point")
        result["network_type"] = network_type
    return result


def load_bootstrap(path, root):
    """Load profiles and resolve only their referenced environment state."""
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as error:
        raise ValueError("Invalid Cat9Kv-UADP bootstrap YAML") from error
    required = {"schema_version", "profiles", "hostname", "domain_name", "management", "dnac"}
    if (not isinstance(data, dict) or set(data) - (required | {"underlay"})
            or not required <= set(data)):
        raise ValueError("Cat9Kv-UADP bootstrap has unsupported or missing fields")
    if data["schema_version"] != 1:
        raise ValueError("Cat9Kv-UADP bootstrap schema_version must be 1")
    profiles = data["profiles"]
    if not isinstance(profiles, list) or not profiles or len(profiles) != len(set(profiles)):
        raise ValueError("profiles must be a nonempty unique list")
    if any(profile not in PROFILES for profile in profiles):
        raise ValueError("Unsupported Cat9Kv-UADP profile")
    if "ospf-underlay" in profiles and "dnac-bootstrap" not in profiles:
        raise ValueError("ospf-underlay requires dnac-bootstrap")
    if ("ospf-underlay" in profiles) != ("underlay" in data):
        raise ValueError("underlay intent is required exactly when ospf-underlay is selected")
    hostname = _token(data["hostname"], "hostname")
    domain_name = _token(data["domain_name"], "domain_name", _DOMAIN)
    management = _management_from_context(root, data["management"])

    dnac = data["dnac"]
    _exact(dnac, ("snmp_ro_env", "snmp_rw_env", "rsa_modulus", "license"), "dnac")
    for field in ("snmp_ro_env", "snmp_rw_env"):
        _token(dnac[field], field, _ENV_NAME)
    if dnac["snmp_ro_env"] == dnac["snmp_rw_env"]:
        raise ValueError("SNMP RO and RW environment variables must be different")
    if dnac["rsa_modulus"] not in (2048, 3072, 4096):
        raise ValueError("rsa_modulus must be 2048, 3072, or 4096")
    license_data = dnac["license"]
    _exact(license_data, ("network", "dna"), "dnac license")
    network_license = _token(license_data["network"], "network license", _LICENSE)
    dna_license = _token(license_data["dna"], "DNA license", _LICENSE)
    if not network_license.startswith("network-") or not dna_license.startswith("dna-"):
        raise ValueError("License values must be network-* and dna-* respectively")
    if network_license.split("-", 1)[1] != dna_license.split("-", 1)[1]:
        raise ValueError("Network and DNA license tiers must match")

    result = {
        "schema_version": 1,
        "profiles": list(profiles),
        "hostname": hostname,
        "domain_name": domain_name,
        "management": management,
        "dnac": {
            "snmp_ro_env": dnac["snmp_ro_env"],
            "snmp_rw_env": dnac["snmp_rw_env"],
            "rsa_modulus": dnac["rsa_modulus"],
            "license": {"network": network_license, "dna": dna_license},
        },
    }
    if "underlay" in data:
        underlay = data["underlay"]
        _exact(underlay, ("ospf", "loopback", "routed_interfaces"), "underlay")
        ospf = underlay["ospf"]
        _exact(ospf, ("process_id", "router_id"), "underlay ospf")
        if type(ospf["process_id"]) is not int or not 1 <= ospf["process_id"] <= 65535:
            raise ValueError("OSPF process_id must be an integer from 1 to 65535")
        try:
            router_id = str(IPv4Address(ospf["router_id"]))
        except ValueError:
            raise ValueError("OSPF router_id must be an IPv4 address") from None
        loopback = _interface_intent(
            underlay["loopback"], "loopback", ospf["process_id"])
        routed = underlay["routed_interfaces"]
        if not isinstance(routed, list) or not routed:
            raise ValueError("routed_interfaces must be a nonempty list")
        routed = [_interface_intent(item, "routed", ospf["process_id"])
                  for item in routed]
        names = ([loopback["interface"].lower()]
                 + [item["interface"].lower() for item in routed])
        addresses = [loopback["address"]] + [item["address"] for item in routed]
        if len(names) != len(set(names)) or len(addresses) != len(set(addresses)):
            raise ValueError("Underlay interfaces and addresses must be unique")
        if router_id != str(IPv4Interface(loopback["address"]).ip):
            raise ValueError("OSPF router_id must equal the declared loopback address")
        result["underlay"] = {
            "ospf": {"process_id": ospf["process_id"], "router_id": router_id},
            "loopback": loopback,
            "routed_interfaces": routed,
        }
    return result


def _secret(value, field):
    if (not isinstance(value, str) or not value
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError(field + " must be a nonempty CLI token without whitespace")
    return value


def bootstrap_commands(intent, username, password, enable_secret, snmp_ro, snmp_rw):
    """Render normalized IOS-XE commands; secret values are supplied at runtime."""
    username = _token(username, "Cisco username")
    password = _secret(password, "Cisco password")
    enable_secret = _secret(enable_secret, "Cisco enable secret")
    snmp_ro = _secret(snmp_ro, "SNMP RO community")
    snmp_rw = _secret(snmp_rw, "SNMP RW community")
    management = intent["management"]
    network = IPv4Network(
        management["address"] + "/" + str(management["prefix_length"]), strict=False)
    license_data = intent["dnac"]["license"]
    commands = [
        "hostname " + intent["hostname"],
        "ip domain name " + intent["domain_name"],
        "aaa new-model",
        "aaa authentication login default local",
        "aaa authorization exec default local if-authenticated",
        "aaa authorization console",
        f"username {username} privilege 15 secret 0 {password}",
        "enable secret 0 " + enable_secret,
        "ip ssh version 2",
        "netconf-yang",
        f"snmp-server community {snmp_ro} RO",
        f"snmp-server community {snmp_rw} RW",
        "interface " + MANAGEMENT_INTERFACE,
        "vrf forwarding " + MANAGEMENT_VRF,
        f"ip address {management['address']} {network.netmask}",
        "no shutdown",
        "exit",
        f"ip route vrf {MANAGEMENT_VRF} 0.0.0.0 0.0.0.0 {management['gateway']}",
        "line console 0",
        "login authentication default",
        "logging synchronous",
        "exec-timeout 0 0",
        "exit",
        "line vty 0 15",
        "login authentication default",
        "transport input ssh",
        "exec-timeout 0 0",
        "exit",
        f"license boot level {license_data['network']} addon {license_data['dna']}",
    ]
    if "ospf-underlay" in intent["profiles"]:
        underlay = intent["underlay"]
        process_id = underlay["ospf"]["process_id"]
        commands.append("ip routing")
        interfaces = [(underlay["loopback"], True)]
        interfaces.extend((item, False) for item in underlay["routed_interfaces"])
        for item, is_loopback in interfaces:
            interface = IPv4Interface(item["address"])
            commands.extend([
                "interface " + item["interface"],
                *([] if is_loopback else ["no switchport"]),
                f"ip address {interface.ip} {interface.network.netmask}",
                *([] if is_loopback else ["ip ospf network point-to-point"]),
                f"ip ospf {process_id} area {item['ospf_area']}",
                "no shutdown",
                "exit",
            ])
        commands.extend([
            "router ospf " + str(process_id),
            "router-id " + underlay["ospf"]["router_id"],
            "passive-interface default",
            *["no passive-interface " + item["interface"]
              for item in underlay["routed_interfaces"]],
            "exit",
        ])
    return commands


def runtime_secrets(intent, root):
    values = environment_values(Path(root))
    names = (intent["dnac"]["snmp_ro_env"], intent["dnac"]["snmp_rw_env"])
    if any(not values.get(name) for name in names):
        raise ValueError("Set " + ", ".join(names) + " in .env")
    return values[names[0]], values[names[1]]


def parse_license_state(output):
    """Return configured current/next license tokens from ``show version``."""
    if "Technology Package License Information" not in output:
        raise RuntimeError("Unrecognized IOS-XE license state")
    current, next_boot = set(), set()
    for line in output.splitlines():
        tokens = re.findall(r"(?:network|dna)-(?:advantage|essentials)", line.lower())
        if not tokens:
            continue
        if re.match(r"^\s*(?:network|dna)-(?:advantage|essentials)\b", line, re.I):
            current.add(tokens[0])
        next_boot.add(tokens[-1])
    if not any(item.startswith("network-") for item in current | next_boot):
        raise RuntimeError("Unrecognized IOS-XE license state")
    return {"current": sorted(current), "next_boot": sorted(next_boot)}


class Cat9kvConsole(Console):
    """Catalyst profile application with idempotent RSA and controlled reload."""

    def initialize(self, intent, username=None, password=None, secret=None,
                   snmp_ro=None, snmp_rw=None):
        desired = set(intent["dnac"]["license"].values())
        self.command("terminal length 0")
        before = parse_license_state(self.command("show version", timeout=120))
        commands = bootstrap_commands(
            intent, username, password, secret, snmp_ro, snmp_rw)
        self.command("configure terminal")
        for index, command in enumerate(commands, start=1):
            timeout = 120 if command.startswith("license boot") else 60
            try:
                self.command(command, timeout=timeout)
            except RuntimeError as error:
                raise RuntimeError(
                    "Catalyst bootstrap command " + str(index)
                    + " was rejected; command and output omitted") from error
        self.command("end")
        keys = self.command("show crypto key mypubkey rsa")
        if not re.search(
                r"^\s*(?:Key name:|Key Data:|Usage: General Purpose Key)",
                keys, re.M | re.I):
            self.command("configure terminal")
            self.command(
                "crypto key generate rsa general-keys modulus "
                + str(intent["dnac"]["rsa_modulus"]), timeout=180)
            self.command("end")
        saved = self.command("write memory", timeout=120)
        if "[OK]" not in saved:
            raise RuntimeError("Device did not confirm write memory; inspect startup-config")
        after = parse_license_state(self.command("show version", timeout=120))
        reload_required = not desired <= set(before["current"])
        if reload_required and not desired <= set(after["next_boot"]):
            raise RuntimeError("Configured license is not present in IOS-XE next-boot state")
        if reload_required:
            self.request_reload()
        return {
            "license_before": before,
            "license_after": after,
            "reload_required": reload_required,
        }

    def login_after_reload(self, username, password, secret):
        """Recover the observed 17.15.01 GRUB fallback, then authenticate."""
        started = time.monotonic()
        trigger = (
            r"(?is:error: invalid magic number.{0,1024}Press any key to continue)|"
            r"(?s:VNGWC - packages\.conf.{0,4096}VNGWC - GOLDEN IMAGE)|"
            r"(?i:Username:\s*$|login:\s*$|Password:\s*$|"
            r"Press RETURN to get started[^\n]*$|[A-Za-z0-9_.()/-]+[>#]\s*$)"
        )
        # Ctrl-R safely redisplays IOS prompts and acts as a non-Enter key at
        # the observed GRUB error, exposing its menu without selecting the
        # broken default entry.
        self.channel.sendall("\x12")
        probe_timeout = min(2, self.boot_timeout)
        observed, match = self.expect(
            trigger, timeout=probe_timeout, wake=False, latest=True,
            return_on_timeout=True)
        if match is None:
            self.channel.sendall(" ")
            observed, _ = self.expect(
                trigger, timeout=max(1, self.boot_timeout - probe_timeout),
                wake=False, latest=True)
        invalid_magic = "error: invalid magic number" in observed.lower()
        menu = "VNGWC - GOLDEN IMAGE" in observed
        recovered = invalid_magic or menu
        if invalid_magic:
            self.channel.sendall(" ")
            self.expect(
                r"(?s:VNGWC - packages\.conf.*VNGWC - GOLDEN IMAGE)",
                timeout=min(60, self.boot_timeout), wake=False, latest=True)
        if recovered:
            self.channel.sendall("\x1b[B\r")
        else:
            # Let the normal login state machine consume the prompt just found.
            self.pending = observed + self.pending
        original_timeout = self.boot_timeout
        self.boot_timeout = max(1, original_timeout - (time.monotonic() - started))
        try:
            super().login(username, password, secret)
        finally:
            self.boot_timeout = original_timeout
        return recovered

    def request_reload(self):
        self.send("reload")
        _, match = self.expect(
            r"(?i:System configuration has been modified[^\n]*Save[^\n]*\[yes/no\]:\s*$|"
            r"Proceed with reload[^\n]*\[confirm\]\s*$)", timeout=60)
        if "save" in match.group().lower():
            self.send("no")
            self.expect(
                r"(?i:Proceed with reload[^\n]*\[confirm\]\s*$)", timeout=30)
        self.send("")

    def verify_license(self, intent):
        desired = set(intent["dnac"]["license"].values())
        self.command("terminal length 0")
        state = parse_license_state(self.command("show version", timeout=120))
        if not desired <= set(state["current"]):
            raise RuntimeError("IOS-XE license did not become active after reload")
        return state
