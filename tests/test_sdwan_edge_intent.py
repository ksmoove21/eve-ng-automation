import unittest
from copy import deepcopy

from eve_lab.sdwan_edge import EdgeStage
from eve_lab.sdwan_edge_intent import compile_edge_intent, compile_edge_stages


def direct(name, left_node, left_interface, right_node, right_interface):
    return {"name": name, "from": {"node": left_node, "interface": left_interface},
            "to": {"node": right_node, "interface": right_interface}}


def topology():
    return {"nodes": [
        {"name": "EDGE-ONE", "template": "c8000v", "image": "c8000v-17.15.01a"},
        {"name": "EDGE-TWO", "template": "c8000v", "image": "c8000v-17.15.01a"},
        {"name": "INET-A", "template": "vios", "image": "iosv"},
        {"name": "MPLS-A", "template": "vios", "image": "iosv"},
        {"name": "LAN-A", "template": "viosl2", "image": "iosv-l2"},
    ], "links": [
        direct("inet", "EDGE-ONE", "Gi1", "INET-A", "Gi0/0"),
        direct("mpls", "EDGE-ONE", "Gi2", "MPLS-A", "Gi0/0"),
        direct("lan", "EDGE-ONE", "Gi3", "LAN-A", "Gi0/1"),
        direct("two", "EDGE-TWO", "Gi1", "INET-A", "Gi0/1"),
    ]}


def intent():
    return {"version": 1, "organization_name": "example-org",
            "vbond_address": "198.51.100.10",
            "controller_transport_prefix": "198.51.100.0/24",
            "edges": [
                {"name": "EDGE-ONE", "hostname": "edge-one", "system_ip": "10.255.0.1",
                 "site_id": 10, "transports": [
                    {"interface": "Gi1", "address": "192.0.2.2/30", "gateway": "192.0.2.1",
                     "color": "biz-internet", "distance": 1,
                     "peer": {"node": "INET-A", "interface": "Gi0/0"}},
                    {"interface": "Gi2", "address": "203.0.113.2/30", "gateway": "203.0.113.1",
                     "color": "mpls", "distance": 2,
                     "peer": {"node": "MPLS-A", "interface": "Gi0/0"}},
                 ], "service_interfaces": [
                    {"vpn": 10, "interface": "Gi3", "address": "10.10.0.1/24",
                     "peer": {"node": "LAN-A", "interface": "Gi0/1"}},
                 ]},
                {"name": "EDGE-TWO", "hostname": "edge-two", "system_ip": "10.255.0.2",
                 "site_id": 10, "transports": [
                    {"interface": "Gi1", "address": "192.0.2.6/30", "gateway": "192.0.2.5",
                     "color": "private1", "peer": {"node": "INET-A", "interface": "Gi0/1"}},
                 ]},
            ]}


