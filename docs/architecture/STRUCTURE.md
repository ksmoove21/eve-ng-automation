# Repository structure and engineering conventions

This repository extends the upstream `wcmder/eve-ng` project into a reusable,
Git-driven EVE-NG lab automation platform.

It is not a definition of one lab. The engine must remain reusable across labs,
vendors, and topologies. Concrete lab intent belongs under `labs/`; reusable
automation belongs under `src/eve_lab/`.

Read this file before changing the repository. Preserve unrelated user edits.

## Project intent and execution model

The project purpose and human/agent division of responsibility live in
[PROJECT-INTENT.md](PROJECT-INTENT.md).

The sprint lifecycle, sandbox authority, and stop conditions live in
[EXECUTION-MODEL.md](EXECUTION-MODEL.md).

This file owns repository structure and engineering conventions.

## Core invariants

- Do not silently change human intent to make deployment or validation pass.
- Validation is observational. It must not repair, configure, restart, or mutate
  the network under test.
- Re-running an operation should be idempotent where practical.
- Prefer safe reconciliation over blind recreation.
- Preserve running nodes unless a requested change cannot safely occur live.
- Distinguish desired state from observed runtime state.
- Destructive operations must be explicit and narrowly scoped.
- Keep credentials and secrets out of Git.
- Treat designated disposable EVE development/test labs as part of the test
  harness. When the sprint requires live proof, use them without an extra
  permission checkpoint.
- Do not extend that authority to parent or persistent infrastructure unless
  the task explicitly authorizes it.
- Preserve upstream behavior unless a change is intentional, understood, and
  tested.
- Prefer reusable capabilities over one-off lab-specific code.

## Development sandbox and autonomy

See [EXECUTION-MODEL.md](EXECUTION-MODEL.md). The designated disposable EVE
development lab is part of the integration-test harness; parent and persistent
infrastructure remain outside that standing authority.

## Repository layers

| Path | Responsibility |
| --- | --- |
| `src/eve_lab/` | Reusable engine, API client, lifecycle, console, validation |
| `labs/` | Concrete topology, init configuration, acceptance intent |
| `tests/` | Offline behavior and regression tests |
| `config/` | EVE server definitions and non-secret runtime configuration |
| `docs/` | Environment notes, roadmap, operational procedures |
| `.state/` | Generated local runtime artifacts; never source of truth |

Keep these boundaries explicit.

Lab-specific addressing, names, routing design, and acceptance criteria belong
under `labs/<lab>/`. Do not hardcode them into generic Python modules.

## External/private workspaces

The installed engine and the active lab workspace may be different directories
or different Git repositories.

The global `--root` option identifies the workspace root containing runtime
inputs such as `labs/`, `config/`, `.env`, and generated `.state/` data.
Do not assume `--root` is the engine source checkout.

This separation is intentional: reusable engine code and generic regression
fixtures may remain public while environment-specific or sensitive labs live in
a private repository. Generic Python modules must not depend on a particular
workspace name, hostname, private domain, PKI name, or lab naming convention.

## Control-platform support

The project is operated from Windows PowerShell and may also be used from
macOS and Linux.

New code and tests must not accidentally assume a POSIX-only control host.

Examples of platform-sensitive behavior include:

- `os.geteuid()`
- Unix permission-bit assertions
- symlink behavior
- path separators
- mapped drives and UNC paths
- shell-specific quoting
- executable lookup and virtual-environment activation

When functionality is inherently Linux-only because it operates on the EVE host
itself, isolate that assumption to the remote operation rather than requiring the
local controller to be Linux or macOS.

Windows PowerShell is a first-class supported control environment.

## Topology and lab definitions

The explicit topology model remains the canonical low-level deployment model.

A lab may later be generated from a higher-level semantic specification, but
that semantic layer should compile into the explicit topology rather than
replace it.

Topology definitions should describe:

- lab identity and remote folder
- nodes and exact image selections
- networks
- links
- layout coordinates when useful
- validation intent

