"""Stage selected-site NDFC VRFs and Networks using Cisco LAN top-down APIs."""

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import quote

import yaml

from .config import _environment
from .ndfc_fabric import _BASE, _FABRICS, _api
from .ndfc_tenants import (
    compile_tenants, compile_tor_access_ports, compile_tor_ports, network_attach_payload,
    network_create_payload, preflight_inventory, validate_network_dhcp,
    vrf_attach_payload, vrf_create_payload,
)
from .ndfc_tor_access import (
    deploy_access_ports, reconcile_access_ports, verify_access_ports,
)
from .nexus_dashboard_browser import (
    NexusDashboardBrowserError, _login, _spki_pin, _wait_for,
)

_TOP_DOWN_ROOT = _BASE + "/lan-fabric/rest/top-down"
_TOP_DOWN = _TOP_DOWN_ROOT + "/fabrics/"


def _collection(page, endpoint, kind):
    status, body = _api(page, "GET", endpoint)
    if status != 200 or not isinstance(body, list):
        raise NexusDashboardBrowserError(
            "NDFC " + kind + " list failed with HTTP " + str(status))
    return body


def _decode_config(item, key, kind):
    value = item.get(key)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise NexusDashboardBrowserError(
                "NDFC " + kind + " readback has invalid template configuration") from exc
    if not isinstance(value, dict):
        raise NexusDashboardBrowserError(
            "NDFC " + kind + " readback lacks template configuration")
    return value


def _check_template(page, name, payloads, config_key):
    endpoint = _BASE + "/configtemplate/rest/config/templates/" + quote(name, safe="")
    status, body = _api(page, "GET", endpoint)
    if status != 200 or not isinstance(body, dict):
        raise NexusDashboardBrowserError(
            "NDFC tenant template unavailable: " + name)
    available = {item.get("name") for item in body.get("parameters", [])
                 if isinstance(item, dict)}
    for payload in payloads:
        missing = set(json.loads(payload[config_key])) - available
        if missing:
            raise NexusDashboardBrowserError(
                "NDFC tenant template lacks configured fields: " +
                ", ".join(sorted(missing)))

def _verify_object(observed, wanted, kind):
    if kind == "VRF":
        identity = ("vrfName", "vrfId", "vrfTemplate")
        config = ("vrfName", "vrfSegmentId", "vrfVlanId")
        key = "vrfTemplateConfig"
    else:
        identity = ("networkName", "networkId", "vrf", "networkTemplate")
        config = ("networkName", "vrfName", "segmentId", "vlanId",
                  "gatewayIpAddress", "tag", "isLayer2Only")
        key = "networkTemplateConfig"
    mismatched = [name for name in identity
                  if str(observed.get(name)) != str(wanted[name])]
    actual_config = _decode_config(observed, key, kind)
    desired_config = json.loads(wanted[key])
    mismatched.extend(name for name in config
                      if str(actual_config.get(name)).lower() !=
                      str(desired_config[name]).lower())
    if mismatched:
        raise NexusDashboardBrowserError(
            "NDFC " + kind + " conflicts with declared intent: " +
            ", ".join(mismatched))


def _stage_collection(page, endpoint, kind, desired):
    current = _collection(page, endpoint, kind)
    name_key = "vrfName" if kind == "VRF" else "networkName"
    by_name = {item.get(name_key): item for item in current}
    if len(by_name) != len(current):
        raise NexusDashboardBrowserError("NDFC " + kind + " list has duplicate names")
    results = []
    for payload in desired:
        name = payload[name_key]
        if name not in by_name:
            status, body = _api(page, "POST", endpoint, payload)
            if status != 200:
                raise NexusDashboardBrowserError(
                    "NDFC " + kind + " creation failed for " + name +
                    " with HTTP " + str(status) + ": " + str(body)[:250])
            current = _collection(page, endpoint, kind)
            matches = [item for item in current if item.get(name_key) == name]
            if len(matches) != 1:
                raise NexusDashboardBrowserError(
                    "NDFC " + kind + " creation lacks exact readback for " + name)
            by_name[name] = matches[0]
            result = "created"
        else:
            result = "already-configured"
            if kind == "Network":
                current_config = _decode_config(
                    by_name[name], "networkTemplateConfig", kind)
                if "tag" not in current_config:
                    updated = dict(by_name[name])
                    updated_config = {**current_config, "tag": ""}
                    updated["networkTemplateConfig"] = json.dumps(
                        updated_config, separators=(",", ":"))
                    _verify_object(updated, payload, kind)
                    status, body = _api(
                        page, "PUT", endpoint + "/" + quote(name, safe=""), updated)
                    if status != 200:
                        raise NexusDashboardBrowserError(
                            "NDFC Network tag correction failed for " + name +
                            " with HTTP " + str(status) + ": " + str(body)[:250])
                    current = _collection(page, endpoint, kind)
                    matches = [item for item in current
                               if item.get(name_key) == name]
                    if len(matches) != 1:
                        raise NexusDashboardBrowserError(
                            "NDFC Network tag correction lacks exact readback")
                    by_name[name] = matches[0]
                    result = "updated"
        _verify_object(by_name[name], payload, kind)
        results.append({"name": name, "status": result})
    return results


