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

Do not stop merely to report that coding, unit tests, deployment, or one
troubleshooting step completed.

## Definition of proof

Offline tests are necessary but are not sufficient for a capability that is
intended to interact with EVE-NG or a guest NOS when an appropriate image and
authorized sandbox are available.

A runtime capability is considered proven when the relevant workflow has
completed against the actual target NOS and the declared acceptance criteria
pass without weakening the human-authored intent.

Validation itself remains read-only. Remediation belongs to the outer
engineering loop, not inside `eve validate`.
