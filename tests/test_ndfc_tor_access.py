"""Focused safeguards for endpoint-derived NDFC access host policies."""

from copy import deepcopy

import pytest

from eve_lab.ndfc_tenants import compile_tor_access_ports
from eve_lab.nexus_dashboard_browser import NexusDashboardBrowserError
from eve_lab import ndfc_tor_access as api


def _intent_and_topology():
    intent = {
        "ndfc_fabrics": [{"name": "LAB", "site": "DC1", "network_vlan_range": "100-199",
                          "regular_leaf_pair": {"nodes": ["Leaf-1", "Leaf-2"]},
                          "border_leaf_pair": {"nodes": ["Border-1", "Border-2"]},
                          "tor_pair": {"nodes": ["ToR-1", "ToR-2"]}}],
        "tenants": {"host_port_mode": "access",
                    "isolation": "no_inter_vrf_route_leaking",
                    "vni_policy": {"l2_range": "20000-29999", "l3_range": "30000-39999"},
                    "dc1": [
                        {"vrf": "BLUE", "vrf_vni": 30001, "vrf_vlan": 130,
                         "zone": "BLUE-ZONE",
                         "networks": [{"name": "BLUE-NET", "prefix": "192.0.2.0/24",
                                       "gateway": "192.0.2.1", "vlan": 110, "vni": 20001}],
                         "endpoints": [
                             {"node": "Server-1", "attachment": "ToR-1",
                              "address": "192.0.2.11/24", "gateway": "192.0.2.1"},
                             {"node": "Server-2", "attachment": "ToR-2",
                              "address": "192.0.2.12/24", "gateway": "192.0.2.1"}]},
                        {"vrf": "GREEN", "vrf_vni": 30002, "vrf_vlan": 140,
                         "zone": "GREEN-ZONE",
                         "networks": [{"name": "GREEN-NET", "prefix": "198.51.100.0/24",
                                       "gateway": "198.51.100.1", "vlan": 120, "vni": 20002}],
                         "endpoints": [{"node": "Developer", "attachment": "ToR-1",
                                        "address": "198.51.100.11/24",
                                        "gateway": "198.51.100.1"}]},
                    ]}}
    topology = {"links": [
        {"from": {"node": "Server-1", "interface": "eth0"},
         "to": {"node": "ToR-1", "interface": "Ethernet1/3"}},
        {"from": {"node": "Server-2", "interface": "eth0"},
         "to": {"node": "ToR-2", "interface": "Ethernet1/3"}},
        {"from": {"node": "Developer", "interface": "eth0"},
         "to": {"node": "ToR-1", "interface": "Ethernet1/4"}},
    ]}
    return intent, topology


def test_compiler_uses_explicit_access_intent_and_exact_endpoint_vlan():
    intent, topology = _intent_and_topology()
    assert compile_tor_access_ports(intent, topology) == [
        {"tor": "ToR-1", "port": "Ethernet1/3", "network": "BLUE-NET", "vlan": 110},
        {"tor": "ToR-2", "port": "Ethernet1/3", "network": "BLUE-NET", "vlan": 110},
        {"tor": "ToR-1", "port": "Ethernet1/4", "network": "GREEN-NET", "vlan": 120},
    ]
    del intent["tenants"]["host_port_mode"]
    with pytest.raises(ValueError, match="host_port_mode"):
        compile_tor_access_ports(intent, topology)
    intent["tenants"]["host_port_mode"] = "trunk"
    with pytest.raises(ValueError, match="host_port_mode"):
        compile_tor_access_ports(intent, topology)


def _template():
    return {"templateSubType": "INTERFACE_ETHERNET", "parameters": [
        {"name": name} for name in ("SERIAL_NUMBER", "INTF_NAME", "ACCESS_VLAN",
                                 "ADMIN_STATE", "PORTTYPE_FAST_ENABLED", "MTU")]}


