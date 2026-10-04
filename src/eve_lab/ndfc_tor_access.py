"""Reconcile and deploy NDFC access policies on declared tenant endpoint ports."""

import time
from urllib.parse import quote

from .ndfc_fabric import _BASE, _api
from .ndfc_switch_deploy import _deployer_history, _preview, _raise_new_deployment_failure
from .nexus_dashboard_browser import NexusDashboardBrowserError, _wait_for

_INTERFACE = _BASE + "/lan-fabric/rest/interface"
_TEMPLATE = _BASE + "/configtemplate/rest/config/templates/int_access_host"
_METADATA = {"PRIORITY", "POLICY_ID", "POLICY_DESC", "GF", "FABRIC_NAME"}


def _rows(page, targets):
    status, body = _api(page, "GET", _INTERFACE)
    if status != 200 or not isinstance(body, list):
        raise NexusDashboardBrowserError("NDFC interface list is unavailable")
    rows = {}
    for group in body:
        if not isinstance(group, dict) or not isinstance(group.get("interfaces"), list):
            raise NexusDashboardBrowserError("NDFC interface list has invalid group")
        for item in group["interfaces"]:
            if not isinstance(item, dict):
                raise NexusDashboardBrowserError("NDFC interface list has invalid row")
            key = item.get("serialNumber"), item.get("ifName")
            if key not in targets:
                continue
            if key in rows:
                raise NexusDashboardBrowserError("NDFC interface list duplicates " + str(key))
            rows[key] = group.get("policy"), item.get("nvPairs")
    return rows


def _targets(access_ports, serials):
    result = {}
    for item in access_ports:
        if item["tor"] not in serials:
            raise ValueError("Declared tenant ToR is absent from NDFC inventory")
        key = serials[item["tor"]], item["port"]
        if key in result:
            raise ValueError("Declared tenant access port is duplicated")
        result[key] = str(item["vlan"])
    return result


def _verify(rows, targets):
    for key, vlan in targets.items():
        policy, nv = rows.get(key, (None, None))
        if policy != "int_access_host" or not isinstance(nv, dict) or str(
                nv.get("ACCESS_VLAN")) != vlan:
            raise NexusDashboardBrowserError(
                "NDFC tenant host access policy differs for " + str(key))


def reconcile_access_ports(page, access_ports, serials):
    """Create or edit only exact endpoint policies after overlay attachment."""
    targets = _targets(access_ports, serials)
    status, template = _api(page, "GET", _TEMPLATE)
    if status != 200 or not isinstance(template, dict):
        raise NexusDashboardBrowserError("NDFC int_access_host template is unavailable")
    fields = {item.get("name") for item in template.get("parameters", [])
              if isinstance(item, dict)}
    required = {"SERIAL_NUMBER", "INTF_NAME", "ACCESS_VLAN", "ADMIN_STATE"}
    if not required <= fields or template.get("templateSubType") != "INTERFACE_ETHERNET":
        raise NexusDashboardBrowserError("NDFC int_access_host template is incompatible")
    rows = _rows(page, targets)
    requests = []
    for key, vlan in targets.items():
        policy, nv = rows.get(key, (None, None))
        if policy == "int_access_host":
            if not isinstance(nv, dict) or str(nv.get("ACCESS_VLAN")) != vlan:
                raise NexusDashboardBrowserError(
                    "Existing NDFC host access VLAN conflicts for " + str(key))
            continue
        if policy not in (None, "int_trunk_host") or (policy and not isinstance(nv, dict)):
            raise NexusDashboardBrowserError(
                "Existing NDFC host interface policy conflicts for " + str(key))
        if policy == "int_trunk_host":
            if str(nv.get("ALLOWED_VLANS", "none")) not in ("none", vlan) or str(
                    nv.get("NATIVE_VLAN", "1")) not in ("1", vlan):
                raise NexusDashboardBrowserError(
                    "Existing NDFC host trunk VLANs conflict for " + str(key))
            desired = {name: value for name, value in nv.items()
                       if name in fields or name in _METADATA}
            method = "PUT"
        else:
            desired = {"SERIAL_NUMBER": key[0], "INTF_NAME": key[1],
                       "ADMIN_STATE": "true", "PORTTYPE_FAST_ENABLED": "true",
                       "BPDUGUARD_ENABLED": "no", "MTU": "jumbo", "SPEED": "Auto"}
            method = "POST"
        desired["ACCESS_VLAN"] = vlan
        requests.append((method, key, desired))
    for method, key, nv in requests:
        payload = {"policy": "int_access_host", "interfaces": [{
            "serialNumber": key[0], "ifName": key[1], "nvPairs": nv}]}
        status, body = _api(page, method, _INTERFACE, payload)
        if status not in (200, 202):
            raise NexusDashboardBrowserError(
                "NDFC host access policy update failed for " + str(key) +
                " with HTTP " + str(status) + ": " + str(body)[:200])
        _wait_for(page, lambda: _is_access(_rows(page, targets), key, targets[key]),
                  time.monotonic() + 30, "NDFC host access policy readback")
    _verify(_rows(page, targets), targets)
    return {"ports": len(targets), "policies_reconciled": len(requests)}


