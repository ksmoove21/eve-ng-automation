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
