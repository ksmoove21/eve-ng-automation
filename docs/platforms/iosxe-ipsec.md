# IOS and IOS-XE route-based IPsec

The iosxe-ipsec initialization profile provides a reusable, platform-oriented
configuration for commercial route-based VPN testing. It is supported by the
existing IOS/IOS-XE execution adapters, including C8000V, ISRv, CSR variants
when their EVE images boot correctly, and compatible IOL images.

The profile configures:

- a global-routing-table underlay interface and directly attached peer;
- an inside interface and static VTI in VRF Red;
- IKEv2 with a pre-shared key by default, or IKEv1 when explicitly selected;
- AES-256, SHA-256, Diffie-Hellman group 14, and an IPsec tunnel transform;
- explicit protected static routes; and
- RIPv2 within the VRF, passive by default except on the VTI.

This is a generic platform interoperability and routing capability. It makes no
claims about vendor-specific security appliance behavior.

## Profile schema

An IOS or IOS-XE node may use configs/NODE-init.yaml with profile:
iosxe-ipsec. Required keys are hostname, underlay, inside, tunnel, psk_env, and
routes. ike_version may be 1 or 2 and defaults to 2.

underlay contains interface, address, and peer. inside and tunnel contain
interface and address. routes is a list of prefix and next_hop mappings, or an
empty list. The peer must be directly attached, addresses and interfaces must
not overlap, and route next hops must be reachable through the inside network.

The pre-shared key is resolved from the workspace environment and is never
stored in the profile. It must contain 24-128 alphanumeric, underscore, or
hyphen characters.

## Validation

The iosxe-ipsec validation check accepts underlay_interface, peer,
underlay_prefix, inside_interface, tunnel, remote_prefixes, local_prefixes,
protected_source, protected_destination, and optional ike_version.

It validates underlay reachability, VRF membership and route isolation, VTI
state, IKE state, active inbound and outbound IPsec SAs, nonzero packet
counters, protected reachability, RIPv2 operational state, and RIP-learned
remote routes. The validator is read-only and fails closed on missing or
unrecognized output.

## Support boundaries

- The implementation uses ordinary commercial IOS/IOS-XE cryptography. It does
  not emulate specialized encryptor hardware, certified security boundaries, or
  proprietary protocols.
- Supported syntax does not guarantee that every EVE image has a usable crypto
  feature set. Live qualification is required per image.
- IOL L2 images that reject IKE, IPsec transforms, or VTI protection are
  unsupported for this profile.
- Static routes are not tracked. A logically installed route can blackhole
  traffic when its security association or remote service is unavailable.
- RIPv2 support covers ordinary route learning and withdrawal over the VTI; it
  does not imply a particular redundancy or site design.
- The profile does not add first-hop redundancy, object tracking, policy-based
  routing, or application-aware failover.

## C8000V licensing

If C8000V reports a blank boot-license level, the initializer selects the
minimum Network Essentials and DNA Essentials tier, saves, reloads once, and
verifies the active level. It does not register a Smart Account, install an
entitlement, or contact a licensing service. Existing nonempty tiers are
preserved.

## Sources

- [Cisco VRF-aware static VTI](https://www.cisco.com/c/en/us/support/docs/security-vpn/ipsec-architecture-implementation/214938-configuring-ikev2-vrf-aware-svti.html)
- [Cisco RIP command reference](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/iproute_rip/command/irr-cr-book/irr-cr-rip.html)
- [Cisco C8000V boot license configuration](https://www.cisco.com/c/en/us/support/docs/ios-nx-os-software/ios-xe-17/217047-enable-license-boot-level-and-addon-on-c.html)
