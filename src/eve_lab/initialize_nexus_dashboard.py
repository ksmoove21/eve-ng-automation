"""Nexus Dashboard first-boot intent and serial-console initialization."""

from ipaddress import AddressValueError, IPv4Address, IPv4Interface
import re
import socket

import yaml

from .device_console import Console


TEMPLATE = "nd"
_VERSION = re.compile(r"Nexus Dashboard\s+([0-9][A-Za-z0-9._()-]*)", re.I)
_CLUSTER_NAME = re.compile(
    r"(?=.{1,63}\Z)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_DOMAIN = re.compile(
    r"(?=.{1,253}\Z)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")


def _exact(data, fields, label):
    if not isinstance(data, dict) or set(data) != set(fields):
        raise ValueError(label + " requires exactly " + ", ".join(fields))


def _network(value, label):
    try:
        interface = IPv4Interface(value)
    except (TypeError, ValueError):
        raise ValueError(label + " address must use IPv4 CIDR interface notation") from None
    if (interface.network.prefixlen < 31
            and interface.ip in (interface.network.network_address,
                                 interface.network.broadcast_address)):
        raise ValueError(label + " address must be a usable host address")
    return interface


def _gateway(value, interface, label):
    try:
        gateway = IPv4Address(value)
    except (TypeError, ValueError):
        raise ValueError(label + " gateway must be an IPv4 address") from None
    if gateway not in interface.network or gateway in (
            interface.network.network_address, interface.network.broadcast_address):
        raise ValueError(label + " gateway must be a usable address in the declared subnet")
    if gateway == interface.ip:
        raise ValueError(label + " gateway must differ from the node address")
    return gateway


def _address_list(values, label):
    if not isinstance(values, list) or not values or len(values) != len(set(values)):
        raise ValueError(label + " must be a nonempty unique list")
    try:
        return [str(IPv4Address(value)) for value in values]
    except (TypeError, ValueError):
        raise ValueError(label + " entries must be IPv4 addresses") from None


def _ntp_list(values):
    """Accept documented NTP targets as either IPv4 literals or hostnames."""
    if not isinstance(values, list) or not values or len(values) != len(set(values)):
        raise ValueError("ntp_servers must be a nonempty unique list")
    normalized = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("ntp_servers entries must be IPv4 addresses or DNS hostnames")
        try:
            normalized.append(str(IPv4Address(value)))
        except ValueError:
            if not _DOMAIN.fullmatch(value):
                raise ValueError(
                    "ntp_servers entries must be IPv4 addresses or DNS hostnames") from None
            normalized.append(value)
    return normalized


def _derived_service_ips(interface, gateway, count, label):
    """Derive a bounded, usable service-IP pool after one node interface."""
    if type(count) is not int or not 1 <= count <= 32:
        raise ValueError(label + " service-IP count must be an integer from 1 to 32")
    addresses = []
    for offset in range(1, count + 1):
        try:
            candidate = interface.ip + offset
        except AddressValueError:
            raise ValueError(label + " service addresses exceed the declared subnet") from None
        if (candidate not in interface.network
                or candidate in (interface.network.network_address,
                                 interface.network.broadcast_address)
                or candidate == gateway):
            raise ValueError(label + " derived service addresses must be usable and not the gateway")
        addresses.append(str(candidate))
    return addresses


def normalize_intent(data):
    """Validate declarative first-boot and supported post-bootstrap intent."""
    version = data.get("schema_version") if isinstance(data, dict) else None
    if version == 1:
        fields = (
            "schema_version", "cluster_name", "management", "data",
            "dns_servers", "search_domains", "ntp_servers",
            "persistent_service_ip_count", "fabric_controller",
        )
    elif version == 2:
        fields = (
            "schema_version", "cluster_name", "management", "data",
            "dns_servers", "search_domains", "ntp_servers",
            "service_ip_pools", "fabric_controller",
        )
    else:
        raise ValueError("Nexus Dashboard bootstrap schema_version must be 1 or 2")
    _exact(data, fields, "Nexus Dashboard bootstrap")
    cluster_name = data["cluster_name"]
    if not isinstance(cluster_name, str) or not _CLUSTER_NAME.fullmatch(cluster_name):
        raise ValueError("cluster_name must be an RFC 1123 lowercase hostname label")

    networks = {}
    for label in ("management", "data"):
        value = data[label]
        _exact(value, ("address", "gateway"), label)
        interface = _network(value["address"], label)
        gateway = _gateway(value["gateway"], interface, label)
        networks[label] = {
            "address": str(interface), "gateway": str(gateway),
        }
    management = IPv4Interface(networks["management"]["address"])
    data_network = IPv4Interface(networks["data"]["address"])
    if management.network.overlaps(data_network.network):
        raise ValueError("management and data networks must use different subnets")

    search_domains = data["search_domains"]
    if (not isinstance(search_domains, list) or not search_domains
            or len(search_domains) != len(set(search_domains))
            or any(not isinstance(value, str) or not _DOMAIN.fullmatch(value)
                   for value in search_domains)):
        raise ValueError("search_domains must be a nonempty unique list of DNS domains")

    if version == 1:
        pool_counts = {"management": 0, "data": data["persistent_service_ip_count"]}
    else:
        pool_counts = data["service_ip_pools"]
        _exact(pool_counts, ("management", "data"), "service_ip_pools")
    management_service_ips = ([] if version == 1 else _derived_service_ips(
        management, IPv4Address(networks["management"]["gateway"]),
        pool_counts["management"], "management"))
    data_service_ips = _derived_service_ips(
        data_network, IPv4Address(networks["data"]["gateway"]),
        pool_counts["data"], "data")
    if set(management_service_ips) & set(data_service_ips):
        raise ValueError("management and data service-IP pools must not overlap")

    fabric = data["fabric_controller"]
    _exact(fabric, ("enabled", "device_management_connectivity"),
           "fabric_controller")
    if type(fabric["enabled"]) is not bool:
        raise ValueError("fabric_controller enabled must be boolean")
    connectivity = fabric["device_management_connectivity"]
    if connectivity not in ("data", "management"):
        raise ValueError("device_management_connectivity must be data or management")

    return {
        "schema_version": version,
        "cluster_name": cluster_name,
        "management": networks["management"],
        "data": networks["data"],
        "dns_servers": _address_list(data["dns_servers"], "dns_servers"),
        "search_domains": list(search_domains),
        "ntp_servers": _ntp_list(data["ntp_servers"]),
        "service_ip_pools": {"Management": management_service_ips, "Data": data_service_ips},
        # Backward-compatible alias for data-plane callers.
        "persistent_service_ips": data_service_ips,
        "fabric_controller": {
            "enabled": fabric["enabled"],
            "device_management_connectivity": connectivity,
        },
        "cluster_leader": True,
    }


