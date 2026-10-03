"""Offline safety checks for NDFC tenant compilation."""

from copy import deepcopy

import pytest

from eve_lab.ndfc_tenants import compile_tenants


def _intent():
    return {
        "ndfc_fabrics": [{
            "name": "LAB", "site": "DC1", "network_vlan_range": "100-199",
            "regular_leaf_pair": {"nodes": ["Leaf-1", "Leaf-2"]},
            "border_leaf_pair": {"nodes": ["Border-1", "Border-2"]},
        }],
        "tenants": {
            "isolation": "no_inter_vrf_route_leaking",
            "vni_policy": {"l2_range": "20000-29999", "l3_range": "30000-39999"},
            "dc1": [
                {"vrf": "BLUE", "vrf_vni": 30001, "vrf_vlan": 130, "zone": "BLUE-ZONE",
                 "networks": [{"name": "BLUE-NET", "prefix": "192.0.2.0/24",
                               "gateway": "192.0.2.1", "vlan": 110, "vni": 20001}],
                 "endpoints": [{"address": "192.0.2.11/24", "gateway": "192.0.2.1"}]},
                {"vrf": "GREEN", "vrf_vni": 30002, "vrf_vlan": 140, "zone": "GREEN-ZONE",
                 "networks": [{"name": "GREEN-NET", "prefix": "198.51.100.0/24",
                               "gateway": "198.51.100.1", "vlan": 120, "vni": 20002}],
                 "endpoints": [{"address": "198.51.100.11/24", "gateway": "198.51.100.1"}]},
            ],
        },
    }


def test_compile_explicit_switch_targets_and_ids():
    compiled = compile_tenants(_intent())
    assert [(v["name"], v["vni"], v["vlan"]) for v in compiled["vrfs"]] == [
        ("BLUE", 30001, 130), ("GREEN", 30002, 140)]
    assert compiled["vrfs"][0]["switches"] == (
        "Leaf-1", "Leaf-2", "Border-1", "Border-2")
    assert compiled["networks"][0]["switches"] == ("Leaf-1", "Leaf-2")


@pytest.mark.parametrize("change", [
    lambda i: i["tenants"]["dc1"][1].update(vrf_vlan=130),
    lambda i: i["tenants"]["dc1"][1]["networks"][0].update(prefix="192.0.2.0/24"),
    lambda i: i["tenants"]["dc1"][1]["endpoints"][0].update(address="192.0.2.12/24"),
])
def test_conflicting_or_misplaced_tenant_intent_is_rejected(change):
    intent = deepcopy(_intent())
    change(intent)
    with pytest.raises(ValueError):
        compile_tenants(intent)

def test_live_inventory_preflight_rejects_wrong_role_or_serial(monkeypatch):
    from eve_lab import ndfc_switches
    from eve_lab.ndfc_tenants import preflight_inventory

    declared = [
        {"name": "Leaf-1", "ip": "192.0.2.10", "role": "leaf"},
        {"name": "Border-1", "ip": "192.0.2.11", "role": "border"},
    ]
    monkeypatch.setattr(ndfc_switches, "compile_switches",
                        lambda _: ("LAB", declared))
    inventory = [
        {"logicalName": "Leaf-1", "ipAddress": "192.0.2.10",
         "switchRole": "leaf", "serialNumber": "SERIAL-1", "ccStatus": "In-Sync"},
        {"logicalName": "Border-1", "ipAddress": "192.0.2.11",
         "switchRole": "border gateway", "serialNumber": "SERIAL-2",
         "ccStatus": "In-Sync"},
    ]
    assert preflight_inventory({}, inventory)["Border-1"] == "SERIAL-2"
    inventory[1]["switchRole"] = "leaf"
    with pytest.raises(ValueError):
        preflight_inventory({}, inventory)
    inventory[1]["switchRole"] = "border gateway"
    inventory[1]["serialNumber"] = "SERIAL-1"
    with pytest.raises(ValueError):
        preflight_inventory({}, inventory)


def test_payloads_preserve_declared_overlay_without_extension_fields():
    import json
    from eve_lab.ndfc_tenants import network_create_payload, vrf_create_payload

    compiled = compile_tenants(_intent())
    vrf = vrf_create_payload("LAB", compiled["vrfs"][0])
    network = network_create_payload("LAB", compiled["networks"][0])
    vrf_cfg = json.loads(vrf["vrfTemplateConfig"])
    net_cfg = json.loads(network["networkTemplateConfig"])
    assert (vrf["vrfId"], vrf_cfg["vrfVlanId"]) == (30001, 130)
    assert "configureStaticDefaultRouteFlag" not in vrf_cfg
    assert (network["networkId"], net_cfg["vlanId"]) == (20001, 110)
    assert net_cfg["gatewayIpAddress"] == "192.0.2.1/24"
    assert "enableIR" not in net_cfg


