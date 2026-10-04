"""NDFC config preview can include both members of a vPC pair."""

import unittest
from unittest.mock import patch

from eve_lab.ndfc_switch_deploy import (
    _deployer_history, _preview, _raise_new_deployment_failure,
)
from eve_lab.nexus_dashboard_browser import NexusDashboardBrowserError


class SwitchPreviewTests(unittest.TestCase):
    def test_selects_exact_serial_from_pair_preview(self):
        response = [
            {"switchId": "peer-b", "status": "Out-of-Sync"},
            {"switchId": "peer-a", "status": "In-Sync"},
        ]
        with patch("eve_lab.ndfc_switch_deploy._api", return_value=(200, response)) as api:
            self.assertEqual(_preview(None, "/fabric", "peer-a")["status"], "In-Sync")
            api.assert_called_once_with(
                None, "GET", "/fabric/config-preview/peer-a?forceShowRun=true")

    def test_rejects_missing_serial(self):
        with patch("eve_lab.ndfc_switch_deploy._api", return_value=(200, [{"switchId": "peer-b"}])):
            with self.assertRaises(NexusDashboardBrowserError):
                _preview(None, "/fabric", "peer-a")


class DeployerHistoryTests(unittest.TestCase):
    def test_filters_exact_user_and_serial(self):
        response = [
            {"serialnumber": "peer-a", "user": "runner", "submittedTime": "2"},
            {"serialnumber": "peer-b", "user": "runner", "submittedTime": "3"},
            {"serialnumber": "peer-a", "user": "admin", "submittedTime": "4"},
        ]
        with patch("eve_lab.ndfc_switch_deploy._api", return_value=(200, response)) as api:
            rows = _deployer_history(None, "fabric", "peer-a", "runner")
        self.assertEqual(rows, response[:1])
        self.assertIn("serial-number=peer-a", api.call_args.args[2])
        self.assertIn("filter=user==runner", api.call_args.args[2])

    def test_rejects_new_missing_lan_credential(self):
        history = [
            {"submittedTime": "2026-10-03 18:00:00", "status": "FAILED",
             "statusDescription": "old failure"},
            {"submittedTime": "2026-10-03 19:00:00", "status": "NOT_EXECUTED",
             "statusDescription": "LAN credential not found for dcnmuser runner"},
        ]
        with self.assertRaisesRegex(NexusDashboardBrowserError, "LAN credential not found"):
            _raise_new_deployment_failure(history, "2026-10-03 18:30:00", "ToR2")
        _raise_new_deployment_failure(history[:1], "2026-10-03 18:30:00", "ToR2")

    def test_rejects_unreadable_history(self):
        with patch("eve_lab.ndfc_switch_deploy._api", return_value=(500, {})):
            with self.assertRaisesRegex(NexusDashboardBrowserError, "history failed"):
                _deployer_history(None, "fabric", "peer-a", "runner")


if __name__ == "__main__":
    unittest.main()
