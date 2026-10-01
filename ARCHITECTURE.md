# EVE-NG Automation Architecture

This file is the top-level structural map of the repository. It describes what the system is, which layer owns which behavior, and the boundaries that must remain true. Process rules for coding agents belong in `AGENTS.md` and `docs/architecture/EXECUTION-MODEL.md`.

## System purpose

The project turns explicit lab intent into a reproducible EVE-NG lab and objective acceptance evidence.

```text
lab intent
   |
   v
topology + configs + acceptance criteria
   |
   v
plan / reconcile
   |
   v
node lifecycle
   |
   v
device initialization
   |
   v
read-only validation
   |
   v
evidence for the operator
```

The engine targets an already-existing EVE-NG server. It does not own the hypervisor, DNS, routing, VPN, firewall path, or cloud infrastructure that makes that server reachable.

## Architectural invariants

- The explicit topology is the canonical low-level desired-state contract.
- Desired state and observed runtime state are distinct.
- Reconciliation is preferred to blind recreation.
- Validation never repairs or mutates the network under test.
- Platform-specific behavior stays behind platform-specific boundaries.
- Private environment values do not leak into the reusable public engine.
- A successful API request is not equivalent to a running process or a ready guest.
- Runtime features require real integration evidence when the authorized sandbox can provide it.
- The repository remains operable without an AI agent.

## Repository layers

| Layer | Primary paths | Responsibility |
| --- | --- | --- |
| Intent | `labs/`, external workspaces | Topology, init data, scenarios, acceptance criteria |
| CLI / orchestration | `src/eve_lab/cli.py` | User command surface and high-level dispatch |
| EVE API / topology | `client.py`, `topology.py`, `deploy.py` | API access, compilation of lab objects, reconciliation, lifecycle |
| Console / initialization | `device_console.py`, `initialize*.py`, `palo_ssh.py` | Interactive bootstrap, configuration application, save/commit behavior |
| Services | `dhcp*.py`, `nat*.py`, `securecrt.py`, `backup.py`, `restore.py` | Optional reusable operator capabilities |
| Validation | `validation.py`, `validation_*.py` | Read-only dispatch, platform parsers, evidence and acceptance results |
| Platform capability | `iosxe_ipsec.py`, platform docs | Reusable feature-specific behavior and constraints |
| Tests | `tests/` | Offline regression and behavior verification |
| Runtime state | `.state/` | Generated local artifacts, never authoritative design intent |
| Documentation | `docs/` | Scoped durable knowledge |

## Control flow

### Deployment and reconciliation

`topology.py` loads explicit desired state. `deploy.py` compares it with EVE state and performs safe supported reconciliation.

The reconciler owns generic object lifecycle and safety policy. Platform adapters must not duplicate generic lifecycle policy.

### Node lifecycle

Lifecycle handling must distinguish three separate states:

1. the EVE API accepted the request;
2. the underlying VM/process reached the expected runtime state;
3. the guest or controller is actually ready for the next operation.

A transition is not complete merely because the API returned success.

### Device initialization

Generic orchestration selects the appropriate platform path. Interactive boot/login behavior and configuration semantics belong in platform-specific initializers or console adapters.

Init files contain declarative configuration intent. The engine owns interactive mechanics such as entering configuration mode and saving configuration where that behavior is implemented.

### Validation

`validation.py` owns schema dispatch, grouping, transport orchestration, and reporting.

Platform validators own fixed read-only commands, parsers, and platform-specific evidence. Validation must fail closed when execution cannot establish the required evidence.

Remediation is outside the validation layer.

## Workspace boundary

The engine checkout and active lab workspace may be different repositories.

The public repository owns reusable code, generic fixtures, schemas, tests, and generic documentation.

A private workspace may own:

- real hostnames and domains;
- private addressing;
- environment topology;
- credentials references;
- internal PKI details;
- environment-specific lab definitions.

The `--root` option identifies the active workspace root. Generic modules must not depend on a particular private workspace name or path.

## State authority

For implementation decisions, prefer evidence in this order:

1. current Git and declared intent;
2. current remote EVE/controller state;
3. current guest/controller observations;
4. documented platform behavior applicable to the exact version;
5. historical evidence.

Generated `.state/` artifacts accelerate operation but do not override declared intent or verified live state.

## Extension rules

Add behavior to the narrowest layer that owns it.

Examples:

- a generic reconciliation race guard belongs in `deploy.py`;
- a Catalyst boot dialog belongs in the Catalyst initializer;
- an NX-OS parser belongs in `validation_nxos.py`;
- a lab-specific BGP ASN belongs in the lab/workspace definition;
- a reusable route-based IPsec capability may have a dedicated capability module and platform document.

Do not create a parallel orchestration path when the existing lifecycle can be extended coherently.

## Current structural watch points

Several orchestration modules are intentionally substantial because they own broad cohesive responsibilities. File size alone is not a reason to split them.

Refactor when evidence shows one or more of these conditions:

- unrelated responsibilities are coupled;
- a change routinely requires touching multiple unrelated branches in the same module;
- tests cannot isolate behavior without broad mocking;
- platform-specific logic leaks into generic orchestration;
- duplicated lifecycle or validation logic appears across modules;
- a module becomes a frequent source of regressions because ownership is unclear.

Track those conditions, not arbitrary line-count thresholds.

For detailed engineering conventions, see [docs/architecture/STRUCTURE.md](docs/architecture/STRUCTURE.md).
