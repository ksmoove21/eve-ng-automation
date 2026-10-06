# Native EVE Pro fixed link delays

`eve_lab.link_quality.reconcile_fixed_delays` plans or applies fixed symmetric
per-side delays to semantic direct Ethernet cables. Planning is read-only;
`apply=True` persists through the native quality endpoint. `enabled=False`
removes the selected delays while retaining profile assignments.

The native endpoint and payload were observed in the installed EVE Pro
7.2.0-4 frontend: `PUT /api/labs/{lab}.unl/quality`, with source/destination
node IDs, interface IDs, labels, per-side delay/jitter/loss/bandwidth and
`save=1`. This is observed installed behavior, not a published REST contract.
The [EVE Pro cookbook, section 9.1.6](https://www.eve-ng.net/wp-content/uploads/2021/06/EVE-COOK-BOOK-4.12-2021.pdf)
documents native per-side delay controls and live impairment changes.

Field qualification on EVE Pro 7.2.0-4: a running IOSv PE–CE cable with 10 ms
on both endpoints had 20/20 successful pings before and after; average RTT
changed from 1 ms to 22 ms. Thus the tested profile means milliseconds per
direction, adding approximately twice the assigned delay to RTT. Saved values
were also accepted/read back on cables with stopped endpoints. Their runtime
activation after boot remains a separate field check.

The helper validates every requested semantic binding before writing, preserves
jitter/loss/bandwidth, rechecks concurrent changes, verifies exact native
readback including styling and attachment preservation, and repeats with zero
changes. It never uses host `tc`, modifies bridges, or starts/stops nodes.
