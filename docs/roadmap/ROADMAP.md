# EVE-NG Automation Roadmap

This fork extends `wcmder/eve-ng` into a reusable network-lab automation platform while preserving the explicit topology and lifecycle model that makes labs predictable and repeatable.

## Goal

Make it possible to describe a lab, deploy it to an existing EVE-NG server, initialize supported devices, and verify that the resulting network satisfies declared acceptance criteria.

The engine remains usable as a normal CLI and does not depend on any particular AI tool, hosting platform, or private environment.

## Current foundation

The project currently provides:

- declarative EVE-NG topology definitions
- topology reconciliation through `eve apply`
- node lifecycle operations
- device initialization
- backup and restore workflows
- reusable public lab fixtures
- read-only IOS XE, NX-OS, Catalyst 9000v UADP, and PAN-OS validation
- reusable KG behavioral and protected-path validation
- Windows, Linux, and macOS controller support
- separate public engine and private workspace support

## Platform support

Expand device support beyond the currently proven platforms.

Planned targets include:

- Cisco IOSv and IOSvL2
- MikroTik CHR
- additional IOS XE variants
- additional firewall and network-platform integrations where practical

Platform support may include topology handling, interface normalization, initialization, configuration persistence, backup/restore, and validation capabilities as appropriate for that platform.

## Reusable lab services

Reduce repetitive per-lab configuration through reusable services such as:

- IPv4 and IPv6 address allocation
- loopback allocation
- point-to-point subnet generation
- ASN allocation
- device-role defaults
- common management configuration
- configuration rendering
- platform-aware interface mapping

These capabilities should remain independent of any specific private environment.

## Network feature support

Expand reusable support for commonly tested network behaviors, including:

- BGP and routing policy
- OSPF
- IS-IS
- VRFs
- MPLS and LDP
- MP-BGP L3VPN
- GRE
- NAT
- MTU and MSS behavior

Where possible, lab definitions should describe the desired network behavior without requiring every platform to use identical configuration syntax.

## Validation and readiness

Continue expanding acceptance validation so a lab can prove operational readiness rather than only confirm that virtual nodes exist.

Target validation areas include:

- node runtime state
- interface state
- IGP adjacency
- BGP session state
- expected and forbidden routes
- end-to-end reachability
- VRF-specific reachability
- MTU/DF behavior
- feature-specific assertions
- defined failure and recovery scenarios

Readiness reporting should clearly distinguish node runtime, device accessibility, configuration application, protocol convergence, and network acceptance results.

## Higher-level lab definitions

The explicit `topology.yaml` format remains the stable lower-level lab contract.

A future optional higher-level format may describe concepts such as:

- device roles and counts
- logical links and site relationships
- routing protocols
- addressing pools
- failure scenarios
- acceptance criteria

That higher-level description can then produce the explicit topology, configuration, and validation artifacts consumed by the existing engine.

## Portability

The reusable engine should continue to avoid assumptions about a specific lab owner or infrastructure environment.

EVE-NG hosting, DNS, routing, VPNs, firewall policy, image availability, and external services remain environment prerequisites unless a future feature explicitly manages them.

## Upstream relationship

The original implementation is `wcmder/eve-ng`.

This fork is maintained independently and may continue to extend the original project with additional network-lab capabilities.
