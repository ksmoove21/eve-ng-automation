# Lessons Learned

This changelog records concrete lessons from implementation, testing, and live
EVE-NG evidence. Each entry should closely mirror the final completion report,
including:

- the outcome and root cause
- a summary of code and file changes
- exact test and integrity-check results
- whether evidence is offline or from live EVE-NG
- remaining limitations or live verification
- commit, push, and merge status

Code diffs may be summarized, but verification results, evidence boundaries,
remaining work, and repository status should be retained. Sensitive console
contents and credentials must never be recorded.

Only this file may be committed and pushed automatically after a completed
prompt. Other repository changes remain uncommitted unless the owner explicitly
requests otherwise.

## 2026-09-27 - IOS XE VRF BGP and read-only console attachment

### VRF BGP requires a route distinguisher

On C8000V 17.16.01a, entering `address-family ipv4 vrf BLUE` failed with
`% VRF BLUE does not have an RD configured.` IOS XE stayed in router
configuration mode, so the following neighbor, network, and
`exit-address-family` commands were interpreted in the wrong context.

The lab fix was to configure an RD under each endpoint's `vrf definition BLUE`.
`exit-address-family` was correct and was retained. Live evidence confirmed the
global OSPF adjacency and the GRE tunnel using global Loopback0 transport with
Tunnel100 in VRF BLUE.

### Ctrl-R alone does not reliably wake an EVE serial console

A running IOS XE console attached through EVE may remain silent after Ctrl-R.
A manual Return caused the privileged EXEC prompt to appear immediately and
released queued validation commands on both R1 and R3.

The read-only login path now waits briefly after Ctrl-R and may send exactly one
blank Return. It first rejects setup, authentication, confirmation, selection,
and configuration-mode prompts so validation cannot accept defaults or enter
configuration.

### Transport noise must be classified separately from interactive prompts

The first fallback implementation was too strict because an EVE Telnet
attachment can buffer harmless transport and console material before a usable
prompt. Benign input includes blank lines, `Trying`/`Connected`/escape-character
preamble lines, raw or printable Ctrl-R artifacts, IOS XE syslog records, and
stale EXEC prompt fragments.

The classifier now explicitly permits those forms while unknown input and all
recognized interactive prompts remain fail-closed. Offline regression coverage
passes for the one-time Return behavior and all refusal cases. The revised
benign-noise classifier still requires live EVE-NG verification.

### The expanded benign-noise classifier still fails live

Live validation after expanding the benign-noise classifier still refused the
one-time Return on both R1 and R3. The available error identified only that some
buffered material was unclassified, so adding more guessed patterns would risk
weakening the read-only guard without identifying the actual input shape.

The refusal path now reports structural evidence only: character and logical-line
counts, category counts, unclassified line lengths, whether those lines contain
control characters, and the control-character code points. It never includes
printable console text, addresses, hostnames, commands, or credentials. The
allowlist and refusal policy are unchanged. Offline redaction and regression
tests pass; the diagnostic output still requires live EVE-NG collection before
the classifier should be changed again.

#### Verification and repository status

- `ReadOnlyLoginTests`: 14 passed.
- `ConsoleTests`: 15 passed.
- All validation tests: 50 passed.
- `git diff --check`: passed, with line-ending conversion warnings only.
- No live EVE operations were performed while implementing the diagnostic.
- `src/eve_lab/device_console.py` and `tests/test_validation_runner.py` remain
  uncommitted for review.
- The diagnostic lesson was committed and pushed separately as `50ecf1e`; the
  feature branch was not merged.
## 2026-09-27 - Changelog entries mirror completion reports

The owner clarified that Lessons Learned entries should preserve nearly all
information from the final completion response. Code changes may be summarized,
but exact verification results, evidence boundaries, remaining work, and
repository status are required for later review away from the console.

The README format and `structure.md` convention now state those requirements.
This was a documentation-only change; no tests or live EVE operations were
needed. `git diff --check` passed with line-ending conversion warnings only.
The README update is committed and pushed separately under the changelog
convention. The `structure.md` convention change and all existing engine, test,
and lab work remain uncommitted, and the feature branch remains unmerged.

## 2026-09-27 - Live console diagnostic identifies ESC/BEL input

One explicitly authorized read-only `eve validate gre-vrf-validation` run was
performed. It returned exit status 1 because console prompt acquisition still
refused the one-time Return on both R1 and R3.

Both nodes produced the same structural classification:

- 80 buffered characters across 5 logical lines
- 3 Telnet preamble lines
- 1 Ctrl-R artifact line
- 0 blank, syslog, EXEC-prompt, unsafe-interactive, or configuration-prompt lines
- 1 unclassified line with length 7
- the unclassified line contained `U+001B` (ESC) and `U+0007` (BEL)

This proves the current refusal is caused by a short terminal-control-bearing
line rather than a recognized setup, credential, confirmation, or configuration
prompt. The diagnostic intentionally did not reveal the five printable
characters in that line, so their contents remain unknown.

No classifier, engine, test, lab, or configuration changes were made from this
evidence. No tests were needed because the repository was unchanged. No second
live command was run. The next change should identify the terminal-control
sequence safely before deciding whether it is benign; the allowlist must not be
weakened from this evidence alone.

This README update is committed and pushed separately under the changelog
convention. All existing engine, test, `structure.md`, and lab changes remain
uncommitted, and the feature branch remains unmerged.

## 2026-09-27 - OSC title normalization resolves live console acquisition

### Identified control sequence

The seven-character line containing ESC and BEL was consistent with an xterm
Operating System Command used to set a terminal title: `ESC ] Ps ; Pt BEL`.
Xterm defines selectors 0, 1, and 2 for icon/window titles, and ECMA-48 defines
OSC as a delimited control string. A sequence such as `ESC ] 0 ; R1 BEL` is
exactly seven characters. Raw console contents remained redacted.

The successful live run after normalization proves that the rejected input
matched a complete OSC title/icon form with selector 0, 1, or 2 and a BEL or ST
terminator. The exact selector and printable title were not logged.

References:

- [Xterm control sequences](https://xorg.freedesktop.org/archive/X11R6.8.0/PDF/ctlseqs.pdf)
- [ECMA-48 control strings](https://ecma-international.org/wp-content/uploads/ECMA-48_3rd_edition_march_1984.pdf)

### Code and safety behavior

`src/eve_lab/device_console.py` now recognizes only complete OSC title/icon
sequences matching:

```text
ESC ] [0|1|2] ; printable-payload (BEL | ST)
```

Those sequences are removed before existing CSI and Ctrl-R normalization.
Printable text outside the sequence is preserved. Incomplete OSC, unsupported
OSC selectors, and unknown escape-sequence families remain unclassified and
unsafe. Setup, credentials, confirmation, selection, and configuration-mode
refusal behavior is unchanged. Normal initialization logic is unchanged.

`tests/test_validation_runner.py` adds coverage for BEL and ST termination, a
Telnet preamble plus OSC sequence, incomplete and unknown escape sequences, an
unsupported OSC selector, and preservation of printable text outside a complete
OSC sequence.

### Verification and repository status

- `ReadOnlyLoginTests`: 18 passed.
- `ConsoleTests`: 15 passed.
- All validation tests: 54 passed.
- `git diff --check`: passed with line-ending conversion warnings only.
- One explicitly authorized live `eve validate gre-vrf-validation` run exited 0.
- All 13 declared checks passed across R1 and R3, including OSPF, global and VRF
  routes, VRF BGP, default route, negative route, VRF pings, and MTU/DF ping.
- No second live command was run.
- `src/eve_lab/device_console.py` and `tests/test_validation_runner.py` remain
  uncommitted for review.
- This README update is committed and pushed separately under the changelog
  convention. The feature branch remains unmerged.


## 2026-09-27 - Main README now explains the fork before the upstream reference

The repository landing page was updated so a new human or AI worker can understand
this fork without inferring behavior from the inherited upstream documentation.

The new front matter:

- identifies the repository as a fork of `wcmder/eve-ng`
- summarizes the capabilities added by this fork
- documents the proven `gre-vrf-validation` reference and its 13 live-passing checks
- explains the intended `plan -> apply -> start -> init -> validate` workflow
- provides Windows PowerShell and Linux/macOS setup examples
- directs agents to `AGENTS.md`, `structure.md`, and this changelog before changes
- documents credentials, image, safety, and inherited portability considerations
- preserves the broader upstream-derived command reference below the fork-specific guidance

This was a documentation-only change. No engine behavior, lab definitions, tests,
or live EVE state were modified. The README change was reviewed on branch
`docs/readme-fork-guide`, merged through PR #3, and is now present on `main`.


## 2026-09-27 - Public repository separated from private lab workspaces

The public fork was generalized so reusable engine code and regression fixtures no
longer depend on the owner's private environment naming.

Changes on `refactor/generic-public-repo`:

- repository branding and README language were made generic
- `config/servers.yaml` now uses `https://eve.example.com` instead of a private endpoint
- `docs/UNSC_ENVIRONMENT.md` was replaced by generic `docs/ENVIRONMENT.md`
- `docs/UNSC_ROADMAP.md` was renamed to `docs/ROADMAP.md` and owner-specific wording was removed
- the Windows baseline runbook was rewritten around a generic target environment
- `unsc-baseline` was renamed to `iosxe-baseline`, including the topology name
- `structure.md` now explicitly supports external/private workspaces
- the CLI `--root` help now describes a workspace root rather than a repository root
- the README documents using an installed public engine against a separate private
  workspace containing `labs/`, `config/`, `.env`, and `.state/`

No validation semantics, topology reconciliation behavior, device initialization,
or console safety behavior changed. No live EVE operations were performed for
this refactor. The generic fixtures remain `iosxe-baseline` and
`gre-vrf-validation`; environment-specific labs are expected to live outside
the public engine repository when privacy is desired.

## 2026-09-27 - PAN-OS optional checks cannot mask execution failure

### Root cause and transport review

The live `No route to host` result for firewall `LAB-PA-01` was caused by stale
private workspace state. `init.yaml` declared management address `10.0.212.131`,
while manual PAN-OS console inspection showed the DHCP-assigned management
address was `10.0.212.38/24` with gateway `10.0.212.254`. The device was running
and reachable through its EVE console. This does not prove a defect in the
existing EVE `direct-tcpip` management SSH path.

`connect_palo()` retains verified device host-key checking while carrying the
SSH session through the already verified EVE SSH connection. Initialization and
console backup reuse that transport when `management_ip` is declared, while
serial console remains available for their existing workflows. PAN-OS running
configuration retrieval already disables CLI paging for the session before
requesting XML. Panorama remains excluded from validation.

The minimum private workspace correction is temporary runtime data:

```yaml
LAB-PA-01:
  management_ip: 10.0.212.38
```

Because that address came from DHCP, it is suitable for the next validation run
but is not a durable static management design. The current validator implements
only the explicit EVE-tunneled path and does not silently try a direct controller
connection. A future direct mode should use an explicit transport field rather
than automatic fallback, but no transport redesign was justified or implemented
for this incident.

### Validation result semantics

The validator previously converted node transport, running-config retrieval,
and XML parsing failures into failed checks. If every check was optional,
`_append_result()` left the overall report as `pass`, even though no assertion
had executed.

`src/eve_lab/validation.py` now marks every node-level execution failure as an
overall failure before appending per-check evidence. That evidence includes
`failure_kind: execution`. A successfully executed optional assertion mismatch
still remains a visible failed check while preserving overall `pass`; required
assertion mismatches still fail the run.

`tests/test_validation_panos_runner.py` covers successful optional and required
assertion semantics, management SSH failure, running-config retrieval failure,
XML parse failure, and successful validation. `docs/validation.md` documents the
execution/assertion distinction, DHCP management-address limits, and the single
implemented EVE-tunneled PAN-OS transport.

### Verification and next live step

- Focused PAN-OS validation and transport tests: 17 passed.
- Full `test_validation*.py` suite: 66 passed.
- `git diff --check`: passed with line-ending conversion warnings only.
- No live EVE or PAN-OS operation was performed.
- After updating the private `init.yaml`, run from the private workspace root:
  `eve validate UNSC-Home-Replica-01`.
- `src/eve_lab/validation.py`, `tests/test_validation_panos_runner.py`, and
  `docs/validation.md` remain uncommitted for review.
- This README entry is committed and pushed separately under the changelog
  convention. The feature branch remains unmerged.

## 2026-09-27 - Live PAN-OS validation fails closed on an untrusted device key

One explicitly authorized, read-only live validation was run against EVE lab
`UNSC-Home-Replica-01` and firewall `LAB-PA-01`. The private workspace still
declared the stale DHCP address `10.0.212.131`, so the test used a process-local
override to target the console-observed address `10.0.212.38`. No workspace file,
EVE object, or PAN-OS setting was changed.

The standard validation path connected to EVE and reached the corrected PAN-OS
management target through the existing Paramiko `direct-tcpip` channel. Device
SSH setup then refused the connection because the PAN-OS host key for
`10.0.212.38` was not present in the trusted host-key store. Host-key checking
was not weakened or bypassed.

The live result was:

- command exit status: 1
- overall result: `fail`
- check: `transport-xml-smoke`
- assertion setting: `required: false`
- check result: `fail`
- evidence kind: `failure_kind: execution`
- reason: the PAN-OS SSH key for `10.0.212.38` is not trusted

This confirms the new failure semantics in a live environment: an optional
assertion does not hide a transport/execution failure. The assertion itself was
not evaluated because verified SSH transport was not established, and running
configuration retrieval and XML parsing did not begin.

The remaining operator steps are to verify and trust the firewall's current SSH
host key through the EVE jump path, then persist the current DHCP address in the
private workspace if another CLI validation is desired:

```yaml
LAB-PA-01:
  management_ip: 10.0.212.38
```

Because `10.0.212.38` is DHCP-derived runtime state, this remains a temporary
environment value rather than a durable static management design. After both
items are complete, the next read-only command is:

```text
eve validate UNSC-Home-Replica-01
```

No second live command was run. No engine, test, or validation documentation
change was made during this live-test turn. The previously prepared changes in
`src/eve_lab/validation.py`, `tests/test_validation_panos_runner.py`, and
`docs/validation.md` remain uncommitted for review. This README update is
committed and pushed separately under the changelog convention. The feature
branch remains unmerged.

## 2026-09-27 - Explicit enrollment of the current PAN-OS lab SSH key

The owner authorized trusting new SSH keys encountered in labs. A proposed broad
automatic trust-on-first-use policy across PAN-OS initialization, backup,
restore, and validation was rejected because it would silently accept every
previously unseen device key and enlarge the trust scope.

The safer action enrolled only the current LAB-PA-01 key for management address
10.0.212.38, reached through the already verified EVE SSH connection. No
existing key was replaced. The enrolled key is:

~~~text
ssh-rsa SHA256:dPUAWTwwFUxtcdAXXMNM3+KZHzcgZEaD7/mJc8m8K0U
~~~

The key was saved in the controller user's standard SSH trust store. EVE and
PAN-OS configuration were not changed, and validation was not rerun. Future key
mismatches remain hard failures.

structure.md now records the owner convention: a new lab-device key may be
enrolled only with explicit owner authorization, scoped to the exact device
address through an already verified EVE connection, with its fingerprint
reported. Saved keys must never be replaced automatically. docs/validation.md
applies that rule to PAN-OS validation.

The previously prepared PAN-OS validation change was completed and committed
with this convention:

- Node-level transport, session, running-config retrieval, and XML parsing
  failures force overall validation result fail, independently of optional
  assertion semantics.
- Execution failures include failure_kind: execution.
- A successfully executed optional assertion mismatch still leaves the overall
  result as pass.
- tests/test_validation_panos_runner.py covers optional and required assertion
  outcomes plus transport, retrieval, parsing, and success cases.
- Panorama validation remains unsupported.
- The only implemented PAN-OS validation transport remains the explicit
  EVE-tunneled direct-tcpip path.

Verification:

- Focused PAN-OS tests: 17 passed.
- Full test_validation*.py suite: 66 passed.
- git diff --check: passed with line-ending conversion warnings only.
- The SSH key enrollment was a live read-only transport operation.
- No live validation was run after enrollment.
- No EVE or PAN-OS configuration was changed.

The implementation, tests, and documentation were committed locally as
5f2b089 (fix: fail closed on PAN-OS validation execution errors). This README
entry is committed separately under the changelog convention. Neither commit is
pushed in this turn because pushing the README commit would also push the
preceding implementation commit, while automatic push authorization applies
only to this changelog file. The feature branch remains unmerged.

## 2026-09-27 - Live PAN-OS validation reaches execution-failure reporting

One explicitly authorized read-only live validation demo ran against
UNSC-Home-Replica-01 and LAB-PA-01. Because the private init.yaml still declares
stale address 10.0.212.131, the process used a nonpersistent override for the
console-observed DHCP address 10.0.212.38. No workspace file, EVE object, or
PAN-OS configuration was changed.

The earlier host-key refusal did not recur because the current firewall key had
been enrolled. EVE reported the node running, but its SSH direct-tcpip channel
returned No route to host for 10.0.212.38:22 throughout the bounded 120-second
retry period.

The final structured result was:

- command exit status: 1
- overall result: fail
- check: transport-xml-smoke
- assertion setting: required false
- check result: fail
- failure classification: execution
- reason: timed out waiting for PAN-OS management SSH; check management address,
  SSH service, and EVE reachability

This is live confirmation that a transport failure cannot be hidden by an
optional assertion. Running-configuration retrieval, XML parsing, and the
security-rule assertion did not execute. It does not establish whether the
DHCP address changed, PAN-OS management SSH became unavailable, or EVE lost its
route; those runtime causes require operator inspection.

No second live command was run. No tests or source changes were needed for this
demo. The branch remains unmerged. This entry is committed separately under the
Lessons Learned convention and is not pushed because the branch also contains
an unpushed implementation commit.

## 2026-09-27 - PAN-OS guest reboot explains the live SSH timeout

Console evidence supplied after the live validation shows that the PAN-OS VM was
unhealthy and rebooted during the validation window. The Linux watchdog
repeatedly reported a soft lockup on CPU 2 in PID 24033, process gdb, with the
task shown around copy_user_generic_string and copy_page_to_iter.

PAN-OS subsequently stopped services and emitted PanOS software stopped,
followed by reboot: Restarting system, SeaBIOS, GRUB, and a fresh kernel boot.
During that shutdown and restart, the EVE direct-tcpip attempts to
10.0.212.38:22 returned No route to host and eventually reached the validator's
bounded timeout.

This evidence identifies the immediate reason management SSH was unavailable:
the guest was stopping or rebooting. It does not identify the underlying cause
of the kernel soft lockup; the excerpt begins within a trace and is insufficient
to attribute that failure to validation, EVE transport, resource sizing, or a
specific PAN-OS defect.

No source change, test run, second validation, or live EVE/PAN-OS operation was
performed. The existing execution-failure result was correct and required no
validator change. This entry is committed separately under the Lessons Learned
convention and is not pushed because the branch contains an unpushed
implementation commit. The feature branch remains unmerged.

## 2026-09-27 - Diagnostic plan for recurring PAN-OS VM soft lockups

The supplied reboot console identifies a guest kernel soft lockup but not its
underlying cause. The live boot reports four virtual CPUs and approximately
8 GB RAM. PAN-OS 12.1 permits software firewalls at an 8 GB floor, but official
VM-Series model requirements and useful operating margin can be higher. The
public lab fixture currently declares 12 GB for its PAN-OS 12.1.7 firewalls, so
the live private node and public fixture are not resource-equivalent.

The principal hypotheses are:

1. A PAN-OS or VM-Series kernel/software defect.
2. EVE host CPU oversubscription preventing a guest vCPU from being scheduled
   long enough to trigger the watchdog.
3. EVE host storage latency or memory pressure stalling the QEMU guest.
4. Guest resource allocation below the requirement of its licensed VM-Series
   model or enabled features.

The gdb process shown in the trace may be collecting or inspecting crash state;
the excerpt does not prove that gdb caused the original stall. The failed
validator never established management SSH, authenticated, retrieved the
configuration, or issued a PAN-OS command, so its validation queries did not
trigger this reboot.

Evidence to preserve after the next occurrence:

- Exact PAN-OS build, licensed VM-Series model, serial, uptime, and last restart.
- PAN-OS show system files output and all new management/data-plane core or
  crash files.
- A tech-support file generated before another reboot overwrites useful state.
- show system info, show system resources, show system software status, and
  show system disk-space files.
- System logs spanning at least ten minutes before and after the watchdog event.
- EVE host CPU load, per-QEMU process CPU, memory/swap pressure, disk latency,
  kernel logs, and the exact QEMU command/resource allocation over the same
  timestamps.
- Which other lab nodes were running and their total vCPU/RAM allocation.

A controlled comparison should first reproduce with only the affected firewall
running. Then repeat at a supported higher memory allocation, such as 12 or
16 GB as appropriate for the licensed model, without changing the workload.
If the problem disappears only when competing nodes are stopped, host
oversubscription is the leading explanation. If it persists in isolation with
adequate resources, preserve the cores and tech-support bundle and open a Palo
Alto Networks support case. Comparing the exact base release with a supported
current maintenance release is a separate controlled test.

Official release notes show PAN-318275 addressed in PAN-OS 12.1.7 for a
VM-Series firewall becoming unresponsive, and 12.1.7-h3 addresses a memory leak
associated with some display CLI commands. Those notes justify checking the
exact maintenance build but do not prove either issue matches this stack trace.

No source change, test, or live operation was performed. This diagnostic entry
is committed separately under the Lessons Learned convention and is not pushed
because the branch contains an unpushed implementation commit. The feature
branch remains unmerged.