def stage_tenants(intent, username, password, site="DC1"):
    """Create selected-site overlays only; do not attach or deploy fabric policy."""
    from playwright.sync_api import sync_playwright

    compiled = compile_tenants(intent, site)
    dhcp_status = {network["name"]: validate_network_dhcp(network)
                   for network in compiled["networks"]}
    fabric = compiled["fabric"]
    root = _TOP_DOWN + quote(fabric, safe="")
    address = intent["management"]["nd"]["address"].split("/")[0]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--ignore-certificate-errors-spki-list=" + _spki_pin(address)])
        try:
            page = browser.new_page()
            page.goto("https://" + address + "/", wait_until="domcontentloaded",
                      timeout=30000)
            _login(page, username, password, 90)
            status, fabric_list = _api(page, "GET", _FABRICS)
            if status != 200 or not isinstance(fabric_list, list) or not any(
                    item.get("fabricName") == fabric for item in fabric_list):
                raise NexusDashboardBrowserError(
                    "NDFC exact " + site + " fabric is absent before tenant staging")
            inventory = _collection(
                page, _FABRICS + "/" + quote(fabric, safe="") +
                "/inventory/switchesByFabric", "switch inventory")
            # Creating controller-side VRF/Network objects does not push switch
            # configuration. Imported exact identities may have ccStatus NA
            # until the first successful fabric Recalculate and deploy.
            serials = preflight_inventory(
                intent, inventory,
                allowed_cc_status=("In-Sync", "Pending", "Out-of-Sync", "NA"),
                site=site)
            vrf_payloads = [vrf_create_payload(fabric, item) for item in compiled["vrfs"]]
            network_payloads = [network_create_payload(fabric, item)
                                for item in compiled["networks"]]
            _check_template(page, "Default_VRF_Universal", vrf_payloads,
                            "vrfTemplateConfig")
            _check_template(page, "Default_Network_Universal", network_payloads,
                            "networkTemplateConfig")
            vrfs = _stage_collection(
                page, root + "/vrfs", "VRF",
                vrf_payloads)
            networks = _stage_collection(
                page, root + "/networks", "Network",
                network_payloads)
            return {"fabric": fabric, "switch_serials": serials,
                    "vrfs": vrfs, "networks": networks,
                    "dhcp_status": dhcp_status, "deployment": "not-requested"}
        finally:
            browser.close()


def _attachment_records(body, name_key):
    """Normalize Cisco list rows with nested or flat attachment records."""
    if not isinstance(body, list):
        raise NexusDashboardBrowserError("NDFC attachment readback is not a list")
    records = {}
    for row in body:
        if not isinstance(row, dict):
            raise NexusDashboardBrowserError("NDFC attachment readback has invalid row")
        children = row.get("lanAttachList")
        children = children if isinstance(children, list) else [row]
        for child in children:
            if not isinstance(child, dict):
                raise NexusDashboardBrowserError("NDFC attachment readback has invalid child")
            name = child.get(name_key) or row.get(name_key)
            serial = child.get("serialNumber") or child.get("switchSerialNo")
            if not name or not serial:
                raise NexusDashboardBrowserError(
                    "NDFC attachment readback lacks name or serial")
            if child.get("isLanAttached") is False:
                continue
            key = name, serial
            if key in records:
                raise NexusDashboardBrowserError(
                    "NDFC attachment readback duplicates a switch serial")
            normalized = dict(child)
            normalized["serialNumber"] = serial
            normalized["vlan"] = child.get("vlan", child.get("vlanId"))
            records[key] = normalized
    return records


