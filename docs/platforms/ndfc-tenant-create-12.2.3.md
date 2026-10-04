# NDFC 12.2.3 VRF and Network creation

The Fabric Overview **VRFs** and **Networks** pages create controller objects
before attaching them to switches. The reusable implementation is
`eve_lab.ndfc_tenant_api` with `--site DC1` or `--site DC2` and no `--attach` or
`--deploy` option. It compiles the selected site's objects from declared intent,
checks the exact switch inventory and installed templates, creates missing
objects, and verifies each object by a fresh readback. A second run returns
`already-configured` for matching objects.

| GUI action | Installed 12.2.3 API | Engine action |
| --- | --- | --- |
| Fabric Overview > VRFs > create | `POST /appcenter/cisco/ndfc/api/v1/lan-fabric/rest/top-down/fabrics/{fabric}/vrfs` | `vrf_create_payload` and `stage_tenants` |
| Fabric Overview > Networks > create | `POST /appcenter/cisco/ndfc/api/v1/lan-fabric/rest/top-down/fabrics/{fabric}/networks` | `network_create_payload` and `stage_tenants` |
| Read the resulting list | `GET` on each corresponding collection | Verify exact name, VNI, VLAN, VRF, gateway, and template |
| Check installed form fields | `GET /appcenter/cisco/ndfc/api/v1/configtemplate/rest/config/templates/{template}` | Validate `Default_VRF_Universal` and `Default_Network_Universal` parameters before writing |

The VRF payload carries its VNI and VRF VLAN. The Network payload carries its
L2 VNI, VLAN, VRF, and gateway. Static Networks leave all DHCP relay template
fields unset. Endpoint IP addresses are configured separately from their
declared static intent. Cisco's [NDFC VXLAN EVPN guide](https://www.cisco.com/c/en/us/td/docs/dcn/ndfc/1222/articles/ndfc-data-center-vxlan-evpn/data-center-vxlan-evpn.html)
shows that DHCP relay is an optional Network advanced action and that a newly
created Network has status `NA` until attachment and deployment.

Controller-only staging permits `ccStatus=NA` for an imported switch with the
correct identity and role. Attachment and deployment have stricter switch
readiness checks. An HTTP 200 from a create request is insufficient: the engine
requires exact collection readback. This action does not push switch
configuration. Use `--attach` for selected leaf attachments and host access
ports, then `--deploy` for their separate deployment after fabric switch
convergence. The host access policy is documented in
[tenant host access ports](ndfc-tenant-host-access.md).
