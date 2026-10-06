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
sourced from Loopback0 received five replies out of five. VPNv4 and customer
VRF acceptance are separate proof stages; these observations do not imply their
completion.

## Proof boundary

An operational LDP session and an LFIB entry establish provider control-plane
and forwarding-table state. A VPNv4 peer with zero received prefixes can be
established before customer attachments exist. These checks alone do not prove
customer VPN route exchange, payload delivery, or isolation. Prove those with
VRF routing and customer traffic tests after customer edges are attached.
