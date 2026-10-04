# EVE-NG runtime environment

## Existing-server model

This project targets an already-existing EVE-NG installation. It does not provision
the EVE server, DNS, routing, VPNs, firewall policy, or the path from the controller
to EVE-NG.

A typical server profile is:

```yaml
servers:
  default:
    url: https://eve.example.com
    username_env: EVE_USERNAME
    password_env: EVE_PASSWORD
    timeout: 120
    ssh_username_env: EVE_SSH_USERNAME
    ssh_password_env: EVE_SSH_PASSWORD
```

Replace the example URL with the EVE-NG server used by your workspace.

## Connectivity boundary

The controller running the CLI must already be able to:

1. resolve the EVE-NG hostname when DNS is used;
2. route to the target address;
3. reach the EVE-NG web/API service; and
4. reach SSH on the EVE host for SSH-backed console and host operations.

The engine should report connectivity failures, but it should not silently alter
routing, VPN, firewall, DNS, or trust configuration to make a connection work.

## Credential groups

EVE web/API credentials:

```text
EVE_USERNAME
EVE_PASSWORD
```

EVE host SSH credentials:

```text
EVE_SSH_USERNAME
EVE_SSH_PASSWORD
```

Guest-device credentials, when required:

```text
CISCO_USERNAME
CISCO_PASSWORD
CISCO_ENABLE_SECRET

PALO_USERNAME
PALO_PASSWORD
```

Keep device credentials independent from EVE credentials. Store real values only
in the local environment or a gitignored `.env`.


## Concurrent automation workers

EVE permits only one active API login per username. Interactive GUI users must
not be reused by automation, and concurrent automation processes must not share
an EVE identity: a later login invalidates the earlier session.

Assign one generic worker identity to each concurrently active execution slot.
Keep the assignment workload-independent so the same slots can run different
platform sprints over time. Each Git worktree may carry its own gitignored
`.env` with that worker's `EVE_USERNAME` and `EVE_PASSWORD`; never copy generated
passwords into tracked examples, documentation, fixtures, logs, or commits.

When the engine source checkout and private lab workspace differ, export the
worktree-specific credential values into the worker process before selecting the
private workspace with `--root`. Environment values take precedence over the
private workspace's `.env`, preserving independent sessions even when workers
share the same lab workspace.

### Shared-lab runtime readback

In one EVE-Pro shared lab, two API users read the same lab UUID and exact node
UUIDs but received different `status` and `sat` fields for nodes started by
the other user. The manager still had live QEMU processes for nodes that one
user's API reported stopped. A normal exact-node EVE stop through the user
session that reported those nodes running cleared the processes; direct host
process termination was unnecessary.

For shared labs, do not infer guest absence from one account's stopped status.
Compare exact lab/node UUIDs, inspect the supported runtime or narrow host
process evidence when permitted, and use the account with the running view for
normal lifecycle reconciliation. Verify QEMU exit before changing placement or
links. This is an observed behavior, not an assumption that every EVE version
or shared-lab setup behaves the same way.

## TLS

TLS verification should remain enabled. If an EVE deployment uses a privately
issued certificate, trust the issuing CA on the controller rather than disabling
verification in the automation.

## Private workspace model

The engine source repository and the active lab workspace may be different.

Use the global `--root` option to select a workspace containing `labs/`,
`config/`, `.env`, and generated `.state/` data. This supports keeping
environment-specific labs and server profiles in a private repository while the
engine remains reusable and generic.
