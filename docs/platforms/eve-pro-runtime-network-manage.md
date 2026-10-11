# EVE Pro direct-link runtime materialization

EVE Pro can persist a lab node's interface assignment without materializing the
running bridge and its endpoint stitches. The node may report carrier while
traffic does not cross the link. The GUI's Network > Manage Save action uses:

```text
PUT /api/labs/{lab}.unl/network/manage
```

The installed EVE Pro 7.2.0-4 GUI sends the existing network ID, bridge options,
and its complete port map. `eve_lab.network_manage` builds that request from
`GET .../networks/{id}` only after the two endpoint identities match one exact
Git direct link. Git link names and EVE display names can differ; select both
the Git link and the observed EVE network ID. The default command is read-only:

```text
python -m eve_lab.network_manage <lab>/topology.yaml --root <workspace> --link <git-link-name> --id <eve-network-id>
```

After explicit authorization for the disposable lab action, add `--apply` for
that single link. The command re-reads the saved network and rejects any
endpoint or option drift. The API response proves only that EVE accepted the
request. Verify the running `vnet` bridge, each endpoint `bun`/`pun`, the `bun`
master, guest `vun` carrier, and an unaffected control link separately before
proceeding to another network. Do not replace this scoped API call with raw
host `ip link`, broad node restarts, or the undocumented netsetup stdin tool.

## Native wipe and placement observation

On EVE Pro 7.2.0-4, a native node wipe can preserve the node object and its image/resource/interface identity while resetting a stopped node's observed satellite placement to the manager/default value. This is an **OBSERVED** version-specific behavior, not a universal API contract; the native API documentation describes wipe but does not document the placement reset. After wiping a stopped node, explicitly restore the intended host/satellite placement and verify the stopped-node pin before starting it.

Reference: [EVE-NG API documentation](https://www.eve-ng.net/index.php/how-to-eve-ng-api/).