def _is_access(rows, key, vlan):
    policy, nv = rows.get(key, (None, None))
    return policy == "int_access_host" and isinstance(nv, dict) and str(
        nv.get("ACCESS_VLAN")) == vlan


def verify_access_ports(page, access_ports, serials):
    """Require all declared host ports to have the exact staged access policy."""
    targets = _targets(access_ports, serials)
    _verify(_rows(page, targets), targets)


def deploy_access_ports(page, fabric, access_ports, serials, username):
    """Deploy only declared host interfaces and require exact convergence."""
    targets = _targets(access_ports, serials)
    _verify(_rows(page, targets), targets)
    endpoint = _BASE + "/lan-fabric/rest/control/fabrics/" + quote(fabric, safe="")
    pending = []
    baselines = {}
    for serial in sorted({key[0] for key in targets}):
        view = _preview(page, endpoint, serial)
        by_port = {}
        for entity in view.get("entityList", []):
            if entity.get("entityType") == "INTERFACE":
                by_port.setdefault(entity.get("entityName"), []).extend(
                    entity.get("commands") or [])
        for (target_serial, port), vlan in targets.items():
            if target_serial != serial or port not in by_port:
                continue
            commands = by_port[port]
            if ("  switchport mode access" not in commands or
                    "  switchport access vlan " + vlan not in commands):
                raise NexusDashboardBrowserError(
                    "NDFC host access preview lacks intended mode/VLAN for " + port)
            pending.append({"serialNumber": serial, "ifName": port})
        history = _deployer_history(page, fabric, serial, username)
        baselines[serial] = max((row.get("submittedTime", "") for row in history),
                                default="")
    if not pending:
        return {"ports": len(targets), "interfaces_deployed": 0}
    status, body = _api(page, "POST", _INTERFACE + "/deploy", pending)
    if status != 200 or (isinstance(body, dict) and body.get("failureList")):
        raise NexusDashboardBrowserError(
            "NDFC tenant host interface deploy failed with HTTP " +
            str(status) + ": " + str(body)[:200])
    for serial in sorted({row["serialNumber"] for row in pending}):
        target_ports = {row["ifName"] for row in pending if row["serialNumber"] == serial}
        def converged():
            history = _deployer_history(page, fabric, serial, username)
            _raise_new_deployment_failure(history, baselines[serial], serial)
            view = _preview(page, endpoint, serial)
            remaining = {item.get("entityName") for item in view.get("entityList", [])
                         if item.get("entityType") == "INTERFACE"}
            success = any(row.get("submittedTime", "") > baselines[serial] and
                          row.get("status") == "SUCCESS" for row in history)
            return not (remaining & target_ports) and success
        _wait_for(page, converged, time.monotonic() + 300,
                  "NDFC tenant host access deployment " + serial)
    _verify(_rows(page, targets), targets)
    return {"ports": len(targets), "interfaces_deployed": len(pending)}
