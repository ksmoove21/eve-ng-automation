"""Read-only NDFC switch discovery preflight for a declared DC1 fabric."""

import argparse
import json
from pathlib import Path
from urllib.parse import quote

import yaml

from .config import _environment
from .ndfc_fabric import _FABRICS, _api, compile_fabric
from .nexus_dashboard_browser import NexusDashboardBrowserError, _login, _spki_pin


def compile_switches(intent):
    """Pair active DC1 switch names, management IPs, and declared NDFC roles."""
    name, _ = compile_fabric(intent)
    fabric = next(item for item in intent["ndfc_fabrics"] if item["site"] == "DC1")
    active = set(intent["scope"]["activation_set"])
    assignments = intent["management"]["fabric_edge"]["assignments"]
    groups = [
        ("spine", ["N9K-Spine-1", "N9K-Spine-2"]),
        ("leaf", fabric["regular_leaf_pair"]["nodes"]),
        ("border", fabric["border_leaf_pair"]["nodes"]),
        ("tor", fabric["tor_pair"]["nodes"]),
    ]
    switches = []
    for role, nodes in groups:
        if len(nodes) != 2:
            raise ValueError("DC1 " + role + " requires exactly two declared switches")
        for node in nodes:
            if node not in active:
                raise ValueError("Inactive switch in DC1 fabric: " + node)
            switches.append({
                "name": node,
                "ip": assignments[node].split("/")[0],
                "role": role,
            })
    if len({item["name"] for item in switches}) != 8:
        raise ValueError("DC1 switch roles must cover eight unique devices")
    if len({item["ip"] for item in switches}) != 8:
        raise ValueError("DC1 management IPs must be unique")
    return name, switches


def check_switch_reachability(intent, username, password):
    """Use Cisco's test-reachability endpoint; this never imports switches."""
    from playwright.sync_api import sync_playwright

    fabric_name, switches = compile_switches(intent)
    address = intent["management"]["nd"]["address"].split("/")[0]
    endpoint = (_FABRICS + "/" + quote(fabric_name, safe="") +
                "/inventory/test-reachability")
    request = {
        "seedIP": ",".join(item["ip"] for item in switches),
        "username": username,
        "password": password,
        "switches": [],
        "preserveConfig": False,
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, args=["--ignore-certificate-errors-spki-list=" +
                                 _spki_pin(address)])
        try:
            page = browser.new_page()
            page.goto("https://" + address + "/", wait_until="domcontentloaded",
                      timeout=30000)
            _login(page, username, password, 90)
            status, body = _api(page, "POST", endpoint, request)
        finally:
            browser.close()
    if status != 200 or not isinstance(body, list):
        raise NexusDashboardBrowserError(
            "NDFC switch reachability check failed with HTTP " + str(status))
    by_ip = {item.get("ipaddr"): item for item in body if isinstance(item, dict)}
    if set(by_ip) != {item["ip"] for item in switches}:
        raise NexusDashboardBrowserError("NDFC reachability returned unexpected switch IPs")
    result = []
    for desired in switches:
        observed = by_ip[desired["ip"]]
        result.append({
            **desired,
            "observed_name": observed.get("sysName"),
            "platform": observed.get("platform"),
            "version": observed.get("version"),
            "serial_number": observed.get("serialNumber"),
            "manageable": (observed.get("sysName") == desired["name"]
                           and bool(observed.get("serialNumber"))
                           and all(observed.get(key) is True for key in
                                   ("reachable", "auth", "valid", "selectable"))),
            "reason": observed.get("statusReason"),
        })
    failed = [item["name"] for item in result if not item["manageable"]]
    if failed:
        raise NexusDashboardBrowserError(
            "NDFC switch identity or manageability preflight failed: " +
            ", ".join(failed))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("intent", type=Path)
    parser.add_argument("--check", action="store_true",
                        help="Compile switch targets without NDFC access")
    args = parser.parse_args()
    intent = yaml.safe_load(args.intent.read_text())
    if args.check:
        name, switches = compile_switches(intent)
        print(json.dumps({"fabric": name, "switches": switches}, indent=2))
        return
    env = _environment(Path.cwd())
    username, password = env.get("CISCO_USERNAME"), env.get("CISCO_PASSWORD")
    if not username or not password:
        raise ValueError("Set CISCO_USERNAME and CISCO_PASSWORD in EVE_ENV_FILE")
    print(json.dumps(check_switch_reachability(intent, username, password), indent=2))


if __name__ == "__main__":
    main()
