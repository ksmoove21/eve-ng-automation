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
python -m eve_lab.network_manage <lab>/topology.yaml --root <workspace> --link DC1-BL1-PA1 --id 23
```

After explicit authorization for the disposable lab action, add `--apply` for
that single link. The command re-reads the saved network and rejects any
endpoint or option drift. The API response proves only that EVE accepted the
request. Verify the running `vnet` bridge, each endpoint `bun`/`pun`, the `bun`
master, guest `vun` carrier, and an unaffected control link separately before
proceeding to another network. Do not replace this scoped API call with raw
host `ip link`, broad node restarts, or the undocumented netsetup stdin tool.
