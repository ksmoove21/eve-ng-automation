# IOS-XE KG behavioral profile

The `kg-ipsec` init profile represents a KG semantic role on the existing
`c8000v` execution platform. It does not implement KG175F hardware, Type 1
cryptography, HAIPE interoperability, classified operation, or an accredited
security boundary. It uses commercial IKEv2/IPsec to exercise a routing boundary.

Ciphertext interfaces and peer reachability use the global routing table.
Plaintext interfaces and the protected static VTI use the case-sensitive VRF
`Red`. RIP v2 runs only within that address family, inherits global passive-by-default interface policy, and
sends updates over the protected tunnel. Explicit PT static routes can be
exported using a prefix-list and route-map; CT routes are never redistributed.

A C8000V node may use `configs/NODE-init.yaml` with `profile: kg-ipsec` instead
of a raw init CFG. Required keys are `hostname`, `ct`, `pt`, `tunnel`, `psk_env`,
and `routes`. CT contains `interface`, `address` (host/prefix), and `peer`.
PT and tunnel contain `interface` and `address`. Routes is a list of
`prefix` and PT `next_hop` mappings (or an empty list). CT peers must be directly
attached; this first profile intentionally does not model a transport network.
The remote PT interface may be a loopback for a minimal remote peer.

The PSK is resolved from the existing environment/.env mechanism and never
stored in the init definition. Use 24-128 alphanumeric, underscore or hyphen
characters. The renderer rejects overlapping CT/PT/VTI networks, duplicate
interfaces, invalid CLI tokens, and routes overlapping the transport.

An image with a blank boot license level does not expose the crypto commands.
The profile selects Network Essentials plus DNA Essentials, saves, reloads once,
and verifies the active boot tier. It does not register a Smart Account, install
entitlements, or contact a license server. Existing nonempty tiers are preserved.
License entitlements and export-controlled high-throughput capabilities remain
outside this lab profile.

## Acceptance

`kg-boundary` requires `ct_interface`, `ct_peer`, `ct_prefix`, `pt_interface`,
`tunnel`, `remote_prefixes`, `local_prefixes`, `pt_source`, and `pt_destination`. It reports
separate CT, VRF interface isolation, VTI, IKE, IPsec, RIP, route isolation, and
PT reachability evidence. All must pass. A learned route must report RIP as its
source; accepted configuration is insufficient. IPsec requires active inbound
and outbound SAs and nonzero encapsulation/decapsulation counters.

The validator issues only show commands and bounded ping probes. Missing,
unsupported, or incomplete output fails closed. It never applies configuration,
clears security associations, or repairs a routing failure. A failed layer is
reported in `failed_layers`.

## EVE visual identity and runtime

The optional topology node `icon` field is the exact filename advertised by the
selected EVE template's `options.icon.list`. Preflight rejects unadvertised
icons. This is generic visual configuration, independent of execution platform.
Node creation and stopped-node reconciliation enforce `cpulimit=0`, overriding
template defaults. Running nodes retain the existing deferred-update policy.

## Sources

- [Cisco VRF-aware static VTI](https://www.cisco.com/c/en/us/support/docs/security-vpn/ipsec-architecture-implementation/214938-configuring-ikev2-vrf-aware-svti.html)
- [Cisco RIP command reference](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/iproute_rip/command/irr-cr-book/irr-cr-rip.html)
- [Cisco C8000V boot license configuration](https://www.cisco.com/c/en/us/support/docs/ios-nx-os-software/ios-xe-17/217047-enable-license-boot-level-and-addon-on-c.html)

Live qualification results belong in the lessons log; offline tests alone do
not establish interoperability with an installed image.
