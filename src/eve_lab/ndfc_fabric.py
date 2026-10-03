"""Reconcile a declared NDFC VXLAN EVPN fabric through documented LAN APIs."""

import argparse
import json
import time
from ipaddress import ip_network
from pathlib import Path
from urllib.parse import quote

import yaml

from .config import _environment
from .nexus_dashboard_browser import (
    NexusDashboardBrowserError, _login, _spki_pin, _wait_for,
)


_BASE = "/appcenter/cisco/ndfc/api/v1"
_FABRICS = _BASE + "/lan-fabric/rest/control/fabrics"
_TEMPLATE = _BASE + "/configtemplate/rest/config/templates/Easy_Fabric"


def compile_fabric(intent, site="DC1"):
    """Map declared site intent to the live Easy_Fabric 12.2.3 NV schema."""
    profiles = [item for item in intent["ndfc_fabrics"] if item["site"] == site]
    if len(profiles) != 1 or site != "DC1":
        raise ValueError("Exactly one active DC1 fabric is required")
    fabric = profiles[0]
    if fabric["mode"] != "Data Center VXLAN EVPN":
        raise ValueError("DC1 must use the Data Center VXLAN EVPN template")
    if fabric["replication"] != "ingress" or fabric["multicast_replication"] != "disabled":
        raise ValueError("DC1 requires ingress replication without multicast")
    pools = fabric["infrastructure_pools"]
    for name in ("underlay_links", "loopbacks", "anycast_vtep", "vpc_peer_keepalive"):
        if ip_network(pools[name]).prefixlen != 24:
            raise ValueError("DC1 infrastructure pool " + name + " must be /24")
    if len({str(ip_network(value)) for value in pools.values()}) != len(pools):
        raise ValueError("DC1 infrastructure pools overlap")
    if fabric["vpc_peer_keepalive_option"] != "management":
        raise ValueError("NDFC 12.2.3 management vPC keepalive mapping is required")
    if fabric["leaf_pre_interfaces_freeform"] != "feature dhcp":
        raise ValueError("DC1 leaf pre-interface DHCP feature intent is required")
    vnis = intent["tenants"]["vni_policy"]
    if vnis["l2_range"] != "20000-29999" or vnis["l3_range"] != "30000-39999":
        raise ValueError("DC1 VNI ranges do not match owner intent")
    for tenant in intent["tenants"]["dc1"]:
        if not 30000 <= tenant["vrf_vni"] <= 39999:
            raise ValueError("DC1 VRF VNI is outside the declared range")
        for network in tenant["networks"]:
            if not 20000 <= network["vni"] <= 29999:
                raise ValueError("DC1 network VNI is outside the declared range")
    low, high = map(int, fabric["network_vlan_range"].split("-"))
    if any(not low <= network["vlan"] <= high
           for tenant in intent["tenants"]["dc1"] for network in tenant["networks"]):
        raise ValueError("DC1 tenant VLAN is outside the declared network VLAN range")
    if fabric["switch_import"] != {"greenfield": True, "preserve_config": False}:
        raise ValueError("DC1 switch import must be greenfield without preserve config")
    name = fabric["name"]
    nv = {
        "FABRIC_NAME": name,
        "FABRIC_TYPE": "Switch_Fabric",
        "BGP_AS": str(fabric["bgp_asn"]),
        "SITE_ID": str(fabric["bgp_asn"]),
        "REPLICATION_MODE": "Ingress",
        "LOOPBACK0_IP_RANGE": pools["loopbacks"],
        "LOOPBACK1_IP_RANGE": pools["anycast_vtep"],
        "SUBNET_RANGE": pools["underlay_links"],
        "SUBNET_TARGET_MASK": "30",
        "L2_SEGMENT_ID_RANGE": vnis["l2_range"],
        "L3_PARTITION_ID_RANGE": vnis["l3_range"],
        "NETWORK_VLAN_RANGE": fabric["network_vlan_range"],
        "VPC_PEER_KEEP_ALIVE_OPTION": "management",
        "ENABLE_TENANT_DHCP": "true",
        "preInterfaceConfigLeaf": fabric["leaf_pre_interfaces_freeform"],
        "SPINE_COUNT": "2",
        "RR_COUNT": "2",
    }
    return name, nv


