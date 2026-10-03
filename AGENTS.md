# Repository guidance

At the start of every new Codex chat or sprint, read [`.codex/workspace-context.md`](.codex/workspace-context.md) and this file to re-establish the authoritative workspace, repository boundary, execution rules, and current operating conventions.

The architecture documents remain authoritative, but do not read all of them mechanically at every start. Read only the document(s) relevant to the task or decision being changed:

- [PROJECT-INTENT.md](docs/architecture/PROJECT-INTENT.md) when the task changes project scope, architectural responsibility, portability goals, or the intended end state.
- [STRUCTURE.md](docs/architecture/STRUCTURE.md) when the task changes repository structure, schemas, reusable engine behavior, platform-adapter boundaries, reconciliation, or durable engineering conventions.
- [EXECUTION-MODEL.md](docs/architecture/EXECUTION-MODEL.md) when the task changes sprint autonomy, live-lab authorization, lifecycle behavior, stop conditions, or proof requirements.

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

Do not re-read unchanged guidance already established in the same active sprint unless new evidence makes it relevant.

This project extends the operating model of upstream `wcmder/eve-ng`; it does
not replace it. Preserve the inherited declarative lab workflow and extend it
with additional platform support, validation, orchestration, and reusable
network-lab capabilities.

Use `PROJECT-INTENT.md` for purpose, `STRUCTURE.md` for repository and engineering conventions, and `EXECUTION-MODEL.md` for sprint autonomy and authorization boundaries.

## Sprint execution contract

Treat an agreed development task as a sprint, not a sequence of permission
checkpoints. Once the objective and acceptance criteria are clear, continue
through implementation, offline tests, applicable live integration tests,
remediation, regression testing, and evidence collection without returning
control merely because an intermediate step completed or failed.

A failed test is an input to the next engineering iteration, not a handoff
point. Diagnose it, repair the implementation when the repair is within scope,
and rerun the relevant tests.

Do not repeatedly retry the same abstraction without gathering new evidence.
When a high-level workflow does not explain a failure, descend deliberately
through the diagnostic stack: command/API result, application evidence, raw
console or transport, runtime/process observation, then narrowly scoped host
inspection when that inspection is within the authorized boundary. Prefer
observation before mutation.

When the root cause depends on uncertain platform behavior, image requirements,
API semantics, boot behavior, version-specific limitations, or vendor syntax,
research authoritative sources before inventing a workaround. Prefer vendor
documentation, upstream project source/docs, release notes or bug documentation,
then reputable community evidence. Validate researched conclusions against the
actual disposable lab.

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
current sprint and execution zone. Do not emit progress-only handoffs such as
"continuing", "currently running", or "next I will" when there is still
authorized work to perform. Continue tool execution until acceptance criteria or
a true stop condition is reached.

If an unfinished sprint resumes in a later conversation turn, treat the previous
turn's final technical state as a checkpoint, not a new planning phase.
Immediately continue from that active state without re-planning, re-summarizing
completed intermediate work, or asking the owner to restate already-authorized
scope. Re-read only the guidance or evidence needed to resume safely.

Stop only when continuing would materially change the agreed architecture or
intent, cross an unauthorized boundary, require unavailable
credentials/resources, or remain technically blocked after reasonable
remediation and evidence gathering.

Preserve unrelated user edits. Do not weaken validation or silently change
human-authored intent to make a lab pass. Do not claim live success without
live evidence.

## Context and usage efficiency

Spend context on evidence that changes implementation decisions.

- Search before reading whole files when the relevant location is unknown.
- Read only the needed file ranges when practical; read a complete file when editing it or when local context is required for correctness.
- Do not repeatedly dump complete configs, generated artifacts, large diffs, or long logs into the conversation. Capture the narrow evidence needed to diagnose the current failure.
- Bound commands that may return large output. Prefer filters, targeted show commands, relevant log ranges, and structured summaries.
- During implementation, run the smallest test set that can falsify the current change. Run broader regression suites at meaningful acceptance gates rather than after every edit.
- Poll long-running boots, jobs, commits, and controllers at bounded intervals. Do not create tight polling loops that consume context without new evidence.
- Preserve durable decisions, evidence, and sprint state in Git-backed files. Do not rely on an indefinitely growing chat as project memory.
- At a true sprint boundary, prefer a fresh Codex thread. For an unfinished active sprint, resume from the existing checkpoint instead of rehydrating the whole project from scratch.
- Keep sprint prompts task-specific. Standing architecture, repository, safety, and autonomy rules belong in checked-in guidance rather than being repeated verbatim in every prompt.
- If the client supports context compaction or summarization, use it only after current state and important evidence are durable in the repository or sprint artifacts.

## Direct-link topology invariant

When lab intent declares a point-to-point cable between two node interfaces, encode it as a direct `from`/`to` link and preserve that same point-to-point semantic in EVE.

Do not model a point-to-point cable by attaching multiple nodes to a declared shared bridge/network. Declared EVE network objects are reserved for intentional shared/multiaccess or infrastructure networks such as Cloud0/pnet and other explicitly shared segments.

If EVE requires a backing bridge for a direct cable, it is adapter-private: exactly one direct link, exactly two endpoints, hidden from the native canvas/status network list, and never shared with another cable.

## EVE integration toolbox

For EVE-NG topology, lifecycle, placement, and runtime operations, treat the
available integrations as a toolbox rather than a fixed precedence chain.

Before adding custom EVE-specific Python, check whether the operation is already
handled cleanly by the native EVE API, EVE-IAC, or a suitable SDK/library.
Compose those integrations when useful. Use EVE-host SSH only for host-level
operations, image/runtime handling, or diagnostics that genuinely require host
access.

Python remains the orchestration, policy, reconciliation, normalization, and
validation layer. Do not reimplement EVE platform behavior without evidence that
the existing integration surfaces leave a real capability gap.

The durable engineering details live in
[STRUCTURE.md](docs/architecture/STRUCTURE.md).

## EVE CPU Limit runtime policy

QEMU nodes created or reconciled by this automation must have EVE-NG CPU Limit
disabled by default (`cpulimit=0`). EVE's limiter may suspend the complete QEMU
process and interfere with deterministic guest boot and readiness behavior.

Treat this as a generic EVE runtime policy, not a platform-adapter behavior.
Platform-specific code must not independently enable CPU Limit. A future
declarative opt-in may be supported only when it is explicit in the node schema;
absence of such an opt-in means disabled.

The deployment reconciler enforces `cpulimit=0` on creation and stopped-node
reconciliation for QEMU nodes. Native IOL records do not persist this QEMU
setting. Running-node safety and race protections remain in effect.
The topology schema does not expose an opt-in to CPU limiting.

When the owner changes a durable project convention, update the owning document under `docs/architecture/` alongside the implementation.
