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

if __name__ == "__main__":
    unittest.main()
