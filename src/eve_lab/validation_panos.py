"""PAN-OS read-only configuration acceptance checks.

This adapter intentionally supports Palo Alto firewall nodes only. Panorama is
not registered for validation.

Validation reads the committed running configuration over management SSH and
never enters configuration mode or commits changes.
"""
from ipaddress import IPv4Address, IPv4Network
import re
import xml.etree.ElementTree as ET


FIELDS = {
    "panos-interface": {"interface", "address", "expected"},
    "panos-zone-interface": {"zone", "interface", "vsys", "expected"},
    "panos-virtual-router-interface": {"virtual_router", "interface", "expected"},
    "panos-route": {"destination", "virtual_router", "next_hop", "expected"},
    "panos-security-rule": {"rule", "vsys", "expected"},
    "panos-nat-rule": {"rule", "vsys", "expected"},
}


def _token(value, field):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", value):
        raise ValueError(field + " must be a single token (letters, digits, _, ., -)")


def _interface(value):
    # PAN-OS interface names commonly contain '/', e.g. ethernet1/1.
    # Keep the accepted alphabet deliberately narrow because interface names are
    # interpolated into ElementTree XPath predicates below.
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_./-]*", value):
        raise ValueError("interface must be a PAN-OS interface token")


def validate_check(check):
    expected = check.get("expected", "present")
    if expected not in ("present", "absent"):
        raise ValueError("PAN-OS expected must be present or absent")
    kind = check["type"]
    if kind == "panos-interface":
        _interface(check.get("interface"))
        if "address" in check:
            if not isinstance(check["address"], str):
                raise ValueError("address must be an IPv4 interface string")
            # Interface addresses are host/prefix values, not network prefixes.
            address, sep, prefix = check["address"].partition("/")
            if not sep or not prefix.isdecimal() or not 0 <= int(prefix) <= 32:
                raise ValueError("address must use IPv4/prefix notation")
            IPv4Address(address)
    elif kind == "panos-zone-interface":
        _token(check.get("zone"), "zone")
        _interface(check.get("interface"))
        _token(check.get("vsys", "vsys1"), "vsys")
    elif kind == "panos-virtual-router-interface":
        _token(check.get("virtual_router"), "virtual_router")
        _interface(check.get("interface"))
    elif kind == "panos-route":
        _token(check.get("virtual_router", "default"), "virtual_router")
        if not isinstance(check.get("destination"), str):
            raise ValueError("destination must be an IPv4 CIDR network")
        if str(IPv4Network(check["destination"], strict=True)) != check["destination"]:
            raise ValueError("destination must use canonical IPv4 CIDR notation")
        if "next_hop" in check:
            if expected == "absent":
                raise ValueError("next_hop applies only to expected present routes")
            IPv4Address(check["next_hop"])
    elif kind in ("panos-security-rule", "panos-nat-rule"):
        _token(check.get("rule"), "rule")
        _token(check.get("vsys", "vsys1"), "vsys")
    else:
        raise ValueError("Unsupported PAN-OS validation type: " + str(kind))


def parse_running_config(text):
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        raise RuntimeError("Invalid PAN-OS running configuration XML") from None
    if root.tag != "config" or root.find("./devices/entry") is None:
        raise RuntimeError("Unrecognized PAN-OS running configuration XML")
    return root


def _device(root):
    device = root.find("./devices/entry")
    if device is None:
        raise RuntimeError("PAN-OS config has no device entry")
    return device


def _presence(matches, expected):
    present = bool(matches)
    return present == (expected == "present"), present


def evaluate(root, check):
    validate_check(check)
    device = _device(root)
    kind = check["type"]
    expected = check.get("expected", "present")
    evidence = {"expected": {k: v for k, v in check.items()
                             if k not in ("name", "node", "type", "required")}}

    if kind == "panos-interface":
        interface = check["interface"]
        entry = device.find(f"./network/interface/ethernet/entry[@name='{interface}']")
        matches = [] if entry is None else [entry]
        passed, present = _presence(matches, expected)
        addresses = []
        if entry is not None:
            addresses = [item.get("name") for item in entry.findall("./layer3/ip/entry") if item.get("name")]
        if "address" in check and expected == "present":
            passed = passed and check["address"] in addresses
        evidence.update(interface=interface, present=present, addresses=addresses)

    elif kind == "panos-zone-interface":
        vsys, zone, interface = check.get("vsys", "vsys1"), check["zone"], check["interface"]
        zone_entry = device.find(f"./vsys/entry[@name='{vsys}']/zone/entry[@name='{zone}']")
        members = [] if zone_entry is None else [m.text for m in zone_entry.findall("./network/layer3/member") if m.text]
        passed, present = _presence([m for m in members if m == interface], expected)
        evidence.update(vsys=vsys, zone=zone, interface=interface, present=present, members=members)

    elif kind == "panos-virtual-router-interface":
        vr, interface = check["virtual_router"], check["interface"]
        vr_entry = device.find(f"./network/virtual-router/entry[@name='{vr}']")
        members = [] if vr_entry is None else [m.text for m in vr_entry.findall("./interface/member") if m.text]
        passed, present = _presence([m for m in members if m == interface], expected)
        evidence.update(virtual_router=vr, interface=interface, present=present, members=members)

    elif kind == "panos-route":
        vr, destination = check.get("virtual_router", "default"), check["destination"]
        vr_entry = device.find(f"./network/virtual-router/entry[@name='{vr}']")
        routes = [] if vr_entry is None else vr_entry.findall("./routing-table/ip/static-route/entry")
        observed = []
        for route in routes:
            if route.findtext("./destination") != destination:
                continue
            next_hop = route.findtext("./nexthop/ip-address")
            observed.append({"name": route.get("name"), "destination": destination, "next_hop": next_hop})
        passed, present = _presence(observed, expected)
        if "next_hop" in check and expected == "present":
            passed = passed and any(route["next_hop"] == check["next_hop"] for route in observed)
        evidence.update(virtual_router=vr, destination=destination, present=present, observed=observed)

    else:
        vsys, rule = check.get("vsys", "vsys1"), check["rule"]
        branch = "security" if kind == "panos-security-rule" else "nat"
        rule_entry = device.find(
            f"./vsys/entry[@name='{vsys}']/rulebase/{branch}/rules/entry[@name='{rule}']")
        matches = [] if rule_entry is None else [rule_entry]
        passed, present = _presence(matches, expected)
        evidence.update(vsys=vsys, rule=rule, present=present)

    if not passed:
        evidence["reason"] = "Observed result does not match acceptance criteria"
    return passed, evidence
