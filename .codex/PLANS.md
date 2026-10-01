# Codex ExecPlans

An ExecPlan is a self-contained, living implementation plan for work that is too large or stateful to rely on chat history.

Use one when required by `AGENTS.md` and `docs/architecture/EXECUTION-MODEL.md`.

## Core rule

A contributor with the current working tree and the ExecPlan should be able to understand the objective, current state, evidence, decisions, and next action without replaying the prior conversation.

Keep the plan current while work proceeds. It is not a pre-work essay that becomes stale after implementation starts.

## Required sections

### Purpose / observable outcome

State what becomes possible after the sprint and how success can be observed.

### Scope and boundaries

Record:

- in-scope repositories and components;
- authorized live environment;
- destructive-operation boundary;
- explicit non-goals.

### Known operator workflow

When a working manual procedure exists, record or link:

- ordered steps;
- platform/version applicability;
- focused manual execution estimate;
- observable lifecycle checkpoints;
- interactions the automation must eliminate.

Do not omit this section merely because the implementation will ultimately use APIs instead of the UI.

### Acceptance criteria

Use observable criteria. Separate offline success from live proof.

### Current state

Keep this section terse and current. Include:

- current branch/commit;
- current live lifecycle state;
- last successful milestone;
- active blocker or current question;
- exact next action;
- completed work that must not be repeated.

### Progress

Maintain a checkbox list with timestamps or meaningful checkpoints.

### Milestones

Break long work into independently verifiable milestones. Each milestone should state:

- objective;
- implementation surface;
- verification;
- exit condition.

### Evidence ledger

Record only evidence that changes engineering decisions.

Use labels where applicable:

- DOCUMENTED;
- OBSERVED;
- VERSION-GATED;
- FIELD-TEST REQUIRED;
- UNSUPPORTED;
- HYPOTHESIS.

Include enough detail to reproduce important observations.

### Retry / investigation ledger

For repeated failures, record:

- operation attempted;
- failure signature;
- what changed before the next attempt;
- new evidence or hypothesis;
- result.

Do not log every harmless command. The purpose is to prevent identical retries from masquerading as progress.

### Automation economics

When the manual path is known, record:

- focused manual baseline;
- 2x checkpoint;
- 4x diagnosis threshold;
- time to first working automated path;
- time to reusable/idempotent path when achieved;
- material waiting/environmental time separately where known.

These figures are controls for detecting thrash, not performance guarantees.

### Surprises and discoveries

Record unexpected facts that materially change the design or future work.

### Decision log

Record material decisions and rationale. Include rejected alternatives only when remembering why they were rejected prevents likely rework.

### Validation

Record exact focused tests, live tests, regression tests, and significant evidence.

Do not claim a validation step ran if it did not.

### Outcomes and retrospective

At completion, summarize:

- delivered capability;
- acceptance result;
- remaining limitations;
- reusable lessons;
- whether the manual-vs-automation cost was justified by repeatability, scale, reliability, or future reuse.

## Plan location

Active plans live in:

`docs/exec-plans/active/<short-sprint-name>.md`

When complete or explicitly abandoned, move the plan to:

`docs/exec-plans/completed/YYYY-MM-DD-<short-sprint-name>.md`

Do not use completed plans as current state.

## Execution behavior

While implementing an ExecPlan:

- continue milestone to milestone while the next action is defined and authorized;
- update the plan after meaningful state changes;
- do not ask for "next steps" that the plan already supplies;
- do not restart completed investigation after a new chat;
- reconcile the plan against actual Git/live state before resuming;
- revise the plan when evidence invalidates an assumption.

The plan is allowed to change. Unrecorded drift is not.