def _ensure_attachment(page, endpoint, name_key, payload, expected_serials, vlan,
                       tor_switch_names=()):
    name = payload[0][name_key]
    expected_tor_ports = payload[0]["lanAttachList"][0].get("torPorts", "")
    def current():
        status, body = _api(page, "GET", endpoint)
        if status != 200:
            raise NexusDashboardBrowserError(
                "NDFC attachment readback failed with HTTP " + str(status))
        records = _attachment_records(body, name_key)
        selected = {serial: row for (row_name, serial), row in records.items()
                    if row_name == name}
        extra = set(selected) - expected_serials
        if extra:
            raise NexusDashboardBrowserError(
                "NDFC " + name + " has undeclared switch attachments")
        for row in selected.values():
            if str(row.get("vlan")) != str(vlan) or row.get("deployment") is False:
                raise NexusDashboardBrowserError(
                    "NDFC " + name + " attachment VLAN or state conflicts")
            actual_tor_ports = row.get("torPorts") or ""
            if not actual_tor_ports and row.get("portNames"):
                tor_names = set(tor_switch_names)
                actual_tor_ports = " ".join(
                    entry for entry in re.findall(r"\S+\([^)]*\)", row["portNames"])
                    if entry.split("(", 1)[0] in tor_names)
            if actual_tor_ports and actual_tor_ports != expected_tor_ports:
                raise NexusDashboardBrowserError(
                    "NDFC " + name + " has undeclared ToR port attachments")
            row["torPorts"] = actual_tor_ports
        return selected

    attached = current()
    missing = expected_serials - set(attached)
    if expected_tor_ports:
        missing |= {serial for serial, row in attached.items()
                    if not row.get("torPorts")}
    if missing:
        request = [{name_key: name, "lanAttachList": [
            row for row in payload[0]["lanAttachList"]
            if row["serialNumber"] in missing]}]
        status, body = _api(page, "POST", endpoint, request)
        if status != 200:
            raise NexusDashboardBrowserError(
                "NDFC " + name + " attachment failed with HTTP " +
                str(status) + ": " + str(body)[:250])
        deadline = time.monotonic() + 120
        def matches_intent():
            observed = current()
            return (set(observed) == expected_serials and
                    all(row.get("torPorts", "") == expected_tor_ports
                        for row in observed.values()))
        _wait_for(page, matches_intent, deadline,
                  "NDFC " + name + " attachment and ToR port readback")
    return {"name": name, "status": "attached" if missing else "already-attached",
            "switches": len(expected_serials)}


