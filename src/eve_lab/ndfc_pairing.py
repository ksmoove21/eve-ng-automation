"""Reconcile declared NDFC vPC pairs through the legacy 12.2.3 LAN API.

Pair creation saves NDFC intent. Recalculate, deploy, and operational proof are
separate steps. This module deliberately refuses a write without exact pair
readback and selected-fabric inventory preflight.
"""

import argparse
import json
import time
from pathlib import Path
from urllib.parse import quote

import yaml

from .config import _environment
from .ndfc_fabric import _BASE, _api
from .ndfc_import import _checked_inventory
from .ndfc_roles import _ROLE_NAMES, _inventory
from .ndfc_switches import compile_switches
from .nexus_dashboard_browser import (
    NexusDashboardBrowserError, _login, _spki_pin, _wait_for,
)


_VPC = _BASE + "/lan-fabric/rest/vpcpair"
_PAIR_KEYS = ("regular_leaf_pair", "border_leaf_pair", "tor_pair")
_METHODS = {"regular_leaf_pair": "Fabric Peering",
            "border_leaf_pair": "physical_vpc_peer_link",
            "tor_pair": "physical_vpc_peer_link"}


def compile_pairs(intent, site="DC1"):
    """Return three exact, nonoverlapping vPC pairs from selected-site intent."""
    fabric, switches = compile_switches(intent, site)
    profile = next(item for item in intent["ndfc_fabrics"]
                   if item["site"] == site)
    by_name = {item["name"]: item for item in switches}
    expected_role = {"regular_leaf_pair": "leaf", "border_leaf_pair": "border",
                     "tor_pair": "tor"}
    pairs = []
    used = set()
    for key in _PAIR_KEYS:
        declaration = profile[key]
        nodes = declaration["nodes"]
        if len(nodes) != 2 or len(set(nodes)) != 2:
            raise ValueError(site + " " + key + " requires two unique switches")
        if (any(name not in by_name or by_name[name]["role"] != expected_role[key]
                for name in nodes) or used.intersection(nodes)):
            raise ValueError(site + " " + key + " has wrong-role or reused members")
        method = declaration.get("method")
        if method != _METHODS[key]:
            raise ValueError(site + " " + key + " has wrong vPC method")
        pairs.append({"kind": key, "nodes": tuple(nodes),
                      "useVirtualPeerlink": key == "regular_leaf_pair"})
        used.update(nodes)
    return fabric, switches, pairs


def _database_id(row):
    """Find NDFC's numeric switch database ID, distinct from its serial."""
    for key in ("switchDbID",):
        value = row.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
        if isinstance(value, str) and value.isdecimal() and int(value) > 0:
            return int(value)
    raise NexusDashboardBrowserError(
        "NDFC inventory lacks the numeric switch database ID for vPC readback")


def _positive_id(value):
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    if isinstance(value, str) and value.isdecimal() and int(value) > 0:
        return int(value)
    return None


def _pair_info(page, database_id, fabric):
    """Normalize installed 12.2.3 per-switch pair info; zero IDs mean unpaired."""
    endpoint = _VPC + "/vpcpairinfo?switchId=" + str(database_id)
    status, body = _api(page, "GET", endpoint)
    if status != 200 or not isinstance(body, dict):
        raise NexusDashboardBrowserError(
            "NDFC vPC pair readback unavailable with HTTP " + str(status))
    first_id = _positive_id(body.get("peerOneDbId"))
    second_id = _positive_id(body.get("peerTwoDbId"))
    first_serial = body.get("peerOneSerialNumber")
    second_serial = body.get("peerTwoSerialNumber")
    if (body.get("peerOneDbId") == 0 and body.get("peerTwoDbId") == 0
            and first_serial is None and second_serial is None):
        return None
    if (not first_id or not second_id or not isinstance(first_serial, str)
            or not first_serial or not isinstance(second_serial, str)
            or not second_serial or body.get("fabricName") != fabric):
        raise NexusDashboardBrowserError(
            "NDFC vPC pair readback has incomplete or foreign identity")
    return {"ids": frozenset((first_id, second_id)),
            "serials": frozenset((first_serial, second_serial)),
            "method": body.get("useVirtualPeerlink")}


def _matches(info, ids, serials, virtual):
    return (info["ids"] == frozenset(ids)
            and info["serials"] == frozenset(serials)
            and (info["method"] is None or info["method"] is virtual))


