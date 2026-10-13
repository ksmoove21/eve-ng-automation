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
| Layer 2 handoff | `GET /dna/intent/api/v1/sda/fabricDevices/layer2Handoffs` | `POST /dna/intent/api/v1/sda/fabricDevices/layer2Handoffs` | No generic update contract | The create-only adapter uses only `networkDeviceId`, `fabricId`, `interfaceName`, `internalVlanId`, and `externalVlanId` in Cisco's documented POST array shape. Its endpoint is fabric/device/interface/internal-VLAN; the external VLAN is immutable. |
| Layer 3 IP-transit handoff | `GET /dna/intent/api/v1/sda/fabricDevices/layer3Handoffs/ipTransits` | `POST /dna/intent/api/v1/sda/fabricDevices/layer3Handoffs/ipTransits` | No generic update contract | The create-only adapter requires `networkDeviceId`, `fabricId`, `transitNetworkId`, `interfaceName`, `virtualNetworkName`, `vlanId`, and `externalConnectivityIpPoolName`. It never supplies local or remote IPs. |

Layer-2 handoff reads require `fabricId`. The adapter preserves controller IDs,
checks both VLANs against the documented non-reserved range, waits for the
asynchronous create task, and verifies exact readback. It neither models
physical-port coexistence nor PUTs, deletes, or rebuilds a handoff.

### Layer-2 handoff provisioning and repair (observed 2.3.7.10)

Catalyst Center 2.3.7.10 accepted a documented Layer-2 handoff POST on an
interface already used by an IP-transit Layer-3 handoff. The asynchronous task
succeeded, filtered GET readback converged, and existing handoff IDs remained
unchanged. This proves controller provisioning acceptance only; data-plane
forwarding requires separate endpoint proof.

A targeted lifecycle repair also succeeded through exact-ID `DELETE
/dna/intent/api/v1/sda/fabricDevices/layer2Handoffs/{id}` and `DELETE
/dna/intent/api/v1/sda/layer2VirtualNetworks/{id}` operations for the defective
targets only. Their tasks completed and subsequent associated-VN creation plus
Layer-2 handoff recreation converged to no-op; unrelated VN and handoff objects
and IDs stayed unchanged.

Those delete operations are explicit, owner-directed lifecycle actions. The
generic Layer-2 VN and handoff adapters remain create-only and never
automatically delete, repair, or rebuild a controller object.
The GET response supplies controller-assigned `localIpAddress` and
`remoteIpAddress` records. After a create task completes, the adapter requires
distinct IPv4 host interfaces in the same `/30` or `/31`, keeps the controller
resource ID, and compares every requested identity field exactly. A changed
endpoint, transit, virtual network, VLAN, or external-connectivity pool fails
closed; it never PUTs, deletes, or rebuilds a handoff.
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

## RMA device replacement and software images

**Documented, 2.3.7:** Mark the faulty device before selecting the replacement.
`POST /dna/intent/api/v1/device-replacement` accepts an array containing the
faulty device ID and `replacementStatus: MARKED_FOR_REPLACEMENT`; verify the
replacement record before invoking the workflow with both serial numbers.
The faulty device must be unreachable and the replacement must match the
model/platform and be outside provisioning. Preserve the existing fabric,
site, transit, VN, pool and handoff objects throughout recovery.

Cisco requires the faulty device's software image in Image Repository before
marking. Its conditional software-upgrade skip for matching software version
and mode applies during replacement; it does not waive that marking prerequisite.
**Observed on 2.3.7.10:** missing image metadata caused marking to return
`NCRM11042` without creating a replacement record.

The documented URL and local-file import APIs accept QCOW2 among their image
formats. Local upload uses `POST /dna/intent/api/v1/image/importation/source/file`
with multipart field `file`; Cisco's 2.3.7.6 SDK supplies the filename, stream,
multipart content type and content length. This avoids requiring an external
HTTP/FTP source. Submit only the unmodified source artifact and use native task,
family/product, version and integrity readback to qualify it. Accepted file extensions do not
prove C9000v applicability or RMA eligibility. A URL connection failure occurs
before parsing and provides no compatibility result.

**Observed on 2.3.7.10:** a native local-file import of an unmodified virtual
base QCOW2 completed successfully after approximately 23 minutes, but the
repository classified it as family `UNKNOWN`, version `-1`, without product
applicability. This is import completion, not image qualification; it does not
satisfy an RMA prerequisite for an exact CAT9K build. A client polling timeout
while the native task remains active must not be reported as import failure.
Do not repack an image,
force invented metadata or substitute a runtime overlay for distributable software.
C9000v Border/Control Plane restoration and preservation of all handoffs remain
**field-test required**; successful task submission is insufficient.

Sources: [Cisco RMA API guide](https://developer.cisco.com/docs/catalyst-center/2-3-7-6/rma-device-replacement/),
[Cisco Base Automation troubleshooting guide](https://www.cisco.com/c/en/us/td/docs/cloud-systems-management/network-automation-and-management/dna-center/tech_notes/b_cisco_dna_center_base_automation_services_troubleshooting_guide.html),
[SWIM URL import schema](https://developer.cisco.com/docs/catalyst-center/2-3-7-4/import-software-image-via-url/),
[SWIM local-file import schema](https://developer.cisco.com/docs/catalyst-center/2-3-7-4/import-local-software-image/),
[Cisco SDK 2.3.7.6 SWIM source](https://github.com/cisco-en-programmability/dnacentersdk/blob/master/dnacentersdk/api/v2_3_7_6/software_image_management_swim.py).

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
- [Delete fabric device Layer-2 handoff by ID](https://developer.cisco.com/docs/catalyst-center/2-3-7-5/delete-fabric-device-layer-2-handoff-by-id/)
- [Delete Layer-2 virtual network by ID](https://developer.cisco.com/docs/catalyst-center/2-3-7-6/delete-layer-2-virtual-network-by-id/)
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
