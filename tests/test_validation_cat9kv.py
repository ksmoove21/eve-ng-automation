from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

import yaml

from eve_lab.validation import validate_lab
from eve_lab.validation_cat9kv import evaluate, validate_check


LICENSE = """Technology Package License Information:
network-advantage  Smart License              network-advantage
dna-advantage      Subscription Smart License dna-advantage
"""
ROUTE = """Routing entry for 0.0.0.0/0
  Known via "static", distance 1, metric 0
  Routing Descriptor Blocks:
  * 192.0.2.1
      Route metric is 0, traffic share count is 1
"""
OSPF_NEIGHBOR = """Neighbor ID     Pri   State           Dead Time   Address         Interface
198.51.100.2      0   FULL/  -        00:00:38    203.0.113.2     GigabitEthernet1/0/1
"""


INTENT = {
    "profiles": ["dnac-bootstrap", "ospf-underlay"],
    "hostname": "C9K-1",
    "domain_name": "example.test",
    "management": {
        "address": "192.0.2.10", "prefix_length": 24, "gateway": "192.0.2.1",
    },
    "dnac": {
        "license": {"network": "network-advantage", "dna": "dna-advantage"},
    },
    "underlay": {
        "ospf": {"process_id": 100, "router_id": "198.51.100.1"},
        "loopback": {
            "interface": "Loopback0", "address": "198.51.100.1/32",
            "ospf_area": "0", "ospf_process_id": 100,
        },
        "routed_interfaces": [{
            "interface": "GigabitEthernet1/0/1", "address": "203.0.113.1/30",
            "ospf_area": "0", "ospf_process_id": 100,
            "network_type": "point-to-point",
        }],
    },
}


