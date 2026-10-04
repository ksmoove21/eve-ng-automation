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

A bounded syntax, command-prerequisite, API-shape, or exact-version question is
normal implementation work, not an owner decision by itself. Resolve it through
focused research and, when useful, delegate the read-only research question to
the Coordinator/scribe while the implementation worker continues its owned lane.
Escalate only when the evidence exposes a real architectural choice, requires
authority outside the active scope, or no supported path remains after reasonable
research and field validation.

When research changes or sharpens a durable platform fact, reconcile the result
into the owning checked-in platform/architecture documentation with the exact
version and evidence classification. Do not leave current vendor behavior only
in chat, a worker message, or the sprint storyboard; the reusable engine should
carry forward the latest validated knowledge.

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

## Nexus Dashboard subagent runner trial

This branch is testing bounded Codex subagents as parallel execution runners. It is an experiment for the active Nexus Dashboard/NDFC DC1 sprint, not yet a durable project-wide convention.

The primary/root agent owns the sprint, critical path, integration decisions, acceptance criteria, and the troubleshooting context of the problem it is actively working. Use the project-scoped `runner` agent for substantial independent work lanes that would otherwise make Root leave that critical path. Start with one runner. Additional agents may be added only when a distinct ready lane exists. The branch configuration caps concurrent spawned threads at three, excluding Root.

Root should normally diagnose failures arising directly from its own active lane. Do not offload an active failure merely to free Root from troubleshooting context. Runners are for independent progress, not for duplicating Root.

### Cost-first model and reasoning policy

Prefer the least expensive model that can reliably complete the bounded role. When a task becomes difficult, prefer increasing reasoning effort on the current model before moving to a more expensive model tier when that remains cost-effective.

Use this escalation order by default:

1. keep the current model and increase reasoning effort;
2. increase reasoning effort again when the model is still making sound progress and the additional depth is justified;
3. escalate the model tier only when evidence indicates a capability ceiling rather than merely a difficult problem.

A capability ceiling includes repeated misclassification of risk, failure to integrate required cross-system evidence, circular retries despite increased reasoning, inability to make a material engineering judgment safely, or another demonstrated limitation that more reasoning depth on the same model is unlikely to fix.

For this trial:
- Coordinator: GPT-5.6 Luna / Low for status, messaging, storyboard, and bookkeeping. Prefer Luna Medium/High before moving to Terra when deeper coordination reasoning is needed.
- Hygiene: GPT-5.6 Terra / Medium for on-demand repository cleanup and maintenance at milestone/closeout checkpoints or when material drift is detected. Prefer Terra High/XHigh before moving to Sol when cleanup requires deeper reasoning.
- Runner: start at GPT-5.6 Terra / Medium. Escalate an individual Runner only when its evidence shows the current step is insufficient: GPT-5.6 Terra / High -> GPT-5.6 Sol / Medium -> GPT-5.6 Sol / High. If GPT-6 Terra is actually exposed by the execution environment, continue GPT-6 Terra / Medium -> GPT-6 Terra / High -> GPT-6 Sol / Medium. Do not assume an unavailable model exists, and do not advance a different Runner merely because its peer needed escalation.
- Root: parent-selected model for the sprint critical path; prefer reasoning-effort escalation before model-tier escalation when the current model remains appropriate.

Do not keep a heavier model on a task solely because it was previously used there. Do not repeatedly retry the same failing task at the same model/reasoning setting. If a cheaper role proves sufficient, prefer it on future spawns. If a role stalls, return the problem to Root with evidence and recommend the next reasoning-effort step before recommending a model-tier change.

Spawn the project-scoped `coordinator` agent when beginning the multi-agent trial.
The coordinator is GPT-5.6 Luna / Low and acts only as control tower/scribe. It
maintains the private sprint storyboard, tracks worker/resource/EVE ownership,
records Git-visible checkpoints, and relays dependency-changing handoffs between
Root and runners. It does not perform network engineering, use EVE, or operate
device consoles. Prefer event-driven worker updates; while the sprint is
actively running, the coordinator may do a lightweight reconciliation at about
15-minute intervals if kept active for that purpose. Silence is preferred when
nothing changed.

Owner-gated work is an exception to ordinary quiet-state reporting. If any active
lane cannot continue without owner authorization or a concrete owner decision,
Coordinator must immediately put an `ATTENTION: OWNER ACTION REQUIRED` block at
the top of the active status artifact with the start time, blocked lane, exact
decision needed, and whether offline work continues. Root and status monitors
must treat that marker as the highest-priority sprint state and must not classify
the affected worker as idle or stalled. Clear it only after a newer explicit
owner directive resolves the gate, then retain the historical checkpoint below.

Spawn the project-scoped `hygiene` agent only for a bounded repository-hygiene pass at a meaningful milestone/closeout checkpoint or when material branch, checkpoint, documentation, or artifact drift is detected. Close it when the pass completes. Do not keep Hygiene resident merely because a concurrency slot is available; preserve that slot for a genuinely ready Runner lane.

Examples for the current sprint:

- Root: Nexus Dashboard, Cluster Bringup, Fabric Controller/NDFC lifecycle, fabric creation, and integration gates.
- Runner lane: PA-FW-1/PA-FW-2 bootstrap, management readiness, HA, interfaces/zones, then WAN/ISP prerequisites as dependencies permit.
- Optional second runner lane: DC1 Nexus switch bootstrap, exact-image/port validation, management readiness, and preparation for NDFC discovery.

### EVE multi-user and console coordination

EVE Web/API authentication is session-sensitive per user. EVE documents that the
same user can log in from only one location; a second login invalidates the first.
Never share one EVE username across concurrent agents.

For this trial, Root and the active runner should use distinct EVE identities.
Root retains its assigned EVE user; the runner uses the separate runner EVE user.
The coordinator never authenticates to EVE.

EVE Pro documents shared labs/projects and parallel Telnet/VNC consoles across
users. Treat that as DOCUMENTED but FIELD-TEST REQUIRED for this automation
because the non-owner API/lifecycle path must be proven against the current EVE
7.2.0-4 environment.

Until the shared-lab API/lifecycle field test passes:

- Root is the EVE lifecycle broker and performs plan/apply/start/stop plus
  console-endpoint discovery.
- A runner that needs a node started, stopped, or rediscovered sends the request
  to Root rather than opening a competing EVE API session.
- Root records or returns the direct console endpoint needed by the runner.

After the field test proves the second user can operate the same shared lab
through the supported EVE interface without session or ownership problems:

- Root may keep its own EVE session under its dedicated user.
- The runner may keep a separate EVE session under its dedicated user.
- Concurrent control-plane use is allowed only on separately owned resources;
  do not issue competing lifecycle mutations against the same node or topology
  object.
- The coordinator/storyboard records EVE identity assignment, node ownership,
  and any lifecycle handoff that changes who may mutate a resource.

The EVE control plane does not globally serialize guest work. EVE documents
parallel Telnet and VNC console access across users. Different agents may work
concurrently on different guest devices through serial/Telnet, VNC, SSH, or the
guest's supported API.

Maintain one active command writer per guest device or console unless Root
explicitly coordinates otherwise. Multiple observers are acceptable when the
access method supports it, but do not allow independent writers to interleave
input. RDP remains single-user per node.


When a runner finishes or blocks, Root either assigns the next ready task in that lane, transfers ownership, or closes the runner. Do not keep idle runners alive merely because the concurrency cap permits them.

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
