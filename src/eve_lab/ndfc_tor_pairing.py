"""Associate a declared NDFC leaf vPC pair with its double-sided ToR pair.

This saves the installed 12.2.3 ToR Pairing GUI intent. Config-save, deploy,
and operational Po/vPC checks are separate acceptance steps.
"""

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import quote

import yaml

from .config import _environment
from .ndfc_fabric import _BASE, _api
from .ndfc_import import _checked_inventory
from .ndfc_pairing import _database_id, _matches, _pair_info, compile_pairs
from .ndfc_roles import _inventory
from .nexus_dashboard_browser import (
    NexusDashboardBrowserError, _login, _spki_pin, _wait_for,
)


_TOR = _BASE + "/lan-fabric/rest/control/tor/fabrics"
_ETHERNET = re.compile(r"Ethernet\d+/\d+\Z")


def compile_tor_pair(intent, topology, site="DC1"):
    """Require four exclusive, declared direct links between exact pair members."""
    fabric, switches, pairs = compile_pairs(intent, site)
    by_kind = {item["kind"]: item for item in pairs}
    leaf = by_kind["regular_leaf_pair"]["nodes"]
    tor = by_kind["tor_pair"]["nodes"]
    expected = {(l, t) for l in leaf for t in tor}
    links = {}
    used_ports = set()
    for link in topology.get("links", []):
        if not isinstance(link, dict) or "from" not in link or "to" not in link:
            continue
        ends = (link["from"], link["to"])
        if not all(isinstance(end, dict) for end in ends):
            raise ValueError("Declared direct link has invalid endpoints")
        names = {end.get("node") for end in ends}
        if len(names) != 2 or not names <= set(leaf + tor):
            continue
        if len(names & set(leaf)) != 1 or len(names & set(tor)) != 1:
            continue
        l_end = next(end for end in ends if end["node"] in leaf)
        t_end = next(end for end in ends if end["node"] in tor)
        pair = l_end["node"], t_end["node"]
        if pair in links or any(not _ETHERNET.fullmatch(end.get("interface", ""))
                                for end in (l_end, t_end)):
            raise ValueError(site + " leaf-ToR direct link is duplicated or invalid")
        for end in (l_end, t_end):
            port = end["node"], end["interface"]
            if port in used_ports:
                raise ValueError(site + " leaf-ToR direct links share a port")
            used_ports.add(port)
        links[pair] = (l_end["interface"], t_end["interface"])
    if set(links) != expected:
        raise ValueError(site + " leaf-ToR pairing requires all four direct links")
    return {"fabric": fabric, "switches": switches, "leaf": leaf,
            "tor": tor, "links": links}


def _id_keys(serials):
    leaf = tuple(serials["leaf"])
    tor = tuple(serials["tor"])
    if len(set(leaf + tor)) != 4:
        raise ValueError("ToR pairing requires four distinct serial numbers")
    return ({serial + "_PO" for serial in leaf + tor} |
            {"~".join(leaf) + "_VPC", "~".join(tor) + "_VPC"})


def _association_payload(serials, proposed):
    """Build the installed GUI's exact JSON-string poVpc payload."""
    if not isinstance(proposed, dict) or set(proposed) != _id_keys(serials):
        raise NexusDashboardBrowserError("NDFC proposed ToR Po/vPC IDs differ")
    if any(not isinstance(value, str) or not value.isdecimal() or
           not 1 <= int(value) <= 4096 for value in proposed.values()):
        raise NexusDashboardBrowserError("NDFC proposed ToR Po/vPC ID is invalid")
    leaf = serials["leaf"]
    tor = serials["tor"]
    return {"leafSN1": leaf[0], "leafSN2": leaf[1],
            "torSN1": tor[0], "torSN2": tor[1],
            "poVpc": json.dumps(proposed, separators=(",", ":"))}


