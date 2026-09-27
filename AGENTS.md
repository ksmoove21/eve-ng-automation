# Repository guidance

This fork extends the upstream `wcmder/eve-ng` project into a reusable EVE-NG
lab automation platform for the owner's networking labs.

## Operating principles

- Preserve upstream working behavior unless a change is intentional and tested.
- Treat Git as the source of truth for desired lab state and implementation.
- Prefer reusable platform capabilities over one-off lab-specific hacks.
- Keep generic automation separate from deployment-specific addressing,
  credentials, hostnames, and other environment details.
- Maintain idempotent behavior where practical. Re-running an operation should
  converge toward desired state rather than duplicate objects.
- Do not make live or destructive EVE-NG changes unless explicitly requested.
- Protect running nodes and existing state when the current engine supports it.
- Add or update tests with changes to topology parsing, reconciliation,
  lifecycle behavior, platform support, or device initialization.
- Preserve unrelated edits.
- Keep secrets out of Git. Use the existing environment-variable and local
  configuration patterns for credentials.
- Keep the existing `eve plan` -> `eve apply` -> lifecycle workflow usable
  while the platform is extended.

## Architecture boundaries

- `src/eve_lab/` owns the reusable automation engine.
- `labs/` contains concrete lab definitions and device initialization inputs.
- `tests/` verifies engine behavior without requiring a live EVE-NG instance
  unless a test is explicitly identified as an integration test.
- Device-specific behavior should remain isolated from generic topology and
  reconciliation logic.
- Higher-level abstractions may compile into the existing explicit topology
  model. Do not remove the explicit topology model merely to introduce a new
  abstraction layer.

## Development workflow

1. Understand and preserve the current upstream baseline.
2. Make changes on feature branches, not directly on `main`.
3. Run the relevant automated tests before proposing a merge.
4. For EVE-facing changes, separate offline validation from live integration
   testing and document which validation was actually performed.
5. Merge confirmed changes only into this fork unless the owner explicitly
   chooses to contribute something upstream.

## Direction

Near-term priorities are to establish the upstream baseline in the owner's
EVE-NG environment, then expand platform coverage beyond the current
Cisco C8000V and Palo Alto/Panorama focus. Likely future capabilities include
additional Cisco platforms, MikroTik CHR, reusable addressing, configuration
generation, validation, and higher-level lab specifications.

The long-term goal is a workflow where network engineering intent is designed,
stored in Git, implemented through reusable automation, deployed to EVE-NG, and
validated into a ready-to-use lab.
