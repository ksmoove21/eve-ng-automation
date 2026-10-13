"""Create-only ordinary Anycast Gateways for Catalyst Center 2.3.7.9.

DOCUMENTED: POST accepts an array and returns an asynchronous task; GET supports
fabricId filtering and pagination (maximum 500). The VN must already belong to
the fabric and its IP pool must exist; prerequisite provisioning is caller-owned.
FIELD-TEST REQUIRED: controller application and forwarding on the target lab.

Only explicit VLAN names/IDs and non-critical, non-INFRA_VN pools are supported.
GET does not document autoGenerateVlanName: the request always disables it and
readback must prove the exact VLAN name. All other requested fields are required
in readback. Existing records, including unmodeled options, must remain stable.
No update, delete, retry of a failed mutation, or rollback is performed.

References:
https://developer.cisco.com/docs/catalyst-center/2-3-7-9/add-anycast-gateways/
https://developer.cisco.com/docs/catalyst-center/2-3-7-9/get-anycast-gateways/
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable

from .catalyst_center import CatalystCenterError, CatalystCenterTaskError, TaskStatus

_ANYCAST_PATH = "/dna/intent/api/v1/sda/anycastGateways"
_OPTION_FIELDS = {
    "is_critical_pool": "isCriticalPool",
    "is_layer2_flooding_enabled": "isLayer2FloodingEnabled",
    "is_wireless_pool": "isWirelessPool",
    "is_ip_directed_broadcast": "isIpDirectedBroadcast",
    "is_intra_subnet_routing_enabled": "isIntraSubnetRoutingEnabled",
    "is_multiple_ip_to_mac_addresses": "isMultipleIpToMacAddresses",
    "auto_generate_vlan_name": "autoGenerateVlanName",
}


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip() and all(ord(char) >= 32 and ord(char) != 127 for char in value)


def _vlan(value: Any) -> bool:
    return type(value) is int and 2 <= value <= 4093 and value not in {1002, 1003, 1004, 1005, 2046}


@dataclass(frozen=True)
class AnycastGateway:
    fabric_id: str
    virtual_network_name: str
    ip_pool_name: str
    vlan_id: int
    vlan_name: str
    traffic_type: str = "DATA"
    is_critical_pool: bool = False
    is_layer2_flooding_enabled: bool = False
    is_wireless_pool: bool = False
    is_ip_directed_broadcast: bool = False
    is_intra_subnet_routing_enabled: bool = True
    is_multiple_ip_to_mac_addresses: bool = False
    auto_generate_vlan_name: bool = False

    def __post_init__(self) -> None:
        if not all(_text(value) for value in (self.fabric_id, self.virtual_network_name, self.ip_pool_name, self.vlan_name)):
            raise ValueError("Anycast gateway fabric, VN, pool, and VLAN names must be nonempty text without control characters")
        if not _vlan(self.vlan_id):
            raise ValueError("Anycast gateway VLAN ID is reserved or outside 2-4093")
        if self.traffic_type not in ("DATA", "VOICE"):
            raise ValueError("Anycast gateway traffic type must be DATA or VOICE")
        if any(type(getattr(self, field)) is not bool for field in _OPTION_FIELDS):
            raise ValueError("Anycast gateway options must be booleans")
        if self.is_critical_pool or self.auto_generate_vlan_name or self.virtual_network_name == "INFRA_VN":
            raise ValueError("Anycast gateway adapter requires non-critical, non-INFRA_VN pools and explicit VLAN names")

    def payload(self) -> dict[str, Any]:
        return {
            "fabricId": self.fabric_id,
            "virtualNetworkName": self.virtual_network_name,
            "ipPoolName": self.ip_pool_name,
            "vlanId": self.vlan_id,
            "vlanName": self.vlan_name,
            "trafficType": self.traffic_type,
            **{api: getattr(self, field) for field, api in _OPTION_FIELDS.items()},
        }


@dataclass(frozen=True)
class AnycastGatewayPlan:
    desired: AnycastGateway
    action: str
    payload: dict[str, Any] | None
    observed_id: str | None


class AnycastGatewayAdapter:
    """Read-first reconciliation; batch missing gateways and verify all readback."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def _records(self, fabric_id: str) -> dict[str, dict[str, Any]]:
        records = self._client.list_all(
            _ANYCAST_PATH, query={"fabricId": fabric_id}, limit=500,
            operation="Anycast gateway list",
        )
        result: dict[str, dict[str, Any]] = {}
        identities: dict[str, set[Any]] = {key: set() for key in ("id", "ipPoolName", "vlanName", "vlanId")}
        for record in records:
            if not isinstance(record, dict) or record.get("fabricId") != fabric_id:
                raise CatalystCenterError("Anycast gateway list returned invalid record or fabric scope")
            if (
                not all(_text(record.get(key)) for key in ("id", "virtualNetworkName", "ipPoolName", "vlanName"))
                or not _vlan(record.get("vlanId")) or record.get("trafficType") not in ("DATA", "VOICE")
            ):
                raise CatalystCenterError("Anycast gateway list returned invalid identity")
            if any(key in record and type(record[key]) is not bool for key in _OPTION_FIELDS.values()):
                raise CatalystCenterError("Anycast gateway list returned invalid option type")
            for key, values in identities.items():
                if record[key] in values:
                    raise CatalystCenterError("Anycast gateway list returned duplicate ID, pool, VLAN ID, or VLAN name")
                values.add(record[key])
            result[record["id"]] = deepcopy(record)
        return result

    @staticmethod
    def _match(desired: AnycastGateway, records: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
        matches = [record for record in records.values() if (
            record["ipPoolName"] == desired.ip_pool_name
            or record["vlanId"] == desired.vlan_id
            or record["vlanName"] == desired.vlan_name
        )]
        if len(matches) > 1:
            raise CatalystCenterError("Anycast gateway has conflicting existing identities")
        if not matches:
            return None
        record = matches[0]
        for key, value in desired.payload().items():
            # This is a POST-only field in the documented 2.3.7.9 GET schema.
            if key == "autoGenerateVlanName" and key not in record:
                continue
            if key not in record or record[key] != value:
                raise CatalystCenterError(f"Anycast gateway conflicts with existing {key}")
        return record

    def _prepare(self, desired_gateways: Iterable[AnycastGateway]) -> tuple[
        tuple[AnycastGatewayPlan, ...], dict[str, dict[str, dict[str, Any]]]
    ]:
        desired = tuple(desired_gateways)
        if not all(isinstance(gateway, AnycastGateway) for gateway in desired):
            raise TypeError("desired gateways must be AnycastGateway instances")
        for field in ("ip_pool_name", "vlan_id", "vlan_name"):
            if len({(gateway.fabric_id, getattr(gateway, field)) for gateway in desired}) != len(desired):
                raise ValueError("desired Anycast gateway pool, VLAN ID, and VLAN name must be unique within each fabric")
        records = {fabric: self._records(fabric) for fabric in sorted({gateway.fabric_id for gateway in desired})}
        ids = [identity for fabric in records.values() for identity in fabric]
        if len(ids) != len(set(ids)):
            raise CatalystCenterError("Anycast gateway list returned duplicate ID across fabrics")
        plans = []
        for gateway in desired:
            observed = self._match(gateway, records[gateway.fabric_id])
            plans.append(AnycastGatewayPlan(
                gateway, "noop" if observed else "create",
                None if observed else gateway.payload(), observed["id"] if observed else None,
            ))
        return tuple(plans), records

    def plan(self, desired_gateways: Iterable[AnycastGateway]) -> tuple[AnycastGatewayPlan, ...]:
        return self._prepare(desired_gateways)[0]

    def reconcile(self, desired_gateways: Iterable[AnycastGateway], *, dry_run: bool = False) -> tuple[AnycastGatewayPlan, ...]:
        plans, before = self._prepare(desired_gateways)
        creates = [plan.payload for plan in plans if plan.action == "create"]
        if dry_run or not creates:
            return plans
        response = self._client.request(
            "POST", _ANYCAST_PATH, body=creates, operation="Anycast gateway create",
        )
        task = self._client.task_reference(response)
        if task is None:
            raise CatalystCenterTaskError("Anycast gateway create returned no task ID")
        status = self._client.wait_task(task)
        if (
            not isinstance(status, TaskStatus) or status.task_id != task.task_id
            or not status.completed or not status.successful or status.error
        ):
            raise CatalystCenterTaskError("Anycast gateway create did not complete successfully")
        actual = {fabric: self._records(fabric) for fabric in before}
        ids = [identity for records in actual.values() for identity in records]
        if len(ids) != len(set(ids)):
            raise CatalystCenterError("Anycast gateway readback returned duplicate ID across fabrics")
        for fabric, records in before.items():
            for identity, record in records.items():
                if actual[fabric].get(identity) != record:
                    raise CatalystCenterError("Anycast gateway reconciliation changed an existing controller object")
        expected_ids = {fabric: set(records) for fabric, records in before.items()}
        for plan in plans:
            observed = self._match(plan.desired, actual[plan.desired.fabric_id])
            if observed is None:
                raise CatalystCenterError("Anycast gateway did not converge in filtered readback")
            if plan.observed_id is not None and observed["id"] != plan.observed_id:
                raise CatalystCenterError("Anycast gateway changed controller ID")
            expected_ids[plan.desired.fabric_id].add(observed["id"])
        if any(set(actual[fabric]) != identities for fabric, identities in expected_ids.items()):
            raise CatalystCenterError("Anycast gateway readback contains unexpected additional objects")
        return plans
