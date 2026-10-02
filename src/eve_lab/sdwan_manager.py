"""Desired-state Manager fabric operations for Catalyst SD-WAN 20.15.1."""
from dataclasses import dataclass
import hashlib
import re
import time


_ORGANIZATION = "/dataservice/settings/configuration/organization"
_VBOND = "/dataservice/settings/configuration/device"
_CERTIFICATE = "/dataservice/settings/configuration/certificate"
_ENTERPRISE_ROOT = (
    "/dataservice/settings/configuration/certificate/enterpriserootca")


@dataclass(frozen=True)
class SettledControlCsr:
    record: dict
    csr: str
    sha256: str


def _pem_sha256(certificate):
    normalized = certificate.replace("\r\n", "\n").strip() + "\n"
    return hashlib.sha256(normalized.encode("ascii")).hexdigest()


def ensure_fabric_settings(api, *, organization, vbond, root_certificate,
                           port=12346):
    """Apply only missing Manager fabric settings and prove exact read-back."""
    changed = []

    current = api.setting(_ORGANIZATION)
    if not current:
        api.set_organization(organization)
        changed.append("organization")
        current = api.setting(_ORGANIZATION)
    if current.get("org") != organization:
        raise RuntimeError("Manager organization differs from declared intent")

    expected_vbond = (vbond, str(port))
    current = api.setting(_VBOND)
    if not current:
        api.set_vbond(vbond, port)
        changed.append("validator")
        current = api.setting(_VBOND)
    observed_vbond = (current.get("domainIp"), str(current.get("port")))
    if observed_vbond != expected_vbond:
        raise RuntimeError("Manager Validator differs from declared intent")

    current = api.setting(_CERTIFICATE)
    signing = current.get("certificateSigning")
    if signing == "cisco":
        api.set_enterprise_certificate_mode()
        changed.append("certificate-mode")
        current = api.setting(_CERTIFICATE)
    if current.get("certificateSigning") != "enterprise":
        raise RuntimeError("Manager certificate mode is neither Cisco nor enterprise")

    expected_root = _pem_sha256(root_certificate)
    current = api.setting(_ENTERPRISE_ROOT)
    installed_root = current.get("enterpriseRootCA")
    if not installed_root:
        api.set_enterprise_root(root_certificate)
        changed.append("enterprise-root")
        current = api.setting(_ENTERPRISE_ROOT)
        installed_root = current.get("enterpriseRootCA")
    if (not isinstance(installed_root, str)
            or _pem_sha256(installed_root) != expected_root):
        raise RuntimeError("Manager enterprise root differs from Manager-local CA")

    return {
        "changed": changed,
        "certificate_mode": "enterprise",
        "enterprise_root_sha256": expected_root,
        "organization": organization,
        "validator": vbond + ":" + str(port),
    }


def control_component_record(api, *, device_ip, personality):
    """Return one exactly correlated control-component certificate record."""
    records = api.inventory("/dataservice/certificate/record")
    matches = [
        record for record in records
        if str(record.get("deviceIP", "")) == device_ip
        and personality.lower() in {
            str(record.get("personality", "")).lower(),
            str(record.get("deviceType", "")).lower(),
        }
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "Manager certificate inventory did not contain one correlated "
            + personality + " record")
    return matches[0]


def control_component_record_by_uuid(api, *, record_uuid, personality):
    """Return one stable-UUID control-component certificate record."""
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", record_uuid or ""):
        raise ValueError("A valid control-component record UUID is required")
    matches = [
        record for record in api.inventory("/dataservice/certificate/record")
        if str(record.get("uuid", "")) == record_uuid
        and personality.lower() in {
            str(record.get("personality", "")).lower(),
            str(record.get("deviceType", "")).lower(),
        }
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "Manager certificate inventory did not contain one stable "
            + personality + " record")
    return matches[0]


def _record_csr(record):
    values = []
    for key in ("deviceCSR", "CSRDetail"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            normalized = value.replace("\r\n", "\n").strip() + "\n"
            if not (normalized.startswith("-----BEGIN CERTIFICATE REQUEST-----\n")
                    and normalized.endswith(
                        "-----END CERTIFICATE REQUEST-----\n")
                    and normalized.count("-----BEGIN CERTIFICATE REQUEST-----") == 1
                    and normalized.count("-----END CERTIFICATE REQUEST-----") == 1):
                raise RuntimeError("Manager returned an invalid control-component CSR")
            values.append(normalized)
    if not values:
        return None
    if len(set(values)) != 1:
        raise RuntimeError("Manager control-component CSR fields disagree")
    return values[0]


def wait_for_control_component_csr(
        api, *, record_uuid, personality, timeout=300, poll_seconds=5,
        stable_observations=2, _sleep=time.sleep, _clock=time.monotonic):
    """Wait for the post-Add lifecycle's final, stable Manager-owned CSR."""
    if timeout <= 0 or poll_seconds <= 0:
        raise ValueError("CSR wait timeout and poll interval must be positive")
    if stable_observations < 2:
        raise ValueError("CSR settlement requires at least two observations")
    deadline = _clock() + timeout
    previous = None
    observations = 0
    while True:
        record = control_component_record_by_uuid(
            api, record_uuid=record_uuid, personality=personality)
        csr = _record_csr(record)
        lifecycle_complete = record.get("lifeCycleRequired") is False
        if lifecycle_complete and csr:
            current = hashlib.sha256(csr.encode("ascii")).hexdigest()
            observations = observations + 1 if current == previous else 1
            previous = current
            if observations >= stable_observations:
                return SettledControlCsr(record, csr, current)
        else:
            previous = None
            observations = 0
        if _clock() >= deadline:
            raise RuntimeError(
                "Manager control-component lifecycle/CSR did not settle")
        _sleep(poll_seconds)


def certificate_is_installed(record, *, root_hash=None):
    """Require Manager's certificate state and serial read-back to agree."""
    status = str(record.get("certInstallStatus", "")).strip().lower()
    serial = str(record.get("serialNumber", "")).strip()
    installed = (status == "installed" and bool(serial)
                 and serial.lower() != "no certificate installed")
    if root_hash is not None:
        expected = root_hash.replace(":", "").strip().lower()
        observed = str(record.get("rootCertHash", "")).strip().lower()
        installed = installed and observed == expected
    return installed
