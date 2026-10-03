# NDFC tenant host access ports

The tenant workflow configures untagged endpoints as NDFC-managed access ports. Set
`tenants.host_port_mode: access` in the lab intent. Each endpoint must name its
ToR attachment, have one direct Ethernet link in `topology.yaml`, and have an
address in exactly one declared tenant Network. The Network VLAN becomes that
host port's access VLAN.

Run the normal tenant commands from the lab workspace with the public engine on
`PYTHONPATH` and the dedicated NDFC credentials in `EVE_ENV_FILE`:

```text
python -m eve_lab.ndfc_tenant_api <lab>/intent.yaml --attach
python -m eve_lab.ndfc_tenant_api <lab>/intent.yaml --deploy
```

`--attach` verifies VRF and Network objects and their exact leaf/ToR attachments,
then creates or reconciles `int_access_host` on only the endpoint-derived ToR
interfaces. It accepts an existing `int_trunk_host` only when its allowed and
native VLANs are empty/default or match the declared Network VLAN. A different
access VLAN, a different interface policy, or a trunk carrying other VLANs stops
reconciliation. ToR uplinks and unused ports are outside the endpoint map.

`--deploy` requires exact `int_access_host` readback before deploying tenant
resources. It checks forced config previews for access mode and VLAN, deploys
only pending endpoint interfaces through NDFC's interface-scoped API, and waits
for both preview convergence and successful per-user deployer history. Repeated
runs leave already matching policies and interfaces untouched.
