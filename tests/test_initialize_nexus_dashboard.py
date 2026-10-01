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
from eve_lab.nexus_dashboard_browser import _state


INTENT = {
    "schema_version": 1,
    "cluster_name": "nd-disposable",
    "management": {"address": "192.0.2.9/24", "gateway": "192.0.2.1"},
    "data": {"address": "198.51.100.10/24", "gateway": "198.51.100.1"},
    "dns_servers": ["203.0.113.53"],
    "search_domains": ["example.test"],
    "ntp_servers": ["203.0.113.53", "203.0.113.123"],
    "persistent_service_ip_count": 5,
    "fabric_controller": {
        "enabled": True,
        "device_management_connectivity": "data",
    },
}


def observed(text):
    return text, re.search(NexusDashboardConsole._PROMPTS, text, re.M)


class NexusDashboardInitTests(unittest.TestCase):
    def test_browser_state_distinguishes_landing_page_from_cluster_bringup(self):
        class Body:
            def __init__(self, text):
                self.text = text
            def inner_text(self):
                return self.text
        class Page:
            def __init__(self, text):
                self.text = text
            def locator(self, selector):
                if selector != "body":
                    raise AssertionError("unexpected selector")
                return Body(self.text)
        self.assertEqual(_state(Page(
            "Cluster Bringup Answer some questions Configuration")),
            "awaiting-bringup")
        self.assertEqual(_state(Page(
            "Cluster Bringup Bootstrap Cluster Deployment")), "initializing")
        self.assertEqual(_state(Page(
            "Nexus Dashboard Overview Cluster Bringup Cluster settings")),
            "ready-or-post-bringup")

    def test_intent_derives_persistent_addresses_and_preserves_data_selection(self):
        intent = normalize_intent(INTENT)
        self.assertEqual(intent["persistent_service_ips"], [
            "198.51.100.11", "198.51.100.12", "198.51.100.13",
            "198.51.100.14", "198.51.100.15",
        ])
        self.assertEqual(
            intent["fabric_controller"]["device_management_connectivity"],
            "data")
        self.assertTrue(intent["cluster_leader"])

    def test_intent_rejects_overlap_bad_connectivity_and_derived_gateway(self):
        cases = [
            {**INTENT, "data": {
                "address": "192.0.2.10/24", "gateway": "192.0.2.1"}},
            {**INTENT, "fabric_controller": {
                "enabled": True, "device_management_connectivity": "invalid"}},
            {**INTENT, "data": {
                "address": "198.51.100.10/24", "gateway": "198.51.100.11"}},
        ]
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_intent(value)

    def test_intent_accepts_ntp_hostname_without_relaxing_dns_validation(self):
        hostname_intent = {**INTENT, "ntp_servers": ["time.example.test"]}
        self.assertEqual(
            normalize_intent(hostname_intent)["ntp_servers"],
            ["time.example.test"])
        with self.assertRaisesRegex(ValueError, "ntp_servers"):
            normalize_intent({**INTENT, "ntp_servers": ["not a hostname"]})

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
            call("secret-value\r"), call("192.0.2.9/24\r"),
            call("192.0.2.1\r"), call("y\r"), call("n\r"),
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

    @patch("eve_lab.initialize.nexus_dashboard_https_ready", return_value=True)
    @patch("eve_lab.initialize.nexus_dashboard_bringup", return_value={
        "status": "ready-or-post-bringup", "login": True, "stage": "classified"})
    @patch("eve_lab.initialize.credentials", return_value=("admin", "secret-value", ""))
    @patch("eve_lab.initialize.load_server", return_value={
        "url": "https://eve.test", "ssh_username": "root", "ssh_password": "secret"})
    @patch("eve_lab.initialize.paramiko.SSHClient")
    def test_initializer_uses_documented_browser_workflow_after_serial_bootstrap(
            self, ssh, server, credentials, browser, https_ready):
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
            result = initialize(client, {"name": "test"}, root, "default")
        self.assertEqual(result["completed"], ["ND-01"])
        self.assertEqual(result["lifecycle"]["ND-01"]["status"],
                         "ready-or-post-bringup")
        browser.assert_called_once_with(
            normalize_intent(INTENT), "admin", "secret-value", timeout=600)
        https_ready.assert_called_once_with(normalize_intent(INTENT))
        ssh.return_value.close.assert_called_once()

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