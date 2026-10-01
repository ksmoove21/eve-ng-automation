# Engine guidance

This file applies to reusable Python engine code under `src/eve_lab/`.

## Ownership

Put behavior in the narrowest layer that owns it. Use [../../ARCHITECTURE.md](../../ARCHITECTURE.md) as the component map and [../../docs/architecture/STRUCTURE.md](../../docs/architecture/STRUCTURE.md) for technical conventions.

- Generic topology, reconciliation, and lifecycle policy stays generic.
- Platform boot/login/configuration behavior stays in platform-specific adapters or initializers.
- Lab-specific names, addressing, credentials, ASNs, and topology do not belong in generic modules.
- Validation remains read-only.
- Services should compose with the existing lifecycle rather than create parallel orchestration paths.

## Change discipline

Prefer the smallest coherent implementation that satisfies the requirement.

Do not split a module merely because it is large. Refactor when there is evidence of mixed responsibility, duplicated logic, unclear ownership, regression-prone coupling, or poor test isolation.

Preserve public CLI behavior unless the task intentionally changes it.

Keep Windows PowerShell as a first-class controller environment. Isolate Linux-only assumptions to remote EVE-host operations.

## Runtime safety

Distinguish API acceptance, runtime/process state, and guest/controller readiness.

Preserve running-node and concurrency protections. Do not weaken safety policy to make a test pass.

Do not log secrets or full sensitive configurations.

## Validation changes

When modifying validation:

- keep commands observational;
- keep expected criteria human-authored;
- return structured evidence;
- fail closed when required evidence cannot be established;
- keep platform-specific parsers in the platform validator when practical.

## Verification

During iteration, run the focused tests for the changed module first. Use targeted live integration for runtime behavior when the authorized environment exists. Broader regression belongs at the acceptance gate.

Do not fix unrelated failures as part of a scoped change.
