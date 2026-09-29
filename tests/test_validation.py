import unittest
from unittest.mock import MagicMock, patch

from eve_lab.validation import _checks, _interface_check, _ping_check


class ValidationTests(unittest.TestCase):
    def test_check_schema_accepts_interface_and_ping(self):
        checks = _checks({"validation": [
            {"name": "r1-gi1", "type": "interface", "node": "R1",
             "interface": "GigabitEthernet1", "address": "10.255.0.1", "state": "up"},
            {"name": "r1-r2", "type": "ping", "node": "R1",
             "destination": "10.255.0.2", "min_success_rate": 100},
        ]})
        self.assertEqual(len(checks), 2)

    def test_interface_check_matches_address_and_up_up(self):
        console = MagicMock()
        console.interface_status.return_value = [{
            "interface": "GigabitEthernet1",
            "ip_address": "10.255.0.1",
            "method": "manual",
            "status": "up",
            "protocol": "up",
        }]
        passed, evidence = _interface_check(console, {
            "interface": "Gi1", "address": "10.255.0.1", "state": "up"
        })
        self.assertTrue(passed)
        self.assertEqual(evidence["ip_address"], "10.255.0.1")

    def test_ping_retries_after_arp_loss(self):
        console = MagicMock()
        console.command.side_effect = [
            "Success rate is 80 percent (4/5)",
            "Success rate is 100 percent (5/5)",
        ]
        with patch("eve_lab.reachability.time.sleep") as sleep:
            passed, evidence = _ping_check(console, {
                "destination": "10.255.0.2", "min_success_rate": 100
            })
        self.assertTrue(passed)
        self.assertEqual(evidence["success_rate"], 100)
        self.assertEqual(len(evidence["attempts"]), 2)
        sleep.assert_called_once_with(10)

    def test_ping_failure_is_reported(self):
        console = MagicMock()
        console.command.side_effect = [
            "Success rate is 0 percent (0/5)",
            "Success rate is 0 percent (0/5)",
            "Success rate is 0 percent (0/5)",
        ]
        with patch("eve_lab.reachability.time.sleep") as sleep:
            passed, evidence = _ping_check(console, {
                "destination": "10.255.0.2", "min_success_rate": 100
            })
        self.assertFalse(passed)
        self.assertEqual(evidence["success_rate"], 0)
        self.assertEqual(len(evidence["attempts"]), 3)
        self.assertEqual([call.args for call in sleep.call_args_list], [(10,), (10,)])


if __name__ == "__main__":
    unittest.main()
