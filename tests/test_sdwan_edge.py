"""IOS XE Catalyst SD-WAN cEdge transaction tests."""
from datetime import datetime, timedelta, timezone
import re
import unittest
from unittest.mock import MagicMock

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from eve_lab.sdwan_edge import (
    CedgeConsole, EdgeStage, absolute_scp_source, certificate_sha256,
    missing_desired_commands, stages_from_edge_plan,
)


_KEY = ec.generate_private_key(ec.SECP256R1())
_NAME = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-ca")])
_NOW = datetime.now(timezone.utc)
CERT = (x509.CertificateBuilder().subject_name(_NAME).issuer_name(_NAME)
        .public_key(_KEY.public_key()).serial_number(1)
        .not_valid_before(_NOW - timedelta(minutes=1))
        .not_valid_after(_NOW + timedelta(days=1))
        .sign(_KEY, hashes.SHA256())
        .public_bytes(serialization.Encoding.PEM).decode("ascii"))


class EdgePlanTests(unittest.TestCase):
    def plan(self):
        return {"adapter": "c8000v-sdwan", "operations": [
            {"name": "controller-mode", "mode": "privileged-exec",
             "command": "controller-mode enable", "one_shot": True},
            *[{"name": name, "mode": "config-transaction",
               "commands": ["system", "exit"], "commit": True}
              for name in ("identity", "transport", "service-lan")],
        ]}

    def test_normalizes_owner_baseline_stage_order(self):
        self.assertEqual([item.name for item in stages_from_edge_plan(self.plan())],
                         ["identity", "transport", "service-lan"])

    def test_rejects_reordered_or_multiline_stage(self):
        plan = self.plan()
        plan["operations"][2]["name"] = "service-lan"
        with self.assertRaises(ValueError):
            stages_from_edge_plan(plan)

    def test_desired_readback_ignores_exit_and_no_shutdown_only(self):
        stages = (EdgeStage("identity", (
            "hostname EDGE", "organization-name org", "no shutdown", "exit")),)
        output = 'hostname EDGE\n organization-name "org"\n'
        self.assertEqual(missing_desired_commands(output, stages), ())
        self.assertEqual(missing_desired_commands("hostname EDGE\n", stages),
                         ("organization-name org",))

    def test_scp_absolute_path_and_certificate_parser(self):
        self.assertEqual(
            absolute_scp_source("admin", "10.1.0.1", "/home/admin/SDWAN.pem"),
            "scp://admin@10.1.0.1//home/admin/SDWAN.pem")
        self.assertEqual(len(certificate_sha256(CERT)), 64)
        with self.assertRaises(ValueError):
            absolute_scp_source("admin", "10.1.0.1", "home/admin/SDWAN.pem")


class EdgeConsoleTests(unittest.TestCase):
    def console(self, responses):
        console = CedgeConsole(MagicMock())
        iterator = iter(responses)
        def expect(pattern, **_kwargs):
            text = next(iterator)
            match = re.search(pattern, text, re.M)
            self.assertIsNotNone(match, text)
            return text, match
        console.expect = MagicMock(side_effect=expect)
        return console

    def test_commits_stage_and_returns_to_exec(self):
        console = self.console([
            "EDGE(config)#", "EDGE(config)#", "EDGE(config)#",
            "Commit complete\nEDGE(config)#", "EDGE#"])
        console.configure_stage(EdgeStage("identity", ("system", "exit")))
        sent = [call.args[0] for call in console.channel.sendall.call_args_list]
        self.assertEqual(sent, [
            "config-transaction\r", "system\r", "exit\r", "commit\r",
            "end\r"])
        self.assertTrue(console.expect.call_args_list[-1].kwargs["redisplay"])
        self.assertTrue(console.expect.call_args_list[0].kwargs["redisplay"])

    def test_rejection_aborts_without_commit(self):
        console = self.console([
            "EDGE(config)#", "% Invalid input\nEDGE(config)#", "EDGE#"])
        with self.assertRaisesRegex(RuntimeError, "command 1"):
            console.configure_stage(EdgeStage("transport", ("bad",)))
        sent = [call.args[0] for call in console.channel.sendall.call_args_list]
        self.assertEqual(sent, ["config-transaction\r", "bad\r", "abort\r"])

    def test_prompt_timeout_names_stage_and_command_without_content(self):
        console = self.console(["EDGE(config)#"])
        console.expect.side_effect = [
            ("EDGE(config)#", re.search(r"[^\n]+#", "EDGE(config)#")),
            RuntimeError("timeout containing secret-command"),
        ]
        with self.assertRaisesRegex(RuntimeError, "transport command 1") as caught:
            console.configure_stage(EdgeStage("transport", ("secret-command",)))
        self.assertNotIn("secret-command", str(caught.exception))

    def test_scp_validates_host_key_and_uses_secret_channel(self):
        console = self.console([
            "RSA key fingerprint is SHA256:trusted\n"
            "Are you sure you want to continue connecting?",
            "Destination filename [SDWAN.pem]?", "Password:",
            "1354 bytes copied\nEDGE#"])
        console.copy_scp_absolute(
            "admin", "10.1.0.1", "/home/admin/SDWAN.pem",
            "bootflash:SDWAN.pem", "secret", {"SHA256:trusted"})
        sent = [call.args[0] for call in console.channel.sendall.call_args_list]
        self.assertEqual(sent, [
            "copy scp://admin@10.1.0.1//home/admin/SDWAN.pem bootflash:SDWAN.pem\r",
            "yes\r", "\r", "secret\r"])

    def test_scp_rejects_wrong_host_key(self):
        console = self.console([
            "RSA key fingerprint is SHA256:wrong\n"
            "Are you sure you want to continue connecting?"])
        with self.assertRaisesRegex(RuntimeError, "fingerprint"):
            console.copy_scp_absolute(
                "admin", "10.1.0.1", "/home/admin/SDWAN.pem",
                "bootflash:SDWAN.pem", "secret", {"SHA256:trusted"})
        self.assertEqual(console.channel.sendall.call_args_list[-1].args[0], "no\r")

    def test_activation_records_attempt_and_discards_output(self):
        console = self.console(["secret echo with backspaces\nEDGE#"])
        attempted = []
        result = console.activate_payg(
            "C8K-PAYG-1234", "one-time-secret", lambda: attempted.append(True))
        self.assertIsNone(result)
        self.assertEqual(attempted, [True])
        self.assertEqual(console.channel.sendall.call_args.args[0],
                         "request platform software sdwan vedge_cloud activate "
                         "chassis-number C8K-PAYG-1234 token one-time-secret\r")


if __name__ == "__main__":
    unittest.main()
