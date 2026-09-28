# Read-only network acceptance validation

`eve validate LAB` evaluates the `validation` list in `labs/LAB/topology.yaml`.
It uses the existing EVE API discovery, verified SSH host connection, Telnet
console transport and `CISCO_*` authentication. There is one console session
per checked node. No device initialization, remediation, configuration save,
protocol clear, interface bounce, node restart or topology write is invoked.
`terminal length 0` changes only session pagination; ping sends probe traffic.

Every check requires `name`, `type` and `node`. Names must be unique. Checks
are required unless the human explicitly sets `required: false`. An optional
failure remains a failed check in the report but does not fail the overall
result. A required failure produces overall `result: fail` and CLI exit 1.
Invalid definitions and transport errors also cause a nonzero exit.

The existing interface/ping fields, defaults, evidence and two-attempt ping
behavior remain unchanged. The baseline lab has not been expanded.

## Implemented scope

Only the existing `c8000v` template is currently enabled for this validation path.
Other templates fail before console access. This is not a claim of support for
IOS XR, NX-OS, other vendors, or other IOS XE templates.

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

