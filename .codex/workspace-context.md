# Codex workspace context

Use this file to re-establish the authoritative workspace. It is not a sprint diary.

## Authoritative local roots

- Public automation repository: `H:\Github\eve-ng-automation`
- Private environment repository: `H:\Github\unsc-homelab`
- Private EVE workspace: `H:\Github\unsc-homelab\VSCode Labs\EVE-Workspace`

The public repository contains the reusable automation framework.

The private repository contains UNSC-specific environment context, lab definitions, topology, addressing, credentials references, and other environment-specific implementation data.

## New-chat bootstrap

Before implementation:

1. Verify that the required authoritative root exists.
2. Do not clone a duplicate checkout or silently substitute another drive/path because shell context was lost.
3. Treat the public repository as the primary engine working root unless the sprint explicitly requires private-repository changes.
4. Inspect the current Git branch, working-tree status, and latest commit before modification.
5. Read the public root `AGENTS.md`.
6. If a matching file exists under `docs/exec-plans/active/`, read it and resume from its current state.
7. Read only the architecture, platform, workflow, or operations documents routed by `AGENTS.md` for the current task.
8. When private lab context is required, read only the applicable guidance in the private EVE workspace.
9. Use absolute paths when crossing repositories.
10. If an authoritative drive or repository is unavailable, report that exact blocker rather than inventing an alternate workspace.

Current Git, the active ExecPlan, and live evidence outrank prior chat summaries. Chat history is supplemental.

## Operator model

Normal profile:

- Model: GPT-6 Sol
- Reasoning: Medium
- Speed: Standard

Escalate reasoning only when the evidence warrants it, such as difficult root-cause analysis, version-specific controller behavior, or architectural ambiguity. Do not interrupt an otherwise healthy sprint merely to change models.

## Repository boundary

Keep reusable code, validators, schemas, tests, and generic documentation in the public repository.

Keep UNSC-specific addressing, hostnames, topology, private lab definitions, secrets references, and environment-specific overrides in the private repository.

Do not leak private values into public examples, tests, fixtures, or documentation.

## Sprint continuity

Long-running work must not depend on chat continuity. When an ExecPlan is required, keep the plan's current state, evidence, decisions, and next action updated so a new session can resume without replaying the conversation.

Stop and authorization behavior is defined by `AGENTS.md` and `docs/architecture/EXECUTION-MODEL.md`.
