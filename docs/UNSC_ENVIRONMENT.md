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
    url: https://eve.unsc.in
```

Credentials are not stored in this file. They remain in the local `.env` file
or the caller's shell environment.

## Connectivity boundary

The automation assumes the workstation running the CLI can already:

1. resolve `eve.unsc.in`;
2. route to the resolved address;
3. reach the EVE-NG HTTPS/API service; and
4. reach SSH on the EVE-NG host when an SSH-backed command is used.

Private routing, WireGuard, local DNS, firewall policy, and other transport
dependencies are external prerequisites. This repository should detect and
report reachability failures, but it should not automatically establish or
modify those connectivity mechanisms.

The automation is intentionally independent of the hosting platform. It should
not contain provider-specific assumptions for Azure, AWS, on-premises
virtualization, or another hosting location unless a future feature explicitly
requires one.

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

## HTTPS

`eve.unsc.in` uses HTTPS. The checked-in server profile therefore uses:

```text
https://eve.unsc.in
```

If the certificate is privately issued, the client must trust the issuing CA
through the operating system or Python trust path rather than disabling TLS
verification in the automation.
