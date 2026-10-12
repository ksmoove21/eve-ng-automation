# Catalyst Center 2.3.7 API contract

This generic adapter contract is pinned to the 2.3.7.10 release line. It records
public operations confirmed in Cisco's 2.3.7 API reference and the current
controller's read surface. It is not a topology definition and never supplies
controller-specific values.

## Reconciliation rules

Read first and preserve controller IDs returned by the matching read. Create
only when the intended object is absent. An update is allowed only where the
exact operation schema documents mutable fields. Never turn an update failure
into delete-and-recreate.

Every mutation requires operation-specific readback after its documented
completion signal. A `taskId` is only a task when that operation returns
`response.taskId`; never treat a resource `id` as a task. Site APIs can instead
return `executionId` and `executionStatusUrl`; an adapter must support that
shape before it mutates sites.

## Command Runner file results

Cisco's Command Runner submits its read-only command request asynchronously. After
the task identifies its file, `GET /dna/intent/api/v1/file/{fileId}` can return
a top-level JSON array of command-response objects. Use the generic
`read_array()` only for this documented array-shaped endpoint; `read()` remains
object-only so an unexpected response shape fails closed.
## Hierarchy and pools

| Resource | Read | Create | Update | Adapter boundary |
| --- | --- | --- | --- | --- |
| Site hierarchy | `GET /dna/intent/api/v1/site` | `POST /dna/intent/api/v1/site` | `PUT /dna/intent/api/v1/site/{siteId}` | Create supplies `type` and its matching area/building/floor structure. Do not invent building coordinates or parent hierarchy. |
| Global IPv4 pool | `GET /dna/intent/api/v1/ipam/globalIpAddressPools` | `POST /dna/intent/api/v1/ipam/globalIpAddressPools` | No generic update contract | GET uses one-based `offset` and `limit` (maximum 500). Create requires only `name`, `poolType`, and `addressSpace.subnet`/`prefixLength`; the create-only adapter omits optional gateway, DNS, and DHCP fields, preserves returned IDs and observed optional metadata, and rejects overlap or immutable identity conflicts. |
| Reserved site IPv4 subpool | `GET /dna/intent/api/v1/ipam/siteIpAddressPools` | `POST /dna/intent/api/v1/ipam/siteIpAddressPools` | No generic update contract | Create requires `ipV4AddressSpace`, `name`, `poolType`, and `siteId`; IPv4 space requires `subnet`, `prefixLength`, and `globalPoolId`. Reconcile is create-only and preserves the returned ID. |

### Delete constraints (observed 2.3.7.10)

Catalyst Center 2.3.7.10 accepted `DELETE
/dna/intent/api/v1/ipam/siteIpAddressPools/{id}` for an unused site subpool
with zero assigned addresses. It returned an asynchronous task and readback
confirmed absence while unrelated records retained their IDs and objects.

It also accepted `DELETE /dna/intent/api/v1/ipam/globalIpAddressPools/{id}`
for an unused global pool only after its subpool-reference count was verified
as zero. The documented global-pool delete response supplies `response.taskId`
and `response.url`; deleting a global pool with subpools is unsupported. The
field readback retained unrelated global-pool identity and optional metadata;
allocation counters are expected to change independently of identity.

The generic IPAM adapters remain deliberately create-only. A future delete
adapter must perform those precondition checks, await the task, and verify the
target absence plus unrelated-object preservation before reporting success.
## Fabric and virtual networks

| Resource | Read | Create | Update | Adapter boundary |
| --- | --- | --- | --- | --- |
| Fabric/site/device inventory | `GET /dna/intent/api/v1/sda/fabricSites`; `GET /dna/intent/api/v1/sda/fabricDevices` | Fabric creation/association is adapter-specific | No generic update contract | Read fabric-site and device IDs before role, VN, or handoff operations. |
| Layer 3 VN | `GET /dna/intent/api/v1/sda/layer3VirtualNetworks` | `POST /dna/intent/api/v1/sda/layer3VirtualNetworks` | `PUT /dna/intent/api/v1/sda/layer3VirtualNetworks` | Cisco documents array payloads. A greenfield create requires only `virtualNetworkName`; it may additionally declare `fabricIds` and `anchoredSiteId`. Preserve the returned record ID. |
| Layer 2 VN | `GET /dna/intent/api/v1/sda/layer2VirtualNetworks` | No generic create contract here | No generic update contract here | Readback includes fabric, VLAN, traffic type, and its associated Layer-3 VN name where present. |
| VN anycast gateway | `GET /dna/intent/api/v1/sda/anycastGateways` | No generic contract here | No generic contract here | Use readback for verification only until a version-specific mutation schema is accepted. |

`anchoredSiteId` is a documented Layer-3 VN field for a greenfield POST. Do not
use its PUT operation to convert an ordinary existing VN into an anchored VN:
that conversion remains unsupported by the relevant Cisco validated design. A
reconciler may create a new intended anchored VN, but must fail closed if an
existing same-name ordinary VN differs from that design.

The older `business/sda/virtual-network` and `business/sda/virtualnetwork/ippool`
operations remain versioned public APIs. Do not mix those resource identities
with the modern Layer-3 VN record without controller readback.

## Transit and handoffs

