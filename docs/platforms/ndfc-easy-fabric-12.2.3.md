# NDFC 12.2.3 Easy Fabric creation

This note records the installed NDFC 12.2.3 behavior for a Data Center
VXLAN EVPN fabric using the `Easy_Fabric` template. Cisco's
[12.2.2/12.2.3 Data Center VXLAN EVPN guide](https://www.cisco.com/c/en/us/td/docs/dcn/ndfc/1222/articles/ndfc-data-center-vxlan-evpn/data-center-vxlan-evpn.html)
defines the GUI sequence: **Manage > Fabrics > Actions > Create Fabric**,
enter a unique name, choose **Data Center VXLAN EVPN**, review the
General Parameters, Replication, Resources, vPC, and other tabs, then
Save. The GUI template populates defaults; the operator supplies values
that differ from the intended fabric design.

## Installed API mapping

The installed `GET /appcenter/cisco/ndfc/api/v1/lan-fabric/v3/api-docs`
lists `createFabricWithNvPairs` as:

```text
POST /appcenter/cisco/ndfc/api/v1/lan-fabric/rest/control/fabrics/{fabricName}/{templateName}
Content-Type: application/json

{"FABRIC_NAME":"<name>","BGP_AS":"<asn>"}
```

Use `Easy_Fabric` for `templateName`. The request body is a JSON
name/value map. The optional `ticketId` query parameter is for change
control. Read the installed
`GET /appcenter/cisco/ndfc/api/v1/configtemplate/rest/config/templates/Easy_Fabric`
before creating and require every declared NV key to exist in that
template. Read back via
`GET /appcenter/cisco/ndfc/api/v1/lan-fabric/rest/control/fabrics`;
match exactly one fabric name and `Easy_Fabric` template, then compare
all explicitly declared NV pairs. A second identical reconciliation
must return an already-configured result and create no duplicate.

## GUI defaults and readback

The installed template metadata reported these defaults during the
victory-fabric field test:

| GUI field / NV key | Installed default |
| --- | --- |
| Replication Mode / `REPLICATION_MODE` | `Multicast` |
| Network VLAN Range / `NETWORK_VLAN_RANGE` | `2300-2999` |
| VRF VLAN Range / `VRF_VLAN_RANGE` | `2000-2299` |

A design that uses ingress replication or different, separate Network
and VRF VLAN resource ranges must send those values explicitly. The
public compiler includes `VRF_VLAN_RANGE` when the selected fabric
declares `vrf_vlan_range`; an older fabric that relies on its already
accepted default retains its existing payload.

The successful 12.2.3 field test sent 18 declared pairs. GET returned
323 pairs: all 18 declared values matched. Among template fields with
nonempty defaults that were not explicitly sent, 162 matched readback
and 55 conditional fields were empty; none had a populated value that
conflicted with its template default. An empty conditional field is not
evidence of a different active setting. Compare the explicitly declared
fields and relevant populated defaults, not the entire template metadata
to the readback object.

The reusable `ndfc_fabric` path checks template availability,
rejects missing declared fields and conflicting existing values,
requires HTTP success, and verifies the readback. The first field-test
run returned `created`; the identical second run returned
`already-configured` with one matching fabric.
