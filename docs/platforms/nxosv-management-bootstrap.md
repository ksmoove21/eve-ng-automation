# NX-OSv 10.5(2) management and boot-image bootstrap in EVE

The EVE topology selects the running NX-OS image. The NX-OS bootstrap YAML
also declares `boot_image`; the initializer first checks `show version` for
that exact image. A mismatch stops before configuration.

NX-OSv may take about a minute to answer `boot nxos bootflash:<image>`. An
earlier initializer sent this command before the management default route and
first save, so a console timeout left the management bootstrap incomplete.
The initializer now applies and saves the declared hostname, management
address, and default route first, then reads them back from startup-config.

After that management gate, it checks the `boot nxos bootflash:` line in both
running and startup configuration. Two exact matches are left alone. A different saved boot image stops for review.
If either line is absent, the initializer sends the declared boot command once
with a bounded 120-second wait, saves, and verifies both the boot line and
management settings in startup-config. A boot-command timeout still leaves
the already verified management configuration saved; it does not claim boot
persistence.

`show boot variables` was empty on this image even when startup-config held
the correct boot line, so it is not the idempotence check. NDFC config-save
requires the boot variable on imported NX-OS 10.5.2 switches; saved
startup-config and a later successful reload are the relevant proof gates.

On the installed NX-OSv 10.5(2) CLI, `show running-config | include boot nxos`
returns `% Invalid command at '^' marker` because the unquoted multiword
filter is rejected. The initializer reads `show running-config` and parses the
exact boot line locally instead; it never treats a rejected show command as
proof that the boot variable is absent.
