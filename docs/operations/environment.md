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
