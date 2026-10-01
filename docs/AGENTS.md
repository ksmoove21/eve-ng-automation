# Documentation guidance

This file applies to `docs/`.

Documentation is a source-of-truth system, not a transcript of agent work.

## Ownership

- `architecture/`: durable purpose, engineering conventions, and execution model.
- `exec-plans/active/`: current substantial sprint state.
- `exec-plans/completed/`: historical execution records.
- `workflows/`: known-good operator procedures.
- `platforms/`: platform/version-specific durable behavior.
- `operations/`: operator and validation procedures.
- `lessons/`: historical reusable evidence.
- `roadmap/`: future direction.

Update [README.md](README.md) when adding or moving a documentation category.

## Current versus historical state

Do not put active sprint state in lessons or the product README.

Do not use completed ExecPlans as current authority.

When a durable fact changes, update the owning current document. Historical records may remain unchanged when they accurately describe what was known at the time.

## Audience

Keep the root project README and public operator docs focused on capabilities, requirements, commands, examples, limitations, and safety.

Keep prompt strategy, agent handoffs, retry narration, and implementation chronology in the execution-plan/process layer rather than user-facing product documentation.

## Evidence

Label uncertain external behavior appropriately. Do not convert a field observation into a general platform guarantee without version/applicability evidence.

Prefer concise evidence links and summaries over large pasted logs or configurations.
