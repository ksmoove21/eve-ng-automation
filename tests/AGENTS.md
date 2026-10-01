# Test guidance

This file applies to `tests/`.

Tests should verify real repository behavior, not create a second implementation contract.

## Scope

- Add focused coverage for changed behavior and important boundaries.
- Keep ordinary unit tests independent of a live EVE server.
- Mark true live/integration behavior explicitly rather than hiding network dependencies in unit tests.
- Reuse existing helpers and patterns before adding test-only abstractions.

## Integrity

Do not weaken assertions, lower acceptance thresholds, mark required behavior optional, or change production intent merely to make tests green.

Avoid production hooks or alternate runtime branches whose only purpose is to make a test easy. Prefer exercising existing public or internal boundaries.

Do not rewrite unrelated tests during a scoped feature change.

## Validation order

Use proportional validation:

1. the smallest test that can falsify the change;
2. the affected module/platform test set;
3. targeted live integration when runtime behavior changed;
4. broader regression at a meaningful acceptance gate.

Do not run the full suite after every edit when a smaller test answers the current question.

Report known unrelated failures separately from failures introduced by the current change.
