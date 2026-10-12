"""Read-first reconciliation for Catalyst Center Layer-3 virtual networks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .catalyst_center import CatalystCenterError, CatalystCenterTaskError

_LAYER3_VN_PATH = "/dna/intent/api/v1/sda/layer3VirtualNetworks"


@dataclass(frozen=True)
class Layer3VirtualNetwork:
    """Desired Layer-3 VN identity and additive fabric membership."""

    virtual_network_name: str
    fabric_ids: tuple[str, ...] = ()
    anchored_site_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.virtual_network_name, str) or not self.virtual_network_name:
            raise ValueError("Layer-3 VN name is required")
        if not isinstance(self.fabric_ids, (tuple, list)):
            raise ValueError("Layer-3 VN fabric IDs must be a list or tuple")
        fabric_ids = tuple(self.fabric_ids)
        if any(not isinstance(fabric_id, str) or not fabric_id for fabric_id in fabric_ids):
            raise ValueError("Layer-3 VN fabric IDs must be non-empty strings")
        if len(set(fabric_ids)) != len(fabric_ids):
            raise ValueError("Layer-3 VN fabric IDs must be unique")
        if self.anchored_site_id is not None and (
            not isinstance(self.anchored_site_id, str) or not self.anchored_site_id
        ):
            raise ValueError("Layer-3 VN anchored site ID must be a non-empty string when supplied")
        object.__setattr__(self, "fabric_ids", fabric_ids)


@dataclass(frozen=True)
class Layer3VirtualNetworkPlan:
    desired: Layer3VirtualNetwork
    action: str
    payload: dict[str, Any] | None
    observed_id: str | None
    expected_fabric_ids: tuple[str, ...]
    expected_anchored_site_id: str | None


class Layer3VirtualNetworkAdapter:
    """Plans additive Layer-3 VN changes; it never detaches memberships."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def _records(self) -> dict[str, dict[str, Any]]:
        records = self._client.list_all(_LAYER3_VN_PATH, limit=500, operation="Layer-3 virtual network list")
        names: dict[str, dict[str, Any]] = {}
        ids: set[str] = set()
        for record in records:
            if not isinstance(record, dict):
                raise CatalystCenterError("Layer-3 virtual network list returned invalid record")
            identity = record.get("id")
            name = record.get("virtualNetworkName")
            fabric_ids = record.get("fabricIds", [])
            anchor = record.get("anchoredSiteId")
            if (
                not isinstance(identity, str)
                or not identity
                or not isinstance(name, str)
                or not name
                or not isinstance(fabric_ids, list)
                or not all(isinstance(fabric_id, str) and fabric_id for fabric_id in fabric_ids)
                or len(set(fabric_ids)) != len(fabric_ids)
                or anchor is not None and (not isinstance(anchor, str) or not anchor)
            ):
                raise CatalystCenterError("Layer-3 virtual network list returned invalid identity")
            if name in names or identity in ids:
                raise CatalystCenterError("Layer-3 virtual network list returned duplicate name or ID")
            names[name] = record
            ids.add(identity)
        return names

    @staticmethod
    def _expected_fabrics(desired: Layer3VirtualNetwork, record: dict[str, Any] | None) -> tuple[str, ...]:
        if record is None:
            return desired.fabric_ids
        merged = list(record["fabricIds"])
        for fabric_id in desired.fabric_ids:
            if fabric_id not in merged:
                merged.append(fabric_id)
        return tuple(merged)

    @classmethod
    def _payload(cls, desired: Layer3VirtualNetwork, record: dict[str, Any] | None) -> dict[str, Any]:
        if record is None:
            payload: dict[str, Any] = {"virtualNetworkName": desired.virtual_network_name}
            if desired.fabric_ids:
                payload["fabricIds"] = list(desired.fabric_ids)
            if desired.anchored_site_id is not None:
                payload["anchoredSiteId"] = desired.anchored_site_id
            return payload

        current_anchor = record.get("anchoredSiteId")
        if desired.anchored_site_id is not None:
            if current_anchor is None:
                raise CatalystCenterError(
                    f"Layer-3 VN {desired.virtual_network_name} is ordinary and cannot be converted to anchored"
                )
            if current_anchor != desired.anchored_site_id:
                raise CatalystCenterError(f"Layer-3 VN {desired.virtual_network_name} has a different anchored site")

        expected_fabrics = cls._expected_fabrics(desired, record)
        if set(expected_fabrics) == set(record["fabricIds"]):
            return {}
        payload = {
            "id": record["id"],
            "virtualNetworkName": desired.virtual_network_name,
            "fabricIds": list(expected_fabrics),
        }
        if current_anchor is not None:
            payload["anchoredSiteId"] = current_anchor
        return payload

    def plan(self, desired_networks: Iterable[Layer3VirtualNetwork]) -> tuple[Layer3VirtualNetworkPlan, ...]:
        desired = tuple(desired_networks)
        if not all(isinstance(network, Layer3VirtualNetwork) for network in desired):
            raise TypeError("desired Layer-3 VNs must be Layer3VirtualNetwork instances")
        if len({network.virtual_network_name for network in desired}) != len(desired):
            raise ValueError("desired Layer-3 VN names must be unique")
        records = self._records()
        plans: list[Layer3VirtualNetworkPlan] = []
        for network in desired:
            record = records.get(network.virtual_network_name)
            payload = self._payload(network, record)
            action = "create" if record is None else "update" if payload else "noop"
            plans.append(
                Layer3VirtualNetworkPlan(
                    network,
                    action,
                    payload or None,
                    None if record is None else record["id"],
                    self._expected_fabrics(network, record),
                    network.anchored_site_id if record is None else record.get("anchoredSiteId"),
                )
            )
        return tuple(plans)

    def reconcile(
        self,
        desired_networks: Iterable[Layer3VirtualNetwork],
        *,
        dry_run: bool = False,
    ) -> tuple[Layer3VirtualNetworkPlan, ...]:
        plans = self.plan(desired_networks)
        if dry_run or all(plan.action == "noop" for plan in plans):
            return plans

        for action, method in (("create", "POST"), ("update", "PUT")):
            payload = [plan.payload for plan in plans if plan.action == action]
            if not payload:
                continue
            response = self._client.request(
                method,
                _LAYER3_VN_PATH,
                body=payload,
                operation=f"Layer-3 virtual network {action}",
            )
            task = self._client.task_reference(response)
            if task is None:
                raise CatalystCenterTaskError(f"Layer-3 virtual network {action} returned no task ID")
            self._client.wait_task(task)

        actual = self._records()
        for plan in plans:
            record = actual.get(plan.desired.virtual_network_name)
            if record is None:
                raise CatalystCenterError(f"Layer-3 VN {plan.desired.virtual_network_name} did not converge")
            if plan.observed_id is not None and record["id"] != plan.observed_id:
                raise CatalystCenterError(f"Layer-3 VN {plan.desired.virtual_network_name} changed controller ID")
            if set(record["fabricIds"]) != set(plan.expected_fabric_ids):
                raise CatalystCenterError(f"Layer-3 VN {plan.desired.virtual_network_name} changed fabric membership")
            if record.get("anchoredSiteId") != plan.expected_anchored_site_id:
                raise CatalystCenterError(f"Layer-3 VN {plan.desired.virtual_network_name} changed anchored site")
        return plans

