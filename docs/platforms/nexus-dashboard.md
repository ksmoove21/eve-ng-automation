# Nexus Dashboard / Fabric Controller

## Observed 3.2.2m / NDFC 12.2.3 recovery

The 3.2.2m appliance and its NDFC 12.2.3 service are live-tested in the EVE
QEMU lab. One long-running guest stopped answering on management and emitted no
serial text even though EVE and QMP still reported QEMU running. A normal,
exact-node EVE stop/start, without a wipe, restored the serial login prompt and
management HTTPS/SSH.

The documented ND management-routes GET recovered from HTTP 500 to 200 before
the NDFC fabrics and Easy_Fabric template GETs recovered from HTTP 500 to 200.
Treat these API readbacks as separate service-readiness gates before a fabric
mutation. After both NDFC GETs returned 200, the reusable DC2 Easy_Fabric
reconciliation returned `already-configured`; the selected fabric's switch
inventory GET returned 200 with zero switches. This is one observed recovery,
not a rule to restart every guest that returns HTTP 500.

## Historical 3.2.1i handoff checkpoint

This section records an unfinished 2026-10-01 sprint and is retained as
historical version-specific evidence. Its appliance and satellite state is not
the current 3.2.2m lab state.

## Live target and release

- **LIVE-TESTED:** EVE template `nd`, image `nd-9.3.2.1c`.
- **LIVE-TESTED:** the appliance serial setup utility identifies the release as
  **Nexus Dashboard 3.2.1i**. The EVE image suffix is not the appliance release.
- **HISTORICAL NOTE:** This 2026-10-01 checkpoint preceded the later live-tested
  3.2.2m/NDFC 12.2.3 cycle described above.
- **LIVE-TESTED:** `ND-01` is running (`status: 2`) in disposable lab
  `nexus-dashboard-disposable` on `eve-sat03` (satellite ID 3), with 16 vCPU,
  65536 MiB RAM, two NICs, `cpulimit=0`, and image `nd-9.3.2.1c`.
- **LIVE-TESTED:** stable readable `virtioa.qcow2` (45 GiB virtual) and
  `virtiob.qcow2` (500 GiB virtual) satisfy the required boot/data disk layout.
- For satellite preflight, declare `required_image_disk_names:
  [virtioa.qcow2, virtiob.qcow2]` for the ND image. The named layout accepts
  an additional stable source QCOW2 while still requiring both boot/data disks
  to be present, readable, and stable.

## EVE identity

This worktree uses generic worker `codex1`. Its live POD 3 assignment is
intentional and authoritative. Its role is `admin` and `extauth` is `internal`.
Only its password was aligned to the existing ignored `.env`; a complete
pre/post comparison proved its POD and every other non-secret account property
unchanged. Fresh authentication and a harmless read succeeded. Do not revert to
the former automation identity or change the worker's POD.

`codex2` and the simultaneous independent-session proof were not revalidated in
this checkpoint. That is separate worker-account acceptance and does not alter
this worktree's `codex1` assignment.

EVE permits one login location per user. Prior HTTP 412/401 evidence correlated
with overlapping same-user automation sessions. Keep one generic EVE identity
per concurrent execution slot and do not introduce an in-process re-login that
invalidates an active session.

## EVE satellite and native cluster networking

**OBSERVED / VERSION MATCH:** the manager runs `eve-ng-pro 7.2.0-4` and
`eve-sat03` now runs `eve-agent 7.2.0-4`. The owner-authorized manager-side
`unl_wrapper -a updatesat` corrected the former 7.0.1-18 agent mismatch. The
agent is active, its `/sync/stat` route exists, and the normal EVE start path
subsequently succeeded. Do not repeat the update without new evidence.

The generic engine preflight inspects the exact image directory read-only on the
selected satellite through configured manager SSH. It uses bounded metadata and
`qemu-img info` stability checks and returns `READY`, `COPYING/UNSTABLE`,
`MISSING`, or `INVALID`. It does not checksum, copy, repair, or alter images.

