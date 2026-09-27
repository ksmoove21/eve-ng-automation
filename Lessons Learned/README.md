# Lessons Learned

This changelog records concrete lessons from implementation, testing, and live
EVE-NG evidence. Entries distinguish offline verification from behavior proven
on live devices.

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
