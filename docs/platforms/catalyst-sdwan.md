# Catalyst SD-WAN factory workflow

The `sdwan-factory` command builds a declared Catalyst SD-WAN lab from EVE
objects through controller certificates, PAYG edge onboarding, and read-only
fabric acceptance. The implementation tested with Catalyst SD-WAN control
components 20.15.1 and C8000V IOS XE SD-WAN 17.16.01a. The topology, image
names, addresses, organization, and live guard belong in a private workspace.

Install the package from this repository and select that workspace with
`--root`. The workspace must contain `labs/<lab>/topology.yaml`,
`labs/<lab>/intent.yaml`, `config/servers.yaml`, and a matching
`labs/<lab>/live-guard.yaml`. Set `EVE_ENV_FILE` to an absolute private file
containing the EVE web and SSH connection variables referenced by the server
configuration. Provide `CISCO_USERNAME`, `CISCO_PASSWORD`, and
`CISCO_ENABLE_SECRET` in the process environment. Keep all credentials outside
Git.

```text
eve --root <private-workspace> sdwan-factory <lab> --check
eve --root <private-workspace> sdwan-factory <lab> --destroy-first --timeout 3600
```

`--check` compiles the workflow without live access. `--destroy-first` deletes
the exact guarded disposable lab, then rebuilds it from intent; use it only
when a new factory generation is intended. An interrupted run resumes the same
EVE generation with the second command **without** `--destroy-first`:

```text
eve --root <private-workspace> sdwan-factory <lab> --timeout 3600
```

The default phase timeout is 3,600 seconds to accommodate a fresh Manager
install. The runner binds one-shot PAYG generation, controller-mode transition,
and activation records to EVE node UUIDs in the private ignored `.state/`
directory. Preserve that directory when resuming a generation. A newly
destroyed lab receives fresh UUIDs and a fresh ledger generation.

Acceptance requires valid Manager, Validator, and Controller certificates and
control state; exact edge configuration; installed root and device
certificates; authorized PAYG identities; active control and OMP; and two UP
BFD sessions to every other edge. The runner emits
`CATALYST_SDWAN_FABRIC_READY` only after those read-backs pass.

The current factory compiler and validator target the three-edge R1 node and
Cloud0 layout; a different topology needs its own compiler contract. This is
an exact-version reference, not a compatibility claim for other releases or
EVE images. Cold boot and post-activation console login can require
a bounded resume of the same generation. A node-only restart may be needed if
IOS XE does not redisplay a usable login prompt; the restart does not authorize
replaying its PAYG token. The runner does not automatically restart a node in
that condition.


## Controller-only plans

`eve_lab.sdwan_control_intent` compiles a controller-only plan from an explicit
topology. It configures controller identity and VPN 0 transport, with VPN 512
only when that controller has an explicit management attachment. Before static
VPN 0 addressing, it removes IPv4 and IPv6 DHCP clients from the declared
transport interface. It never creates aggregation, edge, Cloud0, or
transport-fabric actions. The initializer
can consume that compiled plan directly, so this narrow workflow does not alter
the R1 factory compiler contract.

The console/transaction adapter is field-qualified for control release
20.15.1. Controller-only plans are offline-tested; field acceptance remains
scoped to each declared topology. Disabled DHCP clients are omitted even in
the 20.15.1 details view, so readback proves their absence within the declared
transport interface. Cisco's [Compatibility Matrix Tool](https://www.cisco.com/c/en/us/support/cloud-systems-management/sd-wan/products-device-support-tables-list.html)
documents that control-plane versions must match or exceed the edge-equivalent
release. Its 20.15.1 matrix includes C8000V IOS XE SD-WAN 17.15.1a. This is not
a support claim for 20.12 releases or mixed-version deployments.

## Authentication rejection during first boot

Cisco documents five consecutive failed password attempts and a 15-minute
account lockout for Manager 20.9.1 and later. Console initialization stops on
an explicit credential rejection; it does not retry that failure as a boot
transition. Bounded resume remains available for transient boot/CLI failures.
After a rejected login, preserve the UUID-bound first-boot state and inspect
the transition before submitting another credential. A password-submission
record alone does not prove that the new password was accepted or persisted.