Do not derive or invent design intent merely because a device can support it.

Exact image names are deployment inputs. Preflight must fail clearly when a
requested image is unavailable rather than silently selecting a different image.

Canvas layout is declarative when coordinates are provided. Do not treat visual
placement as authoritative runtime-only state.

## Reconciliation behavior

`eve apply` is a reconciler, not a one-shot creation script.

### EVE CPU Limit policy

EVE-NG CPU Limit is disabled by default for automation-managed nodes
(`cpulimit=0`). The limiter may suspend QEMU execution and interfere with
deterministic boot and readiness behavior. This is a repository-wide runtime
rule and must not be implemented as platform-specific adapter logic.

The reconciler enforces `cpulimit=0` for newly created and stopped managed
nodes, independent of EVE template defaults. Running nodes remain unchanged
under the existing deferral/race protection policy. There is no opt-in to CPU
limiting in the topology schema. Optional `icon` values are checked against the
live template inventory before writes.

Expected behavior:

- create missing declared objects
- verify existing objects
- make safe supported updates
- preserve running objects when mutation would be unsafe
- defer unsafe work with structured reasons
- prune undeclared stopped objects when pruning is enabled
- avoid duplicate nodes, links, or networks
- detect conflicting remote state instead of silently overwriting it
- re-check state before writes when concurrency could make a prior decision
  unsafe

Do not weaken existing race protections merely to make an apply succeed.

Running-state protection is an engine safety policy, not an assumption about
EVE-NG Community Edition. EVE-NG Pro capabilities may later permit additional
safe live operations, but those should be implemented explicitly and tested.

## Lifecycle behavior

Lifecycle commands should distinguish:

- API request accepted
- VM/process actually running or stopped
- guest/device actually ready

A successful EVE start request is not equivalent to a ready network device.

Lifecycle code should use bounded polling, explicit timeouts, and useful failure
messages. Avoid unbounded retries.

## Device initialization

Initialization is a configuration operation and may mutate guests.

For Cisco IOS XE:

- init files contain configuration-mode commands only
- the engine owns entering/exiting configuration mode
- the engine owns credential/VTY bootstrap where currently implemented
- the engine owns configuration save verification
- do not require init files to contain interactive commands such as
  `configure terminal`, `write memory`, or `copy run start`

Device-specific logic should remain isolated from generic topology logic.

Do not log secrets or full device configurations in errors.

## Validation architecture

Validation answers one question:

> Does the deployed lab currently satisfy the acceptance criteria declared by
> the human?

Validation must be read-only.

The lab definition owns the expected behavior. Generic Python code owns how
those expectations are measured.

Implemented primitives include:

- interface state and address
- ping reachability
- route presence or absence (IPv4, optional VRF and next hop)
- default route (IPv4, optional VRF)
- BGP neighbor state (IPv4/IPv6 unicast, optional VRF)
- OSPF neighbor state (global IPv4)
- IS-IS adjacency (neighbor name or system ID)
- VRF reachability (IPv4)
- MTU/DF reachability (IPv4)

`validation.py` owns schema dispatch, node grouping, transport orchestration
and reports. Platform adapters own their schemas, fixed read-only commands and
structured parsers. Registered adapters include IOS XE `c8000v`, Catalyst
9000v UADP `cat9kvuadp`, supported Nexus 9000v templates, and PAN-OS firewall
validation; future platform adapters must explicitly define and test their
capabilities.
See [../operations/validation.md](../operations/validation.md) for exact fields and limitations.

Checks are required by default. Only an explicit human-authored
`required: false` makes a failed check advisory; its failure remains visible.
Never infer optionality or relax thresholds from observed output.

Validation uses guarded console authentication: refuse setup/configuration
prompts and request prompt redisplay without submitting pending input. Device
initialization retains its existing login behavior. Terminal pagination is a
session setting; probes and show commands do not change configuration.

Expected future primitives include:

