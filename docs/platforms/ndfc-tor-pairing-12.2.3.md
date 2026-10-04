# NDFC 12.2.3 ToR pairing API notes

These notes apply to the installed NDFC 12.2.3 LAN UI. Cisco's [12.2.2/12.2.3 ToR guide](https://www.cisco.com/c/en/us/td/docs/dcn/ndfc/1222/articles/ndfc-configure-tor-switches/configuring-tor-switches-and-deploying-networks.html) describes the operator workflow: pair both vPC peers, enable the ToR pair from the leaf pair's **ToR Pairing** view, then recalculate and deploy.

## Installed UI request shape

Read-only analysis of the installed UI bundle at `https://<ndfc-host>/appcenter/cisco/ndfc/ui/apps/lan-common/embedded-ui.js?cachebust=1752313927285` found the `saveTorPairing` route:

```text
POST /appcenter/cisco/ndfc/api/v1/lan-fabric/rest/control/tor/fabrics/{fabricName}/switches/pair/custom-id
```

For a leaf vPC pair connected to a ToR vPC pair, the form builds this body. `poVpc` is a JSON-encoded **string**, not a nested JSON object:

```json
{
  "leafSN1": "LEAF1_SERIAL",
  "leafSN2": "LEAF2_SERIAL",
  "torSN1": "TOR1_SERIAL",
  "torSN2": "TOR2_SERIAL",
  "poVpc": "{\"LEAF1_SERIAL_PO\":\"1\",\"LEAF2_SERIAL_PO\":\"1\",\"TOR1_SERIAL_PO\":\"1\",\"TOR2_SERIAL_PO\":\"1\",\"LEAF1_SERIAL~LEAF2_SERIAL_VPC\":\"1\",\"TOR1_SERIAL~TOR2_SERIAL_VPC\":\"1\"}"
}
```

The six ID values are taken from the form's Advanced fields. In the disposable DC1 run, the UI's proposed-ID read returned `1` for all six fields, and the resulting policy used Po1/vPC1. The UI passes an optional change-control `ticketId` as a query parameter. The installed bundle supplies the URL and body builder; POST is the UI callback's default method and matches Cisco's published ToR pairing API method. This was **source analysis**, not a capture of the owner's Save request. The installed 12.2.3 `/lan-fabric/v3/api-docs` omitted ToR operations, so do not infer this exact route from a later release's OpenAPI alone.

## Readback and deployment

The installed UI uses these read-only requests to populate the leaf-pair view and six proposed IDs:

```text
GET /appcenter/cisco/ndfc/api/v1/lan-fabric/rest/control/tor/fabrics/{fabricName}/switches/{leafSerial}?peerSwitchSN={peerLeafSerial}
GET /appcenter/cisco/ndfc/api/v1/lan-fabric/rest/control/tor/fabrics/{fabricName}/switches/pair/?switchSN={leafSerial}&peerSwitchSN={peerLeafSerial}&torSN={torSerial}&torPeerSwitchSN={peerTorSerial}
GET /appcenter/cisco/ndfc/api/v1/lan-fabric/rest/control/tor/fabrics/{fabricName}/switches/tor/{torSerial}
```

After Save, verify the exact `torPairs[].leafSNs` and ToR parent leaf serials; the tested readback reported `Already paired with (...)` and populated `leafSNs` while its `enable` field remained `false`. Verify generated parent Po and child member policies against the physical link map before deployment.

The installed fabric recalculate endpoint is `POST /appcenter/cisco/ndfc/api/v1/lan-fabric/rest/control/fabrics/{fabricName}/config-save`. For a scoped follow-on deployment, use `POST /appcenter/cisco/ndfc/api/v1/lan-fabric/rest/control/fabrics/{fabricName}/config-deploy/{serialNumber}` on only the affected switches. `GET .../config-preview/{serialNumber}?forceShowRun=true`, per-switch deployer history, and live Po/vPC state establish convergence; HTTP 200 alone does not.

## Reusable command

Run `python -m eve_lab.ndfc_tor_pairing <intent.yaml> --site DC2 --check`
to validate the selected leaf/ToR pair and four declared direct links without
NDFC access. Omit `--check` to save the association. The command reads
`topology.yaml` beside the intent file by default; `--topology` selects a
different topology path. It verifies the four imported switch identities and
roles, existing leaf and ToR vPC pairs, and the installed six-ID proposal
before POST. It treats `leafSNs: null` as unpaired even if the GUI row reports
`enable: true`; saved association requires exact composite leaf and ToR parent
serial readback. Recalculate, scoped deploy, and operational Po/vPC checks
remain separate.