**OBSERVED:** after native EVE start, each satellite TAP is paired with an
EVE-created VXLAN (`xun...`, UDP 8472) using WireGuard `wg0` as the fan-map
underlay and EVE's `tc` BPF program. The manager creates the Cloud0 `bun`/`pun`
side attached to manager `pnet0`. No local satellite `pnet0`, Linux bridge, OVS
bridge, or manually created tunnel is required. Cloud0 was proven end to end by
successful manager-to-ND and manager-to-gateway pings with counters increasing
in both directions. The data-side TAP/VXLAN exists, but guest data addressing
and traffic remain unproven.

Earlier EVE error-12 attempts while the image was copying are invalid platform
failure evidence. The later valid error 12 was traced to the outdated agent's
`/sync/stat` 404 and is resolved. Do not re-investigate local `pnet0`, disk
permissions, or image readiness without contradictory evidence.

## Console and first boot

**DOCUMENTED** for Linux KVM releases before 3.2.2 and **LIVE-TESTED** here:
Cisco's procedure uses a serial console and then sends the operator to the HTTPS
Cluster Bringup wizard.

EVE console mode `telnet` maps the guest serial device through the selected
satellite. The engine resolves that satellite through verified manager SSH and
opens a strict nested SSH command to the satellite-local console port. The live
3.2.1i sequence was:

1. `Press any key to run first-boot setup on this console...`
2. `Press Enter to manually bootstrap your node...`
3. admin password and confirmation
4. management CIDR and gateway
5. cluster-leader confirmation
6. `n` at the review prompt
7. `System configured successfully`

The guest must receive CR only. Sending CRLF caused the LF to be consumed as an
empty answer at the adjacent password-confirmation prompt.

The declared management interface is configured. Serial first boot is complete,
HTTPS is available on the declared management address, and documented `POST /login` succeeds.
A repeated operator-facing `eve init` returned `already-configured` based on the
existing management HTTPS listener without reopening or submitting input to the
serial setup. This proves idempotence for the serial-first-boot phase only.

## Declarative configuration

The private workspace stores the environment-specific Nexus Dashboard intent in
`labs/nexus-dashboard-disposable/configs/ND-01-init.yaml`, including management
and DATA addressing, both declared DNS providers, the declared FQDN NTP target,
the search domain, five derived persistent/service addresses, Fabric Controller,
and DATA device-management connectivity. These values are schema-validated and
remain private; no environment address or hostname is encoded in reusable code.

The owner superseded the earlier DNS and IP-address NTP sources. The current
intent uses two DNS providers and an FQDN NTP target. Schema v2 declares
independent MANAGEMENT and DATA service-IP pool counts; the engine derives each
pool after its corresponding node interface. Schema v3 accepts explicit
MANAGEMENT and DATA IPv4 address lists for environments with reserved service
ranges. Each address must be usable in the declared interface subnet and differ
from the node and gateway addresses. Both schemas reject duplicate/overlapping
pools, check for live external-IP resource conflicts, and read-verify the
separately named documented resources. Schema v1 remains DATA-only compatible.

**OBSERVED:** the live disposable appliance has five available MANAGEMENT and
five available DATA service IPs. Bounded ICMP and neighbor-cache checks from
the appliance found no response or neighbor entry for any newly derived
MANAGEMENT candidate before allocation. The documented API accepted the
MANAGEMENT resource and a normal `eve init` read-verified both pools as
`already-configured` on repeat. No address is hardcoded in reusable code.

Nexus Dashboard browser operations require the declared optional dependency:
`pip install -e .[nexus-dashboard]`.

## Supported API boundary

**DOCUMENTED:** Nexus Dashboard 3.2.1 publishes `POST /login`, token/cookie and
API-key authentication, plus post-deployment platform resources including
GET/PUT cluster and node paths and external-IP resources. The Fabric Controller
API uses the Nexus Dashboard authentication gateway and its documented
`/appcenter/cisco/ndfc/api/v1/...` namespace. Cisco documents in-product API
discovery at `/apidocs/`.

