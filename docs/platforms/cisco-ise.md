# Cisco ISE standalone first boot

## Release and evidence scope

Cisco ISE 3.4.0.608 first-boot setup was field validated on an EVE QEMU guest
with 8 vCPU, 32 GiB RAM and one NIC. This proves the observed setup sequence,
not a completed ISE platform adapter or application/service acceptance.
Environment addressing, credentials and runtime evidence belong in the private
workspace. Retain the generic EVE CPU Limit policy (`cpulimit=0`).

## Setup prerequisites

The VGA console offers `setup` at the initial login prompt. Setup collects the
hostname, static first-interface address and mask, gateway, optional IPv6,
domain, DNS servers, NTP servers, timezone, SSH choice and administrator
credentials. Supply credentials through ignored runtime storage; never include
them in checked-in setup artifacts or process arguments.

ISE validates gateway and nameserver reachability, VM disk I/O and NTP before
application installation. A failed nameserver ping can be declined; that does
not prove DNS resolution. A failed NTP check offers a supported retry and a new
NTP-server prompt. Field validation succeeded using a reachable established
internal server IP after the public hostname failed. Do not bypass failed time
synchronization: the console warns that incorrect time can render the system
unusable. Correlate the retry with actual NTP request/reply and the successful
setup result.

`Setup executed successfully` followed by `Installing Applications` is an
installation checkpoint, not application readiness. Qualify installed version,
`show application`, `show application status ise`, interface addressing,
gateway, DNS resolution, NTP/time and standalone HTTPS readiness afterward.
Controller integration is a separate dependency and acceptance boundary.

Source: [Cisco ISE 3.4 installation and setup guide](https://www.cisco.com/c/en/us/td/docs/security/ise/3-4/install_guide/b_ise_installationGuide34/b_ise_InstallationGuide_chapter_3.html).
