"""Manager application readiness behavior."""
import unittest
from unittest.mock import patch

from eve_lab.sdwan_readiness import (
    ApplicationReadiness, parse_application_status,
    wait_for_application_server,
)
from eve_lab.sdwan_initialize import qualify_manager


def cli_status(state="running", enabled=True, pid=42, uptime=899):
    detail = f" PID:{pid} for {uptime}s" if state == "running" else ""
    return ("vManage# request nms application-server status\n"
            "NMS application server\n"
            f"    Enabled: {str(enabled).lower()}\n"
            f"    Status:  {state}{detail}\n"
            "vManage# ")


class ReadinessTests(unittest.TestCase):
    def test_parse_and_qualify_at_900_seconds(self):
        parsed = parse_application_status(cli_status(uptime=7313))
        self.assertTrue(parsed.enabled and parsed.running)
        tracker = ApplicationReadiness()
        self.assertFalse(tracker.observe(cli_status(uptime=899)).qualified)
        self.assertTrue(tracker.observe(cli_status(uptime=900)).qualified)

    def test_pid_and_uptime_regression_reset(self):
        tracker = ApplicationReadiness()
        self.assertTrue(tracker.observe(cli_status(uptime=1000)).qualified)
        self.assertIn("PID changed", tracker.observe(
            cli_status(pid=43, uptime=5)).reason)
        self.assertTrue(tracker.observe(cli_status(pid=43, uptime=920)).qualified)
        self.assertIn("uptime decreased", tracker.observe(
            cli_status(pid=43, uptime=4)).reason)

    def test_nonrunning_malformed_and_timeout_fail_closed(self):
        tracker = ApplicationReadiness()
        self.assertFalse(tracker.observe(cli_status(enabled=False)).qualified)
        with self.assertRaises(ValueError):
            parse_application_status("Status: running PID:1 for 900s")
        now = [0]
        def sleep(seconds):
            now[0] += seconds
        with self.assertRaisesRegex(TimeoutError, "uptime below"):
            wait_for_application_server(
                lambda: cli_status(uptime=100), timeout_seconds=24,
                poll_seconds=12, monotonic=lambda: now[0], sleep=sleep)

    def test_wait_reports_sanitized_status(self):
        now = [0]
        reports = []
        def sleep(seconds):
            now[0] += seconds
        with self.assertRaises(TimeoutError):
            wait_for_application_server(
                lambda: cli_status(uptime=100), timeout_seconds=12,
                poll_seconds=12, monotonic=lambda: now[0], sleep=sleep,
                on_wait=lambda reason, pid, uptime:
                reports.append((reason, pid, uptime)))
        self.assertEqual(
            reports,
            [("application uptime below qualification threshold", 42, 100)])

    def test_manager_qualification_requires_completed_correlated_init(self):
        topology = {"name": "lab", "path": "/sdwan/lab.unl"}
        client = object()
        compiled = {"node_operations": {"MGR": {
            "adapter": "viptela-control", "personality": "manager"}}}
        with (patch("eve_lab.sdwan_initialize.load_topology", return_value={}),
              patch("eve_lab.sdwan_initialize.load_and_compile",
                    return_value=compiled),
              patch("eve_lab.sdwan_initialize.named", return_value={"MGR": {
                  "status": 2, "uuid": "new", "url": "telnet://eve:1"}}),
              patch("eve_lab.sdwan_initialize._read_state", return_value={
                  "version": 1, "nodes": {"MGR": {
                      "eve_uuid": "old", "first_login": "complete",
                      "completed_stages": ["identity", "vpn0", "vpn512"]}}})):
            with self.assertRaisesRegex(RuntimeError, "correlation is incomplete"):
                qualify_manager(client, topology, ".", "default", "MGR")


if __name__ == "__main__":
    unittest.main()
