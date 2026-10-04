# Nexus Dashboard / Fabric Controller

This document records reusable Nexus Dashboard and NDFC behavior validated by
the automation engine. Environment-specific addressing, hostnames, lab names,
credentials, worker identities, and sprint chronology belong in the private
workspace and are intentionally omitted here.

## Validated platform combinations

The automation has been exercised against:

- EVE-NG Pro 7.2.0-4 with Nexus Dashboard virtual appliances;
- Nexus Dashboard 3.2.1i with the bundled Fabric Controller 12.2.2.241; and
- Nexus Dashboard 3.2.2m with NDFC 12.2.3 during the accepted DC1 fabric
  workflow.

Treat exact versions as compatibility evidence, not a guarantee for every
release. Revalidate lifecycle and API behavior when either Nexus Dashboard or
NDFC changes.

## Image and satellite preflight

Nexus Dashboard requires a stable boot/data-disk layout before start. The engine
supports declaring the expected QCOW2 basenames with
`required_image_disk_names` and validates the selected satellite read-only
before deployment.

Satellite preflight uses bounded file metadata plus `qemu-img info` and reports
structured readiness such as:

- `READY`
- `COPYING/UNSTABLE`
- `MISSING`
- `INVALID`

The preflight does not copy, repair, checksum, or otherwise mutate images.

EVE Pro creates the satellite-side TAP/VXLAN and manager-side Cloud plumbing
through its native cluster control plane. A satellite does not generically
require a manually created local `pnet0`, OVS bridge, Linux bridge, or static
VXLAN device for every lab. When native cluster start/sync fails, diagnose that
native path rather than recreating EVE networking out of band.

## Concurrent EVE sessions

EVE permits only one active API login location per username. Concurrent workers
must use distinct EVE identities; a later login with the same username can
invalidate an existing session.

The reusable engine therefore treats worker credentials as environment input,
never as repository state.

## Console and first boot

For the validated Linux KVM workflow before Nexus Dashboard 3.2.2, Cisco's
supported sequence begins on the serial console and then transitions to the
HTTPS Cluster Bringup wizard.

The observed first-boot sequence includes:

1. enter first-boot setup;
2. choose manual bootstrap;
3. set the administrator password;
4. configure management CIDR and gateway;
5. confirm cluster-leader behavior;
6. review the configuration; and
7. complete serial setup.

The console state machine must send carriage return only where required. Sending
CRLF can leave the line-feed byte to be consumed by the following prompt.

Once the declared management interface is reachable over HTTPS, a repeated
initializer may treat serial bootstrap as already configured rather than
reopening first boot.

## Declarative configuration

Environment-specific Nexus Dashboard values belong in private initialization
intent. The public schema supports the reusable structure only.

Supported intent includes:

- management and DATA interface addressing;
- DNS and search-domain settings;
- NTP intent;
- Fabric Controller enablement;
- LAN device-management connectivity selection;
- independent MANAGEMENT and DATA external/service-IP resources.

Schema behavior includes:

- derived service-IP pools from declared counts;
- explicit address lists for environments with reserved ranges;
- subnet-membership and uniqueness validation;
- exclusion of node/gateway addresses;
- duplicate/overlap rejection; and
- read-before-write conflict checks against existing external-IP resources.

No environment address or hostname should be hardcoded in reusable engine code.

Nexus Dashboard browser automation requires the optional dependency:

```text
pip install -e .[nexus-dashboard]
```

## Supported API boundary

Nexus Dashboard exposes documented authentication and post-deployment platform
APIs, including cluster/node state and external-IP resources. Fabric Controller
uses the Nexus Dashboard authentication gateway and its documented
`/appcenter/cisco/ndfc/api/v1/...` namespace. In-product API discovery is
available through `/apidocs/` when the platform has reached the corresponding
lifecycle state.

