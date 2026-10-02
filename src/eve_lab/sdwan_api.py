"""Certificate-pinned Catalyst SD-WAN 20.15.1 Manager API client."""
from dataclasses import dataclass
from http.client import HTTPSConnection
from http.cookies import SimpleCookie
import ipaddress
import json
from pathlib import Path
import re
import socket
import ssl
from urllib.parse import urlencode


class ManagerApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class ManagerReadiness:
    controller_count: int


@dataclass(frozen=True)
class ActivityStatus:
    activity_id: str
    status: str
    completed: bool


class _NamedTLSConnection(HTTPSConnection):
    def __init__(self, host, port, *, server_name, context, timeout):
        super().__init__(host, port, context=context, timeout=timeout)
        self.server_name = server_name

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), self.timeout)
        self.sock = self._context.wrap_socket(
            self.sock, server_hostname=self.server_name)


class ManagerApi:
    """Use an IP transport while verifying the Manager certificate name."""

    _INVENTORIES = {
        "/dataservice/system/device/controllers",
        "/dataservice/certificate/record",
        "/dataservice/certificate/device/list",
        "/dataservice/certificate/device/details",
        "/dataservice/certificate/csr/details",
    }

    def __init__(self, address: str, *, certificate: Path, server_name: str,
                 port=443, timeout=15):
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as error:
            raise ValueError("A valid Manager IP address is required") from error
        if parsed.version != 4:
            raise ValueError("A valid Manager IPv4 address is required")
        if not re.fullmatch(r"[A-Za-z0-9.-]+", server_name or ""):
            raise ValueError("A valid certificate server name is required")
        self.address = str(parsed)
        self.port = port
        self.server_name = server_name
        self.timeout = timeout
        self.context = ssl.create_default_context(cafile=str(certificate))
        self.session_id = None
        self.xsrf_token = None

    def _request(self, method, path, *, body=None, content_type=None, xsrf=False):
        headers = {"Accept": "application/json"}
        if content_type:
            headers["Content-Type"] = content_type
        if self.session_id:
            headers["Cookie"] = "JSESSIONID=" + self.session_id
        if xsrf:
            if not self.xsrf_token:
                raise ManagerApiError("XSRF token unavailable")
            headers["X-XSRF-TOKEN"] = self.xsrf_token
        connection = _NamedTLSConnection(
            self.address, self.port, server_name=self.server_name,
            context=self.context, timeout=self.timeout)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            payload = response.read(4 * 1024 * 1024 + 1)
            if len(payload) > 4 * 1024 * 1024:
                raise ManagerApiError("Manager API response exceeded size limit")
            return (response.status, payload,
                    {name.lower(): value for name, value in response.getheaders()})
        except (OSError, ssl.SSLError) as error:
            raise ManagerApiError(
                "Manager HTTPS unavailable: " + type(error).__name__) from error
        finally:
            connection.close()

    @staticmethod
    def _decode(payload, operation):
        try:
            value = json.loads(payload)
        except (UnicodeError, ValueError) as error:
            raise ManagerApiError(operation + " returned invalid JSON") from error
        if not isinstance(value, dict):
            raise ManagerApiError(operation + " returned an unexpected body")
        return value

    def qualify(self, username, password):
        status, _, _ = self._request("GET", "/")
        if status != 200:
            raise ManagerApiError("HTTPS qualification failed: HTTP " + str(status))
        body = urlencode({"j_username": username,
                          "j_password": password}).encode()
        status, payload, headers = self._request(
            "POST", "/j_security_check", body=body,
            content_type="application/x-www-form-urlencoded")
        if status != 200 or payload.strip():
            raise ManagerApiError("Manager authentication failed")
        cookies = SimpleCookie()
        cookies.load(headers.get("set-cookie", ""))
        session = cookies.get("JSESSIONID")
        if session is None or not session.value:
            raise ManagerApiError("Manager authentication omitted JSESSIONID")
        self.session_id = session.value
        status, payload, _ = self._request("GET", "/dataservice/client/token")
        if status != 200 or not payload.strip() or b"<" in payload:
            raise ManagerApiError("Manager XSRF acquisition failed")
        self.xsrf_token = payload.decode("ascii").strip()
        records = self.inventory("/dataservice/system/device/controllers")
        return ManagerReadiness(controller_count=len(records))

    def inventory(self, endpoint):
        if endpoint not in self._INVENTORIES:
            raise ValueError("Unsupported Manager inventory endpoint")
        status, payload, _ = self._request("GET", endpoint, xsrf=True)
        if status != 200:
            raise ManagerApiError("Manager inventory failed: HTTP " + str(status))
        records = self._decode(payload, "Manager inventory").get("data")
        if (not isinstance(records, list)
                or not all(isinstance(record, dict) for record in records)):
            raise ManagerApiError("Manager inventory returned unexpected records")
        return tuple(records)

    def _json_write(self, method, endpoint, request, operation):
        status, payload, _ = self._request(
            method, endpoint,
            body=json.dumps(request, separators=(",", ":")).encode(),
            content_type="application/json", xsrf=True)
        if status != 200:
            raise ManagerApiError(operation + " failed: HTTP " + str(status))
        return self._decode(payload, operation) if payload.strip() else {}

    def _json_post(self, endpoint, request, operation):
        return self._json_write("POST", endpoint, request, operation)

    def _json_put(self, endpoint, request, operation):
        return self._json_write("PUT", endpoint, request, operation)

    def setting(self, endpoint):
        allowed = {
            "/dataservice/settings/configuration/organization",
            "/dataservice/settings/configuration/device",
            "/dataservice/settings/configuration/certificate",
            "/dataservice/settings/configuration/certificate/enterpriserootca",
        }
        if endpoint not in allowed:
            raise ValueError("Unsupported Manager setting endpoint")
        status, payload, _ = self._request("GET", endpoint, xsrf=True)
        if status != 200:
            raise ManagerApiError("Manager setting read failed: HTTP " + str(status))
        records = self._decode(payload, "Manager setting read").get("data")
        if (not isinstance(records, list) or len(records) != 1
                or not isinstance(records[0], dict)):
            raise ManagerApiError("Manager setting read returned unexpected records")
        return records[0]

    def set_organization(self, organization):
        if (not isinstance(organization, str) or not organization.strip()
                or len(organization) > 128 or any(
                    ord(character) < 32 for character in organization)):
            raise ValueError("Invalid SD-WAN organization name")
        self._json_post(
            "/dataservice/settings/configuration/organization",
            {"org": organization.strip()}, "Manager organization setting")

    def set_vbond(self, address, port=12346):
        parsed = ipaddress.ip_address(address)
        if parsed.version != 4 or not 1 <= port <= 65535:
            raise ValueError("Invalid Validator address or port")
        self._json_post(
            "/dataservice/settings/configuration/device",
            {"domainIp": str(parsed), "port": str(port)},
            "Manager Validator setting")

    def set_enterprise_certificate_mode(self):
        self._json_post(
            "/dataservice/settings/configuration/certificate",
            {"certificateSigning": "enterprise"},
            "Manager enterprise certificate mode")

    def set_enterprise_root(self, certificate):
        normalized = certificate.replace("\r\n", "\n").strip() + "\n"
        if not re.fullmatch(
                r"-----BEGIN CERTIFICATE-----\n.+\n-----END CERTIFICATE-----\n",
                normalized, re.S):
            raise ValueError("A single enterprise root certificate is required")
        self._json_put(
            "/dataservice/settings/configuration/certificate/enterpriserootca",
            {"enterpriseRootCA": normalized}, "Manager enterprise root CA")

    def generate_csr(self, device_ip):
        parsed = ipaddress.ip_address(device_ip)
        response = self._json_post(
            "/dataservice/certificate/generate/csr",
            {"deviceIP": str(parsed)}, "Control-component CSR generation")
        records = response.get("data")
        if not isinstance(records, list):
            raise ManagerApiError("CSR generation returned unexpected records")
        matches = [record for record in records if isinstance(record, dict)
                   and str(record.get("deviceIP", "")) == str(parsed)]
        if len(matches) != 1:
            raise ManagerApiError("CSR generation did not correlate the target")
        csr = matches[0].get("deviceCSR")
        if not isinstance(csr, str) or not csr.strip().startswith(
                "-----BEGIN CERTIFICATE REQUEST-----"):
            raise ManagerApiError("CSR generation returned no CSR")
        return csr.strip() + "\n"

    def install_signed_certificate(self, certificate):
        normalized = certificate.replace("\r\n", "\n").strip() + "\n"
        if not re.fullmatch(
                r"-----BEGIN CERTIFICATE-----\n.+\n-----END CERTIFICATE-----\n",
                normalized, re.S):
            raise ValueError("A single signed certificate is required")
        status, payload, _ = self._request(
            "POST", "/dataservice/certificate/install/signedCert",
            body=normalized.encode("ascii"), content_type="application/json",
            xsrf=True)
        if status != 200:
            raise ManagerApiError(
                "Signed certificate install failed: HTTP " + str(status))
        response = self._decode(payload, "Signed certificate install")
        activity_id = response.get("id")
        if activity_id is not None and not re.fullmatch(
                r"[A-Za-z0-9-]{1,128}", str(activity_id)):
            raise ManagerApiError("Signed certificate install activity is invalid")
        return activity_id

    def activity_status(self, activity_id):
        if not re.fullmatch(r"[A-Za-z0-9-]{1,128}", activity_id or ""):
            raise ValueError("A valid activity ID is required")
        status, payload, _ = self._request(
            "GET", "/dataservice/device/action/status/" + activity_id,
            xsrf=True)
        if status != 200:
            raise ManagerApiError("Activity status failed: HTTP " + str(status))
        summary = self._decode(payload, "Activity status").get("summary")
        state = summary.get("status") if isinstance(summary, dict) else None
        if not isinstance(state, str) or not state:
            raise ManagerApiError("Activity status returned an unexpected body")
        return ActivityStatus(
            activity_id, state,
            state.strip().lower() in {
                "success", "completed", "done", "failure", "failed", "error"})
