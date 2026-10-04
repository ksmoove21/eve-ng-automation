"""Exact-link EVE Pro Manage request guards."""

from copy import deepcopy

import pytest

from eve_lab.network_manage import compile_manage_payload, manage_network


TOPOLOGY = {"name": "lab", "remote_folder": "/", "links": [{
    "name": "Border-PA", "from": {"node": "Border-1", "interface": "Ethernet1/1"},
    "to": {"node": "PA-1", "interface": "eth1/1"}}]}
NETWORK = {"name": "Border-PA", "type": "bridge", "count": 2,
           "smart": 0, "vlan8021ad": 0, "native_vlan": 1, "pnet_out": "",
           "l2filter_lldp": 0, "l2filter_stp": 0,
           "l2filter_cisco": 0, "l2filter_lacp": 0,
           "interfaces": [
               {"NodeId": 6, "NodeName": "Border-1", "IfId": 1,
                "IfName": "E1/1", "VlanId": 1},
               {"NodeId": 10, "NodeName": "PA-1", "IfId": 1,
                "IfName": "eth1/1", "VlanId": 1}]}


def test_manage_payload_preserves_complete_gui_bridge_form():
    body = compile_manage_payload(TOPOLOGY, "Border-PA", 23, NETWORK)
    assert body == {"network": "23", "smart": "0", "vlan8021ad": "0",
                    "native_vlan": "1", "pnet_out": "", "l2filter_lldp": "0",
                    "l2filter_stp": "0", "l2filter_cisco": "0",
                    "l2filter_lacp": "0", "port": {
                        "0": {"NodeId": "6", "NodeName": "Border-1", "IfId": "1",
                              "IfName": "E1/1", "Vlan": "1"},
                        "1": {"NodeId": "10", "NodeName": "PA-1", "IfId": "1",
                              "IfName": "eth1/1", "Vlan": "1"}}}


def test_manage_rejects_endpoint_drift_without_write():
    class Client:
        writes = []
        def request(self, method, path, payload=None):
            if method != "GET":
                self.writes.append((method, path))
            if path.endswith("/networks"):
                return {"23": {"name": "Border-PA"}}
            changed = deepcopy(NETWORK)
            changed["interfaces"][0]["IfName"] = "E1/2"
            return changed
    client = Client()
    with pytest.raises(ValueError, match="differs"):
        manage_network(client, TOPOLOGY, "Border-PA", 23, apply=True)
    assert client.writes == []


def test_manage_checks_before_exact_single_write_and_readback():
    class Client:
        def __init__(self):
            self.writes = []
        def request(self, method, path, payload=None):
            if method == "PUT":
                self.writes.append((path, payload))
                return {}
            if path.endswith("/networks"):
                return {"23": {"name": "Border-PA"}}
            return deepcopy(NETWORK)
    client = Client()
    assert manage_network(client, TOPOLOGY, "Border-PA", 23)["status"] == "checked"
    assert client.writes == []
    assert manage_network(client, TOPOLOGY, "Border-PA", 23, apply=True)["status"] == "manage-accepted"
    assert len(client.writes) == 1
    assert client.writes[0][0].endswith("/network/manage")
    assert client.writes[0][1]["network"] == "23"
