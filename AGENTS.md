# Repository guidance

Read [PROJECT-INTENT.md](docs/architecture/PROJECT-INTENT.md), [STRUCTURE.md](docs/architecture/STRUCTURE.md), and [EXECUTION-MODEL.md](docs/architecture/EXECUTION-MODEL.md) before changing this repository.

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

When the owner changes a durable project convention, update the owning document under `docs/architecture/` alongside the implementation.
