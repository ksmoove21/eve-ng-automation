# Baseline validation on Windows

This runbook verifies the inherited EVE-NG automation against the existing
UNSC EVE-NG instance without changing any lab state.

Target:

```text
https://eve.unsc.in
```

The goal is to prove local Python setup, repository configuration, DNS/TLS,
EVE-NG API authentication, and server discovery before changing topology or
device support.

## 1. Clone the fork and select the foundation branch

```powershell
git clone https://github.com/ksmoove21/eve-ng-automation.git
cd eve-ng-automation
git switch automation/unsc-foundation
git status
```

Expected: the branch is `automation/unsc-foundation` and the working tree is
clean.

## 2. Create the Python environment

Python 3.11 or newer is required.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

If PowerShell execution policy prevents virtual-environment activation, use the
virtual environment's Python executable directly instead of changing machine
policy:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
```

## 3. Create the local credential file

```powershell
Copy-Item .env.example .env
```

For the first read-only API checks, only these values are required:

```text
EVE_USERNAME=<EVE web/API username>
EVE_PASSWORD=<EVE web/API password>
```

Leave SSH and guest-device credentials blank until those workflows are tested.

The `.env` file is gitignored and must not be committed.

## 4. Verify DNS and HTTPS outside the application

```powershell
Resolve-DnsName eve.unsc.in
Invoke-WebRequest https://eve.unsc.in
```

The workstation already trusts the private PKI used by `eve.unsc.in`.
Do not disable TLS verification.

A successful web request proves only DNS, routing, TCP/TLS, and web-server
reachability. API authentication is validated in the next step.

## 5. Verify EVE-NG API access

These commands are read-only:

```powershell
eve status --server default
eve templates --server default
eve template c8000v --server default
```

Success proves that the Python client can authenticate to EVE-NG and read server
and template information over HTTPS.

Record the output from `eve templates` because it becomes the source for
comparing the inherited example against the images and templates actually
installed on the UNSC EVE server.

## 6. Run the inherited offline tests

From the repository root:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

These tests should run without requiring live EVE-NG changes.

Any failure at this stage should be investigated before modifying the engine.

## 7. Validate the inherited lab definition locally

The inherited implementation currently loads server credentials even for
`plan`, although `plan` itself does not contact EVE-NG.

```powershell
eve plan palo-lab1 --server default
```

This validates the checked-in topology YAML and reports local object counts.

## Stop point

Do not run these during baseline validation:

```text
eve apply
eve start
eve stop
eve delete
eve init
eve restore
eve bootstrap --attach
eve nat add
eve nat remove
eve dhcp update
eve dhcp clear
```

The next phase begins only after:

- the offline tests pass;
- HTTPS/API authentication succeeds;
- template discovery succeeds; and
- the installed EVE image/template inventory has been reviewed.

At that point, create a dedicated disposable baseline lab rather than applying
the inherited `palo-lab1` definition blindly.