def management_https_ready(intent, timeout=3):
    """Return whether the declared management address accepts HTTPS TCP."""
    if not 0 < timeout <= 30:
        raise ValueError("Nexus Dashboard HTTPS probe timeout must be between 1 and 30 seconds")
    address = str(IPv4Interface(intent["management"]["address"]).ip)
    try:
        connection = socket.create_connection((address, 443), timeout=timeout)
    except OSError:
        return False
    connection.close()
    return True

def load_bootstrap(path):
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ValueError("Invalid Nexus Dashboard bootstrap YAML") from error
    return normalize_intent(data)


class NexusDashboardConsole(Console):
    """Drive only the documented and live-observed pre-3.2.2 serial setup."""

    _PROMPTS = (
        r"(?i:Press any key to run first-boot setup on this console\.\.\.|"
        r"Press Enter to manually bootstrap your node\.\.\.|"
        r"Reenter Admin Password:\s*$|Admin Password:\s*$|"
        r"IP Address/Mask:\s*$|Gateway:\s*$|"
        r"Is Cluster Leader\?[^\n]*\(Y/n\):\s*$|"
        r"Is this the cluster leader\?:\s*$|"
        r"Re-enter config\?\s*\(y/N\):\s*$|"
        r"System configured successfully|System UI online[^\n]*|"
        r"(?:login|Username):\s*$)"
    )

    def initialize(self, intent, username=None, password=None):
        if (not isinstance(password, str) or not password
                or any(ord(char) < 32 or ord(char) == 127 for char in password)):
            raise ValueError("CISCO_PASSWORD must be nonempty without control characters")
        stages = set()
        version = None
        for _ in range(14):
            observed, match = self.expect(
                self._PROMPTS, timeout=self.boot_timeout, wake=False, latest=True)
            release = _VERSION.search(observed)
            if release:
                version = release.group(1)
            prompt = match.group().strip()
            lower = prompt.lower()
            if ("system configured successfully" in lower
                    or "system ui online" in lower):
                return {"status": "configured", "release": version,
                        "console_stages": sorted(stages)}
            if lower.startswith(("login:", "username:")):
                return {"status": "already-configured", "release": version,
                        "console_stages": sorted(stages)}
            if "press any key" in lower:
                stage, response = "setup-trigger", " "
            elif "press enter" in lower:
                stage, response = "manual-bootstrap", ""
            elif lower.startswith("reenter admin password"):
                stage, response = "password-confirm", password
            elif lower.startswith("admin password"):
                stage, response = "password", password
            elif lower.startswith("ip address/mask"):
                stage, response = "management-address", intent["management"]["address"]
            elif lower.startswith("gateway"):
                stage, response = "management-gateway", intent["management"]["gateway"]
            elif "cluster leader" in lower:
                stage, response = "cluster-leader", "y" if intent["cluster_leader"] else "n"
            elif lower.startswith("re-enter config"):
                stage, response = "review", "n"
            else:
                raise RuntimeError("Unrecognized Nexus Dashboard first-boot state")
            if stage in stages:
                raise RuntimeError(
                    "Nexus Dashboard repeated a first-boot prompt; value may have been rejected")
            stages.add(stage)
            # Console.send appends CR only. LF must not be sent because this guest
            # consumes it as a second empty response at adjacent prompts.
            self.send(response)
        raise RuntimeError("Nexus Dashboard first-boot setup did not reach a terminal state")
