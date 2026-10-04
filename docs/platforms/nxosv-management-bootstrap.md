# NX-OSv 10.5(2) management bootstrap in EVE

The EVE topology selects the NX-OS boot image. The NX-OS bootstrap YAML keeps
`boot_image` as an exact-image assertion. Before configuring the switch, the
console disables paging and checks `show version` for that running image.

Do not send `boot nxos bootflash:<image>` during repeatable management
bootstrap. On the DC2 N9K-C9500v spines running `nxos64-cs-lite.10.5.2.F.bin`,
that configuration command stalled the console for about a minute. On a fresh
Spine-4 run it prevented the management default route and config save from
executing, while `show version` already reported the declared active image.
`show boot variables` showed an empty NX-OS value even where Spine-3's saved
startup configuration contained a matching boot line. It is therefore not a
reliable idempotence check for this image in this lab.

The reusable initializer validates the active image, applies only hostname and
management configuration, saves, then reads back the saved hostname, address,
and default route. Boot-variable persistence is outside this management gate;
no reboot-persistence claim follows from a successful bootstrap.