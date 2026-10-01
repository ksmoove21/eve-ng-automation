# Execution plans

Execution plans are durable state for substantial, long-running, or live-stateful work.

The format is defined in [`.codex/PLANS.md`](../../.codex/PLANS.md).

## Directories

- [active/](active/README.md): work that is currently in progress.
- [completed/](completed/README.md): completed or explicitly abandoned work retained for history.

An active plan is authoritative only for the sprint it names. It does not replace architecture, platform documentation, or Git.

Keep the number of active plans small. Close or archive stale plans instead of leaving ambiguous "current" state behind.
