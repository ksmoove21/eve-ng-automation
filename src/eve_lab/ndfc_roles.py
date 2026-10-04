"""Assign declared site NDFC switch roles after exact inventory preflight."""

import argparse
import json
import time
from pathlib import Path
from urllib.parse import quote

import yaml

from .config import _environment
from .ndfc_fabric import _BASE, _FABRICS, _api
from .ndfc_import import _selected_switches, _checked_inventory
from .nexus_dashboard_browser import (
    NexusDashboardBrowserError, _login, _spki_pin, _wait_for,
)


_ROLES = _BASE + "/lan-fabric/rest/control/switches/roles"
_ROLE_NAMES = {"spine": "spine", "leaf": "leaf", "border": "border gateway", "tor": "tor"}


def _inventory(page, fabric):
    status, body = _api(
        page, "GET", _FABRICS + "/" + quote(fabric, safe="") +
        "/inventory/switchesByFabric")
    if status != 200 or not isinstance(body, list):
        raise NexusDashboardBrowserError(
            "NDFC switch inventory unavailable with HTTP " + str(status))
    return body


def ensure_switch_roles(intent, username, password, timeout=300, site="DC1", defer=()):
    """Assign declared roles to selected imported switches, preserving other rows."""
    from playwright.sync_api import sync_playwright

    fabric, declared, selected = _selected_switches(intent, site, defer)
    address = intent["management"]["nd"]["address"].split("/")[0]
    desired = {item["name"]: item for item in selected}
    deadline = time.monotonic() + timeout
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, args=["--ignore-certificate-errors-spki-list=" +
                                 _spki_pin(address)])
        try:
            page = browser.new_page()
            page.goto("https://" + address + "/", wait_until="domcontentloaded",
                      timeout=30000)
            _login(page, username, password, timeout)
            observed = _inventory(page, fabric)
            by_name = _checked_inventory(observed, declared)
            if not set(desired) <= set(by_name):
                raise NexusDashboardBrowserError(
                    "NDFC role preflight inventory lacks selected declared switches")
            changes = []
            for name, target in desired.items():
                item = by_name[name]
                role = _ROLE_NAMES[target["role"]]
                if item.get("switchRole") != role:
                    changes.append({"serialNumber": item["serialNumber"], "role": role})
            if not changes:
                return {"status": "already-configured", "fabric": fabric,
                        "count": len(desired)}
            status, response = _api(page, "POST", _ROLES, changes)
            if status != 200:
                raise NexusDashboardBrowserError(
                    "NDFC switch role assignment failed with HTTP " +
                    str(status) + ": " + str(response)[:300])
            initial_names = set(by_name)
            def ready():
                items = _inventory(page, fabric)
                by_name = _checked_inventory(items, declared)
                return (set(by_name) == initial_names and
                        all(by_name[name].get("switchRole") ==
                            _ROLE_NAMES[target["role"]]
                            for name, target in desired.items()))
            _wait_for(page, ready, deadline, "NDFC selected switch roles")
            return {"status": "configured", "fabric": fabric,
                    "changed": len(changes)}
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("intent", type=Path)
    parser.add_argument("--site", choices=("DC1", "DC2"), default="DC1")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--defer", action="append", default=[],
                        help="Declared switch to configure on a later run")
    args = parser.parse_args()
    intent = yaml.safe_load(args.intent.read_text())
    env = _environment(Path.cwd())
    username, password = env.get("CISCO_USERNAME"), env.get("CISCO_PASSWORD")
    if not username or not password:
        raise ValueError("Set CISCO_USERNAME and CISCO_PASSWORD in EVE_ENV_FILE")
    print(json.dumps(ensure_switch_roles(intent, username, password, args.timeout, args.site, args.defer)))


if __name__ == "__main__":
    main()

