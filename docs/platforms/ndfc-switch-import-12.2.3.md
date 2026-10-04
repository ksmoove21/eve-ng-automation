# NDFC 12.2.3 switch import boundary

Cisco's [12.2.2/12.2.3 LAN switch guide](https://www.cisco.com/c/en/us/td/docs/dcn/ndfc/1222/articles/ndfc-add-switches-lan/add-switches-for-lan-operational-mode.html)
describes **Manage > Inventory > Switches > Actions > Add Switches**. Choose
the fabric, discover the management addresses, inspect identity and
manageability, add the selected devices, then assign roles. Form the intended
vPC/ToR pairs before recalculation and deployment so generated settings reach
the switches.

The reusable `ndfc_switches` command currently performs only the discovery
preflight. It sends `POST /lan-fabric/rest/control/fabrics/{fabricName}/inventory/test-reachability`
with the declared seed IPs and `preserveConfig: false`, then checks returned IP,
hostname, serial, and manageability flags. That response is not evidence of
import, role assignment, or device configuration.

The installed 12.2.3 API request and readback for **Import Selected Switches**
and role assignment must be captured before adding a reusable mutation path.
The existing preflight must remain read-only until that mapping and a
post-import identity/role check are proven. A switch must not be reported as
managed merely because reachability succeeded.
