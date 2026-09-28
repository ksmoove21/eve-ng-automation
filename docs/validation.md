# Read-only network acceptance validation

`eve validate LAB` evaluates the `validation` list in `labs/LAB/topology.yaml`.
It uses the existing EVE API discovery, verified SSH host connection, Telnet
console transport and `CISCO_*` authentication. There is one console session
per checked node. No device initialization, remediation, configuration save,
protocol clear, interface bounce, node restart or topology write is invoked.
`terminal length 0` changes only session pagination; ping sends probe traffic.

Every check requires `name`, `type` and `node`. Names must be unique. Checks
are required unless the human explicitly sets `required: false`. An optional
assertion mismatch remains a failed check in the report but does not fail the
overall result. A required assertion mismatch produces overall `result: fail`
and CLI exit 1. Node-level execution failures are independent of assertion
optionality: transport/session failure, configuration retrieval failure, or
failure to parse the collected configuration always fails the overall run and
is reported with `failure_kind: execution`. Invalid definitions also cause a
nonzero exit.

The existing interface/ping fields, defaults, evidence and two-attempt ping
behavior remain unchanged. The baseline lab has not been expanded.

## Implemented scope

`c8000v` remains enabled through the IOS XE adapter in
`src/eve_lab/validation_iosxe.py`. Palo Alto firewall nodes using the
`paloalto` template are also enabled through
`src/eve_lab/validation_panos.py` for committed-configuration assertions.
Panorama is intentionally not registered for validation. NX-OS, IOS XR and
other templates still fail preflight until explicit adapters are added.

| Type | Required fields beyond name/type/node | Optional fields |
| --- | --- | --- |
| `interface` | `interface` | `address`, `state` (default `up`) |
| `ping` | `destination` | `min_success_rate` (default 100) |
| `route` | `prefix`, `expected` | `vrf`, `next_hop` |
| `default-route` | `expected` | `vrf` |
| `bgp-neighbor` | `neighbor`, `state` | `vrf`, `address_family` |
| `ospf-neighbor` | `neighbor`, `state` | none |
| `isis-adjacency` | `neighbor`, `state` | none |
| `vrf-ping` | `vrf`, `destination` | `min_success_rate` (default 100) |
| `mtu-ping` | `destination`, `packet_size`, `df` | `min_success_rate` (default 100) |

All types additionally accept the common `required` boolean. Unknown fields,
wrong types, unsupported scopes and command-injection characters are rejected.
Definitions are never rewritten to match observations.

- Routes are IPv4 only, with canonical CIDR prefixes, for example
  `192.0.2.0/24`. Host bits and netmask notation are rejected. `expected` is
  explicitly `present` or `absent`. `default-route` means `0.0.0.0/0`.
  A covering route is not the requested exact prefix. `next_hop` is an IPv4
  address and applies only to a present route; any matching ECMP next hop
  satisfies it. Directly connected routes have no numeric next hop.
- BGP `address_family` is `ipv4-unicast` (default) or `ipv6-unicast`.
  Neighbor address version must match. Global queries use the scoped
  `show bgp ipv4|ipv6 unicast summary`; VRF queries use
  `show bgp vpnv4|vpnv6 unicast vrf NAME summary` to inspect that VRF's unicast
  peers. VPN AF acceptance, multicast and cross-family transport are not
  implemented. States are `idle`, `connect`, `active`, `opensent`,
  `openconfirm`, `established` (case insensitive). A numeric received-prefix
  count, including zero, means established. Administrative annotations are
  retained in evidence; `Idle (Admin)` has state `idle`.
- OSPF covers the global IPv4 neighbor table. `neighbor` matches a router ID
  or neighbor interface address. States are `down`, `attempt`, `init`,
  `2way`, `exstart`, `exchange`, `loading`, `full` (case insensitive).
  DR/BDR roles remain evidence, not adjacency-state requirements.
- IS-IS matches the displayed neighbor name or a dotted six-byte system ID
  such as `0000.0000.0002`. Numeric expectations resolve dynamic names using
  the read-only `show isis hostname` table when needed. Ambiguous mappings
  fail. States are `up`, `down`, `init` (case insensitive). All observed
  matching interfaces/levels must agree with the declared state.
- For every protocol, no matching row is a failure, even when expecting
  `down` or `idle`. Missing adjacency is not evidence of a particular state.
  Multi-process/multi-topology IS-IS output is not implemented.
- New ping primitives require literal IPv4 destinations. Rates are integers
  from 0 through 100. They send five probes, with a two-second per-probe
  timeout and a 30-second command timeout. A second attempt is allowed if
  the first misses the threshold, preserving the existing ping retry policy.
  Evidence retains each attempt and the best rate. Unparseable responses
  always fail, including when the threshold is zero.
- `packet_size` is the complete IP datagram size in bytes, not ICMP payload
  size, and must be an integer from 36 through 18024. `df: true` sends
  `df-bit`; `df: false` omits it, permitting fragmentation. An MTU check
  measures reachability at the declared size/DF setting; it does not discover
  an exact path MTU. Combining VRF and MTU scopes is not implemented.
