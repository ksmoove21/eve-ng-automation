# NDFC 12.2.3 switch import boundary

Cisco's [12.2.2/12.2.3 LAN switch guide](https://www.cisco.com/c/en/us/td/docs/dcn/ndfc/1222/articles/ndfc-add-switches-lan/add-switches-for-lan-operational-mode.html)
describes **Manage > Inventory > Switches > Actions > Add Switches**. Choose
the fabric, discover the management addresses, inspect identity and
manageability, add the selected devices, then assign roles. Form the intended
vPC/ToR pairs before recalculation and deployment so generated settings reach
the switches.

The reusable `ndfc_switches` command performs only the discovery preflight.
It sends `POST /lan-fabric/rest/control/fabrics/{fabricName}/inventory/test-reachability`
with the declared seed IPs and `preserveConfig: false`, then checks returned IP,
hostname, serial, and manageability flags. That response is not evidence of
import, role assignment, or device configuration.

The separate `ndfc_import` and `ndfc_roles` commands carry out the next two
steps. The installed 12.2.3 OpenAPI identifies
`POST /lan-fabric/rest/control/fabrics/{fabricName}/inventory/discover`
(`discoverSwitches`) with required `seedIP`, `username`, `password`, and
`switches` fields, plus optional `preserveConfig`. It identifies
`POST /lan-fabric/rest/control/switches/roles` (`setSwitchesRole`) with an
array of `{serialNumber, role}` entries. The import command requires an empty
selected-fabric inventory, validates each candidate's identity and
manageability, sends the exact eight selected switches with Preserve Config
false, and verifies fabric inventory readback. An already populated fabric is
accepted only when all eight declared names and management IPs match and each
has a serial number. The role command requires that same exact inventory and
changes only differing declared roles, then waits for role readback.

The site defaults to DC1; use `--site DC2` for the declared second fabric.
The installed request schemas validate the API shape. Device configuration
still requires the later recalculate, preview, and deploy actions.
