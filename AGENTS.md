# Repository guidance

This repository extends `wcmder/eve-ng` into a reusable EVE-NG lab automation engine. Keep the engine generic, keep environment-specific intent outside the engine, and optimize for repeatable evidence rather than chat continuity.

## Source-of-truth order

Use this order when sources disagree:

1. the current Git branch, working tree, and live observed state;
2. the active ExecPlan for the current sprint, when one exists;
3. [ARCHITECTURE.md](ARCHITECTURE.md) for system boundaries and component ownership;
4. [PROJECT-INTENT.md](docs/architecture/PROJECT-INTENT.md) for project purpose;
5. [STRUCTURE.md](docs/architecture/STRUCTURE.md) for durable engineering conventions;
6. [EXECUTION-MODEL.md](docs/architecture/EXECUTION-MODEL.md) for long-running work, live testing, research, retry, and stop conditions;
7. platform, workflow, and operations documents for their scoped behavior;
8. completed ExecPlans and lessons as historical evidence.

Chat history and model memory are supplemental. They do not override current Git or live evidence.

## Start or resume work

Before modifying the repository:

- verify the authoritative workspace paths in [`.codex/workspace-context.md`](.codex/workspace-context.md);
- inspect the current branch, working-tree status, and latest commit;
- read this file;
- read only the scoped document needed for the task;
- if a matching plan exists under `docs/exec-plans/active/`, resume from it instead of reconstructing state from chat;
- preserve unrelated user work.

Do not reread unchanged guidance during the same sprint unless new evidence makes it relevant.

## Planning threshold

Use a lightweight task plan for small, local changes.

Create and maintain an ExecPlan, following [`.codex/PLANS.md`](.codex/PLANS.md), when work is expected to take more than about one hour, spans multiple subsystems, performs a significant refactor or migration, or automates a controller/appliance workflow with meaningful live state.

The ExecPlan is the durable sprint state. Keep its progress, current state, decisions, discoveries, evidence, and next action current at every meaningful checkpoint.

## Known operator workflows

When the owner already knows a working manual procedure, capture it before broad discovery. Use [`docs/workflows/README.md`](docs/workflows/README.md) as the contract.

Treat the known workflow as evidence to verify and automate, not as an invitation to rediscover the product from first principles. Research should fill actual gaps: version behavior, supported automation surfaces, undocumented interactions, or failures that differ from the known path.

## Core invariants

- Do not silently change human-authored intent to make a deployment or test pass.
- Validation is read-only. Remediation belongs outside validation.
- Prefer safe reconciliation over blind recreation.
- Preserve running objects when mutation is unsafe.
- Distinguish requested action, observed runtime state, and guest/application readiness.
- Destructive operations must be explicit and narrowly scoped.
- Keep credentials, secrets, and private environment values out of the public repository.
- Preserve upstream behavior unless a change is intentional and tested.
- Prefer reusable capability over lab-specific engine code.
- Do not claim live success without live evidence.

## Execution zones

Repository-local and offline work is autonomous within the active task.

Designated disposable EVE development/test labs are part of the integration-test harness. Within an authorized sprint, the agent may create, start, stop, initialize, configure, validate, reset, recreate, and delete those lab objects as needed for proof.

Parent or persistent infrastructure requires explicit task authorization. This includes the EVE host OS, vSphere, physical network devices, shared services, production/shared routing and firewalls, and persistent labs not designated for automation testing.

## Investigation economics

Use the cheapest evidence that can answer the current question, then escalate only when needed.

- Search before loading large files when the location is unknown.
- Bound commands with potentially large output.
- Prefer targeted logs and show commands over full dumps.
- Do not repeatedly reopen unchanged files.
- Do not repeat the same failed operation without new evidence or a changed hypothesis.
- Poll long-running jobs at bounded intervals and use completion signals when available.
- Run the smallest test set that can falsify the current change during iteration.
- Run broader regression only at meaningful acceptance gates.
- Stop broad research when the implementation question is already answered by repository evidence or a verified operator workflow.

Detailed retry and stop-loss rules live in [EXECUTION-MODEL.md](docs/architecture/EXECUTION-MODEL.md).

## Testing and proof

A runtime feature is not proven by unit tests alone when an appropriate authorized live sandbox is available.

Use proportional validation:

1. focused offline tests during iteration;
2. applicable live integration against the real NOS/controller;
3. final regression appropriate to the changed surface.

Do not run broad suites after every edit. Do not weaken tests or acceptance criteria to create a green result.

## Git behavior

Do not develop substantial features directly on `main`. Use a focused branch.

Preserve unrelated edits and staged work. Do not reset, clean, or overwrite user changes for convenience.

Git is the durable record of implementation and sprint state. A coding-agent conversation is disposable after its state is recorded.

The owner retains approval for merges and for actions outside the authorized live-test boundary.

## Documentation routing

- [ARCHITECTURE.md](ARCHITECTURE.md): component map, boundaries, and system invariants.
- [PROJECT-INTENT.md](docs/architecture/PROJECT-INTENT.md): project purpose and human/agent responsibility.
- [STRUCTURE.md](docs/architecture/STRUCTURE.md): topology, reconciliation, initialization, validation, portability, security, and other engineering conventions.
- [EXECUTION-MODEL.md](docs/architecture/EXECUTION-MODEL.md): sprint lifecycle, research, evidence, retry economics, authorization, and stop conditions.
- [`.codex/PLANS.md`](.codex/PLANS.md): ExecPlan format.
- [`docs/exec-plans/`](docs/exec-plans/README.md): active and completed long-running plans.
- [`docs/workflows/`](docs/workflows/README.md): known-good operator procedures that automation should reproduce.
- [`docs/platforms/`](docs/platforms/README.md): durable platform-specific behavior.
- [`docs/operations/`](docs/operations/): operator and validation procedures.
- [`docs/lessons/`](docs/lessons/README.md): historical reusable evidence, not current sprint state.
- [`docs/roadmap/`](docs/roadmap/ROADMAP.md): future product direction.

Keep the root README product- and operator-focused. Do not put agent handoff history, prompt strategy, or sprint narration there.