def _proposed_ids(page, fabric, serials):
    endpoint = (_TOR + "/" + quote(fabric, safe="") +
                "/switches/pair/?switchSN=" + quote(serials["leaf"][0], safe="") +
                "&peerSwitchSN=" + quote(serials["leaf"][1], safe="") +
                "&torSN=" + quote(serials["tor"][0], safe="") +
                "&torPeerSwitchSN=" + quote(serials["tor"][1], safe=""))
    return _request(page, endpoint)


def _request(page, endpoint):
    status, body = _api(page, "GET", endpoint)
    if status != 200:
        raise NexusDashboardBrowserError(
            "NDFC ToR pairing readback unavailable with HTTP " + str(status))
    return body


def _tor_view(page, fabric, leaf_serials):
    endpoint = (_TOR + "/" + quote(fabric, safe="") + "/switches/" +
                quote(leaf_serials[0], safe="") + "?peerSwitchSN=" +
                quote(leaf_serials[1], safe=""))
    return _request(page, endpoint)


def _tor_parent(page, fabric, tor_serial):
    endpoint = (_TOR + "/" + quote(fabric, safe="") + "/switches/tor/" +
                quote(tor_serial, safe=""))
    return _request(page, endpoint)


def _serial_set(value):
    if isinstance(value, str):
        return {item.strip() for item in value.split(",") if item.strip()}
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return set(value)
    return set()


def _parent_serials(value):
    if value in (None, "", {}, []):
        return set()
    if isinstance(value, str):
        return _serial_set(value)
    if not isinstance(value, dict):
        raise NexusDashboardBrowserError("NDFC ToR parent readback has unknown shape")
    for key in ("leafSNs", "parentLeafSNs", "leafSN", "parentLeafSN"):
        if key in value:
            return _serial_set(value[key])
    if "leafSN1" in value and "leafSN2" in value:
        return _serial_set([value["leafSN1"], value["leafSN2"]])
    if "switchSN" in value and "peerSN" in value:
        return _serial_set([value["switchSN"], value["peerSN"]])
    raise NexusDashboardBrowserError("NDFC ToR parent readback lacks leaf serials")


def _association_state(view, parents, leaf_serials, tor_serials):
    """Classify the exact composite leaf-pair row, ignoring GUI enable state."""
    if (not isinstance(view, dict) or view.get("peerSwitchSN") != leaf_serials[1]
            or not isinstance(view.get("torPairs"), list)):
        raise NexusDashboardBrowserError("NDFC composite leaf ToR view has unknown shape or peer")
    rows = [row for row in view["torPairs"] if isinstance(row, dict)
            and _serial_set(row.get("torSN")) == set(tor_serials)]
    if len(rows) != 1 or rows[0].get("torPeerSN") != tor_serials[1]:
        raise NexusDashboardBrowserError("NDFC composite leaf ToR row is absent or ambiguous")
    actual = rows[0].get("leafSNs")
    if actual is None:
        if any(_parent_serials(item) for item in parents):
            raise NexusDashboardBrowserError("NDFC ToR parent conflicts with unpaired leaf view")
        return "unpaired"
    if _serial_set(actual) != set(leaf_serials):
        raise NexusDashboardBrowserError("NDFC ToR association has foreign leaf serials")
    parent_sets = [_parent_serials(item) for item in parents]
    if not all(parent_sets):
        return "pending"
    if any(not item <= set(leaf_serials) for item in parent_sets):
        raise NexusDashboardBrowserError("NDFC ToR parent has foreign leaf serials")
    if set().union(*parent_sets) != set(leaf_serials):
        return "pending"
    return "paired"


