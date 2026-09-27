# Baseline validation on Windows

This runbook verifies a fresh checkout from Windows PowerShell before making live
topology changes.

## 1. Clone the repository

```powershell
git clone https://github.com/ksmoove21/eve-ng-automation.git
cd eve-ng-automation
git status
```

Expected: `main` is checked out and the working tree is clean.

## 2. Create the Python environment

Python 3.11 or newer is required.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

If PowerShell execution policy prevents virtual-environment activation, invoke
the virtual environment's executables directly rather than weakening machine
policy.

## 3. Configure a workspace

A workspace may be this repository or a separate/private repository.

For an in-repository test, copy the example credential file:

```powershell
Copy-Item .env.example .env
```

Populate your own EVE credentials and edit `config/servers.yaml` to point to
your EVE-NG instance.

For a separate workspace, use the same `labs/`, `config/`, and `.env`
layout and pass it with:

```powershell
eve --root H:\Github\my-eve-workspace status --server default
```

Keep `.env` gitignored.

## 4. Verify DNS, TLS, and SSH independently

Use the actual hostname from your server profile:

```powershell
Resolve-DnsName eve.example.com
Invoke-WebRequest https://eve.example.com
ssh root@eve.example.com
```

Use the appropriate SSH account for your server. Verify and trust the expected
host key. If the HTTPS certificate is privately issued, trust the issuing CA
rather than disabling TLS verification.

## 5. Verify read-only EVE API access

```powershell
eve status --server default
eve templates --server default
eve template c8000v --server default
```

These checks do not deploy or modify a lab.

## 6. Run offline tests

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

Known inherited POSIX-specific test assumptions are documented in
`structure.md`.

## 7. Plan a generic fixture locally

```powershell
eve plan iosxe-baseline --server default
eve plan gre-vrf-validation --server default
```

Planning validates local lab intent. Review referenced image names against the
target server before applying anything.

## Stop point

Do not continue to `apply`, `start`, `init`, `restore`, `delete`, NAT,
or DHCP changes until you have reviewed the target environment and explicitly
intend to modify it.
