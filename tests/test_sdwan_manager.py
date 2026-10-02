"""Desired-state Manager fabric workflow tests."""
import unittest
from unittest.mock import MagicMock

from eve_lab.sdwan_manager import ensure_fabric_settings


ROOT = "-----BEGIN CERTIFICATE-----\nQUJD\n-----END CERTIFICATE-----\n"


class ManagerFabricTests(unittest.TestCase):
    def test_missing_settings_are_applied_and_read_back_in_order(self):
        api = MagicMock()
        api.setting.side_effect = [
            {}, {"org": "nwl-lab-sdwan"},
            {}, {"domainIp": "10.1.0.2", "port": "12346"},
            {"certificateSigning": "cisco"},
            {"certificateSigning": "enterprise"},
            {}, {"enterpriseRootCA": ROOT},
        ]
        result = ensure_fabric_settings(
            api, organization="nwl-lab-sdwan", vbond="10.1.0.2",
            root_certificate=ROOT)
        self.assertEqual(result["changed"], [
            "organization", "validator", "certificate-mode",
            "enterprise-root"])
        api.set_organization.assert_called_once_with("nwl-lab-sdwan")
        api.set_vbond.assert_called_once_with("10.1.0.2", 12346)
        api.set_enterprise_certificate_mode.assert_called_once_with()
        api.set_enterprise_root.assert_called_once_with(ROOT)

    def test_matching_settings_are_idempotent(self):
        api = MagicMock()
        api.setting.side_effect = [
            {"org": "nwl-lab-sdwan"},
            {"domainIp": "10.1.0.2", "port": "12346"},
            {"certificateSigning": "enterprise"},
            {"enterpriseRootCA": ROOT},
        ]
        result = ensure_fabric_settings(
            api, organization="nwl-lab-sdwan", vbond="10.1.0.2",
            root_certificate=ROOT)
        self.assertEqual(result["changed"], [])
        api.set_organization.assert_not_called()
        api.set_vbond.assert_not_called()
        api.set_enterprise_certificate_mode.assert_not_called()
        api.set_enterprise_root.assert_not_called()

    def test_conflicting_existing_setting_fails_before_mutation(self):
        api = MagicMock()
        api.setting.return_value = {"org": "other"}
        with self.assertRaisesRegex(RuntimeError, "organization differs"):
            ensure_fabric_settings(
                api, organization="nwl-lab-sdwan", vbond="10.1.0.2",
                root_certificate=ROOT)
        api.set_organization.assert_not_called()


if __name__ == "__main__":
    unittest.main()
