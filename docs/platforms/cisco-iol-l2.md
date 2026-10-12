# Cisco IOL-L2 management forwarding

Cisco describes IOL-L2 as a Layer-2 switch image with Layer-3 control-plane and
data-plane support. Its reference-platform feature tests include SVIs and routed
ports; programmability support differs from full IOS-XE virtual machines.

## Observed on IOL XE L2 17.16.01a

With `no ip routing`, a management SVI and `ip default-gateway` configured, the
same-subnet gateway answered ICMP. Off-subnet sourced and unsourced probes failed,
created incomplete ARP entries for the remote destinations, and emitted no remote
ICMP toward the gateway in a correlated passive capture.

Enabling `ip routing` and an IPv4 default route through the management gateway
restored both off-subnet destinations. Running and saved startup configuration
retained one IP-addressed management SVI; data ports and their service VLAN stayed
Layer 2. This is a field observation for the exact image, not a claim that all
IOL-L2 releases require this arrangement.

```text
ip routing
interface Vlan10
 ip address 192.0.2.10 255.255.255.0
 exit
ip route 0.0.0.0 0.0.0.0 192.0.2.1
```

IOS can omit enabled `ip routing` from configuration output because it is the
default. Verify the active default route, next hop, absence of `no ip routing`,
saved startup state and sourced off-subnet probes; do not require an explicit
`ip routing` line as the sole proof. Do not add IP interfaces to switched service
VLANs merely to repair the device's own management reachability.

Generic IOS initialization uses `configs/<node>-init.cfg`; supplemental source
profiles alone are not automatically selected by that filename convention.
Runtime credentials remain outside checked-in command files.

Source: [Cisco IOL-L2 reference platform](https://developer.cisco.com/docs/modeling-labs/iol-l2/).