**OBSERVED:** on this pre-cluster appliance, `/login` works while `/apidocs/`,
the documented v1/v2 cluster collections, node collection, external-IP
collection, and documented backup-status path return 404.

**DOCUMENTED:** Cisco's published 3.2.1 OpenAPI contains no operation that
creates or bootstraps the initial cluster. Cisco's pre-3.2.2 Linux KVM guide
states that only the desktop GUI procedure is supported and directs the
operator to the HTTPS Cluster Bringup wizard after serial setup.

**UNSUPPORTED / UNDOCUMENTED:** internal browser/XHR endpoints must not become
implementation dependencies merely because the GUI calls them.

## 3.2.1i browser Cluster Bringup evidence

**OBSERVED / SUPERSEDED:** The earlier private DNS and IP-address NTP intent
failed the documented NTP management validation. It is no longer current owner
intent and must not be restored.

**OBSERVED:** After the owner supplied replacement private DNS providers and an
FQDN NTP target, the documented browser workflow accepted DNS, search domain,
NTP with preferred source, no-proxy confirmation, the narrowly normalized
UI-invalid App/Service CIDR defaults, the primary-node DATA CIDR/gateway, and
Fabric Controller selection. It advanced through Node Details, Deployment Mode,
and Summary, then accepted the deployment confirmation. This is live evidence
that the documented management-network NTP validation succeeded with the
replacement intent; it necessarily resolved and reached the declared NTP target
through the configured DNS providers. It is not an ICMP-only claim.

**OBSERVED:** Cluster Bringup has persisted and completed. The Dashboard
reported completed Kubernetes runtime, local networks, base system services,
peer networking, Kubernetes stack, cluster health, and ND-cluster setup phases.
The former service-installation gate cleared. A temporary empty HTTPS body and
login-service restart were observed during that transition; the node stayed
running and serial observation reported no fatal marker.

**OBSERVED:** The running appliance's documented `/apidocs/` surface returns
HTTP 200 and publishes the 3.2.1i OpenAPI schema. Its documented platform
cluster and node collection GETs return HTTP 200 with `Active` state; the
external-IP collection GET returns HTTP 200 with an empty baseline. The schema
documents external-IP POST/PUT with `targetNetwork: Data`. These read-only
observations are not an implementation dependency on internal UI requests.

**VERSION-SPECIFIC / OBSERVED:** 3.2.1i has no editable persistent/service-IP
control in its documented initial Summary UI, including View Advanced Settings.
The documented post-cluster external-IP API was used instead: the initially
empty collection accepted one DATA-targeted resource containing the five derived
private service addresses, and read-back returned HTTP 200 with one resource.
No undocumented GUI request was used.

**OBSERVED / CONVERGENCE:** Cisco's supported `rescue-user` commands report
`Running deployment mode ndfc` for `acs deployment running` and `All components
are healthy` for `acs health`, including a fresh bounded recheck. `acs ntp` reports a selected system peer from the declared NTP environment with a small offset. This confirms
the expected Controller deployment mode and healthy platform components. Cisco
release notes identify Fabric Controller **12.2.2.241** as the service bundled
with Nexus Dashboard 3.2.1i; 12.2.3 is not the live target.

## Fabric Controller lifecycle: 12.2.2.241

The following lifecycle model is intentionally explicit: an HTTP response or
GUI label is evaluated only with its documented state, transition, and
prerequisites. It applies to the installed 3.2.1i/12.2.2.241 combination, not
to a future 3.2.2m image.

The browser workflow reads the declared LAN device-management connectivity in
Server Settings. When it already matches management or data, it verifies the
setting without saving; otherwise it selects the declared value and saves it.
The DATA transition below records the observed live run.

