# Known operator workflows

This directory captures working human procedures that automation should reproduce or intentionally improve.

The purpose is to prevent the automation effort from spending hours rediscovering a lifecycle the operator already knows.

Only reusable/public workflow facts belong here. Environment-specific hostnames, addressing, credentials references, and private topology belong in the private workspace.

## When to create a workflow document

Create one when:

- the owner already has a known-good manual process;
- a controller/appliance has a multi-stage lifecycle;
- UI interactions hide ordering or readiness requirements;
- automation repeatedly diverges from a working manual path;
- version-specific behavior matters.

## Template

```markdown
# <Workflow name>

## Purpose
What result the operator obtains.

## Applicability
Platform, product, version/train, image, and known exclusions.

## Focused manual baseline
Approximate time for a competent operator when prerequisites are healthy.

## Prerequisites
Images, licenses, reachability, credentials, resources, PKI, DNS, etc.

## Known-good sequence
1. Step.
2. Step.
3. Step.

## Observable checkpoints
For each lifecycle transition, state what proves that it is actually complete.

## Human interactions to eliminate
Prompts, modals, confirmations, credential entry, waits, copy/paste, etc.

## Candidate automation surfaces
Documented API/CLI/browser/configuration mechanisms and their evidence class.

## Known failure signatures
Failures that have already been explained and should not trigger rediscovery.

## Acceptance
What must be true for the automated workflow to be considered equivalent or better.

## Evidence
Links to vendor docs, platform docs, field observations, or relevant ExecPlans.
```

## Usage rule

Start automation from this workflow when it exists.

Research is still required where the workflow leaves a real gap, where the target version differs, or where live evidence contradicts the recorded procedure. Do not independently rediscover every step merely because the final implementation uses a different interface.

Update the workflow when live evidence proves it stale.
