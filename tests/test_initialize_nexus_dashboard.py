from pathlib import Path
from tempfile import TemporaryDirectory
import re
import unittest
from unittest.mock import MagicMock, patch, call

import yaml

from eve_lab.initialize import initialize
from eve_lab.initialize_nexus_dashboard import (
    NexusDashboardConsole, load_bootstrap, normalize_intent,
)


INTENT = {
    "schema_version": 1,
    "cluster_name": "nd-disposable",
    "management": {"address": "172.18.3.9/24", "gateway": "172.18.3.1"},
    "data": {"address": "172.22.3.10/24", "gateway": "172.22.3.1"},
    "dns_servers": ["10.100.0.1"],
    "search_domains": ["UNSC.IN"],
    "ntp_servers": ["10.100.0.1", "10.100.0.254"],
    "persistent_service_ip_count": 5,
    "fabric_controller": {
        "enabled": True,
        "device_management_connectivity": "data",
    },
}


def observed(text):
    return text, re.search(NexusDashboardConsole._PROMPTS, text, re.M)


class NexusDashboardInitTests(unittest.TestCase):
    def test_intent_derives_persistent_addresses_and_preserves_data_selection(self):
        intent = normalize_intent(INTENT)
        self.assertEqual(intent["persistent_service_ips"], [
            "172.22.3.11", "172.22.3.12", "172.22.3.13",
            "172.22.3.14", "172.22.3.15",
        ])
        self.assertEqual(
            intent["fabric_controller"]["device_management_connectivity"],
            "data")
        self.assertTrue(intent["cluster_leader"])

    def test_intent_rejects_overlap_bad_connectivity_and_derived_gateway(self):
        cases = [
            {**INTENT, "data": {
                "address": "172.18.3.10/24", "gateway": "172.18.3.1"}},
            {**INTENT, "fabric_controller": {
                "enabled": True, "device_management_connectivity": "invalid"}},
            {**INTENT, "data": {
                "address": "172.22.3.10/24", "gateway": "172.22.3.11"}},
        ]
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_intent(value)

    def test_yaml_loader_requires_exact_schema(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "ND-01-init.yaml"
            path.write_text(yaml.safe_dump(INTENT), encoding="utf-8")
            self.assertEqual(load_bootstrap(path), normalize_intent(INTENT))
            path.write_text(yaml.safe_dump({**INTENT, "unknown": True}),
                            encoding="utf-8")
            with self.assertRaises(ValueError):
                load_bootstrap(path)

    def test_serial_first_boot_uses_cr_only_and_records_observed_release(self):
        channel = MagicMock()
        console = NexusDashboardConsole(channel, boot_timeout=900)
        console.expect = MagicMock(side_effect=[
            observed("Press any key to run first-boot setup on this console..."),
            observed("Welcome to Nexus Dashboard 3.2.1i\n"
                     "Press Enter to manually bootstrap your node..."),
            observed("Admin Password:"),
            observed("Reenter Admin Password:"),
            observed("Management Network:\n  IP Address/Mask:"),
            observed("Gateway:"),
            observed("Is Cluster Leader? Note: only one node in the cluster must be leader. (Y/n):"),
            observed("Please review the config\nRe-enter config?(y/N):"),
            observed("System configured successfully"),
        ])

        result = console.initialize(normalize_intent(INTENT), password="secret-value")

        self.assertEqual(result["status"], "configured")
        self.assertEqual(result["release"], "3.2.1i")
        self.assertEqual(channel.sendall.call_args_list, [
            call(" \r"), call("\r"), call("secret-value\r"),
            call("secret-value\r"), call("172.18.3.9/24\r"),
            call("172.18.3.1\r"), call("y\r"), call("n\r"),
        ])
        self.assertTrue(all("\n" not in item.args[0]
                            for item in channel.sendall.call_args_list))

    def test_existing_login_prompt_is_idempotent_and_does_not_send_input(self):
        channel = MagicMock()
        console = NexusDashboardConsole(channel, boot_timeout=30)
        console.expect = MagicMock(return_value=observed("nd-node login:"))
        result = console.initialize(normalize_intent(INTENT), password="secret-value")
        self.assertEqual(result["status"], "already-configured")
        channel.sendall.assert_not_called()

    def test_repeated_secret_prompt_fails_without_exposing_secret(self):
        channel = MagicMock()
        console = NexusDashboardConsole(channel, boot_timeout=30)
        console.expect = MagicMock(side_effect=[
            observed("Admin Password:"), observed("Admin Password:"),
        ])
        with self.assertRaisesRegex(RuntimeError, "repeated") as caught:
            console.initialize(normalize_intent(INTENT), password="secret-value")
        self.assertNotIn("secret-value", str(caught.exception))

    @patch("eve_lab.initialize.paramiko.SSHClient")
    def test_initializer_check_plans_nd_yaml_on_selected_satellite(self, ssh):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "labs/test/configs"
            base.mkdir(parents=True)
            (base / "ND-01-init.yaml").write_text(
                yaml.safe_dump(INTENT), encoding="utf-8")
            client = MagicMock()
            client.request.side_effect = [
                {"1": {"name": "ND-01", "template": "nd", "status": 2,
                       "console": "telnet", "url": "telnet://eve.test:48469",
                       "sat": 3}},
                {"3": {"id": 3, "name": "eve-sat03", "online": 1}},
            ]
            result = initialize(
                client, {"name": "test"}, root, "default", check=True)
            self.assertEqual(result["planned"][0]["template"], "nd")
            self.assertEqual(result["planned"][0]["satellite"], "eve-sat03")
            self.assertTrue(result["planned"][0]["file"].endswith("-init.yaml"))
            ssh.assert_not_called()


if __name__ == "__main__":
    unittest.main()