from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, call, patch

import yaml

from eve_lab.initialize import initialize
from eve_lab.device_console import Console
from eve_lab.initialize_cat9kv import (
    Cat9kvConsole, bootstrap_commands, load_bootstrap, parse_license_state,
    runtime_secrets,
)


CURRENT = """Cisco IOS XE Software
Technology Package License Information:
network-advantage  Smart License              network-advantage
dna-advantage      Subscription Smart License dna-advantage
"""
PENDING = """Cisco IOS XE Software
Technology Package License Information:
network-essentials Smart License              network-advantage
                   Subscription Smart License dna-advantage
"""


class Cat9kvInitTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "context").mkdir()
        self.context = {
            "approved_pools": [{
                "id": "test-pool", "network": "192.0.2.0/24",
                "gateway": "192.0.2.1", "interface_prefix_length": 24,
            }],
            "allocations": [{
                "allocation_id": "test-cat9kv", "pool_id": "test-pool",
                "assignments": [{
                    "logical_device_id": "test/C9K-1", "address": "192.0.2.10",
                }],
            }],
        }
        (self.root / "context/management.yaml").write_text(
            yaml.safe_dump(self.context), encoding="utf-8")
        self.data = {
            "schema_version": 1,
            "profiles": ["dnac-bootstrap", "ospf-underlay"],
            "hostname": "C9K-1",
            "domain_name": "example.test",
            "management": {
                "source": "context/management.yaml",
                "allocation_id": "test-cat9kv",
                "logical_device_id": "test/C9K-1",
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
                    "network_type": "point-to-point",
                }],
            },
        }
        self.path = self.root / "node-init.yaml"
        self.path.write_text(yaml.safe_dump(self.data), encoding="utf-8")

    def test_context_resolution_and_profile_rendering(self):
        intent = load_bootstrap(self.path, self.root)
        self.assertEqual(intent["management"]["address"], "192.0.2.10")
        self.assertEqual(intent["management"]["gateway"], "192.0.2.1")
        commands = bootstrap_commands(
            intent, "automation", "device-pass", "enable-pass", "ro-value", "rw-value")
        for expected in (
            "interface GigabitEthernet0/0",
            "vrf forwarding Mgmt-vrf",
            "ip address 192.0.2.10 255.255.255.0",
            "ip route vrf Mgmt-vrf 0.0.0.0 0.0.0.0 192.0.2.1",
            "aaa authorization exec default local if-authenticated",
            "aaa authorization console",
            "login authentication default",
            "netconf-yang",
            "license boot level network-advantage addon dna-advantage",
            "interface Loopback0",
            "interface GigabitEthernet1/0/1",
            "ip ospf network point-to-point",
            "router ospf 100",
            "no passive-interface GigabitEthernet1/0/1",
        ):
            self.assertIn(expected, commands)
        self.assertNotIn("10.100.254.20", "\n".join(commands))

    def test_schema_rejects_implicit_or_unsafe_state(self):
        cases = []
        cases.append({**self.data, "profiles": ["ospf-underlay"]})
        cases.append({**self.data, "management": {
            **self.data["management"], "source": "../outside.yaml"}})
        cases.append({**self.data, "underlay": {
            **self.data["underlay"], "ospf": {"process_id": 100, "router_id": "198.51.100.2"}}})
        for index, data in enumerate(cases):
            with self.subTest(index=index):
                self.path.write_text(yaml.safe_dump(data), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_bootstrap(self.path, self.root)

    def test_runtime_snmp_secrets_are_environment_owned(self):
        intent = load_bootstrap(self.path, self.root)
        with patch.dict("os.environ", {
            "CAT9KV_SNMP_RO_COMMUNITY": "read-only",
            "CAT9KV_SNMP_RW_COMMUNITY": "read-write",
        }, clear=True):
            self.assertEqual(
                runtime_secrets(intent, self.root), ("read-only", "read-write"))
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "CAT9KV_SNMP"):
                runtime_secrets(intent, self.root)

    def test_license_parser_distinguishes_current_and_next_boot(self):
        self.assertEqual(parse_license_state(CURRENT), {
            "current": ["dna-advantage", "network-advantage"],
            "next_boot": ["dna-advantage", "network-advantage"],
        })
        self.assertEqual(parse_license_state(PENDING), {
            "current": ["network-essentials"],
            "next_boot": ["dna-advantage", "network-advantage"],
        })
        with self.assertRaises(RuntimeError):
            parse_license_state("License Level: network-advantage")

    def test_console_skips_existing_rsa_and_unneeded_reload(self):
        intent = load_bootstrap(self.path, self.root)
        console = MagicMock(spec=Cat9kvConsole)
        console.command.side_effect = lambda command, **kwargs: (
            CURRENT if command == "show version" else
            "Key name: test.example\n" if command == "show crypto key mypubkey rsa" else
            "Building configuration...\n[OK]\n" if command == "write memory" else "")
        result = Cat9kvConsole.initialize(
            console, intent, username="automation", password="device-pass",
            secret="enable-pass", snmp_ro="ro-value", snmp_rw="rw-value")
        self.assertFalse(result["reload_required"])
        self.assertEqual(
            console.command.call_args_list[0].args[0], "terminal length 0")
        console.request_reload.assert_not_called()
        self.assertNotIn(
            "crypto key generate rsa general-keys modulus 2048",
            [call.args[0] for call in console.command.call_args_list])

    def test_console_requests_reload_only_for_pending_license(self):
        intent = load_bootstrap(self.path, self.root)
        console = MagicMock(spec=Cat9kvConsole)
        versions = iter([PENDING, PENDING])

        def response(command, **kwargs):
            if command == "show version":
                return next(versions)
            if command == "show crypto key mypubkey rsa":
                return "% Key pair not found\n"
            if command == "write memory":
                return "[OK]\n"
            return ""

        console.command.side_effect = response
        result = Cat9kvConsole.initialize(
            console, intent, username="automation", password="device-pass",
            secret="enable-pass", snmp_ro="ro-value", snmp_rw="rw-value")
        self.assertTrue(result["reload_required"])
        console.request_reload.assert_called_once_with()
        self.assertIn(
            "crypto key generate rsa general-keys modulus 2048",
            [call.args[0] for call in console.command.call_args_list])

    def test_console_rejection_reports_only_command_index(self):
        intent = load_bootstrap(self.path, self.root)
        console = MagicMock(spec=Cat9kvConsole)

        def response(command, **kwargs):
            if command == "show version":
                return CURRENT
            if command == "ip domain name example.test":
                raise RuntimeError("raw device output")
            return ""

        console.command.side_effect = response
        with self.assertRaisesRegex(
                RuntimeError, "command 2 was rejected; command and output omitted") as caught:
            Cat9kvConsole.initialize(
                console, intent, username="automation", password="device-pass",
                secret="enable-pass", snmp_ro="ro-value", snmp_rw="rw-value")
        self.assertNotIn("example.test", str(caught.exception))
        self.assertNotIn("raw device output", str(caught.exception))

    @patch.object(Console, "login")
    def test_reload_login_selects_golden_image_only_after_exact_failure(self, login):
        channel = MagicMock()
        console = Cat9kvConsole(channel, boot_timeout=600)
        console.expect = MagicMock(side_effect=[
            ("error: invalid magic number\nPress any key to continue...\n"
             "terminal redraw follows", MagicMock()),
            ("VNGWC - packages.conf\nVNGWC - GOLDEN IMAGE", MagicMock()),
        ])
        self.assertTrue(console.login_after_reload("automation", "password", "secret"))
        self.assertEqual(channel.sendall.call_args_list, [
            call("\x12"), call(" "), call("\x1b[B\r")])
        login.assert_called_once_with("automation", "password", "secret")

    @patch.object(Console, "login")
    def test_reload_login_recovers_when_reconnect_sees_grub_menu(self, login):
        channel = MagicMock()
        console = Cat9kvConsole(channel, boot_timeout=600)
        console.expect = MagicMock(return_value=(
            "VNGWC - packages.conf\nVNGWC - GOLDEN IMAGE", MagicMock()))
        self.assertTrue(console.login_after_reload("automation", "password", "secret"))
        self.assertEqual(channel.sendall.call_args_list, [
            call("\x12"), call("\x1b[B\r")])
        login.assert_called_once_with("automation", "password", "secret")

    @patch.object(Console, "login")
    def test_reload_login_uses_space_only_after_silent_ctrl_r_probe(self, login):
        channel = MagicMock()
        console = Cat9kvConsole(channel, boot_timeout=600)
        console.expect = MagicMock(side_effect=[
            ("", None),
            ("VNGWC - packages.conf\nVNGWC - GOLDEN IMAGE", MagicMock()),
        ])
        self.assertTrue(console.login_after_reload("automation", "password", "secret"))
        self.assertEqual(channel.sendall.call_args_list, [
            call("\x12"), call(" "), call("\x1b[B\r")])
        login.assert_called_once_with("automation", "password", "secret")

    def test_post_reload_license_verification_disables_pagination(self):
        intent = load_bootstrap(self.path, self.root)
        console = MagicMock(spec=Cat9kvConsole)
        console.command.side_effect = lambda command, **kwargs: (
            CURRENT if command == "show version" else "")
        state = Cat9kvConsole.verify_license(console, intent)
        self.assertEqual(state["current"], ["dna-advantage", "network-advantage"])
        self.assertEqual(console.command.call_args_list[0].args[0], "terminal length 0")

    @patch("eve_lab.initialize.paramiko.SSHClient")
    def test_initialize_check_plans_structured_cat9kv_file(self, ssh):
        lab = self.root / "labs/test/configs"
        lab.mkdir(parents=True)
        (lab / "C9K-1-init.yaml").write_text(
            yaml.safe_dump(self.data), encoding="utf-8")
        client = MagicMock()
        client.request.return_value = {"7": {
            "name": "C9K-1", "template": "cat9kvuadp", "status": 2,
            "console": "telnet", "url": "telnet://192.0.2.50:32770",
        }}
        result = initialize(
            client, {"name": "test"}, self.root, "default", check=True)
        self.assertEqual(result["planned"][0]["template"], "cat9kvuadp")
        self.assertTrue(result["planned"][0]["file"].endswith("-init.yaml"))
        ssh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
