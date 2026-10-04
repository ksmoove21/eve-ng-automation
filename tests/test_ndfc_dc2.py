"""Nonprivate DC2 fixtures for explicit NDFC site selection."""

from copy import deepcopy
import json
import sys

import pytest
import yaml

from eve_lab.ndfc_fabric import compile_fabric
from eve_lab.ndfc_switches import compile_switches
from eve_lab.ndfc_tenants import (
    compile_tenants, compile_tor_access_ports, preflight_inventory,
)


def _fixture():
    roles = {
        "spine": ["S3", "S4"], "leaf": ["L3", "L4"],
        "border": ["B3", "B4"], "tor": ["T3", "T4"],
    }
    switches = [name for pair in roles.values() for name in pair]
    fabric = {
        "site": "DC2", "name": "SECOND-FABRIC", "mode": "Data Center VXLAN EVPN",
        "bgp_asn": 65002, "replication": "ingress",
        "multicast_replication": "disabled",
        "infrastructure_pools": {
            "underlay_links": "10.11.100.0/24", "loopbacks": "10.11.101.0/24",
            "vpc_peer_keepalive": "10.11.102.0/24",
            "anycast_vtep": "10.11.103.0/24",
        },
        "switch_import": {"greenfield": True, "preserve_config": False},
        "network_vlan_range": "200-299", "vrf_vlan_range": "300-399",
        "vpc_peer_keepalive_option": "management",
        "leaf_pre_interfaces_freeform": "feature dhcp\nservice dhcp",
        "spine_pair": {"nodes": roles["spine"]},
        "regular_leaf_pair": {"nodes": roles["leaf"]},
        "border_leaf_pair": {"nodes": roles["border"]},
        "tor_pair": {"nodes": roles["tor"]},
    }
    intent = {
        "ndfc_fabrics": [fabric],
        "scope": {"r7_activation_set": switches},
        "management": {"fabric_edge": {"assignments": {
            name: "192.0.2." + str(index + 10) + "/24"
            for index, name in enumerate(switches)}}},
        "tenants": {
            "isolation": "no_inter_vrf_route_leaking", "host_port_mode": "access",
            "vni_policy": {"l2_range": "20000-29999", "l3_range": "30000-39999"},
            "dc2": [
                {"vrf": "BLUE", "vrf_vni": 30110, "vrf_vlan": 330,
                 "zone": "BLUE-ZONE", "networks": [
                     {"name": "BLUE-NET", "prefix": "10.11.10.0/24",
                      "gateway": "10.11.10.1", "vlan": 210, "vni": 20110,
                      "dhcp": "fabric_leaf", "dhcp_deployment": "deferred"}],
                 "endpoints": [{"node": "H3", "attachment": "T3",
                                "address": "10.11.10.11/24", "gateway": "10.11.10.1"}]},
                {"vrf": "GREEN", "vrf_vni": 30120, "vrf_vlan": 340,
                 "zone": "GREEN-ZONE", "networks": [
                     {"name": "GREEN-NET", "prefix": "10.11.20.0/24",
                      "gateway": "10.11.20.1", "vlan": 220, "vni": 20120,
                      "dhcp": "fabric_leaf", "dhcp_deployment": "deferred"}],
                 "endpoints": [{"node": "H4", "attachment": "T4",
                                "address": "10.11.20.11/24", "gateway": "10.11.20.1"}]},
            ],
        },
    }
    topology = {"links": [
        {"from": {"node": "H3", "interface": "eth0"},
         "to": {"node": "T3", "interface": "Ethernet1/3"}},
        {"from": {"node": "H4", "interface": "eth0"},
         "to": {"node": "T4", "interface": "Ethernet1/4"}},
    ]}
    return intent, topology


def test_dc2_compiles_explicit_fabric_vrf_vlan_range_and_switches():
    intent, _ = _fixture()
    name, nv = compile_fabric(intent, "DC2")
    assert name == "SECOND-FABRIC"
    assert nv["BGP_AS"] == "65002"
    assert nv["NETWORK_VLAN_RANGE"] == "200-299"
    assert nv["VRF_VLAN_RANGE"] == "300-399"
    assert nv["SUBNET_RANGE"] == "10.11.100.0/24"
    fabric, switches = compile_switches(intent, "DC2")
    assert fabric == name
    assert len(switches) == 8
    assert [x["name"] for x in switches[:2]] == ["S3", "S4"]
    assert {x["role"] for x in switches} == {"spine", "leaf", "border", "tor"}


def test_dc2_tenants_and_endpoint_ports_use_selected_site():
    intent, topology = _fixture()
    compiled = compile_tenants(intent, "DC2")
    assert compiled["fabric"] == "SECOND-FABRIC"
    assert [(x["name"], x["vni"], x["vlan"]) for x in compiled["vrfs"]] == [
        ("BLUE", 30110, 330), ("GREEN", 30120, 340)]
    assert [(x["name"], x["vni"], x["vlan"]) for x in compiled["networks"]] == [
        ("BLUE-NET", 20110, 210), ("GREEN-NET", 20120, 220)]
    assert compile_tor_access_ports(intent, topology, "DC2") == [
        {"tor": "T3", "port": "Ethernet1/3", "network": "BLUE-NET", "vlan": 210},
        {"tor": "T4", "port": "Ethernet1/4", "network": "GREEN-NET", "vlan": 220},
    ]


