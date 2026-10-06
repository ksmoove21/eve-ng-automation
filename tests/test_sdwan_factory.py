"""Pure factory contract and one-shot ledger tests."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from eve_lab.sdwan_factory import FactoryLedger, correlate_single_new


class PaygCorrelationTests(unittest.TestCase):
    def test_requires_exactly_one_set_difference(self):
        uuid, record = correlate_single_new(
            [{"uuid": "old"}], [{"uuid": "old"}, {"uuid": "new", "x": 1}])
        self.assertEqual(uuid, "new")
        self.assertEqual(record["x"], 1)
        for after in ([{"uuid": "old"}],
                      [{"uuid": "old"}, {"uuid": "a"}, {"uuid": "b"}]):
            with self.assertRaisesRegex(RuntimeError, "exactly one"):
                correlate_single_new([{"uuid": "old"}], after)


class FactoryLedgerTests(unittest.TestCase):
    def nodes(self, suffix):
        return {name: {"uuid": name + suffix} for name in (
            "MANAGER1", "VALIDATOR1", "CONTROLLER1",
            "CEDGE-S2", "CEDGE-S3", "CEDGE-S4")}

    def test_same_generation_resumes_and_new_eve_uuids_isolate_state(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "factory.json"
            ledger = FactoryLedger(path)
            first = ledger.bind(self.nodes("-a"))
            first["edges"]["CEDGE-S2"] = {"activation_attempted": True}
            ledger.save()
            resumed = FactoryLedger(path)
            self.assertTrue(resumed.bind(self.nodes("-a"))["edges"]
                            ["CEDGE-S2"]["activation_attempted"])
            fresh = resumed.bind(self.nodes("-b"))
            self.assertEqual(fresh["edges"], {})
            self.assertEqual(len(resumed.value["generations"]), 2)

    def test_missing_uuid_fails_closed(self):
        with TemporaryDirectory() as directory:
            nodes = self.nodes("-a")
            nodes["CEDGE-S4"]["uuid"] = ""
            with self.assertRaisesRegex(RuntimeError, "requires an EVE UUID"):
                FactoryLedger(Path(directory) / "factory.json").bind(nodes)



class DeclaredManagerTests(unittest.TestCase):
    def test_signing_uses_explicit_manager_instead_of_factory_name(self):
        from unittest.mock import Mock, patch
        from contextlib import nullcontext
        from eve_lab.sdwan_factory import _sign_on_manager
        context, console = Mock(), Mock()
        with patch("eve_lab.sdwan_factory._pinned_management_console",
                   return_value=nullcontext(console)) as connection, patch(
                       "eve_lab.sdwan_factory.sign_csr_on_manager",
                       return_value="signed") as signer:
            self.assertEqual(_sign_on_manager(context, "csr", "controller",
                             manager_name="DECLARED-MGR"), "signed")
        connection.assert_called_once_with(context, "DECLARED-MGR")
        signer.assert_called_once_with(console, "csr", name="controller")

    def test_installed_manager_certificate_uses_declared_state_and_identity(self):
        from unittest.mock import Mock, patch
        from eve_lab.sdwan_factory import _install_manager_certificate
        context = Mock()
        state = {"nodes": {"DECLARED-MGR": {}}}
        context.control_plan.return_value = {"desired": {"system_ip": "192.0.2.1"}}
        inventory = {"rootCertHash": "a" * 40}
        with patch("eve_lab.sdwan_factory.read_control_state", return_value=state), patch(
                "eve_lab.sdwan_factory.control_component_record", return_value=inventory) as record, patch(
                "eve_lab.sdwan_factory.certificate_is_installed", return_value=True), patch(
                "eve_lab.sdwan_factory.write_control_state"):
            self.assertFalse(_install_manager_certificate(context, Mock(), manager_name="DECLARED-MGR"))
        context.control_plan.assert_called_once_with("DECLARED-MGR")
        self.assertEqual(record.call_args.kwargs["device_ip"], "192.0.2.1")
        self.assertEqual(state["nodes"]["DECLARED-MGR"]["manager_control_certificate"], "installed")


class DeclaredEdgeManagerTests(unittest.TestCase):
    def test_payg_generation_uses_declared_manager_and_one_inventory_delta(self):
        from unittest.mock import Mock
        from eve_lab.sdwan_factory import _ensure_payg
        context, api = Mock(), Mock()
        context.generation = {}
        context.control_plan.return_value = {"desired": {"organization_name": "example-org"}}
        api.inventory.side_effect = [[], [{"uuid": "new-identity", "chasisNumber": "chassis-test", "token": "test-token"}]]
        api.generate_payg.return_value = {}
        edge, record = _ensure_payg(context, api, "EDGE", manager_name="DECLARED-MGR")
        context.control_plan.assert_called_once_with("DECLARED-MGR")
        api.generate_payg.assert_called_once_with(count=1, validity="valid", organization="example-org")
        self.assertEqual(edge["correlated_uuid"], "new-identity")
        self.assertTrue(edge["generation_attempted"])

    def test_fingerprint_read_uses_explicit_transport_and_rejects_injection(self):
        from unittest.mock import Mock, patch
        from contextlib import nullcontext
        from eve_lab.sdwan_factory import _manager_ssh_fingerprints
        context, console = Mock(), Mock()
        console.command.return_value = "tunnel-interface\nallow-service all"
        with patch("eve_lab.sdwan_factory._pinned_management_console",
                   return_value=nullcontext(console)) as connection, patch(
                       "eve_lab.sdwan_factory.manager_ca_certificate", return_value="root"), patch(
                       "eve_lab.sdwan_factory._enter_shell"), patch(
                       "eve_lab.sdwan_factory._leave_shell"), patch(
                       "eve_lab.sdwan_factory._shell_command", return_value=("0", "SHA256:abc123")):
            root, pins = _manager_ssh_fingerprints(context, manager_name="DECLARED-MGR", transport_interface="eth0")
        connection.assert_called_once_with(context, "DECLARED-MGR")
        console.command.assert_called_once_with("show running-config vpn 0 interface eth0 | nomore", timeout=120)
        self.assertEqual(pins, {"SHA256:abc123"})
        with self.assertRaises(ValueError):
            _manager_ssh_fingerprints(context, transport_interface="eth0\nrequest reboot")


class EdgeAuthenticationTests(unittest.TestCase):
    def run_configuration(self, login_errors, edge):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from eve_lab.sdwan_factory import _configure_edge
        from eve_lab.sdwan_edge import EdgeStage
        console = Mock()
        console.login.side_effect = login_errors
        console.command.return_value = "Controller-Managed"
        context = SimpleNamespace(root=Path("."), ledger=Mock(),
                                 compiled={"node_operations": {"EDGE": {}}})
        with patch("eve_lab.sdwan_factory.credentials", return_value=("admin", "configured", "enable")), patch(
                "eve_lab.sdwan_factory._eve_console", side_effect=lambda *a, **k: nullcontext(console)), patch(
                "eve_lab.sdwan_factory.stages_from_edge_plan", return_value=(EdgeStage("identity", ("hostname EDGE",)),)), patch(
                "eve_lab.sdwan_factory.missing_desired_commands", return_value=()), patch(
                "eve_lab.sdwan_factory.time.sleep"), patch(
                "eve_lab.sdwan_factory.time.monotonic", side_effect=range(20)):
            _configure_edge(context, "EDGE", edge, 10)
        return console

    def test_boot_timeout_retries_configured_login_without_factory_credentials(self):
        console = self.run_configuration([RuntimeError("boot prompt timeout"), None], {})
        self.assertEqual([c.args for c in console.login.call_args_list],
                         [("admin", "configured", "enable")] * 2)

    def test_explicit_post_mode_rejection_uses_factory_password_once(self):
        from eve_lab.device_console import ConsoleAuthenticationError
        edge = {}
        console = self.run_configuration([ConsoleAuthenticationError("rejected"), None, None], edge)
        self.assertEqual([c.args for c in console.login.call_args_list],
                         [("admin", "configured", "enable"), ("admin", "admin", "enable"),
                          ("admin", "configured", "enable")])
        self.assertEqual(console.login.call_args_list[1].kwargs, {"new_password": "configured"})
        self.assertEqual(edge["post_mode_factory_login_result"], "password-initialized")
        self.assertTrue(edge["baseline_complete"])

    def test_rejection_after_completed_password_initialization_stops(self):
        from eve_lab.device_console import ConsoleAuthenticationError
        edge = {"post_mode_factory_login_attempted": True,
                "post_mode_factory_login_result": "password-initialized"}
        with self.assertRaisesRegex(ConsoleAuthenticationError, "recorded password initialization"):
            self.run_configuration([ConsoleAuthenticationError("rejected")], edge)
        self.assertNotIn("post_mode_factory_login_retry_attempted", edge)

if __name__ == "__main__":
    unittest.main()
