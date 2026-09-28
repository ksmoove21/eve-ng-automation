# Repository guidance

Read [structure.md](structure.md) before changing this repository.

Follow its architecture, lab-definition, reconciliation, validation, testing,
platform-support, and Git workflow conventions for all new and modified code.

Preserve unrelated user edits. Do not make live or destructive EVE-NG changes
unless explicitly requested. Do not weaken validation or silently change human
intent to make a lab pass.

When the owner changes a repository convention, update `structure.md`
alongside the implementation.

Keep the root README and user-facing docs product-focused. Do not expose internal design discussions, agent/Codex handoff flow, prompt strategy, implementation sequencing, or decision-history narration there. Keep that material in contributor/internal documentation.

## Initiative and follow-through

Resolve repository-visible and otherwise retrievable prerequisites before asking
the owner. Inspect the relevant code, documentation, tests, history, and current
branch state when they can answer the question.

Proceed autonomously with reversible, low-risk work inside the requested
repository scope, including code changes, tests, documentation, local analysis,
and branch preparation. Do not stop merely to ask permission for work already
authorized by the active task.

Complete every requested deliverable or mark it blocked with the exact missing
dependency. Before reporting completion, verify the implementation, tests,
repository state, requested format, and remaining work.

Treat implementation requests such as "can you", "help me", "build this",
"fix this", and "move forward" as authorization to carry the requested
repository work through implementation, relevant offline verification, and
handoff. Requests to investigate, explain, compare, or review authorize those
activities but do not by themselves authorize unrelated implementation.

Use reasonable assumptions for routine, reversible choices. State assumptions
that materially affect the result. Ask a focused question only when an
unresolved choice would materially change architecture, intent, authorization,
or the resulting implementation.

Corrections and follow-up messages steer the active task unless the owner
cancels it or supplies an incompatible objective. Preserve accepted decisions,
completed work, evidence, and outstanding steps across turns and context
compaction.

Authorization for repository-local, reversible work persists for the active
task. Authorization for live infrastructure actions does not silently broaden:
starting, stopping, configuring, deleting, resetting, or otherwise changing
EVE-NG nodes or network devices requires authorization applicable to that
specific live action and scope.

When live authorization is absent, continue all useful offline preparation that
does not itself alter the live environment, so the owner receives a concrete
result rather than an unnecessary permission checkpoint.

Before handing off an implementation task, check whether authorized work remains
unfinished. Complete it or identify the exact blocker. Do not hand routine
implementation back to the owner merely because the next step requires editing
code, writing tests, or updating documentation.