Before cluster creation, some documented post-deployment APIs are expected to be
unavailable. An HTTP 404 before the documented lifecycle transition is therefore
not sufficient evidence of a platform defect.

The engine must not adopt undocumented browser/XHR endpoints merely because the
GUI uses them internally.

## Lifecycle-first automation

Controller automation follows the supported operator lifecycle. The engine
models the current platform state, the next documented transition, and its
prerequisites before deciding whether a failed API call represents a fault.

A validated sequence is:

```text
serial bootstrap
-> Cluster Bringup
-> base platform services
-> MANAGEMENT/DATA service-IP resources
-> Fabric Controller service setup
-> LAN
-> Fabric Management Advanced
-> service convergence
-> LAN Device Management Connectivity
-> documented NDFC API workflows
```

When a documented API is not yet available, automate the equivalent supported
GUI, CLI, or serial action a human operator would perform. After each transition,
use documented health/readback evidence before advancing.

## Fabric Controller lifecycle

On the validated 12.2.x workflows:

| State | Expected action |
| --- | --- |
| Nexus Dashboard active | Launch Fabric Controller and select the intended feature set. |
| First-run Service Setup | Select LAN and the required Fabric Management feature set, review, and submit. |
| Service deployment | Wait for documented platform/service health to converge. |
| Server Settings | Reconcile LAN Device Management Connectivity to the declared network. |
| API ready | Use documented authenticated NDFC APIs for fabric, inventory, tenant, and deployment operations. |

An empty fabrics list is valid after NDFC becomes API-ready. Do not create a
fabric merely to prove API availability.

## Health and convergence evidence

Useful supported evidence includes:

- `acs deployment running`
- `acs health`
- `acs ntp`
- documented platform cluster/node reads
- external-IP resource reads
- documented NDFC fabric and inventory reads

Lifecycle success should be based on the state appropriate to that phase, not on
a single HTTP response.

If EVE reports the VM running but management services remain unavailable, gather
bounded console, QMP/block-device, TAP/network, and host-runtime evidence before
classifying the failure. Observation at these layers does not by itself justify
host-side mutation.

## NDFC 12.2.3 behavior validated during DC1 acceptance

The accepted DC1 workflow exercised reusable NDFC 12.2.3 behavior including:

- Easy Fabric creation and idempotent readback;
- switch discovery/import;
- LAN credential handling;
- role assignment;
- per-switch deployment/readback;
- vPC/Fabric Peering workflows;
- ToR pairing behavior;
- VRF and Network deployment;
- NDFC-managed endpoint access ports; and
- border/external-edge integration validation.

Version-specific details live in the dedicated NDFC platform notes in this
directory.

## NX-OS DHCP scope observation

On the validated NX-OS 10.5(2) virtual leaf, `feature dhcp` was accepted, while
the bounded probe did not expose IOS-style `ip dhcp pool` local-server syntax.

That observation is a platform fact, not a generic architectural blocker. When a
command surface is unexpectedly absent, check the exact NOS release's command
reference, feature/service prerequisites, release notes, and vendor guidance
before redesigning the lab.

## Testing

Platform-specific focused tests should cover:

- satellite image readiness;
- serial bootstrap state handling;
- intent/schema validation;
- browser lifecycle transitions;
- API readiness and idempotence;
- NDFC fabric/inventory/tenant reconciliation; and
- read-only validation of resulting state.

Known repository portability debt exists in inherited POSIX-specific tests that
use `os.geteuid()` or Unix permission-bit semantics. Those failures should be
validated on a POSIX environment and fixed deliberately rather than treated as
Nexus Dashboard runtime failures.

## References

- Cisco Nexus Dashboard API documentation
- Cisco Nexus Dashboard deployment guides
- Cisco Nexus Dashboard Fabric Controller documentation
- Cisco NDFC LAN initial-setup documentation
- EVE-NG Professional release and cluster documentation

Use the exact-version vendor documentation appropriate to the target release.