def test_dc2_inventory_preflight_rejects_cross_site_or_wrong_role():
    intent, _ = _fixture()
    _, switches = compile_switches(intent, "DC2")
    roles = {"spine": "spine", "leaf": "leaf", "border": "border gateway", "tor": "tor"}
    inventory = [{"logicalName": row["name"], "ipAddress": row["ip"],
                  "switchRole": roles[row["role"]], "serialNumber": "S" + str(i),
                  "ccStatus": "In-Sync"} for i, row in enumerate(switches)]
    assert len(preflight_inventory(intent, inventory, site="DC2")) == 8
    inventory[0]["switchRole"] = "leaf"
    with pytest.raises(ValueError, match="identity or sync"):
        preflight_inventory(intent, inventory, site="DC2")


@pytest.mark.parametrize("edit,match", [
    (lambda i: i["ndfc_fabrics"][0].update(vrf_vlan_range="200-399"), "overlap"),
    (lambda i: i["tenants"]["dc2"][0].update(vrf_vlan=400), "VRF VLAN"),
    (lambda i: i["ndfc_fabrics"][0].pop("switch_import"), "switch_import"),
    (lambda i: i["ndfc_fabrics"][0].pop("spine_pair"), "spine_pair"),
])
def test_dc2_rejects_missing_or_conflicting_declared_fields(edit, match):
    intent, _ = _fixture()
    edit(intent)
    with pytest.raises(ValueError, match=match):
        compile_switches(intent, "DC2")


def test_dc2_cli_check_selects_site_without_live_access(tmp_path, monkeypatch, capsys):
    from eve_lab import ndfc_fabric, ndfc_tenant_api
    intent, _ = _fixture()
    path = tmp_path / "intent.yaml"
    path.write_text(yaml.safe_dump(intent))
    monkeypatch.setattr(sys, "argv", ["ndfc_fabric", str(path), "--site", "DC2", "--check"])
    ndfc_fabric.main()
    assert json.loads(capsys.readouterr().out)["fabric"] == "SECOND-FABRIC"
    monkeypatch.setattr(sys, "argv", ["ndfc_tenant_api", str(path), "--site", "DC2", "--check"])
    ndfc_tenant_api.main()
    checked = json.loads(capsys.readouterr().out)
    assert checked["fabric"] == "SECOND-FABRIC"
    assert checked["dhcp_status"] == {
        "BLUE-NET": "deferred", "GREEN-NET": "deferred"}


def test_dc2_live_cli_dispatch_uses_selected_site_without_network(
        tmp_path, monkeypatch, capsys):
    from eve_lab import ndfc_fabric, ndfc_tenant_api
    intent, topology = _fixture()
    path = tmp_path / "intent.yaml"
    path.write_text(yaml.safe_dump(intent))
    (tmp_path / "topology.yaml").write_text(yaml.safe_dump(topology))
    monkeypatch.setattr(ndfc_fabric, "_environment", lambda *_: {
        "CISCO_USERNAME": "user", "CISCO_PASSWORD": "placeholder"})
    monkeypatch.setattr(ndfc_tenant_api, "_environment", lambda *_: {
        "NDFC_RUNNER_USERNAME": "user", "NDFC_RUNNER_PASSWORD": "placeholder"})
    calls = []
    monkeypatch.setattr(ndfc_fabric, "ensure_fabric", lambda *args: (
        calls.append(("fabric", args[-1])), {"fabric": "SECOND-FABRIC"})[1])
    monkeypatch.setattr(ndfc_tenant_api, "stage_tenants", lambda *args: (
        calls.append(("stage", args[-1])), {"fabric": "SECOND-FABRIC"})[1])
    monkeypatch.setattr(ndfc_tenant_api, "attach_tenants", lambda *args: (
        calls.append(("attach", args[-1])), {"fabric": "SECOND-FABRIC"})[1])
    monkeypatch.setattr(ndfc_tenant_api, "deploy_tenants", lambda *args: (
        calls.append(("deploy", args[-1])), {"fabric": "SECOND-FABRIC"})[1])
    monkeypatch.setattr(sys, "argv", ["ndfc_fabric", str(path), "--site", "DC2"])
    ndfc_fabric.main()
    for option in ([], ["--attach"], ["--deploy"]):
        monkeypatch.setattr(sys, "argv", [
            "ndfc_tenant_api", str(path), "--site", "DC2", *option])
        ndfc_tenant_api.main()
    assert calls == [("fabric", "DC2"), ("stage", "DC2"),
                     ("attach", "DC2"), ("deploy", "DC2")]
    assert capsys.readouterr().out.count("SECOND-FABRIC") == 4


