"""Selected-node start preflight and lifecycle behavior."""

import unittest
from unittest.mock import patch

from eve_lab.selected_start import start_selected
from tests.test_deploy import FakeEve


class SelectedStartTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeEve()
        self.client.nodes = {
            "1": {"id": 1, "name": "ND-01", "status": 0},
            "2": {"id": 2, "name": "DC1-SPINE-01", "status": 0},
            "3": {"id": 3, "name": "DC2-SPINE-01", "status": 0},
        }
        self.topology = {"name": "palo-lab", "remote_folder": "/"}
        self.sleeper = patch("eve_lab.deploy.time.sleep")
        self.sleeper.start()
        self.addCleanup(self.sleeper.stop)

    def test_selected_nodes_start_and_unselected_site_stays_stopped(self):
        names = ["ND-01", "DC1-SPINE-01"]
        result = start_selected(self.client, self.topology, names)
        self.assertEqual(result["changed_nodes"], names)
        self.assertEqual([self.client.nodes[str(i)]["status"] for i in (1, 2, 3)], [2, 2, 0])
        self.assertEqual(start_selected(self.client, self.topology, names)["changed_nodes"], [])
        starts = [path for _, path, _ in self.client.writes if path.endswith("/start")]
        self.assertEqual(len(starts), 2)

    def test_missing_name_rejects_entire_set_before_start(self):
        with self.assertRaisesRegex(RuntimeError, "Missing nodes"):
            start_selected(self.client, self.topology, ["ND-01", "MISSING"])
        self.assertEqual(self.client.writes, [])

    def test_duplicate_name_rejects_entire_set_before_start(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            start_selected(self.client, self.topology, ["ND-01", "ND-01"])
        self.assertEqual(self.client.writes, [])

    def test_transitional_status_rejects_entire_set_before_start(self):
        self.client.nodes["2"]["status"] = 1
        with self.assertRaisesRegex(RuntimeError, "not stopped or running"):
            start_selected(self.client, self.topology, ["ND-01", "DC1-SPINE-01"])
        self.assertEqual(self.client.writes, [])

    def test_duplicate_remote_name_rejects_entire_set_before_start(self):
        self.client.nodes["3"]["name"] = "ND-01"
        with self.assertRaisesRegex(RuntimeError, "Duplicate remote name"):
            start_selected(self.client, self.topology, ["ND-01"])
        self.assertEqual(self.client.writes, [])


if __name__ == "__main__":
    unittest.main()
