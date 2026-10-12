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

_GLOBAL_IPAM_PATH = "/dna/intent/api/v1/ipam/globalIpAddressPools"


@dataclass(frozen=True)
class GlobalIPv4Pool:
    """Minimal immutable identity for a Catalyst Center global IPv4 pool."""

    name: str
    pool_type: str
    subnet: str
    prefix_length: int

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("global IPv4 pool name is required")
        if self.pool_type not in {"Generic", "Tunnel"}:
            raise ValueError("global IPv4 pool type must be Generic or Tunnel")
        if type(self.prefix_length) is not int or not 0 <= self.prefix_length <= 32:
            raise ValueError("global IPv4 pool prefix length must be an IPv4 prefix length")
        network = ipaddress.ip_network(f"{self.subnet}/{self.prefix_length}", strict=True)
        if network.version != 4:
            raise ValueError("global IP pool must be IPv4")
        object.__setattr__(self, "subnet", str(network.network_address))

    @property
    def prefix(self) -> str:
        return f"{self.subnet}/{self.prefix_length}"

    def payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "poolType": self.pool_type,
            "addressSpace": {"subnet": self.subnet, "prefixLength": self.prefix_length},
        }


@dataclass(frozen=True)
class GlobalIPv4PoolPlan:
    desired: GlobalIPv4Pool
    action: str
    payload: dict[str, Any] | None
    observed_id: str | None
    expected_gateway: str | None
    expected_dns_servers: tuple[str, ...]
    expected_dhcp_servers: tuple[str, ...]


class GlobalIPv4PoolAdapter:
    """Read-first, create-only reconciliation for global IPv4 pools."""

    def __init__(self, client: Any) -> None:
        self._client = client

    @staticmethod
    def _record(raw: dict[str, Any]) -> tuple[str, GlobalIPv4Pool, str | None, tuple[str, ...], tuple[str, ...]]:
        address = raw.get("addressSpace")
        if not isinstance(address, dict):
            raise CatalystCenterError("global IPv4 pool list returned invalid address space")
        try:
            pool = GlobalIPv4Pool(raw["name"], raw["poolType"], address["subnet"], address["prefixLength"])
            identity = raw["id"]
        except (KeyError, TypeError, ValueError) as error:
            raise CatalystCenterError("global IPv4 pool list returned invalid identity") from error
        gateway = address.get("gatewayIpAddress")
        dns_servers = address.get("dnsServers", [])
        dhcp_servers = address.get("dhcpServers", [])
        if (
            not isinstance(identity, str) or not identity
            or gateway is not None and (not isinstance(gateway, str) or not gateway)
            or not isinstance(dns_servers, list) or not all(isinstance(server, str) and server for server in dns_servers)
            or not isinstance(dhcp_servers, list) or not all(isinstance(server, str) and server for server in dhcp_servers)
        ):
            raise CatalystCenterError("global IPv4 pool list returned invalid metadata")
        return identity, pool, gateway, tuple(dns_servers), tuple(dhcp_servers)

    def _records(self) -> dict[str, tuple[str, GlobalIPv4Pool, str | None, tuple[str, ...], tuple[str, ...]]]:
        records = self._client.list_all(_GLOBAL_IPAM_PATH, limit=500, operation="global IPv4 pool list")
        result: dict[str, tuple[str, GlobalIPv4Pool, str | None, tuple[str, ...], tuple[str, ...]]] = {}
        ids: set[str] = set()
        names: set[str] = set()
        for raw in records:
            if not isinstance(raw, dict):
                raise CatalystCenterError("global IPv4 pool list returned invalid record")
            identity, pool, gateway, dns_servers, dhcp_servers = self._record(raw)
            if pool.prefix in result or identity in ids or pool.name in names:
                raise CatalystCenterError("global IPv4 pool list returned duplicate identity")
            result[pool.prefix] = (identity, pool, gateway, dns_servers, dhcp_servers)
            ids.add(identity)
            names.add(pool.name)
        return result

    def plan(self, desired_pools: Iterable[GlobalIPv4Pool]) -> tuple[GlobalIPv4PoolPlan, ...]:
        desired = tuple(desired_pools)
        if not all(isinstance(pool, GlobalIPv4Pool) for pool in desired):
            raise TypeError("desired pools must be GlobalIPv4Pool instances")
        if len({pool.name for pool in desired}) != len(desired):
            raise ValueError("desired global IPv4 pool names must be unique")
        if len({pool.prefix for pool in desired}) != len(desired):
            raise ValueError("desired global IPv4 pool prefixes must be unique")
        existing = self._records()
        existing_networks = [ipaddress.ip_network(prefix) for prefix in existing]
        plans: list[GlobalIPv4PoolPlan] = []
        for pool in desired:
            found = existing.get(pool.prefix)
            if found is not None:
                identity, observed, gateway, dns_servers, dhcp_servers = found
                if observed.name != pool.name or observed.pool_type != pool.pool_type:
                    raise CatalystCenterError(f"global IPv4 pool {pool.prefix} has immutable identity conflict")
                plans.append(GlobalIPv4PoolPlan(pool, "noop", None, identity, gateway, dns_servers, dhcp_servers))
                continue
            if any(observed.name == pool.name for _, observed, _, _, _ in existing.values()):
                raise CatalystCenterError(f"global IPv4 pool name {pool.name} already belongs to another prefix")
            network = ipaddress.ip_network(pool.prefix)
            if any(network.overlaps(other) for other in existing_networks) or any(
                network.overlaps(ipaddress.ip_network(plan.desired.prefix)) for plan in plans
            ):
                raise CatalystCenterError(f"global IPv4 pool {pool.prefix} overlaps an existing or desired pool")
            plans.append(GlobalIPv4PoolPlan(pool, "create", pool.payload(), None, None, (), ()))
        return tuple(plans)

    def reconcile(self, desired_pools: Iterable[GlobalIPv4Pool], *, dry_run: bool = False) -> tuple[GlobalIPv4PoolPlan, ...]:
        plans = self.plan(desired_pools)
        if dry_run or all(plan.action == "noop" for plan in plans):
            return plans
        for plan in plans:
            if plan.action != "create":
                continue
            response = self._client.request("POST", _GLOBAL_IPAM_PATH, body=plan.payload, operation="global IPv4 pool create")
            task = self._client.task_reference(response)
            if task is None:
                raise CatalystCenterTaskError("global IPv4 pool create returned no task ID")
            self._client.wait_task(task)

        actual = self._records()
        for plan in plans:
            found = actual.get(plan.desired.prefix)
            if found is None:
                raise CatalystCenterError(f"global IPv4 pool {plan.desired.prefix} did not converge")
            identity, pool, gateway, dns_servers, dhcp_servers = found
            if plan.observed_id is not None and identity != plan.observed_id:
                raise CatalystCenterError(f"global IPv4 pool {plan.desired.prefix} changed controller ID")
            if pool.name != plan.desired.name or pool.pool_type != plan.desired.pool_type:
                raise CatalystCenterError(f"global IPv4 pool {plan.desired.prefix} changed immutable identity")
            if (gateway, dns_servers, dhcp_servers) != (plan.expected_gateway, plan.expected_dns_servers, plan.expected_dhcp_servers):
                raise CatalystCenterError(f"global IPv4 pool {plan.desired.prefix} changed optional allocation metadata")
        return plans