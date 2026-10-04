"""Generic NDFC switch-intent compilation checks."""

from copy import deepcopy
import unittest

from eve_lab.ndfc_switches import compile_switches


def _intent():
    names = [
        "spine-a", "spine-b",
        "leaf-a", "leaf-b",
        "border-a", "border-b",
        "tor-a", "tor-b",
    ]
    assignments = {
        name: f"192.0.2.{index}/24"
        for index, name in enumerate(names, start=10)
    }
    return {
        "scope": {"activation_set": names},
        "management": {
            "fabric_edge": {"assignments": assignments},
            "nd": {"address": "192.0.2.2/24"},
        },
        "ndfc_fabrics": [{
            "name": "SITE-A-FABRIC",
            "site": "DC1",
            "mode": "Data Center VXLAN EVPN",
            "bgp_asn": 65001,
            "replication": "ingress",
            "multicast_replication": "disabled",
            "infrastructure_pools": {
                "underlay_links": "198.51.100.0/24",
                "loopbacks": "198.51.101.0/24",
                "vpc_peer_keepalive": "198.51.102.0/24",
                "anycast_vtep": "198.51.103.0/24",
            },
            "switch_import": {"greenfield": True, "preserve_config": False},
            "network_vlan_range": "100-199",
            "vpc_peer_keepalive_option": "management",
            "leaf_pre_interfaces_freeform": "feature dhcp\nservice dhcp",
            "spine_pair": {"nodes": ["spine-a", "spine-b"]},
            "regular_leaf_pair": {"nodes": ["leaf-a", "leaf-b"]},
            "border_leaf_pair": {"nodes": ["border-a", "border-b"]},
            "tor_pair": {"nodes": ["tor-a", "tor-b"]},
        }],
        "tenants": {
            "vni_policy": {
                "l2_range": "20000-29999",
                "l3_range": "30000-39999",
            },
            "dc1": [{
                "vrf_vni": 30010,
                "networks": [{"vni": 20010, "vlan": 110}],
            }],
        },
    }


class NdfcSwitchTests(unittest.TestCase):
    def test_compiles_generic_declared_switch_names(self):
        name, switches = compile_switches(_intent())
        self.assertEqual(name, "SITE-A-FABRIC")
        self.assertEqual(
            [(item["name"], item["role"]) for item in switches],
            [
                ("spine-a", "spine"),
                ("spine-b", "spine"),
                ("leaf-a", "leaf"),
                ("leaf-b", "leaf"),
                ("border-a", "border"),
                ("border-b", "border"),
                ("tor-a", "tor"),
                ("tor-b", "tor"),
            ],
        )

    def test_requires_explicit_spine_pair(self):
        intent = deepcopy(_intent())
        del intent["ndfc_fabrics"][0]["spine_pair"]
        with self.assertRaisesRegex(ValueError, "explicit spine_pair.nodes"):
            compile_switches(intent)


if __name__ == "__main__":
    unittest.main()
