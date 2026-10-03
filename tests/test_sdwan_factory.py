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


if __name__ == "__main__":
    unittest.main()