def _api(page, method, endpoint, payload=None):
    result = page.evaluate("""async ({method, endpoint, payload}) => {
        const options = {method};
        if (payload !== null) {
            options.headers = {'Content-Type': 'application/json; charset=utf-8'};
            options.body = JSON.stringify(payload);
        }
        const response = await fetch(endpoint, options);
        return {status: response.status, body: await response.text()};
    }""", {"method": method, "endpoint": endpoint, "payload": payload})
    try:
        body = json.loads(result["body"])
    except (KeyError, TypeError, json.JSONDecodeError):
        body = result.get("body")
    return result["status"], body


def _find_fabric(page, name):
    status, listing = _api(page, "GET", _FABRICS)
    if status != 200 or not isinstance(listing, list):
        raise NexusDashboardBrowserError("NDFC documented fabric list is unavailable")
    matching = [item for item in listing if isinstance(item, dict)
                and item.get("fabricName") == name]
    if len(matching) > 1:
        raise NexusDashboardBrowserError("NDFC returned duplicate fabric " + name)
    return matching[0] if matching else None


def _verify_fabric(item, desired):
    if item.get("templateName") != "Easy_Fabric":
        raise NexusDashboardBrowserError("Existing NDFC fabric has a different template")
    actual = item.get("nvPairs")
    if not isinstance(actual, dict):
        raise NexusDashboardBrowserError("NDFC fabric NV readback is unavailable")
    mismatched = [key for key, value in desired.items()
                  if str(actual.get(key, "")).strip() != str(value).strip()]
    if mismatched:
        raise NexusDashboardBrowserError(
            "NDFC fabric conflicts with declared NV pairs: " + ", ".join(mismatched))


def ensure_fabric(intent, username, password, timeout=300):
    """Create DC1 only when absent, then verify every declared NV pair."""
    name, desired = compile_fabric(intent)
    from playwright.sync_api import sync_playwright
    address = intent["management"]["nd"]["address"].split("/")[0]
    deadline = time.monotonic() + timeout
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, args=["--ignore-certificate-errors-spki-list=" + _spki_pin(address)])
        try:
            page = browser.new_page()
            page.goto("https://" + address + "/", wait_until="domcontentloaded",
                      timeout=min(30000, int(timeout * 1000)))
            _login(page, username, password, max(1, deadline - time.monotonic()))
            status, template = _api(page, "GET", _TEMPLATE)
            if status != 200 or not isinstance(template, dict):
                raise NexusDashboardBrowserError("NDFC Easy_Fabric template is unavailable")
            available = {item.get("name") for item in template.get("parameters", [])
                         if isinstance(item, dict)}
            missing = set(desired) - available
            if missing:
                raise NexusDashboardBrowserError(
                    "Live NDFC template lacks declared NV fields: " + ", ".join(sorted(missing)))
            current = _find_fabric(page, name)
            if current:
                _verify_fabric(current, desired)
                return {"status": "already-configured", "fabric": name}
            endpoint = _FABRICS + "/" + quote(name, safe="") + "/Easy_Fabric"
            status, response = _api(page, "POST", endpoint, desired)
            if status != 200:
                raise NexusDashboardBrowserError(
                    "NDFC fabric creation failed with HTTP " + str(status) +
                    ": " + str(response)[:300])
            observed = {}
            def ready():
                observed["fabric"] = _find_fabric(page, name)
                return observed["fabric"] is not None
            _wait_for(page, ready, deadline, "NDFC DC1 fabric readback")
            _verify_fabric(observed["fabric"], desired)
            return {"status": "created", "fabric": name}
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("intent", type=Path)
    parser.add_argument("--check", action="store_true", help="Compile without live access")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    intent = yaml.safe_load(args.intent.read_text())
    if args.check:
        name, nv = compile_fabric(intent)
        print(json.dumps({"fabric": name, "template": "Easy_Fabric", "nvPairs": nv}, indent=2))
        return
    env = _environment(Path.cwd())
    username, password = env.get("CISCO_USERNAME"), env.get("CISCO_PASSWORD")
    if not username or not password:
        raise ValueError("Set CISCO_USERNAME and CISCO_PASSWORD in EVE_ENV_FILE or environment")
    print(json.dumps(ensure_fabric(intent, username, password, args.timeout)))


if __name__ == "__main__":
    main()
