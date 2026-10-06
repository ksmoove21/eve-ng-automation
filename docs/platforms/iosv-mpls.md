# IOSv MPLS provider validation

## Documented capabilities

Cisco lists MPLS, MPLS L3VPN, OSPF and BGP as supported IOSv features in
[the IOSv platform documentation](https://developer.cisco.com/docs/modeling-labs/iosv/).
That support statement does not qualify every image version or EVE deployment.

The IOS-family validation adapter supports operational IPv4 LDP neighbors,
exact IPv4 LFIB prefixes with numeric outgoing labels or penultimate-hop popping,
and established VPNv4 BGP peers. See [validation](../operations/validation.md)
for declarative checks and command scope.

LDP parsing follows Cisco's
[LDP overview and verification examples](https://www.cisco.com/c/en/us/td/docs/ios/mpls/configuration/guide/convert/mp_ldp_book/mp_ldp_overview.html).
LFIB parsing follows the
[IOS MPLS command reference](https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/mpls/command/mp-cr-book/mp-s2.html).
Unsupported output formats fail acceptance rather than being interpreted as
successful forwarding or route absence.

## Observed IOSv 15.9(3)M8 behavior

IOSv 15.9(3)M8 on EVE-NG 7.2.0-4 has been observed reaching privileged EXEC
through native Telnet consoles with eight GigabitEthernet interfaces. Initial
setup is declined by the existing IOS console bootstrap. A three-router
PE-P-PE field test also observed FULL OSPF adjacencies, operational LDP sessions
in label space zero, numeric outgoing labels at each PE for the remote PE
loopback, and `Pop Label` entries at the P router. Reciprocal PE loopback probes
sourced from Loopback0 received five replies out of five. The same field test established global VPNv4
peering with zero received customer prefixes, PE-only customer VRFs with RD/RT
policy, and full startup/running configuration equality on all three routers.
Customer-facing ports stayed unassigned and shut down. Global VPNv4 summary
is field-tested; a VRF-scoped query remains unqualified for this image.

## IOSv 15.9(3)M8 DMVPN Phase 3

FIELD-TESTED on EVE-NG 7.2.0-4 with IOSv 15.9(3)M8: the image accepted and
operated an IKEv2 profile using AES-CBC-256, SHA-256, and DH group 14 with a
transport-mode IPsec profile. A dual-hub mGRE/NHRP Phase 3 topology established
two registered spokes at each hub, two static NHS mappings at each spoke, eight
READY IKEv2 SAs, and four established BGP hub-spoke sessions. Sourced tunnel
probes to both hubs passed 5/5 and showed active IPsec encapsulation and
decapsulation counters with zero send and receive errors.

A bounded synthetic TEST-NET /32 route exchange then produced direct dynamic
spoke-to-spoke NHRP mappings, active direct-spoke transport IPsec SAs, and
strict sourced traffic at 5/5 in both directions. The temporary loopbacks and
exact BGP advertisements were removed, and all BGP sessions returned to zero
received prefixes. This qualifies the overlay mechanisms only. Real LAN prefix
exports, enterprise service routing, and production payload policy remain
untested.

## Proof boundary

An operational LDP session and an LFIB entry establish provider control-plane
and forwarding-table state. A VPNv4 peer with zero received prefixes can be
established before customer attachments exist. These checks alone do not prove
customer VPN route exchange, payload delivery, or isolation. Prove those with
VRF routing and customer traffic tests after customer edges are attached.

Imported VPN routes on IOSv 15.9(3)M8 were observed with a `(default)`
annotation on the remote PE next hop. The route parser accepts that exact
annotation and retains those addresses as `global_next_hops`; unknown scopes
and incomplete descriptors still fail validation. This records recursive
lookup scope, not proof of customer payload delivery.

IOSv 15.9(3)M8 defaulted to an 80-column terminal in the same lab. A long
VRF BGP redistribution command executed but its full echo was not retained,
so echo-correlated initialization stopped. `terminal width 512` was accepted
and the command subsequently completed with full echo verification. IOS
initialization that requires command echoes now prepares that session width
before entering configuration mode; terminal width is session state.

The same image subsequently passed customer PE-CE OSPF in a VRF while
provider OSPF ran in the global table, including VPN route exchange, reciprocal
customer probes and increasing provider label counters. Reusing the global
process router ID for the customer process was rejected with `% OSPF: router-id
... in use by ospf process ...`; a distinct customer router ID was saved and
adopted after a process-scoped restart. Console commands now treat that exact
rejection family as an error instead of claiming configuration success.

## Bounded IOSv console recovery observation

FIELD-TESTED on EVE Pro 7.2.0-4 with IOSv 15.9(3)M8: an unconfigured
new-lab guest exposed a reachable Telnet wrapper but no IOS serial payload.
A simple stop/start did not recover it. Read-only QMP reported running,
serial frontend open, and boot disk reads comparable to a working peer.
A native stop/wipe/start of only that unconfigured disposable guest restored
normal login and `show version`. The root cause remains unqualified; this is
not proof of boot failure or a general requirement to wipe IOSv nodes.
Preserve configured guests. Native wipe rebuilds the selected guest from its
base image; use it only within an authorized disposable scope after preserving
needed evidence and confirming the guest has no configuration to retain.

## OSPF external routes at a CE BGP boundary

Cisco documents that `redistribute ospf <process>` under BGP includes only
OSPF internal routes unless external route types are selected explicitly. See
[OSPF-to-BGP redistribution](https://www.cisco.com/c/en/us/support/docs/ip/border-gateway-protocol-bgp/5242-bgp-ospf-redis.html).
FIELD-TESTED on IOSv 15.9(3)M8: a customer payload learned as OSPF external
type 1 was present in the CE RIB but absent from its BGP export. Explicit
`match internal external 1 external 2` with an exact prefix route map admitted
the intended payload while retaining the existing internal exports. Saved
configuration and bidirectional payload probes were verified. Do not broaden
external redistribution without the owning lab's explicit prefix policy.
