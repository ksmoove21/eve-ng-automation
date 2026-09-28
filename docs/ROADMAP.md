# EVE-NG Automation Roadmap

This fork starts from `wcmder/eve-ng` and preserves its current declarative
topology and lifecycle model while extending it for broader network-lab use.

## Goal

Create a reusable lab platform where network engineering intent is stored in
Git, compiled into explicit EVE-NG topology and device configuration, deployed
through the automation engine, and validated before the lab is considered
ready.

The automation engine should remain usable without an AI agent. ChatGPT and
Codex may assist with design and implementation, but Git and the automation
code are the durable source of truth.

## Phase 0: Preserve the baseline

- Keep the inherited `palo-lab1` example functional.
- Inventory the current CLI, topology schema, supported templates, and tests.
- Establish an offline regression-test workflow.
- Establish a separate live-integration checklist for a target EVE-NG host.
- Document the local development and Git branching workflow.
- Do not redesign working upstream behavior before a baseline is established.

Exit criteria:

- Existing automated tests pass locally.
- `eve plan palo-lab1` succeeds with local configuration.
- The engine can authenticate to the target EVE-NG instance.
- A non-destructive status/template query succeeds.

## Phase 1: Environment compatibility

Adapt the fork to the target EVE-NG installation without embedding
environment-specific values in reusable engine code.

Candidate work:

- EVE server profile configuration.
- Installed image/template inventory.
- Management cloud/network mapping.
- Interface-name compatibility checks.
- Integration-test fixtures and dry-run procedures.

Exit criteria:

- Existing example topology can be planned against the local image inventory.
- No secrets or private infrastructure values are committed to Git.

## Phase 2: Platform expansion

Add platform support incrementally, with one platform per feature branch where
practical.

Initial targets:

1. Palo Alto VM-Series firewall validation (Panorama excluded)
2. Cisco NX-OSv / Nexus 9000v, including vPC readiness
3. Cisco IOSv / IOSvL2
4. MikroTik CHR
5. Additional IOS XE variants as needed

Each platform addition should define:

- EVE template/image handling.
- Interface normalization.
- Console or management bootstrap behavior.
- Configuration save semantics.
- Backup/restore behavior where supported.
- Automated tests.

A platform is not considered complete merely because its adapter, parser, or
offline tests exist. Where the required image is available in the designated
EVE development sandbox, platform completion requires end-to-end proof that:

- the topology plans successfully;
- the node deploys/reconciles successfully;
- the guest reaches usable readiness;
- bootstrap/initialization succeeds;
- configuration-save semantics are verified where applicable;
- declared validation succeeds against the actual NOS;
- offline regression tests remain green; and
- reusable platform quirks/failures discovered during live testing are recorded.

If live testing fails, the sprint continues through diagnosis, repair, and
retest unless a true architectural, authorization, resource, or technical
blocker is reached.

## Phase 3: Reusable lab services

Build reusable capabilities that reduce per-lab manual configuration.

Candidate capabilities:

- IPv4/IPv6 address allocation.
- Loopback allocation.
- Point-to-point subnet generation.
- ASN allocation.
- Device-role defaults.
- Common management configuration.
- Configuration rendering.
- Platform-aware interface mapping.

These should remain separate from concrete lab definitions.

## Phase 4: Network feature modules

Introduce reusable configuration-generation components for commonly tested
network behaviors.

Initial candidates:

- BGP and policy controls.
- OSPF.
- IS-IS.
- VRFs.
- MPLS/LDP.
- MP-BGP L3VPN.
- GRE.
- NAT.
- MTU/MSS controls.

A feature module should describe intended network behavior while leaving
platform-specific syntax to the appropriate renderer.

## Phase 5: Validation and readiness

A deployed lab is not considered ready merely because EVE nodes exist.

Introduce acceptance checks for:

- Node runtime state.
- Interface state.
- IGP adjacency.
- BGP session state.
- Expected route presence.
- End-to-end reachability.
- Feature-specific assertions.
- Defined failure/recovery scenarios.

Long-term readiness output should distinguish topology deployment, guest boot,
configuration application, protocol convergence, and acceptance-test status.

## Phase 6: Higher-level lab specification

Keep the current explicit `topology.yaml` model as a stable lower-level
contract.

Add an optional higher-level specification that can describe intent such as:

- device roles and counts;
- logical links and site relationships;
- routing protocols;
- addressing pools;
- failure scenarios;
- acceptance criteria.

A compiler/renderer may expand that intent into the explicit topology,
configuration, and validation artifacts consumed by the existing engine.

## Phase 7: Agent-assisted workflow

Optimize the development workflow around engineer-defined intent and autonomous
sprint execution.

Desired flow:

1. Engineer and ChatGPT define the lab objective, architecture, execution
   boundary, and acceptance criteria.
2. Durable intent is represented in Git where appropriate.
3. Codex implements or reuses automation components on a feature branch.
4. Codex runs focused offline tests.
5. Codex uses the designated disposable EVE development lab to deploy, start,
   initialize, and validate the real guest platform when the sprint requires
   runtime proof.
6. Intermediate failures feed directly into diagnosis, repair, and retest
   without an owner nudge.
7. Codex stops only for a material architecture/intent change, an unauthorized
   infrastructure boundary, unavailable required resources, or a persistent
   technical blocker.
8. The engineer and ChatGPT review the completed diff and evidence.
9. Confirmed changes merge into this fork.

The agent is an implementation worker, not the durable project memory. Git owns
the implementation and intent that must survive across sessions. The private
workspace owns environment-specific lab inputs. A Codex conversation should be
disposable once its sprint is complete.

MCP or another agent-control interface may be added later for interactive
operation, but it is not a dependency of the core automation engine.

## Upstream relationship

The original implementation is `wcmder/eve-ng`.

This fork is intended for independent experimentation and extension. Changes
remain in this fork unless a maintainer explicitly decides to contribute a
specific change upstream.
