# Select an NDFC fabric site

The NDFC fabric, switch preflight, and tenant commands use DC1 by default. Pass
`--site DC2` to select the second declared fabric explicitly:

```text
python -m eve_lab.ndfc_fabric <lab>/intent.yaml --site DC2 --check
python -m eve_lab.ndfc_switches <lab>/intent.yaml --site DC2 --check
python -m eve_lab.ndfc_tenant_api <lab>/intent.yaml --site DC2 --check
```

After reviewing those offline results, use the same site option with the
applicable live commands: `ndfc_fabric` to reconcile the fabric,
`ndfc_tenant_api --attach` to stage attachments and host access policies, and
`ndfc_tenant_api --deploy` to deploy the selected site's tenant resources.
The tenant command reads `topology.yaml` beside the intent for attachment and
deployment. Each site is matched by its exact fabric name and switch inventory;
another site's switches cannot satisfy its inventory preflight.

The selected fabric must declare its switch import policy, Network VLAN range,
management vPC keepalive option, and leaf pre-interface configuration. DC2 also
requires an explicit `spine_pair.nodes` and `scope.r7_activation_set`. An
optional `vrf_vlan_range` maps to NDFC `VRF_VLAN_RANGE`; when present, it must
be separate from the Network VLAN range and contain every selected VRF VLAN.
Omitting this field preserves the DC1 Easy_Fabric payload used by existing
installations.

Tenant attachment requires exact direct endpoint links to the selected ToR
pair. Host access VLANs come from the selected tenant Networks, as described in
[tenant host access ports](ndfc-tenant-host-access.md).

The installed 12.2.3 `Default_Network_Universal` template exposes DHCP relay
fields but no proven per-Network leaf DHCP server scope. A Network can retain
`dhcp: fabric_leaf` for future intent when it also declares
`dhcp_deployment: deferred`. Tenant staging, attachment, and deployment then
report that Network's `dhcp_status` as `deferred` and do not claim lease service.
Without the explicit marker, those commands stop before any API mutation.
`dhcp: deferred_out_of_scope` remains supported.