- VRF names must be single CLI tokens using letters, digits, underscores,
  dots or hyphens. They must start with a letter, digit or underscore.

Parsers require recognized headers/rows or the explicit IOS route-not-in-table
response. Command errors, unknown formats and detected pagination/truncation
fail with reasons; they do not prove route absence. Evidence contains parsed
observations, expected criteria and generated commands, without raw console
transcripts or credentials. Session-open failures give failure evidence for
all checks on that node. Host SSH failures remain top-level errors.

## Example acceptance intent

These documentation addresses are independent of the baseline lab. The node
must already exist in the containing topology; no deployment is implied.

```yaml
validation:
  - {name: subnet, type: route, node: edge, prefix: 192.0.2.0/24, expected: present, next_hop: 198.51.100.1}
  - {name: no-default, type: default-route, node: edge, vrf: BLUE, expected: absent}
  - {name: bgp, type: bgp-neighbor, node: edge, neighbor: 198.51.100.1, state: established, address_family: ipv4-unicast}
  - {name: ospf, type: ospf-neighbor, node: edge, neighbor: 203.0.113.1, state: full}
  - {name: isis, type: isis-adjacency, node: edge, neighbor: '0000.0000.0002', state: up}
  - {name: tenant-ping, type: vrf-ping, node: edge, vrf: BLUE, destination: 192.0.2.10, min_success_rate: 100}
  - {name: path-mtu, type: mtu-ping, node: edge, destination: 192.0.2.10, packet_size: 1500, df: true, min_success_rate: 100}
```

## Console safety and compatibility

Validation opts into read-only login. It refuses initial setup, enable-secret
creation/save and configuration-mode prompts. Initialization retains its
previous default login behavior. Validation requests Ctrl-R prompt redisplay
instead of submitting an initial Enter, so a pending command or setup default
is not submitted. It also disables periodic Enter wakeups. A console that
cannot safely redisplay a recognizable prompt fails by timeout; validation
never falls back to setup or configuration repair.

