from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from eve_lab.validation import validate_lab


CONFIG = """<config>
  <devices>
    <entry name="localhost.localdomain">
      <network>
        <interface>
          <ethernet>
            <entry name="ethernet1/1"/>
          </ethernet>
        </interface>
      </network>
    </entry>
  </devices>
</config>"""


class PanosRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        lab = self.root / "labs" / "fixture"
        lab.mkdir(parents=True)
        (lab / "init.yaml").write_text(
            "PA:\n  management_ip: 192.0.2.10\n", encoding="utf-8")
        self.node = {
            "name": "PA",
            "template": "paloalto",
            "status": "2",
        }

    def run_validation(self, *, required=True, present=True, connect_error=None,
                       running_error=None, running_xml=CONFIG):
        check = {
            "name": "interface",
            "type": "panos-interface",
            "node": "PA",
            "interface": "ethernet1/1" if present else "ethernet1/2",
            "expected": "present",
        }
        if not required:
            check["required"] = False
        topology = {
            "name": "fixture",
            "nodes": [{"name": "PA"}],
            "validation": [check],
        }
        client = MagicMock()
        device, channel = MagicMock(), MagicMock()

        with ExitStack() as stack:
            stack.enter_context(patch(
                "eve_lab.validation.named", return_value={"PA": self.node}))
            stack.enter_context(patch(
                "eve_lab.validation.load_server", return_value={
                    "url": "https://eve.example.invalid",
                    "ssh_username": "eve-user",
                    "ssh_password": "eve-password",
                }))
            stack.enter_context(patch(
                "eve_lab.validation.credentials", return_value=["admin", "palo-password"]))
            ssh_factory = stack.enter_context(patch("eve_lab.validation.paramiko.SSHClient"))
            connect = stack.enter_context(patch("eve_lab.validation.connect_palo"))
            console_factory = stack.enter_context(patch("eve_lab.validation.PaloConsole"))
            running = stack.enter_context(patch("eve_lab.validation.palo_running"))
            connect.return_value = (device, channel)
            if connect_error is not None:
                connect.side_effect = connect_error
            if running_error is not None:
                running.side_effect = running_error
            else:
                running.return_value = running_xml

            report = validate_lab(client, topology, self.root)

        ssh = ssh_factory.return_value
        ssh.load_system_host_keys.assert_called_once_with()
        ssh.set_missing_host_key_policy.assert_not_called()
        ssh.close.assert_called_once_with()
        if connect_error is None:
            connect.assert_called_once_with(
                ssh, "192.0.2.10", "admin", "palo-password", 60)
            console_factory.return_value.login.assert_called_once_with(
                "admin", "palo-password")
            channel.close.assert_called_once_with()
            device.close.assert_called_once_with()
        return report

    def test_optional_assertion_failure_after_successful_transport_keeps_pass(self):
        report = self.run_validation(required=False, present=False)
        self.assertEqual(report["result"], "pass")
        self.assertEqual(report["checks"][0]["result"], "fail")
        self.assertFalse(report["checks"][0]["required"])
        self.assertNotIn("failure_kind", report["checks"][0]["evidence"])

    def test_management_ssh_transport_failure_fails_optional_run(self):
        report = self.run_validation(
            required=False, connect_error=RuntimeError("management SSH unavailable"))
        self.assertEqual(report["result"], "fail")
        self.assertEqual(
            report["checks"][0]["evidence"]["failure_kind"], "execution")

    def test_running_config_retrieval_failure_fails_optional_run(self):
        report = self.run_validation(
            required=False, running_error=RuntimeError("running config unavailable"))
        self.assertEqual(report["result"], "fail")
        self.assertEqual(
            report["checks"][0]["evidence"]["failure_kind"], "execution")

    def test_running_config_xml_parse_failure_fails_optional_run(self):
        report = self.run_validation(required=False, running_xml="<config><devices>")
        self.assertEqual(report["result"], "fail")
        self.assertEqual(
            report["checks"][0]["evidence"]["failure_kind"], "execution")

    def test_required_assertion_failure_fails_run(self):
        report = self.run_validation(present=False)
        self.assertEqual(report["result"], "fail")
        self.assertEqual(report["checks"][0]["result"], "fail")
        self.assertNotIn("failure_kind", report["checks"][0]["evidence"])

    def test_successful_assertion_passes_run(self):
        report = self.run_validation()
        self.assertEqual(report["result"], "pass")
        self.assertEqual(report["checks"][0]["result"], "pass")


if __name__ == "__main__":
    unittest.main()
