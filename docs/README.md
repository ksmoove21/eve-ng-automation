# Documentation

Documentation is organized by responsibility and loaded progressively.

## System and engineering

- [../ARCHITECTURE.md](../ARCHITECTURE.md): top-level component map, boundaries, and ownership.
- [architecture/PROJECT-INTENT.md](architecture/PROJECT-INTENT.md): purpose and human/agent division of responsibility.
- [architecture/STRUCTURE.md](architecture/STRUCTURE.md): durable technical and repository conventions.
- [architecture/EXECUTION-MODEL.md](architecture/EXECUTION-MODEL.md): long-running execution, research, retry, authorization, and stop conditions.

## Execution knowledge

- [exec-plans/](exec-plans/README.md): durable active/completed plans for substantial work.
- [workflows/](workflows/README.md): known-good operator workflows that automation should reproduce.
- [platforms/](platforms/README.md): durable NOS/controller-specific behavior.
- [operations/](operations/): validation and operator/environment procedures.

## Historical and future context

- [lessons/README.md](lessons/README.md): chronological reusable engineering evidence. It is historical context, not current sprint state.
- [roadmap/ROADMAP.md](roadmap/ROADMAP.md): future product direction.

The root README remains the operator entry point and command reference. Internal agent process and sprint narration belong in the scoped documents above.
