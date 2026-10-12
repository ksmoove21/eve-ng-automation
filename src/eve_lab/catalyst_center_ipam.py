"""Create-only IPv4 site IPAM reservation reconciliation for Catalyst Center."""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any, Iterable

from .catalyst_center import CatalystCenterError, CatalystCenterTaskError

_IPAM_PATH = "/dna/intent/api/v1/ipam/siteIpAddressPools"


@dataclass(frozen=True)
class IPv4Reservation:
    name: str
    pool_type: str
    site_id: str
    subnet: str
    prefix_length: int
    global_pool_id: str
    gateway_ip_address: str | None = None

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (self.name, self.pool_type, self.site_id, self.subnet, self.global_pool_id)):
            raise ValueError("IPAM reservation name, pool type, site ID, subnet, and global pool ID are required")
        if type(self.prefix_length) is not int or not 0 <= self.prefix_length <= 32:
            raise ValueError("IPAM reservation prefix length must be an IPv4 prefix length")
        network = ipaddress.ip_network(f"{self.subnet}/{self.prefix_length}", strict=True)
        if network.version != 4:
            raise ValueError("IPAM reservation must be IPv4")
        if self.gateway_ip_address is not None:
            gateway = ipaddress.ip_address(self.gateway_ip_address)
            if gateway.version != 4 or gateway not in network or gateway in (network.network_address, network.broadcast_address):
                raise ValueError("IPAM reservation gateway must be a usable IPv4 address in the subnet")
        object.__setattr__(self, "subnet", str(network.network_address))

    @property
    def prefix(self) -> str:
        return f"{self.subnet}/{self.prefix_length}"

    def payload(self) -> dict[str, Any]:
        address_space: dict[str, Any] = {
            "subnet": self.subnet,
            "prefixLength": self.prefix_length,
            "globalPoolId": self.global_pool_id,
        }
        if self.gateway_ip_address is not None:
            address_space["gatewayIpAddress"] = self.gateway_ip_address
        return {"ipV4AddressSpace": address_space, "name": self.name, "poolType": self.pool_type, "siteId": self.site_id}


@dataclass(frozen=True)
class IPv4ReservationPlan:
    desired: IPv4Reservation
    action: str
    payload: dict[str, Any] | None
    observed_id: str | None
    expected_name: str


