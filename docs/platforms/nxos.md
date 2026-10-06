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
