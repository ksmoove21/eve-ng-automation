# PAN-OS console field qualification

## Observed EVE Pro 7.2.0-4 / PAN-OS 11.1.0 KVM image

A disposable VM-Series guest exposed a reachable Telnet endpoint with no guest
serial payload. Bounded serial observations did not establish boot failure.
Read-only QMP status and block queries showed a running guest and a 60 GiB
virtual disk; disk overlay file size alone was not its virtual capacity.
A VGA screenshot showed a ready login prompt. Native QMP keyboard input then
completed factory-admin authentication and the mandatory password change to
the configured runtime credential. No credential values belong in evidence.

This proves this guest's VGA first-login path. It does not establish that all
PAN-OS 11.1 images require VGA, nor that the existing serial-only initializer
can bootstrap this image. Prefer a supported console path, then management
SSH/API when reachable; preserve device host-key verification.

[EVE's Palo image guide](https://www.eve-ng.net/index.php/documentation/howtos/howto-add-palo-alto/)
is version-specific and older listed serial examples do not qualify 11.1.
[Palo VM-Series requirements](https://docs.paloaltonetworks.com/vm-series/activation-and-onboarding/vm-series-models/vm-series-system-requirements)
are model/license-specific: the published VM-300 memory minimum is 9 GB and its
disk minimum 60 GB. A 4-vCPU/8-GiB guest reaching VGA login is an observation,
not a supported resource-profile claim or proof of dataplane readiness.

The SSH helper accepts an explicit `known_hosts` file in addition to system
keys. Enroll only a public key whose fingerprint matches trusted guest console
output (`show ssh-fingerprints hash-type sha256 format base64` on PAN-OS 11.1).
The file can remain in ignored workspace state. Missing or changed keys still
fail; this does not enable automatic key acceptance or disable verification.

## PAN-OS 11.1.0 routing parser observations

FIELD-TESTED on the same disposable guest: set the BGP router ID before other BGP options or
`enable yes`; otherwise the server rejects activation because router ID is
required. A peer's local-address IP must reference the configured interface
address including its prefix length. A bare address was rejected as an invalid
reference. Set OSPF backbone area type `normal` explicitly before adding its
interface; the unset area type failed the backbone stub/NSSA constraint.
These observations qualify parser prerequisites, not routing convergence.

## Session diagnostics after routing changes

On PAN-OS 11.1.0, `show session all filter source <host-IP> destination
<host-IP>` accepts exact host addresses. Field validation rejected a CIDR
network in the destination filter. Keep diagnostics and any authorized session
clear bounded to explicit endpoint pairs or a verified session ID.

A current FIB route alone does not establish that an existing UDP session has
correct reverse-flow zone state. Field readback observed a session retaining an
old reverse zone while its egress interface matched the new FIB route; its
reverse packet count remained zero. Inspect `show session id <ID>` alongside
routing and packet evidence. Palo documents long-lived session behavior after
routing changes and targeted session cleanup in its
[session reroute knowledge-base article](https://knowledgebase.paloaltonetworks.com/KCSArticleDetail?id=kA10g000000PLlfCAG).
Requalify traffic after recovery; do not infer success from a session-clear
acknowledgment or broaden firewall policy to mask cached state.