def _groups():
    return [
        {"policy": "int_trunk_host", "interfaces": [
            {"serialNumber": "TOR1", "ifName": "Ethernet1/3", "nvPairs": {
                "SERIAL_NUMBER": "TOR1", "INTF_NAME": "Ethernet1/3",
                "ALLOWED_VLANS": "110", "NATIVE_VLAN": "1", "ADMIN_STATE": "true",
                "POLICY_ID": "P-1"}},
            {"serialNumber": "TOR1", "ifName": "Ethernet1/1", "nvPairs": {
                "ALLOWED_VLANS": "110,120"}},
            {"serialNumber": "TOR2", "ifName": "Ethernet1/4", "nvPairs": {
                "ALLOWED_VLANS": "none"}},
        ]}]


def test_reconcile_changes_only_declared_host_and_is_idempotent(monkeypatch):
    groups = _groups()
    writes = []
    def fake_api(_, method, endpoint, payload=None):
        if endpoint.endswith("/int_access_host"):
            return 200, _template()
        if method == "GET":
            return 200, deepcopy(groups)
        writes.append((method, payload))
        row = next(x for x in groups[0]["interfaces"] if x["ifName"] == "Ethernet1/3")
        groups[0]["interfaces"].remove(row)
        groups.append({"policy": "int_access_host", "interfaces": [
            {"serialNumber": "TOR1", "ifName": "Ethernet1/3",
             "nvPairs": payload["interfaces"][0]["nvPairs"]}]})
        return 200, {}
    monkeypatch.setattr(api, "_api", fake_api)
    monkeypatch.setattr(api, "_wait_for", lambda _, pred, *__: assert_predicate(pred))
    ports = [{"tor": "ToR-1", "port": "Ethernet1/3", "vlan": 110}]
    serials = {"ToR-1": "TOR1", "ToR-2": "TOR2"}
    assert api.reconcile_access_ports(None, ports, serials)["policies_reconciled"] == 1
    assert writes[0][0] == "PUT"
    assert writes[0][1]["interfaces"][0]["nvPairs"]["ACCESS_VLAN"] == "110"
    assert "ALLOWED_VLANS" not in writes[0][1]["interfaces"][0]["nvPairs"]
    assert api.reconcile_access_ports(None, ports, serials)["policies_reconciled"] == 0
    assert len(writes) == 1
    assert groups[0]["interfaces"] == _groups()[0]["interfaces"][1:]


def assert_predicate(predicate):
    assert predicate()


def test_reconcile_rejects_conflicting_vlan_before_write(monkeypatch):
    groups = _groups()
    groups[0]["interfaces"][0]["nvPairs"]["ALLOWED_VLANS"] = "120"
    methods = []
    def fake_api(_, method, endpoint, payload=None):
        methods.append(method)
        return (200, _template()) if endpoint.endswith("/int_access_host") else (200, groups)
    monkeypatch.setattr(api, "_api", fake_api)
    with pytest.raises(NexusDashboardBrowserError, match="conflict"):
        api.reconcile_access_ports(
            None, [{"tor": "ToR-1", "port": "Ethernet1/3", "vlan": 110}],
            {"ToR-1": "TOR1"})
    assert methods == ["GET", "GET"]


def test_deploy_preflight_rejects_trunk_policy_without_post(monkeypatch):
    groups = _groups()
    methods = []
    def fake_api(_, method, endpoint, payload=None):
        methods.append(method)
        return 200, groups
    monkeypatch.setattr(api, "_api", fake_api)
    with pytest.raises(NexusDashboardBrowserError, match="access policy differs"):
        api.deploy_access_ports(
            None, "LAB", [{"tor": "ToR-1", "port": "Ethernet1/3", "vlan": 110}],
            {"ToR-1": "TOR1"}, "runner")
    assert methods == ["GET"]


