# Execution model

The unit of work is a sprint with an objective and acceptance criteria, not an
individual prompt or command.

## Normal engineering loop

```text
intent
  -> implement
  -> focused offline tests
  -> designated EVE sandbox
  -> real NOS initialization / validation
  -> failure evidence
  -> diagnose and repair
  -> retest
  -> PASS with evidence
```

An intermediate failure is not a handoff point. If the repair remains inside
the agreed architecture and authorization boundary, the coding agent should
continue without waiting for another owner prompt.

## Resume behavior

A conversation turn ending does not end an unfinished sprint.

When execution resumes later, the previous turn's final technical state is the
checkpoint. Continue from the active lab/process/test state without restarting
planning, repeating completed work, or asking for authorization that is already
recorded in the sprint and repository guidance.

Refresh remote guidance only when it may have changed, preserve local working
state, then resume the next technical action. Keep restart overhead small.

At a true sprint boundary, prefer a fresh Codex thread so the next task does not
inherit unrelated tool output and troubleshooting history. Do not restart an
actively progressing sprint solely to obtain a smaller context.

## Context discipline

Context is an engineering resource. Use enough evidence to make the next
technical decision, but avoid repeatedly carrying information that is already
durable in Git.

- Start with `.codex/workspace-context.md` and `AGENTS.md`; load additional
  architecture documents only when the current task needs their owning
  decisions.
- Search first when the relevant location is unknown, then read the smallest
  useful range. Read complete files when editing them or when surrounding
  context is necessary for correctness.
- Bound potentially large command, log, diff, config, and test output. Prefer
  targeted commands and relevant ranges over full dumps.
- During iteration, run focused tests that can falsify the current change.
  Reserve broad regression suites for meaningful acceptance gates.
- Poll long-running NOS boots, controller jobs, commits, and other asynchronous
  operations at bounded intervals rather than tight loops.
- Keep standing project rules in checked-in guidance and sprint-specific
  requirements in the prompt. Do not restate the complete project architecture
  in every sprint prompt.
- Before compaction or a sprint handoff, persist important state, decisions, and
  evidence in Git-backed artifacts so continuation does not depend on chat
  history.

These rules optimize context use without weakening live proof, test coverage, or
failure evidence.

## Diagnostic depth

Use the highest-level supported interface first, but do not remain trapped at
that layer when it stops producing useful evidence.

Escalate diagnostic depth as needed:

```text
supported command / API
        |
        v
returned evidence / application logs
        |
        v
raw device console or transport
        |
        v
EVE runtime / process observation
        |
        v
narrowly scoped host inspection
        |
        v
research + hypothesis
        |
        v
repair
        |
        v
live retest
```

Do not repeatedly rerun the same failing operation without obtaining new
evidence or changing a justified hypothesis.

Read-only host inspection that is narrowly scoped to the runtime of a designated
disposable EVE test lab may be used to understand that lab's behavior. Host-side
mutation, process termination, global EVE changes, or recovery actions still
require the authorization applicable to the task. Observation does not imply
standing permission to alter the EVE host.

## Lifecycle-first controller automation

Controller platforms expose console, GUI, and API capabilities at different
points in their lifecycle. Model the current product state, its documented next
transition, and that transition's prerequisites before classifying an API error,
GUI condition, or service state as a fault.

The supported operator lifecycle is the behavioral authority. Use a documented
API only when it is both supported and available in the current lifecycle state.
When that API is not yet available, automate the equivalent documented GUI, CLI,
or serial-console action a human operator would perform. An unavailable API
before its expected lifecycle state is evidence about the transition; it is not
by itself a platform failure. Do not replace such a transition with undocumented
browser endpoints or internal GUI requests.

After each transition, collect only the health and state evidence that the
product documents for that stage. Continue to the next lifecycle action when
that evidence is satisfied; investigate or repair only when a documented
prerequisite or expected transition fails.

## External research

Research is part of implementation when observed behavior depends on uncertain
external platform facts.

Use research when needed for device boot behavior, image/resource requirements,
vendor syntax, API semantics, version-specific limitations, release behavior,
or known defects.

Prefer evidence in this order:

1. vendor/platform documentation;
2. upstream project documentation and source;
3. vendor or upstream release notes and bug documentation;
4. reputable community evidence.

Research should explain or constrain a hypothesis, not replace live validation.
Test the conclusion against the actual disposable lab before treating it as a
durable platform fact.

## Execution zones

### Repository and offline work

Autonomous. The agent may inspect, edit, test, and refactor within the current
sprint while preserving unrelated user work.

### Designated disposable EVE development/test labs

Autonomous. The agent may plan, apply, start, stop, initialize, configure,
validate, reset, recreate, and delete lab objects and guest devices as needed to
prove the sprint.

These labs are part of the integration-test harness.

### Parent or persistent infrastructure

Requires explicit task authorization. This includes the EVE host operating
system, vSphere, physical network devices, production/shared firewalls and
routing, shared services, and persistent labs that were not designated for
automation testing.

## Stop conditions

Return control when:

- continuing would materially change the agreed architecture or human intent;
- continuing would cross the authorized infrastructure boundary;
- required credentials, images, licenses, or other resources are unavailable;
- a technically meaningful blocker remains after reasonable remediation; or
- the sprint acceptance criteria are satisfied.

Do not stop merely to report that coding, unit tests, deployment, one
troubleshooting step, research, or a recovery action completed. Progress-only
messages are not sprint completion.

## Definition of proof

Offline tests are necessary but are not sufficient for a capability that is
intended to interact with EVE-NG or a guest NOS when an appropriate image and
authorized sandbox are available.

A runtime capability is considered proven when the relevant workflow has
completed against the actual target NOS and the declared acceptance criteria
pass without weakening the human-authored intent.

Validation itself remains read-only. Remediation belongs to the outer
engineering loop, not inside `eve validate`.