def test_attachment_payloads_target_only_declared_switches():
    from eve_lab.ndfc_tenants import network_attach_payload, vrf_attach_payload

    compiled = compile_tenants(_intent())
    serials = {name: "SERIAL-" + name for name in
               ("Leaf-1", "Leaf-2", "Border-1", "Border-2")}
    vrf = vrf_attach_payload("LAB", compiled["vrfs"][0], serials)[0]
    network = network_attach_payload("LAB", compiled["networks"][0], serials)[0]
    assert {x["serialNumber"] for x in vrf["lanAttachList"]} == set(serials.values())
    assert {x["serialNumber"] for x in network["lanAttachList"]} == {
        "SERIAL-Leaf-1", "SERIAL-Leaf-2"}
    assert all("switchPorts" not in x for x in network["lanAttachList"])


def test_attachment_readback_rejects_undeclared_serial(monkeypatch):
    from eve_lab import ndfc_tenant_api as api
    from eve_lab.nexus_dashboard_browser import NexusDashboardBrowserError

    body = [{"vrfName": "BLUE", "lanAttachList": [
        {"serialNumber": "SERIAL-1", "vlan": 130, "deployment": True},
        {"serialNumber": "SERIAL-EXTRA", "vlan": 130, "deployment": True},
    ]}]
    monkeypatch.setattr(api, "_api", lambda *_: (200, body))
    payload = [{"vrfName": "BLUE", "lanAttachList": [
        {"serialNumber": "SERIAL-1", "vlan": 130, "deployment": True}]}]
    with pytest.raises(NexusDashboardBrowserError, match="undeclared"):
        api._ensure_attachment(None, "/vrfs/attachments", "vrfName",
                               payload, {"SERIAL-1"}, 130)


def test_tor_host_ports_follow_declared_endpoint_links():
    from eve_lab.ndfc_tenants import compile_tor_ports, network_attach_payload

    intent = _intent()
    intent["ndfc_fabrics"][0]["tor_pair"] = {"nodes": ["ToR-1", "ToR-2"]}
    intent["tenants"]["dc1"][0]["endpoints"][0].update(
        node="Server-1", attachment="ToR-1")
    intent["tenants"]["dc1"][1]["endpoints"][0].update(
        node="Developer-1", attachment="ToR-2")
    topology = {"links": [
        {"from": {"node": "Server-1", "interface": "eth0"},
         "to": {"node": "ToR-1", "interface": "Ethernet1/3"}},
        {"from": {"node": "ToR-2", "interface": "Ethernet1/4"},
         "to": {"node": "Developer-1", "interface": "eth0"}},
    ]}
    ports = compile_tor_ports(intent, topology)
    assert ports == {"BLUE-NET": "ToR-1(Ethernet1/3)",
                     "GREEN-NET": "ToR-2(Ethernet1/4)"}
    network = compile_tenants(intent)["networks"][0]
    payload = network_attach_payload(
        "LAB", network, {"Leaf-1": "SERIAL-1", "Leaf-2": "SERIAL-2"},
        ports["BLUE-NET"])[0]["lanAttachList"]
    assert {row["torPorts"] for row in payload} == {"ToR-1(Ethernet1/3)"}
    topology["links"][0]["to"]["interface"] = "Ethernet1/4"
    topology["links"][1]["from"]["node"] = "ToR-1"
    intent["tenants"]["dc1"][1]["endpoints"][0]["attachment"] = "ToR-1"
    with pytest.raises(ValueError, match="share a ToR host port"):
        compile_tor_ports(intent, topology)


def test_network_attachment_readback_uses_get_fields_and_exact_tor_ports(monkeypatch):
    from eve_lab import ndfc_tenant_api as api
    from eve_lab.nexus_dashboard_browser import NexusDashboardBrowserError

    body = [{"networkName": "BLUE-NET", "lanAttachList": [
        {"switchSerialNo": "SERIAL-1", "vlanId": 110,
         "isLanAttached": True, "lanAttachState": "IN-SYNC",
         "portNames": "ToR-1(Ethernet1/3)"},
    ]}]
    monkeypatch.setattr(api, "_api", lambda *_: (200, body))
    payload = [{"networkName": "BLUE-NET", "lanAttachList": [
        {"serialNumber": "SERIAL-1", "vlan": 110, "deployment": True,
         "torPorts": "ToR-1(Ethernet1/3)"}]}]
    result = api._ensure_attachment(None, "/networks/attachments", "networkName",
                                    payload, {"SERIAL-1"}, 110, {"ToR-1", "ToR-2"})
    assert result["status"] == "already-attached"
    body[0]["lanAttachList"][0]["portNames"] += " ToR-2(Ethernet1/4)"
    with pytest.raises(NexusDashboardBrowserError, match="undeclared ToR"):
        api._ensure_attachment(None, "/networks/attachments", "networkName",
                               payload, {"SERIAL-1"}, 110, {"ToR-1", "ToR-2"})
