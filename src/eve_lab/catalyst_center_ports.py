"""Create-only explicit trunk port assignments for Catalyst Center 2.3.7.9.

DOCUMENTED: POST arrays must contain one device from one fabric. GET can filter
by both identities. Its limit parameter says 500 while the response schema says
50; use pages of 50 to avoid treating a capped page as the end of the collection.
The authentication enum is 'No Authentication' (including the space).
FIELD-TEST REQUIRED: controller application and guest trunk forwarding.

Each device batch is task-verified and read back before another is submitted.
A failure may leave earlier batches applied; rerun planning against actual state.
There is no automatic mutation retry, PUT, DELETE, or rollback.

https://developer.cisco.com/docs/catalyst-center/2-3-7-9/add-port-assignments/
https://developer.cisco.com/docs/catalyst-center/2-3-7-9/get-port-assignments/
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any, Callable, Iterable, Mapping

from .catalyst_center import CatalystCenterError, CatalystCenterTaskError, TaskStatus

_PORT_PATH = "/dna/intent/api/v1/sda/portAssignments"
Group = tuple[str, str]
Records = dict[str, dict[str, Any]]
TrunkObserver = Callable[[str, str, str], Mapping[str, Any]]


def normalize_vlan_ranges(value: str) -> str:
    """Canonicalize a nonoverlapping VLAN list/ranges or 'all' within 1..4094."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Allowed VLAN ranges must be a nonempty string")
    if value.strip() == "all":
        return "all"
    intervals = []
    for token in value.split(","):
        match = re.fullmatch(r"\s*([0-9]+)\s*(?:-\s*([0-9]+)\s*)?", token)
        if not match:
            raise ValueError("Allowed VLAN ranges contain an invalid token")
        first = int(match[1])
        last = int(match[2]) if match[2] is not None else first
        if not 1 <= first <= last <= 4094:
            raise ValueError("Allowed VLAN ranges must be within 1-4094 and ascending")
        intervals.append((first, last))
    merged: list[tuple[int, int]] = []
    for first, last in sorted(intervals):
        if merged and first <= merged[-1][1]:
            raise ValueError("Allowed VLAN ranges must not overlap or repeat")
        if merged and first == merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], last)
        else:
            merged.append((first, last))
    if merged == [(1, 4094)]:
        return "all"
    return ",".join(str(first) if first == last else f"{first}-{last}" for first, last in merged)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip() and all(ord(char) >= 32 and ord(char) != 127 for char in value)


def _vlan(value: Any) -> bool:
    return type(value) is int and 1 <= value <= 4094


@dataclass(frozen=True)
class TrunkPortAssignment:
    fabric_id: str
    network_device_id: str
    interface_name: str
    native_vlan_id: int
    allowed_vlan_ranges: str

    def __post_init__(self) -> None:
        if not all(_text(value) for value in (self.fabric_id, self.network_device_id, self.interface_name)):
            raise ValueError("Trunk fabric, device, and interface identities must be nonempty text without control characters")
        if not _vlan(self.native_vlan_id):
            raise ValueError("Trunk native VLAN ID must be an integer within 1-4094")
        object.__setattr__(self, "allowed_vlan_ranges", normalize_vlan_ranges(self.allowed_vlan_ranges))

    @property
    def group(self) -> Group:
        return self.fabric_id, self.network_device_id

    def payload(self) -> dict[str, Any]:
        return {
            "fabricId": self.fabric_id,
            "networkDeviceId": self.network_device_id,
            "interfaceName": self.interface_name,
            "connectedDeviceType": "TRUNKING_DEVICE",
            "authenticateTemplateName": "No Authentication",
            "nativeVlanId": self.native_vlan_id,
            "allowedVlanRanges": self.allowed_vlan_ranges,
        }


@dataclass(frozen=True)
class TrunkPortAssignmentPlan:
    desired: TrunkPortAssignment
    action: str
    payload: dict[str, Any] | None
    observed_id: str | None


