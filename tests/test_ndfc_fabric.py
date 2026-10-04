"""Focused mapping checks for the live NDFC Easy_Fabric API contract."""

from copy import deepcopy
import unittest

from eve_lab.ndfc_fabric import _guarded_fabric_update, compile_fabric
from eve_lab.nexus_dashboard_browser import NexusDashboardBrowserError


INTENT = {
    "ndfc_fabrics": [{
        "name": "DC1-VXLAN-EVPN", "site": "DC1",
        "mode": "Data Center VXLAN EVPN", "bgp_asn": 65001,
        "replication": "ingress", "multicast_replication": "disabled",
        "infrastructure_pools": {
            "underlay_links": "10.240.100.0/24",
            "loopbacks": "10.240.101.0/24",
            "vpc_peer_keepalive": "10.240.102.0/24",
            "anycast_vtep": "10.240.103.0/24",
        },
        "switch_import": {"greenfield": True, "preserve_config": False},
        "network_vlan_range": "100-199",
        "vpc_peer_keepalive_option": "management",
        "leaf_pre_interfaces_freeform": "feature dhcp\nservice dhcp",
    }],
    "tenants": {
        "vni_policy": {"l2_range": "20000-29999", "l3_range": "30000-39999"},
        "dc1": [{"vrf_vni": 30010, "networks": [{"vni": 20010, "vlan": 110}]}],
    },
}


class NdfcFabricTests(unittest.TestCase):
    def test_compiles_declared_pools_and_owner_vni_ranges(self):
        name, nv = compile_fabric(INTENT)
        self.assertEqual(name, "DC1-VXLAN-EVPN")
        self.assertEqual(nv["REPLICATION_MODE"], "Ingress")
        self.assertEqual(nv["SUBNET_RANGE"], "10.240.100.0/24")
        self.assertEqual(nv["LOOPBACK0_IP_RANGE"], "10.240.101.0/24")
        self.assertEqual(nv["LOOPBACK1_IP_RANGE"], "10.240.103.0/24")
        self.assertEqual(nv["L2_SEGMENT_ID_RANGE"], "20000-29999")
        self.assertEqual(nv["L3_PARTITION_ID_RANGE"], "30000-39999")
        self.assertEqual(nv["preInterfaceConfigLeaf"], "feature dhcp\nservice dhcp")
        self.assertNotIn("VRF_VLAN_RANGE", nv)

    def test_static_dc2_disables_fabric_dhcp_and_allows_only_guarded_update(self):
        intent = deepcopy(INTENT)
        fabric = intent["ndfc_fabrics"][0]
        fabric.update(site="DC2", name="SECOND-FABRIC", bgp_asn=65002,
                      network_vlan_range="200-299", vrf_vlan_range="300-399",
                      leaf_pre_interfaces_freeform="", tenant_dhcp_service="disabled_static")
        intent["tenants"]["dc2"] = [{"vrf_vni": 30110, "vrf_vlan": 330,
                                       "networks": [{"vni": 20110, "vlan": 210}]}]
        _, desired = compile_fabric(intent, "DC2")
        self.assertEqual(desired["ENABLE_TENANT_DHCP"], "false")
        self.assertEqual(desired["preInterfaceConfigLeaf"], "")
        actual = dict(desired, ENABLE_TENANT_DHCP="true",
                      preInterfaceConfigLeaf="feature dhcp\nservice dhcp")
        self.assertEqual(_guarded_fabric_update("DC2", actual, desired), {
            "ENABLE_TENANT_DHCP": "false", "preInterfaceConfigLeaf": ""})
        actual["BGP_AS"] = "65003"
        with self.assertRaises(NexusDashboardBrowserError):
            _guarded_fabric_update("DC2", actual, desired)
        fabric["leaf_pre_interfaces_freeform"] = "feature dhcp"
        with self.assertRaisesRegex(ValueError, "cannot add leaf DHCP"):
            compile_fabric(intent, "DC2")

    def test_rejects_tenant_vni_outside_owner_range(self):
        intent = deepcopy(INTENT)
        intent["tenants"]["dc1"][0]["networks"][0]["vni"] = 30010
        with self.assertRaisesRegex(ValueError, "network VNI"):
            compile_fabric(intent)


if __name__ == "__main__":
    unittest.main()
