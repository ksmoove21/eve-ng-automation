"""Installed NDFC 12.2.3 composite leaf/ToR pairing contract."""

import json
import sys

import pytest
import yaml

from eve_lab import ndfc_tor_pairing
from eve_lab.ndfc_switches import compile_switches
from eve_lab.nexus_dashboard_browser import NexusDashboardBrowserError
from test_ndfc_dc2 import _fixture, _fake_browser, assert_ready


def _inputs():
    intent, _ = _fixture()
    intent["management"]["nd"] = {"address": "192.0.2.1/24"}
    profile = intent["ndfc_fabrics"][0]
    profile["regular_leaf_pair"]["method"] = "Fabric Peering"
    profile["border_leaf_pair"]["method"] = "physical_vpc_peer_link"
    profile["tor_pair"]["method"] = "physical_vpc_peer_link"
    links = [{"from": {"node": leaf, "interface": "Ethernet1/" + str(51 + ti)},
              "to": {"node": tor, "interface": "Ethernet1/" + str(li + 1)}}
             for li, leaf in enumerate(("L3", "L4"))
             for ti, tor in enumerate(("T3", "T4"))]
    return intent, {"links": links}


def _serials():
    return {"leaf": ("S-L3", "S-L4"), "tor": ("S-T3", "S-T4")}


def _proposal():
    return {key: "1" for key in ndfc_tor_pairing._id_keys(_serials())}


def test_compile_requires_four_exact_direct_links_and_unique_ports():
    intent, topology = _inputs()
    compiled = ndfc_tor_pairing.compile_tor_pair(intent, topology, "DC2")
    assert compiled["fabric"] == "SECOND-FABRIC"
    assert set(compiled["links"]) == {
        ("L3", "T3"), ("L3", "T4"), ("L4", "T3"), ("L4", "T4")}
    topology["links"].pop()
    with pytest.raises(ValueError, match="all four direct links"):
        ndfc_tor_pairing.compile_tor_pair(intent, topology, "DC2")
    topology = _inputs()[1]
    topology["links"][1]["from"]["interface"] = "Ethernet1/51"
    with pytest.raises(ValueError, match="share a port"):
        ndfc_tor_pairing.compile_tor_pair(intent, topology, "DC2")


def test_gui_payload_uses_exact_six_proposed_ids_as_json_string():
    payload = ndfc_tor_pairing._association_payload(_serials(), _proposal())
    assert payload["leafSN1"] == "S-L3"
    assert payload["torSN2"] == "S-T4"
    assert isinstance(payload["poVpc"], str)
    assert json.loads(payload["poVpc"]) == _proposal()
    with pytest.raises(NexusDashboardBrowserError, match="proposed"):
        ndfc_tor_pairing._association_payload(_serials(), {"S-L3_PO": "1"})


def test_proposal_get_uses_all_four_exact_serials(monkeypatch):
    sent = []
    def api(page, method, endpoint):
        sent.append((method, endpoint))
        return 200, _proposal()
    monkeypatch.setattr(ndfc_tor_pairing, "_api", api)
    assert ndfc_tor_pairing._proposed_ids(
        object(), "SECOND-FABRIC", _serials()) == _proposal()
    assert sent == [("GET", ndfc_tor_pairing._TOR +
                     "/SECOND-FABRIC/switches/pair/?switchSN=S-L3&peerSwitchSN=S-L4"
                     "&torSN=S-T3&torPeerSwitchSN=S-T4")]


def test_gui_readback_enable_true_with_null_leaf_serials_is_unpaired():
    view = {"peerSwitchSN": "S-L4", "torPairs": [{
        "torSN": "S-T3,S-T4", "torPeerSN": "S-T4", "torName": "T3~T4",
        "recommended": False, "enable": True, "leafSNs": None,
        "remarks": "Switch(es) are not connected"}]}
    assert ndfc_tor_pairing._association_state(
        view, ["", ""], _serials()["leaf"], _serials()["tor"]) == "unpaired"
    view["torPairs"][0]["leafSNs"] = "S-L3,S-L4"
    assert ndfc_tor_pairing._association_state(
        view, ["", ""], _serials()["leaf"], _serials()["tor"]) == "pending"
    assert ndfc_tor_pairing._association_state(
        view, [{"leafSNs": "S-L3,S-L4"}, {"leafSNs": "S-L3,S-L4"}],
        _serials()["leaf"], _serials()["tor"]) == "paired"
    view["torPairs"][0]["leafSNs"] = "S-L3,FOREIGN"
    with pytest.raises(NexusDashboardBrowserError, match="foreign"):
        ndfc_tor_pairing._association_state(
            view, ["", ""], _serials()["leaf"], _serials()["tor"])


