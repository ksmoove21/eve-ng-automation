# Project intent

This repository extends the upstream `wcmder/eve-ng` operating model rather
than replacing it.

The goal is simple: remove repetitive lab preparation so the engineer can move
from network intent to a usable EVE-NG lab with as little manual work as
practical.

The inherited lifecycle remains the foundation:

```text
lab definition + configs
        |
        v
eve plan
        |
        v
eve apply
        |
        v
eve start
        |
        v
eve init
        |
        v
eve validate
        |
        v
operator access / engineering work
```

New work should extend that flow with additional platform support, validation,
backup/restore, operator conveniences such as SecureCRT session generation, and
other reusable capabilities. Prefer integrating existing APIs and tools over
recreating control planes that already exist.

## Division of responsibility

The engineer owns:

- desired outcome;
- network architecture;
- constraints and authorization boundaries;
- acceptance criteria; and
- material design decisions.

ChatGPT may help refine architecture, identify dependencies, and translate
intent into an implementation contract.

Codex or another coding agent owns the implementation work inside those
boundaries: inspect the existing code and APIs, write the code, test it, exercise
it in the designated sandbox, diagnose failures, repair the implementation, and
finish the sprint.

Git is the durable record. A coding-agent conversation is disposable after its
sprint is complete.

## Design principles

- Keep the system simple enough to understand and operate without an AI agent.
- Keep reusable engine logic separate from lab- and environment-specific data.
- Preserve working upstream behavior unless a change is intentional and tested.
- Prefer extension and composition over parallel replacement systems.
- Treat real EVE/NOS integration as part of proving runtime features.
- Keep provider-specific infrastructure automation outside the reusable EVE lab
  engine unless an optional integration explicitly requires it.
