"""Guard legacy NDFC vPC writes with declared intent and exact readback."""

import json
import sys

import pytest
import yaml

from eve_lab import ndfc_pairing
from eve_lab.ndfc_switches import compile_switches
from eve_lab.nexus_dashboard_browser import NexusDashboardBrowserError
from test_ndfc_dc2 import _fixture, _fake_browser, assert_ready


def _intent():
    intent, _ = _fixture()
    intent["management"]["nd"] = {"address": "192.0.2.1/24"}
    profile = intent["ndfc_fabrics"][0]
    profile["regular_leaf_pair"]["method"] = "Fabric Peering"
    profile["border_leaf_pair"]["method"] = "physical_vpc_peer_link"
    profile["tor_pair"]["method"] = "physical_vpc_peer_link"
    return intent


def _rows(intent):
    _, switches = compile_switches(intent, "DC2")
    roles = {"spine": "spine", "leaf": "leaf",
             "border": "border gateway", "tor": "tor"}
    return [{"logicalName": item["name"], "ipAddress": item["ip"],
             "serialNumber": "SERIAL-" + item["name"],
             "switchDbID": index + 1, "switchRole": roles[item["role"]]}
            for index, item in enumerate(switches)]


def _browser(monkeypatch, rows):
    _fake_browser(monkeypatch)
    monkeypatch.setattr(ndfc_pairing, "_spki_pin", lambda address: "pin")
    monkeypatch.setattr(ndfc_pairing, "_login", lambda *args: None)
    monkeypatch.setattr(ndfc_pairing, "_inventory", lambda *args: rows)
    monkeypatch.setattr(ndfc_pairing, "_wait_for",
                        lambda page, ready, deadline, label: assert_ready(ready))


def test_compile_dc2_three_declared_methods_and_reject_wrong_method():
    intent = _intent()
    fabric, _, pairs = ndfc_pairing.compile_pairs(intent, "DC2")
    assert fabric == "SECOND-FABRIC"
    assert [(item["kind"], item["nodes"], item["useVirtualPeerlink"])
            for item in pairs] == [
                ("regular_leaf_pair", ("L3", "L4"), True),
                ("border_leaf_pair", ("B3", "B4"), False),
                ("tor_pair", ("T3", "T4"), False),
            ]
    intent["ndfc_fabrics"][0]["tor_pair"]["method"] = "Fabric Peering"
    with pytest.raises(ValueError, match="wrong vPC method"):
        ndfc_pairing.compile_pairs(intent, "DC2")


def test_pair_readback_uses_live_switch_database_id_and_shape(monkeypatch):
    sent = []
    body = {"peerOneDbId": 0, "peerTwoDbId": 0,
            "peerOneSerialNumber": None, "peerTwoSerialNumber": None}
    monkeypatch.setattr(ndfc_pairing, "_api", lambda page, method, url:
                        (sent.append((method, url)), (200, body))[1])
    assert ndfc_pairing._pair_info(object(), 2356, "SECOND-FABRIC") is None
    assert sent == [("GET", ndfc_pairing._VPC + "/vpcpairinfo?switchId=2356")]
    assert ndfc_pairing._database_id({"switchDbID": 2356}) == 2356
    with pytest.raises(NexusDashboardBrowserError, match="database ID"):
        ndfc_pairing._database_id({"serialNumber": "SERIAL-L3"})
    body.update(peerOneDbId=2356, peerTwoDbId=2357,
                peerOneSerialNumber="SERIAL-L3",
                peerTwoSerialNumber="SERIAL-L4", fabricName="SECOND-FABRIC")
    assert ndfc_pairing._pair_info(object(), 2356, "SECOND-FABRIC") == {
        "ids": frozenset((2356, 2357)),
        "serials": frozenset(("SERIAL-L3", "SERIAL-L4")),
        "method": None}
    body["fabricName"] = "FOREIGN"
    with pytest.raises(NexusDashboardBrowserError, match="foreign identity"):
        ndfc_pairing._pair_info(object(), 2356, "SECOND-FABRIC")


