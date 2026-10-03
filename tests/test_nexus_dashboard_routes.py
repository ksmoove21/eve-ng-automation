"""Focused validation for declared Nexus Dashboard management routes."""

import unittest

from eve_lab.nexus_dashboard_routes import declared_management_routes


class ManagementRouteIntentTests(unittest.TestCase):
    def test_canonicalizes_and_deduplicates(self):
        intent = {"nexus_dashboard": {"management_network_routes": [
            "172.19.3.0/24", "172.19.3.0/24"]}}
        self.assertEqual(declared_management_routes(intent), ["172.19.3.0/24"])

    def test_rejects_host_address_and_wrong_shape(self):
        with self.assertRaises(ValueError):
            declared_management_routes({"nexus_dashboard": {
                "management_network_routes": ["172.19.3.42/24"]}})
        with self.assertRaises(ValueError):
            declared_management_routes({"nexus_dashboard": {
                "management_network_routes": "172.19.3.0/24"}})
