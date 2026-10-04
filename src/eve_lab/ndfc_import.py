"""Import the declared site switches into NDFC after exact identity preflight."""

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


def _selected_switches(intent, site, defer):
    fabric, declared = compile_switches(intent, site)
    deferred = tuple(defer)
    names = {item["name"] for item in declared}
    if (len(set(deferred)) != len(deferred) or not set(deferred) <= names
            or len(deferred) == len(declared)):
        raise ValueError("Deferred switches must be unique declared names and leave a target")
    selected = [item for item in declared if item["name"] not in deferred]
    return fabric, declared, selected


def _checked_inventory(items, declared):
    desired = {item["name"]: item for item in declared}
    by_name = {item.get("logicalName"): item for item in items
               if isinstance(item, dict)}
    if (len(by_name) != len(items) or not set(by_name) <= set(desired)
            or any(item.get("ipAddress") != desired[name]["ip"]
                   or not item.get("serialNumber")
                   for name, item in by_name.items())):
        raise NexusDashboardBrowserError(
            "NDFC fabric inventory differs from exact declared switches")
    return by_name


def import_switches(intent, username, password, timeout=600, site="DC1", defer=()):
    """Discover selected declared switches; later runs add missing members only."""
    from playwright.sync_api import sync_playwright

    name, declared, selected = _selected_switches(intent, site, defer)
    profile = next(item for item in intent["ndfc_fabrics"] if item["site"] == site)
    if profile["switch_import"] != {"greenfield": True, "preserve_config": False}:
        raise ValueError(site + " import must be greenfield with Preserve Config NO")
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
            existing = _checked_inventory(_inventory(page, endpoint), declared)
            pending = [item for item in selected if item["name"] not in existing]
            if not pending:
                return {"status": "already-imported", "fabric": name,
                        "declared_count": len(declared),
                        "observed_count": len(existing)}
            request = {
                "seedIP": ",".join(item["ip"] for item in pending),
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
            if set(by_ip) != {item["ip"] for item in pending}:
                raise NexusDashboardBrowserError(
                    "NDFC reachability returned unexpected management IPs")
            imports = []
            for item in pending:
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
            expected = {**{name: item["serialNumber"]
                           for name, item in existing.items()},
                        **{item["name"]: by_ip[item["ip"]]["serialNumber"]
                           for item in pending}}
            observed = {}
            def ready():
                observed["inventory"] = _inventory(page, endpoint)
                by_name = _checked_inventory(observed["inventory"], declared)
                return (set(by_name) == set(expected) and
                        all(by_name[item]["serialNumber"] == serial
                            for item, serial in expected.items()))
            _wait_for(page, ready, deadline, "NDFC selected switch import readback")
            return {
                "status": "imported", "fabric": name,
                "declared_count": len(declared),
                "imported_count": len(pending),
                "observed_count": len(observed["inventory"]),
            }
        finally:
            browser.close()


# Preserve the original DC1 entry point for existing callers.
import_dc1_switches = import_switches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("intent", type=Path)
    parser.add_argument("--site", choices=("DC1", "DC2"), default="DC1")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--defer", action="append", default=[],
                        help="Declared switch to add on a later run")
    args = parser.parse_args()
    intent = yaml.safe_load(args.intent.read_text())
    env = _environment(Path.cwd())
    username, password = env.get("CISCO_USERNAME"), env.get("CISCO_PASSWORD")
    if not username or not password:
        raise ValueError("Set CISCO_USERNAME and CISCO_PASSWORD in EVE_ENV_FILE")
    print(json.dumps(import_switches(
        intent, username, password, args.timeout, args.site, args.defer)))


if __name__ == "__main__":
    main()