_LAYER2_VN_PATH = "/dna/intent/api/v1/sda/layer2VirtualNetworks"


@dataclass(frozen=True)
class Layer2VirtualNetwork:
    fabric_id: str
    vlan_name: str
    traffic_type: str
    vlan_id: int | None = None
    associated_layer3_virtual_network_name: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.fabric_id, str) or not self.fabric_id:
            raise ValueError("Layer-2 VN fabric ID is required")
        if not isinstance(self.vlan_name, str) or not self.vlan_name or any(not (char.isalnum() or char in "_-") for char in self.vlan_name):
            raise ValueError("Layer-2 VN name may contain only alphanumeric characters, underscores, and hyphens")
        if self.traffic_type not in {"DATA", "VOICE"}:
            raise ValueError("Layer-2 VN traffic type must be DATA or VOICE")
        if self.vlan_id is not None and (type(self.vlan_id) is not int or not 2 <= self.vlan_id <= 4093 or 1002 <= self.vlan_id <= 1005 or self.vlan_id == 2046):
            raise ValueError("Layer-2 VN VLAN ID is reserved or outside 2-4093")
        if self.associated_layer3_virtual_network_name is not None and (
            not isinstance(self.associated_layer3_virtual_network_name, str) or not self.associated_layer3_virtual_network_name
        ):
            raise ValueError("Layer-2 VN associated Layer-3 VN name must be non-empty when supplied")

    def payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"fabricId": self.fabric_id, "vlanName": self.vlan_name, "trafficType": self.traffic_type}
        if self.vlan_id is not None:
            payload["vlanId"] = self.vlan_id
        if self.associated_layer3_virtual_network_name is not None:
            payload["associatedLayer3VirtualNetworkName"] = self.associated_layer3_virtual_network_name
        return payload


@dataclass(frozen=True)
class Layer2VirtualNetworkPlan:
    desired: Layer2VirtualNetwork
    action: str
    payload: dict[str, Any] | None
    observed_id: str | None