| Resource | Read | Create | Update | Adapter boundary |
| --- | --- | --- | --- | --- |
| Transit network | `GET /dna/intent/api/v1/sda/transitNetworks` | `POST /dna/intent/api/v1/sda/transitNetworks` | `PUT /dna/intent/api/v1/sda/transitNetworks` | List filters include `id`, `name`, `type`, `offset`, and `limit` (maximum 500). Cisco documents transit `id`, `name`, `type`, routing protocol, and ASN as non-updatable. |
| Layer 2 handoff | `GET /dna/intent/api/v1/sda/fabricDevices/layer2Handoffs` | `POST /dna/intent/api/v1/sda/fabricDevices/layer2Handoffs` | No generic update contract | Create identity: `networkDeviceId`, `fabricId`, `interfaceName`, `internalVlanId`, `externalVlanId`. |
| Layer 3 IP-transit handoff | `GET /dna/intent/api/v1/sda/fabricDevices/layer3Handoffs/ipTransits` | `POST /dna/intent/api/v1/sda/fabricDevices/layer3Handoffs/ipTransits` | `PUT /dna/intent/api/v1/sda/fabricDevices/layer3Handoffs/ipTransits` | Create identity: `networkDeviceId`, `fabricId`, `transitNetworkId`, `interfaceName`, `virtualNetworkName`, `vlanId`. |

Layer-3 handoff reads require `fabricId`, accept optional `networkDeviceId`, and
use `offset`/`limit`. The documented update schema identifies device, fabric,
transit, interface, external-connectivity pool, VN, and VLAN as immutable. Fail
closed on a change to any of those fields.

Layer-2 and Layer-3 creates return the documented asynchronous
`response.taskId` and `response.url` shape. Track that task, then read back the
specific handoff before reporting convergence. Mutation payloads may be one
object or a documented batch of objects; generic transport supports both but
resource adapters own field validation.

## TLS compatibility

The generic client uses Python's strict default context unless an environment
provides an explicit `ssl.SSLContext`. An injected context must retain
`CERT_REQUIRED` and hostname checking. This permits a caller with a known CA to
remove only `VERIFY_X509_STRICT` for a documented legacy certificate-chain
compatibility case; it does not permit unverified TLS or hostname bypass.

Python 3.13 adds `VERIFY_X509_STRICT` and `VERIFY_X509_PARTIAL_CHAIN` to the
default context flags. Python documents that strict validation can reject
pre-RFC 5280 or malformed certificates, and shows clearing only the strict flag
for a compatibility exception.

## Sources

- [Catalyst Center 2.3.7.10 API changelog](https://developer.cisco.com/docs/catalyst-center/api-changelog/)
- [Create Site](https://developer.cisco.com/docs/catalyst-center/2-3-7-7/create-site/)
- [Create a global IP address pool](https://developer.cisco.com/docs/catalyst-center/2-3-7-10/create-a-global-ip-address-pool/)
- [Delete a global IP address pool](https://developer.cisco.com/docs/catalyst-center/2-3-7-9/delete-a-global-ip-address-pool/)
- [Reserve IP address subpools](https://developer.cisco.com/docs/catalyst-center/reserve-create-ip-address-subpools/)
- [Command Runner](https://developer.cisco.com/docs/catalyst-center/command-runner/)
- [Download a file by fileId](https://developer.cisco.com/docs/catalyst-center/2-3-7-6/download-a-file-by-fileid/)
- [Add Layer 3 virtual networks](https://developer.cisco.com/docs/catalyst-center/2-3-7-6/add-layer-3-virtual-networks/)
- [Get Layer 3 virtual networks](https://developer.cisco.com/docs/catalyst-center/2-3-7-6/get-layer-3-virtual-networks/)
- [Get Layer 2 virtual networks](https://developer.cisco.com/docs/catalyst-center/2-3-7-6/get-layer-2-virtual-networks/)
- [Add transit networks](https://developer.cisco.com/docs/catalyst-center/2-3-7-6/add-transit-networks/)
- [Get transit networks](https://developer.cisco.com/docs/catalyst-center/2-3-7-6/get-transit-networks/)
- [Add Layer 2 handoffs](https://developer.cisco.com/docs/catalyst-center/2-3-7-5/add-fabric-devices-layer-2-handoffs/)
- [Add Layer 3 IP-transit handoffs](https://developer.cisco.com/docs/catalyst-center/2-3-7-5/add-fabric-devices-layer-3-handoffs-with-ip-transit/)
- [Get Layer 3 IP-transit handoffs](https://developer.cisco.com/docs/catalyst-center/2-3-7-6/get-fabric-devices-layer-3-handoffs-with-ip-transit/)
- [Python 3.13 SSL documentation](https://docs.python.org/3.13/library/ssl.html)


### Layer-3 VN membership ordering

**OBSERVED on Catalyst Center 2.3.7.10:** Layer-3 VN `fabricIds` ordering can
change between reads without a membership change. Reconciliation compares this
field as an unordered unique membership set, retains the controller's existing
order when constructing an additive request, and still rejects a readback that
adds or removes any member. Controller record IDs and anchors remain exact
identity fields.

## Layer-2 virtual network creation

The create-only adapter uses Cisco's 2.3.7.9 batch `POST
/dna/intent/api/v1/sda/layer2VirtualNetworks` contract. It sends only requested
`fabricId`, `vlanName`, `trafficType`, optional `vlanId`, and optional associated
Layer-3 VN name. It verifies that an associated Layer-3 VN already exists.
Existing Layer-2 records are immutable association identities for this adapter:
conflicts fail closed; it never PUTs, deletes, or rebuilds one.

- [Add Layer-2 virtual networks](https://developer.cisco.com/docs/catalyst-center/2-3-7-9/add-layer-2-virtual-networks/)
- [Layer-2 VN update request fields](https://developer.cisco.com/docs/catalyst-center/2-3-7-9/updatelayer2virtualnetworksrequest/)
