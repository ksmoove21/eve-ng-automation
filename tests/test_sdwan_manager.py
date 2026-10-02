"""Desired-state Manager fabric workflow tests."""
import unittest
from unittest.mock import MagicMock

from eve_lab.sdwan_manager import (
    certificate_is_installed, control_component_record,
    ensure_fabric_settings,
)


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

    def test_control_record_requires_exact_ip_and_personality(self):
        api = MagicMock()
        expected = {"deviceIP": "172.16.1.101", "personality": "vmanage"}
        api.inventory.return_value = (
            expected,
            {"deviceIP": "172.16.1.102", "personality": "vbond"},
        )
        self.assertIs(control_component_record(
            api, device_ip="172.16.1.101", personality="vmanage"), expected)

    def test_control_record_uses_device_type_for_20_15_vbond(self):
        api = MagicMock()
        expected = {
            "deviceIP": "10.1.0.2", "deviceType": "vbond",
            "personality": "vedge",
        }
        api.inventory.return_value = (expected,)
        self.assertIs(control_component_record(
            api, device_ip="10.1.0.2", personality="vbond"), expected)

    def test_certificate_acceptance_requires_status_and_real_serial(self):
        self.assertTrue(certificate_is_installed({
            "certInstallStatus": "Installed", "serialNumber": "1234"}))
        self.assertFalse(certificate_is_installed({
            "certInstallStatus": "Installed",
            "serialNumber": "No certificate installed"}))
        self.assertFalse(certificate_is_installed({
            "certInstallStatus": "Pending", "serialNumber": "1234"}))
        self.assertTrue(certificate_is_installed({
            "certInstallStatus": "Installed", "serialNumber": "1234",
            "rootCertHash": "aabb"}, root_hash="AA:BB"))
        self.assertFalse(certificate_is_installed({
            "certInstallStatus": "Installed", "serialNumber": "1234",
            "rootCertHash": "ccdd"}, root_hash="AA:BB"))

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