class TrunkPortAssignmentAdapter:
    """Read-first, create-only trunks with per-device batches and preservation."""

    def __init__(self, client: Any, *, trunk_observer: TrunkObserver | None = None) -> None:
        if trunk_observer is not None and not callable(trunk_observer):
            raise TypeError("trunk_observer must be callable")
        self._client = client
        self._trunk_observer = trunk_observer

    def _observed_trunk(self, group: Group, interface_name: str) -> Mapping[str, Any]:
        if self._trunk_observer is None:
            raise CatalystCenterError("Port assignment list returned missing trunk VLAN state without a supplemental observer")
        try:
            observed = self._trunk_observer(group[0], group[1], interface_name)
        except Exception as error:
            raise CatalystCenterError("Supplemental trunk observer failed") from error
        if not isinstance(observed, Mapping):
            raise CatalystCenterError("Supplemental trunk observer returned an invalid record")
        identity = (observed.get("fabricId"), observed.get("networkDeviceId"), observed.get("interfaceName"))
        if identity != (*group, interface_name) or not all(_text(value) for value in identity):
            raise CatalystCenterError("Supplemental trunk observer returned an invalid identity")
        return observed

    def _hydrate_trunk(self, record: dict[str, Any], group: Group) -> None:
        native_missing = "nativeVlanId" not in record
        allowed_missing = "allowedVlanRanges" not in record
        if not native_missing and not _vlan(record["nativeVlanId"]):
            raise CatalystCenterError("Port assignment list returned missing or invalid native VLAN")
        if not allowed_missing:
            try:
                record["allowedVlanRanges"] = normalize_vlan_ranges(record["allowedVlanRanges"])
            except ValueError as error:
                raise CatalystCenterError("Port assignment list returned missing or invalid allowed VLAN ranges") from error
        if not native_missing and not allowed_missing:
            return

        observed = self._observed_trunk(group, record["interfaceName"])
        if native_missing:
            if not _vlan(observed.get("nativeVlanId")):
                raise CatalystCenterError("Supplemental trunk observer returned missing or invalid native VLAN")
            record["nativeVlanId"] = observed["nativeVlanId"]
        elif "nativeVlanId" in observed:
            if not _vlan(observed["nativeVlanId"]) or observed["nativeVlanId"] != record["nativeVlanId"]:
                raise CatalystCenterError("Supplemental trunk observer conflicts with controller native VLAN")

        if allowed_missing:
            try:
                record["allowedVlanRanges"] = normalize_vlan_ranges(observed.get("allowedVlanRanges"))
            except ValueError as error:
                raise CatalystCenterError("Supplemental trunk observer returned missing or invalid allowed VLAN ranges") from error
        elif "allowedVlanRanges" in observed:
            try:
                observed_allowed = normalize_vlan_ranges(observed["allowedVlanRanges"])
            except ValueError as error:
                raise CatalystCenterError("Supplemental trunk observer returned missing or invalid allowed VLAN ranges") from error
            if observed_allowed != record["allowedVlanRanges"]:
                raise CatalystCenterError("Supplemental trunk observer conflicts with controller allowed VLAN ranges")

    def _records(self, group: Group) -> Records:
        rows = self._client.list_all(
            _PORT_PATH, query={"fabricId": group[0], "networkDeviceId": group[1]},
            limit=50, operation="Port assignment list",
        )
        result: Records = {}
        interfaces: set[str] = set()
        for raw in rows:
            if not isinstance(raw, dict) or (raw.get("fabricId"), raw.get("networkDeviceId")) != group:
                raise CatalystCenterError("Port assignment list returned invalid record or fabric/device scope")
            if not all(_text(raw.get(key)) for key in ("id", "interfaceName", "connectedDeviceType")):
                raise CatalystCenterError("Port assignment list returned invalid identity")
            record = deepcopy(raw)
            if record["connectedDeviceType"] == "TRUNKING_DEVICE":
                self._hydrate_trunk(record, group)
            if record["id"] in result or record["interfaceName"] in interfaces:
                raise CatalystCenterError("Port assignment list returned duplicate ID or interface")
            result[record["id"]] = record
            interfaces.add(record["interfaceName"])
        return result

    def _snapshot(self, groups: Iterable[Group]) -> dict[Group, Records]:
        snapshot = {group: self._records(group) for group in groups}
        ids = [identity for records in snapshot.values() for identity in records]
        if len(ids) != len(set(ids)):
            raise CatalystCenterError("Port assignment list returned duplicate ID across devices")
        return snapshot

    @staticmethod
    def _match(desired: TrunkPortAssignment, records: Records) -> dict[str, Any] | None:
        observed = next((record for record in records.values() if record["interfaceName"] == desired.interface_name), None)
        if observed is not None:
            for key, value in desired.payload().items():
                if key not in observed or observed[key] != value:
                    raise CatalystCenterError(f"Trunk port assignment conflicts with existing {key}")
        return observed

    def _prepare(self, desired_assignments: Iterable[TrunkPortAssignment]) -> tuple[
        tuple[TrunkPortAssignmentPlan, ...], dict[Group, Records]
    ]:
        desired = tuple(desired_assignments)
        if not all(isinstance(item, TrunkPortAssignment) for item in desired):
            raise TypeError("desired assignments must be TrunkPortAssignment instances")
        if len({(*item.group, item.interface_name) for item in desired}) != len(desired):
            raise ValueError("desired trunk fabric/device/interface identities must be unique")
        before = self._snapshot(sorted({item.group for item in desired}))
        plans = []
        for item in desired:
            observed = self._match(item, before[item.group])
            plans.append(TrunkPortAssignmentPlan(
                item, "noop" if observed else "create", None if observed else item.payload(),
                observed["id"] if observed else None,
            ))
        return tuple(plans), before

    def plan(self, desired_assignments: Iterable[TrunkPortAssignment]) -> tuple[TrunkPortAssignmentPlan, ...]:
        return self._prepare(desired_assignments)[0]

    def _verify(self, plans: tuple[TrunkPortAssignmentPlan, ...], before: dict[Group, Records], completed: set[Group]) -> dict[Group, Records]:
        actual = self._snapshot(before)
        expected_ids = {group: set(records) for group, records in before.items()}
        for group, records in before.items():
            for identity, record in records.items():
                if actual[group].get(identity) != record:
                    raise CatalystCenterError("Trunk reconciliation changed an existing controller object")
        for plan in plans:
            if plan.action == "create" and plan.desired.group not in completed:
                continue
            observed = self._match(plan.desired, actual[plan.desired.group])
            if observed is None:
                raise CatalystCenterError("Trunk port assignment did not converge in filtered readback")
            if plan.observed_id is not None and observed["id"] != plan.observed_id:
                raise CatalystCenterError("Trunk port assignment changed controller ID")
            expected_ids[plan.desired.group].add(observed["id"])
        if any(set(actual[group]) != identities for group, identities in expected_ids.items()):
            raise CatalystCenterError("Port assignment readback contains unexpected additional objects")
        return actual

    def reconcile(self, desired_assignments: Iterable[TrunkPortAssignment], *, dry_run: bool = False) -> tuple[TrunkPortAssignmentPlan, ...]:
        plans, before = self._prepare(desired_assignments)
        if dry_run:
            return plans
        completed: set[Group] = set()
        for group in before:
            creates = [plan.payload for plan in plans if plan.action == "create" and plan.desired.group == group]
            if not creates:
                continue
            response = self._client.request(
                "POST", _PORT_PATH, body=creates, operation="Trunk port assignment create",
            )
            task = self._client.task_reference(response)
            if task is None:
                raise CatalystCenterTaskError("Trunk port assignment create returned no task ID")
            status = self._client.wait_task(task)
            if (
                not isinstance(status, TaskStatus) or status.task_id != task.task_id
                or not status.completed or not status.successful or status.error
            ):
                raise CatalystCenterTaskError("Trunk port assignment create did not complete successfully")
            completed.add(group)
            before = self._verify(plans, before, completed)
        return plans
