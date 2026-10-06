"""Offline tests for the controller-only Catalyst SD-WAN compiler."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import yaml

from eve_lab.sdwan_control_intent import compile_intent, load_and_compile


def link(name, left, left_if, right, right_if):
    return {"name": name, "from": {"node": left, "interface": left_if},
            "to": {"node": right, "interface": right_if}}


def topology():
    return {
        "name": "control-fixture", "remote_folder": "/test",
        "nodes": [
            {"name": "MGR", "template": "vtmgmt", "image": "vtmgmt-20.15.1"},
            {"name": "VAL", "template": "vtbond", "image": "vtbond-20.15.1"},
            {"name": "CTRL", "template": "vtsmart", "image": "vtsmart-20.15.1"},
            {"name": "LEAF", "template": "nxosv"},
        ],
        "networks": [{"name": "CLOUD0", "type": "pnet0"}],
        "links": [
            link("mgr-transport", "MGR", "eth0", "LEAF", "Ethernet1/1"),
            link("val-transport", "VAL", "eth0", "LEAF", "Ethernet1/2"),
            link("ctrl-transport", "CTRL", "eth0", "LEAF", "Ethernet1/3"),
            {"node": "MGR", "interface": "eth1", "network": "CLOUD0"},
        ],
    }


def intent():
    def controller(name, personality, system_ip, address, peer):
        return {"name": name, "personality": personality, "hostname": name.lower(),
                "system_ip": system_ip, "site_id": 1,
                "transport": {"interface": "eth0", "address": address,
                              "gateway": "192.0.2.254", "color": "private1",
                              "peer": {"node": "LEAF", "interface": peer}}}
    manager = controller("MGR", "manager", "10.255.0.1", "192.0.2.1/24", "Ethernet1/1")
    manager["management"] = {"network": "CLOUD0", "interface": "eth1",
                             "address": "198.51.100.2/24", "gateway": "198.51.100.1"}
    return {"version": 1, "name": "control-fixture", "organization_name": "example-sdwan",
            "vbond_address": "192.0.2.2", "controllers": [
                manager,
                controller("VAL", "validator", "10.255.0.2", "192.0.2.2/24", "Ethernet1/2"),
                controller("CTRL", "controller", "10.255.0.3", "192.0.2.3/24", "Ethernet1/3"),
            ]}


class ControlIntentTests(unittest.TestCase):
    def test_compiles_only_controllers_and_cleans_dhcp_on_declared_transport(self):
        source = intent()
        result = compile_intent(source, topology())
        self.assertEqual(source, intent())
        self.assertEqual(set(result["node_operations"]), {"MGR", "VAL", "CTRL"})
        self.assertEqual(result["safety"], {"contains_secrets": False,
                                             "topology_synthesized": False})
        manager = result["node_operations"]["MGR"]
        self.assertEqual([item["name"] for item in manager["operations"]],
                         ["identity", "vpn0", "vpn512"])
        vpn0 = manager["operations"][1]["commands"]
        transport = vpn0.index("interface eth0")
        self.assertEqual(vpn0[transport + 1:transport + 3],
                         ["no ip dhcp-client", "no ipv6 dhcp-client"])
        self.assertIn("no interface eth1", vpn0)
        self.assertEqual([item["name"] for item in result["node_operations"]["VAL"]["operations"]],
                         ["identity", "vpn0"])

    def test_rejects_unsafe_and_mismatched_topology(self):
        secret = intent()
        secret["controllers"][0]["token"] = "not-allowed"
        commands = intent()
        commands["controllers"][0]["commands"] = ["bad"]
        wrong_link = intent()
        wrong_link["controllers"][0]["transport"]["peer"]["interface"] = "Ethernet1/9"
        missing_management = topology()
        missing_management["links"] = missing_management["links"][:-1]
        for value, topo in ((secret, topology()), (commands, topology()),
                            (wrong_link, topology()), (intent(), missing_management)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                compile_intent(value, topo)

    def test_allows_shared_site_and_rejects_wrong_appliance_image(self):
        self.assertEqual(compile_intent(intent(), topology())["node_operations"]["MGR"]["desired"]["site_id"], 1)
        wrong = topology()
        wrong["nodes"][1]["image"] = "vtbond-20.12.6"
        with self.assertRaisesRegex(ValueError, "20.15.1"):
            compile_intent(intent(), wrong)

    def test_loader_rejects_path_traversal_before_reading(self):
        with self.assertRaisesRegex(ValueError, "Invalid controller lab name"):
            load_and_compile(Path("."), "../other", topology())

    def test_loads_standalone_controller_intent(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "labs" / "control-fixture"
            base.mkdir(parents=True)
            (base / "controller-intent.yaml").write_text(yaml.safe_dump(intent()), encoding="utf-8")
            self.assertEqual(load_and_compile(root, "control-fixture", topology())["lab"],
                             "control-fixture")


if __name__ == "__main__":
    unittest.main()