class Layer2VirtualNetworkAdapter:
    """Create-only Layer-2 VNs; existing association identity is immutable."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def _records(self, fabric_id: str) -> list[dict[str, Any]]:
        records = self._client.list_all(_LAYER2_VN_PATH, query={"fabricId": fabric_id}, limit=500, operation="Layer-2 virtual network list")
        ids: set[str] = set()
        names: set[tuple[str, str]] = set()
        explicit_vlans: set[tuple[str, int]] = set()
        result: list[dict[str, Any]] = []
        for record in records:
            if not isinstance(record, dict):
                raise CatalystCenterError("Layer-2 virtual network list returned invalid record")
            identity, fabric, name, vlan, traffic, association = (
                record.get("id"), record.get("fabricId"), record.get("vlanName"), record.get("vlanId"), record.get("trafficType"), record.get("associatedLayer3VirtualNetworkName")
            )
            if (
                not isinstance(identity, str) or not identity or fabric != fabric_id or not isinstance(name, str) or not name
                or vlan is not None and type(vlan) is not int or traffic not in {"DATA", "VOICE"}
                or association is not None and (not isinstance(association, str) or not association)
            ):
                raise CatalystCenterError("Layer-2 virtual network list returned invalid identity")
            name_key = (fabric, name)
            vlan_key = None if vlan is None else (fabric, vlan)
            if identity in ids or name_key in names or vlan_key is not None and vlan_key in explicit_vlans:
                raise CatalystCenterError("Layer-2 virtual network list returned duplicate ID, name, or explicit VLAN")
            ids.add(identity)
            names.add(name_key)
            if vlan_key is not None:
                explicit_vlans.add(vlan_key)
            result.append(record)
        return result

    def _validate_layer3_associations(self, desired: tuple[Layer2VirtualNetwork, ...]) -> None:
        required = {network.associated_layer3_virtual_network_name for network in desired if network.associated_layer3_virtual_network_name is not None}
        if not required:
            return
        records = self._client.list_all(_LAYER3_VN_PATH, limit=500, operation="Layer-3 virtual network list")
        available = {record.get("virtualNetworkName") for record in records if isinstance(record, dict)}
        missing = required - available
        if missing:
            raise CatalystCenterError("Layer-2 VN associated Layer-3 VN is not present")

    def plan(self, desired_networks: Iterable[Layer2VirtualNetwork]) -> tuple[Layer2VirtualNetworkPlan, ...]:
        desired = tuple(desired_networks)
        if not all(isinstance(network, Layer2VirtualNetwork) for network in desired):
            raise TypeError("desired Layer-2 VNs must be Layer2VirtualNetwork instances")
        names = {(network.fabric_id, network.vlan_name) for network in desired}
        explicit_vlans = {(network.fabric_id, network.vlan_id) for network in desired if network.vlan_id is not None}
        if len(names) != len(desired) or len(explicit_vlans) != sum(network.vlan_id is not None for network in desired):
            raise ValueError("desired Layer-2 VN fabric names and explicit VLAN IDs must be unique")
        self._validate_layer3_associations(desired)
        records: dict[str, list[dict[str, Any]]] = {fabric: self._records(fabric) for fabric in {network.fabric_id for network in desired}}
        plans: list[Layer2VirtualNetworkPlan] = []
        for network in desired:
            matches = [record for record in records[network.fabric_id] if record["vlanName"] == network.vlan_name or network.vlan_id is not None and record.get("vlanId") == network.vlan_id]
            if len(matches) > 1:
                raise CatalystCenterError(f"Layer-2 VN {network.vlan_name} has conflicting existing identities")
            if not matches:
                plans.append(Layer2VirtualNetworkPlan(network, "create", network.payload(), None))
                continue
            record = matches[0]
            if record["vlanName"] != network.vlan_name or network.vlan_id is not None and record.get("vlanId") != network.vlan_id or record["trafficType"] != network.traffic_type or record.get("associatedLayer3VirtualNetworkName") != network.associated_layer3_virtual_network_name:
                raise CatalystCenterError(f"Layer-2 VN {network.vlan_name} conflicts with immutable existing association")
            plans.append(Layer2VirtualNetworkPlan(network, "noop", None, record["id"]))
        return tuple(plans)

    def reconcile(self, desired_networks: Iterable[Layer2VirtualNetwork], *, dry_run: bool = False) -> tuple[Layer2VirtualNetworkPlan, ...]:
        plans = self.plan(desired_networks)
        if dry_run or all(plan.action == "noop" for plan in plans):
            return plans
        for plan in plans:
            if plan.action != "create":
                continue
            response = self._client.request("POST", _LAYER2_VN_PATH, body=[plan.payload], operation="Layer-2 virtual network create")
            task = self._client.task_reference(response)
            if task is None:
                raise CatalystCenterTaskError("Layer-2 virtual network create returned no task ID")
            self._client.wait_task(task)
        actual: dict[str, list[dict[str, Any]]] = {fabric: self._records(fabric) for fabric in {plan.desired.fabric_id for plan in plans}}
        for plan in plans:
            matches = [record for record in actual[plan.desired.fabric_id] if record["vlanName"] == plan.desired.vlan_name]
            if len(matches) != 1:
                raise CatalystCenterError(f"Layer-2 VN {plan.desired.vlan_name} did not converge")
            record = matches[0]
            if plan.observed_id is not None and record["id"] != plan.observed_id:
                raise CatalystCenterError(f"Layer-2 VN {plan.desired.vlan_name} changed controller ID")
            if plan.desired.vlan_id is not None and record.get("vlanId") != plan.desired.vlan_id or record["trafficType"] != plan.desired.traffic_type or record.get("associatedLayer3VirtualNetworkName") != plan.desired.associated_layer3_virtual_network_name:
                raise CatalystCenterError(f"Layer-2 VN {plan.desired.vlan_name} changed association")
        return plans