def _recommendation(page, serial, peer_serial, virtual):
    """Require the selected peer to be available, without treating warnings as blocks."""
    endpoint = (_VPC + "/recommendation?serialNumber=" + quote(serial, safe="") +
                "&useVirtualPeerlink=" + str(virtual).lower())
    status, body = _api(page, "GET", endpoint)
    if status != 200 or not isinstance(body, list):
        raise NexusDashboardBrowserError(
            "NDFC vPC recommendations unavailable with HTTP " + str(status))
    peers = [item for item in body if isinstance(item, dict)
             and item.get("serialNumber") == peer_serial]
    if len(peers) != 1 or peers[0].get("blockSelection") is not False:
        raise NexusDashboardBrowserError(
            "NDFC vPC selected peer is absent or blocked: " + peer_serial)
    return peers[0]


def ensure_pairs(intent, username, password, timeout=300, site="DC1", kinds=()):
    """Save only missing exact pairs; reject conflicting peers and roles."""
    from playwright.sync_api import sync_playwright

    fabric, declared, pairs = compile_pairs(intent, site)
    selected = set(kinds)
    if selected and (len(selected) != len(kinds) or not selected <= set(_PAIR_KEYS)):
        raise ValueError("Pair selection must contain unique declared pair kinds")
    targets = [pair for pair in pairs if not selected or pair["kind"] in selected]
    address = intent["management"]["nd"]["address"].split("/")[0]
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
            by_name = _checked_inventory(_inventory(page, fabric), declared)
            for pair in targets:
                rows = [by_name.get(name) for name in pair["nodes"]]
                if any(row is None for row in rows):
                    raise NexusDashboardBrowserError(
                        "NDFC vPC inventory lacks " + pair["kind"])
                expected_role = _ROLE_NAMES[{
                    "regular_leaf_pair": "leaf", "border_leaf_pair": "border",
                    "tor_pair": "tor"}[pair["kind"]]]
                if any(row.get("switchRole") != expected_role for row in rows):
                    raise NexusDashboardBrowserError(
                        "NDFC vPC role preflight failed for " + pair["kind"])
            changed = []
            for pair in targets:
                rows = [by_name[name] for name in pair["nodes"]]
                serials = tuple(row["serialNumber"] for row in rows)
                ids = tuple(_database_id(row) for row in rows)
                observed = [_pair_info(page, database_id, fabric) for database_id in ids]
                if all(info is not None and _matches(
                        info, ids, serials, pair["useVirtualPeerlink"]) for info in observed):
                    continue
                if any(info is not None for info in observed):
                    raise NexusDashboardBrowserError(
                        "NDFC vPC pairing conflicts with " + pair["kind"])
                _recommendation(page, serials[0], serials[1],
                                pair["useVirtualPeerlink"])
                _recommendation(page, serials[1], serials[0],
                                pair["useVirtualPeerlink"])
                payload = {"peerOneId": serials[0], "peerTwoId": serials[1],
                           "useVirtualPeerlink": pair["useVirtualPeerlink"]}
                status, response = _api(page, "POST", _VPC, payload)
                if status != 200:
                    raise NexusDashboardBrowserError(
                        "NDFC vPC pairing failed for " + pair["kind"] +
                        " with HTTP " + str(status) + ": " + str(response)[:300])
                def ready():
                    infos = [_pair_info(page, database_id, fabric) for database_id in ids]
                    return all(info is not None and _matches(
                        info, ids, serials, pair["useVirtualPeerlink"]) for info in infos)
                _wait_for(page, ready, deadline, "NDFC " + pair["kind"] + " pair")
                changed.append(pair["kind"])
            return {"status": "configured" if changed else "already-configured",
                    "fabric": fabric, "selected": [pair["kind"] for pair in targets],
                    "changed": changed,
                    "method_proof": "requires generated config and device readback"}
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("intent", type=Path)
    parser.add_argument("--site", choices=("DC1", "DC2"), default="DC1")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--pair", action="append", default=[], choices=_PAIR_KEYS,
                        help="Pair kind to reconcile; default is all three")
    parser.add_argument("--check", action="store_true",
                        help="Compile pair intent without NDFC access")
    args = parser.parse_args()
    intent = yaml.safe_load(args.intent.read_text())
    if args.check:
        fabric, _, pairs = compile_pairs(intent, args.site)
        print(json.dumps({"fabric": fabric, "pairs": pairs}, indent=2))
        return
    env = _environment(Path.cwd())
    username, password = env.get("CISCO_USERNAME"), env.get("CISCO_PASSWORD")
    if not username or not password:
        raise ValueError("Set CISCO_USERNAME and CISCO_PASSWORD in EVE_ENV_FILE")
    print(json.dumps(ensure_pairs(intent, username, password, args.timeout,
                                  args.site, args.pair)))


if __name__ == "__main__":
    main()

