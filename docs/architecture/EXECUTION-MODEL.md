# Execution model

The unit of substantial work is a sprint with an objective, acceptance criteria, and durable state. An individual prompt or tool call is not a project boundary.

This document governs long-running implementation, research-heavy work, live appliance/controller automation, retry economics, and stop conditions.

## Work classes

### Small/local work

Use a lightweight plan when the change is narrow, low risk, and expected to complete well under an hour.

### Sprint work

Use an ExecPlan when work:

- is expected to take more than about one hour;
- spans multiple modules or systems;
- performs a significant migration/refactor;
- depends on uncertain external platform behavior; or
- automates a controller/appliance workflow with meaningful lifecycle state.

ExecPlan format is defined in [`.codex/PLANS.md`](../../.codex/PLANS.md). Active plans live under [`docs/exec-plans/active/`](../exec-plans/active/README.md).

## Start with what is already known

Before broad discovery, determine whether the owner already has a working manual procedure.

If yes:

1. capture the ordered workflow and observable checkpoints;
2. record the approximate focused manual execution time;
3. identify the human interactions the automation must eliminate;
4. verify version applicability;
5. identify supported automation surfaces;
6. automate that path before exploring alternatives.

Use [`docs/workflows/README.md`](../workflows/README.md) for the capture format.

A known operator workflow is not infallible, but it is first-class evidence. Do not spend hours rediscovering behavior that the organization already knows unless current evidence contradicts it.

## Normal engineering loop

```text
intent / known workflow
        |
        v
bounded research and repo inspection
        |
        v
implementation
        |
        v
focused offline tests
        |
        v
authorized live integration
        |
        v
acceptance evidence
        |
        +---- PASS ---> final regression / review
        |
        +---- FAIL ---> classify -> diagnose -> repair -> retest
```

Intermediate failure is an input to the next engineering iteration, not automatically a handoff point.

## Failure classification

Before changing code after a live failure, classify the failure as narrowly as evidence permits:

- **HARNESS/TOOLING**: browser, shell, transport, test harness, or orchestration failure.
- **ENVIRONMENT**: hypervisor, capacity, reachability, DNS, PKI, image, license, or external dependency.
- **LIFECYCLE**: operation attempted before the appliance/controller reached the state that exposes the capability.
- **AUTOMATION**: the implementation does not reproduce supported behavior correctly.
- **PLATFORM**: observed product behavior or defect remains after harness/environment causes are ruled out.
- **UNKNOWN**: evidence is insufficient; gather evidence before mutation.

Do not attribute a harness problem to the vendor platform.

## Evidence classes

Use explicit evidence labels when external behavior affects implementation:

- **DOCUMENTED**: supported by current authoritative vendor/upstream documentation.
- **OBSERVED**: reproduced in the target lab/version.
- **VERSION-GATED**: behavior is documented or observed only for a specific release/train.
- **FIELD-TEST REQUIRED**: plausible/documented behavior that still requires target-version proof.
- **UNSUPPORTED**: authoritative evidence or controlled testing shows the path is not supported.
- **HYPOTHESIS**: a working explanation that has not yet been proven.

A hypothesis is not a conclusion.

## Research policy

Research is part of implementation when a material external fact is uncertain.

Preferred order:

1. exact-version vendor documentation;
2. upstream project source/documentation;
3. release notes and defect/bug documentation;
4. reputable implementation examples;
5. community reports and issue threads.

Community evidence is useful for failure patterns and hidden edge cases, but it does not outrank exact-version authoritative evidence.

Research should answer a specific implementation question. Stop researching when the question is adequately answered and move to a controlled field test.

## Diagnostic depth

Start at the highest supported surface that can answer the question and descend only when evidence requires it:

```text
supported API / command
        |
        v
returned result / application evidence
        |
        v
raw console / transport
        |
        v
runtime / process observation
        |
        v
narrow host inspection
        |
        v
targeted research / new hypothesis
```

Prefer observation before mutation.

