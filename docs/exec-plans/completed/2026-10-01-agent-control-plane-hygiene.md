# Harden the agent execution control plane

This ExecPlan records the repository-control-plane review completed on 2026-10-01. It follows `.codex/PLANS.md`.

## Purpose / observable outcome

Reduce agent rediscovery, repeated validation, stale-state reconstruction, and ambiguous stop behavior without changing the working EVE automation engine.

The repository now provides a compact root agent map, scoped nested guidance, a top-level architecture map, durable execution plans, known-operator-workflow capture, explicit retry economics, and shared sprint states.

## Scope and boundaries

In scope:

- public repository guidance and architecture documentation;
- ExecPlan structure;
- known operator workflow structure;
- context/retry/validation economics;
- Git autonomy on feature branches;
- review of major engine modules for evidence of an immediate structural refactor need.

Out of scope:

- Nexus Dashboard or Catalyst SD-WAN implementation state that is not present on the public remote;
- private UNSC workspace data;
- live appliance mutation;
- engine behavior changes.

## Known operator workflow

Not applicable to this documentation/control-plane sprint.

The review was motivated by controller/appliance automation where known manual workflows exist. The repository now requires those workflows to be captured before broad rediscovery.

## Acceptance criteria

- Root agent guidance is a routing/control document rather than a duplicated engineering manual.
- Architecture and execution/process ownership are separated.
- Significant long-running work has a durable resumable plan format.
- Known manual procedures have a durable capture format.
- Retry, research, polling, and test escalation have explicit limits.
- "stalled" has a precise shared meaning.
- Scoped code/test/docs rules can load progressively through nested `AGENTS.md` files.
- No engine refactor is performed without evidence.
- Documentation navigation links resolve.

## Current state

- Status: COMPLETE.
- Branch: `ops/agent-control-plane-hygiene`.
- Base: `main` at `2c7a3371ade4859e34a5433bd09075f41bb6c981`.
- Control-plane commits before this record:
  - `4e32bad38055d6f01d2154e2d4e9d645c8afbc58` — harden agent execution control plane.
  - `cd1d603613ee44811dab0ae93ddf389dac5dc639` — scope agent guidance and sprint states.
- Live lifecycle state: not applicable; no live infrastructure was changed.
- Next action: review the pull request and merge only if the owner accepts the new operating model.
- Do not repeat: broad analysis of whether file size alone justifies splitting `deploy.py`, `initialize.py`, `device_console.py`, or `validation.py`; this review found no such evidence.

## Progress

- [x] Audited remote branch state and repository tree.
- [x] Reviewed root guidance, workspace context, architecture/execution documents, roadmap, lessons index, README size/navigation, and major engine module boundaries.
- [x] Compared the observed structure with current OpenAI ExecPlan, AGENTS, nested-instruction, and harness-engineering patterns.
- [x] Reviewed community reports for repeated polling, oversized command output, excessive test loops, and context churn.
- [x] Reworked root guidance and architecture ownership.
- [x] Added ExecPlan and known-workflow systems.
- [x] Added explicit stop-loss, evidence, retry, and sprint-state terminology.
- [x] Added scoped nested guidance for `src/eve_lab/`, `tests/`, and `docs/`.
- [x] Reviewed bounded retry/polling code in major engine modules.
- [x] Verified changed documentation links.

## Milestones

### Repository knowledge map

Result: `AGENTS.md` is 124 lines and routes to scoped sources instead of duplicating them. `ARCHITECTURE.md` now owns the top-level component map.

Proof: branch file inspection and link validation.

### Long-running execution state

Result: `.codex/PLANS.md` defines the living-plan contract and `docs/exec-plans/` separates active from completed state.

Proof: all plan paths are present and cross-links resolve.

### Known workflow first

Result: `docs/workflows/README.md` defines how an operator's working manual procedure, lifecycle checkpoints, manual baseline, and interaction points are captured before automation research expands.

Proof: workflow template is present and routed from root guidance and the execution model.

### Bounded autonomy

Result: retry discipline, 2x/4x manual-baseline checkpoints, polling/output limits, proportional validation, failure classification, evidence classes, and sprint states are documented.

Proof: `docs/architecture/EXECUTION-MODEL.md`.

### Scoped guidance