def ensure_tor_pair(intent, topology, username, password, timeout=300,
                    site="DC1"):
    """Save exact ToR association after inventory, vPC, and direct-link preflight."""
    from playwright.sync_api import sync_playwright

    compiled = compile_tor_pair(intent, topology, site)
    fabric = compiled["fabric"]
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
            by_name = _checked_inventory(_inventory(page, fabric),
                                         compiled["switches"])
            selected = compiled["leaf"] + compiled["tor"]
            if not set(selected) <= set(by_name):
                raise NexusDashboardBrowserError("NDFC ToR pairing inventory lacks a member")
            for name in selected:
                role = "leaf" if name in compiled["leaf"] else "tor"
                if by_name[name].get("switchRole") != role:
                    raise NexusDashboardBrowserError("NDFC ToR pairing member role differs")
            serials = {key: tuple(by_name[name]["serialNumber"]
                                  for name in compiled[key])
                       for key in ("leaf", "tor")}
            for names, virtual in ((compiled["leaf"], True),
                                   (compiled["tor"], False)):
                ids = tuple(_database_id(by_name[name]) for name in names)
                observed = [_pair_info(page, item, fabric) for item in ids]
                if not all(info is not None and _matches(info, ids,
                           tuple(by_name[name]["serialNumber"] for name in names),
                           virtual) for info in observed):
                    raise NexusDashboardBrowserError(
                        "NDFC leaf and ToR vPC pairs must exist before ToR pairing")
            view = _tor_view(page, fabric, serials["leaf"])
            parents = [_tor_parent(page, fabric, serial)
                       for serial in serials["tor"]]
            state = _association_state(view, parents, serials["leaf"],
                                       serials["tor"])
            if state == "paired":
                return {"status": "already-paired", "fabric": fabric}
            if state != "unpaired":
                raise NexusDashboardBrowserError("NDFC ToR association conflicts")
            payload = _association_payload(
                serials, _proposed_ids(page, fabric, serials))
            endpoint = (_TOR + "/" + quote(fabric, safe="") +
                        "/switches/pair/custom-id")
            status, response = _api(page, "POST", endpoint, payload)
            if status != 200:
                raise NexusDashboardBrowserError(
                    "NDFC ToR pairing save failed with HTTP " + str(status) +
                    ": " + str(response)[:250])
            def ready():
                view = _tor_view(page, fabric, serials["leaf"])
                parents = [_tor_parent(page, fabric, serial)
                           for serial in serials["tor"]]
                return _association_state(view, parents, serials["leaf"],
                                          serials["tor"]) == "paired"
            _wait_for(page, ready, deadline, "NDFC ToR association")
            return {"status": "paired", "fabric": fabric,
                    "leaf": list(compiled["leaf"]), "tor": list(compiled["tor"]),
                    "po_vpc": json.loads(payload["poVpc"]),
                    "deployment": "config-save and scoped deploy still required"}
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("intent", type=Path)
    parser.add_argument("--topology", type=Path,
                        help="Topology YAML; defaults beside the intent file")
    parser.add_argument("--site", choices=("DC1", "DC2"), default="DC1")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--check", action="store_true",
                        help="Compile direct-link and pair intent without NDFC")
    args = parser.parse_args()
    intent = yaml.safe_load(args.intent.read_text())
    topology = yaml.safe_load((args.topology or args.intent.with_name(
        "topology.yaml")).read_text())
    if args.check:
        compiled = compile_tor_pair(intent, topology, args.site)
        print(json.dumps({key: value for key, value in compiled.items()
                          if key != "switches" and key != "links"} | {
                              "links": [{"leaf": leaf, "tor": tor,
                                         "leaf_port": ports[0], "tor_port": ports[1]}
                                        for (leaf, tor), ports in compiled["links"].items()]},
                         indent=2))
        return
    env = _environment(Path.cwd())
    username, password = env.get("CISCO_USERNAME"), env.get("CISCO_PASSWORD")
    if not username or not password:
        raise ValueError("Set CISCO_USERNAME and CISCO_PASSWORD in EVE_ENV_FILE")
    print(json.dumps(ensure_tor_pair(
        intent, topology, username, password, args.timeout, args.site)))


if __name__ == "__main__":
    main()
