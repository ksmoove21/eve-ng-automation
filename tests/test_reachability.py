"""Focused tests for bounded live reachability retries."""
import unittest
from unittest.mock import Mock, patch

from eve_lab.reachability import retry_ping


class ReachabilityRetryTests(unittest.TestCase):
    def run_probe(self, rates):
        probe = Mock(side_effect=[
            {"success_rate": rate, "received": rate // 20, "sent": 5}
            for rate in rates
        ])
        with patch("eve_lab.reachability.time.sleep") as sleep:
            result = retry_ping(probe)
        return result, probe, sleep

    def test_first_attempt_succeeds(self):
        (passed, best, attempts), probe, sleep = self.run_probe([100])
        self.assertTrue(passed)
        self.assertEqual(best, 100)
        self.assertEqual(len(attempts), 1)
        probe.assert_called_once_with()
        sleep.assert_not_called()

    def test_second_attempt_succeeds(self):
        (passed, best, attempts), probe, sleep = self.run_probe([0, 100])
        self.assertTrue(passed)
        self.assertEqual([a["success_rate"] for a in attempts], [0, 100])
        self.assertEqual(probe.call_count, 2)
        sleep.assert_called_once_with(10)

    def test_third_attempt_succeeds(self):
        (passed, best, attempts), probe, sleep = self.run_probe([0, 80, 100])
        self.assertTrue(passed)
        self.assertEqual([a["success_rate"] for a in attempts], [0, 80, 100])
        self.assertEqual(probe.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual([c.args for c in sleep.call_args_list], [(10,), (10,)])

    def test_all_three_fail_and_preserve_evidence(self):
        (passed, best, attempts), probe, sleep = self.run_probe([0, 20, 80])
        self.assertFalse(passed)
        self.assertEqual(best, 80)
        self.assertEqual([a["success_rate"] for a in attempts], [0, 20, 80])
        self.assertEqual(probe.call_count, 3)
        self.assertEqual([c.args for c in sleep.call_args_list], [(10,), (10,)])

    def test_no_retry_or_sleep_after_threshold_success(self):
        probe = Mock(side_effect=[{"success_rate": 80, "received": 4, "sent": 5}])
        with patch("eve_lab.reachability.time.sleep") as sleep:
            passed, best, attempts = retry_ping(probe, minimum_success_rate=80)
        self.assertTrue(passed)
        self.assertEqual(best, 80)
        self.assertEqual(len(attempts), 1)
        probe.assert_called_once_with()
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