Source: [Cisco 20.x user authentication guide](https://www.cisco.com/c/en/us/td/docs/routers/sdwan/configuration/system-interface/vedge-20-x/systems-interfaces-book/user-access-authentication.html).
Lockout behavior is DOCUMENTED; a returned login prompt is an observed
rejection signal, not by itself proof of lockout.

## Explicit edge plans and controller PKI

`eve_lab.sdwan_edge_intent` compiles c8000v 17.15.01a baseline transactions
against declared direct transport peers. It accepts GiN/GigabitEthernetN
names, resolves them to one native port, and rejects duplicate identities,
addresses, colors and conflicting attachments. Transport plans include default
and controller-prefix routes with declared administrative distances; default
distance 1 is omitted in generated CLI to match canonical IOS XE readback.
The service-LAN transaction is optional. Explicit service interfaces create
their IPv4 VRFs; an enrollment-only plan creates no service-VPN state.

The Manager API/PKI helpers accept an explicit Manager node name while their
original factory default remains available. FIELD-TESTED on control release
20.15.1: a topology-bound three-controller plan completed identity/transport,
Manager VPN512, Manager-local CA, enterprise trust, pinned HTTPS/API settings,
and Manager-owned CSR/sign/install lifecycle. All three exact records became
READY/valid with installed valid certificates and reciprocal DTLS relationships.
This does not qualify cEdge enrollment, service-VPN payload or BFD/data behavior.


## Active transport routes

Cisco documents a VPN0 default route for each transport tunnel so the Validator
is reachable through each WAN ([network interface guide](https://www.cisco.com/c/en/us/td/docs/routers/sdwan/configuration/system-interface/vedge-20-x/systems-interfaces-book/configure-interfaces.html)).
FIELD-TESTED on C8000V 17.15.01a: two active transport next hops require both
routes to be installed. A higher-distance static route was absent from the RIB;
equal-distance routes installed both next hops. After correcting an independent
access-VLAN mismatch, both interface-sourced Validator probes passed. This
qualifies underlay reachability only; control and BFD acceptance remain separate.
Validate gateway ARP and the intermediate switch VLAN before enrollment.


C8000V post-mode bootstrap distinguishes a transient prompt timeout from an
explicit credential rejection. Only an explicit rejection permits the bounded
factory-password initialization path. Once password initialization is recorded
as complete, another rejection stops; it does not submit factory credentials
or repeat configured credentials. This safeguard is offline-tested separately
from guest boot and console availability.

Atomic factory-ledger writes fsync a complete temporary file before replacing
its destination. On Windows/SMB, transient replacement denials with Windows
error 5, 32, or 33 receive at most six attempts over three seconds. Other errors
and exhausted retries propagate immediately; no in-place overwrite is used.
One-shot PAYG generation and activation must still wait for a successful durable
save. A failed pre-submit save does not authorize replay of an ambiguous API
request: reconcile the saved inventory snapshot and the exact failure point.

For service-side BGP on C8000V IOS XE 17.15.01a, configure an RD under the
service VRF before creating its BGP address family. Field validation rejected
an otherwise parsed transaction with `VRF ... does not have an RD configured`;
the transaction was aborted. Cisco's [17.x BGP configuration guide](https://www.cisco.com/c/en/us/td/docs/routers/sdwan/configuration/routing/ios-xe-17/routing-configuration-guide-17-x/border-gateway-protocol/configure-bgp.html)
includes `rd 1:<VPN>` in its service VRF example. This is a local VRF/BGP
prerequisite; it does not authorize cross-VRF route-target imports or exports.

On IOS XE 17.15.01a, asynchronous `%SMART_LIC` messages can appear during a
successful SCP transfer and contain the word `error`. The SCP result classifier
excludes those diagnostic lines while retaining transfer failures and requiring
a copied-byte result. Field validation independently confirmed the destination
file's nonzero size and SHA-256 match to the source CA before installation;
the classifier result alone is insufficient proof of certificate fidelity.