- MPLS/LDP state
- MP-BGP VPNv4/VPNv6 state
- GRE/tunnel state
- bounded generic command assertions where a dedicated primitive is not yet
  available

Prefer structured parsers over brittle substring checks.

Each validation check should return structured evidence, not merely true/false.
Reachability checks share a bounded three-attempt policy with 10 seconds between
failed attempts; that timing never lowers a human-authored pass threshold.

A failed acceptance check should cause `eve validate` to return a nonzero exit
status.

Validation must never:

- alter device configuration
- clear protocol state
- bounce interfaces
- restart nodes
- modify topology
- change expected criteria to match observed state

If a test fails, report the failure.

## Acceptance evidence

Where practical, return evidence that explains why a check passed or failed.

Examples:

```json
{
  "name": "r1-gi1",
  "type": "interface",
  "result": "pass",
  "evidence": {
    "interface": "GigabitEthernet1",
    "ip_address": "10.255.0.1",
    "status": "up",
    "protocol": "up"
  }
}
```

and:

```json
{
  "name": "r1-to-r2",
  "type": "ping",
  "result": "pass",
  "evidence": {
    "destination": "10.255.0.2",
    "success_rate": 100
  }
}
```

Do not expose credentials, enable secrets, or sensitive configuration in
validation evidence.

## Testing

Update tests with engine changes.

Separate:

1. offline/unit behavior
2. live EVE integration validation

Offline tests are the first validation layer, not the completion condition for
runtime features. If a capability is intended to deploy, initialize, operate,
or validate an EVE guest and an appropriate image exists in the authorized
development sandbox, successful live integration is required before that
capability is considered proven.

A unit test must not require a live EVE server unless explicitly identified as
an integration test.

New tests should run on Windows when the tested feature is intended to be
controller-platform independent.

Do not mark the repository healthy merely because one platform-specific test
suite is green. Conversely, do not treat known POSIX-only inherited tests as a
runtime EVE failure.

Known inherited portability debt includes POSIX assumptions around
`os.geteuid()` and Unix chmod semantics. Fix this deliberately rather than
papering over failures.

For new capabilities, add focused tests before broad integration testing.

## Error handling

Prefer specific, actionable failures.

Good errors identify:

- object or node
- expected condition
- observed condition where safe
- whether partial changes may remain
- whether retry is appropriate

Do not include passwords, secrets, or full sensitive command output.

Avoid catch-all behavior that converts every failure into the same generic
message when the code can safely distinguish causes.

## Secrets and authentication

Secrets belong in the local environment and existing `.env` pattern.

Never commit:

- EVE passwords
- device passwords
- enable secrets
- SSH private keys
- API tokens

Repository examples may include variable names but not real secret values.

System SSH host-key verification should remain enabled. Do not add insecure
fallbacks merely to bypass trust errors. A previously unseen lab-device key may
be enrolled only with explicit owner authorization, scoped to the exact device
address through an already verified EVE connection. Report its fingerprint and
never replace a saved key automatically; a changed key remains a hard failure.

TLS validation should remain enabled. Private/internal deployments may use a
private CA, but the control workstation should trust that CA rather than disabling verification.

## EVE server assumptions

The engine targets an already-existing EVE-NG server.

It does not provision:

- EVE-NG itself
- DNS
- routing
- VPN/WireGuard
- cloud infrastructure
- firewall paths

Those are prerequisites outside the engine boundary.

Keep the automation hosting-platform agnostic. Do not introduce Azure, AWS, or
other provider-specific assumptions into the reusable engine unless a future
feature explicitly requires an optional provider integration.

## Branch and Git workflow

Do not develop substantial features directly on `main`.

Use focused feature branches.

Recommended flow:

```text
main
  -> feature branch
  -> implementation
  -> focused offline tests
  -> designated-sandbox live integration
  -> diagnose / repair / retest until acceptance passes
  -> final regression tests
  -> review diff and evidence
  -> merge
```

Live testing in a designated disposable EVE development lab is part of the
normal sprint and does not require a second approval checkpoint. The owner
retains approval for merges and for operations outside the sandbox boundary.

