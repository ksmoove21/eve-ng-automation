# Repository guidance

Read [structure.md](structure.md) before changing this repository.

This project extends the operating model of upstream `wcmder/eve-ng`; it does
not replace it. Preserve the inherited declarative lab workflow and extend it
with additional platform support, validation, orchestration, and reusable
network-lab capabilities.

Follow `structure.md` for architecture, lab-definition, reconciliation,
validation, testing, platform-support, execution-boundary, and Git workflow
conventions.

## Sprint execution contract

Treat an agreed development task as a sprint, not a sequence of permission
checkpoints. Once the objective and acceptance criteria are clear, continue
through implementation, offline tests, applicable live integration tests,
remediation, regression testing, and evidence collection without returning
control merely because an intermediate step completed or failed.

A failed test is an input to the next engineering iteration, not a handoff
point. Diagnose it, repair the implementation when the repair is within scope,
and rerun the relevant tests.

Use these execution zones:

- **Repository/offline work:** autonomous.
- **Designated disposable EVE development/test labs:** autonomous. Codex may
  plan, apply, start, stop, initialize, configure, validate, reset, recreate,
  and delete lab objects and guest devices when needed to prove the sprint.
- **Parent or persistent infrastructure:** requires explicit task authorization.
  This includes the EVE host OS, vSphere, physical network devices, production
  firewalls/routing, shared services, and persistent labs not designated for
  automation testing.

Do not ask for intermediate confirmation for actions already covered by the
current sprint and execution zone. Stop only when continuing would materially
change the agreed architecture or intent, cross an unauthorized boundary,
require unavailable credentials/resources, or remain technically blocked after
reasonable remediation.

Preserve unrelated user edits. Do not weaken validation or silently change
human-authored intent to make a lab pass. Do not claim live success without
live evidence.

When the owner changes a repository convention, update `structure.md`
alongside the implementation.