| State | Next transition and prerequisite | Evidence / classification |
| --- | --- | --- |
| ND Active | Start Fabric Controller and choose its feature set. Before a feature set is chosen, NDFC permits only Backup and Restore. | **DOCUMENTED:** the 12.2.2 LAN initial-setup guide calls this Feature Management and specifies Fabric Discovery, Fabric Controller, or SAN Controller personas. |
| NDFC first-run Service Setup | From the Dashboard launcher, open Fabric Controller, choose `Service Setup`, choose `LAN`, choose `Fabric Management Advanced`, review Summary, then Submit. | **OWNER-CONFIRMED / OBSERVED:** this is the authoritative operator lifecycle for this platform. The live 3.2.1i UI showed Advanced as Fabric Builder, Endpoint Locator, and Performance Monitoring; its rendered Summary showed LAN, all three features, and both declared service pools before Submit. The separate documented 12.2.2 optional-feature table does not map Basic/Advanced labels, so that table is contextual rather than a reason to substitute Basic for the owner-confirmed workflow. |
| NDFC Service Setup submitted | Wait for the first-run deployment and services to settle; then open Server Settings. | **OBSERVED:** the live Summary showed default `LAN Device Management Connectivity: Management`, then native `Submit` disabled both Submit and Back. `acs deployment running` reports `ndfc` and `acs health` reports all components healthy. This state is a deployment transition, not an API fault. |
| NDFC Server Settings | Change `LAN Device Management Connectivity` from its initial Management value to `DATA`, save, and wait for mandatory service reassignment. | **DOCUMENTED / OBSERVED:** `Admin → System Settings → Server Settings → Admin` exposes the selector. The live control moved from Management to Data, Save completed, and a fresh UI read returned `Data`. The five DATA persistent IPs exceed the 3.2.x two-address base requirement; the MANAGEMENT pool remains configured for first-run capacity. |
| NDFC API ready | After Service Setup and DATA reassignment settle, use the authenticated documented fabrics GET. An empty list is valid; no fabric is created. | **OBSERVED:** the previously 404 documented fabrics GET now returns HTTP 200 with an empty JSON list after the UI lifecycle completed and DATA persisted. Earlier 404 was `not-yet-available`, not a platform fault or a reason to use an internal endpoint. |

### Clean cycle 1 convergence failure

**OBSERVED / PARTIAL SUCCESS:** The first authorized clean acceptance cycle recreated
only the disposable lab, passed selected-satellite image preflight, started ND-01
on `eve-sat03`, and completed the fresh serial bootstrap plus documented browser
Cluster Bringup Summary submission. The EVE node remains `running`. Read-only QMP
then reported `running` and `io-status: ok` for both QCOW2 devices, with the
expected 16-vCPU/64-GiB process and both TAP-backed NICs. This rules out an
image-readiness, disk-layout, or pre-QEMU launch failure for this cycle.

**OBSERVED / FAILED CONVERGENCE:** After the documented service window had
been exceeded, four final five-minute-spaced bounded checks failed: the first
reached TCP/443 but timed out in the TLS handshake; the remaining three timed
out before a usable HTTPS connection. The serial device exposed no login, error,
panic, or fatal output. This is a guest-service-convergence failure, not an
EVE-host, image-readiness, disk-layout, or pre-QEMU launch diagnosis. Clean
cycle 1 is therefore not a PASS. Preserve the running appliance; do not restart,
repair, or recreate it solely to clear evidence, and do not begin clean cycle 2
without a new, evidence-backed recovery hypothesis.
**OBSERVED / NETWORK DISAMBIGUATION:** A bounded header-only capture on the
management TAP during a failed HTTPS probe observed inbound TCP SYN traffic and
no SYN-ACK from the guest. TAP carrier and error counters were clean. Together
with QMP `running` and both block devices reporting `io-status: ok`, this is
evidence that EVE delivers the attempted management connection to ND-01 but the
guest network/service stack does not answer. It does not identify the internal
Nexus Dashboard component responsible. A VM restart remains a live mutation and
requires explicit owner authorization before it is used as a recovery diagnostic.
**Current next action:** preserve the failed clean-cycle-1 appliance and obtain
a new, evidence-backed guest-service recovery or supported diagnostic path before
retrying. Do not create a fabric, onboard a device, restart, repair, or clean-wipe
the preserved appliance merely to repeat the cycle.

