# Codex workspace context

Use this file to re-establish repository context at the start of every new Codex chat or sprint.

## Authoritative local roots

- Public automation repository: `H:\Github\eve-ng-automation`
- Private environment repository: `H:\Github\unsc-homelab`
- Private EVE workspace: `H:\Github\unsc-homelab\VSCode Labs\EVE-Workspace`

The public repository contains reusable automation framework code.

The private repository contains UNSC-specific environment context, lab definitions, topology, addressing, credentials references, and other environment-specific implementation data.

## New-chat bootstrap contract

Before implementation work:

1. Verify that `H:\Github\eve-ng-automation` exists.
2. Verify that `H:\Github\unsc-homelab` exists.
3. Treat the public repository as the primary working root unless the sprint explicitly requires private-repository changes.
4. Read the public root `AGENTS.md`.
5. Read the architecture documents referenced by `AGENTS.md`.
6. When private lab or environment context is required, read the applicable guidance under the private EVE workspace.
7. Use absolute paths when crossing between the public and private repositories.
8. Do not clone duplicate repositories or silently substitute another drive/path because a new chat starts without the prior shell context.
9. If `H:` is unavailable, report that as the blocker rather than inventing an alternate workspace.
10. Verify the current Git branch and working-tree status before modifying either repository.

Git and repository guidance are the durable source of project context. Prior chat memory is supplemental and must not override checked-in project guidance or current repository state.

## Repository boundary

Keep reusable code, validators, schemas, tests, and generic documentation in the public repository.

Keep UNSC-specific addressing, hostnames, topology, private lab definitions, secrets references, and environment-specific overrides in the private repository.

Do not leak private values into public fixtures, examples, tests, or documentation.

## Sprint behavior

Once the sprint objective and acceptance criteria are established, continue through inspection, implementation, testing, applicable live validation, remediation, documentation, and scoped commits without returning control at ordinary intermediate steps.

Stop only at a true risk or authorization boundary as defined by `AGENTS.md` and `docs/architecture/EXECUTION-MODEL.md`.
