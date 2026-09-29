# Catalyst 9000v UADP

The reusable engine supports the EVE-NG template ID `cat9kvuadp` through a
dedicated structured initializer and read-only validation adapter. Do not use
the display-name spelling `cat9kv-uadp` in topology `template` fields.

## EVE and image boundary

The target EVE template exposes `GigabitEthernet0/0` as the management
interface and `GigabitEthernet1/0/N` as data interfaces. The target server's
template defaults are 4 vCPU, 18432 MiB RAM, 25 Ethernet interfaces, and a
Telnet serial console. The current integration image is
`cat9kvuadp-17.15.01`; other releases require their own live verification.

First boot is resource-intensive and can take many minutes. EVE reporting a
running QEMU process is not guest readiness. Use a bounded `eve init --timeout`
window and inspect both the guest console and QEMU state before deciding that a
long first boot has failed.

On the live-tested 17.15.01 image, the first licensing reload can select a GRUB
`packages.conf` entry that verifies its hash but fails with `invalid magic
number`. When that exact failure and the explicit two-entry GRUB menu are
observed, the Cat9Kv reload path selects `VNGWC - GOLDEN IMAGE` once and
continues bounded console reacquisition. It does not guess at other bootloader
failures or apply this recovery to other templates.

## Structured initialization

Files named `configs/NODE-init.yaml` use schema version 1. The required
`dnac-bootstrap` profile owns management and Catalyst Center prerequisites. The
optional `ospf-underlay` profile requires `dnac-bootstrap` and explicit
underlay intent.

```yaml
schema_version: 1
profiles: [dnac-bootstrap, ospf-underlay]
hostname: C9K-1
domain_name: lab.example
management:
  source: context/management-addressing.yaml
  allocation_id: catalyst-lab
  logical_device_id: catalyst-lab/C9K-1
dnac:
  snmp_ro_env: CAT9KV_SNMP_RO_COMMUNITY
  snmp_rw_env: CAT9KV_SNMP_RW_COMMUNITY
  rsa_modulus: 2048
  license:
    network: network-advantage
    dna: dna-advantage
underlay:
  ospf:
    process_id: 100
    router_id: 192.0.2.1
  loopback:
    interface: Loopback0
    address: 192.0.2.1/32
    ospf_area: 0
  routed_interfaces:
    - interface: GigabitEthernet1/0/1
      address: 198.51.100.1/30
      ospf_area: 0
      network_type: point-to-point
```

The management source must be a workspace-relative YAML path that stays inside
the selected `--root`. It must contain `approved_pools` and `allocations`; the
allocation and logical-device IDs must resolve exactly once. The engine derives
the address, prefix length, and gateway from that registry rather than from
sample defaults in reusable code.

Device login continues to use `CISCO_USERNAME`, `CISCO_PASSWORD`, and
`CISCO_ENABLE_SECRET`. SNMP communities are separate runtime secrets named by
the structured intent and normally stored in the workspace's gitignored
`.env`. Community values are never placed in topology or init YAML.

The DNAC profile configures:

- hostname and domain name;
- local AAA with console authorization, a privilege-15 user that enters the
  privileged exec directly after login, and an enable secret retained for
  recovery rather than normal login;
- SSH version 2 and an RSA key when one does not already exist;
- NETCONF/YANG;
- one RO and one RW SNMP community;
- `GigabitEthernet0/0` in `Mgmt-vrf`, with a VRF default route;
- console and VTY session behavior suitable for automation; and
- the declared Network and DNA license tiers.

The underlay profile enables IP routing, assigns the declared loopback and
routed `GigabitEthernet1/0/N` interfaces, makes routed links OSPF
point-to-point, and uses passive-by-default OSPF with only declared routed
uplinks made active.

## Save, license, and reload behavior

Initialization checks the current and next-boot technology-package state,
applies configuration, generates RSA keys only when absent, and requires a
successful `write memory` confirmation. A license change triggers one
controlled reload only when the desired tier is not already current. The
initializer reacquires the console after the reload and fails unless both
declared licenses become current. An idempotent rerun does not reload merely
because the license command is present in the profile.

## Read-only validation

Two composite validation types are available:

```yaml
validation:
  - name: bootstrap-ready
    type: cat9kv-dnac-bootstrap
    node: C9K-1
  - name: underlay-ready
    type: cat9kv-underlay
    node: C9K-1
    neighbors:
      - {neighbor: 192.0.2.2, state: full}
```

`cat9kv-dnac-bootstrap` reports `DNAC_BOOTSTRAP_READY` only when the declared
identity, AAA/privilege, SSH, NETCONF, SNMP modes, RSA key, management state,
default route, licensing, and EVE-host TCP probes for ports 22 and 830 all
pass. Evidence records only the existence and modes of SNMP configuration, not
community values.

`cat9kv-underlay` reports `UNDERLAY_READY` after node-local interface and OSPF
intent passes. Neighbors are required only when the topology explicitly lists
them; this permits single-node staging without inventing an adjacency.

Both validators are read-only. They do not generate keys, enable services,
alter licensing, repair configuration, save, reload, or weaken declared
acceptance criteria.

Serial-console reads are validated strictly. The adapter retries an interface
configuration query once when the console returns no matching stanza, then
fails closed if the second response is also incomplete. Operational interface
state is never substituted for the declared running configuration.

## Current limitations

- Catalyst Center discovery/onboarding itself is outside this engine; the
  readiness state proves device prerequisites and management service reachability.
- Smart Licensing registration and entitlement consumption are external to
  the boot-level configuration checked here.
- Only IPv4 management and an IPv4 OSPF underlay are implemented.
- Data interfaces are intentionally limited to `GigabitEthernet1/0/N`, and
  routed OSPF links are point-to-point in this profile.
- Backup/restore has not received Cat9Kv-specific live qualification.
- The live integration host repeatedly placed otherwise healthy Cat9Kv QEMU
  processes in a stopped state. That is an EVE/QEMU host condition outside the
  engine; an operator must diagnose or resume the affected process before a
  bounded initialization or validation run can make progress.
