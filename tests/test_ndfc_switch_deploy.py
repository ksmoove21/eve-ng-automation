"""NDFC config preview can include both members of a vPC pair."""

import unittest
from unittest.mock import patch

from eve_lab.ndfc_switch_deploy import _preview
from eve_lab.nexus_dashboard_browser import NexusDashboardBrowserError


class SwitchPreviewTests(unittest.TestCase):
    def test_selects_exact_serial_from_pair_preview(self):
        response = [
            {"switchId": "peer-b", "status": "Out-of-Sync"},
            {"switchId": "peer-a", "status": "In-Sync"},
        ]
        with patch("eve_lab.ndfc_switch_deploy._api", return_value=(200, response)):
            self.assertEqual(_preview(None, "/fabric", "peer-a")["status"], "In-Sync")

    def test_rejects_missing_serial(self):
        with patch("eve_lab.ndfc_switch_deploy._api", return_value=(200, [{"switchId": "peer-b"}])):
            with self.assertRaises(NexusDashboardBrowserError):
                _preview(None, "/fabric", "peer-a")


if __name__ == "__main__":
    unittest.main()