class Cat9kvValidationTests(unittest.TestCase):
    def console(self):
        console = MagicMock()
        outputs = {
            "show running-config | include ^hostname": "hostname C9K-1\n",
            "show running-config | include ^ip domain name": "ip domain name example.test\n",
            "show running-config | section ^aaa": (
                "aaa new-model\naaa authentication login default local\n"
                "aaa authorization exec default local if-authenticated\n"
                "aaa authorization console\n"),
            "show running-config | include ^username": (
                "username automation privilege 15 secret 9 redacted\n"),
            "show ip ssh": "SSH Enabled - version 2.0\n",
            "show privilege": "Current privilege level is 15\n",
            "show netconf-yang status": "netconf-yang: enabled\n",
            "show running-config | include ^snmp-server community": (
                "snmp-server community hidden-ro RO\n"
                "snmp-server community hidden-rw RW\n"),
            "show crypto key mypubkey rsa": "Key name: C9K-1.example.test\n",
            "show running-config interface GigabitEthernet0/0": (
                "interface GigabitEthernet0/0\n vrf forwarding Mgmt-vrf\n"
                " ip address 192.0.2.10 255.255.255.0\n no shutdown\n"),
            "show ip route vrf Mgmt-vrf 0.0.0.0 0.0.0.0": ROUTE,
            "show version": LICENSE,
            "show running-config | include ^ip routing": "ip routing\n",
            "show ip ospf 100 | include Routing Process|Router ID": (
                ' Routing Process "ospf 100" with ID 198.51.100.1\n'),
            "show running-config interface Loopback0": (
                "interface Loopback0\n ip address 198.51.100.1 255.255.255.255\n"
                " ip ospf 100 area 0\n no shutdown\n"),
            "show running-config interface GigabitEthernet1/0/1": (
                "interface GigabitEthernet1/0/1\n no switchport\n"
                " ip address 203.0.113.1 255.255.255.252\n"
                " ip ospf network point-to-point\n ip ospf 100 area 0\n no shutdown\n"),
            "show ip ospf neighbor": OSPF_NEIGHBOR,
        }
        console.command.side_effect = lambda command, **kwargs: outputs[command]
        console.interface_status.return_value = [
            {"interface": "GigabitEthernet0/0", "ip_address": "192.0.2.10",
             "status": "up", "protocol": "up"},
            {"interface": "Loopback0", "ip_address": "198.51.100.1",
             "status": "up", "protocol": "up"},
            {"interface": "GigabitEthernet1/0/1", "ip_address": "203.0.113.1",
             "status": "up", "protocol": "up"},
        ]
        return console

    def test_dnac_bootstrap_passes_without_exposing_communities(self):
        console = self.console()
        passed, evidence = evaluate(
            console, {"type": "cat9kv-dnac-bootstrap"}, INTENT,
            username="automation")
        self.assertTrue(passed)
        self.assertEqual(evidence["readiness"], "DNAC_BOOTSTRAP_READY")
        self.assertTrue(all(evidence["observed"]["checks"].values()))
        self.assertNotIn("hidden-ro", repr(evidence))
        self.assertNotIn("hidden-rw", repr(evidence))

    def test_dnac_bootstrap_fails_closed_on_missing_netconf(self):
        console = self.console()
        original = console.command.side_effect
        console.command.side_effect = lambda command, **kwargs: (
            "netconf-yang: disabled\n" if command == "show netconf-yang status"
            else original(command, **kwargs))
        passed, evidence = evaluate(
            console, {"type": "cat9kv-dnac-bootstrap"}, INTENT,
            username="automation")
        self.assertFalse(passed)
        self.assertFalse(evidence["observed"]["checks"]["netconf_enabled"])

    def test_underlay_passes_with_and_without_declared_neighbor(self):
        for neighbors in ([], [{"neighbor": "198.51.100.2", "state": "full"}]):
            with self.subTest(neighbors=neighbors):
                console = self.console()
                check = {"type": "cat9kv-underlay", "neighbors": neighbors}
                passed, evidence = evaluate(console, check, INTENT)
                self.assertTrue(passed)
                self.assertEqual(evidence["readiness"], "UNDERLAY_READY")
                if not neighbors:
                    self.assertNotIn(
                        "show ip ospf neighbor",
                        [call.args[0] for call in console.command.call_args_list])

    def test_underlay_neighbor_is_required_only_when_declared(self):
        console = self.console()
        console.command.side_effect = lambda command, **kwargs: (
            OSPF_NEIGHBOR.replace("FULL/  -", "INIT/  -")
            if command == "show ip ospf neighbor" else
            self.console().command.side_effect(command, **kwargs))
        passed, evidence = evaluate(console, {
            "type": "cat9kv-underlay",
            "neighbors": [{"neighbor": "198.51.100.2", "state": "full"}],
        }, INTENT)
        self.assertFalse(passed)
        self.assertFalse(evidence["observed"]["checks"]["neighbors"])

    def test_underlay_retries_one_empty_interface_response(self):
        console = self.console()
        original = console.command.side_effect
        command = "show running-config interface GigabitEthernet1/0/1"
        attempts = 0

        def response(value, **kwargs):
            nonlocal attempts
            if value == command:
                attempts += 1
                if attempts == 1:
                    return "\n"
            return original(value, **kwargs)

        console.command.side_effect = response
        passed, _ = evaluate(console, {"type": "cat9kv-underlay"}, INTENT)
        self.assertTrue(passed)
        self.assertEqual(attempts, 2)

    def test_underlay_still_fails_closed_after_empty_interface_retry(self):
        console = self.console()
        original = console.command.side_effect
        command = "show running-config interface GigabitEthernet1/0/1"
        console.command.side_effect = lambda value, **kwargs: (
            "\n" if value == command else original(value, **kwargs))
        passed, evidence = evaluate(console, {"type": "cat9kv-underlay"}, INTENT)
        self.assertFalse(passed)
        self.assertFalse(evidence["observed"]["checks"]["interfaces"])

    def test_neighbor_schema_rejects_duplicates_and_injection(self):
        for neighbors in (
            [{"neighbor": "198.51.100.2;reload", "state": "full"}],
            [{"neighbor": "198.51.100.2", "state": "invalid"}],
            [{"neighbor": "198.51.100.2", "state": "full"}] * 2,
        ):
            with self.subTest(neighbors=neighbors), self.assertRaises(ValueError):
                validate_check({"type": "cat9kv-underlay", "neighbors": neighbors})

    def test_runner_reports_both_readiness_states(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            configs = root / "labs/fixture/configs"
            configs.mkdir(parents=True)
            (root / "context").mkdir()
            context = {
                "approved_pools": [{
                    "id": "pool", "network": "192.0.2.0/24",
                    "gateway": "192.0.2.1", "interface_prefix_length": 24,
                }],
                "allocations": [{
                    "allocation_id": "fixture", "pool_id": "pool",
                    "assignments": [{
                        "logical_device_id": "fixture/C9K-1",
                        "address": "192.0.2.10",
                    }],
                }],
            }
            (root / "context/management.yaml").write_text(
                yaml.safe_dump(context), encoding="utf-8")
            data = {
                "schema_version": 1,
                "profiles": ["dnac-bootstrap", "ospf-underlay"],
                "hostname": "C9K-1", "domain_name": "example.test",
                "management": {
                    "source": "context/management.yaml",
                    "allocation_id": "fixture",
                    "logical_device_id": "fixture/C9K-1",
                },
                "dnac": {
                    "snmp_ro_env": "CAT9KV_SNMP_RO_COMMUNITY",
                    "snmp_rw_env": "CAT9KV_SNMP_RW_COMMUNITY",
                    "rsa_modulus": 2048,
                    "license": {
                        "network": "network-advantage", "dna": "dna-advantage",
                    },
                },
                "underlay": {
                    "ospf": {"process_id": 100, "router_id": "198.51.100.1"},
                    "loopback": {
                        "interface": "Loopback0", "address": "198.51.100.1/32",
                        "ospf_area": 0,
                    },
                    "routed_interfaces": [{
                        "interface": "GigabitEthernet1/0/1",
                        "address": "203.0.113.1/30", "ospf_area": 0,
                    }],
                },
            }
            (configs / "C9K-1-init.yaml").write_text(
                yaml.safe_dump(data), encoding="utf-8")
            topology = {
                "name": "fixture",
                "nodes": [{"name": "C9K-1"}],
                "validation": [
                    {"name": "bootstrap", "type": "cat9kv-dnac-bootstrap",
                     "node": "C9K-1"},
                    {"name": "underlay", "type": "cat9kv-underlay",
                     "node": "C9K-1"},
                ],
            }
            node = {
                "name": "C9K-1", "template": "cat9kvuadp", "status": "2",
                "console": "telnet", "url": "telnet://example.invalid:32770",
            }
            channel, console = MagicMock(), MagicMock()
            with patch("eve_lab.validation.named", return_value={"C9K-1": node}), \
                    patch("eve_lab.validation.load_server", return_value={
                        "url": "https://example.invalid", "ssh_username": "test",
                        "ssh_password": "test"}), \
                    patch("eve_lab.validation.credentials", return_value=["test"] * 3), \
                    patch("eve_lab.validation._open_console", return_value=(channel, console)), \
                    patch("eve_lab.validation.validation_cat9kv.evaluate", side_effect=[
                        (True, {"readiness": "DNAC_BOOTSTRAP_READY"}),
                        (True, {"readiness": "UNDERLAY_READY"}),
                    ]), \
                    patch("eve_lab.validation.paramiko.SSHClient") as ssh:
                report = validate_lab(MagicMock(), topology, root)
            self.assertEqual(report["result"], "pass")
            self.assertEqual(report["readiness"]["C9K-1"], [
                "DNAC_BOOTSTRAP_READY", "UNDERLAY_READY"])
            self.assertEqual(
                ssh.return_value.get_transport.return_value.open_channel.call_count, 2)


if __name__ == "__main__":
    unittest.main()