class EdgeIntentTests(unittest.TestCase):
    def test_compiles_direct_transports_aliases_routes_and_service(self):
        result = compile_edge_intent(intent(), topology())
        first = result["edges"]["EDGE-ONE"]
        transport = first["operations"][1]["commands"]
        self.assertIn("interface GigabitEthernet1", transport)
        self.assertIn("interface GigabitEthernet2", transport)
        self.assertIn("ip route 0.0.0.0 0.0.0.0 192.0.2.1", transport)
        self.assertIn("ip route 198.51.100.0 255.255.255.0 203.0.113.1 2", transport)
        second = result["edges"]["EDGE-TWO"]["operations"][1]["commands"]
        self.assertIn("ip route 0.0.0.0 0.0.0.0 192.0.2.5", second)
        service = first["operations"][2]
        self.assertEqual(service["mode"], "config-transaction")
        self.assertIn("vrf definition 10", service["commands"])
        self.assertTrue(all(isinstance(x, EdgeStage)
                            for x in compile_edge_stages(intent(), topology())["EDGE-ONE"]))

    def test_omits_service_stage_when_no_service_is_declared(self):
        result = compile_edge_intent(intent(), topology())
        self.assertEqual([item["name"] for item in result["edges"]["EDGE-TWO"]["operations"]],
                         ["identity", "transport"])
        self.assertEqual([item.name for item in compile_edge_stages(intent(), topology())["EDGE-TWO"]],
                         ["identity", "transport"])

    def test_normalizes_singular_transport_and_rejects_ambiguity(self):
        single = intent()
        single["edges"][1]["transport"] = single["edges"][1].pop("transports")[0]
        self.assertIn("color private1",
                      compile_edge_intent(single, topology())["edges"]["EDGE-TWO"]["operations"][1]["commands"])
        ambiguous = intent()
        ambiguous["edges"][1]["transport"] = deepcopy(ambiguous["edges"][1]["transports"][0])
        with self.assertRaisesRegex(ValueError, "both transport"):
            compile_edge_intent(ambiguous, topology())

    def test_rejects_identity_org_gateway_and_color_gaps(self):
        for field, value in (("token", "x"), ("chassis_number", "x"), ("otp", "x")):
            candidate = intent()
            candidate["edges"][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "runtime secret"):
                compile_edge_intent(candidate, topology())
        bad_org = intent()
        bad_org["organization_name"] = 'bad"org'
        with self.assertRaisesRegex(ValueError, "organization_name"):
            compile_edge_intent(bad_org, topology())
        bad_gateway = intent()
        bad_gateway["edges"][0]["transports"][0]["gateway"] = "192.0.2.3"
        with self.assertRaisesRegex(ValueError, "usable peer"):
            compile_edge_intent(bad_gateway, topology())
        duplicate_color = intent()
        duplicate_color["edges"][0]["transports"][1]["color"] = "biz-internet"
        with self.assertRaisesRegex(ValueError, "colors"):
            compile_edge_intent(duplicate_color, topology())
        duplicate_transport_address = intent()
        duplicate_transport_address["edges"][1]["transports"][0]["address"] = "192.0.2.2/30"
        with self.assertRaisesRegex(ValueError, "addresses"):
            compile_edge_intent(duplicate_transport_address, topology())

        duplicate_hostname = intent()
        duplicate_hostname["edges"][1]["hostname"] = "edge-one"
        with self.assertRaisesRegex(ValueError, "hostnames"):
            compile_edge_intent(duplicate_hostname, topology())
        duplicate_system = intent()
        duplicate_system["edges"][1]["system_ip"] = "10.255.0.1"
        with self.assertRaisesRegex(ValueError, "system_ip"):
            compile_edge_intent(duplicate_system, topology())

    def test_aliases_cannot_configure_one_native_port_twice(self):
        candidate = intent()
        candidate["edges"][0]["transports"][1]["interface"] = "GigabitEthernet1"
        topo = topology()
        for link in topo["links"]:
            if link["from"].get("interface") == "Gi2":
                link["from"]["interface"] = "GigabitEthernet1"
        with self.assertRaisesRegex(ValueError, "interfaces"):
            compile_edge_intent(candidate, topo)

    def test_rejects_invalid_topology_binding(self):
        bad_image = topology()
        bad_image["nodes"][0]["image"] = "other"
        with self.assertRaisesRegex(ValueError, "c8000v-17.15.01a"):
            compile_edge_intent(intent(), bad_image)
        shared = topology()
        shared["links"].append({"node": "EDGE-ONE", "interface": "Gi1", "network": "Cloud0"})
        with self.assertRaisesRegex(ValueError, "shared network"):
            compile_edge_intent(intent(), shared)
        duplicate_endpoint = topology()
        duplicate_endpoint["links"].append(
            direct("duplicate", "EDGE-ONE", "Gi1", "INET-A", "Gi0/9"))
        with self.assertRaisesRegex(ValueError, "one direct link"):
            compile_edge_intent(intent(), duplicate_endpoint)
        duplicate_node = topology()
        duplicate_node["nodes"].append(deepcopy(duplicate_node["nodes"][0]))
        with self.assertRaisesRegex(ValueError, "node names"):
            compile_edge_intent(intent(), duplicate_node)
        unknown_peer = intent()
        unknown_peer["edges"][0]["transports"][0]["peer"]["node"] = "MISSING"
        with self.assertRaisesRegex(ValueError, "not declared"):
            compile_edge_intent(unknown_peer, topology())
        unsupported = intent()
        unsupported["edges"][0]["transports"][0]["interface"] = "Gi0/1"
        with self.assertRaisesRegex(ValueError, "GiN"):
            compile_edge_intent(unsupported, topology())


if __name__ == "__main__":
    unittest.main()