def test_live_method_saves_only_after_vpc_and_inventory_preflight(monkeypatch):
    intent, topology = _inputs()
    _, switches = compile_switches(intent, "DC2")
    roles = {"spine": "spine", "leaf": "leaf", "border": "border gateway",
             "tor": "tor"}
    rows = [{"logicalName": item["name"], "ipAddress": item["ip"],
             "serialNumber": "S-" + item["name"], "switchDbID": i + 1,
             "switchRole": roles[item["role"]]}
            for i, item in enumerate(switches)]
    _fake_browser(monkeypatch)
    monkeypatch.setattr(ndfc_tor_pairing, "_spki_pin", lambda address: "pin")
    monkeypatch.setattr(ndfc_tor_pairing, "_login", lambda *args: None)
    monkeypatch.setattr(ndfc_tor_pairing, "_inventory", lambda *args: rows)
    monkeypatch.setattr(ndfc_tor_pairing, "_wait_for",
                        lambda page, ready, deadline, label: assert_ready(ready))
    serial_ids = {item["serialNumber"]: item["switchDbID"] for item in rows}
    def info(page, database_id, fabric):
        pair = ("S-L3", "S-L4") if database_id in (3, 4) else ("S-T3", "S-T4")
        return {"ids": frozenset(serial_ids[item] for item in pair),
                "serials": frozenset(pair), "method": None}
    monkeypatch.setattr(ndfc_tor_pairing, "_pair_info", info)
    paired = [False]
    def view(page, fabric, leaf_serials):
        return {"peerSwitchSN": "S-L4", "torPairs": [{"torSN": "S-T3,S-T4", "torPeerSN": "S-T4",
                              "leafSNs": "S-L3,S-L4" if paired[0] else None}]}
    monkeypatch.setattr(ndfc_tor_pairing, "_tor_view", view)
    monkeypatch.setattr(ndfc_tor_pairing, "_tor_parent", lambda *args:
                        {"leafSNs": "S-L3,S-L4"} if paired[0] else "")
    monkeypatch.setattr(ndfc_tor_pairing, "_proposed_ids", lambda *args: _proposal())
    posts = []
    def api(page, method, endpoint, payload):
        posts.append((method, endpoint, payload))
        paired[0] = True
        return 200, {}
    monkeypatch.setattr(ndfc_tor_pairing, "_api", api)
    result = ndfc_tor_pairing.ensure_tor_pair(
        intent, topology, "user", "secret", site="DC2")
    assert result["status"] == "paired"
    assert len(posts) == 1
    assert posts[0][0] == "POST"
    assert posts[0][1].endswith("/tor/fabrics/SECOND-FABRIC/switches/pair/custom-id")
    assert json.loads(posts[0][2]["poVpc"]) == _proposal()
    assert ndfc_tor_pairing.ensure_tor_pair(
        intent, topology, "user", "secret", site="DC2")["status"] == "already-paired"
    assert len(posts) == 1
    rows[2]["switchRole"] = "spine"
    with pytest.raises(NexusDashboardBrowserError, match="role differs"):
        ndfc_tor_pairing.ensure_tor_pair(
            intent, topology, "user", "secret", site="DC2")


def test_check_cli_uses_topology_without_network(tmp_path, monkeypatch, capsys):
    intent, topology = _inputs()
    path = tmp_path / "intent.yaml"
    path.write_text(yaml.safe_dump(intent))
    (tmp_path / "topology.yaml").write_text(yaml.safe_dump(topology))
    monkeypatch.setattr(sys, "argv", ["ndfc_tor_pairing", str(path),
                                         "--site", "DC2", "--check"])
    ndfc_tor_pairing.main()
    result = json.loads(capsys.readouterr().out)
    assert result["fabric"] == "SECOND-FABRIC"
    assert len(result["links"]) == 4
