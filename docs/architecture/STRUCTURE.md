# Repository structure and engineering conventions

This document owns durable technical conventions for the reusable engine. It intentionally does not own agent workflow, sprint autonomy, research policy, or execution-plan behavior. Those live in `AGENTS.md` and [EXECUTION-MODEL.md](EXECUTION-MODEL.md).

See [../../ARCHITECTURE.md](../../ARCHITECTURE.md) for the top-level component map.

## Repository boundaries

| Path | Responsibility |
| --- | --- |
| `src/eve_lab/` | Reusable engine, API client, lifecycle, initialization, services, validation |
| `labs/` | Public generic topology fixtures, init configuration, acceptance intent |
| `tests/` | Offline behavior and regression tests |
| `config/` | EVE server definitions and non-secret runtime configuration |
| `docs/` | Durable scoped knowledge |
| `.state/` | Generated local runtime artifacts; never design source of truth |

Lab-specific addressing, names, routing design, and acceptance criteria belong in lab/workspace data, not generic Python modules.

## External/private workspaces

The installed engine and active lab workspace may be different directories or repositories.

The global `--root` option identifies the workspace containing inputs such as `labs/`, `config/`, `.env`, and generated `.state/` data. Do not assume `--root` is the engine source checkout.

Generic modules must not depend on a private workspace name, hostname, domain, PKI name, or naming convention.

## Control-platform portability

Windows PowerShell is a first-class controller environment. macOS and Linux are also supported.

New code and tests must account for platform-sensitive behavior such as:

- `os.geteuid()` and POSIX permission semantics;
- path separators, mapped drives, and UNC paths;
- symlink behavior;
- shell quoting;
- executable lookup and virtual-environment activation.

Linux-only behavior required on the remote EVE host must remain isolated to the remote operation.

## Topology contract

The explicit topology model is the canonical low-level desired-state contract.

A future semantic layer may generate explicit topology, configuration, and validation artifacts, but it must not make runtime behavior dependent on hidden AI inference.

Topology definitions may declare:

- lab identity and remote folder;
- exact node/image selections;
- networks and links;
- layout coordinates;
- scenarios;
- initialization intent;
- validation intent.

Exact image names are deployment inputs. Preflight should fail clearly when a requested image is unavailable instead of silently selecting another image.

Do not derive design intent merely because a device can support it.

## Reconciliation

`eve apply` is a reconciler, not a one-shot creation script.

Expected behavior:

- create missing declared objects;
- verify existing objects;
- make safe supported updates;
- preserve running objects when mutation would be unsafe;
- defer unsafe work with structured reasons;
- prune undeclared stopped objects when pruning is enabled;
- avoid duplicate nodes, links, or networks;
- detect conflicting remote state instead of silently overwriting it;
- re-check state before writes when concurrency may invalidate an earlier decision.

Do not weaken race protections merely to make an apply succeed.

### EVE CPU Limit

Automation-managed QEMU nodes use `cpulimit=0` by default. EVE CPU limiting may suspend the complete QEMU process and interfere with deterministic boot/readiness behavior.

The reconciler enforces `cpulimit=0` on creation and safe stopped-node reconciliation. Native IOL records do not persist this QEMU setting.

Running-node protections remain in effect. The topology schema does not currently expose an opt-in to CPU limiting.

This is a generic EVE runtime policy, not a platform-adapter behavior.

## Lifecycle semantics

Lifecycle code must distinguish:

1. API request accepted;
2. VM/process reached the intended runtime state;
3. guest/controller became ready.

Use bounded polling, explicit timeouts, and actionable failure messages. Avoid unbounded retries.

## Device initialization

Initialization may mutate guests and therefore belongs outside validation.

For IOS XE init files:

- files contain configuration-mode commands;
- the engine owns entering/exiting configuration mode;
- the engine owns implemented credential/VTY bootstrap;
- the engine owns save verification;
- init files should not require interactive wrapper commands such as `configure terminal` or `write memory`.

