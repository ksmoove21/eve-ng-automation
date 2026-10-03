"""Import the declared DC1 switches into NDFC after exact identity preflight."""

import argparse
import json
import time
from pathlib import Path
from urllib.parse import quote

import yaml

from .config import _environment
from .ndfc_fabric import _FABRICS, _api
from .ndfc_switches import compile_switches
from .nexus_dashboard_browser import (
    NexusDashboardBrowserError, _login, _spki_pin, _wait_for,
)


def _inventory(page, endpoint):
    status, items = _api(page, "GET", endpoint + "/inventory/switchesByFabric")
    if status != 200 or not isinstance(items, list):
        raise NexusDashboardBrowserError(
            "NDFC fabric switch inventory unavailable with HTTP " + str(status))
    return items


def import_dc1_switches(intent, username, password, timeout=600):
    """Discover only exact, manageable DC1 targets; preserve-config is disabled."""
    from playwright.sync_api import sync_playwright

    name, desired = compile_switches(intent)
    profile = next(item for item in intent["ndfc_fabrics"] if item["site"] == "DC1")
    if profile["switch_import"] != {"greenfield": True, "preserve_config": False}:
        raise ValueError("DC1 import must be greenfield with Preserve Config NO")
    address = intent["management"]["nd"]["address"].split("/")[0]
    endpoint = _FABRICS + "/" + quote(name, safe="")
    deadline = time.monotonic() + timeout
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, args=["--ignore-certificate-errors-spki-list=" +
                                 _spki_pin(address)])
        try:
            page = browser.new_page()
            page.goto("https://" + address + "/", wait_until="domcontentloaded",
                      timeout=30000)
            _login(page, username, password, max(1, deadline - time.monotonic()))
            existing = _inventory(page, endpoint)
            if existing:
                raise NexusDashboardBrowserError(
                    "NDFC fabric inventory is nonempty; inspect before any further import")
            request = {
                "seedIP": ",".join(item["ip"] for item in desired),
                "username": username,
                "password": password,
                "switches": [],
                "preserveConfig": False,
            }
            status, candidates = _api(
                page, "POST", endpoint + "/inventory/test-reachability", request)
            if status != 200 or not isinstance(candidates, list):
                raise NexusDashboardBrowserError(
                    "NDFC reachability preflight failed with HTTP " + str(status))
            by_ip = {item.get("ipaddr"): item for item in candidates
                     if isinstance(item, dict)}
            if set(by_ip) != {item["ip"] for item in desired}:
                raise NexusDashboardBrowserError(
                    "NDFC reachability returned unexpected management IPs")
            imports = []
            for item in desired:
                observed = by_ip[item["ip"]]
                if (observed.get("sysName") != item["name"]
                        or not observed.get("serialNumber")
                        or not observed.get("deviceIndex")
                        or not all(observed.get(flag) is True for flag in
                                   ("reachable", "auth", "valid", "selectable"))):
                    raise NexusDashboardBrowserError(
                        "NDFC switch is not exactly manageable: " + item["name"])
                imports.append({
                    key: observed[key] for key in
                    ("deviceIndex", "ipaddr", "platform", "serialNumber",
                     "sysName", "version")
                })
            request["switches"] = imports
            status, response = _api(
                page, "POST", endpoint + "/inventory/discover", request)
            if status != 200:
                raise NexusDashboardBrowserError(
                    "NDFC greenfield switch import failed with HTTP " +
                    str(status) + ": " + str(response)[:300])
            observed = {}
            def ready():
                observed["inventory"] = _inventory(page, endpoint)
                return len(observed["inventory"]) == len(desired)
            _wait_for(page, ready, deadline, "NDFC eight-switch import readback")
            return {
                "status": "imported",
                "fabric": name,
                "declared_count": len(desired),
                "observed_count": len(observed["inventory"]),
            }
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("intent", type=Path)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    intent = yaml.safe_load(args.intent.read_text())
    env = _environment(Path.cwd())
    username, password = env.get("CISCO_USERNAME"), env.get("CISCO_PASSWORD")
    if not username or not password:
        raise ValueError("Set CISCO_USERNAME and CISCO_PASSWORD in EVE_ENV_FILE")
    print(json.dumps(import_dc1_switches(
        intent, username, password, args.timeout)))


if __name__ == "__main__":
    main()