## Retry discipline

Do not repeat the same failed operation merely because another retry is cheap.

A retry must have at least one of:

- new evidence;
- a changed implementation;
- a changed environmental condition;
- a changed hypothesis;
- a documented transient condition with a bounded retry policy.

Record significant repeated failures and what changed between attempts in the active ExecPlan.

If two controlled attempts fail in materially the same way, stop treating another identical attempt as progress. Move to diagnosis.

## Automation economics and stop-loss

Automation may reasonably cost more than one manual execution to engineer. It must not consume unbounded time without increasing reusable knowledge or capability.

For a workflow with a known focused manual baseline:

- at roughly **2x manual time**, checkpoint progress and explain the remaining uncertainty;
- at roughly **4x manual time**, enter **DIAGNOSIS** unless a clearly new platform problem or intentionally broader reusable capability justifies continued implementation;
- after entering DIAGNOSIS, do not resume repeated experimentation until the active plan records a new hypothesis or evidence-backed path.

These are project control thresholds, not promises that automation must always finish inside them.

For research-heavy work with no known manual baseline, budget by explicit milestones and evidence gates instead of time multipliers.

Track enough information in the active plan to distinguish productive engineering cost from thrashing:

- manual baseline when known;
- time to first working path;
- time to reusable/idempotent path;
- major research questions;
- repeated investigations;
- blocked/waiting time;
- validation cycles;
- genuinely new platform discoveries.

## Long-running jobs and context use

- Use bounded polling intervals.
- Prefer completion notifications or status endpoints over repeated wake/check loops.
- Bound potentially large command/log output by bytes or narrow filters.
- Avoid reopening unchanged files.
- Persist durable state before context compaction or handoff.
- Do not spend model turns narrating that a job is still running unless that observation changes the next action.

## Validation economics

During iteration, use the cheapest test that can falsify the current change.

Escalate in this order as appropriate:

1. targeted unit test or static check;
2. changed-module test set;
3. targeted live integration;
4. broader regression at an acceptance gate.

Do not run every test suite after every edit. Do not skip required live proof merely to save usage.

## Execution zones

### Repository and offline work

Autonomous within the active task. Inspect, edit, test, refactor, and prepare branches while preserving unrelated work.

### Designated disposable EVE development/test labs

Autonomous when included in the active sprint authorization. The agent may plan, apply, start, stop, initialize, configure, validate, reset, recreate, and delete the designated lab objects and guest devices needed for proof.

### Parent or persistent infrastructure

Requires explicit task authorization. This includes the EVE host operating system, vSphere, physical devices, production/shared routing and firewalls, shared services, and persistent labs not designated for automation testing.

Read-only inspection does not imply standing permission to mutate parent infrastructure.

## Resume behavior

A conversation ending does not end an unfinished sprint.

On resume:

1. inspect current Git and live state;
2. read the matching active ExecPlan;
3. verify that its recorded current state still matches reality;
4. continue the next recorded action.

Do not restart planning, replay completed steps, or ask the owner to restate scope that is already durable.

If current reality differs from the plan, update the plan before proceeding.

## Stop conditions

Return control when:

- acceptance criteria are satisfied;
- continuing would materially change architecture or human intent;
- continuing would cross an unauthorized boundary;
- required credentials, images, licenses, or resources are unavailable;
- a meaningful blocker remains after evidence-backed remediation;
- the stop-loss threshold is reached without a new justified hypothesis; or
- additional work would be speculative rather than evidence-driven.

Do not stop merely because one implementation phase, test, research query, or recovery action finished.

## Definition of proof

Offline tests are necessary but not sufficient for runtime behavior when an appropriate authorized live environment exists.

A runtime capability is proven when:

- the intended workflow completes on the actual target platform/version;
- declared acceptance criteria pass;
- evidence distinguishes API acceptance, runtime state, and guest/application readiness where relevant;
- no acceptance threshold or human intent was weakened to obtain the result.

Validation itself remains read-only.