def test_deploy_targets_only_declared_access_port_and_checks_history(monkeypatch):
    groups = [{"policy": "int_access_host", "interfaces": [
        {"serialNumber": "TOR1", "ifName": "Ethernet1/3",
         "nvPairs": {"ACCESS_VLAN": "110"}}]}]
    posts = []
    def fake_api(_, method, endpoint, payload=None):
        if method == "POST":
            posts.append(payload)
            return 200, {"message": "Interface deployed successfully"}
        return 200, groups
    previews = [
        {"entityList": [{"entityType": "INTERFACE", "entityName": "Ethernet1/3",
                         "commands": ["  switchport mode access",
                                      "  switchport access vlan 110"]}]},
        {"entityList": []},
    ]
    histories = [
        [{"submittedTime": "1", "status": "SUCCESS"}],
        [{"submittedTime": "2", "status": "SUCCESS"}],
    ]
    monkeypatch.setattr(api, "_api", fake_api)
    monkeypatch.setattr(api, "_preview", lambda *_: previews.pop(0))
    monkeypatch.setattr(api, "_deployer_history", lambda *_: histories.pop(0))
    monkeypatch.setattr(api, "_wait_for", lambda _, pred, *__: assert_predicate(pred))
    result = api.deploy_access_ports(
        None, "LAB", [{"tor": "ToR-1", "port": "Ethernet1/3", "vlan": 110}],
        {"ToR-1": "TOR1"}, "runner")
    assert result == {"ports": 1, "interfaces_deployed": 1}
    assert posts == [[{"serialNumber": "TOR1", "ifName": "Ethernet1/3"}]]


def test_deploy_rejects_preview_without_access_mode(monkeypatch):
    groups = [{"policy": "int_access_host", "interfaces": [
        {"serialNumber": "TOR1", "ifName": "Ethernet1/3",
         "nvPairs": {"ACCESS_VLAN": "110"}}]}]
    methods = []
    def fake_api(_, method, endpoint, payload=None):
        methods.append(method)
        return 200, groups
    monkeypatch.setattr(api, "_api", fake_api)
    monkeypatch.setattr(api, "_preview", lambda *_: {"entityList": [
        {"entityType": "INTERFACE", "entityName": "Ethernet1/3",
         "commands": ["  switchport mode trunk"]}]})
    with pytest.raises(NexusDashboardBrowserError, match="preview lacks"):
        api.deploy_access_ports(
            None, "LAB", [{"tor": "ToR-1", "port": "Ethernet1/3", "vlan": 110}],
            {"ToR-1": "TOR1"}, "runner")
    assert methods == ["GET"]


def test_reconcile_creates_missing_endpoint_policy_without_touching_uplink(monkeypatch):
    groups = [{"policy": "int_trunk_host", "interfaces": [
        {"serialNumber": "TOR1", "ifName": "Ethernet1/1",
         "nvPairs": {"ALLOWED_VLANS": "110,120"}}]}]
    writes = []
    def fake_api(_, method, endpoint, payload=None):
        if endpoint.endswith("/int_access_host"):
            return 200, _template()
        if method == "GET":
            return 200, deepcopy(groups)
        writes.append((method, payload))
        groups.append({"policy": "int_access_host", "interfaces": [
            {"serialNumber": "TOR1", "ifName": "Ethernet1/3",
             "nvPairs": payload["interfaces"][0]["nvPairs"]}]})
        return 200, {}
    monkeypatch.setattr(api, "_api", fake_api)
    monkeypatch.setattr(api, "_wait_for", lambda _, pred, *__: assert_predicate(pred))
    result = api.reconcile_access_ports(
        None, [{"tor": "ToR-1", "port": "Ethernet1/3", "vlan": 110}],
        {"ToR-1": "TOR1"})
    assert result == {"ports": 1, "policies_reconciled": 1}
    assert writes[0][0] == "POST"
    assert writes[0][1]["interfaces"][0]["ifName"] == "Ethernet1/3"
    assert groups[0]["interfaces"][0]["ifName"] == "Ethernet1/1"


def test_interface_rows_ignore_unrelated_duplicates_but_reject_target_duplicate(monkeypatch):
    groups = [{"policy": "loopback", "interfaces": [
        {"serialNumber": "OTHER", "ifName": "loopback1", "nvPairs": {}}]},
        {"policy": "loopback", "interfaces": [
            {"serialNumber": "OTHER", "ifName": "loopback1", "nvPairs": {}}]},
        {"policy": "int_trunk_host", "interfaces": [
            {"serialNumber": "TOR1", "ifName": "Ethernet1/3", "nvPairs": {}}]}]
    monkeypatch.setattr(api, "_api", lambda *_: (200, groups))
    target = {("TOR1", "Ethernet1/3"): "110"}
    assert api._rows(None, target) == {
        ("TOR1", "Ethernet1/3"): ("int_trunk_host", {})}
    groups.append(deepcopy(groups[-1]))
    with pytest.raises(NexusDashboardBrowserError, match="duplicates"):
        api._rows(None, target)
