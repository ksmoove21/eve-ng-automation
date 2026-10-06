# PAN-OS console field qualification

## Observed EVE Pro 7.2.0-4 / PAN-OS 11.1.0 KVM image

A disposable VM-Series guest exposed a reachable Telnet endpoint with no guest
serial payload. Bounded serial observations did not establish boot failure.
Read-only QMP status and block queries showed a running guest and a60GiB
virtual disk; disk overlay file size alone was not its virtual capacity.
A VGA screenshot showed a ready login prompt. Native QMP keyboard input then
completed factory-admin authentication and the mandatory password change to
the configured runtime credential. No credential values belong in evidence.

This proves this guest's VGA first-login path. It does not establish that all
PAN-OS11.1 images require VGA, nor that the existing serial-only initializer
can bootstrap this image. Prefer a supported console path, then management
SSH/API when reachable; preserve device host-key verification.

[EVE's Palo image guide](https://www.eve-ng.net/index.php/documentation/howtos/howto-add-palo-alto/)
is version-specific and older listed serial examples do not qualify11.1.
[Palo VM-Series requirements](https://docs.paloaltonetworks.com/vm-series/activation-and-onboarding/vm-series-models/vm-series-system-requirements)
are model/license-specific: the published VM-300 memory minimum is9GB and its
disk minimum60GB. A4-vCPU/8GiB guest reaching VGA login is an observation,
not a supported resource-profile claim or proof of dataplane readiness.