Codex or another coding agent may implement changes, but Git remains the durable
record of both intent and implementation.

Preserve unrelated edits and existing staged work.

## Agent responsibilities

Before coding:

1. read this file
2. inspect the existing implementation
3. identify the owning architectural layer
4. state or infer the acceptance criteria from repository intent
5. avoid unrelated refactors

While coding:

- make the smallest coherent change that satisfies the requirement
- preserve existing public CLI behavior unless intentionally changing it
- add tests for new behavior
- keep user-specific values in lab definitions, not generic engine code
- keep validation read-only
- preserve safety checks

After coding:

1. run relevant focused offline tests;
2. when applicable, execute the feature against the designated EVE test lab;
3. diagnose and repair failures that remain within the agreed intent;
4. repeat testing until the defined acceptance criteria pass or a true stop
   condition is reached;
5. run final regression tests and review the diff;
6. report what changed, what was tested, and the live evidence;
7. identify only genuine unresolved blockers or verification that could not be
   performed;
8. do not claim live success without live evidence.

Do not return control merely to announce that an intermediate phase completed.
The unit of work is the sprint and its acceptance criteria, not an individual
prompt or command.

## Current proven baseline

The `iosxe-baseline` lab is the first known-good operational reference.

It has demonstrated:

- Windows PowerShell control
- HTTPS EVE API access
- EVE-NG Pro 7.2.0-4
- C8000V image discovery
- declarative lab creation
- direct-link bridge synthesis
- explicit node layout
- start/stop lifecycle
- safe repeated apply
- running-node preservation
- stopped-node reconciliation
- Git-backed IOS XE init files
- SSH to the EVE host
- Telnet console automation
- configuration save
- interface-state parsing
- declarative interface acceptance checks
- declarative bidirectional ping acceptance checks
- machine-readable PASS/FAIL validation

Treat this lab as a regression fixture for future engine changes.

Do not casually expand it into a large feature lab. Prefer additional focused
labs when new behaviors need isolated proof.

## Long-term direction

The engine should evolve toward four clear layers:

1. intent
2. compilation/generation
3. runtime/reconciliation
4. validation/evidence

A future higher-level lab specification may express semantic networking intent
such as routing domains, BGP relationships, VRFs, or transport roles. That layer
should compile deterministically into explicit topology, configuration, and
acceptance criteria.

AI may assist with design and implementation, but the repository must remain
understandable and operable without AI.

## Lessons learned changelog

Record reusable implementation, test, and live-operation lessons in
[`../lessons/README.md`](../lessons/README.md) at meaningful sprint
boundaries or when live testing reveals a reusable platform/environment
behavior. Do not append an entry merely because an intermediate prompt or
implementation step completed.

Failures encountered during a sprint should be captured as engineering evidence
and folded into the final lesson when they reveal something reusable. Continue
remediation without returning control solely to document the failure.

A completed entry should closely mirror the sprint completion report: outcome
and root cause, summarized code and file changes, exact test results,
offline-versus-live evidence, remaining limitations or verification, and
commit/push/merge status. Code diffs may be summarized; do not omit the other
review evidence.

This changelog is the only repository file an agent may automatically commit and
push. Such commits must stage only `docs/lessons/README.md`; all engine, lab,
test, documentation, and unrelated working-tree changes remain outside that
commit. A task-specific instruction not to merge still applies to the working
branch.

## Platform service configuration

Optional `configs/NODE-services.cfg` files extend an existing initializer with
configuration-mode commands before its save/commit. They use the same command
restrictions and secret handling as init CFG files. Structured Nexus and Catalyst
bootstrap intent remains authoritative for management/bootstrap; lab-specific
VLANs, vPC, and security intent stay in the active workspace.

The IOS-XE `kg-ipsec` init profile is documented in
[IOS-XE KG](../platforms/iosxe-kg.md). It is a semantic configuration profile,
not a separate platform adapter or a generic role framework.
