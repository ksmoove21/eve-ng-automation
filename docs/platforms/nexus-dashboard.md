# Nexus Dashboard / Fabric Controller

## Active in-place handoff checkpoint

This is an unfinished sprint checkpoint captured on 2026-10-01. Preserve the
running discovery appliance and continue from this state.

## Live target and release

- **LIVE-TESTED:** EVE template `nd`, image `nd-9.3.2.1c`.
- **LIVE-TESTED:** the appliance serial setup utility identifies the release as
  **Nexus Dashboard 3.2.1i**. The EVE image suffix is not the appliance release.
- **VERSION-GATED / FIELD-TEST REQUIRED:** Nexus Dashboard 3.2.2m has not been
  installed or live-tested.
- **LIVE-TESTED:** `ND-01` is running (`status: 2`) in disposable lab
  `nexus-dashboard-disposable` on `eve-sat03` (satellite ID 3), with 16 vCPU,
  65536 MiB RAM, two NICs, `cpulimit=0`, and image `nd-9.3.2.1c`.
- **LIVE-TESTED:** stable readable `virtioa.qcow2` (45 GiB virtual) and
  `virtiob.qcow2` (500 GiB virtual) satisfy the required boot/data disk layout.

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
intent uses two DNS providers and an FQDN NTP target. Persistent/service-IP
configuration, Fabric Controller readiness, and DATA selection remain pending
post-cluster validation.

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
are healthy` for `acs health`, including a fresh bounded recheck. This confirms
the expected Controller deployment mode and healthy platform components. Cisco
release notes identify Fabric Controller **12.2.2.241** as the service bundled
with Nexus Dashboard 3.2.1i; 12.2.3 is not the live target.

**OBSERVED / CONVERGENCE:** The documented Fabric Controller fabrics GET
`/appcenter/cisco/ndfc/api/v1/lan-fabric/rest/control/fabrics` remains HTTP 404
across bounded, token-authenticated rechecks after the documented 30-minute
startup window. The Dashboard platform and node APIs remain `Active`; this is
specifically Fabric Controller service-gateway registration absence, not Cluster
Bringup, DNS/NTP, management/data addressing, external-IP, or API-login failure.
Do not create a fabric, onboard a device, or use an undocumented app endpoint
as a workaround.

**Current next action:** continue bounded readiness polling; if the authenticated gateway remains absent despite the healthy `ndfc` deployment, obtain Cisco-supported service-lifecycle evidence or owner authorization for a demonstrated Fabric Controller repair path;
then discover the running `/apidocs/`, use only documented cluster/node/external
IP and Fabric Controller APIs, configure the pending intent, implement
read-only validation, and run two complete clean build/bootstrap/validation
cycles. The preserved running appliance must not be deleted merely for
observation.
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
- [Fabric Controller prerequisites, 3.2.x](https://www.cisco.com/c/en/us/td/docs/dcn/nd/3x/deployment/cisco-nexus-dashboard-and-services-deployment-guide-321/nd-prereq-ndfc.html)
- [Nexus Dashboard Fabric Controller API 12.2.3](https://developer.cisco.com/docs/nexus-dashboard-fabric-controller/12-2-3/)
- [EVE Professional release notes](https://www.eve-ng.net/index.php/documentation/release-notes/)
- [EVE Pro cluster upgrade guidance](https://www.eve-ng.net/index.php/1845-2/eve-pro-upgrade-from-v6-x-to-v7-x/)
- [EVE API single-location rule](https://www.eve-ng.net/index.php/how-to-eve-ng-api/)