def attach_tenants(intent, topology, username, password, site="DC1"):
    """Attach staged tenant objects and exact ToR host ports without deployment."""
    from playwright.sync_api import sync_playwright

    compiled = compile_tenants(intent, site)
    dhcp_status = {network["name"]: validate_network_dhcp(network)
                   for network in compiled["networks"]}
    tor_ports = compile_tor_ports(intent, topology, site)
    access_ports = compile_tor_access_ports(intent, topology, site)
    for network in compiled["networks"]:
        if network["name"] not in tor_ports:
            raise ValueError(site + " network lacks declared endpoint ToR ports")
    fabric = compiled["fabric"]
    root = _TOP_DOWN + quote(fabric, safe="")
    address = intent["management"]["nd"]["address"].split("/")[0]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--ignore-certificate-errors-spki-list=" + _spki_pin(address)])
        try:
            page = browser.new_page()
            page.goto("https://" + address + "/", wait_until="domcontentloaded",
                      timeout=30000)
            _login(page, username, password, 90)
            inventory = _collection(
                page, _FABRICS + "/" + quote(fabric, safe="") +
                "/inventory/switchesByFabric", "switch inventory")
            serials = preflight_inventory(
                intent, inventory,
                allowed_cc_status=("In-Sync", "Pending", "Out-of-Sync"), site=site)
            for kind, leaf, desired in (
                    ("VRF", "vrfs", compiled["vrfs"]),
                    ("Network", "networks", compiled["networks"])):
                records = _collection(page, root + "/" + leaf, kind)
                key = "vrfName" if kind == "VRF" else "networkName"
                by_name = {item.get(key): item for item in records}
                if len(by_name) != len(records):
                    raise NexusDashboardBrowserError(
                        "NDFC staged " + kind + " list has duplicate names")
                for item in desired:
                    if item["name"] not in by_name:
                        raise NexusDashboardBrowserError(
                            "NDFC declared " + kind + " is absent before attachment")
                    payload = (vrf_create_payload(fabric, item) if kind == "VRF"
                               else network_create_payload(fabric, item))
                    _verify_object(by_name[item["name"]], payload, kind)
            vrfs = [_ensure_attachment(
                page, root + "/vrfs/attachments", "vrfName",
                vrf_attach_payload(fabric, item, serials),
                {serials[name] for name in item["switches"]}, item["vlan"])
                for item in compiled["vrfs"]]
            networks = [_ensure_attachment(
                page, root + "/networks/attachments", "networkName",
                network_attach_payload(fabric, item, serials, tor_ports[item["name"]]),
                {serials[name] for name in item["switches"]}, item["vlan"],
                set(next(profile["tor_pair"]["nodes"] for profile in
                         intent["ndfc_fabrics"] if profile["site"] == site)))
                for item in compiled["networks"]]
            host_ports = reconcile_access_ports(page, access_ports, serials)
            return {"fabric": fabric, "vrfs": vrfs, "networks": networks,
                    "host_ports": host_ports, "dhcp_status": dhcp_status,
                    "deployment": "not-requested"}
        finally:
            browser.close()


def _deployment_map(compiled, serials, kind):
    """Build the 12.2.3 resource deploy map from declared switch identities."""
    resources = compiled["vrfs" if kind == "VRF" else "networks"]
    by_serial = {}
    for item in resources:
        for switch in item["switches"]:
            by_serial.setdefault(serials[switch], []).append(item["name"])
    return {serial: ",".join(names) for serial, names in sorted(by_serial.items())}


def _deployment_states(page, root, compiled, serials, tor_ports, tor_names, kind):
    leaf = "vrfs" if kind == "VRF" else "networks"
    key = "vrfName" if kind == "VRF" else "networkName"
    rows = _attachment_records(
        _collection(page, root + "/" + leaf + "/attachments", kind + " attachments"),
        key)
    states = {}
    for item in compiled[leaf]:
        expected_serials = {serials[name] for name in item["switches"]}
        selected = {serial: row for (name, serial), row in rows.items()
                    if name == item["name"]}
        if set(selected) != expected_serials:
            raise NexusDashboardBrowserError(
                "NDFC " + item["name"] + " deployment attachments differ from intent")
        for serial, row in selected.items():
            if str(row["vlan"]) != str(item["vlan"]):
                raise NexusDashboardBrowserError(
                    "NDFC " + item["name"] + " deployment VLAN differs from intent")
            if kind == "Network":
                observed = row.get("torPorts") or " ".join(
                    token for token in re.findall(r"\S+\([^)]*\)",
                                                  row.get("portNames") or "")
                    if token.split("(", 1)[0] in tor_names)
                if observed != tor_ports[item["name"]]:
                    raise NexusDashboardBrowserError(
                        "NDFC " + item["name"] + " deployment ToR ports differ from intent")
            state = row.get("lanAttachState")
            if state not in ("PENDING", "OUT-OF-SYNC", "IN PROGRESS", "IN-SYNC", "DEPLOYED"):
                raise NexusDashboardBrowserError(
                    "NDFC " + item["name"] + " has invalid deployment state: " +
                    str(state))
            states[item["name"], serial] = state
    return states


