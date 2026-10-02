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