def test_dc2_fabric_leaf_dhcp_requires_explicit_deferral_before_api():
    from eve_lab.ndfc_tenant_api import attach_tenants, deploy_tenants, stage_tenants
    from eve_lab.ndfc_tenants import network_create_payload, validate_network_dhcp
    intent, topology = _fixture()
    compiled = compile_tenants(intent, "DC2")
    assert [x["dhcp"] for x in compiled["networks"]] == ["fabric_leaf"] * 2
    assert [validate_network_dhcp(x) for x in compiled["networks"]] == ["deferred"] * 2
    payload = network_create_payload("SECOND-FABRIC", compiled["networks"][0])
    config = json.loads(payload["networkTemplateConfig"])
    assert not any("dhcp" in key.lower() for key in config)
    del intent["tenants"]["dc2"][0]["networks"][0]["dhcp_deployment"]
    for operation in [
        lambda: stage_tenants(intent, "user", "placeholder", "DC2"),
        lambda: attach_tenants(intent, topology, "user", "placeholder", "DC2"),
        lambda: deploy_tenants(intent, topology, "user", "placeholder", "DC2"),
    ]:
        with pytest.raises(ValueError, match="dhcp_deployment: deferred"):
            operation()


def _fake_browser(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    import playwright.sync_api

    page = SimpleNamespace(goto=lambda *a, **kw: None)
    browser = SimpleNamespace(new_page=lambda: page, close=lambda: None)
    runtime = SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kw: browser))
    monkeypatch.setattr(playwright.sync_api, "sync_playwright",
                        lambda: nullcontext(runtime))


def test_dc2_import_reconciles_only_exact_inventory(monkeypatch):
    from eve_lab import ndfc_import
    from eve_lab.nexus_dashboard_browser import NexusDashboardBrowserError

    intent, _ = _fixture()
    intent["management"]["nd"] = {"address": "192.0.2.1/24"}
    _, switches = compile_switches(intent, "DC2")
    _fake_browser(monkeypatch)
    monkeypatch.setattr(ndfc_import, "_spki_pin", lambda address: "pin")
    monkeypatch.setattr(ndfc_import, "_login", lambda *a: None)
    rows = [{"logicalName": row["name"], "ipAddress": row["ip"],
             "serialNumber": "S" + str(i)}
            for i, row in enumerate(switches)]
    monkeypatch.setattr(ndfc_import, "_inventory", lambda *a: rows)
    monkeypatch.setattr(ndfc_import, "_api", lambda *a: pytest.fail(
        "exact inventory must not be imported again"))
    result = ndfc_import.import_switches(intent, "user", "secret", site="DC2")
    assert result["status"] == "already-imported"
    assert result["fabric"] == "SECOND-FABRIC"
    rows[0]["ipAddress"] = "192.0.2.200"
    with pytest.raises(NexusDashboardBrowserError, match="differs"):
        ndfc_import.import_switches(intent, "user", "secret", site="DC2")


def test_dc2_roles_post_only_differing_serial(monkeypatch):
    from eve_lab import ndfc_roles

    intent, _ = _fixture()
    intent["management"]["nd"] = {"address": "192.0.2.1/24"}
    _, switches = compile_switches(intent, "DC2")
    _fake_browser(monkeypatch)
    monkeypatch.setattr(ndfc_roles, "_spki_pin", lambda address: "pin")
    monkeypatch.setattr(ndfc_roles, "_login", lambda *a: None)
    roles = {"spine": "spine", "leaf": "leaf",
             "border": "border gateway", "tor": "tor"}
    rows = [{"logicalName": row["name"], "ipAddress": row["ip"],
             "serialNumber": "S" + str(i), "switchRole": roles[row["role"]]}
            for i, row in enumerate(switches)]
    rows[0]["switchRole"] = "leaf"
    monkeypatch.setattr(ndfc_roles, "_inventory", lambda *a: rows)
    sent = []
    def api(page, method, endpoint, payload):
        sent.append((method, endpoint, payload))
        rows[0]["switchRole"] = "spine"
        return 200, {}
    monkeypatch.setattr(ndfc_roles, "_api", api)
    monkeypatch.setattr(ndfc_roles, "_wait_for",
                        lambda page, ready, deadline, label: assert_ready(ready))
    result = ndfc_roles.ensure_switch_roles(intent, "user", "secret", site="DC2")
    assert result["changed"] == 1
    assert sent == [("POST", ndfc_roles._ROLES,
                     [{"serialNumber": "S0", "role": "spine"}])]


def assert_ready(ready):
    assert ready()


def test_dc2_switch_deploy_rejects_cross_site_selection_before_api():
    from eve_lab.ndfc_switch_deploy import deploy_switches

    intent, _ = _fixture()
    with pytest.raises(ValueError, match="declared DC2"):
        deploy_switches(intent, "user", "secret", names=["S1"], site="DC2")