def deploy_tenants(intent, topology, username, password, site="DC1"):
    """Deploy only declared tenant resources after exact attachment preflight."""
    from playwright.sync_api import sync_playwright

    compiled = compile_tenants(intent, site)
    dhcp_status = {network["name"]: validate_network_dhcp(network)
                   for network in compiled["networks"]}
    tor_ports = compile_tor_ports(intent, topology, site)
    access_ports = compile_tor_access_ports(intent, topology, site)
    tor_names = set(next(profile["tor_pair"]["nodes"] for profile in
                         intent["ndfc_fabrics"] if profile["site"] == site))
    fabric = compiled["fabric"]
    root = _TOP_DOWN + quote(fabric, safe="")
    address = intent["management"]["nd"]["address"].split("/")[0]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--ignore-certificate-errors-spki-list=" + _spki_pin(address)])
        try:
            page = browser.new_page()
            page.goto("https://" + address + "/", wait_until="domcontentloaded",
                      timeout=30000)
            _login(page, username, password, 90)
            inventory = _collection(
                page, _FABRICS + "/" + quote(fabric, safe="") +
                "/inventory/switchesByFabric", "switch inventory")
            serials = preflight_inventory(
                intent, inventory,
                allowed_cc_status=("In-Sync", "Pending", "Out-of-Sync"), site=site)
            before = {kind: _deployment_states(
                page, root, compiled, serials, tor_ports, tor_names, kind)
                for kind in ("VRF", "Network")}
            # Require the access policy from --attach before any resource deploy.
            verify_access_ports(page, access_ports, serials)
            result = {}
            for kind, endpoint in (("VRF", _TOP_DOWN_ROOT + "/vrfs/deploy"),
                                   ("Network", _TOP_DOWN_ROOT + "/networks/deploy")):
                pending = {key for key, state in before[kind].items()
                           if state not in ("IN-SYNC", "DEPLOYED")}
                if pending:
                    mapping = _deployment_map(compiled, serials, kind)
                    selected = {}
                    for serial, names in mapping.items():
                        needed = [name for name in names.split(",")
                                  if (name, serial) in pending]
                        if needed:
                            selected[serial] = ",".join(needed)
                    status, body = _api(page, "POST", endpoint, selected)
                    if status != 200 or (isinstance(body, dict) and body.get("failureList")):
                        raise NexusDashboardBrowserError(
                            "NDFC " + kind + " deploy failed with HTTP " +
                            str(status) + ": " + str(body)[:250])
                    deadline = time.monotonic() + 300
                    _wait_for(page, lambda: all(
                        state in ("IN-SYNC", "DEPLOYED") for state in
                        _deployment_states(page, root, compiled, serials,
                                           tor_ports, tor_names, kind).values()),
                        deadline, "NDFC " + kind + " attachment deployment")
                result[kind.lower() + "s"] = {
                    "resources": len(compiled["vrfs" if kind == "VRF" else "networks"]),
                    "attachments_deployed": len(pending),
                }
            host_ports = deploy_access_ports(
                page, fabric, access_ports, serials, username)
            return {"fabric": fabric, **result, "host_ports": host_ports,
                    "dhcp_status": dhcp_status, "deployment": "in-sync"}
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("intent", type=Path)
    parser.add_argument("--site", choices=("DC1", "DC2"), default="DC1")
    parser.add_argument("--check", action="store_true",
                        help="Compile without NDFC access")
    parser.add_argument("--attach", action="store_true",
                        help="Attach staged overlays without deploying")
    parser.add_argument("--deploy", action="store_true",
                        help="Deploy only declared attached tenant resources")
    args = parser.parse_args()
    intent = yaml.safe_load(args.intent.read_text())
    if args.check:
        compiled = compile_tenants(intent, args.site)
        compiled["dhcp_status"] = {
            network["name"]: validate_network_dhcp(network)
            for network in compiled["networks"]}
        print(json.dumps(compiled, indent=2))
        return
    env = _environment(Path.cwd())
    username = env.get("NDFC_RUNNER_USERNAME")
    password = env.get("NDFC_RUNNER_PASSWORD")
    if not username or not password:
        raise ValueError(
            "Set NDFC_RUNNER_USERNAME and NDFC_RUNNER_PASSWORD in EVE_ENV_FILE")
    if args.attach and args.deploy:
        parser.error("Select only one of --attach or --deploy")
    topology = (yaml.safe_load(args.intent.with_name("topology.yaml").read_text())
                if args.attach or args.deploy else None)
    result = (deploy_tenants(intent, topology, username, password, args.site)
              if args.deploy else attach_tenants(
                  intent, topology, username, password, args.site) if args.attach
              else stage_tenants(intent, username, password, args.site))
    result.pop("switch_serials", None)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()