See Cisco's [IOS XE CLI editing reference](https://www.cisco.com/c/en/us/td/docs/routers/ios-xe/system-management/system-management/m_cf-cli-basics.html)
for prompt redisplay, [routing command reference](https://www.cisco.com/c/en/us/td/docs/ios/iproute_pi/command/reference/iri_book/iri_pi2.html),
[BGP command reference](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/iproute_bgp/command/irg-cr-book/bgp-n1.html),
[OSPF reference](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/iproute_ospf/command/iro-cr-book/ospf-s1.html),
[IS-IS reference](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/iproute_isis/command/irs-cr-book/irs-l1.html)
and [ping reference](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/fundamentals/command/cf_command_ref/monitor_event-trace_through_Q.html).
Command references inform implementation; they do not replace image-specific
live verification.

## Offline and live verification

Run from the repository root on Windows PowerShell, macOS or Linux:

```text
python -m unittest discover -s tests -p "test_validation*.py" -v
python -m unittest discover -s tests -p test_device_console.py -v
```

The fixtures are synthetic and all API/SSH calls in runner tests are mocked.
No new controller OS assumptions or dependencies are introduced.

Still requires separately authorized live verification on the target C8000V
IOS XE image and EVE-NG console path:

1. Ctrl-R prompt redisplay, credential/enable authentication, rejection of
   setup/configuration-mode prompts and safe failure with pending input.
2. Existing baseline interface/ping results and JSON/exit-status behavior.
3. Exact route presence/absence, default routes, connected and ECMP routes,
   next-hop mismatches and nonexistent VRFs in global and VRF scopes.
4. BGP summary syntax/output for IPv4/IPv6 unicast globally and in VRFs,
   including established (zero prefixes), idle and administrative shutdown.
5. OSPF router-ID/address matching, point-to-point and broadcast roles,
   multiple adjacencies and missing/wrong states.
6. IS-IS L1/L2 adjacency tables and dynamic hostname/system-ID resolution,
   including missing/wrong states and duplicate-hostname rejection.
7. VRF ping reachability and MTU probes with DF on/off at passing/failing
   sizes, verifying the target image's packet-size semantics and counters.
8. Session pagination, timeouts, cleanup, one connection per checked node,
   required versus explicitly optional failure behavior and nonzero exits.

Use a separate focused lab for new live cases; do not expand the baseline
merely to exercise all types. No live EVE operation was performed for this work.


## PAN-OS firewall validation

PAN-OS validation uses the firewall management plane rather than the EVE serial
console. The controller first connects to the EVE host over SSH, then opens a
`direct-tcpip` tunnel to the firewall management address declared in
`labs/LAB/init.yaml`. Device authentication uses `PALO_USERNAME` and
`PALO_PASSWORD`. This EVE-tunneled path is currently the only implemented
PAN-OS validation transport. The validator does not silently fall back to a
direct controller connection. The firewall SSH key must be present in the
controller trust store. A new key may be enrolled only with explicit owner
authorization for that exact address through the verified EVE connection; a
changed saved key is never accepted automatically.

The validator reuses the existing read-only running-config workflow:

```text
set cli pager off
set cli op-command-xml-output on
show config running
set cli op-command-xml-output off
```

It parses the returned committed XML once per firewall and evaluates all
declared checks locally. It does not enter configuration mode, modify candidate
configuration, commit, clear sessions or alter runtime state.

Supported PAN-OS types in this first slice:

| Type | Required fields | Optional fields |
| --- | --- | --- |
| `panos-interface` | `interface` | `address`, `expected` |
| `panos-zone-interface` | `zone`, `interface` | `vsys`, `expected` |
| `panos-virtual-router-interface` | `virtual_router`, `interface` | `expected` |
| `panos-route` | `destination` | `virtual_router`, `next_hop`, `expected` |
| `panos-security-rule` | `rule` | `vsys`, `expected` |
| `panos-nat-rule` | `rule` | `vsys`, `expected` |

`expected` defaults to `present`. `vsys` defaults to `vsys1`, and
`virtual_router` defaults to `default` for route checks. Route checks in
this slice inspect committed IPv4 static routes. Dynamic routing state, runtime
interface state, session/policy counters and packet probes remain future live
validation work.

Example:

```yaml
validation:
  - name: outside-address
    type: panos-interface
    node: PA1
    interface: ethernet1/1
    address: 198.51.100.1/30
    expected: present

  - name: outside-zone
    type: panos-zone-interface
    node: PA1
    zone: OUTSIDE
    interface: ethernet1/1
    expected: present

  - name: outside-vr
    type: panos-virtual-router-interface
    node: PA1
    virtual_router: default
    interface: ethernet1/1
    expected: present

  - name: default-route
    type: panos-route
    node: PA1
    destination: 0.0.0.0/0
    next_hop: 198.51.100.2
    expected: present

  - name: allow-test
    type: panos-security-rule
    node: PA1
    rule: ALLOW-TEST
    expected: present
```

The corresponding private workspace must provide:

```yaml
# labs/LAB/init.yaml
PA1:
  management_ip: 192.0.2.10
```

The management IP is environment/runtime data and need not be committed to a
public engine repository. It must be the firewall's current management address
as reachable from the EVE host. A DHCP-learned address may be placed in the
private workspace temporarily for live validation, but it is not a durable
static management design and may need to be refreshed after a lease change.

A stale management address is an input error, not evidence that the
`direct-tcpip` transport architecture is defective. Direct controller-to-firewall
SSH is not implemented. If it is added later, transport selection must be an
explicit validated workspace field; the validator must not probe and silently
fall back between direct and EVE-tunneled paths.

If management SSH cannot be established, running configuration cannot be
retrieved, or the returned XML cannot be parsed, no assertion was actually
evaluated. These execution failures make the overall validation result `fail`
even when every declared check for that firewall has `required: false`.

## NX-OS / Nexus 9000v validation

`nxosv9k` and `nxosv9k-9300v` nodes use the existing verified EVE-host SSH and
Telnet-console path with the existing `CISCO_USERNAME`, `CISCO_PASSWORD`, and
`CISCO_ENABLE_SECRET` credential source. Read-only login safety is unchanged.
The supported machine-readable checks are `nxos-interface`, `nxos-vlan`,
`nxos-vrf`, `nxos-route`, `nxos-ping`, `nxos-vpc`, `nxos-port-channel`, and
`nxos-bgp-neighbor`. All accept `required: false` under the same assertion and
execution-failure rules described above.

```yaml
validation:
  - {name: uplink, type: nxos-interface, node: leaf1, interface: Ethernet1/1, admin_state: up, oper_state: up}
  - {name: tenant, type: nxos-vlan, node: leaf1, vlan: 10, state: active}
  - {name: vrf, type: nxos-vrf, node: leaf1, vrf: BLUE}
  - {name: route, type: nxos-route, node: leaf1, prefix: 192.0.2.0/24, expected: present, next_hop: 198.51.100.1}
  - {name: reach, type: nxos-ping, node: leaf1, destination: 192.0.2.2, vrf: BLUE}
  - {name: vpc, type: nxos-vpc, node: leaf1, state: up, peer_state: up, peer_link_state: up, consistency: up}
  - {name: po, type: nxos-port-channel, node: leaf1, port_channel: Po1, oper_state: up, members: [Eth1/1, Eth1/2]}
  - {name: bgp, type: nxos-bgp-neighbor, node: leaf1, neighbor: 192.0.2.2, state: established}
```

These parsers deliberately fail closed on pagination, CLI errors, malformed or
unrecognized output. They cover IPv4 routes and IPv4/IPv6-unicast BGP summary
syntax only. EVPN, VXLAN, NVE and VTEP assertions are intentionally deferred
until image-specific output is verified live.

NX-OS bootstrap is intentionally separate from validation. The immediate
implementation seam is the generic `initialize()` template registry and its
Cisco console implementation: add an NX-OS console initializer that owns
configuration mode and save verification, with private lab files supplying
hostname, management address/prefix, gateway and boot image. It must reuse
`CISCO_*` credentials. The current generic Cisco initializer uses IOS-XE
command and `write memory` semantics, so this validation change does not
pretend it can safely bootstrap NX-OS.
