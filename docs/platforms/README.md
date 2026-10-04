# Platform documentation

This directory holds durable, platform-specific behavior that should survive
individual implementation sprints.

Create a platform document when support is sufficiently stable to describe
things such as:

- supported EVE templates and known-good images;
- console and first-boot behavior;
- initialization/bootstrap rules;
- configuration-save semantics;
- validation capabilities;
- backup/restore behavior;
- operator-access discovery such as SecureCRT support;
- known image/version quirks; and
- live-tested limitations.

Do not copy chronological troubleshooting logs here. Reusable conclusions
graduate here from `docs/lessons/README.md`; the lessons file retains the
historical record of how they were discovered.

Keep platform-specific behavior out of generic engine modules unless the code is
implemented through an explicit platform adapter.

Current platform notes:

- [Catalyst 9000v UADP](cat9kv-uadp.md)
- [NX-OS / Nexus 9000v](nxos.md)

- [IOS and IOS-XE route-based IPsec](iosxe-ipsec.md)
- [Nexus Dashboard / Fabric Controller](nexus-dashboard.md)

- [NX-OSv management bootstrap](nxosv-management-bootstrap.md): active-image preflight and repeatable management configuration.
