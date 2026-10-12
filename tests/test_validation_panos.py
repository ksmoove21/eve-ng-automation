import unittest
from unittest.mock import MagicMock

from eve_lab.validation_panos import (
    evaluate,
    evaluate_operational,
    parse_running_config,
    validate_check,
)


SAMPLE = """<config version="12.1.0">
  <devices>
    <entry name="localhost.localdomain">
      <network>
        <interface>
          <ethernet>
            <entry name="ethernet1/1">
              <layer3>
                <ip>
                  <entry name="198.51.100.1/30"/>
                </ip>
              </layer3>
            </entry>
            <entry name="ethernet1/2">
              <layer3>
                <ip>
                  <entry name="203.0.113.1/30"/>
                </ip>
              </layer3>
            </entry>
          </ethernet>
        </interface>
        <virtual-router>
          <entry name="default">
            <interface>
              <member>ethernet1/1</member>
              <member>ethernet1/2</member>
            </interface>
            <routing-table>
              <ip>
                <static-route>
                  <entry name="DEFAULT">
                    <destination>0.0.0.0/0</destination>
                    <nexthop>
                      <ip-address>198.51.100.2</ip-address>
                    </nexthop>
                  </entry>
                </static-route>
              </ip>
            </routing-table>
          </entry>
        </virtual-router>
      </network>
      <vsys>
        <entry name="vsys1">
          <zone>
            <entry name="OUTSIDE">
              <network>
                <layer3>
                  <member>ethernet1/1</member>
                </layer3>
              </network>
            </entry>
            <entry name="INSIDE">
              <network>
                <layer3>
                  <member>ethernet1/2</member>
                </layer3>
              </network>
            </entry>
          </zone>
          <rulebase>
            <security>
              <rules>
                <entry name="ALLOW-TEST"/>
              </rules>
            </security>
            <nat>
              <rules>
                <entry name="TEST-NAT"/>
              </rules>
            </nat>
          </rulebase>
        </entry>
      </vsys>
    </entry>
  </devices>
</config>"""


class PanosValidationTests(unittest.TestCase):
    def setUp(self):
        self.root = parse_running_config(SAMPLE)

    def check(self, check, expected=True):
        passed, evidence = evaluate(self.root, {"name": "x", "node": "pa", **check})
        self.assertEqual(passed, expected)
        self.assertIsInstance(evidence, dict)
        return evidence

    def test_interface_address(self):
        evidence = self.check({
            "type": "panos-interface",
            "interface": "ethernet1/1",
            "address": "198.51.100.1/30",
            "expected": "present",
        })
        self.assertEqual(evidence["addresses"], ["198.51.100.1/30"])
        self.check({
            "type": "panos-interface",
            "interface": "ethernet1/3",
            "expected": "absent",
        })

    def test_zone_and_virtual_router_membership(self):
        self.check({
            "type": "panos-zone-interface",
            "zone": "OUTSIDE",
            "interface": "ethernet1/1",
            "expected": "present",
        })
        self.check({
            "type": "panos-virtual-router-interface",
            "virtual_router": "default",
            "interface": "ethernet1/2",
            "expected": "present",
        })
        self.check({
            "type": "panos-zone-interface",
            "zone": "OUTSIDE",
            "interface": "ethernet1/2",
            "expected": "absent",
        })

    def test_static_route(self):
        evidence = self.check({
            "type": "panos-route",
            "virtual_router": "default",
            "destination": "0.0.0.0/0",
            "next_hop": "198.51.100.2",
            "expected": "present",
        })
        self.assertEqual(evidence["observed"][0]["name"], "DEFAULT")
        self.check({
            "type": "panos-route",
            "virtual_router": "default",
            "destination": "192.0.2.0/24",
            "expected": "absent",
        })

    def test_security_and_nat_rule_presence(self):
        self.check({
            "type": "panos-security-rule",
            "rule": "ALLOW-TEST",
            "expected": "present",
        })
        self.check({
            "type": "panos-nat-rule",
            "rule": "TEST-NAT",
            "expected": "present",
        })
        self.check({
            "type": "panos-security-rule",
            "rule": "DOES-NOT-EXIST",
            "expected": "absent",
        })

    def test_invalid_intent_fails_closed(self):
        bad = [
            {"type": "panos-interface", "interface": "ethernet1/1;delete", "expected": "present"},
            {"type": "panos-interface", "interface": "ethernet1/1'][@name='evil", "expected": "present"},
            {"type": "panos-route", "destination": "192.0.2.1/24", "expected": "present"},
            {"type": "panos-route", "destination": "0.0.0.0/0", "expected": "absent", "next_hop": "192.0.2.1"},
            {"type": "panos-security-rule", "rule": "ALLOW TEST", "expected": "present"},
        ]
        for check in bad:
            with self.subTest(check=check), self.assertRaises((ValueError, TypeError)):
                validate_check({"name": "x", "node": "pa", **check})

    def test_invalid_xml_is_rejected(self):
        for text in ("", "<config/>", "<config><devices>"):
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                parse_running_config(text)



class PanosReadinessTests(unittest.TestCase):
    def readiness(self, jobs, chassis="yes"):
        console = MagicMock()
        console.command.side_effect = [chassis, jobs]
        return evaluate_operational(console, {"type": "panos-readiness"})

    def test_latest_finished_commit_controls_historical_failures_by_job_id(self):
        passed, evidence = self.readiness(
            "12 Commit FIN FAIL\n13 Commit FIN OK")
        self.assertTrue(passed)
        self.assertEqual(evidence["latest_finished_commit"], {
            "id": 13, "status": "FIN", "result": "OK"})
        self.assertFalse(evidence["unfinished_or_failed_commit"])

        passed, evidence = self.readiness(
            "2026/10/12 10:00:00 2026/10/12 10:00:01 14 Commit FIN OK 2026/10/12 10:00:02")
        self.assertTrue(passed)
        self.assertEqual(evidence["latest_finished_commit"]["id"], 14)

        passed, evidence = self.readiness(
            "13 Commit FIN OK\n12 Commit FIN FAIL")
        self.assertTrue(passed)
        self.assertEqual(evidence["latest_finished_commit"]["id"], 13)

    def test_active_newer_or_failed_latest_commit_blocks_readiness(self):
        for jobs in (
                "12 Commit FIN OK\n13 Commit ACT PEND",
                "12 Commit FIN OK\n13 Commit FIN FAIL"):
            with self.subTest(jobs=jobs):
                passed, evidence = self.readiness(jobs)
                self.assertFalse(passed)
                self.assertTrue(evidence["unfinished_or_failed_commit"])

    def test_readiness_fails_closed_without_finished_commit_or_with_malformed_row(self):
        for jobs in ("", "12 Commit ACT PEND", "12 Commit FIN"):
            with self.subTest(jobs=jobs):
                passed, evidence = self.readiness(jobs)
                self.assertFalse(passed)
                self.assertFalse(evidence["successful_commit"])
        passed, evidence = self.readiness("12 Commit FIN")
        self.assertEqual(evidence["malformed_commit_rows"], ["12 Commit FIN"])

    def test_chassis_not_ready_blocks_a_successful_latest_commit(self):
        passed, evidence = self.readiness("12 Commit FIN OK", chassis="no")
        self.assertFalse(passed)
        self.assertFalse(evidence["chassis_ready"])
if __name__ == "__main__":
    unittest.main()