Result: path-specific rules moved into nested `AGENTS.md` files for engine code, tests, and docs.

Proof: nested files are present and root guidance points agents to the closest applicable file.

## Evidence ledger

- DOCUMENTED: OpenAI's harness-engineering write-up reports that a large monolithic `AGENTS.md` became context-heavy, stale, and hard to verify; their replacement uses a short agent map, `ARCHITECTURE.md`, structured docs, and active/completed execution plans.
- DOCUMENTED: current Codex instructions support directory-scoped nested `AGENTS.md` files with closer files taking precedence.
- DOCUMENTED: OpenAI's ExecPlan guidance recommends living self-contained plans for multi-hour or multi-file work and requires progress, discoveries, decisions, and outcomes to stay current.
- OBSERVED: prior root `AGENTS.md` was about 10 KB and `STRUCTURE.md` was 577 lines with repeated execution/authorization/testing material.
- OBSERVED: after the change, root `AGENTS.md` is 124 lines and `STRUCTURE.md` is 233 lines.
- OBSERVED: major engine retry/polling loops inspected in `deploy.py`, `initialize.py`, `device_console.py`, and validation paths are bounded rather than unbounded.
- OBSERVED: all relative links in the changed control-plane documents resolve.
- HYPOTHESIS REJECTED: large orchestration module size by itself indicates the immediate need for a code refactor. The current module responsibilities remain coherent enough that a size-only refactor would be speculative.

## Retry / investigation ledger

No repeated live operations were performed.

The public GitHub remote did not contain the current Nexus Dashboard or SD-WAN work discussed outside the repository. The review did not fabricate that state or attempt to reconstruct it as public current state.

## Automation economics

No manual execution baseline applies to this documentation sprint.

The new execution model adds a project control policy for future known workflows:

- roughly 2x the focused manual baseline triggers a progress/evidence checkpoint;
- roughly 4x triggers DIAGNOSIS unless a genuinely new platform problem or intentionally broader reusable capability explains the cost.

## Surprises and discoveries

- The repository had already moved partway toward progressive disclosure, but the same rules were still repeated in `AGENTS.md`, `STRUCTURE.md`, and `EXECUTION-MODEL.md`.
- The biggest verifiable problem was therefore competing process authority and context cost, not obvious engine decomposition.
- Current Codex community issue reports describe repeated wait/poll model turns as a real usage problem, so repository guidance now explicitly avoids narration/poll loops. Repository guidance may reduce exposure but cannot by itself fix a runtime orchestration defect in Codex.

## Decision log

- Decision: do not refactor engine modules in this sprint.
  Rationale: module size alone is not evidence of broken ownership, and the inspected polling loops are bounded.

- Decision: keep root `AGENTS.md` as the always-loaded control plane and use nested files for path-specific rules.
  Rationale: reduces irrelevant instruction load and matches current Codex scoping semantics.

- Decision: treat known manual operator workflows as first-class automation input.
  Rationale: rediscovering an already-working lifecycle wastes time and can lead the automation away from the platform's real state sequence.

- Decision: allow autonomous scoped commit/push on feature branches but retain owner approval for merging to `main`.
  Rationale: supports the desired hands-off implementation model without silently broadening release authority.

- Decision: define STALLED separately from WAITING and DIAGNOSIS.
  Rationale: slow work with a valid next action is not stalled; identical retries without new evidence are.

## Validation

Performed:

- compared `main` with the feature branch;
- enumerated changed files and sizes;
- fetched the branch recursively and verified the new paths;
- parsed Markdown links in the changed control-plane documents and found zero unresolved relative links;
- reviewed major engine modules for wait/retry loops and broad failure patterns.

Not performed:

- Python unit tests, because no executable engine or test code changed;
- live EVE/controller tests, because this sprint did not change runtime behavior.

## Outcomes and retrospective

The repository now has a clearer separation between:

- always-loaded agent control;
- system architecture;
- detailed engineering conventions;
- long-running execution state;
- known human workflows;
- historical lessons.

The change deliberately does not claim to solve Codex runtime polling defects or to make every controller automation complete inside the manual execution time. It instead makes excess time visible, classifiable, and bounded so the agent must explain why continued work is justified.

The next Nexus Dashboard and SD-WAN sprints should each create or update their own active ExecPlan in the repository where their actual implementation state lives.
