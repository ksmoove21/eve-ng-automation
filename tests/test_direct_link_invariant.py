"""Regression tests for the repository-wide direct-link topology invariant."""

import unittest

from eve_lab.topology import expand_links, validate


class DirectLinkInvariantTests(unittest.TestCase):
    def topology(self):
        return {
            "name": "direct-links",
            "remote_folder": "/",
            "nodes": [
                {"name": "A", "template": "iol", "type": "iol", "image": "iol.bin"},
                {"name": "B", "template": "iol", "type": "iol", "image": "iol.bin"},
                {"name": "C", "template": "iol", "type": "iol", "image": "iol.bin"},
            ],
            "networks": [],
            "links": [
                {
                    "name": "A-B",
                    "from": {"node": "A", "interface": "Ethernet0/0"},
                    "to": {"node": "B", "interface": "Ethernet0/0"},
                },
                {
                    "name": "B-C",
                    "from": {"node": "B", "interface": "Ethernet0/1"},
                    "to": {"node": "C", "interface": "Ethernet0/0"},
                },
            ],
        }

    def test_each_direct_cable_gets_exclusive_two_endpoint_backing_network(self):
        topology = self.topology()
        expanded, direct = expand_links(topology)

        self.assertEqual([item["name"] for item in expanded["networks"]], ["A-B", "B-C"])
        self.assertEqual(len(direct), 2)

        for name, attachments in direct:
            self.assertEqual(len(attachments), 2)
            self.assertEqual(
                [link for link in expanded["links"] if link["network"] == name],
                attachments,
            )

        self.assertNotEqual(
            {item["node"] for item in direct[0][1]},
            {item["node"] for item in direct[1][1]},
        )
        validate(topology)

    def test_explicit_shared_network_remains_distinct_from_direct_cables(self):
        topology = self.topology()
        topology["networks"].append({"name": "CLOUD0", "type": "pnet0"})
        topology["links"].append(
            {"node": "A", "interface": "Ethernet0/2", "network": "CLOUD0"}
        )

        expanded, direct = expand_links(topology)

        self.assertEqual(
            [item["name"] for item in expanded["networks"]],
            ["CLOUD0", "A-B", "B-C"],
        )
        self.assertEqual(len(direct), 2)
        self.assertEqual(
            [link for link in expanded["links"] if link.get("network") == "CLOUD0"],
            [{"node": "A", "interface": "Ethernet0/2", "network": "CLOUD0"}],
        )
        validate(topology)


if __name__ == "__main__":
    unittest.main()