class IPv4ReservationAdapter:
    """Read-first, create-only reconciliation for site IPv4 address subpools."""

    def __init__(self, client: Any) -> None:
        self._client = client

    @staticmethod
    def _record(record: dict[str, Any]) -> tuple[str, str, str, str, str, str | None, str]:
        address = record.get("ipV4AddressSpace")
        if not isinstance(address, dict):
            raise CatalystCenterError("IPAM reservation list returned invalid IPv4 address space")
        try:
            reservation = IPv4Reservation(
                record["name"], record["poolType"], record["siteId"], address["subnet"], address["prefixLength"], address["globalPoolId"], address.get("gatewayIpAddress")
            )
            identity = record["id"]
        except (KeyError, TypeError, ValueError) as error:
            raise CatalystCenterError("IPAM reservation list returned invalid identity") from error
        if not isinstance(identity, str) or not identity:
            raise CatalystCenterError("IPAM reservation list returned invalid ID")
        return identity, reservation.site_id, reservation.prefix, reservation.global_pool_id, reservation.pool_type, reservation.gateway_ip_address, reservation.name

    def _records(self) -> dict[tuple[str, str], tuple[str, str, str, str, str | None, str]]:
        records = self._client.list_all(_IPAM_PATH, limit=500, operation="IPAM reservation list")
        result: dict[tuple[str, str], tuple[str, str, str, str, str | None, str]] = {}
        ids: set[str] = set()
        names: set[str] = set()
        for raw in records:
            if not isinstance(raw, dict):
                raise CatalystCenterError("IPAM reservation list returned invalid record")
            identity, site, prefix, global_pool, pool_type, gateway, name = self._record(raw)
            key = (site, prefix)
            if key in result or identity in ids or name in names:
                raise CatalystCenterError("IPAM reservation list returned duplicate identity")
            result[key] = (identity, global_pool, pool_type, gateway, name, prefix)
            ids.add(identity)
            names.add(name)
        return result

    @staticmethod
    def _validate_existing(desired: IPv4Reservation, existing: tuple[str, str, str, str | None, str, str]) -> None:
        _, global_pool, pool_type, gateway, _, _ = existing
        if global_pool != desired.global_pool_id or pool_type != desired.pool_type:
            raise CatalystCenterError(f"IPAM reservation {desired.site_id} {desired.prefix} has immutable identity conflict")
        if gateway != desired.gateway_ip_address:
            raise CatalystCenterError(f"IPAM reservation {desired.site_id} {desired.prefix} has gateway conflict")

    def plan(self, desired_reservations: Iterable[IPv4Reservation]) -> tuple[IPv4ReservationPlan, ...]:
        desired = tuple(desired_reservations)
        if not all(isinstance(reservation, IPv4Reservation) for reservation in desired):
            raise TypeError("desired reservations must be IPv4Reservation instances")
        if len({reservation.name for reservation in desired}) != len(desired):
            raise ValueError("desired IPAM reservation names must be unique")
        if len({(reservation.site_id, reservation.prefix) for reservation in desired}) != len(desired):
            raise ValueError("desired IPAM reservation site/prefix identities must be unique")
        existing = self._records()
        existing_networks = [(site, ipaddress.ip_network(prefix)) for (site, prefix) in existing]
        plans: list[IPv4ReservationPlan] = []
        for reservation in desired:
            key = (reservation.site_id, reservation.prefix)
            found = existing.get(key)
            if found is None and any(existing_name == reservation.name for _, _, _, _, existing_name, _ in existing.values()):
                raise CatalystCenterError(f"IPAM reservation name {reservation.name} already belongs to another allocation")
            if found is not None:
                self._validate_existing(reservation, found)
                plans.append(IPv4ReservationPlan(reservation, "noop", None, found[0], found[4]))
                continue
            network = ipaddress.ip_network(reservation.prefix)
            if any(network.overlaps(other) for _, other in existing_networks) or any(
                network.overlaps(ipaddress.ip_network(plan.desired.prefix)) for plan in plans
            ):
                raise CatalystCenterError(f"IPAM reservation {reservation.site_id} {reservation.prefix} overlaps an existing or desired reservation")
            plans.append(IPv4ReservationPlan(reservation, "create", reservation.payload(), None, reservation.name))
        return tuple(plans)

    def reconcile(self, desired_reservations: Iterable[IPv4Reservation], *, dry_run: bool = False) -> tuple[IPv4ReservationPlan, ...]:
        plans = self.plan(desired_reservations)
        if dry_run or all(plan.action == "noop" for plan in plans):
            return plans
        for plan in plans:
            if plan.action != "create":
                continue
            response = self._client.request("POST", _IPAM_PATH, body=plan.payload, operation="IPAM reservation create")
            task = self._client.task_reference(response)
            if task is None:
                raise CatalystCenterTaskError("IPAM reservation create returned no task ID")
            self._client.wait_task(task)

        actual = self._records()
        for plan in plans:
            found = actual.get((plan.desired.site_id, plan.desired.prefix))
            if found is None:
                raise CatalystCenterError(f"IPAM reservation {plan.desired.site_id} {plan.desired.prefix} did not converge")
            identity, global_pool, pool_type, gateway, name, _ = found
            if plan.observed_id is not None and identity != plan.observed_id:
                raise CatalystCenterError(f"IPAM reservation {plan.desired.site_id} {plan.desired.prefix} changed controller ID")
            if global_pool != plan.desired.global_pool_id or pool_type != plan.desired.pool_type or gateway != plan.desired.gateway_ip_address:
                raise CatalystCenterError(f"IPAM reservation {plan.desired.site_id} {plan.desired.prefix} changed allocation")
            if name != plan.expected_name:
                raise CatalystCenterError(f"IPAM reservation {plan.desired.site_id} {plan.desired.prefix} changed display name")
        return plans
