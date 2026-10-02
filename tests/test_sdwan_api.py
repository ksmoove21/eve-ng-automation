"""Catalyst SD-WAN 20.15.1 Manager API contracts."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from eve_lab.sdwan_api import ManagerApi, ManagerApiError


class FixtureApi(ManagerApi):
    def __init__(self, replies):
        with patch("ssl.create_default_context", return_value=object()):
            super().__init__("192.0.2.10", certificate=Path("pin.pem"),
                             server_name="cisco.com")
        self.replies = iter(replies)
        self.calls = []
        self.xsrf_token = "token"

    def _request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return next(self.replies)


class ManagerApiTests(unittest.TestCase):
    def test_qualify_requires_session_xsrf_and_inventory(self):
        api = FixtureApi([
            (200, b"", {}),
            (200, b"", {"set-cookie": "JSESSIONID=session; Path=/"}),
            (200, b"token", {}),
            (200, json.dumps({"data": [{"deviceType": "vmanage"}]}).encode(), {}),
        ])
        result = api.qualify("admin", "hidden")
        self.assertEqual(result.controller_count, 1)
        self.assertEqual(api.session_id, "session")

    def test_enterprise_settings_use_field_proven_2015_contracts(self):
        api = FixtureApi([
            (200, b"{}", {}), (200, b"{}", {}),
            (200, b"{}", {}), (200, b"{}", {})])
        api.set_organization("nwl-lab-sdwan")
        api.set_vbond("10.1.0.2")
        api.set_enterprise_certificate_mode()
        api.set_enterprise_root(
            "-----BEGIN CERTIFICATE-----\nQUJD\n-----END CERTIFICATE-----\n")
        requests = [json.loads(call[2]["body"]) for call in api.calls]
        self.assertEqual(requests[0], {"org": "nwl-lab-sdwan"})
        self.assertEqual(requests[1], {"domainIp": "10.1.0.2", "port": "12346"})
        self.assertEqual(requests[2], {"certificateSigning": "enterprise"})
        self.assertIn("enterpriseRootCA", requests[3])
        self.assertEqual([call[0] for call in api.calls],
                         ["POST", "POST", "POST", "PUT"])

    def test_setting_read_requires_one_record(self):
        api = FixtureApi([(200, b'{"data":[{"org":"nwl-lab-sdwan"}]}', {})])
        self.assertEqual(
            api.setting("/dataservice/settings/configuration/organization"),
            {"org": "nwl-lab-sdwan"})

    def test_csr_is_correlated_by_target_ip(self):
        payload = {"data": [{"deviceIP": "10.1.0.1", "deviceCSR":
                              "-----BEGIN CERTIFICATE REQUEST-----\nQ\n"
                              "-----END CERTIFICATE REQUEST-----"}]}
        api = FixtureApi([(200, json.dumps(payload).encode(), {})])
        csr = api.generate_csr("10.1.0.1")
        self.assertTrue(csr.startswith("-----BEGIN CERTIFICATE REQUEST-----"))
        self.assertEqual(api.calls[0][1], "/dataservice/certificate/generate/csr")

    def test_signed_install_preserves_2015_raw_pem_json_content_type(self):
        api = FixtureApi([(200, b'{"id":"task-1"}', {})])
        activity = api.install_signed_certificate(
            "-----BEGIN CERTIFICATE-----\nQ\n-----END CERTIFICATE-----\n")
        self.assertEqual(activity, "task-1")
        self.assertEqual(api.calls[0][2]["content_type"], "application/json")

    def test_inventory_and_activity_fail_closed(self):
        api = FixtureApi([(200, b'{"data":{}}', {})])
        with self.assertRaises(ManagerApiError):
            api.inventory("/dataservice/certificate/record")
        with self.assertRaises(ValueError):
            api.activity_status("bad/id")


if __name__ == "__main__":
    unittest.main()
