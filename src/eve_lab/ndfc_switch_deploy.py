"""Deploy exact declared DC1 NDFC switches and require per-switch convergence."""

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
    status, body = _api(page, "GET", endpoint + "/inventory/switchesByFabric")
    if status != 200 or not isinstance(body, list):
        raise NexusDashboardBrowserError(
            "NDFC switch inventory failed with HTTP " + str(status))
    return body


def _preview(page, endpoint, serial):
    status, body = _api(page, "GET", endpoint + "/config-preview/" + quote(serial, safe=""))
    if status != 200 or not isinstance(body, list):
        raise NexusDashboardBrowserError(
            "NDFC switch config-preview failed with HTTP " + str(status))
    matching = [item for item in body if isinstance(item, dict)
                and item.get("switchId") == serial]
    if len(matching) != 1:
        raise NexusDashboardBrowserError(
            "NDFC switch config-preview did not identify exactly one requested serial")
    return matching[0]


def deploy_switches(intent, username, password, names=None, timeout=300):
    """Use Cisco's per-switch deploy API; HTTP success alone is insufficient."""
    from playwright.sync_api import sync_playwright

    fabric, desired = compile_switches(intent)
    by_name = {item["name"]: item for item in desired}
    selected = names or list(by_name)
    if len(selected) != len(set(selected)) or set(selected) - set(by_name):
        raise ValueError("Switch selection must contain unique declared DC1 names")
    endpoint = _FABRICS + "/" + quote(fabric, safe="")
    address = intent["management"]["nd"]["address"].split("/")[0]
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, args=["--ignore-certificate-errors-spki-list=" +
                                 _spki_pin(address)])
        try:
            page = browser.new_page()
            page.goto("https://" + address + "/", wait_until="domcontentloaded",
                      timeout=30000)
            _login(page, username, password, timeout)
            inventory = _inventory(page, endpoint)
            observed = {item.get("logicalName"): item for item in inventory}
            if len(inventory) != len(by_name) or set(observed) != set(by_name):
                raise NexusDashboardBrowserError(
                    "NDFC deploy preflight inventory differs from DC1 intent")
            for name, wanted in by_name.items():
                item = observed[name]
                if item.get("ipAddress") != wanted["ip"] or not item.get("serialNumber"):
                    raise NexusDashboardBrowserError(
                        "NDFC deploy preflight identity differs for " + name)
            for name in selected:
                serial = observed[name]["serialNumber"]
                current = _preview(page, endpoint, serial)
                if current.get("status") == "In-Sync" and not current.get("pendingConfig"):
                    results.append({"name": name, "status": "already-in-sync"})
                    print(json.dumps(results[-1]), flush=True)
                    continue
                status, response = _api(
                    page, "POST", endpoint + "/config-deploy/" + quote(serial, safe=""))
                if status != 200:
                    raise NexusDashboardBrowserError(
                        "NDFC per-switch deploy failed for " + name + " with HTTP " +
                        str(status) + ": " + str(response)[:200])
                deadline = time.monotonic() + timeout
                def converged():
                    view = _preview(page, endpoint, serial)
                    return view.get("status") == "In-Sync" and not view.get("pendingConfig")
                _wait_for(page, converged, deadline, "NDFC In-Sync " + name)
                results.append({"name": name, "status": "in-sync"})
                print(json.dumps(results[-1]), flush=True)
            return {"fabric": fabric, "switches": results}
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("intent", type=Path)
    parser.add_argument("--node", action="append", dest="names")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    intent = yaml.safe_load(args.intent.read_text())
    env = _environment(Path.cwd())
    username, password = env.get("CISCO_USERNAME"), env.get("CISCO_PASSWORD")
    if not username or not password:
        raise ValueError("Set CISCO_USERNAME and CISCO_PASSWORD in EVE_ENV_FILE")
    deploy_switches(intent, username, password, args.names, args.timeout)


if __name__ == "__main__":
    main()