def test_pair_posts_exact_serials_method_and_is_idempotent(monkeypatch):
    intent = _intent()
    rows = _rows(intent)
    _browser(monkeypatch, rows)
    observed = {}
    serial_to_id = {row["serialNumber"]: row["switchDbID"] for row in rows}
    monkeypatch.setattr(ndfc_pairing, "_pair_info",
                        lambda page, database_id, fabric: observed.get(database_id))
    posts = []
    def api(page, method, endpoint, payload=None):
        if method == "GET":
            selected = endpoint.split("serialNumber=")[1].split("&")[0]
            peer = "SERIAL-L4" if selected == "SERIAL-L3" else "SERIAL-L3"
            return 200, [{"serialNumber": peer, "recommended": False,
                          "blockSelection": False, "fabricName": None}]
        posts.append((method, endpoint, payload))
        first, second = payload["peerOneId"], payload["peerTwoId"]
        info = {"ids": frozenset((serial_to_id[first], serial_to_id[second])),
                "serials": frozenset((first, second)), "method": None}
        for serial in (first, second):
            observed[serial_to_id[serial]] = info
        return 200, {}
    monkeypatch.setattr(ndfc_pairing, "_api", api)
    result = ndfc_pairing.ensure_pairs(
        intent, "user", "secret", site="DC2", kinds=("regular_leaf_pair",))
    assert result["changed"] == ["regular_leaf_pair"]
    assert posts == [("POST", ndfc_pairing._VPC, {
        "peerOneId": "SERIAL-L3", "peerTwoId": "SERIAL-L4",
        "useVirtualPeerlink": True})]
    assert ndfc_pairing.ensure_pairs(
        intent, "user", "secret", site="DC2",
        kinds=("regular_leaf_pair",))["status"] == "already-configured"
    assert len(posts) == 1


def test_recommendation_allows_warning_but_rejects_block_or_wrong_peer(monkeypatch):
    rows = [{"serialNumber": "SERIAL-L4", "recommended": False,
             "blockSelection": False, "fabricName": None}]
    sent = []
    monkeypatch.setattr(ndfc_pairing, "_api", lambda page, method, endpoint:
                        (sent.append((method, endpoint)), (200, rows))[1])
    assert ndfc_pairing._recommendation(
        object(), "SERIAL-L3", "SERIAL-L4", True) is rows[0]
    assert sent[0] == ("GET", ndfc_pairing._VPC +
                       "/recommendation?serialNumber=SERIAL-L3&useVirtualPeerlink=true")
    rows[0]["blockSelection"] = True
    with pytest.raises(NexusDashboardBrowserError, match="absent or blocked"):
        ndfc_pairing._recommendation(object(), "SERIAL-L3", "SERIAL-L4", True)
    rows[0]["blockSelection"] = False
    rows[0]["serialNumber"] = "FOREIGN"
    with pytest.raises(NexusDashboardBrowserError, match="absent or blocked"):
        ndfc_pairing._recommendation(object(), "SERIAL-L3", "SERIAL-L4", True)


def test_pair_rejects_wrong_role_or_conflicting_existing_peer_before_post(monkeypatch):
    intent = _intent()
    rows = _rows(intent)
    _browser(monkeypatch, rows)
    monkeypatch.setattr(ndfc_pairing, "_api", lambda *args: pytest.fail("no write"))
    monkeypatch.setattr(ndfc_pairing, "_pair_info", lambda *args: None)
    rows[2]["switchRole"] = "spine"
    with pytest.raises(NexusDashboardBrowserError, match="role preflight"):
        ndfc_pairing.ensure_pairs(intent, "user", "secret", site="DC2",
                                  kinds=("regular_leaf_pair",))
    rows[2]["switchRole"] = "leaf"
    monkeypatch.setattr(ndfc_pairing, "_pair_info",
                        lambda page, database_id, fabric: {
                            "ids": frozenset((3, 99)),
                            "serials": frozenset(("SERIAL-L3", "FOREIGN")),
                            "method": None} if database_id == 3 else None)
    with pytest.raises(NexusDashboardBrowserError, match="conflicts"):
        ndfc_pairing.ensure_pairs(intent, "user", "secret", site="DC2",
                                  kinds=("regular_leaf_pair",))


def test_pair_cli_check_selects_dc2_without_live_access(tmp_path, monkeypatch, capsys):
    path = tmp_path / "intent.yaml"
    path.write_text(yaml.safe_dump(_intent()))
    monkeypatch.setattr(sys, "argv", ["ndfc_pairing", str(path),
                                         "--site", "DC2", "--check"])
    ndfc_pairing.main()
    result = json.loads(capsys.readouterr().out)
    assert result["fabric"] == "SECOND-FABRIC"
    assert len(result["pairs"]) == 3

