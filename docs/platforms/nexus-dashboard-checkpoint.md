# Nexus Dashboard active sprint checkpoint

- **Current lifecycle state:** Clean-cycle-1 post-Cluster-Bringup convergence failure: the guest is powered on, QEMU storage is healthy, but the guest does not answer management TCP. A normal stop/start of only disposable `ND-01` is owner-authorized and pending.
- **Git/working-tree state:** At capture: branch `automation/nexus-dashboard-platform`, commit `aa97d8f`, clean worktree.
- **Proven automation behavior:** Selected-satellite image preflight; serial first boot; documented browser Cluster Bringup; post-cluster external service-IP API reconciliation; Fabric Controller LAN/Advanced Service Setup; DATA device-management selection; documented empty-fabrics API read; normal reusable-init idempotence on the earlier healthy appliance.
- **Remaining acceptance gates:** Verify the authorized normal restart preserves configuration and restores documented service readiness; run normal reusable initialization and idempotence; then prove two independent clean deploy-to-validation cycles starting from genuinely uninitialized appliances. No fabric creation.
- **Exact next action:** Use this worktree's EVE CLI to stop `ND-01`, verify QEMU stops, then start it and begin bounded lifecycle-aware readiness polling.
