import unittest
from eve_lab.sdwan_bfd import EdgeTransport, evaluate_bfd, expected_paths, parse_bfd_sessions

class BfdIntentTests(unittest.TestCase):
    def setUp(self):
        self.local = EdgeTransport("192.0.2.1", 1, ("mpls", "biz-internet"))
        remote = EdgeTransport("192.0.2.2", 2, ("mpls", "biz-internet"))
        same_site = EdgeTransport("192.0.2.3", 1, ("mpls",))
        self.required, self.isolated = expected_paths(self.local,
            [self.local, remote, same_site],
            {("mpls", "mpls"), ("biz-internet", "biz-internet")})

    def test_separate_underlays(self):
        observed = {path: "up" for path in self.required}
        observed.update({path: "down" for path in self.isolated})
        self.assertEqual(len(self.required), 2)
        self.assertEqual(len(self.isolated), 2)
        self.assertTrue(evaluate_bfd(observed, self.required, self.isolated)["passed"])

    def test_missing_extension_fails(self):
        result = evaluate_bfd({("192.0.2.2", "mpls", "mpls"): "up"},
                              self.required, self.isolated)
        self.assertFalse(result["passed"])
        self.assertEqual(result["required_issues"],
            [("192.0.2.2", "biz-internet", "biz-internet", "missing")])

    def test_isolation_and_unknown_paths_fail(self):
        observed = {path: "up" for path in self.required | self.isolated}
        observed[("192.0.2.99", "mpls", "mpls")] = "up"
        result = evaluate_bfd(observed, self.required, self.isolated)
        self.assertFalse(result["passed"])
        self.assertEqual(len(result["isolation_violations"]), 2)
        self.assertEqual(len(result["unexpected_paths"]), 1)

    def test_down_required_and_absent_isolated(self):
        observed = {path: "up" for path in self.required}
        self.assertTrue(evaluate_bfd(observed, self.required, self.isolated)["passed"])
        observed[next(iter(self.required))] = "down"
        self.assertFalse(evaluate_bfd(observed, self.required, self.isolated)["passed"])

    def test_invalid_intent_rejected(self):
        with self.assertRaises(ValueError):
            EdgeTransport("192.0.2.1", 1, ("mpls", "mpls"))
        with self.assertRaises(ValueError):
            expected_paths(self.local, [self.local, self.local], set())
        with self.assertRaises(ValueError):
            evaluate_bfd({}, self.required, self.required)

    def test_parser(self):
        row = "192.0.2.2 2 up mpls mpls 198.51.100.1 198.51.100.2 12346 ipsec"
        self.assertEqual(parse_bfd_sessions("SYSTEM IP STATE\n" + row),
                         {("192.0.2.2", "mpls", "mpls"): "up"})
        with self.assertRaises(ValueError):
            parse_bfd_sessions(row + "\n" + row.replace(" up ", " down "))

if __name__ == "__main__":
    unittest.main()