Device-specific login, boot-dialog, save/commit, and parser behavior must remain isolated from generic topology logic.

Do not expose secrets or full sensitive configurations in errors.

## Platform service configuration

Optional `configs/NODE-services.cfg` files extend an existing initializer with configuration-mode commands before save/commit.

They use the same command restrictions and secret handling as init configuration.

Structured management/bootstrap intent remains authoritative for platforms that provide it. Lab-specific VLAN, vPC, security, routing, and service intent stays in the lab/workspace.

The reusable IOS/IOS-XE route-based IPsec profile is documented in [../platforms/iosxe-ipsec.md](../platforms/iosxe-ipsec.md). It is a capability profile, not a generic role framework.

## Validation architecture

Validation answers:

> Does the deployed lab currently satisfy the acceptance criteria declared by the human?

Validation is observational.

The lab definition owns expected behavior. Generic code owns orchestration and measurement. Platform adapters own fixed read-only commands and structured parsers.

`validation.py` owns schema dispatch, node grouping, transport orchestration, and report assembly.

Registered validation paths include IOS XE, Catalyst 9000v UADP, supported Nexus 9000v templates, and PAN-OS. Exact fields and limitations are documented in [../operations/validation.md](../operations/validation.md).

Checks are required by default. Only explicit human-authored `required: false` makes a failed check advisory. Its failure must remain visible.

Never infer optionality or relax a threshold from observed output.

Validation may use safe session operations such as prompt redisplay or terminal pagination control, but it must not alter persistent device configuration.

### Validation must never

- configure the device;
- clear protocol state;
- bounce interfaces;
- restart nodes;
- modify topology;
- rewrite expected criteria to match observed state.

### Evidence

Checks should return structured evidence sufficient to explain pass/fail without exposing sensitive data.

A failed required check must produce a nonzero validation result.

Prefer structured parsers over brittle substring checks.

## Testing

Separate:

1. offline/unit behavior;
2. live EVE/NOS integration.

A unit test must not require a live EVE server unless explicitly marked as integration behavior.

Add focused tests for new behavior before broad regression testing.

Runtime capabilities require successful live integration when an appropriate authorized image/environment exists.

Do not declare the repository unhealthy solely because of a known unrelated portability limitation, and do not declare it healthy because one platform-specific suite is green.

Known inherited portability debt such as POSIX-only permission assumptions should be fixed deliberately rather than hidden.

## Error handling

Prefer failures that identify:

- the affected object/node;
- expected condition;
- safe observed condition;
- whether partial change may remain;
- whether retry is appropriate.

Do not collapse distinguishable failures into a single generic message when the distinction is useful for recovery.

## Secrets and trust

Secrets belong in the local environment and existing `.env` pattern.

Never commit:

- EVE or device passwords;
- enable secrets;
- API tokens;
- private keys;
- environment-specific credentials.

SSH host-key verification and TLS validation should remain enabled.

A previously unseen disposable-lab device key may be enrolled only through the explicitly authorized trust workflow. A changed saved key remains a hard failure unless the owner authorizes replacement after verification.

Private/internal PKI should be trusted by the controller rather than bypassed.

## EVE server assumptions

The reusable engine targets an already-existing reachable EVE-NG server.

The engine does not provision:

- EVE-NG itself;
- the hypervisor;
- DNS;
- routing;
- VPN/WireGuard;
- cloud infrastructure;
- external firewall paths.

Keep provider-specific infrastructure automation outside the reusable engine unless a future optional integration explicitly requires it.

## Architectural change standard

Change the narrowest layer that owns the behavior.

Avoid unrelated refactors during feature work. Refactor when concrete evidence shows coupling, duplicated responsibility, unclear ownership, or testability problems.

When a durable technical convention changes, update this document or the narrower platform/operations document that owns it.
