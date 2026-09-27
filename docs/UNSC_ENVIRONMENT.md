# UNSC EVE-NG environment

## Existing target

This fork targets an existing EVE-NG installation rather than provisioning an
EVE-NG server.

Default server:

```text
eve.unsc.in
```

The checked-in server profile is:

```yaml
servers:
  default:
    url: http://eve.unsc.in
```

Credentials are not stored in this file. They remain in the local `.env` file
or the caller's shell environment.

## Connectivity boundary

The automation assumes the workstation running the CLI can already:

1. resolve `eve.unsc.in`;
2. route to the resolved address;
3. reach the EVE-NG web/API service; and
4. reach SSH on the EVE-NG host when an SSH-backed command is used.

Private routing, WireGuard, local DNS, firewall policy, and other transport
dependencies are external prerequisites. This repository should detect and
report reachability failures, but it should not automatically establish or
modify those connectivity mechanisms.

This keeps the automation usable whether the EVE-NG instance is local, hosted,
or reachable through a private tunnel.

## Credential groups

### EVE-NG web/API

Required for API-backed commands:

```text
EVE_USERNAME
EVE_PASSWORD
```

### EVE-NG host SSH

Required only for workflows that SSH to the EVE host:

```text
EVE_SSH_USERNAME
EVE_SSH_PASSWORD
```

### Guest devices

Required only when the automation logs into the emulated devices:

```text
CISCO_USERNAME
CISCO_PASSWORD
CISCO_ENABLE_SECRET

PALO_USERNAME
PALO_PASSWORD
```

Device credentials are intentionally independent of EVE-NG credentials.

## Initial baseline validation

Before modifying topology or device support, verify the inherited engine against
the existing server with non-destructive operations:

```text
eve status --server default
eve templates --server default
eve template c8000v --server default
```

After server discovery succeeds, inspect installed images and templates before
attempting `apply`, `start`, `init`, or other state-changing operations.

## HTTP versus HTTPS

The inherited implementation used HTTP, so this fork initially preserves that
behavior for the UNSC target. If `eve.unsc.in` is later confirmed to use HTTPS
for its EVE-NG API, update `config/servers.yaml` to the HTTPS URL and validate
the client behavior before merging that change.
