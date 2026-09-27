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

## 2026-09-27 - Agent initiative is broad for repository work and narrow for live infrastructure

The root agent guidance was expanded after review of external initiative and
follow-through guidance. The useful behavior was adopted, but it was narrowed
for an infrastructure-automation repository where live actions can have
side effects beyond the Git working tree.

`AGENTS.md` now tells agents to resolve retrievable prerequisites before asking
the owner, carry already-authorized reversible repository work through
implementation and offline verification, avoid unnecessary permission
checkpoints, preserve active-task context across follow-up turns, and identify
the exact blocker when a deliverable cannot be completed.

The same convention is mirrored in `structure.md` so repository policy and the
root agent entry point remain consistent. The live-action boundary is explicit:
repository-local reversible authorization may persist for the active task, but
starting, stopping, configuring, deleting, resetting, or otherwise changing
EVE-NG nodes or network devices requires authorization applicable to that
specific live action and scope. When live authorization is absent, agents should
continue useful offline preparation rather than stopping prematurely.

This was a documentation-only change. No engine behavior, tests, lab
definitions, EVE-NG state, or network-device state were changed. No test suite
was required. The changes are on branch `docs/agent-initiative-guidance` and
opened for review in PR #7; the branch has not been merged.

