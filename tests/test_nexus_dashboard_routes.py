"""Focused validation for declared Nexus Dashboard management routes."""

import unittest

from eve_lab.nexus_dashboard_routes import (
    declared_management_routes, ensure_management_routes,
)


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


class ManagementRouteReadbackTests(unittest.TestCase):
    def test_existing_route_uses_documented_api_without_ui(self):
        class Page:
            def evaluate(self, script):
                self.script = script
                return {"status": 200, "body": {"items": [{"spec": {
                    "destination": "172.19.3.0/24", "targetNetwork": "Management"}}]}}
        page = Page()
        result = ensure_management_routes(page, {"nexus_dashboard": {
            "management_network_routes": ["172.19.3.0/24"]}}, 1)
        self.assertEqual(result["status"], "already-configured")
        self.assertIn("/nexus/infra/api/platform/v1/routes", page.script)