## Current implementation and tests

The worktree currently contains:

- selected-satellite image readiness with bounded stability evidence
- native satellite console routing through configured manager SSH
- Nexus Dashboard structured intent validation
- the live-observed CR-only serial first-boot state machine
- browser-driven documented Cluster Bringup after serial setup, with an explicit post-bootstrap username control when rendered
- a bounded management HTTPS-listener check for serial-phase idempotence
- focused regression coverage for the satellite and initializer paths

Checkpoint verification: focused Nexus Dashboard/satellite coverage passed with
`29 passed, 13 subtests passed`. The complete Windows run produced `303 passed,
206 subtests passed, 24 failed`; all 24 failures are the already-documented inherited
POSIX portability cases (`os.geteuid` and Unix mode-bit assertions), not failures in
the sprint paths. Final acceptance review remains pending.

## Sources

- [Nexus Dashboard API 3.2.1 Getting Started](https://developer.cisco.com/docs/nexus-dashboard/3-2-1/getting-started/)
- [Nexus Dashboard 3.2.1 OpenAPI](https://pubhub.devnetcloud.com/media/nexus-dashboard-api-321/docs/api/nexus-dashboard-321.json)
- [Nexus Dashboard API 3.2.x changelog](https://developer.cisco.com/docs/nexus-dashboard/3-2-1/api-changelog/)
- [Linux KVM deployment before 3.2.2](https://www.cisco.com/c/en/us/td/docs/dcn/nd/3x/deployment/cisco-nexus-dashboard-and-services-deployment-guide-321/nd-deploy-kvm.pdf)
- [Fabric Controller prerequisites, 3.2.1](https://www.cisco.com/c/en/us/td/docs/dcn/nd/3x/deployment/cisco-nexus-dashboard-and-services-deployment-guide-321/nd-prerequisites-ndfc-32x.pdf)
- [Fabric Controller 12.2.2/12.2.3 LAN initial setup](https://www.cisco.com/c/en/us/td/docs/dcn/ndfc/1222/articles/ndfc-overview-initial-setup-lan/overview-and-initial-setup-of-ndfc-lan.html)
- [Fabric Controller 12.2.1 API getting started (VERSION-GATED API reference)](https://developer.cisco.com/docs/nexus-dashboard-fabric-controller/12-2-1/getting-started/)
- [EVE Professional release notes](https://www.eve-ng.net/index.php/documentation/release-notes/)
- [EVE Pro cluster upgrade guidance](https://www.eve-ng.net/index.php/1845-2/eve-pro-upgrade-from-v6-x-to-v7-x/)
- [EVE API single-location rule](https://www.eve-ng.net/index.php/how-to-eve-ng-api/)

## DC1 NX-OS DHCP scope note

**OBSERVED on the active DC1 target:** NX-OS 10.5(2) on the leaf accepted
`feature dhcp`, but the first bounded probe with that feature alone did not
expose IOS-style `ip dhcp pool` local-server syntax. That observation was
initially escalated too early as an architectural blocker.

**OWNER INTENT / CURRENT SPRINT:** preserve the NDFC Leaf Pre-Interfaces
Freeform lines `feature dhcp` followed by `service dhcp`. Do not remove them.
Local DHCP-server capability and lease validation are deferred from the DC1
sprint. DC1 endpoints use their Git-declared static addresses for current
acceptance, so DHCP must not gate switch onboarding, R4 convergence, or R6.

**ENGINE LEARNING:** when a command surface is unexpectedly absent, first check
the exact NOS release's command reference, feature/service prerequisites,
release notes, and relevant vendor guidance, then run a bounded live probe.
Syntax/prerequisite discovery is implementation work rather than an owner
decision. Reconcile validated version-specific findings back into this platform
document so future sprints do not repeat the same discovery.

