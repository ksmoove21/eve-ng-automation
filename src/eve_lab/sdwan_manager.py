"""Desired-state Manager fabric operations for Catalyst SD-WAN 20.15.1."""
import hashlib


_ORGANIZATION = "/dataservice/settings/configuration/organization"
_VBOND = "/dataservice/settings/configuration/device"
_CERTIFICATE = "/dataservice/settings/configuration/certificate"
_ENTERPRISE_ROOT = (
    "/dataservice/settings/configuration/certificate/enterpriserootca")


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
        and str(record.get("personality", "")).lower() == personality.lower()
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "Manager certificate inventory did not contain one correlated "
            + personality + " record")
    return matches[0]


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
