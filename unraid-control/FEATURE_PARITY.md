# Feature parity register

This register defines completion. A visible navigation item or native WebUI
shortcut is not feature parity. API operations are independently authored;
upstream source is not copied. Status reflects implementation and verification,
not design intent. Every unsupported workflow remains in the native WebUI.

| Unraid area | Implemented in this branch | Remaining for native parity |
|---|---|---|
| Dashboard | Hardware info, CPU/memory, array capacity, workload state, unread alerts | UPS, network throughput, sensors, durable charts, customization |
| Main / storage | Array/cache/parity/boot inventory, state, size, errors, temperature; confirmed array/parity controls | Disk assignment, encrypted unlock, spin control, detailed pool/ZFS, boot mirroring, SMART, filesystem checks/repair/format, Mover |
| Shares | Inventory, usage, allocation and disk filters | Create/edit/delete, primary/secondary storage, Mover direction, SMB/NFS/security, permissions, browse files |
| Users | Native WebUI access | SMB users, permissions, credentials, identity management |
| Docker | Inventory, autostart display, supplied WebUI links; start/stop/restart/pause/unpause | Install/edit templates, networks/volumes, autostart editing, updates/rollback, logs/console, resource limits and CPU pinning |
| VMs | Inventory; start/stop/reboot/pause/resume | Create/edit, CPU/memory/vDisk, PCI/USB/GPU passthrough, snapshots, VNC/SPICE console, XML editing |
| Network | Interface/link/address inventory | DHCP/static addressing, bonding/bridging/VLAN, DNS, routes, WireGuard and Tailscale |
| Settings | This app's connection/access/controls/title/Hub link | Unraid system/services/display/notification settings, schedules, UPS and power policy |
| Notifications | Unread inventory and individual archive | Archive filters, notification channels, rules and acknowledgement history |
| Plugins / Apps | API-module inventory and native WebUI access | Full .plg inventory, install/update/remove, CA search/install, supply-chain metadata |
| Tools | Native shortcuts and coverage register | OS upgrades/rollback, diagnostics export, syslog, permissions, terminal, file manager, power actions |
| Homelab additions | Service tiles/icons/groups, optional login, original workspace, audit trail | Connector integration cards, branding upload, Zigbee/MQTT objects, occupancy hold timers, solar/time filters, PostgreSQL history |

## Engineering acceptance

1. Each native workflow must have documented API/host contracts for 7.2.3.
   Schema discovery determines supported fields; permissions determine access.
2. Unsupported host workflows require an explicitly scoped companion plugin,
   not browser scraping, hidden PHP endpoints or general SSH/shell execution.
   The companion's distribution and privilege boundary are not built yet.
3. Writes require validation, state preconditions, clear effect previews,
   confirmation, activity recording, and verification from fresh host state.
4. Data operations need failure/recovery checks on a disposable test server;
   UI mocks cannot verify storage correctness or justify a perfection claim.
5. Measure request latency/load and disk sleep behavior before claiming an
   optimization over the native WebUI. This branch reduces repeated reads via
   caching/single-flight, but comparative benchmarks have not been performed.
6. Mark a feature complete only when the native workflow works end-to-end,
   including permission errors, outages, cancellation, and restart recovery.

## Verification as of this preview

Local contract tests and browser checks exercise configuration, secret
preservation, section containment, supported-field selection, confirmation
expiry/replay, service tiles, routing and mobile overflow. Live server
validation and the remaining native workflows are still outstanding.
