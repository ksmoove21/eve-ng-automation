"""Offline tests for the generic Catalyst SD-WAN intent compiler."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import yaml

from eve_lab.sdwan_intent import compile_intent, load_and_compile


def endpoint(node, interface):
    return {"node": node, "interface": interface}


def direct(name, left_node, left_interface, right_node, right_interface):
    return {
        "name": name,
        "from": endpoint(left_node, left_interface),
        "to": endpoint(right_node, right_interface),
    }


def topology():
    return {
        "name": "sdwan-fixture",
        "remote_folder": "/test",
        "nodes": [
            {"name": "MGR", "template": "vtmgmt", "type": "qemu", "image": "manager"},
            {"name": "VAL", "template": "vtbond", "type": "qemu", "image": "validator"},
            {"name": "CTRL", "template": "vtsmart", "type": "qemu", "image": "controller"},
            {"name": "AGG", "template": "viosl2", "type": "qemu", "image": "switch"},
            {"name": "WAN-A", "template": "iol", "type": "iol", "image": "iol-l3"},
            {"name": "WAN-B", "template": "iol", "type": "iol", "image": "iol-l3"},
            {"name": "EDGE-A", "template": "c8000v", "type": "qemu", "image": "cedge"},
            {"name": "ACCESS-A", "template": "viosl2", "type": "qemu", "image": "switch"},
        ],
        "networks": [{"name": "MGMT", "type": "pnet0"}],
        "links": [
            direct("mgr", "MGR", "eth1", "AGG", "GigabitEthernet0/0"),
            direct("val", "VAL", "ge0/0", "AGG", "GigabitEthernet0/1"),
            direct("ctrl", "CTRL", "eth1", "AGG", "GigabitEthernet0/2"),
            direct("wan-a", "AGG", "GigabitEthernet1/0", "WAN-A", "Ethernet0/0"),
            direct("wan-b", "AGG", "GigabitEthernet1/1", "WAN-B", "Ethernet0/0"),
            direct("edge-a", "EDGE-A", "GigabitEthernet1", "WAN-A", "Ethernet0/1"),
            direct("edge-b", "EDGE-A", "GigabitEthernet2", "WAN-B", "Ethernet0/1"),
            direct("access", "EDGE-A", "GigabitEthernet3", "ACCESS-A",
                   "GigabitEthernet0/0"),
            {"node": "MGR", "interface": "eth0", "network": "MGMT"},
            {"node": "VAL", "interface": "eth0", "network": "MGMT"},
            {"node": "CTRL", "interface": "eth0", "network": "MGMT"},
            {"node": "EDGE-A", "interface": "GigabitEthernet4", "network": "MGMT"},
        ],
    }


def intent():
    return {
        "version": 1,
        "name": "sdwan-fixture",
        "organization_name": "example-sdwan",
        "control_plane": {
            "site_id": 1,
            "service_network": "192.0.2.0/24",
            "vbond_address": "192.0.2.2",
            "transport_color": "private1",
            "aggregation": {
                "node": "AGG",
                "controller_svi": {
                    "interface": "Vlan10",
                    "address": "192.0.2.254/24",
                },
                "transports": {
                    "wan_a": {
                        "interface": "GigabitEthernet1/0",
                        "address": "198.51.100.100/24",
                    },
                    "wan_b": {
                        "interface": "GigabitEthernet1/1",
                        "address": "203.0.113.100/24",
                    },
                },
            },
            "components": [
                {"name": "MGR", "personality": "manager", "hostname": "manager",
                 "system_ip": "10.255.0.1", "site_id": 1,
                 "vpn0_address": "192.0.2.1/24", "vpn0_gateway": "192.0.2.254"},
                {"name": "VAL", "personality": "validator", "hostname": "validator",
                 "system_ip": "10.255.0.2", "site_id": 1,
                 "vpn0_address": "192.0.2.2/24", "vpn0_gateway": "192.0.2.254"},
                {"name": "CTRL", "personality": "controller", "hostname": "controller",
                 "system_ip": "10.255.0.3", "site_id": 1,
                 "vpn0_address": "192.0.2.3/24", "vpn0_gateway": "192.0.2.254"},
            ],
        },
        "transport_fabrics": [
            {"name": "WAN-A", "color": "biz-internet", "subnet": "198.51.100.0/24",
             "mode": "transparent_bridge", "bridge_domain": 101,
             "gateway": {"node": "AGG", "interface": "GigabitEthernet1/0",
                         "address": "198.51.100.100/24"},
             "member_interfaces": ["Ethernet0/0", "Ethernet0/1"]},
            {"name": "WAN-B", "color": "public-internet", "subnet": "203.0.113.0/24",
             "mode": "transparent_bridge", "bridge_domain": 102,
             "gateway": {"node": "AGG", "interface": "GigabitEthernet1/1",
                         "address": "203.0.113.100/24"},
             "member_interfaces": ["Ethernet0/0", "Ethernet0/1"]},
        ],
        "edges": [
            {"name": "EDGE-A", "hostname": "EDGE-A", "system_ip": "10.255.1.1",
             "site_id": 10,
             "transports": [
                 {"interface": "GigabitEthernet1", "address": "198.51.100.1/24",
                  "color": "biz-internet"},
                 {"interface": "GigabitEthernet2", "address": "203.0.113.1/24",
                  "color": "public-internet"},
             ],
             "controller_routes": [
                 {"prefix": "192.0.2.0/24", "next_hop": "198.51.100.100"},
                 {"prefix": "192.0.2.0/24", "next_hop": "203.0.113.100"},
             ],
             "service": {"vpn": 10, "interface": "GigabitEthernet3",
                         "address": "10.10.0.254/24", "switch": "ACCESS-A",
                         "switch_address": "10.10.0.2/24"}},
        ],
        "management": {
            "network": "MGMT", "vpn": 512,
            "addressing_source": "context/management-addressing.yaml",
            "pool": "172.19.3.0/24", "gateway": "172.19.3.1",
            "assignments": {
                "MGR": "172.19.3.20/24", "VAL": "172.19.3.21/24",
                "CTRL": "172.19.3.22/24", "EDGE-A": "172.19.3.23/24",
            },
        },
        "acceptance": {
            "forbid_transport_prefixes": ["/30", "/31"],
            "require_dual_controller_routes": True,
            "require_gateway_owner": "AGG",
            "require_only_visible_network": "MGMT",
        },
    }


class CompilerTests(unittest.TestCase):
    def test_compiles_dependency_order_and_exact_shared_transport_state(self):
        source = intent()
        before = deepcopy(source)
        result = compile_intent(source, topology())
        self.assertEqual(source, before)
        self.assertEqual(result["safety"]["transport_prefixes"],
                         ["198.51.100.0/24", "203.0.113.0/24"])
        self.assertFalse(result["safety"]["contains_secrets"])
        self.assertTrue(result["safety"]["payg_activation_one_shot"])
        dc1 = result["node_operations"]["AGG"]["commands"]
        self.assertIn("ip address 198.51.100.100 255.255.255.0", dc1)
        self.assertIn("ip address 203.0.113.100 255.255.255.0", dc1)
        edge = result["node_operations"]["EDGE-A"]
        self.assertEqual(edge["operations"][0]["command"], "controller-mode enable")
        self.assertTrue(edge["operations"][0]["one_shot"])
        identity = next(item for item in edge["operations"]
                        if item["name"] == "identity")
        transport = next(item for item in edge["operations"]
                         if item["name"] == "transport")
        self.assertEqual(identity["mode"], "config-transaction")
        self.assertTrue(identity["commit"])
        self.assertIn("ip address 198.51.100.1 255.255.255.0",
                      transport["commands"])
        self.assertIn("ip route 192.0.2.0 255.255.255.0 198.51.100.100",
                      transport["commands"])
        self.assertNotIn("write memory", transport["commands"])
        self.assertIn("bridge-domain 101",
                      result["node_operations"]["WAN-A"]["commands"])
        self.assertEqual(
            result["node_operations"]["WAN-A"]["capability_gate"]["classification"],
            "FIELD_PROVEN")
        self.assertEqual(
            result["node_operations"]["WAN-A"]["validation"]["bridge_domain"],
            101)

    def test_compiles_service_lan_and_switch_desired_state(self):
        result = compile_intent(intent(), topology())
        edge = result["node_operations"]["EDGE-A"]
        service = next(item for item in edge["operations"]
                       if item["name"] == "service-lan")
        self.assertIn("vrf forwarding 10", service["commands"])
        self.assertIn("ip address 10.10.0.254 255.255.255.0",
                      service["commands"])
        switch = result["node_operations"]["ACCESS-A"]["commands"]
        self.assertIn("ip address 10.10.0.2 255.255.255.0", switch)
        self.assertIn("ip default-gateway 10.10.0.254", switch)

    def test_compiles_controller_interfaces_stages_and_management(self):
        result = compile_intent(intent(), topology())
        manager = result["node_operations"]["MGR"]
        self.assertEqual(manager["adapter"], "viptela-control")
        self.assertEqual([stage["name"] for stage in manager["operations"]],
                         ["identity", "vpn0", "vpn512"])
        self.assertIn("interface eth1", manager["operations"][1]["commands"])
        self.assertIn("allow-service all", manager["operations"][1]["commands"])
        self.assertIn("interface eth0", manager["operations"][2]["commands"])
        self.assertIn("ip address 172.19.3.20/24",
                      manager["operations"][2]["commands"])
        validator = result["node_operations"]["VAL"]
        self.assertIn("vbond 192.0.2.2 local",
                      validator["operations"][0]["commands"])
        self.assertIn("no interface eth0",
                      validator["operations"][1]["commands"])
        self.assertIn("allow-service netconf",
                      validator["operations"][1]["commands"])
        self.assertIn("allow-service sshd",
                      validator["operations"][1]["commands"])
        self.assertIn("no allow-service all",
                      validator["operations"][1]["commands"])
        self.assertNotIn("allow-service all",
                         validator["operations"][1]["commands"])
        controller = result["node_operations"]["CTRL"]
        self.assertNotIn("encapsulation ipsec",
                         controller["operations"][1]["commands"])
        edge = result["node_operations"]["EDGE-A"]["desired"]
        self.assertEqual(edge["vpn512_address"], "172.19.3.23/24")

    def test_rejects_incomplete_duplicate_or_off_pool_management(self):
        missing = intent()
        del missing["management"]["assignments"]["CTRL"]
        duplicate = intent()
        duplicate["management"]["assignments"]["CTRL"] = "172.19.3.20/24"
        off_pool = intent()
        off_pool["management"]["assignments"]["CTRL"] = "172.18.3.22/24"
        for value in (missing, duplicate, off_pool):
            with self.subTest(value=value), self.assertRaises(ValueError):
                compile_intent(value, topology())

    def test_rejects_reversed_control_appliance_interface_roles(self):
        value = topology()
        for link in value["links"]:
            if link.get("name") == "mgr":
                link["from"]["interface"] = "eth0"
            elif link.get("node") == "MGR" and link.get("network") == "MGMT":
                link["interface"] = "eth1"
        with self.assertRaisesRegex(ValueError, "transport/management interfaces"):
            compile_intent(intent(), value)

    def test_rejects_subdivision_wrong_gateway_and_missing_direct_link(self):
        cases = []
        subdivided = intent()
        subdivided["transport_fabrics"][0]["subnet"] = "198.51.100.0/31"
        cases.append(subdivided)
        wrong_owner = intent()
        wrong_owner["transport_fabrics"][0]["gateway"]["node"] = "WAN-A"
        cases.append(wrong_owner)
        wrong_route = intent()
        wrong_route["edges"][0]["controller_routes"][0]["next_hop"] = "198.51.100.99"
        cases.append(wrong_route)
        duplicate_bridge = intent()
        duplicate_bridge["transport_fabrics"][1]["bridge_domain"] = 101
        cases.append(duplicate_bridge)
        for item in cases:
            with self.subTest(item=item), self.assertRaises(ValueError):
                compile_intent(item, topology())
        disconnected = topology()
        disconnected["links"] = [item for item in disconnected["links"]
                                 if item.get("name") != "access"]
        with self.assertRaisesRegex(ValueError, "not linked"):
            compile_intent(intent(), disconnected)

    def test_rejects_runtime_secret_or_identity_material(self):
        for key in ("token", "otp", "uuid", "chassis_number"):
            value = intent()
            value["edges"][0][key] = "must-not-be-here"
            with self.subTest(key=key), self.assertRaisesRegex(
                    ValueError, "runtime identity or secret"):
                compile_intent(value, topology())

    def test_rejects_extra_visible_network(self):
        value = topology()
        value["networks"].append({"name": "EXTRA", "type": "bridge"})
        with self.assertRaisesRegex(ValueError, "only the management"):
            compile_intent(intent(), value)

    def test_load_and_compile_reads_workspace_intent(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "labs" / "sdwan-fixture"
            base.mkdir(parents=True)
            (base / "intent.yaml").write_text(yaml.safe_dump(intent()))
            result = load_and_compile(root, "sdwan-fixture", topology())
            self.assertEqual(result["lab"], "sdwan-fixture")


if __name__ == "__main__":
    unittest.main()
