# NX-OS

## Live-tested reference

Nexus 9000v `nxosv9k-9300v-10.5.2.F` completed a disposable EVE-NG integration on NX-OS 10.5.2. This is a known-good reference, not a release-wide compatibility claim.

## Bootstrap

The initializer reuses `CISCO_USERNAME`, `CISCO_PASSWORD`, and `CISCO_ENABLE_SECRET`. First boot may show Power On Auto Provisioning, request secure-password and initial `admin` setup input, then use `login:` rather than `Username:`. The RED clean rebuild exercised this first-boot path on a fresh NX1 guest. The console state machine handles these states before applying the six-key private bootstrap intent and saving with `copy running-config startup-config`.

## Validation

Verified management commands are `show ip route 0.0.0.0/0 vrf management` and `ping <destination> vrf management count 5 timeout 2`. NX-OS 10.5.2 reports ping success as `N packets transmitted, N packets received, X% packet loss`; the validator parses that structured summary.
## NX-OSv 10.5.2.F manual fabric field qualification

Both the 9300v and 9500v image variants completed management initialization
with exact `nxos64-cs-lite.10.5.2.F.bin` boot intent saved. A three-node manual
OSPF underlay reached FULL neighbors and routing/VTEP loopback reachability.
This qualifies the exercised virtual image features, not every hardware feature.

Session width matters for echo-correlated configuration. A long command in
VRF address-family mode exceeded the default-width echo boundary on 9300v.
`terminal width 511` was accepted and full replay with echo verification saved
successfully. NX-OS bootstrap now prepares this session width before applying
configuration. This is session state, not persistent guest configuration.

## NX-OS 10.5(x) NVE diagnostics and Lite resource requirements

**DOCUMENTED, exact-image field validation required:** Cisco's 10.5(x) VXLAN
guide uses `show running-config interface nve 1`; the resulting configuration
heading is `interface nve1`. Do not infer that NVE configuration is absent from
an invalid-interface error produced by the unspaced show form. Use
`show nve interface nve1 detail`, `show nve vni`, and `show nve peers` to
qualify operational state alongside EVPN path validity and advertisement.
A zero gateway/next-hop field on a locally generated type-5 entry alone is
insufficient to diagnose a forwarding failure.

Sources: [VXLAN configuration guide, 10.5(x)](https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/105x/configuration/vxlan/cisco-nexus-9000-series-nx-os-vxlan-configuration-guide-release-105x.pdf)
and [EVPN filtering guide, 10.5(x)](https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/105x/configuration/vxlan/cisco-nexus-9000-series-nx-os-vxlan-configuration-guide-release-105x/m_configuring_bgp_evpn_filtering.html).

**DOCUMENTED for Lite images:** Cisco lists 4.5 GB minimum RAM, 8 GB
recommended RAM, two minimum vCPUs and four recommended vCPUs for 9300v/9500v
Lite. The full-image minimums must not be applied to the checked-in
`nxos64-cs-lite.10.5.2.F.bin` reference without distinguishing the image flavor.
These resource limits do not establish the cause of any observed service crash.
Source: [Nexus 9300v and 9500v Lite, 10.5(x)](https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/105x/configuration/n9000v-9300v-9500v/cisco-nexus-9000v-9300v-9500v-guide-release-105x/m-nexus-9300v-and-9500v-lite-nx-os-image.html).

## Missing NVE runtime despite saved configuration

**OBSERVED on NX-OSv Lite 10.5.2.F:** the NVE feature remained enabled,
startup configuration retained NVE1, and its VLAN/VRF/source-loopback
prerequisites remained configured, but running interfaces and NVE VNI state
lacked NVE1. Both `interface nve1` and `interface nve 1` returned
`Invalid interface format at '^' marker.` The same state persisted across
one disk-preserving guest restart.

**DOCUMENTED for a different release scenario:** Cisco lists this rejection
and missing NVE state in CSCwf92752 for upgrades into 10.4(x). Its workaround
is to disable and re-enable `feature nv overlay`, then restore the full NVE
configuration. This is a comparable symptom, not confirmation that 10.5.2.F
has that exact defect. Ordinary interface reconciliation must not silently
perform this feature cycle.
Source: [Cisco 10.4(2)F release notes, CSCwf92752](https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/104x/release-notes/cisco-nexus-9000-nxos-release-notes-1042.html).

**FIELD-VALIDATED recovery on Lite 10.5.2.F:** the bounded feature cycle
allowed NVE1 to be recreated and saved to startup configuration. The intended
L2 and L3 VNIs became operational, both VTEP peers reached Up, and a firewall
BGP default was exported as a valid EVPN type-5 route and installed on the
remote leaf. Wait for the reported fabric convergence timer to expire before
classifying an early absent route or Down peer as the recovery result.
This proves the exercised recovery, not the exact defect attribution or
uninterrupted fabric stability.

## NX-OS 10.5(x) QEMU and NIC requirements

**DOCUMENTED:** Cisco sets QEMU 4.2.0 as the minimum for the 10.5(x)
Nexus 9000v KVM deployment and supports E1000 network adapters. Retain
`e1000`; do not substitute `e1000e` or virtio based only on a reset message.
Use an installed QEMU release meeting the documented minimum and qualify
that runtime with the exact simulator image.
Source: [Cisco 10.5(x) deployment guide](https://www.cisco.com/c/en/us/td/docs/dcn/nx-os/nexus9000/105x/configuration/n9000v-9300v-9500v/cisco-nexus-9000v-9300v-9500v-guide-release-105x/m-nexus-9000v-deployment.html).

**OBSERVED on Lite 10.5.2.F with QEMU 4.1.0:** repeated underlay adjacency
loss and E1000 kernel adapter resets were observed after boot. Four vCPUs
alone did not establish stability. QEMU 4.1.0 is below the documented
minimum, but the observations do not prove that mismatch caused the resets.
Earlier image bootstrap or point-in-time fabric success does not waive
these runtime requirements. Qualification on an eligible installed QEMU
release is separate from the bounded NVE reconstruction recovery above.
